#!/usr/bin/env bash
# =============================================================================
# Kwes — infra/scripts/bootstrap_tls.sh
#
# 1. Génère un certificat auto-signé (90 j) pour que Nginx démarre sans erreur
#    avant l'émission du certificat réel.
# 2. Émet ensuite le certificat Let's Encrypt via HTTP-01 (webroot).
#
# Usage :
#   KWES_DOMAIN=api.kwes.example LETSENCRYPT_EMAIL=ops@kwes.example \
#     bash infra/scripts/bootstrap_tls.sh [--self-signed-only]
#
# Prérequis : DNS du domaine pointant déjà sur le VPS, ports 80/443 ouverts.
# =============================================================================
set -Eeuo pipefail

DOMAIN=${KWES_DOMAIN:-${1:-}}
EMAIL=${LETSENCRYPT_EMAIL:-}
DOCKER=${DOCKER:-docker}
PROJECT=${COMPOSE_PROJECT_NAME:-kwes}

if [[ -z "${DOMAIN}" ]]; then
  echo "ERREUR: KWES_DOMAIN non défini (ex. KWES_DOMAIN=api.kwes.example)." >&2
  exit 1
fi

CERT_VOL="${PROJECT}_nginx_certs"
ACME_VOL="${PROJECT}_nginx_acme"

echo ">> certificat auto-signé pour ${DOMAIN} (volume ${CERT_VOL})"
$DOCKER run --rm -v "${CERT_VOL}:/certs" alpine:3.20 sh -c "
  set -e
  apk add --no-cache openssl >/dev/null
  mkdir -p /certs/live/${DOMAIN}
  openssl req -x509 -nodes -newkey rsa:2048 -days 90 \
    -keyout /certs/live/${DOMAIN}/privkey.pem \
    -out    /certs/live/${DOMAIN}/fullchain.pem \
    -subj '/CN=${DOMAIN}' >/dev/null 2>&1
  chmod 600 /certs/live/${DOMAIN}/privkey.pem
  echo '   ok'
"

if [[ "${1:-}" == "--self-signed-only" ]]; then
  echo ">> terminé (auto-signé uniquement). Démarrer : docker compose up -d proxy"
  exit 0
fi

if [[ -z "${EMAIL}" ]]; then
  echo "ERREUR: LETSENCRYPT_EMAIL non défini." >&2
  exit 1
fi

echo ">> démarrage du proxy pour servir le challenge ACME"
$DOCKER compose -f "$(dirname "$0")/../docker-compose.yml" up -d proxy

echo ">> émission Let's Encrypt pour ${DOMAIN}"
$DOCKER run --rm \
  -v "${CERT_VOL}:/etc/letsencrypt" \
  -v "${ACME_VOL}:/var/www/certbot" \
  certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    -d "${DOMAIN}" \
    --email "${EMAIL}" --agree-tos --no-eff-email -n

echo ">> rechargement de Nginx"
$DOCKER compose -f "$(dirname "$0")/../docker-compose.yml" exec proxy nginx -s reload

echo ">> renouvellement automatique : ajouter au crontab du VPS"
echo "   17 3 * * * cd /opt/kwes/infra && docker compose run --rm --entrypoint certbot proxy renew --quiet && docker compose exec proxy nginx -s reload"
