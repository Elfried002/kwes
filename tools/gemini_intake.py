#!/usr/bin/env python3
"""Fenêtre de saisie de la clé Gemini — Kwes.

- écoute uniquement sur 127.0.0.1:8100 (jamais exposé directement) ;
- accessible en HTTPS sous /kwes-gemini/k/<jeton> via nginx ;
- jeton à usage unique, valable 60 minutes ;
- la clé est chiffrée (Fernet) et écrite sous GOOGLE_API_KEY_ENC ;
- aucune valeur n'est journalisée ni renvoyée dans la réponse ;
- le service s'arrête dès que la clé est enregistrée.
"""
import html
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

BASE = Path("/home/babayaga/business/kwes")
ENV_PATH = BASE / "backend/.env"
KEY_FILE = BASE / ".secrets/gemini.key"
TOKEN_PATH = BASE / ".gemini_intake_token"
STATUS_PATH = BASE / ".gemini_intake_status.json"
TTL_SECONDS = 60 * 60

TOKEN = secrets.token_urlsafe(24)
TOKEN_PATH.write_text(TOKEN)
os.chmod(TOKEN_PATH, 0o600)

START = time.time()
USED = False


def clean(value: str) -> str:
    """Retire les caractères invisibles d'un copier-coller."""
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00a0", "\n", "\r", "\t"):
        value = value.replace(ch, "")
    return value.strip()


def write_env(key: str) -> None:
    """Écrit GOOGLE_API_KEY_ENC, supprime toute ancienne clé en clair."""
    from cryptography.fernet import Fernet

    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        os.chmod(KEY_FILE, 0o600)
    token = Fernet(KEY_FILE.read_bytes()).encrypt(key.encode("utf-8")).decode("ascii")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    kept = [line for line in lines if not re.match(r"^(GOOGLE_API_KEY|GOOGLE_API_KEY_ENC|GEMINI_API_KEY)=", line)]
    kept.append(f"GOOGLE_API_KEY_ENC={token}")

    tmp = ENV_PATH.with_suffix(".env.tmp")
    tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


def check(key: str) -> dict:
    """Teste la clé : liste des modèles, puis les deux modèles autorisés."""
    checks: dict[str, str] = {}
    headers = {"x-goog-api-key": key}

    def status(url: str) -> str:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                return "ok" if response.status == 200 else f"http_{response.status}"
        except urllib.error.HTTPError as exc:
            return f"http_{exc.code}"
        except Exception:  # noqa: BLE001
            return "erreur_reseau"

    checks["cles"] = status("https://generativelanguage.googleapis.com/v1beta/models")
    for model in ("gemini-3.8-live", "gemini-3.8-live-extended-thinking"):
        checks[model] = status(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        )
    return checks


FORM = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kwes — clé Gemini</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;color:#F7FBFF;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{width:min(560px,92vw);padding:32px;border-radius:20px;background:rgba(255,255,255,.04);
border:1px solid rgba(92,231,255,.25);box-shadow:0 20px 60px rgba(0,0,0,.45)}
h1{font-size:20px;margin:0 0 6px;background:linear-gradient(90deg,#5CE7FF,#6B58FF);
-webkit-background-clip:text;color:transparent}
p{color:#B9C6E4;font-size:13px;line-height:1.5}
label{display:block;margin:18px 0 6px;font-size:13px;color:#5CE7FF}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2f55;background:#0b1030;
color:#F7FBFF;font-family:ui-monospace,Menlo,monospace;font-size:13px;box-sizing:border-box}
input:focus{outline:2px solid #267BFF;outline-offset:1px}
button{margin-top:22px;width:100%;padding:13px;border:0;border-radius:10px;font-weight:600;
font-size:14px;background:linear-gradient(90deg,#267BFF,#6B58FF);color:#fff;cursor:pointer}
small{display:block;margin-top:14px;color:#7C8AB5;font-size:11px;line-height:1.5}
</style></head><body><main>
<h1>Nouvelle clé Gemini</h1>
<p>Lien à usage unique, valable 60 minutes. La clé est chiffrée sur le serveur
(<code>GOOGLE_API_KEY_ENC</code>) et n'est jamais affichée ni journalisée.</p>
<form method="POST" action="">
<label for="k">Clé API Gemini (AIza…)</label>
<input id="k" name="gemini" type="password" autocomplete="off" spellcheck="false" required>
<button type="submit">Enregistrer la clé</button>
</form>
<small>L'ancienne clé doit être révoquée dans Google AI Studio. Cette page ne dépose
aucun cookie et n'appelle aucun service externe depuis votre appareil.</small>
</main></body></html>"""

OK_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kwes — clé enregistrée</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;color:#F7FBFF;
font-family:system-ui,sans-serif}main{text-align:center;padding:28px;max-width:520px}
code{color:#5CE7FF}</style></head>
<body><main><h1>Clé enregistrée</h1><p>Vérification : %s</p>
<p>Cette page est désormais close. Vous pouvez la fermer.</p></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "KwesGeminiIntake/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _path_ok(self, path: str) -> bool:
        return path.rstrip("/") == f"/k/{TOKEN}"

    def _send(self, code: int, body: str):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if used_or_expired():
            return self._send(410, "<h1>Lien expiré</h1>")
        if not self._path_ok(self.path.split("?")[0]):
            return self._send(404, "<h1>Introuvable</h1>")
        self._send(200, FORM)

    def do_POST(self):  # noqa: N802
        if used_or_expired():
            return self._send(410, "<h1>Lien expiré</h1>")
        if not self._path_ok(self.path.split("?")[0]):
            return self._send(404, "<h1>Introuvable</h1>")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8192:
            return self._send(413, "<h1>Requête invalide</h1>")
        body = self.rfile.read(length).decode("utf-8", "replace")
        key = clean(parse_qs(body).get("gemini", [""])[0])
        if len(key) < 20 or any(ch.isspace() for ch in key):
            return self._send(400, "<h1>Clé invalide</h1><p>Format inattendu, rien n'a été enregistré.</p>")

        write_env(key)
        checks = check(key)
        STATUS_PATH.write_text(
            json.dumps(
                {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": checks, "mode": "0600"},
                ensure_ascii=False,
            )
        )
        os.chmod(STATUS_PATH, 0o600)
        used_or_expired(force=True)
        self._send(200, OK_PAGE % html.escape(json.dumps(checks, ensure_ascii=False)))
        threading.Timer(2.0, lambda: os._exit(0)).start()


def used_or_expired(force: bool = False) -> bool:
    global USED
    if force:
        USED = True
        try:
            os.remove(TOKEN_PATH)
        except OSError:
            pass
        return False
    return USED or (time.time() - START) > TTL_SECONDS


def main() -> None:
    if not ENV_PATH.exists():
        print(json.dumps({"erreur": f"{ENV_PATH} absent"}), file=sys.stderr)
        raise SystemExit(1)
    server = ThreadingHTTPServer(("127.0.0.1", 8100), Handler)
    threading.Timer(TTL_SECONDS + 5, lambda: os._exit(0)).start()
    print(json.dumps({"port": 8100, "ttl_s": TTL_SECONDS}))
    server.serve_forever()


if __name__ == "__main__":
    main()
