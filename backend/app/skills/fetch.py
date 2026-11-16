"""Accès réseau contrôlé pour les skills : allowlist, anti-SSRF, extraction lisible.

Politique (docs/08-security/SECURITY_MODEL.md §8) :
- http/https uniquement, pas d'userinfo, ports 80/443 seulement ;
- blocage IP privées, loopback, link-local, réservées, multicast et endpoints
  metadata cloud (169.254.169.254, metadata.google.internal, ...) ;
- résolution DNS vérifiée à chaque saut de redirection ;
- allowlist de domaines configurée par environnement (jamais par le modèle).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.skills.base import FetchedPage, SkillError, SkillProviderError, SkillValidationError

logger = logging.getLogger("kwes.skills.fetch")

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}

_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ignore[rz]?\s+(all\s+|les\s+|toutes\s+)?(previous\s+|pr[ée]c[ée]dentes?\s+)?instructions", re.I), "instruction_override"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+instructions", re.I), "instruction_override"),
    (re.compile(r"(system|developer)\s*prompt|prompt\s*syst[èe]me", re.I), "system_prompt_probe"),
    (re.compile(r"you\s+are\s+now\s+|tu\s+es\s+maintenant\s+", re.I), "role_hijack"),
    (re.compile(r"(send|reveal|give|expose|envoie|r[ée]v[èe]le|donne)[^.\n]{0,40}(api[_\s-]?key|secret|token|password|mot de passe)", re.I), "secret_request"),
    (re.compile(r"(curl|wget)\s+https?://|rm\s+-rf\s+/", re.I), "command_injection"),
    (re.compile(r"<\s*script", re.I), "script_tag"),
)

MAX_TEXT_CHARS = 20_000
MAX_LINKS = 40


def normalize_host(host: str) -> str:
    return (host or "").strip().lower().strip("[]").rstrip(".")


def is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback


def domain_allowlisted(host: str, allowlist: list[str]) -> bool:
    host = normalize_host(host)
    if not host:
        return False
    for entry in allowlist:
        entry = normalize_host(entry)
        if entry and (host == entry or host.endswith("." + entry)):
            return True
    return False


def validate_url_shape(
    url: str, allowlist: list[str], *, enforce_allowlist: bool = True
) -> str:
    """Validation statique (aucune résolution DNS, aucun réseau)."""
    if not isinstance(url, str) or not url.strip():
        raise SkillValidationError("URL manquante.")
    candidate = url.strip()
    if len(candidate) > 2048:
        raise SkillValidationError("URL trop longue.")
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise SkillValidationError("Schéma d'URL non autorisé (http/https uniquement).")
    if "@" in parts.netloc:
        raise SkillValidationError("URL avec identifiants intégrés refusée.")
    host = normalize_host(parts.hostname or "")
    if not host:
        raise SkillValidationError("URL sans hôte.")
    if host in BLOCKED_HOSTNAMES or any(host.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        raise SkillValidationError("Hôte interne ou metadata refusé.")
    try:
        port = parts.port
    except ValueError as exc:
        raise SkillValidationError("Port invalide.") from exc
    if port not in ALLOWED_PORTS:
        raise SkillValidationError("Port non autorisé.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (not ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_private):
        raise SkillValidationError("Adresse IP privée, locale ou réservée refusée.")
    if enforce_allowlist and not domain_allowlisted(host, allowlist):
        raise SkillValidationError(f"Domaine non autorisé: {host}")
    return candidate


async def assert_public_host(host: str) -> None:
    """Résout le nom et refuse toute adresse non globale (anti DNS rebinding)."""
    normalized = normalize_host(host)
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, normalized, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise SkillProviderError(f"Résolution DNS impossible pour {normalized}.") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise SkillProviderError(f"Résolution DNS vide pour {normalized}.")
    for address in addresses:
        if is_private_ip(address):
            raise SkillValidationError("La résolution DNS pointe vers une adresse non publique.")


@dataclass
class ReadableContent:
    title: str
    text: str
    links: list[dict[str, str]]
    injection_findings: list[str]
    sanitized: bool


class _Extractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object"}
    # Zones de contenu principal : sur une grosse page, le texte utile y est
    # (le reste est menu, barre latérale, pied de page). On privilégie ce bloc
    # quand il contient assez de texte, sinon on retombe sur le document entier.
    CONTENT_TAGS = {"main", "article"}
    BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer", "li", "tr",
        "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.scoped_parts: list[str] = []
        self._scope_depth = 0
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            mapping = {k.lower(): v for k, v in attrs}
            href = (mapping.get("href") or "").strip()
            if href:
                self._current_href = href
                self._link_text = []
        if tag in self.CONTENT_TAGS:
            self._scope_depth += 1
        if tag in self.BLOCK_TAGS:
            self.text_parts.append("\n")
            if self._scope_depth:
                self.scoped_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self.CONTENT_TAGS and self._scope_depth:
            self._scope_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._current_href:
            label = " ".join("".join(self._link_text).split())[:120]
            if len(self.links) < MAX_LINKS:
                self.links.append({"url": self._current_href, "label": label or self._current_href[:80]})
            self._current_href = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._current_href is not None:
            self._link_text.append(data)
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned + " ")
            if self._scope_depth:
                self.scoped_parts.append(cleaned + " ")

    # -- sortie ---------------------------------------------------------
    def result(self, base_url: str) -> ReadableContent:
        scoped = "".join(self.scoped_parts).strip()
        raw_text = "".join(self.scoped_parts) if len(scoped) >= 400 else "".join(self.text_parts)
        raw_text = re.sub(r"[ \t]+", " ", raw_text)
        raw_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()
        title = " ".join("".join(self.title_parts).split())[:300]
        findings: list[str] = []
        lines = raw_text.splitlines()
        sanitized_lines: list[str] = []
        for line in lines:
            matched = [label for pattern, label in _INJECTION_PATTERNS if pattern.search(line)]
            if matched:
                findings.extend(matched)
                sanitized_lines.append("[CONTENU NON FIABLE SUPPRIMÉ]")
            else:
                sanitized_lines.append(line)
        text = "\n".join(sanitized_lines)[:MAX_TEXT_CHARS]
        links = []
        for link in self.links:
            absolute = urljoin(base_url, link["url"])
            if absolute.startswith(("http://", "https://")):
                links.append({"url": absolute, "label": link["label"]})
        return ReadableContent(
            title=title,
            text=text,
            links=links,
            injection_findings=sorted(set(findings)),
            sanitized=bool(findings),
        )


def extract_readable(html: str, base_url: str) -> ReadableContent:
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # HTML malformé : on garde ce qui a été extrait
        logger.warning("HTML malformé lors de l'extraction url=%s", base_url)
    return parser.result(base_url)


def parse_json_page(page: FetchedPage) -> dict[str, Any]:
    try:
        payload = json.loads(page.text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


async def safe_fetch(
    url: str,
    *,
    allowlist: list[str],
    enforce_allowlist: bool = True,
    timeout: float = 15.0,
    max_bytes: int = 2_000_000,
    max_redirects: int = 4,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchedPage:
    current = validate_url_shape(url, allowlist, enforce_allowlist=enforce_allowlist)
    timeout_cfg = httpx.Timeout(timeout)
    started = asyncio.get_running_loop().time()

    async with httpx.AsyncClient(
        timeout=timeout_cfg,
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "KwesBot/0.1 (+read-only; contact: ops@kwes.local)"},
    ) as client:
        for _hop in range(max_redirects + 1):
            parts = urlsplit(current)
            await assert_public_host(parts.hostname or "")
            try:
                response = await client.get(current)
            except httpx.TimeoutException as exc:
                raise SkillProviderError("Délai dépassé lors de la lecture de la page.") from exc
            except httpx.HTTPError as exc:
                raise SkillProviderError("Lecture réseau impossible.") from exc

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                if not location:
                    raise SkillProviderError("Redirection sans destination.")
                current = validate_url_shape(
                    urljoin(current, location), allowlist, enforce_allowlist=enforce_allowlist
                )
                continue

            body = response.content[:max_bytes]
            encoding = response.encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
            return FetchedPage(
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                content_type=response.headers.get("content-type", ""),
                text=text,
                elapsed_ms=elapsed,
            )

    raise SkillProviderError("Trop de redirections.")


def make_fetcher(allowlist: list[str], settings: Any) -> Any:
    if getattr(settings, "skill_offline_mode", False):
        # Mode hors ligne (tests / CI) : aucune sortie réseau possible, même par
        # accident. Un test qui a besoin de contenu fournit un fetcher factice.
        async def _offline(url: str) -> FetchedPage:
            raise SkillError("Accès réseau désactivé en mode hors ligne.")

        return _offline

    async def _fetch(url: str) -> FetchedPage:
        return await safe_fetch(
            url,
            allowlist=allowlist,
            enforce_allowlist=not getattr(settings, "browser_open_web", False),
            timeout=min(20.0, settings.skill_default_timeout_seconds),
            max_bytes=settings.fetch_max_bytes,
            max_redirects=settings.fetch_max_redirects,
        )

    return _fetch


def ensure_text(text: str, *, minimum: int = 40) -> str:
    if len(text.strip()) < minimum:
        raise SkillError("Contenu extrait insuffisant pour produire un résultat fiable.")
    return text
