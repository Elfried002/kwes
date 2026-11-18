"""Exécution de code directement sur le serveur (sans Docker).

Le serveur dédié de Kwes n'a plus de Docker : les outils tournent sur le système.
Ce module remplace le runner conteneurisé par une exécution de processus locale,
avec les garde-fous qui restent utiles — délai maximal, répertoire jetable, sortie
bornée, variables d'environnement nettoyées — mais sans isolation de noyau.

Si un utilisateur système `kwesexec` existe, le code est exécuté sous cette
identité (moins de droits que le compte du service) ; sinon sous l'utilisateur
courant. Le réseau reste disponible : l'agent doit pouvoir agir.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

MAX_OUTPUT = 20_000
EXEC_USER = os.environ.get("KWES_EXEC_USER", "kwesexec")


def _runuser_prefix() -> list[str] | None:
    """Préfixe permettant d'exécuter le code sous l'utilisateur `kwesexec`.

    Deux cas : le service tourne déjà en root (runuser direct), ou il tourne sous
    `kwes` avec une règle sudo limitée à `runuser -u kwesexec`. Sans l'un des deux,
    le code s'exécute sous l'utilisateur courant.
    """
    if not shutil.which("runuser"):
        return None
    candidates = (
        [["runuser", "-u", EXEC_USER, "--"]]
        if os.geteuid() == 0
        # `sudo -u` directement : la règle sudoers autorise kwes à agir *comme*
        # kwesexec, pas à lancer runuser.
        else [["sudo", "-n", "-u", EXEC_USER, "--"]]
    )
    for prefix in candidates:
        try:
            probe = subprocess.run(prefix + ["true"], capture_output=True, timeout=5)
        except Exception:  # noqa: BLE001
            continue
        if probe.returncode == 0:
            return prefix
    return None


async def run_native(
    code: str, *, language: str = "python", timeout_seconds: int = 10
) -> dict[str, object]:
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix="kwes-exec-"))
    try:
        if language == "python":
            script = workdir / "main.py"
            script.write_text(code, encoding="utf-8")
            argv = ["python3", "-I", "-B", str(script)]
        else:
            script = workdir / "main.sh"
            script.write_text(code, encoding="utf-8")
            argv = ["bash", str(script)]

        prefix = _runuser_prefix()
        command = (prefix or []) + argv
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(workdir),
            "TMPDIR": str(workdir),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }

        if prefix:
            # Le répertoire appartient à root : on l'ouvre à l'utilisateur d'exécution.
            subprocess.run(["chmod", "-R", "a+rwX", str(workdir)], check=False)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
            exit_code = process.returncode or 0
            timed_out = False
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except Exception:  # noqa: BLE001
                process.kill()
            stdout, stderr = await process.communicate()
            exit_code = 124
            timed_out = True

        out = (stdout or b"").decode("utf-8", "replace")
        err = (stderr or b"").decode("utf-8", "replace")
        truncated = len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT
        duration = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "stdout": out[:MAX_OUTPUT],
            "stderr": err[:MAX_OUTPUT],
            "exit_code": exit_code,
            "duration_ms": duration,
            "truncated": truncated,
            "timed_out": timed_out,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


__all__ = ["run_native", "EXEC_USER"]
