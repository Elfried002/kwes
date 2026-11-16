"""File de tâches : Redis si disponible, sinon file in-process (tests/dev).

Le contrat impose une reprise des tâches orphelines au démarrage : la file est
volontairement simple (liste Redis / asyncio.Queue) et la source de vérité reste
la base de données (statuts des tâches).
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


class TaskQueue(Protocol):
    backend: str

    async def enqueue(self, task_id: uuid.UUID) -> None: ...

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None: ...

    async def close(self) -> None: ...


class MemoryTaskQueue:
    backend = "memory"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()

    async def enqueue(self, task_id: uuid.UUID) -> None:
        await self._queue.put(task_id)

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def close(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    def size(self) -> int:
        return self._queue.qsize()


class RedisTaskQueue:
    backend = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    async def connect(cls, url: str) -> "RedisTaskQueue":
        client = Redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=2.0,
        )
        await client.ping()
        return cls(client)

    async def enqueue(self, task_id: uuid.UUID) -> None:
        try:
            await self._client.lpush(QUEUE_KEY, str(task_id))
        except RedisError as exc:
            logger.error("Enqueue Redis impossible: %s", type(exc).__name__)
            raise

    async def dequeue(self, timeout: float = 1.0) -> uuid.UUID | None:
        try:
            item = await self._client.brpop([QUEUE_KEY], timeout=max(1, int(timeout)))
        except RedisError as exc:
            logger.warning("Dequeue Redis en erreur: %s", type(exc).__name__)
            await asyncio.sleep(timeout)
            return None
        if not item:
            return None
        _key, value = item
        try:
            return uuid.UUID(str(value))
        except ValueError:
            logger.error("Identifiant de tâche invalide dans la file Redis")
            return None

    async def heartbeat(self, ttl_seconds: int) -> None:
        try:
            await self._client.set("kwes:worker:heartbeat", "alive", ex=ttl_seconds)
        except RedisError:
            pass

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
        queue = await RedisTaskQueue.connect(settings.redis_url)
        logger.info("File de tâches: Redis.")
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
