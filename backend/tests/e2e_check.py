#!/usr/bin/env python3
"""Vérification de bout en bout du backend Kwes (Postgres réel + Gemini réel)."""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

ENV = "/home/babayaga/business/kwes/backend/.env"
cfg = {}
for line in open(ENV, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()

B = "http://127.0.0.1:8000/api/v1"
with httpx.Client(timeout=30) as _c:
    tok = _c.post(f"{B}/dev/token", json={"email": "elfried@zawena.com"}).json()
token = tok["token"]
H = {"Authorization": f"Bearer {token}"}

with httpx.Client(timeout=120) as c:
    print("health:", c.get(f"{B}/health").json())
    r = c.post(f"{B}/conversations", json={"title": "vérification e2e"}, headers=H)
    print("création conversation:", r.status_code)
    conv = r.json().get("id") if r.status_code < 300 else None

    r = c.post(f"{B}/chat", json={"conversation_id": conv,
                                  "message": "Réponds en une phrase : que sais-tu faire ?",
                                  "language": "fr", "mode": "auto"}, headers=H)
    print("chat:", r.status_code, "| mock:", r.headers.get("X-Kwes-Mock"))
    body = r.json() if r.status_code < 300 else r.text[:300]
    if isinstance(body, dict):
        print("  réponse:", str(body.get("response"))[:220])
        print("  task_id:", body.get("task_id"), "| status:", body.get("status"))
        tid = body.get("task_id")
    else:
        print(body)
        tid = None

    if tid:
        r = c.get(f"{B}/tasks/{tid}", headers=H)
        t = r.json() if r.status_code < 300 else {}
        print("task:", r.status_code, "|", t.get("status"), "| progress:", t.get("progress"))
        r = c.get(f"{B}/tasks/{tid}", headers=H)
    r = c.get(f"{B}/tasks", headers=H)
    data = r.json() if r.status_code < 300 else []
    print("liste tâches:", r.status_code, "| nb:", len(data) if isinstance(data, list) else data)

    r = c.get(f"{B}/skills", headers=H)
    data = r.json() if r.status_code < 300 else []
    print("skills:", r.status_code, [s.get("name") for s in data] if isinstance(data, list) else data)

    # Mission réelle : doit créer une tâche et la faire exécuter par le worker
    import time
    r = c.post(f"{B}/chat", json={"conversation_id": conv,
        "message": "Prépare une mission de recherche web sur le marché des agents IA en Côte d'Ivoire, puis résume.",
        "language": "fr", "mode": "mission"}, headers=H)
    print("chat mission:", r.status_code, "| mock:", r.headers.get("X-Kwes-Mock"))
    b = r.json() if r.status_code < 300 else {}
    tid = b.get("task_id")
    print("  task_id:", tid, "| status:", b.get("status"))
    if tid:
        for _ in range(20):
            t = c.get(f"{B}/tasks/{tid}", headers=H).json()
            print("   ->", t.get("status"), "| progression:", t.get("progress"))
            if t.get("status") in ("completed", "failed", "awaiting_approval", "cancelled"):
                break
            time.sleep(2)
