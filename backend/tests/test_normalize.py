"""Normalisation des entrées : un synonyme connu ne doit pas faire échouer une mission."""

from __future__ import annotations

from app.skills.normalize import normalize_payload


def test_depth_synonym_is_accepted() -> None:
    payload = {"query": "assistants vocaux Afrique", "depth": "approfondie", "scope": "web"}
    assert normalize_payload("web_research", payload)["depth"] == "deep"
    assert payload["depth"] == "approfondie"  # la copie ne modifie pas l'original


def test_unknown_depth_falls_back_to_standard() -> None:
    assert normalize_payload("web_research", {"query": "x", "depth": "intense"})["depth"] == "standard"
    assert normalize_payload("web_research", {"query": "x", "depth": "RAPIDE"})["depth"] == "quick"


def test_other_skills_are_untouched() -> None:
    payload = {"query": "x", "depth": "approfondie"}
    assert normalize_payload("remember", payload) == payload


def test_registry_accepts_french_depth(client_app_registry=None) -> None:
    """Le registre charge réellement le schéma et accepte le synonyme."""
    from pathlib import Path

    from app.core.config import Settings
    from app.skills.registry import SkillRegistry

    settings = Settings(app_env="test", deepseek_api_key="", skill_offline_mode=True)
    registry = SkillRegistry(Path("app/skills"), settings)
    registry.load()
    registry.validate_input(
        "web_research",
        normalize_payload("web_research", {"query": "assistants vocaux", "depth": "approfondie"}),
    )
