"""Pipeline de recherche : plan → fournisseurs → déduplication → lecture → preuves.

Aucune étape ne « devine » : si rien n'est trouvé ou lu, le résultat le dit et
la réponse reste vide plutôt que d'inventer.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.core.config import Settings
from app.db.base import Database
from app.research.core import (
    ResearchOutcome,
    Source,
    best_passage,
    dedupe_hits,
    score_source,
)
from app.research.evidence import record
from app.research.extract import extract_pdf, looks_like_pdf
from app.research.planner import plan_queries
from app.research.providers import ProviderRouter, ResearchCache, build_router
from app.skills.fetch import extract_readable, sanitize_text, validate_url_shape

logger = logging.getLogger("kwes.research.service")

DEPTH_PLAN = {
    "quick": {"queries": 1, "pages": 2},
    "standard": {"queries": 2, "pages": 4},
    "deep": {"queries": 3, "pages": 5},
}


class ResearchService:
    def __init__(self, settings: Settings, *, cache_client: Any | None = None) -> None:
        self.settings = settings
        self.cache = ResearchCache(
            cache_client,
            ttl_seconds=settings.research_cache_ttl_seconds,
            enabled=settings.research_cache_enabled,
        )

    async def run(
        self,
        *,
        query: str,
        depth: str,
        db: Database | None,
        user_id: uuid.UUID | None,
        task_id: uuid.UUID | None = None,
        fetcher: Any | None = None,
        allowlist: list[str] | None = None,
        language: str = "fr",
    ) -> ResearchOutcome:
        settings = self.settings
        plan = DEPTH_PLAN.get(str(depth), DEPTH_PLAN["standard"])
        queries = plan_queries(query, str(depth), settings.research_max_queries)[: plan["queries"]]
        warnings: list[str] = []
        if not queries:
            return ResearchOutcome(answer="", sources=[], queries=[], warnings=["Requête vide."])

        router, client = await build_router(
            searxng_url=settings.searxng_url,
            cache=self.cache,
            daily_limit=settings.research_provider_daily_limit,
        )
        try:
            # Un fournisseur qui lève ne doit pas faire échouer toute la recherche :
            # chaque requête est isolée et son échec devient un avertissement.
            gathered = await asyncio.gather(
                *(router.search(item, limit=8, language=language) for item in queries),
                return_exceptions=True,
            )
        finally:
            await client.aclose()

        hits = []
        providers_used: list[str] = []
        for item in gathered:
            if isinstance(item, BaseException):
                logger.warning("Recherche en échec (%s)", type(item).__name__)
                warnings.append(f"Recherche indisponible ({type(item).__name__}).")
                continue
            results, used, notes = item
            hits.extend(results)
            providers_used.extend([p for p in used if p not in providers_used])
            warnings.extend([w for w in notes if w not in warnings])

        if not hits:
            warnings.append(
                "Aucune source trouvée : les fournisseurs n'ont rien renvoyé. "
                "Aucune réponse n'est produite pour éviter d'inventer."
            )
            return ResearchOutcome(
                answer="", sources=[], queries=queries, providers_used=[], warnings=warnings
            )

        sources = dedupe_hits(hits)
        for source in sources:
            source.score = score_source(source, query)
        sources.sort(key=lambda s: (-s.score, s.domain))
        selected = sources[: max(1, plan["pages"])]

        if fetcher is not None:
            await self._read_sources(
                selected,
                fetcher=fetcher,
                allowlist=allowlist or [],
                db=db,
                user_id=user_id,
                task_id=task_id,
                warnings=warnings,
                concurrency=settings.research_concurrency,
            )

        answer = self._synthesize(query, selected, warnings)
        return ResearchOutcome(
            answer=answer,
            sources=selected,
            queries=queries,
            providers_used=providers_used,
            warnings=warnings,
            evidence_ids=[s.evidence_id for s in selected if s.evidence_id],
        )

    # ------------------------------------------------------------------
    async def _read_sources(
        self,
        sources: list[Source],
        *,
        fetcher: Any,
        allowlist: list[str],
        db: Database | None,
        user_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        warnings: list[str],
        concurrency: int,
    ) -> None:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def read(source: Source) -> None:
            async with semaphore:
                await self._read_one(
                    source,
                    fetcher=fetcher,
                    allowlist=allowlist,
                    db=db,
                    user_id=user_id,
                    task_id=task_id,
                    warnings=warnings,
                )

        await asyncio.gather(*(read(item) for item in sources))

    async def _read_one(
        self,
        source: Source,
        *,
        fetcher: Any,
        allowlist: list[str],
        db: Database | None,
        user_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        warnings: list[str],
    ) -> None:
        settings = self.settings
        try:
            validate_url_shape(
                source.url,
                allowlist,
                enforce_allowlist=not getattr(settings, "browser_open_web", False),
            )
        except Exception as exc:  # noqa: BLE001 — domaine refusé = source écartée
            source.status = "refusée"
            note = f"{source.domain} écartée : {str(exc)[:80]}"
            if note not in warnings:
                warnings.append(note)
            return

        try:
            page = await asyncio.wait_for(fetcher(source.url), timeout=settings.research_provider_timeout_seconds + 10)
        except Exception as exc:  # noqa: BLE001
            source.status = "illisible"
            note = f"{source.domain} illisible ({type(exc).__name__})"
            if note not in warnings:
                warnings.append(note)
            return
        if getattr(page, "status", 200) >= 400:
            source.status = "illisible"
            return

        raw = getattr(page, "raw", None)
        if raw is not None and looks_like_pdf(raw, getattr(page, "content_type", "")):
            extraction = extract_pdf(
                raw,
                max_bytes=settings.research_pdf_max_bytes,
                max_pages=settings.research_pdf_max_pages,
            )
            if extraction.status != "ok":
                source.status = extraction.status
                note = f"{source.domain} : {extraction.error}"
                if note not in warnings:
                    warnings.append(note)
                return
            body, findings = sanitize_text(extraction.text)
            title = source.title
            provider_label = f"{','.join(source.providers)}|pdf"
        else:
            readable = extract_readable(getattr(page, "text", "") or "", getattr(page, "final_url", source.url))
            body = readable.text
            findings = readable.injection_findings
            title = readable.title or source.title
            provider_label = ",".join(source.providers)
            if findings:
                note = f"{source.domain} : contenu suspect neutralisé ({', '.join(findings)})"
                if note not in warnings:
                    warnings.append(note)

        if len(body.strip()) < 80:
            source.status = "vide"
            return
        source.excerpt = best_passage(body) or body[:600]
        source.title = title or source.title
        source.status = "lue"

        if db is not None and user_id is not None:
            evidence_id = await record(
                db,
                user_id=user_id,
                task_id=task_id,
                url=source.url,
                canonical_url=source.canonical_url,
                domain=source.domain,
                title=source.title,
                content=body,
                provider=provider_label,
                status="ok",
                provenance={"providers": source.providers, "score": source.score},
            )
            source.evidence_id = evidence_id

    # ------------------------------------------------------------------
    def _synthesize(self, query: str, sources: list[Source], warnings: list[str]) -> str:
        """Synthèse extractive, sourcée. Aucun fait ajouté hors des lectures."""
        read = [s for s in sources if s.status == "lue"]
        if not read:
            warnings.append(
                "Aucune page n'a pu être lue : la réponse n'est pas rédigée "
                "(les résultats du moteur ne sont pas des preuves)."
            )
            return ""
        lines = [f"Recherche : {query}", ""]
        for index, source in enumerate(read, start=1):
            excerpt = (source.excerpt or source.snippet or "").strip()
            lines.append(f"[{index}] {source.title} ({source.domain}) — {excerpt[:320]}")
        lines.append("")
        lines.append(
            "Synthèse limitée aux passages ci-dessus ; chaque point est rattachable à sa preuve."
        )
        return "\n".join(lines)
