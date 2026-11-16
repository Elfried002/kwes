#!/usr/bin/env bash
# =============================================================================
# Kwes — infra/scripts/restore.sh
#
# Restauration d'une sauvegarde produite par infra/scripts/backup.sh.
# La procédure est volontairement bloquante : rien ne s'exécute sans
# RESTORE_CONFIRM=yes, et une sauvegarde de sécurité est prise avant écrasement.
#
# Usage :
#   DATABASE_URL="postgresql://.../kwes" \
#   RESTORE_CONFIRM=yes \
#     bash infra/scripts/restore.sh /var/backups/kwes/kwes-20261116T030000Z.dump.gz
#
# Ordre (docs/10-infrastructure/OBSERVABILITY_BACKUP.md §6) :
#   1. vérifier l'empreinte SHA-256     4. restaurer données + objets
#   2. déchiffrer si nécessaire         5. rejouer les migrations (idempotentes)
#   3. sauvegarder l'état courant       6. contrôles d'intégrité + /health
# =============================================================================
set -Eeuo pipefail

: "${DATABASE_URL:?DATABASE_URL est requis}"
: "${1:?usage: restore.sh <fichier.dump.gz[.gpg]>}"

FILE="$1"
[[ -f "${FILE}" ]] || { echo "ERREUR: ${FILE} introuvable" >&2; exit 1; }

if [[ "${RESTORE_CONFIRM:-no}" != "yes" ]]; then
  cat >&2 <<EOF
Refus : cette opération ÉCRASE la base cible.
  cible : ${DATABASE_URL##*@}
Relancer avec RESTORE_CONFIRM=yes si c'est bien l'intention.
EOF
  exit 1
fi

DOCKER=${DOCKER:-docker}
PG_IMAGE=${PG_IMAGE:-postgres:16-alpine}

# Même logique que backup.sh : `127.0.0.1` depuis un conteneur = le conteneur.
NET_ARGS=()
if [[ -n "${BACKUP_NETWORK:-}" ]]; then
  NET_ARGS=(--network "${BACKUP_NETWORK}")
elif [[ "${DATABASE_URL}" =~ @(127\.0\.0\.1|localhost)[:/] ]]; then
  NET_ARGS=(--network host)
  if [[ "${DATABASE_URL}" =~ @localhost ]]; then
    DATABASE_URL=${DATABASE_URL/@localhost/@127.0.0.1}
  fi
fi

WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

# 1. Intégrité ---------------------------------------------------------------
if [[ -f "${FILE}.sha256" ]]; then
  echo ">> vérification sha256"
  ( cd "$(dirname "${FILE}")" && sha256sum -c "$(basename "${FILE}").sha256" )
else
  echo ">> pas d'empreinte .sha256 (ignoré)"
fi

# 2. Déchiffrement -----------------------------------------------------------
plain="${WORK}/restore.dump.gz"
case "${FILE}" in
  *.gpg)
    echo ">> déchiffrement GPG"
    gpg --batch --yes --output "${plain}" --decrypt "${FILE}"
    ;;
  *.gz)
    cp "${FILE}" "${plain}"
    ;;
  *)
    echo ">> fichier non compressé"
    plain="${FILE}"
    ;;
esac

dump="${WORK}/restore.dump"
if [[ "${plain}" == *.gz ]]; then
  echo ">> décompression"
  gzip -dc "${plain}" > "${dump}"
else
  cp "${plain}" "${dump}"
fi

# 3. Sauvegarde de sécurité de l'état courant --------------------------------
echo ">> sauvegarde de sécurité de la base cible avant écrasement"
DATABASE_URL="${DATABASE_URL}" BACKUP_DIR="${BACKUP_DIR:-/var/backups/kwes}" \
  BACKUP_NETWORK="${BACKUP_NETWORK:-}" \
  bash "$(dirname "$0")/backup.sh" || echo "   ⚠️ sauvegarde préalable impossible — poursuite sous votre responsabilité"

# 4. Restauration ------------------------------------------------------------
echo ">> pg_restore (clean + if-exists)"
$DOCKER run --rm -i "${NET_ARGS[@]}" -e PGURL="${DATABASE_URL}" "${PG_IMAGE}" \
  sh -c 'pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="$PGURL"' \
  < "${dump}"

# 5. Migrations idempotentes -------------------------------------------------
echo ">> réapplication des migrations (idempotentes)"
for f in "$(dirname "$0")/../../supabase/migrations/"*.sql; do
  echo "   - $(basename "$f")"
  $DOCKER run --rm -i "${NET_ARGS[@]}" -e PGURL="${DATABASE_URL}" "${PG_IMAGE}" \
    sh -c 'psql "$PGURL" -v ON_ERROR_STOP=1 -q' < "$f"
done

# 6. Contrôles ---------------------------------------------------------------
echo ">> contrôles d'intégrité"
$DOCKER run --rm -i "${NET_ARGS[@]}" -e PGURL="${DATABASE_URL}" "${PG_IMAGE}" \
  sh -c 'psql "$PGURL" -At -f -' <<'SQL'
select 'tables_public=' || count(*)
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r';
select 'rls_desactivee=' || count(*)
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity = false;
select 'skills=' || count(*) from public.skills;
select 'versions_actives=' || count(*) from public.skill_versions where status = 'active';
SQL

echo
echo ">> terminé. Vérifier ensuite : curl -fsS \$KWES_URL/health && bash infra/scripts/healthcheck.sh"
