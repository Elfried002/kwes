"""P0 : séparation API/worker, verrou d'exécution, reprise et arrêt propre.

Ces tests couvrent les garanties annoncées dans le rapport P0 :
* le worker peut tourner sans l'API et inversement ;
* une tâche n'est jamais exécutée deux fois en parallèle ;
* une tâche en cours est remise en file (donc rejouée) après un arrêt brutal ;
* l'arrêt propre attend les tâches en cours ;
* aucun secret n'apparaît dans les journaux.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.utils import utcnow
from app.db.base import Database
from app.db.models import Profile, Task
from app.main import create_app
from app.worker.claims import claim_task, release_all, release_task
from app.worker.queue import MemoryTaskQueue
from app.worker.runtime import build_runtime
from app.worker.worker import TaskWorker


class _RecordingOrchestrator:
    """Orchestrateur factice : compte les exécutions et peut ralentir."""

    def __init__(self, delay: float = 0.0, outcome: str = "completed") -> None:
        self.delay = delay
        self.outcome = outcome
        self.calls: list[uuid.UUID] = []

    async def execute_task(self, task_id: uuid.UUID) -> str:
        self.calls.append(task_id)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.outcome


async def _make_task(settings: Settings, *, status: str = "queued") -> tuple[Database, uuid.UUID]:
    db = Database(settings.database_url)
    await db.create_all()
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    async with db.session() as session:
        session.add(Profile(id=user_id, display_name="Test P0"))
        await session.flush()
        session.add(
            Task(
                id=task_id,
                user_id=user_id,
                title="Mission P0",
                goal="Vérifier le worker",
                status=status,
            )
        )
        await session.commit()
    return db, task_id


# ---------------------------------------------------------------------------
# Verrou d'exécution
# ---------------------------------------------------------------------------
async def test_claim_is_exclusive_between_workers(settings: Settings) -> None:
    db, task_id = await _make_task(settings)
    try:
        assert await claim_task(db, task_id, "worker-a", ttl_seconds=120) is True
        # Le second worker ne peut pas prendre la tâche.
        assert await claim_task(db, task_id, "worker-b", ttl_seconds=120) is False
        # Le propriétaire peut la reprendre (idempotent).
        assert await claim_task(db, task_id, "worker-a", ttl_seconds=120) is True
        await release_task(db, task_id, "worker-a")
        assert await claim_task(db, task_id, "worker-b", ttl_seconds=120) is True
    finally:
        await db.dispose()


async def test_claim_expires_after_ttl(settings: Settings) -> None:
    db, task_id = await _make_task(settings)
    try:
        async with db.session() as session:
            task = await session.get(Task, task_id)
            task.claimed_by = "worker-mort"
            task.claimed_at = utcnow() - timedelta(seconds=600)
            await session.commit()
        # Un verrou périmé n'empêche pas la reprise par un autre worker.
        assert await claim_task(db, task_id, "worker-b", ttl_seconds=60) is True
    finally:
        await db.dispose()


async def test_release_all_frees_only_own_claims(settings: Settings) -> None:
    db, task_id = await _make_task(settings)
    try:
        await claim_task(db, task_id, "worker-a", ttl_seconds=120)
        assert await release_all(db, "worker-z") == 0
        assert await release_all(db, "worker-a") == 1
        assert await claim_task(db, task_id, "worker-b", ttl_seconds=120) is True
    finally:
        await db.dispose()


# ---------------------------------------------------------------------------
# File : reprise et acquittement
# ---------------------------------------------------------------------------
async def test_requeue_processing_restores_inflight() -> None:
    queue = MemoryTaskQueue()
    task_id = uuid.uuid4()
    await queue.enqueue(task_id)
    assert await queue.claim(timeout=0.1) == task_id
    assert await queue.claim(timeout=0.1) is None  # déjà en cours, pas en file
    assert await queue.requeue_processing() == 1
    assert await queue.claim(timeout=0.1) == task_id
    await queue.ack(task_id)
    assert await queue.claim(timeout=0.05) is None


async def test_enqueue_is_deduplicated() -> None:
    queue = MemoryTaskQueue()
    task_id = uuid.uuid4()
    await queue.enqueue(task_id)
    await queue.enqueue(task_id)
    assert queue.size() == 1


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def test_worker_refuses_task_held_by_another_worker(settings: Settings) -> None:
    db, task_id = await _make_task(settings)
    orchestrator = _RecordingOrchestrator()
    queue = MemoryTaskQueue()
    worker = TaskWorker(
        settings=settings.model_copy(update={"worker_name": "worker-b"}),
        db=db,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        queue=queue,
    )
    try:
        assert await claim_task(db, task_id, "worker-a", ttl_seconds=120) is True
        await queue.enqueue(task_id)
        await worker.start()
        await asyncio.sleep(0.4)
        await worker.stop()
        assert orchestrator.calls == []  # aucun effet : la tâche était détenue
    finally:
        await db.dispose()


async def test_graceful_stop_waits_for_inflight_task(settings: Settings) -> None:
    db, task_id = await _make_task(settings)
    orchestrator = _RecordingOrchestrator(delay=0.4)
    queue = MemoryTaskQueue()
    worker = TaskWorker(settings=settings, db=db, orchestrator=orchestrator, queue=queue)  # type: ignore[arg-type]
    try:
        await worker.start()
        await queue.enqueue(task_id)
        await asyncio.sleep(0.1)
        await worker.stop(drain_seconds=3.0)
        assert orchestrator.calls == [task_id]
        assert worker.processed == 1
    finally:
        await db.dispose()


async def test_worker_logs_do_not_contain_secrets(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "sk-test-SECRET-0000"
    runtime_settings = settings.model_copy(update={"google_api_key": secret})
    db, task_id = await _make_task(runtime_settings)
    worker = TaskWorker(
        settings=runtime_settings,
        db=db,
        orchestrator=_RecordingOrchestrator(),  # type: ignore[arg-type]
        queue=MemoryTaskQueue(),
    )
    try:
        caplog.set_level("DEBUG", logger="kwes")
        await worker.start()
        await worker.stop()
        assert secret not in caplog.text
        assert "sk-test" not in caplog.text
    finally:
        await db.dispose()


# ---------------------------------------------------------------------------
# Séparation réelle API / worker
# ---------------------------------------------------------------------------
def test_api_starts_without_inline_worker(
    settings: Settings, fake_fetcher, headers: dict[str, str]
) -> None:
    offline = settings.model_copy(update={"worker_inline": False})
    application = create_app(offline)
    application.state.fetcher = fake_fetcher
    with TestClient(application) as client:
        assert application.state.worker is None
        response = client.post(
            "/api/v1/tasks",
            json={"goal": "Préparer un plan de lancement"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        task_id = response.json()["id"]
        # Sans worker, la tâche reste en attente : l'API ne l'exécute pas.
        time.sleep(0.5)
        detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
        assert detail["status"] in ("planning", "queued"), detail
        assert detail["progress"] == 0


async def test_worker_built_separately_processes_api_task(
    settings: Settings, fake_fetcher
) -> None:
    """Le worker démarre avec ses propres composants et termine une tâche en file."""
    offline = settings.model_copy(update={"worker_inline": False})
    application = create_app(offline)
    application.state.fetcher = fake_fetcher
    with TestClient(application) as client:
        from tests.conftest import _headers  # type: ignore[attr-defined]

        user_id = uuid.uuid4()
        headers = _headers(offline, user_id, "p0@kwes.local")
        response = client.post(
            "/api/v1/tasks", json={"goal": "Rédiger une note de synthèse"}, headers=headers
        )
        assert response.status_code == 201, response.text
        task_id = uuid.UUID(response.json()["id"])

        # Composants partagés : mêmes base, registre et file que l'API.
        worker = TaskWorker(
            settings=offline,
            db=application.state.db,
            orchestrator=application.state.orchestrator,
            queue=application.state.queue,
        )
        await worker.start()
        deadline = asyncio.get_running_loop().time() + 20
        status = None
        while asyncio.get_running_loop().time() < deadline:
            detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
            status = detail["status"]
            if status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.1)
        await worker.stop()
        assert status == "completed", status
        assert worker.processed == 1


async def test_build_runtime_exposes_same_components(settings: Settings) -> None:
    runtime = await build_runtime(settings)
    try:
        assert runtime.queue.backend == "memory"
        assert runtime.orchestrator is not None
        assert runtime.db is not None
    finally:
        await runtime.aclose()
