"""File de tâches durable : Redis en production, file mémoire en tests/dev.

Garanties réelles (P0)
----------------------
* **Au moins une fois** : une tâche sortie de la file est déplacée atomiquement
  dans une liste « en cours » propre au worker (``BLMOVE``). Si le worker meurt,
  son contenu est remis en file au démarrage suivant, et la reprise en base
  (``recover_orphans``) couvre les tâches non réclamées.
* **Pas d'exécution simultanée** : le verrou d'exécution est porté par la base
  (``tasks.claimed_by``), pas par Redis. Deux workers qui sortiraient deux fois
  le même identifiant ne peuvent pas l'exécuter en parallèle : le second échoue
  au ``claim`` et abandonne sans effet.
* **Pas exactement une fois** : une étape interrompue entre son exécution et son
  enregistrement peut être rejouée. Les étapes terminées ne le sont jamais
  (statut vérifié avant exécution) et les actions sensibles restent derrière une
  approbation liée au hachage du payload.

La source de vérité reste PostgreSQL : Redis n'est qu'un accélérateur. Une perte
de Redis ne doit jamais corrompre l'état d'une mission.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

logger = logging.getLogger("kwes.queue")

QUEUE_KEY = "kwes:queue:tasks"
QUEUE_IDS_KEY = "kwes:queue:ids"
PROCESSING_PREFIX = "kwes:queue:processing:"


class TaskQueue(Protocol):
    backend: str

    async def enqueue(self, task_id: uuid.UUID) -> None: ...

    async def claim(self, timeout: float = 1.0) -> uuid.UUID | None: ...

    async def ack(self, task_id: uuid.UUID) -> None: ...

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None: ...

    async def requeue_processing(self) -> int: ...

    async def close(self) -> None: ...


class MemoryTaskQueue:
    """File en mémoire : tests uniquement, aucune garantie de reprise."""

    backend = "memory"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._inflight: set[uuid.UUID] = set()
        self._known: set[uuid.UUID] = set()

    async def enqueue(self, task_id: uuid.UUID) -> None:
        # Dédoublonnage : mêmes garanties que la file Redis (SADD).
        if task_id in self._known or task_id in self._inflight:
            return
        self._known.add(task_id)
        await self._queue.put(task_id)

    async def claim(self, timeout: float = 1.0) -> uuid.UUID | None:
        try:
            task_id = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        self._known.discard(task_id)
        self._inflight.add(task_id)
        return task_id

    async def ack(self, task_id: uuid.UUID) -> None:
        self._known.discard(task_id)
        self._inflight.discard(task_id)

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None:
        return await self.claim(timeout)

    async def requeue_processing(self) -> int:
        pending = list(self._inflight)
        self._inflight.clear()
        for task_id in pending:
            await self.enqueue(task_id)
        return len(pending)

    async def close(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
        self._inflight.clear()
        self._known.clear()

    def size(self) -> int:
        return self._queue.qsize()


class RedisTaskQueue:
    """File Redis avec liste « en cours » par worker et dédoublonnage des entrées."""

    backend = "redis"

    def __init__(self, client: Redis, name: str = "kwes-worker-1") -> None:
        self._client = client
        self._name = name
        self.processing_key = f"{PROCESSING_PREFIX}{name}"

    @classmethod
    async def connect(cls, url: str, name: str = "kwes-worker-1") -> "RedisTaskQueue":
        client = Redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=2.0,
        )
        await client.ping()
        return cls(client, name=name)

    # ------------------------------------------------------------------
    async def enqueue(self, task_id: uuid.UUID) -> None:
        value = str(task_id)
        try:
            # SADD renvoie 1 si l'identifiant n'était pas déjà en file.
            added = await self._client.sadd(QUEUE_IDS_KEY, value)
            if added:
                await self._client.lpush(QUEUE_KEY, value)
        except RedisError as exc:
            logger.error("Enqueue Redis impossible: %s", type(exc).__name__)
            raise

    async def claim(self, timeout: float = 1.0) -> uuid.UUID | None:
        """Déplace atomiquement la tâche de la file vers la liste « en cours »."""
        try:
            value = await self._client.blmove(
                QUEUE_KEY, self.processing_key, max(1, int(timeout)), "RIGHT", "LEFT"
            )
        except RedisError as exc:
            logger.warning("Dequeue Redis en erreur: %s", type(exc).__name__)
            await asyncio.sleep(min(2.0, timeout))
            return None
        if not value:
            return None
        try:
            task_id = uuid.UUID(str(value))
        except ValueError:
            logger.error("Identifiant de tâche invalide dans la file Redis")
            await self._client.lrem(self.processing_key, 0, value)
            return None
        # La tâche est en cours : elle ne doit plus être considérée comme « en file ».
        await self._client.srem(QUEUE_IDS_KEY, value)
        return task_id

    async def ack(self, task_id: uuid.UUID) -> None:
        value = str(task_id)
        try:
            await self._client.lrem(self.processing_key, 0, value)
            await self._client.srem(QUEUE_IDS_KEY, value)
        except RedisError as exc:
            logger.warning("Ack Redis impossible: %s", type(exc).__name__)

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None:
        """Alias historique : ``claim`` sans acquittement immédiat."""
        return await self.claim(timeout)

    async def requeue_processing(self) -> int:
        """Remet en file ce que ce worker avait en cours avant son arrêt."""
        moved = 0
        try:
            while True:
                value = await self._client.rpop(self.processing_key)
                if not value:
                    break
                await self._client.sadd(QUEUE_IDS_KEY, value)
                await self._client.lpush(QUEUE_KEY, value)
                moved += 1
        except RedisError as exc:
            logger.warning("Reprise de la liste en cours impossible: %s", type(exc).__name__)
        if moved:
            logger.warning("Reprise : %s tâche(s) en cours remise(s) en file.", moved)
        return moved

    async def heartbeat(self, ttl_seconds: int) -> None:
        try:
            await self._client.set(f"kwes:worker:{self._name}:heartbeat", "alive", ex=ttl_seconds)
        except RedisError:
            pass

    async def size(self) -> int:
        try:
            return int(await self._client.llen(QUEUE_KEY))
        except RedisError:
            return -1

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except RedisError:
            pass


async def build_queue(settings: Settings) -> TaskQueue:
    if settings.queue_backend == "memory":
        logger.info("File de tâches: mémoire (in-process).")
        return MemoryTaskQueue()

    try:
        queue = await RedisTaskQueue.connect(settings.redis_url, name=settings.worker_name)
        logger.info("File de tâches: Redis (worker=%s).", settings.worker_name)
        return queue
    except Exception as exc:
        if settings.queue_backend == "redis":
            logger.error("Redis demandé mais indisponible (%s) : file mémoire utilisée.", type(exc).__name__)
        else:
            logger.warning(
                "Redis indisponible (%s) : bascule sur la file in-process "
                "(mono-instance, non persistante).",
                type(exc).__name__,
            )
        return MemoryTaskQueue()
