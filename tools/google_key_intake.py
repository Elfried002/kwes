#!/usr/bin/env python3
"""Fenêtre de saisie de la clé Google Gemini — Kwes.

Deux facteurs, une seule utilisation, 60 minutes :
  1. le lien contient un jeton aléatoire de 24 octets ;
  2. la page demande un code à 6 chiffres, communiqué par un autre canal.

La clé n'est jamais journalisée, jamais renvoyée, jamais écrite en clair dans
`.env` : elle est chiffrée (Fernet) avec une clé locale en 600, uniquement
déchiffrable par le backend qui tourne sous le même compte système.

La validation est un vrai appel à l'API Google :
  - `GET /v1beta/models` (la clé est-elle acceptée ?) ;
  - `POST /v1beta/auth_tokens` (l'accès Live API est-il autorisé ?).
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from cryptography.fernet import Fernet

BASE = Path("/home/babayaga/business/kwes")
ENV_PATH = BASE / "backend/.env"
SECRETS_DIR = BASE / ".secrets"
KEY_PATH = SECRETS_DIR / "gemini.key"
TOKEN_PATH = BASE / ".google_intake_token"
CODE_PATH = BASE / ".google_intake_code"
STATUS_PATH = BASE / ".google_intake_status.json"

TTL_SECONDS = 60 * 60
MAX_CODE_ATTEMPTS = 5
GEMINI_MODEL = "gemini-3.8-live"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

TOKEN = secrets.token_urlsafe(24)
CODE = f"{secrets.randbelow(1_000_000):06d}"
START = time.time()
USED = False
ATTEMPTS = {"count": 0}

TOKEN_PATH.write_text(TOKEN)
os.chmod(TOKEN_PATH, 0o600)
CODE_PATH.write_text(CODE)
os.chmod(CODE_PATH, 0o600)


def write_secret(ciphertext: str) -> None:
    """Écrit la valeur chiffrée dans .env, sans jamais toucher aux autres lignes."""
    lines: list[str] = []
    replaced = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("GOOGLE_API_KEY_ENC="):
                lines.append(f"GOOGLE_API_KEY_ENC={ciphertext}")
                replaced = True
            elif line.startswith("GOOGLE_API_KEY="):
                # Ancienne clé en clair : retirée du fichier.
                continue
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"GOOGLE_API_KEY_ENC={ciphertext}")
    if not any(line.startswith("GOOGLE_VOICE=") for line in lines):
        lines.append("GOOGLE_VOICE=Charon")
    if not any(line.startswith("GOOGLE_LIVE_MODEL=") for line in lines):
        lines.append(f"GOOGLE_LIVE_MODEL={GEMINI_MODEL}")
    tmp = ENV_PATH.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


def google_get(url: str, key: str) -> tuple[int, dict | str]:
    request = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw[:200].decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx : corps utile pour le diagnostic
        return exc.code, ""
    except Exception:  # noqa: BLE001
        return 0, ""


def google_post(url: str, key: str, payload: dict) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:  # noqa: BLE001
        return 0, ""


FORM = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kwes — clé Google Gemini</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;color:#F7FBFF;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{width:min(560px,92vw);padding:32px;border-radius:20px;background:rgba(255,255,255,.04);
border:1px solid rgba(92,231,255,.25);box-shadow:0 20px 60px rgba(0,0,0,.45)}
h1{font-size:20px;margin:0 0 6px;background:linear-gradient(90deg,#5CE7FF,#6B58FF);
-webkit-background-clip:text;color:transparent}
p{color:#B9C6E4;font-size:13px;line-height:1.55}
label{display:block;margin:18px 0 6px;font-size:13px;color:#5CE7FF}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2f55;background:#0b1030;
color:#F7FBFF;font-family:ui-monospace,Menlo,monospace;font-size:13px;box-sizing:border-box}
input:focus{outline:2px solid #267BFF;outline-offset:1px}
button{margin-top:22px;width:100%;padding:13px;border:0;border-radius:10px;font-weight:600;
font-size:14px;background:linear-gradient(90deg,#267BFF,#6B58FF);color:#fff;cursor:pointer}
small{display:block;margin-top:14px;color:#7C8AB5;font-size:11px;line-height:1.5}
</style></head><body><main>
<h1>Clé Google Gemini</h1>
<p>Lien à usage unique, valable 60 minutes, protégé par le code à 6 chiffres reçu sur ton téléphone.
La clé est chiffrée avant d'être écrite dans <code>backend/.env</code> (600) ; elle n'est jamais
affichée, ni journalisée, ni renvoyée.</p>
<form method="POST" action="">
<label for="c">Code d'accès (6 chiffres)</label>
<input id="c" name="code" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code"
spellcheck="false" required>
<label for="k">GOOGLE_API_KEY</label>
<input id="k" name="key" type="password" autocomplete="off" spellcheck="false" required>
<button type="submit">Vérifier et enregistrer</button>
</form>
<small>La vérification appelle réellement l'API Google : liste des modèles, puis création d'un
jeton Live éphémère. Aucun cookie, aucun service tiers depuis cette page.</small>
</main></body></html>"""


def result_page(checks: dict, ok: bool) -> str:
    title = "Clé Gemini enregistrée" if ok else "Clé refusée"
    color = "#5CE7FF" if ok else "#FF8A8A"
    rows = "".join(
        f"<li><strong>{html.escape(label)}</strong> : {html.escape(str(value))}</li>"
        for label, value in checks.items()
    )
    note = (
        "<p>Le backend utilise désormais Gemini Live pour la voix. ElevenLabs n'est plus appelé.</p>"
        if ok
        else "<p>Rien n'a été enregistré. Vérifie que l'API Gemini est activée sur le projet Google, puis réessaie.</p>"
    )
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kwes — Gemini</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#100B32;
color:#F7FBFF;font-family:system-ui,sans-serif}}main{{width:min(560px,92vw);padding:28px;
border-radius:18px;background:rgba(255,255,255,.04);border:1px solid rgba(92,231,255,.25)}}
h1{{font-size:19px;color:{color};margin:0 0 12px}}ul{{list-style:none;padding:0;font-size:13px;
line-height:1.9;color:#B9C6E4}}p{{font-size:13px;color:#B9C6E4}}</style></head>
<body><main><h1>{title}</h1><ul>{rows}</ul>{note}</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "KwesGoogleIntake/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # aucune donnée de requête journalisée
        return

    def _path_ok(self, path: str) -> bool:
        return path.rstrip("/") == f"/k/{TOKEN}"

    def _send(self, code: int, body: str) -> None:
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
        fields = parse_qs(body)
        code = (fields.get("code", [""])[0] or "").strip()
        key = (fields.get("key", [""])[0] or "").strip()
        # Copier-coller depuis un gestionnaire de mots de passe peut ajouter des
        # espaces ou des caractères invisibles : on les retire, sans imposer un
        # format Google plus strict que le fournisseur lui-même.
        key = "".join(ch for ch in key if 33 <= ord(ch) <= 126)

        ATTEMPTS["count"] += 1
        if ATTEMPTS["count"] > MAX_CODE_ATTEMPTS:
            used_or_expired(force=True)
            return self._send(429, "<h1>Trop de tentatives</h1><p>Lien fermé.</p>")
        if not secrets.compare_digest(code, CODE):
            return self._send(
                403,
                result_page(
                    {"Code d'accès": "incorrect", "Enregistrement": "aucun"}, False
                ),
            )
        if not (20 <= len(key) <= 512) or not re.fullmatch(r"[A-Za-z0-9_\-\.]+", key):
            return self._send(
                400,
                result_page(
                    {
                        "Clé reçue": f"non exploitable ({len(key)} caractères utiles)",
                        "Enregistrement": "aucun",
                    },
                    False,
                ),
            )

        status, payload = google_get(f"{API_ROOT}/models?pageSize=1", key)
        models: list[str] = []
        if status == 200 and isinstance(payload, dict):
            models = [str(item.get("name", "")) for item in payload.get("models", [])]

        live_status, live_payload = google_post(
            f"{API_ROOT}/auth_tokens",
            key,
            {
                "uses": 1,
                "expireTime": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 300)
                ),
                "newSessionExpireTime": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 120)
                ),
            },
        )

        checks = {
            "Clé reçue": "oui (non affichée, non journalisée)",
            "Liste des modèles": "ok" if status == 200 else f"refusée (HTTP {status})",
            "Jeton Live éphémère": "ok" if live_status == 200 else f"refusé (HTTP {live_status})",
        }
        ok = status == 200 and live_status == 200

        if ok:
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            if not KEY_PATH.exists():
                KEY_PATH.write_bytes(Fernet.generate_key())
                os.chmod(KEY_PATH, 0o600)
            ciphertext = Fernet(KEY_PATH.read_bytes()).encrypt(key.encode("utf-8")).decode("ascii")
            write_secret(ciphertext)
            checks["Modèle vocal"] = GEMINI_MODEL

        STATUS_PATH.write_text(
            json.dumps(
                {
                    "le": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "checks": checks,
                    "env_path": str(ENV_PATH),
                    "mode": "0600",
                    "encrypted": ok,
                    "model": GEMINI_MODEL,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        os.chmod(STATUS_PATH, 0o600)

        if ok:
            used_or_expired(force=True)
        self._send(200 if ok else 502, result_page(checks, ok))
        if ok:
            threading.Timer(2.0, lambda: os._exit(0)).start()


def used_or_expired(force: bool = False) -> bool:
    global USED
    if force:
        USED = True
        for path in (TOKEN_PATH, CODE_PATH):
            try:
                os.remove(path)
            except OSError:
                pass
        return False
    return USED or (time.time() - START) > TTL_SECONDS


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8100), Handler)
    threading.Timer(TTL_SECONDS + 5, lambda: os._exit(0)).start()
    print(json.dumps({"port": 8100, "ttl_s": TTL_SECONDS}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
