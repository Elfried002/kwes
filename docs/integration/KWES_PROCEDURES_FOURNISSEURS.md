# KWES — Procédures de configuration par fournisseur

Chaque procédure se termine par un **test réel** et un **statut** à tenir à jour. Aucune
intégration n'est déclarée opérationnelle avant que ce test ait réussi.

## Apple — Sign in with Apple

1. developer.apple.com → Certificates, Identifiers & Profiles → Identifiers → **+** → Services IDs.
2. Créer `com.agentkwes.web` (ou l'identifiant retenu), cocher **Sign in with Apple**, Configure :
   - Domains : `agent-kwes.com`
   - Return URLs : `https://yhgbvyibsvsjpxsnjdzn.supabase.co/auth/v1/callback`
   *(le domaine **sans** `https://` dans le champ Domains, l'URL complète dans Return URLs)*
3. Keys → **+** → « Sign in with Apple » → télécharger le `.p8` (une seule fois) ; noter le Key ID.
4. Noter le Team ID (Membership).
5. Supabase → Authentication → Providers → **Apple** → activer, renseigner Services ID, Team ID, Key ID, contenu du `.p8`.
6. Vérifier `apple: true` sur `/auth/v1/settings`.

**Test :** `https://agent-kwes.com/#/connexion` → « Continuer avec Apple » → authentification Apple → retour sur `/#/` avec session active → `/api/v1/me` répond 200.
**Statut actuel :** bloqué — fournisseur désactivé, aucun identifiant fourni.

## Telegram

**Par utilisateur (aucune configuration serveur)**
1. @BotFather → `/newbot` → nom + username → jeton `123456:ABC…`.
2. KWES → Connecteurs → Telegram → coller le jeton → Enregistrer (chiffré AES-GCM, jamais réaffiché).
3. « Tester » → vérifie que le secret est présent et déchiffrable.

**Test réel :** mission « envoie Bonjour sur Telegram, chat 42 » → l'outil `telegram.send` renvoie `message_id`, journalisé avec preuve.
**Limite :** un bot ne donne accès qu'aux conversations qui lui parlent — jamais au compte personnel.

**Réception (non implémentée) :** exige `setWebhook` + `TELEGRAM_WEBHOOK_SECRET`, endpoint `POST /api/v1/webhooks/telegram` à créer.

## Meta / WhatsApp Business Platform

1. developers.facebook.com → Create App → type **Business** → ajouter le produit **WhatsApp**.
2. Business Settings → Comptes → **WhatsApp Business Account** (WABA) → ajouter/valider un numéro professionnel.
3. Business Settings → Utilisateurs système → créer un utilisateur système, l'assigner au WABA, générer un jeton **permanent** avec `whatsapp_business_messaging` + `whatsapp_business_management`.
4. App Dashboard → WhatsApp → API Setup : noter **Phone Number ID** et **WABA ID**.
5. Webhook : URL `https://api.agent-kwes.com/api/v1/webhooks/whatsapp`, Verify Token généré par KWES, s'abonner à `messages`.
6. App Review → **Advanced Access** sur les deux permissions (délai 1–2 semaines).

**Test réel :** envoi d'un texte vers un numéro de test (fenêtre de service 24 h), réception d'un message entrant, vérification de la déduplication.
**Statut actuel :** outils `declared` — aucun envoi réel possible, rien n'est simulé.
**Interdit :** WhatsApp Web automatisé, QR non officiel, accès aux conversations personnelles.

## Microsoft Graph (si conservé)

1. entra.microsoft.com → App registrations → New registration.
2. Redirect URI (Web) : `https://yhgbvyibsvsjpxsnjdzn.supabase.co/auth/v1/callback`.
3. Certificates & secrets → New client secret → noter la valeur (une seule fois).
4. API permissions → Microsoft Graph → déléguées : `Mail.Read`, `Calendars.ReadWrite` → Grant admin consent.
5. Supabase → Providers → **Azure** → activer avec Client ID / Secret / Tenant `common`.

**Test réel :** `/api/v1/connectors` → Microsoft `available` ; connexion ; lecture de 3 messages.
**Décision requise :** conserver ou retirer le connecteur du catalogue.

## Sentry

1. sentry.io → projet backend + projet frontend.
2. Settings → Client Keys → copier les DSN.
3. Settings → Auth Tokens → token scope `event:read` (lecture pour le cockpit).
4. Variables : `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `VITE_SENTRY_DSN`, `SENTRY_AUTH_TOKEN`.

**Test réel :** provoquer une exception contrôlée sur staging (`GET /api/v1/dev/boom`, à ajouter si absent), vérifier l'événement dans Sentry puis le compteur dans `/urs/`.
**Statut actuel :** non configuré ; le cockpit affiche « Aucun DSN configuré ».
