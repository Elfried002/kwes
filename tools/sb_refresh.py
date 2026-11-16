"""Rafraîchit le jeton de test Supabase (dev uniquement).

Lit `SUPABASE_URL` et `SUPABASE_ANON_KEY` dans `backend/.env`, échange le
`refresh_token` de `.sb_session.json`, puis réécrit `.sb_session.json` et
`.sb_bearer`. N'affiche jamais le jeton : seulement son type et son expiration.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "backend" / ".env"
SESSION = ROOT / ".sb_session.json"
BEARER = ROOT / ".sb_bearer"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    env = read_env()
    base = env.get("SUPABASE_URL", "").rstrip("/")
    anon = env.get("SUPABASE_ANON_KEY", "")
    if not base or not anon:
        print("SUPABASE_URL ou SUPABASE_ANON_KEY absent de backend/.env")
        return 1

    session = json.loads(SESSION.read_text(encoding="utf-8"))
    refresh = session.get("refresh_token")
    if not refresh:
        print("Aucun refresh_token dans .sb_session.json")
        return 1

    body = json.dumps({"refresh_token": refresh}).encode()
    request = urllib.request.Request(
        f"{base}/auth/v1/token?grant_type=refresh_token",
        data=body,
        headers={"apikey": anon, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 — outil de dev
        print(f"Échec du rafraîchissement: {type(exc).__name__}")
        return 1

    session.update(
        {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", refresh),
            "expires_in": data.get("expires_in"),
            "expires_at": int(time.time()) + int(data.get("expires_in", 3600)),
            "token_type": data.get("token_type", "bearer"),
        }
    )
    SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")
    os.chmod(SESSION, 0o600)
    BEARER.write_text(session["access_token"], encoding="utf-8")
    os.chmod(BEARER, 0o600)
    print(
        json.dumps(
            {
                "status": "ok",
                "expires_at": session["expires_at"],
                "remaining_seconds": session["expires_at"] - int(time.time()),
                "user": session.get("user", {}).get("id"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
