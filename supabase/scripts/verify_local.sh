#!/usr/bin/env bash
# =============================================================================
# Kwes — supabase/scripts/verify_local.sh
#
# Applique les migrations sur une base PostgreSQL JETABLE (Docker, image
# pgvector/pgvector:pg16) puis exécute les contrôles et les tests RLS.
# Rien n'est écrit hors du conteneur éphémère, qui est supprimé à la fin.
#
# Usage :
#   bash supabase/scripts/verify_local.sh              # docker direct
#   DOCKER="sudo docker" bash supabase/scripts/verify_local.sh
#
# Variables :
#   PORT       port hôte du PostgreSQL jetable (défaut 55432)
#   KEEP=1     conserve le conteneur (debug)
# =============================================================================
set -Eeuo pipefail

DOCKER=${DOCKER:-docker}
PORT=${PORT:-55432}
IMAGE=${IMAGE:-pgvector/pgvector:pg16}
NAME="kwes-migtest-$$"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PW="kwes_test_pw"

cleanup() {
  if [[ "${KEEP:-0}" == "1" ]]; then
    echo ">> conteneur conservé : $NAME (port $PORT, mot de passe $PW)"
    return
  fi
  $DOCKER rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo ">> démarrage de $IMAGE ($NAME) sur 127.0.0.1:$PORT"
$DOCKER run -d --name "$NAME" \
  -e POSTGRES_PASSWORD="$PW" -e POSTGRES_USER=kwes -e POSTGRES_DB=kwes \
  -p "127.0.0.1:$PORT:5432" "$IMAGE" >/dev/null

echo -n ">> attente de PostgreSQL"
for i in $(seq 1 60); do
  if $DOCKER exec "$NAME" pg_isready -U kwes -d kwes >/dev/null 2>&1; then
    echo " prêt (${i}s)"; break
  fi
  echo -n "."; sleep 1
  if [[ $i -eq 60 ]]; then echo " TIMEOUT"; exit 1; fi
done

# Découpage volontaire : DOCKER peut valoir "sudo docker" (deux mots).
# shellcheck disable=SC2206
PSQL=($DOCKER exec -i "$NAME" psql -U kwes -d kwes -v ON_ERROR_STOP=1 -q)

echo ">> 0000 shim auth local (Supabase fournit auth.uid() nativement)"
"${PSQL[@]}" -f - < "$ROOT/supabase/local/0000_local_auth_shim.sql" >/dev/null

echo ">> 0001_init.sql"
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0001_init.sql"

echo ">> 0002_rls.sql"
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0002_rls.sql"

echo ">> 0003_seed_skills.sql"
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0003_seed_skills.sql"

echo ""
echo ">> idempotence : réapplication de 0001/0002/0003"
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0001_init.sql" >/dev/null
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0002_rls.sql" >/dev/null
"${PSQL[@]}" -f - < "$ROOT/supabase/migrations/0003_seed_skills.sql" >/dev/null
echo "   OK — réexécution sans erreur"

echo ""
echo ">> contrôles post-migration"
"${PSQL[@]}" -f - < "$ROOT/supabase/scripts/checks.sql"

echo ""
echo ">> tests fonctionnels RLS"
"${PSQL[@]}" -f - < "$ROOT/supabase/tests/rls_test.sql"

echo ""
echo "=== VÉRIFICATION COMPLÈTE : OK ==="
