"""Bac à sable d'exécution : isolement, limites, refus explicite.

Les tests d'isolation réels ne s'exécutent que si `KWES_SANDBOX_TEST=1` (Docker
requis) : la suite standard reste rapide et indépendante de l'hôte.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.skills.base import SkillValidationError
from app.skills.code_exec.skill import build_argv, run, run_sandbox

SANDBOX_ENABLED = os.environ.get("KWES_SANDBOX_TEST") == "1"


def test_argv_is_locked_down(tmp_path: Path) -> None:
    argv = build_argv(tmp_path, language="python", timeout_seconds=5, name="kwes-sbx-test")
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--read-only" in joined
    assert "--user 65534:65534" in joined
    assert "--memory 256m" in joined
    assert "--pids-limit 64" in joined
    assert "no-new-privileges" in joined
    assert f"src={tmp_path},dst=/work" in joined
    # Aucun montage du système hôte, aucun accès au socket docker dans le conteneur.
    assert "/etc" not in joined and "/var/run/docker.sock,dst" not in joined
    assert argv[-2:] == ["python", "/work/main.py"]


def test_shell_language_uses_shell_entrypoint(tmp_path: Path) -> None:
    argv = build_argv(tmp_path, language="shell", timeout_seconds=5)
    assert argv[-2:] == ["/bin/sh", "/work/main.sh"]


async def test_empty_code_is_refused() -> None:
    with pytest.raises(SkillValidationError):
        await run({"code": "   "}, ctx=None)  # type: ignore[arg-type]


async def test_unknown_language_is_refused() -> None:
    with pytest.raises(SkillValidationError):
        await run_sandbox("print(1)", language="ruby")


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (Docker)")
async def test_sandbox_runs_python_and_returns_stdout() -> None:
    result = await run_sandbox("print('bonjour'); print(6 * 7)", timeout_seconds=15)
    assert result.exit_code == 0
    assert "bonjour" in result.stdout
    assert "42" in result.stdout


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (Docker)")
async def test_sandbox_has_no_network() -> None:
    result = await run_sandbox(
        "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)",
        timeout_seconds=15,
    )
    assert result.exit_code != 0
    assert "URLError" in result.stderr or "Name or service not known" in result.stderr


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (Docker)")
async def test_sandbox_cannot_read_host_files() -> None:
    result = await run_sandbox(
        "import pathlib\nprint(pathlib.Path('/etc/kwes-secret').exists())", timeout_seconds=15
    )
    assert result.stdout.strip() == "False"


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (Docker)")
async def test_sandbox_kills_infinite_loop() -> None:
    from app.skills.base import SkillError

    with pytest.raises(SkillError):
        await run_sandbox("import time\nwhile True: time.sleep(0.1)", timeout_seconds=3)
