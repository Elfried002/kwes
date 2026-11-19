"""Mission agentique réelle en staging : plan, spécialistes, journal, livrable."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:18001/api/v1"
TOKEN = Path("/home/babayaga/business/kwes/.sb_bearer").read_text().strip()
HEAD = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
OBJECTIF = (
    "Compare le prix du cacao en Côte d'Ivoire cette semaine avec deux sources datées, "
    "puis rédige un rapport court avec une recommandation d'achat."
)


def call(method: str, path: str, body: dict | None = None, timeout: int = 120):
    request = urllib.request.Request(
        f"{BASE}{path}", method=method, headers=HEAD,
        data=json.dumps(body).encode() if body else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:400].decode(errors="replace")


status, created = call("POST", "/missions", {"objective": OBJECTIF, "language": "fr"})
print("création:", status, created if status >= 400 else created.get("id"))
if status != 201:
    raise SystemExit(1)

mission_id = created["id"]
etats = []
for tick in range(60):
    time.sleep(5)
    code, vue = call("GET", f"/missions/{mission_id}")
    if code != 200:
        print("lecture:", code, vue)
        break
    taches = [(t["agent_id"], t["status"]) for t in vue["tasks"]]
    etats.append((vue["status"], len(vue["events"]), taches))
    print(f"  {tick * 5:3d}s {vue['status']:<18} événements={len(vue['events']):<3} tâches={taches}")
    if vue["status"] in {"completed", "completed_partial", "failed", "cancelled"}:
        Path("/tmp/mission_e2e.json").write_text(json.dumps(vue, ensure_ascii=False, indent=2))
        print("\nLIVRABLE:\n", (vue.get("summary") or "")[:1500])
        print("\npreuves par tâche:")
        for t in vue["tasks"]:
            print(f"  - {t['agent_id']}: {t['status']}, preuves={len(t['evidence'])}, "
                  f"outils={t['tools']}")
        print("\névénements distincts:", sorted({e["type"] for e in vue["events"]}))
        break
