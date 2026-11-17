"""Skill code_exec — exécution de code dans un conteneur jetable et isolé.

Aucun accès au système hôte, aucun réseau, aucun secret : le code soumis tourne
dans un conteneur Docker sans privilèges, avec des limites strictes, et le
conteneur est détruit à la fin. Si Docker n'est pas disponible, le skill échoue
explicitement : il ne simule jamais une exécution.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from app.skills.base import SkillContext, SkillError, SkillResult, SkillValidationError

IMAGE = "python:3.12-alpine"
# Le worker tourne avec PrivateTmp : un répertoire sous /tmp ne serait pas visible
# par le démon Docker (qui vit hors du service). On travaille donc dans un dossier
# du projet, couvert par ReadWritePaths.
SANDBOX_ROOT = Path(
    os.environ.get("KWES_SANDBOX_DIR", str(Path(__file__).resolve().parents[3] / ".sandbox"))
)
MAX_OUTPUT_CHARS = 20_000
MAX_CODE_CHARS = 20_000
DEFAULT_TIMEOUT = 10
HARD_TIMEOUT = 25


class SandboxResult:
    """Résultat d'exécution (classe simple : le chargeur n'inscrit pas le module
    dans sys.modules, ce qui casse @dataclass avec slots)."""

    __slots__ = ("stdout", "stderr", "exit_code", "duration_ms", "truncated")

    def __init__(self, stdout: str, stderr: str, exit_code: int, duration_ms: int, truncated: bool) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.truncated = truncated


def docker_available() -> bool:
    return shutil.which("docker") is not None


def docker_host() -> str:
    """Hôte Docker à utiliser : proxy restreint par défaut, sinon socket local."""
    import os

    return os.environ.get("DOCKER_HOST") or "tcp://127.0.0.1:2375"


def _docker_prefix() -> list[str]:
    """Commande docker, sans sudo : le service worker n'a aucun privilège.

    L'accès passe par un proxy (conteneurs + images uniquement) qui relaie vers
    le socket réel en lecture seule. Aucun argument utilisateur n'entre ici.
    """
    return ["docker"]


def _can_use_docker_directly() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
            check=False,
            env={**os.environ, "DOCKER_HOST": docker_host()},
        )
        return completed.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _kill_group(pid: int) -> None:
    import os
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def build_argv(workdir: Path, *, language: str, timeout_seconds: int, name: str = "") -> list[str]:
    """Construit la commande d'exécution isolée (testable sans Docker)."""
    if language == "shell":
        command = ["/bin/sh", "/work/main.sh"]
    else:
        command = ["python", "/work/main.py"]
    return [
        *_docker_prefix(), "run", "--rm", *(["--name", name] if name else []),
        "--network", "none",
        "--memory", "256m", "--memory-swap", "256m",
        "--cpus", "0.5",
        "--pids-limit", "64",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:size=32m",
        "--user", "65534:65534",
        "--workdir", "/work",
        "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", f"type=bind,src={workdir},dst=/work",
        IMAGE,
        *command,
    ]


async def run_sandbox(
    code: str, *, language: str = "python", timeout_seconds: int = DEFAULT_TIMEOUT
) -> SandboxResult:
    if not docker_available():
        raise SkillError("Environnement isolé indisponible (Docker absent) : exécution refusée.")
    if len(code) > MAX_CODE_CHARS:
        raise SkillValidationError("Code trop long (20 000 caractères maximum).")
    if language not in ("python", "shell"):
        raise SkillValidationError("Langage non pris en charge.")

    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        SANDBOX_ROOT.chmod(0o755)
    except OSError:
        pass
    workdir = Path(tempfile.mkdtemp(prefix="kwes-sbx-", dir=SANDBOX_ROOT))
    try:
        filename = "main.sh" if language == "shell" else "main.py"
        script = workdir / filename
        script.write_text(code, encoding="utf-8")
        # Le conteneur tourne en 65534 : lecture seule du script, aucune écriture
        # hors de son /tmp éphémère.
        workdir.chmod(0o755)
        script.chmod(0o644)
        container_name = f"kwes-sbx-{uuid.uuid4().hex[:12]}"
        argv = build_argv(
            workdir, language=language, timeout_seconds=timeout_seconds, name=container_name
        )
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_HOST": docker_host()},
            # Groupe de processus dédié : tuer sudo ne tue pas docker run, il
            # faut tuer tout le groupe sinon les tuyaux restent ouverts.
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds + 5)
        except asyncio.TimeoutError:
            _kill_group(process.pid)
            # Tuer le client docker ne tue pas le conteneur : on le supprime.
            try:
                subprocess.run(
                    [*_docker_prefix(), "rm", "-f", container_name],
                    capture_output=True,
                    timeout=10,
                    check=False,
                    env={**os.environ, "DOCKER_HOST": docker_host()},
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            raise SkillError(f"Exécution interrompue après {timeout_seconds} s (limite).")
        duration = int((time.monotonic() - started) * 1000)
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        truncated = len(out) > MAX_OUTPUT_CHARS
        return SandboxResult(
            stdout=out[:MAX_OUTPUT_CHARS],
            stderr=err[:MAX_OUTPUT_CHARS],
            exit_code=int(process.returncode or 0),
            duration_ms=duration,
            truncated=truncated,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    code = str(payload.get("code") or "")
    if not code.strip():
        raise SkillValidationError("Aucun code fourni.")
    language = str(payload.get("language") or "python")
    timeout_seconds = min(HARD_TIMEOUT, max(1, int(payload.get("timeout_seconds") or DEFAULT_TIMEOUT)))

    ctx.logger.info("code_exec langage=%s longueur=%s timeout=%s", language, len(code), timeout_seconds)
    result = await run_sandbox(code, language=language, timeout_seconds=timeout_seconds)

    summary = (
        f"Exécution terminée en {result.duration_ms} ms (code {result.exit_code})."
        if result.exit_code == 0
        else f"Exécution en échec (code {result.exit_code}) après {result.duration_ms} ms."
    )
    return SkillResult(
        output={
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
            "sandbox": "docker-ephemeral",
            "network": "none",
        },
        summary=summary,
        evidence=[{"type": "execution", "sandbox": "docker-ephemeral", "exit_code": result.exit_code}],
    )
