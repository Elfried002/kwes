# =============================================================================
# Kwes — infra/backend.Dockerfile
#
# Image unique pour l'API et le worker (même code, commande différente).
# Multi-stage, utilisateur non-root, pas d'outils de build dans l'image finale.
#
# Build (depuis la racine du dépôt) :
#   docker build -f infra/backend.Dockerfile -t kwes/backend:dev .
# =============================================================================

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Étape 1 — construction du virtualenv
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dépendances système de compilation (psycopg, cffi, éventuels wheels absents)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . /build

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip wheel setuptools \
 && if [ -f requirements.txt ]; then \
        /opt/venv/bin/pip install -r requirements.txt; \
    elif [ -f pyproject.toml ]; then \
        /opt/venv/bin/pip install .; \
    else \
        echo "Aucun requirements.txt/pyproject.toml : installation du socle ASGI minimal" \
        && /opt/venv/bin/pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"; \
    fi

# -----------------------------------------------------------------------------
# Étape 2 — image d'exécution
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8000 \
    TZ=UTC \
    APP_HOME=/app

# libpq5 : client PostgreSQL (psycopg) ; curl non installé => healthcheck Python
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root dédié (UID/GID fixes pour des volumes prévisibles)
RUN groupadd --gid 10001 kwes \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin kwes

WORKDIR ${APP_HOME}

COPY --from=builder --chown=kwes:kwes /opt/venv /opt/venv
COPY --chown=kwes:kwes backend/ ${APP_HOME}/

RUN mkdir -p ${APP_HOME}/data /tmp/kwes \
 && chown -R kwes:kwes ${APP_HOME}/data /tmp/kwes \
 && chmod 750 ${APP_HOME}/data

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4); sys.exit(0 if r.status < 400 else 1)"]

# tini : PID 1 correct, SIGTERM transmis, pas de zombies (worker + Playwright)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Surchargé par le service `worker` (command: python -m app.worker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
