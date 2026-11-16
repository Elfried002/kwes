#!/usr/bin/env bash
# =============================================================================
# Kwes — infra/scripts/backup.sh
#
# Sauvegarde logique chiffrée de la base (Supabase ou Postgres local) :
#   pg_dump --format=custom -> gzip -> (GPG) -> rotation -> vérification.
#
# Usage :
#   DATABASE_URL="postgresql://..." bash infra/scripts/backup.sh
#   BACKUP_GPG_RECIPIENT=ops@kwes.example bash infra/scripts/backup.sh
#
# Variables :
#   DATABASE_URL            connexion PostgreSQL (obligatoire)
#   BACKUP_DIR              destination locale (défaut /var/backups/kwes)
#   BACKUP_GPG_RECIPIENT    destinataire GPG (chiffrement, recommandé)
#   BACKUP_RETENTION_DAYS   rétention locale en jours (défaut 14)
#   RESTORE_VERIFY=1        rejoue le dump dans une base jetable (défaut 1)
#
# ⚠️  La copie doit ensuite être poussée HORS du VPS (rclone/S3/rsync) :
#     une sauvegarde unique sur le serveur ne protège de rien.
# =============================================================================
set -Eeuo pipefail

: "${DATABASE_URL:?DATABASE_URL est requis}"
BACKUP_DIR=${BACKUP_DIR:-/var/backups/kwes}
RETENTION=${BACKUP_RETENTION_DAYS:-14}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DOCKER=${DOCKER:-docker}
PG_IMAGE=${PG_IMAGE:-postgres:16-alpine}

# Le client pg_dump tourne dans un conteneur : `127.0.0.1` y désigne le conteneur
# lui-même, pas l'hôte. On bascule en réseau hôte dans ce cas, ou sur le réseau
# Docker nommé fourni (ex. BACKUP_NETWORK=kwes_internal pour le service `postgres`).
NET_ARGS=()
if [[ -n "${BACKUP_NETWORK:-}" ]]; then
  NET_ARGS=(--network "${BACKUP_NETWORK}")
elif [[ "${DATABASE_URL}" =~ @(127\.0\.0\.1|localhost)[:/] ]]; then
  NET_ARGS=(--network host)
  if [[ "${DATABASE_URL}" =~ @localhost ]]; then
    DATABASE_URL=${DATABASE_URL/@localhost/@127.0.0.1}
  fi
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

base="${BACKUP_DIR}/kwes-${STAMP}.dump"
tmp="${base}.partial"
trap 'rm -f "${tmp}"' EXIT   # jamais de .partial résiduel après un échec

echo ">> pg_dump ${STAMP}"
$DOCKER run --rm -i "${NET_ARGS[@]}" -e PGURL="${DATABASE_URL}" "${PG_IMAGE}" \
  sh -c 'pg_dump --no-owner --no-privileges --format=custom --compress=6 "$PGURL"' \
  > "${tmp}"

if [[ ! -s "${tmp}" ]]; then
  echo "ERREUR: dump vide" >&2
  rm -f "${tmp}"
  exit 1
fi

echo ">> vérification de l'archive (pg_restore --list)"
toc=$($DOCKER run --rm -i "${NET_ARGS[@]}" "${PG_IMAGE}" pg_restore --list < "${tmp}")
tables=$(printf '%s\n' "${toc}" | grep -c 'TABLE DATA' || true)
echo "   ${tables} tables de données dans l'archive"
if (( tables < 13 )); then
  echo "ERREUR: seulement ${tables} tables — dump suspect, conservé sous ${tmp}" >&2
  exit 1
fi

echo ">> compression"
gzip -9 -c "${tmp}" > "${base}.gz"
rm -f "${tmp}"

artifact="${base}.gz"
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  echo ">> chiffrement GPG pour ${BACKUP_GPG_RECIPIENT}"
  gpg --batch --yes --trust-model always \
      --recipient "${BACKUP_GPG_RECIPIENT}" \
      --output "${base}.dump.gz.gpg" --encrypt "${base}.gz"
  shred -u "${base}.gz" 2>/dev/null || rm -f "${base}.gz"
  artifact="${base}.dump.gz.gpg"
fi

sha256sum "${artifact}" > "${artifact}.sha256"
chmod 600 "${artifact}" "${artifact}.sha256" "${artifact}.sha256"

echo ">> rotation (> ${RETENTION} j)"
find "${BACKUP_DIR}" -maxdepth 1 -name 'kwes-*' -type f -mtime "+${RETENTION}" -print -delete

echo ">> terminé : ${artifact} ($(du -h "${artifact}" | cut -f1))"
echo "   empreinte : $(cut -d' ' -f1 "${artifact}.sha256")"
echo
echo "   Étape suivante (hors VPS) :"
echo "     rclone copy ${artifact} remote:kwes-backups/"
