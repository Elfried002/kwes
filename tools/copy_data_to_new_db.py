"""Copie des données du PostgreSQL historique vers le nouveau serveur.

Petit jeu de données : un COPY par table, dans l'ordre des dépendances, évite
d'installer pg_dump. Le tunnel SSH ouvert par l'appelant expose le PostgreSQL
distant sur 127.0.0.1:15432.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql

from app.core.config import Settings

OLD = Settings().database_url.replace("postgresql+psycopg://", "postgresql://")
NEW_PW = os.environ["NEW_OWNER_PW"]
NEW = f"postgresql://kwes:{NEW_PW}@127.0.0.1:15432/kwes"

ORDER = [
    "users",
    "profiles",
    "tenants",
    "tenant_memberships",
    "tenant_settings",
    "skills",
    "skill_versions",
    "conversations",
    "messages",
    "tasks",
    "task_steps",
    "executions",
    "memories",
    "approvals",
    "integrations",
    "audit_logs",
    "notifications",
    "device_connectors",
    "device_commands",
    "documents",
    "evidence",
    "voice_sessions",
]


def tables(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "select tablename from pg_tables where schemaname='public'"
        ).fetchall()
    }


def copy_table(old, new, table: str) -> int:
    with old.cursor().copy(
        sql.SQL("copy {} to stdout with (format csv)").format(sql.Identifier(table))
    ) as source:
        with new.cursor() as dst:
            with dst.copy(
                sql.SQL("copy {} from stdin with (format csv)").format(sql.Identifier(table))
            ) as target:
                for chunk in source:
                    target.write(chunk)
    return new.execute(
        sql.SQL("select count(*) from {}").format(sql.Identifier(table))
    ).fetchone()[0]


def main() -> None:
    with psycopg.connect(OLD) as old, psycopg.connect(NEW, autocommit=False) as new:
        old_tables = tables(old)
        new_tables = tables(new)
        present = [t for t in ORDER if t in old_tables and t in new_tables]

        with new.cursor() as dst:
            dst.execute(
                sql.SQL("truncate auth.users, {} cascade").format(
                    sql.SQL(", ").join(sql.Identifier(t) for t in present)
                )
            )
        new.commit()

        # 1. auth.users d'abord : les profils y font référence.
        with old.cursor().copy("copy auth.users to stdout with (format csv)") as source:
            with new.cursor() as dst:
                with dst.copy("copy auth.users from stdin with (format csv)") as target:
                    for chunk in source:
                        target.write(chunk)
        new.commit()
        print("  auth.users           ", new.execute("select count(*) from auth.users").fetchone()[0])

        # 2. Tables métier dans l'ordre des dépendances.
        total = 0
        for table in present:
            n = copy_table(old, new, table)
            new.commit()
            total += n
            print(f"  {table:22} {n:>6} lignes")

        print(f"total copié: {total}")


if __name__ == "__main__":
    main()
