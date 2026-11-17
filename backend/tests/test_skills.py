"""Skills : manifestes, schémas, timeout, permissions, injection, anti-SSRF."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.skills.base import (
    SkillContext,
    SkillOutputError,
    SkillPermissionError,
    SkillResult,
    SkillTimeout,
    SkillValidationError,
)
from app.skills.fetch import extract_readable, validate_url_shape
from app.skills.registry import SkillRegistry
from tests.fixtures import HOSTILE_HTML, WIKI_JSON, build_fake_fetcher

ALL_PERMISSIONS = {"web.search", "web.read", "local.write", "browser.read"}


def make_ctx(settings, fetcher, *, granted=None, timeout=5.0) -> SkillContext:
    return SkillContext(
        user_id=uuid.uuid4(),
        settings=settings,
        fetch=fetcher,
        allowlist=settings.browser_domain_allowlist,
        granted_permissions=frozenset(ALL_PERMISSIONS if granted is None else granted),
        timeout_seconds=timeout,
    )


def test_registry_loads_expected_skills(app) -> None:
    registry: SkillRegistry = app.state.registry
    assert registry.names == [
        "browser_readonly",
        "business_planning",
        "code_exec",
        "document_write",
        "remember",
        "web_research",
    ]
    assert registry.load_errors == {}
    for manifest in registry.manifests():
        assert len(manifest["artifact_hash"]) == 64
        assert manifest["input_schema"]["type"] == "object"


async def test_input_schema_rejects_unknown_field(app, settings) -> None:
    with pytest.raises(SkillValidationError):
        await app.state.registry.execute(
            "web_research", {"query": "ok", "evil": True}, make_ctx(settings, build_fake_fetcher())
        )


async def test_input_schema_requires_query(app, settings) -> None:
    with pytest.raises(SkillValidationError):
        await app.state.registry.execute("web_research", {}, make_ctx(settings, build_fake_fetcher()))


async def test_missing_permission_rejected(app, settings) -> None:
    ctx = make_ctx(settings, build_fake_fetcher(), granted={"local.write"})
    with pytest.raises(SkillPermissionError):
        await app.state.registry.execute(
            "web_research", {"query": "marché"}, ctx
        )


async def test_business_planning_is_deterministic(app, settings) -> None:
    payload = {"objective": "Lancer une offre de livraison à Cotonou", "constraints": ["budget 5M FCFA"]}
    ctx = make_ctx(settings, build_fake_fetcher())
    first = await app.state.registry.execute("business_planning", payload, ctx)
    second = await app.state.registry.execute("business_planning", payload, ctx)
    assert first.output == second.output
    assert len(first.output["steps"]) == 5
    assert first.output["kpis"]
    assert first.output["risks"]


async def test_business_planning_publish_not_performed(app, settings) -> None:
    result = await app.state.registry.execute(
        "business_planning",
        {"objective": "Publier le rapport", "publish_external": True},
        make_ctx(settings, build_fake_fetcher()),
    )
    action = result.output["external_action"]
    assert action["requested"] is True
    assert action["performed"] is False
    assert "NON effectuée" in result.output["summary"]


async def test_skill_timeout_is_enforced(app, settings, monkeypatch) -> None:
    skill = app.state.registry.get("business_planning")
    assert skill is not None

    async def slow(payload, ctx):  # noqa: ANN001
        await asyncio.sleep(2)
        return SkillResult(output={}, summary="trop tard")

    monkeypatch.setattr(skill.module, "run", slow)
    with pytest.raises(SkillTimeout):
        await app.state.registry.execute(
            "business_planning",
            {"objective": "objectif de test"},
            make_ctx(settings, build_fake_fetcher(), timeout=0.05),
        )


async def test_output_schema_violation_detected(app, settings, monkeypatch) -> None:
    skill = app.state.registry.get("business_planning")
    assert skill is not None

    async def bad(payload, ctx):  # noqa: ANN001
        return SkillResult(output={"unexpected": True}, summary="invalide")

    monkeypatch.setattr(skill.module, "run", bad)
    with pytest.raises(SkillOutputError):
        await app.state.registry.execute(
            "business_planning",
            {"objective": "objectif de test"},
            make_ctx(settings, build_fake_fetcher()),
        )


async def test_web_research_nominal_with_injected_fetcher(app, settings) -> None:
    fetcher = build_fake_fetcher()
    result = await app.state.registry.execute(
        "web_research", {"query": "fintechs Bénin", "depth": "standard"}, make_ctx(settings, fetcher)
    )
    output = result.output
    assert output["sources"], output
    assert output["synthesis"]
    assert output["facts"]
    assert any("hors allowlist" in limit for limit in output["limits"])
    assert "outside.example.org" in output["skipped_sources"]
    assert all("outside.example.org" not in source["url"] for source in output["sources"])


async def test_web_research_neutralises_injection(app, settings) -> None:
    fetcher = build_fake_fetcher({"example.com/competitor": HOSTILE_HTML})
    result = await app.state.registry.execute(
        "web_research", {"query": "concurrence", "depth": "standard"}, make_ctx(settings, fetcher)
    )
    serialized = str(result.output)
    assert "IGNORE ALL PREVIOUS" not in serialized
    assert "attacker@example.org" not in serialized
    assert any("neutralisé" in limit for limit in result.output["limits"])


async def test_web_research_falls_back_to_wikipedia(app, settings) -> None:
    fetcher = build_fake_fetcher(
        {"duckduckgo.com": "{}", "wikipedia.org/w/api.php": WIKI_JSON}
    )
    result = await app.state.registry.execute(
        "web_research", {"query": "fintech", "depth": "quick"}, make_ctx(settings, fetcher)
    )
    output = result.output
    assert output["sources"], output
    assert all("wikipedia.org" in source["url"] for source in output["sources"])
    assert any("Wikipédia" in limit for limit in output["limits"])
    assert len(output["sources"][0]["snippet"]) > 40


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "https://example.com:8080/",
        "https://user:pass@example.com/",
        "ftp://example.com/file",
        "https://evil.example.org/page",
        "https://example.com.evil.org/page",
    ],
)
def test_url_shape_blocks_dangerous_targets(settings, url: str) -> None:
    with pytest.raises(SkillValidationError):
        validate_url_shape(url, settings.browser_domain_allowlist)


def test_url_shape_allows_listed_domain(settings) -> None:
    assert validate_url_shape("https://example.com/page", settings.browser_domain_allowlist)


async def test_browser_readonly_nominal(app, settings) -> None:
    result = await app.state.registry.execute(
        "browser_readonly",
        {"url": "https://example.com/page", "objective": "veille"},
        make_ctx(settings, build_fake_fetcher()),
    )
    output = result.output
    assert "fintechs" in output["title"].lower()
    assert output["content"]
    assert output["untrusted"] is True
    assert output["injection_detected"] is False
    assert output["links"]


async def test_browser_readonly_flags_hostile_content(app, settings) -> None:
    result = await app.state.registry.execute(
        "browser_readonly",
        {"url": "https://example.com/hostile"},
        make_ctx(settings, build_fake_fetcher()),
    )
    output = result.output
    assert output["injection_detected"] is True
    assert "IGNORE ALL PREVIOUS" not in output["content"]
    assert "[CONTENU NON FIABLE SUPPRIMÉ]" in output["content"]


async def test_browser_readonly_blocks_unlisted_domain(app, settings) -> None:
    with pytest.raises(SkillValidationError):
        await app.state.registry.execute(
            "browser_readonly",
            {"url": "https://evil.example.org/page"},
            make_ctx(settings, build_fake_fetcher()),
        )


def test_extract_readable_skips_scripts_and_collects_links() -> None:
    extracted = extract_readable(
        "<html><head><title>T</title><script>alert(1)</script></head>"
        "<body><p>Texte utile.</p><a href='/x'>Lien</a></body></html>",
        "https://example.com/base",
    )
    assert extracted.title == "T"
    assert "alert(1)" not in extracted.text
    assert "Texte utile." in extracted.text
    assert extracted.links[0]["url"] == "https://example.com/x"


def _write_skill(directory: Path, *, name: str, permissions: str, risk: str = "R0") -> None:
    directory.mkdir(parents=True)
    (directory / "manifest.yaml").write_text(
        f"""name: {name}
version: 1.0.0
description: Skill de test
entrypoint: skill.py
permissions:
  - {permissions}
risk_level: {risk}
network:
  mode: none
  domains: []
resources:
  timeout_seconds: 5
  memory_mb: 64
  cpu_limit: 0.1
""",
        encoding="utf-8",
    )
    (directory / "schemas").mkdir()
    (directory / "schemas" / "input.json").write_text('{"type": "object"}', encoding="utf-8")
    (directory / "schemas" / "output.json").write_text('{"type": "object"}', encoding="utf-8")
    (directory / "skill.py").write_text(
        "from app.skills.base import SkillResult\n\n"
        "async def run(payload, ctx):\n"
        "    return SkillResult(output={}, summary='ok')\n",
        encoding="utf-8",
    )


def test_manifest_cannot_escalate_permissions(tmp_path: Path, settings) -> None:
    _write_skill(tmp_path / "web_research", name="web_research", permissions="secrets.read")
    registry = SkillRegistry(tmp_path, settings)
    registry.load()
    assert registry.get("web_research") is None
    assert "web_research" in registry.load_errors


def test_manifest_risk_must_match_policy(tmp_path: Path, settings) -> None:
    _write_skill(
        tmp_path / "business_planning", name="business_planning", permissions="local.write", risk="R0"
    )
    registry = SkillRegistry(tmp_path, settings)
    registry.load()
    assert registry.get("business_planning") is None
    assert "risk_level" in registry.load_errors["business_planning"]
