"""Configure l'authentification Supabase via l'API Management.

Le jeton d'accès personnel (PAT) n'est jamais écrit dans le dépôt : il est lu
dans `SUPABASE_ACCESS_TOKEN` ou dans `~/.secrets/supabase_pat` (600).

Usage :
    python tools/supabase_auth_config.py --check
    python tools/supabase_auth_config.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJET = "yhgbvyibsvsjpxsnjdzn"
SITE_URL = "https://agent-kwes.com"
REDIRECTIONS = [
    "https://agent-kwes.com/**",
    "https://www.agent-kwes.com/**",
    "https://kwes.vercel.app/**",
]
TEMPLATE_OTP = """<h2>Votre code KWES</h2>
<p>Voici votre code de vérification : <strong>{{ .Token }}</strong></p>
<p>Il expire dans {{ .TokenExpiresIn }} minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>
"""


def jeton() -> str:
    env = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if env:
        return env
    chemin = Path.home() / ".secrets" / "supabase_pat"
    if chemin.exists():
        return chemin.read_text().strip()
    print("PAT absent : définir SUPABASE_ACCESS_TOKEN ou créer ~/.secrets/supabase_pat (600).")
    raise SystemExit(2)


def appel(methode: str, chemin: str, corps: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"https://api.supabase.com{chemin}",
        method=methode,
        data=json.dumps(corps).encode() if corps else None,
        headers={
            "Authorization": f"Bearer {jeton()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        print(f"HTTP {exc.code} sur {chemin} : {detail}")
        raise SystemExit(1)


def etat() -> dict:
    config = appel("GET", f"/v1/projects/{PROJET}/config/auth")
    return {
        "site_url": config.get("site_url"),
        "uri_allow_list": config.get("uri_allow_list"),
        "mailer_autoconfirm": config.get("mailer_autoconfirm"),
        "otp_length": config.get("mailer_otp_length"),
        "otp_expiry": config.get("mailer_otp_exp"),
    }


def afficher(config: dict) -> None:
    print("Site URL            :", config["site_url"])
    print("Redirect URLs       :", config["uri_allow_list"])
    print("Confirmation e-mail :", "désactivée" if config["mailer_autoconfirm"] else "activée")
    print("Longueur OTP        :", config["otp_length"])
    print("Expiration OTP (s)  :", config["otp_expiry"])


def appliquer() -> None:
    corps = {
        "site_url": SITE_URL,
        "uri_allow_list": ",".join(REDIRECTIONS),
        # Confirmation obligatoire : le compte n'ouvre une session qu'après le code.
        "mailer_autoconfirm": False,
        "mailer_otp_length": 6,
        "mailer_otp_exp": 3600,
        "mailer_subjects_confirmation": "Votre code de vérification KWES",
        "mailer_templates_confirmation_content": TEMPLATE_OTP,
    }
    appel("PATCH", f"/v1/projects/{PROJET}/config/auth", corps)
    print("Configuration appliquée.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    config = etat()
    afficher(config)
    if args.apply:
        appliquer()
        print("\nAprès application :")
        afficher(etat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
