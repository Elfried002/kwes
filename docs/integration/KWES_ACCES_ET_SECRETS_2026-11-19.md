# KWES — Registre consolidé des accès et secrets

**Date :** 19 novembre 2026 · **Portée :** staging et production · **Règle :** aucune valeur secrète n'est écrite ici, seulement le nom, l'usage et la procédure.

Légende statut : ✅ présent · ⚠️ partiel · ❌ manquant · 🔒 secret confidentiel · 🌐 identifiant public

---

## 1. Vercel et domaine agent-kwes.com

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| Projet | `frontend` (`prj_e8FsktRf1BFdrqnzVW44iuDTOArl`) | ✅ | — |
| Domaines | `agent-kwes.com` (canonique), `www` → 308, `kwes.vercel.app` → 308 | ✅ | — |
| SSL | Let's Encrypt, CN=agent-kwes.com, expire 16/02/2027 | ✅ | — |
| DNS | A `216.198.79.1` chez LWS (`ns17–20.lwsdns.com`) | ✅ | — |
| Variables | `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | ✅ | 🌐 |

**Utilité :** hébergement du frontend, redirections et certificat.
**Où :** vercel.com → projet `frontend` → Settings → Domains / Environment Variables.
**Test :** `curl -I https://agent-kwes.com` → 200 ; `curl -I https://www.agent-kwes.com` → 308 vers l'apex.

---

## 2. Supabase (Auth, PostgreSQL, redirections) — **bloquant Google**

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| URL projet | `SUPABASE_URL` | ✅ | 🌐 |
| Clé publique | `SUPABASE_ANON_KEY` | ✅ | 🌐 |
| Secret JWT | `SUPABASE_JWT_SECRET` | ✅ | 🔒 |
| **Site URL** | doit être `https://agent-kwes.com` | ❌ (actuellement `https://kwes.vercel.app`) | — |
| **Redirect URLs** | `https://agent-kwes.com/**`, `https://www.agent-kwes.com/**` | ❌ | — |
| Mot de passe base applicatif | `KWES_DB_APP_PASSWORD` | ✅ | 🔒 |

**Utilité :** identité, sessions, isolation RLS.
**Où :** supabase.com → projet `yhgbvyibsvsjpxsnjdzn` → Authentication → URL Configuration.
**Procédure :** Site URL = `https://agent-kwes.com` ; Additional Redirect URLs = les deux lignes ci-dessus ; Save.
**Pourquoi c'est bloquant :** le callback d'erreur renvoie aujourd'hui sur `kwes.vercel.app`. Comme le vérificateur PKCE est stocké par origine, l'échange échoue et l'utilisateur retombe sur la connexion.
**Test :** `curl -s -D - "https://<ref>.supabase.co/auth/v1/callback?error=access_denied&redirect_to=https://agent-kwes.com/" | grep -i location` doit renvoyer `agent-kwes.com`.

---

## 3. Google Cloud OAuth (Gmail, Agenda)

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| Client ID | `GOOGLE_OAUTH_CLIENT_ID` | ❌ | 🌐 |
| Client Secret | `GOOGLE_OAUTH_CLIENT_SECRET` | ❌ | 🔒 |
| URI de redirection autorisée | `https://yhgbvyibsvsjpxsnjdzn.supabase.co/auth/v1/callback` | ✅ (le fournisseur Google de Supabase fonctionne déjà) | — |
| Origine JavaScript autorisée | `https://agent-kwes.com` | à ajouter | — |
| Scopes | `gmail.readonly`, `gmail.compose`, `calendar.events` | — | — |
| Clé Gemini | `GOOGLE_API_KEY_ENC` + `/opt/kwes/.secrets/gemini.key` | ✅ | 🔒 |

**Attention :** deux choses distinctes. Le **login Google** passe par le fournisseur Google de Supabase (déjà activé, ✅) et fonctionne dès que l'URL #2 est corrigée. Le **connecteur Gmail/Agenda** (l'agent qui lit les e-mails) exige en plus un client OAuth dédié, aujourd'hui absent — d'où le statut `needs_configuration` du connecteur.
**Où :** console.cloud.google.com → APIs & Services → Credentials → Create OAuth client ID (Web application).
**Procédure :** ajouter l'URI de redirection Supabase ci-dessus + `https://agent-kwes.com` en origine ; activer Gmail API et Google Calendar API ; télécharger le JSON, me transmettre les deux valeurs par canal sécurisé.
**Test :** `GET /api/v1/connectors` → Google passe de `needs_configuration` à `available` ; puis connexion réelle et `POST /connectors/google/test`.

---

## 4. Apple Developer / Sign in with Apple — **entièrement manquant**

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| Team ID | 10 caractères | ❌ | 🌐 |
| Services ID | ex. `com.agentkwes.web` | ❌ | 🌐 |
| Key ID | 10 caractères | ❌ | 🌐 |
| Clé privée | `.p8` (téléchargée une seule fois) | ❌ | 🔒 |
| Domaine vérifié | `agent-kwes.com` | ❌ | — |
| Return URL | `https://yhgbvyibsvsjpxsnjdzn.supabase.co/auth/v1/callback` | ❌ | — |
| Fournisseur Supabase | `apple` | ❌ **désactivé** (vérifié sur `/auth/v1/settings`) | — |

**Utilité :** troisième moyen de connexion.
**Où :** developer.apple.com → Certificates, Identifiers & Profiles → Identifiers → Services IDs → Sign In with Apple → Configure.
**Procédure :** créer le Services ID, cocher « Sign in with Apple », ajouter le domaine et la Return URL ; créer une clé « Sign in with Apple » ; dans Supabase → Authentication → Providers → Apple, renseigner Services ID, Team ID, Key ID et la clé `.p8`.
**Test :** bouton « Continuer avec Apple » → écran Apple → retour sur `agent-kwes.com/#/` avec session active.
**Note :** le bouton est déjà en place et affiche aujourd'hui « La connexion Apple n'est pas encore activée sur ce service ».

---

## 5. Telegram Bot API

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| Jeton de bot | saisi par **chaque utilisateur** dans l'écran Connecteurs | ✅ (mécanisme) | 🔒 |
| Secret webhook (optionnel) | `TELEGRAM_WEBHOOK_SECRET` | ❌ (réception non implémentée) | 🔒 |

**Utilité :** envoi de messages par l'agent, via le bot de l'utilisateur.
**Où :** @BotFather → `/newbot` → jeton.
**Procédure :** aucune configuration serveur nécessaire pour l'envoi ; l'utilisateur colle son jeton, il est chiffré en base.
**Test :** Connecteurs → Telegram → coller le jeton → « Tester » → mission demandant un envoi, vérifier `message_id` dans le journal.

---

## 6. Meta / WhatsApp Business Platform

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| App ID | `META_APP_ID` | ❌ | 🌐 |
| App Secret | `META_APP_SECRET` | ❌ | 🔒 |
| WABA ID | `WHATSAPP_BUSINESS_ACCOUNT_ID` | ❌ | 🌐 |
| Phone Number ID | `WHATSAPP_PHONE_NUMBER_ID` | ❌ | 🌐 |
| Jeton système permanent | `WHATSAPP_SYSTEM_USER_TOKEN` | ❌ | 🔒 |
| Verify Token webhook | généré par KWES | ❌ | 🔒 |
| Revue Meta | Advanced Access | ❌ | — |

**Où :** developers.facebook.com → app Business → produit WhatsApp ; Business Settings → Utilisateurs système.
**Procédure :** créer l'app, ajouter WhatsApp, associer le WABA et le numéro, générer le jeton, déclarer l'URL de webhook `https://api.agent-kwes.com/api/v1/webhooks/whatsapp`, puis demander l'Advanced Access (`whatsapp_business_messaging`, `whatsapp_business_management`).
**Test :** envoi réel vers un numéro de test + réception webhook. Aucun envoi n'est simulé aujourd'hui : les outils restent `declared`.
**Délai :** revue Meta 1–2 semaines.

---

## 7. Microsoft Graph (si les connecteurs Microsoft sont conservés)

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| Client ID | `MICROSOFT_OAUTH_CLIENT_ID` | ❌ | 🌐 |
| Client Secret | `MICROSOFT_OAUTH_CLIENT_SECRET` | ❌ | 🔒 |
| Scopes | `Mail.Read`, `Calendars.ReadWrite` | — | — |
| Fournisseur Supabase | `azure` | ❌ désactivé | — |

**Décision à prendre :** conserver Microsoft ou retirer le connecteur du catalogue. Aujourd'hui il est affiché `needs_configuration`, ce qui est honnête mais inutile sans identifiants.

---

## 8. Sentry (backend et frontend)

| Élément | Nom | Statut | Nature |
|---|---|---|---|
| DSN backend | `SENTRY_DSN` | ❌ | 🔒 |
| DSN frontend | `VITE_SENTRY_DSN` | ❌ | 🔒 |
| Jeton de lecture API | `SENTRY_AUTH_TOKEN` | ❌ | 🔒 |
| Organisation / projet | `SENTRY_ORG`, `SENTRY_PROJECT` | ❌ | 🌐 |

**Où :** sentry.io → Settings → Projects → Client Keys (DSN) ; Settings → Auth Tokens (scope `event:read`).
**Test :** provoquer une exception contrôlée sur staging, vérifier l'événement dans Sentry et le compteur dans `/urs/`.

---

## 9. Ce qui est déjà en place (ne pas redemander)

`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, `DATABASE_URL`, `KWES_DB_APP_PASSWORD`, `REDIS_URL`, `GOOGLE_API_KEY_ENC`, `/opt/kwes/.secrets/gemini.key` (600), `KWES_SECRETS_KEY_FILE` (coffre des connecteurs), les trois variables Vercel.

---

## 10. Ordre de priorité

1. **Supabase URL Configuration** — 2 minutes, débloque Google immédiatement.
2. **Google OAuth client** — débloque le connecteur Gmail/Agenda.
3. **Apple** — débloque la 3ᵉ connexion.
4. **Sentry** — débloque le monitoring du cockpit.
5. **Meta/WhatsApp** — le plus long (revue).
6. **Microsoft** — seulement si conservé.
