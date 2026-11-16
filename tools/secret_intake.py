#!/usr/bin/env python3
"""Fenêtre de saisie ponctuelle de secrets — Kwes.

- écoute uniquement sur 127.0.0.1:8099 (jamais exposé directement)
- accessible via nginx en HTTPS sous /kwes-secret/k/<token>
- jeton à usage unique, TTL 20 minutes
- aucune valeur de secret n'est journalisée ni renvoyée dans la réponse
- le service s'arrête dès que les clés sont enregistrées
"""
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

BASE = "/home/babayaga/business/kwes"
ENV_PATH = f"{BASE}/backend/.env"
TOKEN_PATH = f"{BASE}/.secret_intake_token"
STATUS_PATH = f"{BASE}/.secret_intake_status.json"
TTL_SECONDS = 60 * 60

TOKEN = secrets.token_urlsafe(24)
with open(TOKEN_PATH, "w") as f:
    f.write(TOKEN)
os.chmod(TOKEN_PATH, 0o600)

START = time.time()
USED = False

DEFAULTS = {
    "DATABASE_URL": "postgresql+psycopg://kwes:kwes@127.0.0.1:5432/kwes",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "DEV_JWT_SECRET": "dev-secret-change-me",
    "SUPABASE_JWT_SECRET": "",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-chat",
    "ELEVENLABS_VOICE_ID": "",
    "CORS_ORIGINS": "http://127.0.0.1:5173,http://localhost:5173",
}


def write_env(keys: dict) -> None:
    existing = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    merged = {**DEFAULTS, **existing, **keys}
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Kwes — secrets locaux. Ne jamais commiter.\n")
        for k, v in merged.items():
            f.write(f"{k}={v}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


def check_key(url: str, header: str, value: str) -> str:
    try:
        req = urllib.request.Request(url, headers={header: value})
        with urllib.request.urlopen(req, timeout=12) as r:
            return "ok" if 200 <= r.status < 300 else f"http_{r.status}"
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        return f"http_{code}" if code else "erreur_reseau"


FORM = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kwes — clés API</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;color:#F7FBFF;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{width:min(560px,92vw);padding:32px;border-radius:20px;background:rgba(255,255,255,.04);
border:1px solid rgba(92,231,255,.25);box-shadow:0 20px 60px rgba(0,0,0,.45)}
h1{font-size:20px;margin:0 0 6px;background:linear-gradient(90deg,#5CE7FF,#6B58FF);-webkit-background-clip:text;color:transparent}
p{color:#B9C6E4;font-size:13px;line-height:1.5}
label{display:block;margin:16px 0 6px;font-size:13px;color:#5CE7FF}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2f55;background:#0b1030;color:#F7FBFF;
font-family:ui-monospace,Menlo,monospace;font-size:13px;box-sizing:border-box}
input:focus{outline:2px solid #267BFF;outline-offset:1px}
button{margin-top:22px;width:100%;padding:13px;border:0;border-radius:10px;font-weight:600;font-size:14px;
background:linear-gradient(90deg,#267BFF,#6B58FF);color:#fff;cursor:pointer}
small{display:block;margin-top:14px;color:#7C8AB5;font-size:11px}
</style></head><body><main>
<h1>Clés API — Kwes</h1>
<p>Lien à usage unique, valable 20 minutes. Les clés sont écrites dans <code>backend/.env</code> (permissions 600)
et ne transitent jamais par Telegram. Aucune valeur n'est affichée ni journalisée après l'envoi.</p>
<form method="POST" action="">
<label for="d">DEEPSEEK_API_KEY</label>
<input id="d" name="deepseek" type="password" autocomplete="off" spellcheck="false" required>
<label for="e">ELEVENLABS_API_KEY</label>
<input id="e" name="elevenlabs" type="password" autocomplete="off" spellcheck="false">
<button type="submit">Enregistrer</button>
</form>
<small>Cette page ne dépose aucun cookie et n'appelle aucun service externe.</small>
</main></body></html>"""

OK_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kwes — enregistré</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;color:#F7FBFF;
font-family:system-ui,sans-serif}main{text-align:center;padding:28px}</style></head>
<body><main><h1>Clés enregistrées</h1><p>Vérification : %s</p>
<p>Cette page est désormais close.</p></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "KwesSecretIntake/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silence: aucune donnée de requête journalisée
        return

    def _path_ok(self, path: str) -> bool:
        return path.rstrip("/") == f"/k/{TOKEN}"

    def _send(self, code: int, body: str, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        global USED
        if used_or_expired():
            return self._send(410, "<h1>Lien expiré</h1>")
        if not self._path_ok(self.path.split("?")[0]):
            return self._send(404, "<h1>Introuvable</h1>")
        self._send(200, FORM)

    def do_POST(self):  # noqa: N802
        global USED
        if used_or_expired():
            return self._send(410, "<h1>Lien expiré</h1>")
        if not self._path_ok(self.path.split("?")[0]):
            return self._send(404, "<h1>Introuvable</h1>")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8192:
            return self._send(413, "<h1>Requête invalide</h1>")
        body = self.rfile.read(length).decode("utf-8", "replace")
        fields = parse_qs(body)
        ds = (fields.get("deepseek", [""])[0] or "").strip()
        el = (fields.get("elevenlabs", [""])[0] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-\.]{16,200}", ds):
            return self._send(400, "<h1>Clé DeepSeek invalide</h1><p>Format inattendu, rien n'a été enregistré.</p>")
        if el and not re.fullmatch(r"[A-Za-z0-9_\-\.]{16,200}", el):
            return self._send(400, "<h1>Clé ElevenLabs invalide</h1><p>Format inattendu, rien n'a été enregistré.</p>")
        keys = {"DEEPSEEK_API_KEY": ds}
        if el:
            keys["ELEVENLABS_API_KEY"] = el
        write_env(keys)
        checks = {
            "deepseek": check_key("https://api.deepseek.com/models", "Authorization", f"Bearer {ds}"),
            "elevenlabs": check_key("https://api.elevenlabs.io/v1/voices", "xi-api-key", el) if el else "non fourni",
        }
        with open(STATUS_PATH, "w") as f:
            json.dump({"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": checks,
                       "env_path": ENV_PATH, "mode": "0600"}, f)
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


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 8099), Handler)
    threading.Timer(TTL_SECONDS + 5, lambda: os._exit(0)).start()
    print(json.dumps({"port": 8099, "token_file": TOKEN_PATH, "ttl_s": TTL_SECONDS}))
    srv.serve_forever()


if __name__ == "__main__":
    main()
