#!/usr/bin/env python3
"""Runner de bac à sable Kwes — socket Unix, commande Docker fixe.

Pourquoi ce service existe : exposer l'API Docker (même via un proxy filtrant)
permet à tout processus local de créer un conteneur privilégié avec « / » monté,
donc de prendre le serveur. Vérifié pendant l'audit du 17/11.

Ici, le seul contrat exposé est : « exécute ce code Python/shell dans un
conteneur jetable ». La commande Docker est construite par ce service, jamais
transmise par le client. Aucun argument client n'atteint `docker run`.

Socket : /run/kwes/sandbox.sock, 0660 root:kwes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

SOCKET_PATH = Path(os.environ.get("KWES_SANDBOX_SOCKET", "/run/kwes/sandbox.sock"))
WORK_ROOT = Path(os.environ.get("KWES_SANDBOX_ROOT", "/var/lib/kwes-sandbox"))
IMAGE = "python:3.12-alpine"
MAX_CODE = 20_000
MAX_TIMEOUT = 20
MAX_OUTPUT = 20_000
DOCKER = "/usr/bin/docker"


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def docker_argv(workdir: Path, language: str, name: str) -> list[str]:
    entry = ["/bin/sh", "/work/main.sh"] if language == "shell" else ["python", "/work/main.py"]
    return [
        DOCKER, "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", "256m", "--memory-swap", "256m",
        "--cpus", "0.5", "--pids-limit", "64",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:size=32m",
        "--user", "65534:65534",
        "--workdir", "/work",
        "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", f"type=bind,src={workdir},dst=/work",
        IMAGE, *entry,
    ]


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def execute(code: str, language: str, timeout: int) -> dict:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="run-", dir=WORK_ROOT))
    name = f"kwes-sbx-{uuid.uuid4().hex[:12]}"
    try:
        filename = "main.sh" if language == "shell" else "main.py"
        script = workdir / filename
        script.write_text(code, encoding="utf-8")
        workdir.chmod(0o755)
        script.chmod(0o644)
        started = time.monotonic()
        proc = subprocess.Popen(
            docker_argv(workdir, language, name),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            subprocess.run([DOCKER, "rm", "-f", name], capture_output=True, timeout=10, check=False)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return {"ok": False, "error": f"Exécution interrompue après {timeout} s (limite)."}
        duration = int((time.monotonic() - started) * 1000)
        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "stdout": stdout[:MAX_OUTPUT],
            "stderr": stderr[:MAX_OUTPUT],
            "exit_code": int(proc.returncode or 0),
            "duration_ms": duration,
            "truncated": len(stdout) > MAX_OUTPUT,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = "?"
    try:
        sock = writer.get_extra_info("socket")
        if sock is not None:
            uid, _pid, _gid = struct_peercred(sock)
            peer = f"uid={uid}"
        raw = await asyncio.wait_for(reader.readline(), timeout=10)
        try:
            request = json.loads(raw.decode("utf-8"))
        except Exception:
            writer.write(b'{"ok":false,"error":"requete_invalide"}\n')
            await writer.drain()
            return
        code = str(request.get("code") or "")
        language = str(request.get("language") or "python")
        timeout = int(request.get("timeout") or 10)
        if not code.strip():
            writer.write(b'{"ok":false,"error":"code_vide"}\n')
            await writer.drain()
            return
        if len(code) > MAX_CODE:
            writer.write(b'{"ok":false,"error":"code_trop_long"}\n')
            await writer.drain()
            return
        if language not in ("python", "shell"):
            writer.write(b'{"ok":false,"error":"langage_non_supporte"}\n')
            await writer.drain()
            return
        timeout = max(1, min(MAX_TIMEOUT, timeout))
        log(f"execution {peer} langage={language} taille={len(code)} timeout={timeout}")
        result = await asyncio.to_thread(execute, code, language, timeout)
        writer.write((json.dumps(result) + "\n").encode("utf-8"))
        await writer.drain()
    except Exception as exc:  # noqa: BLE001 — une requête cassée ne tue pas le service
        log(f"erreur requete {peer}: {type(exc).__name__}")
        try:
            writer.write(json.dumps({"ok": False, "error": "erreur_interne"}).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def struct_peercred(sock) -> tuple[int, int, int]:
    import socket as socket_module
    import struct

    creds = sock.getsockopt(socket_module.SOL_SOCKET, socket_module.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", creds)
    return uid, pid, gid


async def main() -> None:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Le dossier doit être traversable pour que le groupe kwes atteigne le
        # socket ; l'accès reste contrôlé par les droits du socket (0660).
        os.chmod(SOCKET_PATH.parent, 0o755)
    except OSError:
        pass
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    server = await asyncio.start_unix_server(handle, path=str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o660)
    try:
        shutil.chown(SOCKET_PATH, user="root", group="kwes")
    except LookupError:
        log("groupe kwes absent : socket laissé à root")
    log(f"runner prêt sur {SOCKET_PATH}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
