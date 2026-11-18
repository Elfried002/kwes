#!/usr/bin/env python3
"""Durcissement multi-tenant : rôle applicatif sans privilège + RLS forcée.

À exécuter une fois, avec le rôle administrateur (`kwes`). Idempotent.

- crée `kwes_app` : LOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE ;
- donne les droits DML sur le schéma public, rien de plus ;
- force la RLS sur toutes les tables qui la portent déjà (le propriétaire lui-même
  est alors soumis aux politiques) ;
- vérifie qu'une session sans contexte ne voit rien et qu'avec contexte elle voit
  uniquement ses lignes.
"""
import asyncio
import secrets
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402


async def main() -> int:
    settings = Settings()
    admin_url = settings.database_url
    password = secrets.token_urlsafe(24)

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        exists = (
            await conn.execute(text("select 1 from pg_roles where rolname='kwes_app'"))
        ).scalar()
        if exists:
            await conn.execute(text(f"alter role kwes_app with password '{password}'"))
            print("rôle kwes_app : mot de passe renouvelé")
        else:
            await conn.execute(
                text(
                    f"create role kwes_app login password '{password}' "
                    "nosuperuser nocreatedb nocreaterole noinherit nobypassrls"
                )
            )
            print("rôle kwes_app : créé")

        for statement in (
            "grant usage on schema public to kwes_app",
            "grant select, insert, update, delete on all tables in schema public to kwes_app",
            "grant usage, select on all sequences in schema public to kwes_app",
            "alter default privileges in schema public grant select, insert, update, delete on tables to kwes_app",
            "alter default privileges in schema public grant usage, select on sequences to kwes_app",
        ):
            await conn.execute(text(statement))

        tables = (
            await conn.execute(
                text(
                    "select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace "
                    "where n.nspname='public' and c.relkind='r' and c.relrowsecurity"
                )
            )
        ).scalars().all()
        for table in tables:
            await conn.execute(text(f'alter table public."{table}" force row level security'))
        print(f"RLS forcée sur {len(tables)} tables")

        # Vérification : sans contexte, aucune ligne visible.
        await conn.execute(text("set role kwes_app"))
        await conn.execute(text("select set_config('request.jwt.claims', '', false)"))
        visible_tasks = (await conn.execute(text("select count(*) from tasks"))).scalar()
        print("sans contexte, tâches visibles :", visible_tasks)

        user_id = (
            await conn.execute(
                text("select user_id from tasks group by user_id order by count(*) desc limit 1")
            )
        ).scalar()
        await conn.execute(
            text("select set_config('request.jwt.claims', :v, false)"),
            {"v": f'{{"sub":"{user_id}"}}'},
        )
        scoped = (await conn.execute(text("select count(*) from tasks"))).scalar()
        total = 0
        await conn.execute(text("reset role"))
        total = (await conn.execute(text("select count(*) from tasks"))).scalar()
        print(f"avec contexte ({user_id}) : {scoped} / {total} tâches visibles")

    await engine.dispose()

    print("\nAjoutez ces deux lignes à backend/.env :")
    print(f"KWES_DB_APP_PASSWORD={password}")
    print(f"DATABASE_URL=postgresql+psycopg://kwes_app:{password}@127.0.0.1:5432/kwes")
    return 0 if visible_tasks == 0 and 0 < scoped <= total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
