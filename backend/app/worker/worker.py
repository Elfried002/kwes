"""Worker de consommation des missions : heartbeat, reprise des orphelines, retries."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.agent.orchestrator import TERMINAL_TASK_STATUSES, Orchestrator
from app.core.config import Settings
from app.core.utils import utcnow
from app.db.base import Database
from app.db.models import Task
from app.worker.queue import RedisTaskQueue, TaskQueue

logger = logging.getLogger("kwes.worker")


class TaskWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        orchestrator: Orchestrator,
        queue: TaskQueue,
    ) -> None:
        self.settings = settings
        self.db = db
        self.orchestrator = orchestrator
        self.queue = queue
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self.heartbeat_at = None
        self.processed = 0
        self.failures = 0

    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        await self.recover_orphans()
        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="kwes-heartbeat"))
        for index in range(max(1, self.settings.worker_concurrency)):
            self._tasks.append(
                asyncio.create_task(self._consume_loop(index), name=f"kwes-worker-{index}")
            )
        logger.info(
            "Worker démarré (concurrency=%s, queue=%s)",
            self.settings.worker_concurrency,
            self.queue.backend,
        )

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.queue.close()
        logger.info("Worker arrêté (processed=%s failures=%s)", self.processed, self.failures)

    # ------------------------------------------------------------------
    async def _consume_loop(self, index: int) -> None:
        while self._running:
            try:
                task_id = await self.queue.dequeue(timeout=self.settings.worker_poll_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Worker %s: lecture file en erreur (%s)", index, type(exc).__name__)
                await asyncio.sleep(1.0)
                continue
            if task_id is None:
                continue
            await self.handle_task(task_id)

    async def handle_task(self, task_id: uuid.UUID) -> None:
        try:
            outcome = await self.orchestrator.execute_task(task_id)
            self.processed += 1
            logger.info("Task %s -> %s", task_id, outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failures += 1
            logger.exception("Échec inattendu du worker pour la tâche %s", task_id)
            await self._mark_worker_failure(task_id)

    async def _mark_worker_failure(self, task_id: uuid.UUID) -> None:
        try:
            async with self.db.session() as session:
                task = await session.get(Task, task_id)
                if task is None or task.status in TERMINAL_TASK_STATUSES:
                    return
                task.status = "failed"
                task.error_code = "WORKER_ERROR"
                task.completed_at = utcnow()
                task.result_summary = "Erreur interne du worker : la mission n'a pas abouti."
                await session.commit()
                user_id = task.user_id
            from app.core.events import event_bus

            await event_bus.publish(
                user_id,
                "task.failed",
                {"task_id": str(task_id), "error_code": "WORKER_ERROR", "message": "Erreur interne du worker."},
            )
        except Exception:
            logger.exception("Impossible de marquer la tâche %s en échec", task_id)

    # ------------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        interval = max(1.0, self.settings.worker_heartbeat_interval_seconds)
        while self._running:
            self.heartbeat_at = utcnow()
            if isinstance(self.queue, RedisTaskQueue):
                await self.queue.heartbeat(self.settings.worker_heartbeat_ttl_seconds)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    async def recover_orphans(self) -> int:
        """Remet en file les tâches sans worker : queued, ou running/planning périmées."""
        if not self.settings.orphan_recovery_enabled:
            return 0
        cutoff = utcnow() - timedelta(seconds=self.settings.worker_heartbeat_ttl_seconds)
        recovered: list[uuid.UUID] = []
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(Task).where(
                        Task.status.in_(("queued", "planning", "running")),
                    )
                )
            ).scalars().all()
            for task in rows:
                updated = task.updated_at
                if updated is not None and updated.tzinfo is None:
                    updated = updated.replace(tzinfo=cutoff.tzinfo)
                stale = updated is None or updated < cutoff
                if task.status == "queued" or stale:
                    task.status = "queued"
                    task.error_code = None
                    recovered.append(task.id)
            await session.commit()

        for task_id in recovered:
            await self.queue.enqueue(task_id)
        if recovered:
            logger.warning("Reprise de %s tâche(s) orpheline(s) au démarrage.", len(recovered))
        return len(recovered)
