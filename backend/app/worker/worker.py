"""Worker de consommation des missions : heartbeat, reprise, verrou d'exécution.

Le worker peut tourner dans l'API (tests) ou dans son propre processus
(``python -m app.worker``). La logique métier reste l'orchestrateur existant :
ce module ne fait que réclamer une tâche, l'exécuter, enregistrer le résultat et
libérer le verrou.
"""

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
from app.worker.claims import claim_task, release_all, release_task
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
        self.owner = settings.worker_name
        self._tasks: list[asyncio.Task[None]] = []
        self._inflight: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._running = False
        self.heartbeat_at = None
        self.processed = 0
        self.failures = 0

    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        # 1. Ce que ce worker avait en cours avant son dernier arrêt.
        await self.queue.requeue_processing()
        # 2. Les tâches sans worker encore vivant.
        await self.recover_orphans()
        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="kwes-heartbeat"))
        self._tasks.append(asyncio.create_task(self._sweep_loop(), name="kwes-sweep"))
        for index in range(max(1, self.settings.worker_concurrency)):
            self._tasks.append(
                asyncio.create_task(self._consume_loop(index), name=f"kwes-consume-{index}")
            )
        logger.info(
            "Worker démarré (id=%s, concurrency=%s, queue=%s)",
            self.owner,
            self.settings.worker_concurrency,
            self.queue.backend,
        )

    async def stop(self, drain_seconds: float | None = None) -> None:
        """Arrêt propre : plus de nouvelle tâche, on laisse finir l'en-cours."""
        drain = self.settings.worker_drain_seconds if drain_seconds is None else drain_seconds
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        pending = [task for task in self._inflight.values() if not task.done()]
        if pending:
            logger.info("Arrêt : attente de %s tâche(s) en cours (max %.0f s).", len(pending), drain)
            done, still = await asyncio.wait(pending, timeout=max(0.0, drain))
            for task in still:
                task.cancel()
            if still:
                await asyncio.gather(*still, return_exceptions=True)
                logger.warning("Arrêt : %s tâche(s) interrompue(s), elles seront reprises.", len(still))
        self._inflight.clear()

        released = await release_all(self.db, self.owner)
        if released:
            logger.info("Arrêt : %s verrou(s) libéré(s).", released)
        await self.queue.requeue_processing()
        await self.queue.close()
        logger.info("Worker arrêté (processed=%s failures=%s)", self.processed, self.failures)

    # ------------------------------------------------------------------
    async def _consume_loop(self, index: int) -> None:
        while self._running:
            try:
                task_id = await self.queue.claim(timeout=self.settings.worker_poll_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Worker %s: lecture file en erreur (%s)", index, type(exc).__name__)
                await asyncio.sleep(1.0)
                continue
            if task_id is None:
                continue
            if task_id in self._inflight:
                # Déjà traité par ce processus : on ne double pas l'exécution.
                await self.queue.ack(task_id)
                continue
            self._inflight[task_id] = asyncio.create_task(
                self.handle_task(task_id), name=f"kwes-task-{task_id}"
            )

    async def handle_task(self, task_id: uuid.UUID) -> None:
        claimed = False
        try:
            claimed = await claim_task(
                self.db, task_id, self.owner, self.settings.worker_claim_ttl_seconds
            )
            if not claimed:
                logger.info("Task %s ignorée : déjà détenue par un autre worker.", task_id)
                return
            outcome = await self.orchestrator.execute_task(task_id)
            self.processed += 1
            logger.info("Task %s -> %s", task_id, outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failures += 1
            logger.exception("Échec inattendu du worker pour la tâche %s", task_id)
            await self._mark_worker_failure(task_id)
        finally:
            if claimed:
                try:
                    await release_task(self.db, task_id, self.owner)
                except Exception:
                    logger.exception("Libération du verrou impossible task=%s", task_id)
            await self.queue.ack(task_id)
            self._inflight.pop(task_id, None)

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

    async def _sweep_loop(self) -> None:
        """Rattrapage périodique : Redis perdu, mise en file échouée, worker mort."""
        interval = max(5.0, float(self.settings.worker_sweep_interval_seconds))
        while self._running:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            if not self._running:
                break
            try:
                await self.recover_orphans()
            except Exception:
                logger.exception("Balayage périodique en erreur (poursuite).")

    async def recover_orphans(self) -> int:
        """Remet en file les tâches sans worker : queued, ou running/planning périmées."""
        if not self.settings.orphan_recovery_enabled:
            return 0
        cutoff = utcnow() - timedelta(seconds=self.settings.worker_heartbeat_ttl_seconds)
        recovered: list[uuid.UUID] = []
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(Task).where(Task.status.in_(("queued", "planning", "running")))
                )
            ).scalars().all()
            for task in rows:
                updated = task.updated_at
                if updated is not None and updated.tzinfo is None:
                    updated = updated.replace(tzinfo=cutoff.tzinfo)
                stale = updated is None or updated < cutoff
                # Une tâche détenue par un worker encore vivant n'est pas reprise.
                held = task.claimed_by is not None and not stale
                if held:
                    continue
                if task.status == "queued" or stale:
                    task.status = "queued"
                    task.error_code = None
                    task.claimed_by = None
                    task.claimed_at = None
                    recovered.append(task.id)
            await session.commit()

        for task_id in recovered:
            # Redis dédoublonne : une tâche déjà en file n'est pas ajoutée deux fois.
            await self.queue.enqueue(task_id)
        if recovered:
            logger.warning("Reprise de %s tâche(s) orpheline(s) remise(s) en file.", len(recovered))
        return len(recovered)

    def status(self) -> dict[str, object]:
        return {
            "worker": self.owner,
            "running": self._running,
            "queue": self.queue.backend,
            "inflight": len(self._inflight),
            "processed": self.processed,
            "failures": self.failures,
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
        }
