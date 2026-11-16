"""P0.1 : l'authentification de production n'accepte que des jetons Supabase ES256.

Les tests génèrent une paire de clés locale et remplacent le JWKS par cette clé :
aucun appel réseau, aucune clé réelle utilisée.
"""

from __future__ import annotations

import base64
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import Settings
from app.core.errors import Unauthenticated
from app.core.security import create_dev_token, decode_token
from app.main import create_app

KID = "test-key-p0-1"
SUPABASE = "https://demo.supabase.co"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    numbers = key.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "kid": KID,
        "alg": "ES256",
        "use": "sig",
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
    }
    return private_pem, jwk


@pytest.fixture
def jwks(monkeypatch, keypair):
    _, jwk = keypair
    monkeypatch.setattr(
        "app.core.security._jwks_cache", lambda settings: {"keys": [jwk]}
    )
    monkeypatch.setattr("app.core.security._JWKS", {"data": {"keys": [jwk]}, "at": time.time()})
    return jwk


@pytest.fixture
def prod_settings(tmp_path) -> Settings:
    return Settings(
        app_env="production",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'kwes_auth.db'}",
        queue_backend="memory",
        worker_inline=False,
        supabase_url=SUPABASE,
        supabase_jwt_secret="",
        rate_limit_enabled=False,
        log_level="CRITICAL",
        deepseek_api_key="",
        skill_offline_mode=True,
        browser_open_web=False,
    )


def _es256(keypair, *, sub=None, aud="authenticated", iss=f"{SUPABASE}/auth/v1", exp_delta=600, kid=KID):
    private_pem, _ = keypair
    now = int(time.time())
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "email": "prod@kwes.local",
        "aud": aud,
        "iss": iss,
        "role": "authenticated",
        "iat": now,
        "exp": now + exp_delta,
    }
    return jwt.encode(payload, private_pem, algorithm="ES256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# Décodage
# ---------------------------------------------------------------------------
def test_valid_es256_is_accepted(prod_settings, keypair, jwks) -> None:
    token = _es256(keypair)
    payload = decode_token(token, prod_settings)
    assert payload["aud"] == "authenticated"
    assert payload["iss"] == f"{SUPABASE}/auth/v1"


def test_hs256_dev_token_is_rejected_in_production(prod_settings, jwks, keypair) -> None:
    dev_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 600},
        "dev-secret-change-me",
        algorithm="HS256",
    )
    with pytest.raises(Unauthenticated):
        decode_token(dev_token, prod_settings)


def test_expired_token_is_rejected(prod_settings, keypair, jwks) -> None:
    with pytest.raises(Unauthenticated):
        decode_token(_es256(keypair, exp_delta=-10), prod_settings)


def test_bad_signature_is_rejected(prod_settings, keypair, jwks) -> None:
    other = ec.generate_private_key(ec.SECP256R1())
    pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "iss": f"{SUPABASE}/auth/v1",
            "exp": int(time.time()) + 600,
        },
        pem,
        algorithm="ES256",
        headers={"kid": KID},  # même kid, mauvaise clé
    )
    with pytest.raises(Unauthenticated):
        decode_token(token, prod_settings)


def test_bad_issuer_is_rejected(prod_settings, keypair, jwks) -> None:
    with pytest.raises(Unauthenticated):
        decode_token(_es256(keypair, iss="https://evil.example.com/auth/v1"), prod_settings)


def test_bad_audience_is_rejected(prod_settings, keypair, jwks) -> None:
    with pytest.raises(Unauthenticated):
        decode_token(_es256(keypair, aud="anon"), prod_settings)


def test_unknown_kid_is_rejected(prod_settings, keypair, jwks) -> None:
    with pytest.raises(Unauthenticated):
        decode_token(_es256(keypair, kid="inconnu"), prod_settings)


def test_unsigned_token_is_rejected(prod_settings, jwks, keypair) -> None:
    import json

    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64(
        json.dumps(
            {
                "sub": str(uuid.uuid4()),
                "aud": "authenticated",
                "iss": f"{SUPABASE}/auth/v1",
                "exp": int(time.time()) + 600,
            }
        ).encode()
    )
    token = f"{header}.{body}."  # signature vide : alg « none »
    with pytest.raises(Unauthenticated):
        decode_token(token, prod_settings)


def test_missing_supabase_url_fails_closed(tmp_path, keypair, jwks) -> None:
    settings = Settings(
        app_env="production",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'x.db'}",
        supabase_url="",
        deepseek_api_key="",
    )
    with pytest.raises(Unauthenticated):
        decode_token(_es256(keypair), settings)


def test_dev_mode_still_accepts_hs256(settings: Settings) -> None:
    token = create_dev_token(uuid.uuid4(), settings=settings)
    assert decode_token(token, settings)["aud"] == "authenticated"


def test_dev_mode_rejects_other_algorithms(settings: Settings) -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 600},
        settings.jwt_secret,
        algorithm="HS512",
    )
    with pytest.raises(Unauthenticated):
        decode_token(token, settings)


def test_dev_token_creation_is_forbidden_in_production(prod_settings) -> None:
    with pytest.raises(RuntimeError):
        create_dev_token(uuid.uuid4(), settings=prod_settings)


# ---------------------------------------------------------------------------
# API : routes protégées, isolation entre utilisateurs
# ---------------------------------------------------------------------------
def test_protected_route_rejects_hs256_in_production(prod_settings, jwks, keypair) -> None:
    app = create_app(prod_settings)
    with TestClient(app) as client:
        dev_token = jwt.encode(
            {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 600},
            "dev-secret-change-me",
            algorithm="HS256",
        )
        response = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {dev_token}"})
        assert response.status_code == 401
        # Sans en-tête du tout.
        assert client.get("/api/v1/tasks").status_code == 401


def test_protected_route_accepts_valid_es256(prod_settings, jwks, keypair) -> None:
    app = create_app(prod_settings)
    with TestClient(app) as client:
        token = _es256(keypair)
        response = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text


def test_user_cannot_read_another_users_task(prod_settings, jwks, keypair) -> None:
    app = create_app(prod_settings)
    with TestClient(app) as client:
        alice = _es256(keypair)
        bob = _es256(keypair)
        created = client.post(
            "/api/v1/tasks",
            json={"goal": "Mission privée d'Alice", "steps": [
                {"skill": "remember", "title": "Mémoriser", "input": {"content": "note privée"}}
            ]},
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert client.get(
            f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {bob}"}
        ).status_code == 404
        assert client.get(
            f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {alice}"}
        ).status_code == 200
