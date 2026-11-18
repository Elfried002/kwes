"""Skill code_exec — exécution de code dans un conteneur jetable et isolé.

Le worker n'a **aucun** accès à l'API Docker : il envoie `{code, language,
timeout}` sur un socket Unix local et un service dédié (root) construit lui-même
la commande `docker run`. C'est la seule façon d'éviter qu'un processus local
puisse créer un conteneur privilégié avec « / » monté (constat d'audit du 17/11 :
un proxy Docker, même filtré, laissait passer `Privileged: true`).

Si le runner est indisponible, le skill échoue explicitement : aucune exécution
n'est simulée.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from app.skills.base import SkillContext, SkillError, SkillResult, SkillValidationError

SOCKET_PATH = Path(os.environ.get("KWES_SANDBOX_SOCKET", "/run/kwes/sandbox.sock"))
MAX_CODE_CHARS = 20_000
DEFAULT_TIMEOUT = 10
HARD_TIMEOUT = 20


async def run_sandbox(
    code: str, *, language: str = "python", timeout_seconds: int = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """Envoie le code au runner et renvoie son résultat brut."""
    if len(code) > MAX_CODE_CHARS:
        raise SkillValidationError("Code trop long (20 000 caractères maximum).")
    if language not in ("python", "shell"):
        raise SkillValidationError("Langage non pris en charge.")
    timeout_seconds = max(1, min(HARD_TIMEOUT, timeout_seconds))

    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError):
        # Serveur sans Docker : exécution directe sur le système, mêmes limites
        # de temps et de sortie, sans isolation de noyau.
        from app.skills.code_exec.native import run_native

        return await run_native(code, language=language, timeout_seconds=timeout_seconds)

    try:
        request = {"code": code, "language": language, "timeout": timeout_seconds}
        writer.write((json.dumps(request) + "\n").encode("utf-8"))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds + 15)
    except asyncio.TimeoutError as exc:
        raise SkillError("Bac à sable : aucune réponse du runner (délai dépassé).") from exc
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    if not line:
        raise SkillError("Bac à sable : connexion fermée sans résultat.")
    try:
        payload = json.loads(line.decode("utf-8"))
    except ValueError as exc:
        raise SkillError("Bac à sable : réponse illisible.") from exc
    if not payload.get("ok"):
        raise SkillError(str(payload.get("error") or "Exécution refusée par le bac à sable."))
    return payload


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    code = str(payload.get("code") or "")
    if not code.strip():
        raise SkillValidationError("Aucun code fourni.")
    language = str(payload.get("language") or "python")
    timeout_seconds = int(payload.get("timeout_seconds") or DEFAULT_TIMEOUT)

    ctx.logger.info("code_exec langage=%s longueur=%s timeout=%s", language, len(code), timeout_seconds)
    result = await run_sandbox(code, language=language, timeout_seconds=timeout_seconds)

    exit_code = int(result.get("exit_code", 1))
    duration = int(result.get("duration_ms", 0))
    summary = (
        f"Exécution terminée en {duration} ms (code {exit_code})."
        if exit_code == 0
        else f"Exécution en échec (code {exit_code}) après {duration} ms."
    )
    return SkillResult(
        output={
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "exit_code": exit_code,
            "duration_ms": duration,
            "truncated": bool(result.get("truncated")),
            "sandbox": str(result.get("sandbox") or "native-process"),
            "network": "available",
        },
        summary=summary,
        evidence=[{"type": "execution", "sandbox": "native", "exit_code": exit_code}],
    )
