"""Registre de preuves et pipeline de recherche, sans réseau réel."""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.db.base import Database
from app.db.models import Evidence, Profile
from app.research.core import SearchHit
from app.research.evidence import build_excerpt, content_fingerprint, list_for_user, record
from app.research.service import ResearchService
from app.skills.base import FetchedPage


def _open(settings: Settings) -> Settings:
    """Web public autorisé (décision produit) : plus de filtre d'allowlist."""
    return settings.model_copy(update={"browser_open_web": True})


async def _db(settings: Settings) -> Database:
    db = Database(settings.database_url)
    await db.create_all()
    return db


async def _user(db: Database) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with db.session() as session:
        session.add(Profile(id=user_id, display_name="Chercheur"))
        await session.commit()
    return user_id


async def test_record_creates_one_evidence_per_content(settings: Settings) -> None:
    db = await _db(settings)
    user = await _user(db)
    try:
        first = await record(
            db,
            user_id=user,
            task_id=None,
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            domain="example.com",
            title="Titre",
            content="Un contenu stable et suffisamment long pour être haché.",
            provider="searxng",
        )
        second = await record(
            db,
            user_id=user,
            task_id=None,
            url="https://example.com/a?utm_source=x",
            canonical_url="https://example.com/a",
            domain="example.com",
            title="Titre",
            content="Un   contenu stable et suffisamment long pour être haché.",
            provider="wikipedia",
        )
        assert first and first == second  # même empreinte => même preuve
        async with db.session() as session:
            rows = (await session.execute(__import__("sqlalchemy").select(Evidence))).scalars().all()
        assert len(rows) == 1
    finally:
        await db.dispose()


async def test_evidence_is_isolated_between_users(settings: Settings) -> None:
    db = await _db(settings)
    alice, bob = await _user(db), await _user(db)
    try:
        await record(
            db, user_id=alice, task_id=None, url="https://a.fr", canonical_url="https://a.fr",
            domain="a.fr", title="Alice", content="Contenu d'Alice, suffisamment long pour être gardé.",
            provider="searxng",
        )
        await record(
            db, user_id=bob, task_id=None, url="https://b.fr", canonical_url="https://b.fr",
            domain="b.fr", title="Bob", content="Contenu de Bob, suffisamment long pour être gardé aussi.",
            provider="searxng",
        )
        alice_rows = await list_for_user(db, alice)
        bob_rows = await list_for_user(db, bob)
        assert [r["title"] for r in alice_rows] == ["Alice"]
        assert [r["title"] for r in bob_rows] == ["Bob"]
    finally:
        await db.dispose()


def test_fingerprint_ignores_whitespace_and_case() -> None:
    assert content_fingerprint("Bonjour   le Monde") == content_fingerprint("bonjour le monde\n")


def test_excerpt_cuts_on_sentence() -> None:
    text = ("Première phrase courte. " * 40)
    excerpt = build_excerpt(text, limit=100)
    assert excerpt.endswith(".") and len(excerpt) <= 120


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class _FakeRouter:
    def __init__(self, hits, warnings=None) -> None:
        self.hits = hits
        self.warnings = warnings or []
        self.calls: list[str] = []

    async def search(self, query: str, limit: int, language: str):
        self.calls.append(query)
        return self.hits, ["searxng"], self.warnings


class _FakeClient:
    async def aclose(self) -> None:
        return None


@pytest.fixture
def patch_router(monkeypatch):
    def apply(router):
        async def _build(**kwargs):
            return router, _FakeClient()

        monkeypatch.setattr("app.research.service.build_router", _build)
        return router

    return apply


async def test_service_reads_pages_and_records_evidence(settings: Settings, patch_router) -> None:
    hits = [
        SearchHit("https://gouv.fr/rapport", "Rapport officiel", "extrait", "searxng", 0),
        SearchHit("https://reddit.com/post", "Avis", "extrait", "searxng", 1),
    ]
    router = patch_router(_FakeRouter(hits))

    async def fetcher(url: str) -> FetchedPage:
        # Contenu distinct par URL : deux pages identiques partageraient la
        # même empreinte et donc la même preuve (comportement voulu).
        body = f"Source {url}. " + "Les assistants vocaux progressent en Afrique de l Ouest. " * 12
        return FetchedPage(
            url=url, final_url=url, status=200, content_type="text/html",
            text=f"<html><head><title>Rapport {url}</title></head><body><main>{body}</main></body></html>",
        )

    db = await _db(settings)
    user = await _user(db)
    try:
        service = ResearchService(_open(settings))
        outcome = await service.run(
            query="assistants vocaux Afrique",
            depth="standard",
            db=db,
            user_id=user,
            fetcher=fetcher,
            allowlist=[],
        )
        assert router.calls  # le plan a bien été exécuté
        assert any(s.status == "lue" for s in outcome.sources)
        assert outcome.evidence_ids
        assert "[1]" in outcome.answer
        async with db.session() as session:
            rows = (await session.execute(__import__("sqlalchemy").select(Evidence))).scalars().all()
        assert len(rows) == len(outcome.evidence_ids)
    finally:
        await db.dispose()


async def test_service_returns_empty_answer_when_no_source(settings: Settings, patch_router) -> None:
    patch_router(_FakeRouter([]))
    service = ResearchService(_open(settings))
    outcome = await service.run(query="sujet introuvable", depth="quick", db=None, user_id=None)
    assert outcome.sources == []
    assert outcome.answer == ""
    assert any("Aucune source" in w for w in outcome.warnings)


async def test_service_does_not_treat_search_hits_as_evidence(settings: Settings, patch_router) -> None:
    hits = [SearchHit("https://example.com/x", "Titre", "extrait", "searxng", 0)]
    patch_router(_FakeRouter(hits))

    async def broken_fetcher(url: str) -> FetchedPage:
        raise RuntimeError("réseau indisponible")

    db = await _db(settings)
    user = await _user(db)
    try:
        service = ResearchService(_open(settings))
        outcome = await service.run(
            query="q", depth="quick", db=db, user_id=user, fetcher=broken_fetcher, allowlist=[]
        )
        assert outcome.evidence_ids == []
        assert outcome.answer == ""
        assert any("illisible" in w for w in outcome.warnings)
    finally:
        await db.dispose()


async def test_pdf_source_is_extracted_and_recorded(settings: Settings, patch_router) -> None:
    from tests.test_research_pdf import LONG_TEXT, _build_pdf

    hits = [SearchHit("https://example.com/doc.pdf", "Document", "extrait", "searxng", 0)]
    patch_router(_FakeRouter(hits))

    async def pdf_fetcher(url: str) -> FetchedPage:
        payload = _build_pdf(LONG_TEXT)
        return FetchedPage(
            url=url, final_url=url, status=200, content_type="application/pdf",
            text="", raw=payload,
        )

    db = await _db(settings)
    user = await _user(db)
    try:
        service = ResearchService(_open(settings))
        outcome = await service.run(
            query="rapport", depth="quick", db=db, user_id=user, fetcher=pdf_fetcher, allowlist=[]
        )
        assert outcome.sources[0].status == "lue"
        assert outcome.evidence_ids
    finally:
        await db.dispose()
