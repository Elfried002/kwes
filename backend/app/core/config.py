"""Configuration applicative (pydantic-settings, alimentée par l'environnement / .env).

Aucune valeur secrète n'est codée en dur : les secrets viennent uniquement de
l'environnement. Les valeurs par défaut sont soit non sensibles, soit les
valeurs de développement explicitement prévues par CONTRACTS.md.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_JWT_SECRET = "dev-secret-change-me"
DEFAULT_CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
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
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue_backend: Literal["auto", "redis", "memory"] = "auto"
    database_pool_size: int = 5

    # --- Authentification ----------------------------------------------
    dev_jwt_secret: str = DEFAULT_DEV_JWT_SECRET
    supabase_jwt_secret: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_leeway_seconds: int = 30
    jwt_audience: str = ""  # vide = pas de vérification d'audience

    # --- Fournisseurs ---------------------------------------------------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 30.0
    deepseek_max_retries: int = 2
    deepseek_temperature: float = 0.2

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
    approval_ttl_minutes: int = 30

    # --- WebSocket --------------------------------------------------------
    ws_heartbeat_seconds: float = 30.0
    ws_require_origin: bool = False  # True en prod : Origin obligatoire

    # --- Voix : Gemini Live ----------------------------------------------
    # La clé n'est jamais en clair dans .env : GOOGLE_API_KEY_ENC est déchiffrée
    # à la demande par app.core.secrets (fichier local 600).
    google_api_key: str = ""
    google_live_model: str = "gemini-3.8-live"
    google_voice: str = "Charon"
    google_live_max_session_seconds: int = 900      # fermeture dure d'une session vocale
    google_live_idle_seconds: int = 45              # inactivité avant fermeture
    google_live_daily_budget_eur: float = 3.0       # estimation, jamais une facture
    google_live_reconnect_attempts: int = 2

    # --- Skills -----------------------------------------------------------
    browser_allowlist: str = DEFAULT_BROWSER_ALLOWLIST
    web_extra_allowlist: str = ""
    fetch_max_bytes: int = 2_000_000
    fetch_max_redirects: int = 4
    skill_offline_mode: bool = False  # tests : aucun accès réseau autorisé

    # --- Divers ----------------------------------------------------------
    log_level: str = "INFO"
    demo_prefix: str = "[DEMO]"

    # ------------------------------------------------------------------
    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_env(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
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
    def llm_is_mock(self) -> bool:
        return not bool(self.deepseek_api_key.strip())

    @property
    def voice_is_mock(self) -> bool:
        """La voix est indisponible tant qu'aucune clé Google n'est résolue."""
        return not bool(self.gemini_api_key)

    def mock_providers(self) -> list[str]:
        providers: list[str] = []
        if self.llm_is_mock:
            providers.append("deepseek")
        if self.voice_is_mock:
            providers.append("gemini")
        return providers


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
