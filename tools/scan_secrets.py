"""Recherche de secrets dans les fichiers suivis par Git.

Utilisé en local et dans la CI : aucun secret ne doit être commité. Le script
n'imprime jamais la valeur trouvée, seulement le fichier et la ligne.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[0-9A-Za-z_\-]{20,}")),
    ("elevenlabs_key", re.compile(r"xi-api-key\s*[:=]\s*[0-9a-f]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}")),
    ("jwt", re.compile(r"eyJhbGciOi[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("db_url_with_password", re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s:@/]{6,}@")),
    ("supabase_service_role", re.compile(r"service_role[^\n]{0,40}eyJ")),
]

ALLOWED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".md", ".yml", ".yaml", ".json", ".sql", ".txt", ".service", ".toml", ".sh"}
SKIP_FILES = {".env", ".sb_bearer", ".sb_session.json"}


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def scan() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_files():
        if path.name in SKIP_FILES or not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES and path.name != "Dockerfile":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if "scan_secrets" in line or "PATTERNS" in line:
                continue
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                if label == "db_url_with_password":
                    # Les exemples documentaires (`<password>`, `***`) ne sont
                    # pas des secrets : on ne signale qu'une valeur plausible.
                    password = re.search(r"://[^:]+:([^@]+)@", line)
                    if password and (
                        password.group(1).startswith("<")
                        or set(password.group(1)) <= {"*", "x", "X", "."}
                    ):
                        continue
                findings.append((str(path), number, label))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("Aucun secret détecté dans les fichiers suivis.")
        return 0
    for path, line, label in findings:
        print(f"{path}:{line} → motif « {label} »")
    print(f"{len(findings)} occurrence(s) à corriger.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
