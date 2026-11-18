"""Infrastructure : schéma des 15 tables, adaptateurs MOCK, worker, voix."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.llm import GeminiTextClient, MOCK_MARKER
from app.agent.voice import GeminiVoiceProvider
from app.core.config import Settings
from app.core.utils import utcnow
from app.db.base import Database
from app.db.models import ALL_MODELS, Base, Profile, Task
from app.worker.queue import MemoryTaskQueue
from app.worker.worker import TaskWorker


def test_all_tables_exist_with_expected_names() -> None:
    expected = {
        "profiles",
        "conversations",
        "messages",
        "tasks",
        "task_steps",
        "executions",
        "skills",
        "skill_versions",
        "memories",
        "approvals",
        "integrations",
        "audit_logs",
        "notifications",
        "device_connectors",
        "device_commands",
        "documents",
        "voice_sessions",
        "evidence",
        # SaaS multi-tenant (migration 0013)
        "tenants",
        "tenant_memberships",
        "tenant_settings",
    }
    assert set(Base.metadata.tables) == expected
    assert len(ALL_MODELS) == 21  # 18 + tenants + appartenances + paramètres d'espace


def test_task_columns_match_data_model() -> None:
    columns = set(Base.metadata.tables["tasks"].columns.keys())
    assert {
        "id",
        "user_id",
        "conversation_id",
        "title",
        "goal",
        "status",
        "priority",
        "progress",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "result_summary",
        "error_code",
    } <= columns


def test_approval_and_execution_columns() -> None:
    approvals = set(Base.metadata.tables["approvals"].columns.keys())
    assert {"payload_hash", "summary", "status", "expires_at", "decided_at", "action_type"} <= approvals
    executions = set(Base.metadata.tables["executions"].columns.keys())
    assert {"idempotency_key", "input_redacted", "duration_ms", "error_code"} <= executions


async def test_offline_answer_is_deterministic_and_labelled(settings: Settings) -> None:
    client = GeminiTextClient(settings)
    messages = [{"role": "user", "content": "Bonjour"}]
    first = await client.chat(messages)
    second = await client.chat(messages)
    assert first.mock is True
    assert first.content == second.content
    assert MOCK_MARKER in first.content


async def test_offline_plan_is_valid_json(settings: Settings) -> None:
    client = GeminiTextClient(settings)
    result = await client.chat(
        [{"role": "user", "content": "Prépare une étude de marché sur les fintechs"}],
        json_mode=True,
        purpose="plan",
    )
    plan = result.json()
    assert plan["steps"][0]["skill"] == "web_research"
    assert plan["steps"][0]["id"] == "step_1"


def test_live_reasoner_converts_history_for_sessions(settings: Settings) -> None:
    """L'historique interne devient des tours Live (outils inclus)."""
    from app.agent.live_reasoner import _turns

    system, turns = _turns(
        [
            {"role": "system", "content": "consignes"},
            {"role": "user", "content": "cherche kwes"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_0", "name": "web_research", "arguments": {"query": "kwes"}}],
            },
            {"role": "tool", "name": "web_research", "content": '{"status": "ok"}'},
        ]
    )
    assert system == "consignes"
    assert len(turns) == 3
    assert turns[1].role == "model"
    assert "web_research" in turns[1].parts[0].text
    assert "[Résultat de l'outil web_research]" in turns[2].parts[0].text


def test_gemini_converts_history_to_contents(settings: Settings) -> None:
    """L'historique interne (assistant + tool_call_id) devient des parts Gemini."""
    from app.agent.llm import _to_contents

    contents = _to_contents(
        [
            {"role": "system", "content": "consignes"},
            {"role": "user", "content": "cherche kwes"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_0",
                        "function": {"name": "web_research", "arguments": '{"query": "kwes"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_0", "content": '{"status": "ok"}'},
        ]
    )
    assert len(contents) == 3
    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.name == "web_research"
    assert contents[2].parts[0].function_response.name == "web_research"


def test_gemini_without_key_is_offline_and_labelled(settings: Settings) -> None:
    client = GeminiTextClient(settings)
    assert client.mock is True


async def test_voice_mock_falls_back_to_text(settings: Settings) -> None:
    provider = GeminiVoiceProvider(settings)
    result = await provider.synthesize("Bonjour")
    assert result.mock is True
    assert result.audio is None
    assert result.fallback is True
    assert result.text == "Bonjour"


def test_voice_endpoint_returns_text_fallback(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/voice/synthesize", json={"text": "Bonjour Kwes"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is True
    assert body["audio_base64"] is None
    assert body["mock"] is True


async def test_worker_recovers_orphaned_tasks(settings: Settings) -> None:
    db = Database(settings.database_url)
    await db.create_all()
    user_id = uuid.uuid4()
    stale = utcnow() - timedelta(minutes=10)
    async with db.session() as session:
        session.add(Profile(id=user_id, display_name="Orphelin"))
        await session.flush()
        session.add(
            Task(
                user_id=user_id,
                title="Mission orpheline",
                goal="Reprise après crash",
                status="running",
                created_at=stale,
                updated_at=stale,
            )
        )

    queue = MemoryTaskQueue()
    worker = TaskWorker(settings=settings, db=db, orchestrator=None, queue=queue)  # type: ignore[arg-type]
    recovered = await worker.recover_orphans()
    assert recovered == 1
    assert queue.size() == 1
    async with db.session() as session:
        from sqlalchemy import select

        task = (await session.execute(select(Task))).scalars().first()
        assert task is not None and task.status == "queued"
    await db.dispose()


def test_mock_header_absent_when_keys_configured(settings: Settings, fake_fetcher) -> None:
    from app.main import create_app

    configured = settings.model_copy(
        update={"google_api_key": "configured"}
    )
    application = create_app(configured)
    application.state.fetcher = fake_fetcher
    with TestClient(application) as local_client:
        response = local_client.get("/api/v1/health")
        assert response.headers.get("X-Kwes-Mock") is None
        assert response.json()["dependencies"]["llm"] == "ok"
