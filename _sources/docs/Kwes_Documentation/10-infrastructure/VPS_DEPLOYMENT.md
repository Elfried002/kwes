# Déploiement VPS — Kwes

## 1. Configuration visée

- 4 vCPU ;
- 8 Go RAM ;
- 100 Go NVMe ;
- Ubuntu Server 24.04 LTS ;
- architecture x86_64 ;
- accès SSH par clé ;
- sauvegarde externe.

Cette configuration est un point de départ pour Alpha, pas une garantie de capacité en charge. Playwright et les tâches concurrentes peuvent consommer beaucoup de mémoire.

## 2. Préparation serveur

- mettre à jour le système ;
- créer un utilisateur non-root ;
- désactiver l'accès SSH par mot de passe après validation des clés ;
- configurer le firewall ;
- installer Docker Engine et Compose ;
- configurer les mises à jour de sécurité ;
- installer un outil de monitoring ;
- créer les répertoires de données avec permissions minimales.

## 3. Services Docker

- API FastAPI ;
- worker ;
- Redis ;
- reverse proxy ;
- monitoring optionnel.

Supabase reste managé. Ne pas auto-héberger PostgreSQL sur le même VPS pour l'Alpha sans besoin spécifique.

## 4. Réseau

Ports publics :
- 80/tcp pour redirection HTTP vers HTTPS ;
- 443/tcp HTTPS ;
- 22/tcp SSH restreint à des IP ou VPN si possible.

Redis et ports internes ne doivent pas être exposés publiquement.

## 5. Reverse proxy

- TLS valide ;
- limite de taille ;
- timeouts adaptés au streaming ;
- support WebSocket ;
- headers de sécurité ;
- logs structurés ;
- redirection HTTPS.

## 6. Déploiement applicatif

1. récupérer une version taguée du dépôt ;
2. construire les images ;
3. valider les variables d'environnement ;
4. exécuter migrations ;
5. démarrer les services ;
6. vérifier `/health` ;
7. tester chat et tâche asynchrone ;
8. surveiller logs et ressources.

## 7. Sauvegardes

- sauvegardes Supabase selon offre et politique ;
- export périodique chiffré ;
- copie externe des fichiers nécessaires ;
- test de restauration ;
- ne pas stocker la seule sauvegarde sur le VPS.

## 8. Mise à jour et rollback

- déploiement versionné ;
- migrations compatibles ;
- sauvegarde avant migration destructive ;
- possibilité de revenir à l'image précédente ;
- vérifier la santé après déploiement.
