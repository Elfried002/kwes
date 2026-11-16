# ADR-001 — Séparation frontend Vercel et backend VPS

- **Statut :** accepté
- **Date :** 2026-11-15

## Contexte
Le frontend doit être rapide à déployer et accessible sur le web. Le moteur agentique doit exécuter des tâches persistantes, des workers et des navigateurs automatisés.

## Décision
- frontend React/Vite sur Vercel ;
- FastAPI, Redis, workers et Playwright sur VPS ;
- Supabase pour la persistance managée ;
- communication HTTPS et WebSocket sécurisé.

## Conséquences positives
- séparation des responsabilités ;
- tâches persistantes indépendantes du navigateur ;
- déploiement frontend simplifié ;
- contrôle du runtime backend.

## Conséquences négatives
- gestion CORS et WebSocket ;
- deux environnements de déploiement ;
- supervision réseau supplémentaire.
