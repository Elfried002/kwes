# Kwes — infrastructure (VPS, Docker, sauvegarde, observabilité)

Déploiement de l'API, du worker, de Redis et du reverse proxy sur un VPS
Ubuntu 24.04 (4 vCPU / 8 Go / 100 Go NVMe). Le frontend vit sur Vercel
([`docs/deploiement_vercel.md`](../docs/deploiement_vercel.md)) et la base sur
Supabase managé ([`supabase/README.md`](../supabase/README.md)).

## 1. Architecture

```
             Internet
                │  80/443
        ┌───────▼────────┐
        │  proxy (nginx) │  TLS, rate limit, WS upgrade, logs JSON
        └───────┬────────┘
                │ réseau `edge`
   ┌────────────┴─────────────┐
   │                          │
┌──▼─────────┐         ┌──────▼───────┐
│ backend    │         │ worker       │  même image, commande différente
│ (uvicorn)  │         │ (asyncio)    │
└──┬──────┬──┘         └──────┬───────┘
   │      │ réseau `internal` │  (aucune sortie Internet)
   │   ┌──▼──────┐            │
   │   │ redis 7 │◄───────────┘
   │   └─────────┘
   │
   │ (profil `local` uniquement)
┌──▼──────────────┐        ┌──────────────────┐
│ postgres 16     │        │ Supabase managé  │  ← production Alpha
│ + pgvector      │        └──────────────────┘
└─────────────────┘
```

Fichiers :

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | 5 services, healthchecks, volumes nommés, réseaux |
| `backend.Dockerfile` | image API **et** worker, multi-stage, non-root (UID 10001) |
| `frontend.Dockerfile` | optionnel : PWA servie depuis le VPS |
| `nginx/kwes.conf` | TLS, en-têtes, streaming SSE, WebSocket, rate limit |
| `nginx/00-zones.conf` | zones de rate limit, `log_format` JSON, gzip |
| `caddy/Caddyfile` | alternative à Nginx (TLS automatique) |
| `scripts/bootstrap_tls.sh` | certificat auto-signé puis Let's Encrypt |
| `scripts/healthcheck.sh` | sonde de bout en bout (cron/alerte) |
| `scripts/backup.sh` | dump chiffré + vérification + rotation |
| `scripts/restore.sh` | restauration guidée avec garde-fou |

## 2. Préparation du VPS (une fois)

```bash
# 2.1 Système à jour
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades

# 2.2 Utilisateur non-root
sudo adduser --disabled-password --gecos "" kwes
sudo usermod -aG sudo kwes
sudo rsync -a ~/.ssh /home/kwes/ && sudo chown -R kwes:kwes /home/kwes/.ssh

# 2.3 SSH par clé uniquement (après avoir validé la connexion !)
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/'            /etc/ssh/sshd_config
sudo systemctl restart ssh

# 2.4 Firewall : SSH restreint + HTTP/HTTPS
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <VOTRE_IP> to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 2.5 Mises à jour de sécurité automatiques
sudo dpkg-reconfigure --priority=low unattended-upgrades

# 2.6 Docker Engine + Compose (dépôt officiel)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu noble stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker kwes

# 2.7 Répertoires de données, permissions minimales
sudo mkdir -p /opt/kwes /var/backups/kwes
sudo chown kwes:kwes /opt/kwes /var/backups/kwes
sudo chmod 750 /opt/kwes /var/backups/kwes
```

## 3. Déploiement applicatif

```bash
# 3.1 Version taguée (jamais une branche flottante en prod)
cd /opt/kwes
git clone https://github.com/<org>/kwes.git .
git checkout v0.1.0-alpha

# 3.2 Configuration
cp .env.example .env
chmod 600 .env
$EDITOR .env      # renseigner DATABASE_URL (Supabase), REDIS_URL, secrets,
                  # KWES_DOMAIN, CORS_ORIGINS, DEEPSEEK_API_KEY...
                  # CONTAINER_DATABASE_URL = DATABASE_URL avec host `postgres`
                  #   (uniquement si vous utilisez le profil local)

# 3.3 Validation de la configuration (échoue tôt si une var manque)
docker compose -f infra/docker-compose.yml config -q

# 3.4 TLS
KWES_DOMAIN=api.kwes.example LETSENCRYPT_EMAIL=ops@kwes.example \
  bash infra/scripts/bootstrap_tls.sh

# 3.5 Migrations (idempotentes, transactionnelles)
for f in supabase/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
psql "$DATABASE_URL" -f supabase/scripts/checks.sql   # 13 tables, RLS partout

# 3.6 Démarrage
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps

# 3.7 Vérifications
curl -fsS https://api.kwes.example/health | jq .
bash infra/scripts/healthcheck.sh
```

### Mode local complet (PostgreSQL dans Docker)

```bash
docker compose -f infra/docker-compose.yml --profile local up -d --build
```

Le conteneur `postgres` applique automatiquement, au premier démarrage du
volume, le shim `auth` puis `0001`/`0002`/`0003`.

### Ce que le compose garantit

- **aucun port publié** pour `postgres`, `redis`, `backend`, `worker` ;
  seul `proxy` expose `80` et `443` (`docker compose ps` le confirme) ;
- `postgres` et `redis` vivent sur le réseau `internal` (`internal: true`) :
  pas de sortie Internet, pas d'accès depuis l'hôte ;
- `backend` / `worker` tournent en **UID 10001**, `cap_drop: ALL`,
  `no-new-privileges`, `tini` en PID 1 (SIGTERM propre) ;
- healthchecks sur `postgres`, `redis`, `backend`, `proxy` ; `worker` publie un
  heartbeat dans Redis (pas de port HTTP à sonder) ;
- logs `json-file` plafonnés (10 Mo × 5) pour ne pas saturer le disque.

## 4. Mise à jour et rollback

```bash
cd /opt/kwes
git fetch --tags && git checkout v0.1.1-alpha

# sauvegarde AVANT toute migration destructive
DATABASE_URL="$DATABASE_URL" bash infra/scripts/backup.sh

for f in supabase/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done

KWES_VERSION=v0.1.1-alpha docker compose -f infra/docker-compose.yml up -d --build
curl -fsS https://api.kwes.example/health
```

Rollback applicatif : `git checkout v0.1.0-alpha` puis
`KWES_VERSION=v0.1.0-alpha docker compose ... up -d` (les migrations de l'Alpha
sont additives : le code N-1 reste compatible avec le schéma N).

Rollback base : voir [`supabase/README.md`](../supabase/README.md) §6.

## 5. Sauvegarde et restauration

```bash
# Sauvegarde (dump custom + gzip + GPG + rotation 14 j + vérification du TOC)
DATABASE_URL="$DATABASE_URL" \
BACKUP_GPG_RECIPIENT=ops@kwes.example \
  bash infra/scripts/backup.sh

# Copie hors du VPS — INDISPENSABLE : une sauvegarde sur le serveur ne protège de rien
rclone copy /var/backups/kwes/kwes-*.gpg remote:kwes-backups/

# Restauration (garde-fou : refuse sans RESTORE_CONFIRM=yes)
DATABASE_URL="$DATABASE_URL" RESTORE_CONFIRM=yes \
  bash infra/scripts/restore.sh /var/backups/kwes/kwes-20261116T030000Z.dump.gz.gpg
```

`backup.sh`/`restore.sh` font tourner `pg_dump`/`pg_restore` dans un conteneur
`postgres:16-alpine` : si `DATABASE_URL` pointe sur `127.0.0.1`, ils passent
automatiquement en `--network host` (sinon `127.0.0.1` désignerait le conteneur).
Pour sauvegarder le service compose `postgres`, utiliser
`BACKUP_NETWORK=kwes_internal DATABASE_URL=postgresql://kwes:...@postgres:5432/kwes`.

`restore.sh` enchaîne : vérification SHA-256 → déchiffrement → sauvegarde de
l'état courant → `pg_restore --clean --if-exists --exit-on-error` → réapplication
des migrations → contrôles (`tables_public`, `rls_desactivee`, `skills`,
`versions_actives`).

Cron recommandé sur le VPS :

```cron
# m  h  dom mon dow  commande
17   3  *   *   *    cd /opt/kwes && DATABASE_URL=$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2-) BACKUP_GPG_RECIPIENT=ops@kwes.example bash infra/scripts/backup.sh >> /var/log/kwes-backup.log 2>&1
*/5  *  *   *   *    cd /opt/kwes && KWES_URL=https://api.kwes.example bash infra/scripts/healthcheck.sh >> /var/log/kwes-health.log 2>&1 || mail -s "Kwes KO" ops@kwes.example < /var/log/kwes-health.log
23   4  *   *   *    cd /opt/kwes && docker compose -f infra/docker-compose.yml exec proxy nginx -s reload
```

Test de restauration à faire **une fois par mois** sur une base jetable (§6 de
`docs/10-infrastructure/OBSERVABILITY_BACKUP.md`) : une sauvegarde jamais
restaurée n'est pas une sauvegarde.

## 6. Observabilité

**Logs.** Le proxy écrit du JSON (`request_id`, statut, latence, upstream) ;
le backend écrit du JSON (`LOG_FORMAT=json`) avec `request_id`, `task_id`,
`user_id` pseudonymisé, `duration_ms`, `error_code`. Un `request_id` relie
requête HTTP → conversation → mission → étapes → appels outils.

```bash
docker compose -f infra/docker-compose.yml logs -f --tail=100 backend
docker compose -f infra/docker-compose.yml logs -f backend | jq -c 'select(.level=="error")'
docker stats --no-stream
```

**Métriques à surveiller** (cf. `OBSERVABILITY_BACKUP.md` §2) : CPU/RAM/disque,
latence et taux d'erreur API, état Redis, taille de file, durée des missions,
taux de succès des skills, erreurs DeepSeek/ElevenLabs, reconnexions WebSocket.

**Alertes** (`healthcheck.sh` couvre déjà 1, 3, 4 et 5) :

| Alerte | Détection |
|---|---|
| disque presque plein | `healthcheck.sh` (`df` ≥ 85 %) |
| worker sans heartbeat | `GET kwes:worker:heartbeat` (âge > 180 s) |
| service indisponible | `/health` + état des conteneurs |
| sauvegarde échouée | absence de dump < 26 h |
| queue qui augmente | `LLEN` de la file Redis (à instrumenter côté worker) |
| erreurs répétées | comptage des logs `level=error` |

Optionnel : `METRICS_ENABLED=true` (Prometheus, à ajouter avec un service
`prometheus`/`grafana`), `SENTRY_DSN` pour les traces d'erreur.

## 7. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| `proxy` redémarre en boucle | certificat absent pour `KWES_DOMAIN` | `bash infra/scripts/bootstrap_tls.sh --self-signed-only` |
| `nginx: host not found in upstream "backend"` | `backend` non healthy | `docker compose ps`, `logs backend` |
| `502` sur `/api/*` | backend down ou mauvais `DATABASE_URL` | `logs backend`, `curl localhost:8000/health` (dans le conteneur) |
| `worker` healthy mais tâches bloquées | mauvais `WORKER_COMMAND` | `docker compose logs worker`, vérifier `python -m app.worker` |
| WebSocket fermé toutes les 60 s | `proxy_read_timeout` trop court | déjà à 3600 s dans `kwes.conf` ; vérifier un proxy intermédiaire |
| migrations : `auth.uid() introuvable` | migration lancée sur un PostgreSQL nu | appliquer `supabase/local/0000_local_auth_shim.sql` (jamais sur Supabase) |
| `permission denied for table` côté client | policy manquante ou rôle `anon` | vérifier `pg_policies`, le JWT doit porter `role: authenticated` |

## 8. Limites connues (Alpha)

- Pas d'orchestrateur (un seul VPS) : pas de bascule automatique en cas de
  panne ; le redémarrage est assuré par `restart: unless-stopped`.
- Pas de mTLS ni de segmentation réseau avancée entre `backend` et `redis`.
- Le sandbox d'exécution des skills (isolation forte : seccomp, réseau coupé,
  quotas cgroup) n'est **pas** couvert par ce compose : il demande un runner
  dédié (`docs/09-skills/SKILL_SPECIFICATION.md` §5 et `SECURITY_MODEL.md` §7).
- Playwright dans le worker augmente fortement la RAM : `mem_limit: 2g` est un
  plancher, à relever ou à isoler dans un service séparé si les tâches
  concurrentes augmentent.
- Redis sans mot de passe (réseau Docker interne uniquement) : ajouter
  `--requirepass` si Redis devient joignable hors du réseau `internal`.
- Les images ne sont pas signées (cosign/notation) : à ajouter avant une mise
  en production élargie.
