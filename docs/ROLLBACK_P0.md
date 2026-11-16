# Rollback P0 — revenir à l'API avec worker intégré

Objectif : rétablir le fonctionnement antérieur en moins de deux minutes si le service
`kwes-worker` pose problème. La migration `0011` étant additive, elle **ne doit pas** être annulée
pour un rollback fonctionnel.

## Pré-requis

- Sauvegarde : `/home/babayaga/backups/kwes-pre-p0-20261116-2205.tgz`
- Commit P0 : voir `git log --oneline -1`

## Procédure (5 étapes)

```bash
# 1. Arrêter les deux services
sudo systemctl stop kwes-worker kwes-api

# 2. Relancer l'API en mode historique : le worker tourne dans le processus
cd /home/babayaga/business/kwes/backend
WORKER_INLINE=true nohup .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 > api.log 2>&1 &

# 3. Vérifier
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/health
curl -s -o /dev/null -w "%{http_code}\n" https://n8n.streetflexs.store/kwes-api/api/v1/health
tail -5 api.log          # doit contenir « Worker inline activé (dev/tests). »

# 4. Désactiver les unités pour éviter un redémarrage automatique ultérieur
sudo systemctl disable kwes-api kwes-worker

# 5. Créer une mission de contrôle et vérifier qu'elle se termine
```

## Si le code lui-même doit être annulé

```bash
cd /home/babayaga/business/kwes
git revert --no-edit <commit P0>      # annule le code, garde l'historique
cd backend && .venv/bin/python -m pytest -q   # attendu : 148 passed
sudo systemctl restart kwes-api       # ou relancer en mode historique (étape 2)
```

La migration `0011` peut rester en place : les colonnes `claimed_by`/`claimed_at` sont nullables
et le code antérieur ne les lit pas. Pour les supprimer malgré tout (destructif, déconseillé) :

```sql
alter table public.tasks drop column if exists claimed_by;
alter table public.tasks drop column if exists claimed_at;
```

## Retour vers P0

```bash
sudo systemctl enable --now kwes-api kwes-worker
sudo systemctl status kwes-api kwes-worker
```

## Points de contrôle après rollback

| Contrôle | Attendu |
|---|---|
| `/api/v1/health` local et public | 200 |
| `tail backend/api.log` | « Worker inline activé » |
| Soumission d'une mission | statut `completed` |
| `ps aux \| grep app.worker` | aucun processus worker séparé |
