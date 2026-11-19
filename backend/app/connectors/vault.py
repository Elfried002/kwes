"""Coffre de secrets des connecteurs : chiffrement au repos, jamais en clair.

Le matériel de clé vient du fichier de secrets du serveur (600, hors dépôt).
Chaque secret est chiffré en AES-GCM avec un nonce aléatoire ; la référence
stockée en base ne contient ni le jeton ni la clé.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(RuntimeError):
    code = "VAULT_UNAVAILABLE"


def _material(settings: Any) -> bytes:
    """Dérive 32 octets à partir du fichier de clé du serveur.

    Le fichier est désigné par `KWES_SECRETS_KEY_FILE` (même source que le
    déchiffrement des clés fournisseur) ; aucun secret n'est stocké en base.
    """
    import os

    chemin = (
        os.environ.get("KWES_SECRETS_KEY_FILE", "")
        or getattr(settings, "secrets_key_file", "")
        or ""
    )
    if not chemin:
        raise VaultError("Aucun fichier de clé configuré pour le coffre.")
    path = Path(chemin)
    if not path.exists():
        raise VaultError("Fichier de clé du coffre introuvable.")
    brut = path.read_bytes()
    if len(brut) < 16:
        raise VaultError("Fichier de clé du coffre invalide.")
    return hashlib.sha256(b"kwes-connector-vault:" + brut).digest()


def encrypt(settings: Any, payload: dict[str, Any]) -> str:
    """Chiffre un document JSON et renvoie « v1:<base64(nonce|ciphertext)> »."""
    import json

    key = _material(settings)
    nonce = os.urandom(12)
    data = json.dumps(payload, ensure_ascii=False).encode()
    chiffre = AESGCM(key).encrypt(nonce, data, b"kwes-connector")
    return "v1:" + base64.b64encode(nonce + chiffre).decode()


def decrypt(settings: Any, blob: str) -> dict[str, Any]:
    import json

    if not blob.startswith("v1:"):
        raise VaultError("Format de secret inconnu.")
    key = _material(settings)
    brut = base64.b64decode(blob[3:])
    nonce, chiffre = brut[:12], brut[12:]
    data = AESGCM(key).decrypt(nonce, chiffre, b"kwes-connector")
    return json.loads(data.decode())


def reference(tenant_id: uuid.UUID, provider_id: str, owner: uuid.UUID) -> str:
    """Référence stable et non secrète d'une connexion dans le coffre."""
    digest = hashlib.sha256(f"{tenant_id}:{provider_id}:{owner}".encode()).hexdigest()[:24]
    return f"conn:{digest}"
