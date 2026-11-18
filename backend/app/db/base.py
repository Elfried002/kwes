"""Connexion base de données asynchrone (SQLAlchemy 2.x).

Production : PostgreSQL via psycopg 3 (`postgresql+psycopg://`).
Tests : SQLite via aiosqlite (`sqlite+aiosqlite://`), avec les limites
documentées dans README.md (pas de types natifs PG, pas de RLS, contraintes
partielles).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.models import Base

logger = logging.getLogger("kwes.db")


def _normalize_url(url: str) -> str:
    """Force un driver asynchrone compatible."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Database:
    def __init__(self, url: str, *, pool_size: int = 5, echo: bool = False) -> None:
        self.url = _normalize_url(url)
        self.is_sqlite = self.url.startswith("sqlite")
        kwargs: dict[str, Any] = {"echo": echo, "future": True}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in self.url:
                kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = max(1, pool_size)
        self.engine: AsyncEngine = create_async_engine(self.url, **kwargs)
        if self.is_sqlite:
            from sqlalchemy import event

            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.execute("PRAGMA foreign_keys=ON")
                finally:
                    cursor.close()

        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - dépend de l'infra
            logger.warning("Database ping failed: %s", type(exc).__name__)
            return False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                # La RLS est posée au niveau *session* (rôle + claims) : la
                # connexion retourne au pool, il faut la rendre neutre, sinon la
                # requête suivante hérite de l'identité précédente.
                if not self.is_sqlite:
                    try:
                        await session.execute(text("reset role"))
                        await session.execute(
                            text("select set_config('request.jwt.claims', '', false)")
                        )
                        await session.commit()
                    except Exception:  # noqa: BLE001
                        await session.rollback()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : une session par requête, commit en fin de requête."""
    db: Database = request.app.state.db
    async with db.session() as session:
        yield session
