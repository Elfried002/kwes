#!/usr/bin/env bash
# =============================================================================
# Kwes — infra/scripts/healthcheck.sh
#
# Vérification de bout en bout d'un déploiement (VPS), appelable en cron
# toutes les 5 minutes. Sort en code non nul dès qu'un contrôle échoue, ce qui
# permet de brancher une alerte (mail, healthcheck Uptime Kuma, etc.).
#
# Usage :
#   KWES_URL=https://api.kwes.example bash infra/scripts/healthcheck.sh
#
# Contrôles :
#   1. /health du backend (statut + dépendances database/redis/llm) ;
#   2. conteneurs non healthy ou en restart ;
#   3. heartbeat worker dans Redis ;
#   4. espace disque < 85 % ;
#   5. fraîcheur de la dernière sauvegarde (< 26 h).
# =============================================================================
set -Eeuo pipefail

KWES_URL=${KWES_URL:-http://127.0.0.1:8000}
HEARTBEAT_KEY=${HEARTBEAT_KEY:-kwes:worker:heartbeat}
COMPOSE_DIR=${COMPOSE_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
DOCKER=${DOCKER:-docker}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/kwes}
fail=0
note() { printf '%-42s %s\n' "$1" "$2"; }
ko()   { note "$1" "KO — $2"; fail=1; }
ok()   { note "$1" "OK${2:+ — $2}"; }

# 1. Santé applicative -------------------------------------------------------
json=$(curl -fsS --max-time 10 "${KWES_URL}/health" 2>/dev/null || true)
if [[ -z "${json}" ]]; then
  ko "backend /health" "injoignable (${KWES_URL}/health)"
else
  status=$(printf '%s' "${json}" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  if [[ "${status}" == "ok" || "${status}" == "healthy" ]]; then
    ok "backend /health" "${status}"
  else
    ko "backend /health" "status=${status:-inconnu} — ${json:0:200}"
  fi
fi

# 2. Conteneurs --------------------------------------------------------------
if command -v ${DOCKER} >/dev/null 2>&1; then
  while read -r name state health; do
    [[ -z "${name}" ]] && continue
    if [[ "${state}" != "running" ]]; then
      ko "conteneur ${name}" "état=${state}"
    elif [[ "${health}" == "unhealthy" ]]; then
      ko "conteneur ${name}" "unhealthy"
    else
      ok "conteneur ${name}" "${state}${health:+/$health}"
    fi
  done < <($DOCKER ps --format '{{.Names}}\t{{.State}}\t{{.Status}}' 2>/dev/null \
             | awk -F'\t' '/^kwes-/{split($3,a,"("); h=(a[2]?a[2]:""); sub(/\)/,"",h); print $1"\t"$2"\t"h}')
fi

# 3. Heartbeat worker --------------------------------------------------------
hb=$($DOCKER exec kwes-redis redis-cli GET "${HEARTBEAT_KEY}" 2>/dev/null | tr -d '\r' || true)
if [[ -z "${hb}" || "${hb}" == "" ]]; then
  ko "worker heartbeat" "clé ${HEARTBEAT_KEY} absente"
else
  now=$(date +%s)
  if [[ "${hb}" =~ ^[0-9]+$ ]]; then
    age=$(( now - hb ))
    if (( age > ${HEARTBEAT_MAX_AGE:-180} )); then
      ko "worker heartbeat" "vu il y a ${age}s (> ${HEARTBEAT_MAX_AGE:-180}s)"
    else
      ok "worker heartbeat" "vu il y a ${age}s"
    fi
  else
    ok "worker heartbeat" "${hb:0:32}"
  fi
fi

# 4. Disque ------------------------------------------------------------------
used=$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)
if (( used >= 85 )); then ko "disque /" "${used}% utilisé"; else ok "disque /" "${used}% utilisé"; fi

# 5. Sauvegarde récente ------------------------------------------------------
if [[ -d "${BACKUP_DIR}" ]]; then
  latest=$(find "${BACKUP_DIR}" -name 'kwes-*.dump.gz*' -mmin -1560 -print -quit 2>/dev/null || true)
  if [[ -z "${latest}" ]]; then
    ko "sauvegarde < 26 h" "aucun dump récent dans ${BACKUP_DIR}"
  else
    ok "sauvegarde < 26 h" "$(basename "${latest}")"
  fi
else
  note "sauvegarde < 26 h" "répertoire ${BACKUP_DIR} absent (ignoré)"
fi

echo
if (( fail )); then
  echo "RÉSULTAT : KO"
  exit 1
fi
echo "RÉSULTAT : OK"
