# Kwes

Agent personnel autonome : on lui parle, il planifie, il exécute avec des outils
vérifiés, il demande une validation quand l'action est sensible, il rend compte.

Nom prononcé « Kwéss ». Interface en français, pensée mobile d'abord.

## Ce qui fonctionne réellement

- **Voix temps réel** — Gemini Live, WebSocket avec ticket court, barge-in
  mesuré (interruption à 1,50 s), session maintenue sur plusieurs tours.
- **Conversation écrite** — réponse en texte, fil de discussion par auteur.
- **Recherche web sourcée** — SearXNG local, garde-fous SSRF, sources citées.
- **Lecture de pages** — rendu navigateur pour les pages JavaScript.
- **Exécution de code** — conteneur isolé, réseau coupé, sans privilège.
- **Mémoire** — faits persistants par utilisateur, consultables et supprimables.
- **Documents** — production et téléchargement (Markdown/texte).
- **Missions** — planification multi-étapes, approbation avant action
  irréversible, journal d'exécution.
- **Multi-tenant** — Supabase Auth, isolation vérifiée côté API ; RLS renforcée
  côté base (rôle applicatif sans `BYPASSRLS`).

## Ce qui n'est pas fait

E-mail, WhatsApp/Telegram, agenda, paiement de factures, OCR, sites authentifiés,
connexion à des applications natives, application Android. Aucune langue
ivoirienne n'est validée par un locuteur natif (voir `docs/LANGUES_VOIX.md`).

## Architecture

```
backend/    FastAPI — agent, outils, voix, recherche, worker, migrations
frontend/   React + TypeScript + Vite (PWA)
infra/      Postgres, Redis, SearXNG, runner d'exécution isolé (Docker)
deploy/     unités systemd durcies (NoNewPrivileges, ProtectSystem=strict)
supabase/   schéma, politiques RLS, migrations
tools/      sondes de mesure (latence, modèles, langues, navigateur)
docs/       décisions, preuves de test, limites connues
```

## Démarrage local

```bash
cp backend/.env.example backend/.env      # renseigner les valeurs
docker compose -f infra/docker-compose.yml up -d
cd backend && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && python -m pytest -q     # 240 tests
cd frontend && npx vitest run         # 134 tests
```

## Secrets

Aucun secret n'est versionné. `backend/.env` reste hors du dépôt ; les
sauvegardes `.env.*` sont ignorées. Les coordonnées bancaires et les jetons
d'accès ne doivent jamais entrer dans le dépôt, un rapport ou un journal.

## État

Branche de travail : `alpha/jour-1`. L'état détaillé, les décisions et les
preuves de test vivent dans `IMPLEMENTATION_STATUS.md`, `DECISIONS_LOG.md` et
`docs/`.
