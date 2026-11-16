"""Rendu de page via Playwright (Chromium headless) pour le skill browser_readonly.

Sécurité : la validation d'URL (allowlist, schéma, port, anti-SSRF) est faite
AVANT le lancement du navigateur, puis chaque requête — y compris les
sous-ressources — est revalidée dans un gestionnaire de route. Les domaines
d'allowlist sont seuls autorisés ; tout le reste est bloqué, sans exception.

Repli : si Playwright ou Chromium est absent, l'appelant doit utiliser le
fetcher httpx classique (`render_available()` renvoie False).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from app.skills.base import FetchedPage, SkillProviderError, SkillValidationError
from app.skills.fetch import validate_url_shape

logger = logging.getLogger("kwes.skills.render")

MAX_HTML_BYTES = 3_000_000


def render_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


async def render_fetch(
    url: str,
    *,
    allowlist: list[str],
    timeout: float = 20.0,
    wait_until: str = "networkidle",
    enforce_allowlist: bool = True,
) -> FetchedPage:
    """Charge la page avec exécution JavaScript et renvoie le HTML rendu."""
    validated = validate_url_shape(url, allowlist, enforce_allowlist=enforce_allowlist)

    from playwright.async_api import async_playwright

    started = time.monotonic()
    blocked = {"count": 0}

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                context = await browser.new_context(
                    java_script_enabled=True,
                    ignore_https_errors=False,
                    user_agent="KwesBot/0.1 (read-only)",
                    viewport={"width": 1280, "height": 900},
                )

                async def _guard(route: Any) -> None:
                    target = route.request.url
                    try:
                        if route.request.resource_type in {"media", "font"}:
                            await route.abort()
                            return
                        validate_url_shape(target, allowlist, enforce_allowlist=enforce_allowlist)
                    except SkillValidationError:
                        blocked["count"] += 1
                        await route.abort()
                        return
                    try:
                        await route.continue_()
                    except Exception:  # noqa: BLE001 — requête déjà annulée
                        pass

                await context.route("**/*", _guard)
                page = await context.new_page()
                response = await page.goto(
                    validated, wait_until=wait_until, timeout=int(timeout * 1000)
                )
                status = response.status if response is not None else 0
                try:
                    await page.wait_for_timeout(600)
                except Exception:  # noqa: BLE001
                    pass
                html = await page.content()
                final_url = page.url or validated
                title = await page.title()
            finally:
                await browser.close()
    except SkillValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("rendu Playwright impossible url=%s err=%s", validated[:120], exc)
        raise SkillProviderError("Page inaccessible par le navigateur.") from exc

    if len(html) > MAX_HTML_BYTES:
        html = html[:MAX_HTML_BYTES]

    elapsed = int((time.monotonic() - started) * 1000)
    logger.info(
        "render ok url=%s status=%s chars=%s blocked=%s ms=%s title=%s",
        validated[:120], status, len(html), blocked["count"], elapsed, (title or "")[:80],
    )
    return FetchedPage(
        url=validated,
        final_url=final_url,
        status=status or 200,
        content_type="text/html; rendered=playwright",
        text=html,
        elapsed_ms=elapsed,
    )


def make_browser_fetcher(allowlist: list[str], settings: Any) -> Any:
    """Fetcher prioritaire : Chromium rendu, avec repli httpx à l'usage.

    Le repli est décidé à chaque appel (Chromium peut échouer ponctuellement),
    jamais silencieusement : un log WARNING est émis et le HTML renvoyé est
    celui du rendu serveur.
    """
    from app.skills.fetch import safe_fetch

    timeout = min(20.0, float(getattr(settings, "skill_default_timeout_seconds", 20.0)))
    mode = str(getattr(settings, "browser_render", "auto"))

    if getattr(settings, "skill_offline_mode", False):
        from app.skills.base import SkillError

        async def _offline(url: str) -> FetchedPage:
            raise SkillError("Accès réseau désactivé en mode hors ligne.")

        return _offline

    async def _fetch(url: str) -> FetchedPage:
        if mode != "httpx" and render_available():
            try:
                return await render_fetch(
                    url,
                    allowlist=allowlist,
                    timeout=timeout,
                    enforce_allowlist=not getattr(settings, "browser_open_web", False),
                )
            except SkillProviderError:
                if mode == "playwright":
                    raise
                logger.warning("Repli httpx après échec du rendu pour %s", url[:120])
        return await safe_fetch(
            url,
            allowlist=allowlist,
            enforce_allowlist=not getattr(settings, "browser_open_web", False),
            timeout=timeout,
            max_bytes=settings.fetch_max_bytes,
            max_redirects=settings.fetch_max_redirects,
        )

    return _fetch


async def self_test(url: str = "https://example.com") -> dict[str, Any]:
    """Test manuel : rendu d'une page et mesure du temps."""
    started = time.monotonic()
    page = await render_fetch(url, allowlist=[urlsplit(url).hostname or ""])
    return {
        "ok": True,
        "status": page.status,
        "chars": len(page.text),
        "ms": int((time.monotonic() - started) * 1000),
        "contains_js_marker": "<script" in page.text.lower(),
    }


if __name__ == "__main__":  # pragma: no cover - usage manuel
    print(asyncio.run(self_test()))
