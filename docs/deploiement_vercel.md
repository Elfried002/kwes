# Déploiement Vercel — frontend Kwes

Le frontend React/Vite est un **site statique** : Vercel sert les assets et le
PWA ; les tâches persistantes, le worker et le navigateur automatisé restent sur
le VPS ([`infra/README.md`](../infra/README.md)).

Référence : `docs/10-infrastructure/VERCEL_AND_PWA.md`.

## 1. Import du projet

1. Vercel → **Add New… → Project → Import Git Repository**.
2. **Root Directory** : `frontend` (le dépôt contient aussi `backend/`, `infra/`).
3. **Framework Preset** : `Vite`. Détection automatique :
   - Build Command : `npm run build`
   - Output Directory : `dist`
   - Install Command : `npm ci`
4. Node : 22.x (Project Settings → General → Node.js Version).

Aucune fonction serverless, aucun `vercel.json` obligatoire pour un SPA Vite.
Si le routeur est côté client (React Router), une règle de réécriture est
nécessaire :

```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "DENY" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
        { "key": "Permissions-Policy", "value": "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)" },
        {
          "key": "Content-Security-Policy",
          "value": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' https://api.kwes.example wss://api.kwes.example https://*.supabase.co; media-src 'self' blob: https:; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        },
        { "key": "Strict-Transport-Security", "value": "max-age=63072000; includeSubDomains; preload" }
      ]
    },
    {
      "source": "/sw.js",
      "headers": [{ "key": "Cache-Control", "value": "no-cache, no-store, must-revalidate" }]
    },
    {
      "source": "/manifest.webmanifest",
      "headers": [{ "key": "Cache-Control", "value": "no-cache" }]
    },
    {
      "source": "/assets/(.*)",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }]
    }
  ]
}
```

`connect-src` doit lister **exactement** l'API (`https://` et `wss://`) et le
domaine Supabase si le client y accède directement — sinon le chat et le
WebSocket sont bloqués par le navigateur.

## 2. Variables d'environnement

Vercel → **Project Settings → Environment Variables**. Seules des valeurs
**publiques** : tout ce qui commence par `VITE_` finit dans le bundle.

| Variable | Exemple | Secret ? |
|---|---|---|
| `VITE_API_BASE_URL` | `https://api.kwes.example` | non |
| `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` | non |
| `VITE_SUPABASE_ANON_KEY` | `eyJhbGciOi...` (anon) | non (protégée par la RLS) |
| `VITE_APP_VERSION` | `0.1.0` | non |

**Interdits en `VITE_*`** : `SUPABASE_SERVICE_ROLE_KEY`, `DEEPSEEK_API_KEY`,
`ELEVENLABS_API_KEY`, `SUPABASE_JWT_SECRET`, `DEV_JWT_SECRET`. Une clé
`service_role` dans le bundle contourne toute la RLS.

Environnements : `Production` → `https://api.kwes.example` ;
`Preview` → URL de staging ou `http://127.0.0.1:8000` pour les tests locaux.

Rappel build-time : les `VITE_*` sont figées **au build**. Changer une valeur
exige un redéploiement (Deployments → Redeploy), pas seulement un redémarrage.

## 3. CORS côté backend

`CORS_ORIGINS` doit contenir chaque origine réelle du frontend, sans slash final
et avec le schéma exact :

```dotenv
CORS_ORIGINS=https://kwes.example,https://www.kwes.example,https://kwes-git-main-<team>.vercel.app
```

Les domaines de preview Vercel changent à chaque déploiement : soit une liste
explicite mise à jour, soit un motif `https://*-<team>.vercel.app` si le backend
sait l'interpréter. **Ne jamais** mettre `*` : le token part en en-tête
`Authorization` et les cookies ne doivent pas être acceptés depuis n'importe où.

Vérification :

```bash
curl -i -X OPTIONS https://api.kwes.example/api/v1/chat \
  -H "Origin: https://kwes.example" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type"
# attendu : 200/204 + access-control-allow-origin: https://kwes.example
```

## 4. Domaine

1. Vercel → Domains → **Add** `kwes.example` (+ `www` en redirection).
2. Chez le registrar : `A 76.76.21.21` pour l'apex, `CNAME cname.vercel-dns.com`
   pour `www` — ou les valeurs affichées par Vercel (elles évoluent).
3. Attendre l'émission du certificat (automatique, Let's Encrypt).
4. Tester `https://kwes.example` **et** `https://www.kwes.example` (redirection).

Le backend expose une origine différente (`api.kwes.example`) : c'est un
sous-domaine, donc pas de souci de cookies `SameSite` tant que
l'authentification se fait par `Authorization: Bearer` (c'est le cas ici).

## 5. PWA

- `manifest.webmanifest` (nom, `theme_color`, `display: standalone`,
  `start_url: "/"`), icônes 192/512 et `maskable` — les assets existent dans
  `frontend/public/brand/`.
- Service worker : précache des **assets statiques uniquement**. Ne jamais mettre
  en cache les réponses `/api/*` (données privées) : stratégie `network-only`
  pour l'API, `cache-first` pour les assets fingerprintés.
- Versionner le cache (`kwes-v<n>`) et purger les anciens à l'activation.
- Écran hors ligne : coquille applicative + message clair (« les missions
  continuent sur le serveur »).
- Microphone : HTTPS obligatoire, accès uniquement sur action utilisateur,
  indicateur visible, arrêt explicite, fallback texte.

Contrôle rapide :

```bash
# le service worker ne doit pas intercepter l'API
curl -s https://kwes.example/sw.js | grep -i "api" && echo "⚠️ vérifier la stratégie"
# Lighthouse (onglet PWA) : installable + hors ligne OK
```

## 6. Déploiement continu

- Production : push sur `main` → déploiement automatique après CI verte
  (`.github/workflows/ci.yml`, job `frontend`).
- Preview : chaque PR obtient une URL ; la tester avant merge (chat, WebSocket,
  micro).
- Ne pas activer « Ignore Build Step » sans raison : le build doit échouer si
  `tsc` échoue.

## 7. Checklist avant mise en ligne

- [ ] `frontend/` défini comme Root Directory
- [ ] `VITE_API_BASE_URL` en HTTPS, sans slash final
- [ ] aucune clé secrète dans les variables `VITE_*` (`grep -r "VITE_.*KEY"`)
- [ ] `CORS_ORIGINS` contient le domaine de production **et** les previews
- [ ] `connect-src` de la CSP autorise l'API et `wss://`
- [ ] rechargement à froid fonctionnel sur une route profonde (rewrite SPA)
- [ ] `sw.js` et `manifest.webmanifest` en `no-cache`
- [ ] PWA installable (Lighthouse) et écran hors ligne affiché
- [ ] `/health` du backend accessible depuis le navigateur (pas de blocage mixte)
- [ ] en-têtes de sécurité présents (`curl -I`)

```bash
curl -sI https://kwes.example | grep -Ei 'content-security|strict-transport|x-frame|x-content'
```
