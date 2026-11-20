"""Configuration applicative (pydantic-settings, alimentée par l'environnement / .env).

Aucune valeur secrète n'est codée en dur : les secrets viennent uniquement de
l'environnement. Les valeurs par défaut sont soit non sensibles, soit les
valeurs de développement explicitement prévues par CONTRACTS.md.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_JWT_SECRET = "dev-secret-change-me"
# Origine de production incluse par défaut : sans elle, le navigateur bloque
# l'API et l'interface affiche « Backend injoignable ».
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173,http://localhost:5173,"
    "https://kwes.vercel.app,https://agent-kwes.com,https://www.agent-kwes.com,https://frontend-elfried002s-projects.vercel.app"
)
DEFAULT_BROWSER_ALLOWLIST = (
    "wikipedia.org,fr.wikipedia.org,en.wikipedia.org,example.com,www.example.com,duckduckgo.com"
)


class Settings(BaseSettings):
    """Paramètres du backend Kwes.

    Les noms de champs correspondent aux variables d'environnement du contrat
    (insensibles à la casse) : DATABASE_URL -> database_url, etc.
    """

    model_config = SettingsConfigDict(
        env_file=os.environ.get("KWES_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Kwes API"
    app_env: Literal["dev", "prod", "test"] = "dev"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    # --- Infrastructure -------------------------------------------------
    database_url: str = "postgresql+psycopg://kwes:kwes@127.0.0.1:5432/kwes"
    # RLS réelle : l'application se connecte avec un rôle sans privilège et
    # déclare l'identité de l'utilisateur à chaque transaction. Désactiver ce
    # drapeau est le rollback immédiat (retour au rôle administrateur).
    # Deux noms acceptés : `DB_RLS_ENABLED` (nom du champ) et `KWES_RLS_ENABLED`
    # (nom utilisé dans les fichiers d'environnement). Sans cet alias, la
    # variable KWES_RLS_ENABLED était silencieusement ignorée.
    db_rls_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("DB_RLS_ENABLED", "KWES_RLS_ENABLED"),
    )
    # Réservé au worker (composant système) : il traite les missions de tous
    # les espaces et ne peut donc pas porter l'identité d'un utilisateur.
    db_rls_bypass: bool = Field(default=False, alias="DB_RLS_BYPASS")
    kwes_db_app_password: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue_backend: Literal["auto", "redis", "memory"] = "auto"
    database_pool_size: int = 5
    #: Racine du package d'agents (SOUL/AGENT/SPEC/config.yaml par agent).
    agents_package_root: str = "/opt/kwes/agents_pkg"
    #: Manifestes des connecteurs (YAML versionnés dans le dépôt).
    connectors_dir: str = "connectors"
    #: Base publique de l'API, utilisée pour les URLs de retour OAuth.
    public_api_url: str = "https://api.agent-kwes.com"
    #: Application web, destination après une connexion OAuth réussie.
    frontend_url: str = "https://kwes.vercel.app"
    #: Supervision : sans DSN, aucune erreur n'est envoyée (statut affiché tel quel).
    sentry_dsn: str = ""
    sentry_environment: str = ""
    #: Reprise automatique des missions interrompues (processus API).
    mission_sweeper_enabled: bool = True
    mission_sweeper_interval_seconds: int = 120
    mission_sweeper_stale_seconds: int = 600

    # --- Authentification ----------------------------------------------
    dev_jwt_secret: str = DEFAULT_DEV_JWT_SECRET
    supabase_jwt_secret: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_leeway_seconds: int = 30
    jwt_audience: str = ""  # vide = pas de vérification d'audience

    # --- Fournisseurs ---------------------------------------------------
    # Un seul fournisseur, deux modèles, aucun repli (brief §4.3 et §16).
    # Le modèle Live rend la main quand la transcription du tour est complète :
    # mesuré de ~1 s (décision d'outil) à ~18 s (synthèse après lecture de 4
    # pages), avec des pointes au-delà de 20 s côté fournisseur. Un plafond à
    # 20 s produisait des 500 `LLMTimeout` sur un tour pourtant valide ; 35 s
    # laisse la marge nécessaire sans bloquer indéfiniment une requête.
    gemini_timeout_seconds: float = 35.0
    gemini_total_timeout_seconds: float = 60.0
    gemini_temperature: float = 0.2

    # --- API -------------------------------------------------------------
    cors_origins: str = DEFAULT_CORS_ORIGINS
    max_request_body_bytes: int = 1_500_000
    max_message_chars: int = 8000
    dev_endpoints: bool = False  # active POST /dev/token — dev uniquement
    browser_render: Literal["auto", "playwright", "httpx"] = "auto"  # rendu des pages lues par browser_readonly
    # Lecture de n'importe quel site public, au lieu de la seule allowlist.
    # Les garde-fous SSRF restent actifs (IP privées, metadata, ports, redirections).
    browser_open_web: bool = False
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 180
    rate_limit_chat_per_minute: int = 40
    request_id_header: str = "X-Request-ID"

    # --- Orchestrateur / worker -----------------------------------------
    max_task_steps: int = 6
    max_plan_repair_attempts: int = 1
    # Boucle d'outils conversationnelle : nombre d'allers-retours modèle → outil
    # avant de rendre la main. 2 suffit (chercher puis lire, ou rédiger).
    max_tool_rounds: int = 2
    max_tool_calls_per_round: int = 3
    max_memories_in_prompt: int = 12
    max_step_retries: int = 2
    step_retry_backoff_seconds: float = 0.25
    skill_default_timeout_seconds: float = 60.0
    worker_concurrency: int = 2
    worker_poll_timeout_seconds: float = 1.0
    worker_heartbeat_interval_seconds: float = 10.0
    worker_heartbeat_ttl_seconds: int = 60
    orphan_recovery_enabled: bool = True
    # P0 : le worker tourne dans un processus séparé. L'API ne le démarre
    # que si cette option est explicitement activée (tests, dev).
    worker_inline: bool = False
    worker_drain_seconds: float = 20.0
    worker_claim_ttl_seconds: int = 120
    # Balayage périodique : rattrape les tâches créées pendant une coupure Redis
    # ou dont la mise en file a échoué (la base reste la source de vérité).
    worker_sweep_interval_seconds: float = 30.0
    worker_name: str = "kwes-worker-1"
    approval_ttl_minutes: int = 30

    # --- WebSocket --------------------------------------------------------
    ws_heartbeat_seconds: float = 30.0
    ws_require_origin: bool = False  # True en prod : Origin obligatoire

    # --- Voix : Gemini Live ----------------------------------------------
    # La clé n'est jamais en clair dans .env : GOOGLE_API_KEY_ENC est déchiffrée
    # à la demande par app.core.secrets (fichier local 600).
    google_api_key: str = ""
    google_live_model: str = "gemini-3.8-live"
    # Mode raisonnement approfondi : même API Live, modèle différent (vérifié
    # disponible sur la clé le 17/11 : gemini-3.8-live-extended-thinking).
    #: Un seul modèle pour la voix et les missions : le mode « thinking » pilote
    #: le niveau de raisonnement, pas le modèle. Deux modèles différents
    #: ajoutaient un aller-retour de sélection perceptible à l'ouverture.
    google_live_thinking_model: str = "gemini-3.8-live"
    # Niveau exigé par le modèle : sans lui, l'API refuse la connexion
    # (« Thinking level must be specified for this model »).
    google_thinking_level: str = "HIGH"
    # Bascule automatique désactivée par défaut : couper la session en cours
    # pour changer de modèle supprimait la réponse en préparation (constaté au
    # test navigateur du 17/11). Le mode approfondi s'active explicitement
    # ({"type":"mode","value":"thinking"}) et revient seul au mode rapide.
    voice_auto_thinking: bool = False
    google_voice: str = "Charon"
    google_live_max_session_seconds: int = 900      # fermeture dure d'une session vocale
    google_live_idle_seconds: int = 45              # inactivité avant fermeture
    google_live_daily_budget_eur: float = 3.0       # estimation, jamais une facture
    google_live_reconnect_attempts: int = 2

    # --- Skills -----------------------------------------------------------
    browser_allowlist: str = DEFAULT_BROWSER_ALLOWLIST
    web_extra_allowlist: str = ""
    fetch_max_bytes: int = 2_000_000
    # Un PDF est plus volumineux qu'une page HTML : plafond distinct, sinon les
    # documents réels sont tronqués et deviennent illisibles (constaté sur arXiv).
    fetch_pdf_max_bytes: int = 8_000_000
    fetch_max_redirects: int = 4
    skill_offline_mode: bool = False  # tests : aucun accès réseau autorisé

    # --- Recherche (P1) ---------------------------------------------------
    research_engine: Literal["v2", "legacy"] = "v2"
    searxng_url: str = "http://127.0.0.1:8888"
    research_cache_enabled: bool = True
    research_cache_ttl_seconds: int = 86_400  # 24 h
    research_max_queries: int = 4
    research_max_pages: int = 5
    research_provider_daily_limit: int = 500
    research_provider_timeout_seconds: float = 15.0
    research_concurrency: int = 4
    research_pdf_max_bytes: int = 8_000_000
    research_pdf_max_pages: int = 40
    research_synthesis_enabled: bool = True

    # --- Exécution isolée (bac à sable) ---------------------------------
    # Le worker n'a pas le droit d'utiliser sudo (NoNewPrivileges) : il parle à
    # un proxy Docker restreint, en lecture seule sur le socket, qui n'expose
    # que conteneurs et images.
    code_exec_docker_host: str = "tcp://127.0.0.1:2375"

    # --- Divers ----------------------------------------------------------
    log_level: str = "INFO"
    demo_prefix: str = "[DEMO]"

    # ------------------------------------------------------------------
    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_env(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            # « production » et « prod » sont équivalents : une valeur explicite
            # doit toujours atterrir sur le mode le plus strict.
            aliases = {"production": "prod", "prod": "prod", "dev": "dev",
                       "development": "dev", "test": "test"}
            return aliases.get(normalized, normalized)
        return value

    @property
    def gemini_api_key(self) -> str:
        """Clé Google en clair, uniquement en mémoire process.

        En environnement `test`, aucune résolution de fichier : la suite ne doit
        jamais appeler un fournisseur payant (constaté le 16/11 — la synthèse
        partait réellement vers Google pendant les tests).
        """
        explicit = (self.google_api_key or "").strip()
        if explicit:
            return explicit
        if self.app_env == "test":
            return ""
        from app.core.secrets import resolve_secret

        return resolve_secret("GOOGLE_API_KEY")

    @property
    def voice_backend(self) -> str:
        """Fournisseur vocal actif, sans ambiguïté : gemini ou dégradé."""
        return "gemini" if self.gemini_api_key else "indisponible"

    @property
    def effective_database_url(self) -> str:
        """URL réellement utilisée : rôle applicatif restreint si RLS est active."""
        # Le worker est un composant système : il traite les missions de tous les
        # espaces et ne peut pas porter l'identité d'un utilisateur. Il garde donc
        # le rôle propriétaire (BYPASSRLS) ; l'API, elle, passe toujours par
        # `kwes_app`.
        if self.db_rls_bypass:
            return self.database_url
        if not self.db_rls_enabled or not self.kwes_db_app_password:
            return self.database_url
        # SQLite (tests) n'a ni rôles ni RLS : ne jamais réécrire ces URL.
        if not self.database_url.startswith("postgresql"):
            return self.database_url
        from urllib.parse import quote, urlsplit, urlunsplit

        parts = urlsplit(self.database_url)
        host = parts.hostname or "127.0.0.1"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"kwes_app:{quote(self.kwes_db_app_password, safe='')}@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def browser_domain_allowlist(self) -> list[str]:
        items = self.browser_allowlist.split(",") + self.web_extra_allowlist.split(",")
        return [d.strip().lower().rstrip(".") for d in items if d.strip()]

    @property
    def jwt_secret(self) -> str:
        """Secret HS256 effectif (dev : DEV_JWT_SECRET, sinon SUPABASE_JWT_SECRET)."""
        if self.app_env in ("dev", "test"):
            return self.dev_jwt_secret or DEFAULT_DEV_JWT_SECRET
        return self.supabase_jwt_secret

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"

    @property
    def jwt_issuer(self) -> str:
        """Émetteur attendu des jetons Supabase (`https://<ref>.supabase.co/auth/v1`)."""
        base = (self.supabase_url or "").rstrip("/")
        return f"{base}/auth/v1" if base else ""

    @property
    def llm_is_mock(self) -> bool:
        """Vrai si aucune clé Gemini n'est disponible : mode hors ligne explicite."""
        return not bool(self.gemini_api_key.strip())

    @property
    def voice_is_mock(self) -> bool:
        """La voix est indisponible tant qu'aucune clé Google n'est résolue."""
        return not bool(self.gemini_api_key)

    def mock_providers(self) -> list[str]:
        providers: list[str] = []
        if self.llm_is_mock:
            providers.append("gemini")
        if self.voice_is_mock and "gemini" not in providers:
            providers.append("gemini")
        return providers


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
