"""Rafraîchit le jeton Supabase de test et réécrit .sb_bearer (0600)."""

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path("/home/babayaga/business/kwes")
env = dict(
    line.split("=", 1)
    for line in (ROOT / "backend/.env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
supabase = env["SUPABASE_URL"].strip().strip('"')
anon = env["SUPABASE_ANON_KEY"].strip().strip('"')
session = json.loads((ROOT / ".sb_session.json").read_text())

request = urllib.request.Request(
    f"{supabase}/auth/v1/token?grant_type=refresh_token",
    data=json.dumps({"refresh_token": session["refresh_token"]}).encode(),
    headers={"apikey": anon, "Content-Type": "application/json"},
)
fresh = json.loads(urllib.request.urlopen(request).read())
session.update({"access_token": fresh["access_token"], "refresh_token": fresh["refresh_token"]})
(ROOT / ".sb_session.json").write_text(json.dumps(session))
bearer = ROOT / ".sb_bearer"
bearer.write_text(fresh["access_token"])
os.chmod(bearer, 0o600)
print("jeton rafraîchi")
