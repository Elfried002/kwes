"""Point d'entrée du service worker : ``python -m app.worker``.

Cycle de vie
------------
* démarrage : connexion Redis/PostgreSQL, reprise des tâches en cours, boucles ;
* arrêt (SIGTERM/SIGINT) : plus de nouvelle tâche, attente des tâches en cours
  (``WORKER_DRAIN_SECONDS``), libération des verrous, remise en file, sortie 0 ;
* ``--check`` : vérifie la fraîcheur du battement de cœur sans démarrer le worker.

Aucun secret n'est journalisé : la configuration est résumée par des booléens et
des noms d'hôtes, jamais par des valeurs d'identifiants.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import timedelta

from app.core.config import get_settings
from app.core.utils import utcnow
from app.worker.runtime import build_runtime
from app.worker.worker import TaskWorker

logger = logging.getLogger("kwes.worker.service")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,  # journald capture stdout
    )


async def _run() -> int:
    settings = get_settings()
    _configure_logging(settings.log_level)

    runtime = await build_runtime(settings)
    worker = TaskWorker(
        settings=settings, db=runtime.db, orchestrator=runtime.orchestrator, queue=runtime.queue
    )

    stop_event = asyncio.Event()

    def _request_stop(signum: int) -> None:
        logger.info("Signal %s reçu : arrêt demandé.", signal.Signals(signum).name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop, sig)

    await worker.start()
    logger.info(
        "Service worker prêt %s",
        json.dumps(
            {
                "worker": worker.owner,
                "queue": worker.queue.backend,
                "concurrency": settings.worker_concurrency,
                "drain_seconds": settings.worker_drain_seconds,
            }
        ),
    )
    try:
        await stop_event.wait()
    finally:
        await worker.stop()
        await runtime.aclose()
    return 0


async def _check() -> int:
    """Vérifie que le worker tourne (battement de cœur Redis récent)."""
    from redis.asyncio import Redis

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1.0)
    try:
        value = await redis.get(f"kwes:worker:{settings.worker_name}:heartbeat")
        ttl = await redis.ttl(f"kwes:worker:{settings.worker_name}:heartbeat")
    finally:
        await redis.aclose()

    healthy = value is not None and ttl > 0
    print(
        json.dumps(
            {
                "worker": settings.worker_name,
                "healthy": healthy,
                "heartbeat": value,
                "ttl_seconds": ttl,
                "checked_at": utcnow().isoformat(),
                "stale_after": str(timedelta(seconds=settings.worker_heartbeat_ttl_seconds)),
            }
        )
    )
    return 0 if healthy else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker de missions Kwes")
    parser.add_argument("--check", action="store_true", help="vérifie le battement de cœur")
    args = parser.parse_args(argv)
    if args.check:
        return asyncio.run(_check())
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover - filet de sécurité
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
