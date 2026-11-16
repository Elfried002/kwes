# =============================================================================
# Kwes — infra/frontend.Dockerfile  (OPTIONNEL)
#
# Le frontend de production est servi par Vercel (docs/10-infrastructure/
# VERCEL_AND_PWA.md). Cette image sert les cas : prévisualisation, PWA servie
# depuis le VPS, environnement hors Vercel, test de la CSP réelle.
#
# Build (depuis la racine) :
#   docker build -f infra/frontend.Dockerfile \
#     --build-arg VITE_API_BASE_URL=https://api.kwes.example \
#     -t kwes/frontend:dev .
#
# ⚠️  Toute variable VITE_* finit dans le bundle public : jamais de secret.
# =============================================================================

ARG NODE_VERSION=22

# -----------------------------------------------------------------------------
# Étape 1 — build Vite
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /app

# Dépendances d'abord : cache Docker préservé si le lockfile ne change pas
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund; \
    fi

COPY frontend/ ./

# URL d'API injectée au build (non secrète)
ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_ANON_KEY=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_SUPABASE_URL=${VITE_SUPABASE_URL} \
    VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY} \
    NODE_ENV=production

RUN npm run build

# -----------------------------------------------------------------------------
# Étape 2 — serveur statique Nginx non privilégié
# -----------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Variante `unprivileged` : écoute sur 8080, tourne en UID 101
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

# SPA + en-têtes de sécurité, sans TLS (le TLS est terminé par le proxy)
RUN cat > /etc/nginx/conf.d/kwes-frontend.conf <<'CONF'
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA : toutes les routes inconnues retombent sur index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Le service worker et le manifeste ne doivent jamais être mis en cache
    location = /sw.js            { add_header Cache-Control "no-cache"; }
    location = /manifest.webmanifest { add_header Cache-Control "no-cache"; }

    # Assets fingerprintés : cache long
    location ~* \.(js|css|woff2?|png|jpg|jpeg|svg|webp|gif|ico)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location = /healthz { access_log off; return 200 "ok\n"; }
}
CONF

RUN chown -R nginx:nginx /usr/share/nginx/html

USER 101:101
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]

CMD ["nginx", "-g", "daemon off;"]
