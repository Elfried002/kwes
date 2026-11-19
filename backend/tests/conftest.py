"""Fixtures pytest : app isolée, base SQLite temporaire, JWT dev, fetcher factice.

LIMITE DOCUMENTÉE : les tests utilisent SQLite (aiosqlite) car PostgreSQL n'est
pas disponible dans l'environnement. Types PG natifs (uuid, jsonb, timestamptz),
RLS et contraintes d'exclusion ne sont donc pas exercés ; le schéma SQLAlchemy
est identique et destiné à PostgreSQL en production.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.core.security import create_dev_token  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.fixtures import build_fake_fetcher  # noqa: E402

TERMINAL = ("completed", "failed", "awaiting_approval", "cancelled")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'kwes_test.db'}",
        queue_backend="memory",
        worker_concurrency=1,
        worker_poll_timeout_seconds=0.05,
        worker_heartbeat_interval_seconds=30,
        # P0 : la production tourne avec un worker séparé ; les tests gardent le
        # worker inline pour continuer à vérifier le traitement de bout en bout.
        worker_inline=True,
        worker_drain_seconds=5.0,
        rate_limit_enabled=False,
        log_level="CRITICAL",
        google_api_key="",
        skill_offline_mode=True,
        # Hermétique : le .env de production ouvre le web (P0), les tests non.
        browser_open_web=False,
        ws_heartbeat_seconds=30,
        max_task_steps=6,
        max_step_retries=1,
        step_retry_backoff_seconds=0.01,
        agents_package_root=str(
            Path(__file__).resolve().parents[2] / "docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1"
        ),
        connectors_dir=str(Path(__file__).resolve().parents[2] / "connectors"),
    )


@pytest.fixture
def fake_fetcher() -> Callable[[str], Any]:
    return build_fake_fetcher()


@pytest.fixture
def app(settings: Settings, fake_fetcher):
    application = create_app(settings)
    application.state.fetcher = fake_fetcher
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        # L'orchestrateur est construit au démarrage et capture son fetcher :
        # sans ce rebranchement, les tests appelaient le vrai réseau (constaté
        # le 16/11 — deux requêtes Wikipedia pendant une suite « hors ligne »).
        orchestrator = app.state.orchestrator
        orchestrator.fetcher = app.state.fetcher
        orchestrator.tool_runner.fetcher = app.state.fetcher
        yield test_client


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.uuid4()


def _headers(settings: Settings, uid: uuid.UUID, email: str) -> dict[str, str]:
    token = create_dev_token(uid, email, settings)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def headers(settings: Settings, user_id: uuid.UUID) -> dict[str, str]:
    return _headers(settings, user_id, "ada@kwes.local")


@pytest.fixture
def headers_other(settings: Settings, other_user_id: uuid.UUID) -> dict[str, str]:
    return _headers(settings, other_user_id, "other@kwes.local")


@pytest.fixture
def db_session_factory(settings: Settings):
    """Session SQLAlchemy SYNCHRONE sur le même fichier SQLite (tests uniquement)."""
    url = settings.database_url.replace("+aiosqlite", "")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    # `create_all` laisse une transaction ouverte sur SQLite : sans ce
    # recyclage, la connexion synchrone verrouille le fichier et l'API échoue
    # en « database is locked » dès qu'elle doit écrire.
    engine.dispose()
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def wait_task(client: TestClient, headers: dict[str, str]):
    def _wait(
        task_id: str,
        statuses: Iterable[str] = TERMINAL,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        body: dict[str, Any] | None = None
        while time.time() < deadline:
            response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            if body["status"] in set(statuses):
                return body
            time.sleep(0.05)
        raise AssertionError(
            f"Timeout en attendant la tâche {task_id} (dernier statut: {body.get('status') if body else None})"
        )

    return _wait


@pytest.fixture
def create_mission(client: TestClient, headers: dict[str, str]):
    def _create(message: str = "Prépare une étude de marché sur les fintechs au Bénin") -> dict[str, Any]:
        response = client.post(
            "/api/v1/chat", json={"message": message, "mode": "mission"}, headers=headers
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("task_id"), payload
        return payload

    return _create
