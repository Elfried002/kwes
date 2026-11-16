"""Le seed des skills doit supporter une montée de version sans violer l'unicité.

Régression constatée en P1 : une seule version active est autorisée par skill en
base (`uq_skill_versions_one_active`). Insérer la nouvelle version sans
rétrograder l'ancienne faisait échouer le démarrage de l'API (502 en production).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.base import Database
from app.db.models import SkillVersion
from app.main import seed_skills


class _Registry:
    def __init__(self, version: str) -> None:
        self.version = version

    def manifests(self) -> list[dict]:
        return [
            {
                "name": "skill_test_p1",
                "description": "Skill de test",
                "version": self.version,
                "artifact_hash": f"hash-{self.version}",
            }
        ]


@pytest.mark.asyncio
async def test_seed_skills_supports_version_bump(settings: Settings) -> None:
    db = Database(settings.database_url)
    await db.create_all()
    try:
        await seed_skills(db, _Registry("1.0.0"))
        await seed_skills(db, _Registry("1.1.0"))
        async with db.session() as session:
            rows = (
                await session.execute(
                    select(SkillVersion).order_by(SkillVersion.created_at)
                )
            ).scalars().all()
        assert [r.version for r in rows] == ["1.0.0", "1.1.0"]
        assert [r.status for r in rows] == ["deprecated", "active"]
    finally:
        await db.dispose()
