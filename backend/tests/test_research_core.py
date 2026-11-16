"""Moteur de recherche P1 : URL, déduplication, qualité de source, planification."""

from __future__ import annotations

from app.research.core import (
    SearchHit,
    best_passage,
    Source,
    canonicalize_url,
    classify_source,
    dedupe_hits,
    domain_of,
    score_source,
)
from app.research.planner import key_terms, plan_queries


def test_canonicalize_strips_tracking_and_fragment() -> None:
    url = "https://WWW.Example.com:443/article/?utm_source=x&utm_medium=y&id=42#section"
    assert canonicalize_url(url) == "https://example.com/article?id=42"


def test_canonicalize_keeps_meaningful_params() -> None:
    url = "https://example.com/search?q=kwes&page=2"
    assert canonicalize_url(url) == "https://example.com/search?page=2&q=kwes"


def test_canonicalize_keeps_non_default_port() -> None:
    assert canonicalize_url("http://example.com:8080/a/") == "http://example.com:8080/a"


def test_domain_of_strips_www_and_mobile() -> None:
    assert domain_of("https://www.lemonde.fr/x") == "lemonde.fr"
    assert domain_of("https://m.example.org/y") == "example.org"
    assert domain_of("not a url") == ""


def test_classify_source() -> None:
    assert classify_source("service-public.gouv.fr") == "officielle"
    assert classify_source("data.gov.uk") == "officielle"
    assert classify_source("lemonde.fr") == "média"
    assert classify_source("reddit.com") == "communauté"
    assert classify_source("un-site-inconnu.xyz") == "inconnue"


def test_official_source_outranks_community() -> None:
    official = Source(
        url="https://gouv.fr/a", canonical_url="https://gouv.fr/a", domain="gouv.fr",
        title="Rapport officiel", snippet="données", category="officielle",
    )
    forum = Source(
        url="https://reddit.com/a", canonical_url="https://reddit.com/a", domain="reddit.com",
        title="Avis", snippet="données", category="communauté",
    )
    assert score_source(official, "rapport") > score_source(forum, "rapport")


def test_provider_agreement_increases_score() -> None:
    one = Source(url="https://a.fr", canonical_url="https://a.fr", domain="a.fr",
                 title="t", snippet="s", providers=["searxng"], category="inconnue")
    two = Source(url="https://b.fr", canonical_url="https://b.fr", domain="b.fr",
                 title="t", snippet="s", providers=["searxng", "duckduckgo"], category="inconnue")
    assert score_source(two, "t") > score_source(one, "t")


def test_dedupe_merges_providers_and_keeps_longest_snippet() -> None:
    hits = [
        SearchHit("https://www.example.com/a?utm_source=x", "Titre A", "court", "searxng", 0),
        SearchHit("https://example.com/a", "Titre A", "un extrait beaucoup plus long", "duckduckgo", 1),
        SearchHit("https://example.com/b", "Autre", "x", "wikipedia", 2),
    ]
    sources = dedupe_hits(hits)
    assert len(sources) == 2
    merged = next(s for s in sources if s.domain == "example.com" and s.canonical_url.endswith("/a"))
    assert sorted(merged.providers) == ["duckduckgo", "searxng"]
    assert merged.snippet == "un extrait beaucoup plus long"


def test_dedupe_ignores_non_http() -> None:
    assert dedupe_hits([SearchHit("ftp://x", "t", "s", "searxng")]) == []


def test_plan_queries_respects_depth_and_cap() -> None:
    assert plan_queries("assistants vocaux", "quick", 4) == ["assistants vocaux"]
    standard = plan_queries("assistants vocaux", "standard", 4)
    assert len(standard) == 2 and standard[0] == "assistants vocaux"
    deep = plan_queries("assistants vocaux", "deep", 3)
    assert len(deep) == 3
    # Aucune variante ne remplace la requête d'origine.
    assert all(q.startswith("assistants vocaux") for q in deep)


def test_key_terms_filters_short_words() -> None:
    assert key_terms("les assistants vocaux en Afrique") == ["assistants", "vocaux", "afrique"]


def test_best_passage_skips_navigation_junk() -> None:
    text = (
        "Basculer la table des matieres\n48 langues\nالعربية\nDeutsch\nEnglish\n"
        "Espanol\nFrancais\nItaliano\n"
        "\n\nOrange est une entreprise francaise de telecommunications presente dans "
        "de nombreux pays d Afrique de l Ouest, ou elle exploite des reseaux mobiles et "
        "propose des services numeriques aux particuliers comme aux entreprises."
    )
    passage = best_passage(text)
    assert passage.startswith("Orange est une entreprise")


def test_best_passage_truncates_on_sentence() -> None:
    text = "Phrase complete. " * 60
    passage = best_passage(text, max_chars=120)
    assert len(passage) <= 130
