"""Résolution des secrets fournisseurs (chiffrés au repos).

Les clés ne sont jamais stockées en clair dans `.env` : on y trouve
`<NOM>_ENC`, un jeton Fernet, et la clé de déchiffrement vit dans un fichier
`600` hors du dépôt (`.secrets/<fournisseur>.key`). Le backend tourne sous le
même compte système, donc il est le seul à pouvoir lire les deux.

Résolution, dans l'ordre :
1. variable d'environnement en clair (`<NOM>`) — utile en CI ou en local ;
2. `<NOM>_ENC` dans `.env`, déchiffré avec la clé locale ;
3. chaîne vide (le fournisseur bascule alors en mode dégradé explicite).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("kwes.secrets")

# Racine du dépôt : backend/app/core/secrets.py -> backend/app/core -> backend -> racine
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KEY_FILE = PROJECT_ROOT / ".secrets" / "gemini.key"


def _key_file() -> Path:
    override = os.environ.get("KWES_SECRETS_KEY_FILE")
    return Path(override) if override else DEFAULT_KEY_FILE


def decrypt_value(ciphertext: str, *, key_file: Path | None = None) -> str:
    path = key_file or _key_file()
    if not path.is_file():
        logger.warning("Clé de déchiffrement absente: %s", path)
        return ""
    try:
        return Fernet(path.read_bytes()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("Déchiffrement impossible (jeton ou clé invalide).")
        return ""


def resolve_secret(name: str) -> str:
    """Valeur en clair d'un secret, ou chaîne vide. Jamais journalisée."""
    plain = os.environ.get(name, "").strip()
    if plain:
        return plain
    encrypted = os.environ.get(f"{name}_ENC", "").strip()
    if not encrypted:
        # pydantic lit `.env` ; hors Settings (scripts, tests) on retombe dessus.
        encrypted = _read_env_file(f"{name}_ENC")
    if encrypted:
        return decrypt_value(encrypted).strip()
    return ""


def _read_env_file(key: str) -> str:
    env_path = PROJECT_ROOT / "backend" / ".env"
    if not env_path.is_file():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def encrypt_to_env(name: str, value: str) -> None:
    """Utilitaire d'administration : écrit `<NOM>_ENC` dans backend/.env (600)."""
    key_file = _key_file()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
        os.chmod(key_file, 0o600)
    ciphertext = Fernet(key_file.read_bytes()).encrypt(value.encode("utf-8")).decode("ascii")
    env_path = PROJECT_ROOT / "backend" / ".env"
    lines = [
        line
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith((f"{name}=", f"{name}_ENC="))
    ]
    lines.append(f"{name}_ENC={ciphertext}")
    tmp = env_path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
