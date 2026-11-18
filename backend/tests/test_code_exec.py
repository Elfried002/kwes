"""Bac à sable d'exécution : isolement, limites, refus explicite.

Depuis l'audit du 17/11, le worker ne parle plus à l'API Docker : il envoie le
code à un runner (socket Unix) qui construit lui-même la commande. Les tests
vérifient la commande du runner, puis l'isolation réelle quand
`KWES_SANDBOX_TEST=1` (runner et Docker actifs).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from app.skills.base import SkillError, SkillValidationError
from app.skills.code_exec.skill import run, run_sandbox

SANDBOX_ENABLED = os.environ.get("KWES_SANDBOX_TEST") == "1"
RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "kwes-sandbox-runner.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("kwes_sandbox_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_runner_command_is_locked_down(tmp_path: Path) -> None:
    module = _runner_module()
    argv = module.docker_argv(tmp_path, "python", "kwes-sbx-test")
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
    assert "/var/run/docker.sock" not in joined
    assert argv[-2:] == ["python", "/work/main.py"]


def test_runner_shell_entrypoint(tmp_path: Path) -> None:
    module = _runner_module()
    argv = module.docker_argv(tmp_path, "shell", "kwes-sbx-test")
    assert argv[-2:] == ["/bin/sh", "/work/main.sh"]


async def test_empty_code_is_refused() -> None:
    with pytest.raises(SkillValidationError):
        await run({"code": "   "}, ctx=None)  # type: ignore[arg-type]


async def test_unknown_language_is_refused() -> None:
    with pytest.raises(SkillValidationError):
        await run_sandbox("print(1)", language="ruby")


async def test_native_execution_sans_runner(monkeypatch, tmp_path: Path) -> None:
    """Sans conteneur ni socket, le code s'exécute nativement sur le serveur.

    Comportement voulu depuis la migration : plus de Docker, plus de runner
    séparé, exécution directe sous l'utilisateur dédié (voir `native.py`).
    """
    import app.skills.code_exec.skill as skill_module

    monkeypatch.setattr(skill_module, "SOCKET_PATH", tmp_path / "absent.sock")
    result = await run_sandbox("print(6 * 7)")
    assert result["exit_code"] == 0
    assert result["ok"] is True
    assert result["stdout"].strip() == "42"


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (runner + Docker)")
async def test_sandbox_runs_python_and_returns_stdout() -> None:
    result = await run_sandbox("print('bonjour'); print(6 * 7)", timeout_seconds=15)
    assert result["exit_code"] == 0
    assert "bonjour" in result["stdout"]
    assert "42" in result["stdout"]


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (runner + Docker)")
async def test_sandbox_has_no_network() -> None:
    result = await run_sandbox(
        "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)",
        timeout_seconds=15,
    )
    assert result["exit_code"] != 0
    assert "URLError" in result["stderr"] or "Name or service not known" in result["stderr"]


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (runner + Docker)")
async def test_sandbox_cannot_read_host_files() -> None:
    result = await run_sandbox(
        "import pathlib\nprint(pathlib.Path('/etc/kwes-secret').exists())", timeout_seconds=15
    )
    assert result["stdout"].strip() == "False"


@pytest.mark.skipif(not SANDBOX_ENABLED, reason="KWES_SANDBOX_TEST=1 requis (runner + Docker)")
async def test_sandbox_kills_infinite_loop() -> None:
    with pytest.raises(SkillError):
        await run_sandbox("import time\nwhile True: time.sleep(0.1)", timeout_seconds=3)
