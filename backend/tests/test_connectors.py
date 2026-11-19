"""Connecteurs : catalogue honnête, OAuth state à usage unique, coffre chiffré."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

CONNECTORS = Path(__file__).resolve().parents[2] / "connectors"


@pytest.fixture()
def connectors_env(monkeypatch, tmp_path):
    """Identifiants OAuth factices et fichier de clé du coffre."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-de-test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret-de-test")
    key = tmp_path / "vault.key"
    key.write_bytes(b"cle-de-test-suffisamment-longue-pour-le-coffre")
    monkeypatch.setenv("KWES_SECRETS_KEY_FILE", str(key))
    return key


def test_catalogue_expose_les_quatre_fournisseurs(client, headers) -> None:
    reponse = client.get("/api/v1/connectors", headers=headers)
    assert reponse.status_code == 200, reponse.text
    items = {item["provider_id"]: item for item in reponse.json()["items"]}

    assert set(items) == {"google", "microsoft", "telegram", "whatsapp"}
    # Sans identifiants serveur, Google n'est pas connectable — et le dit.
    assert items["google"]["status"] == "needs_configuration"
    assert items["google"]["connection"] is None
    assert items["telegram"]["capabilities"][0]["status"] == "implemented"


def test_connexion_refusee_sans_identifiants_serveur(client, headers) -> None:
    reponse = client.post("/api/v1/connectors/google/connect", headers=headers)
    assert reponse.status_code == 422, reponse.text
    assert "Identifiants serveur absents" in reponse.json()["error"]["message"]


def test_connexion_oauth_produit_une_url_pkce(client, headers, connectors_env, app, monkeypatch) -> None:
    reponse = client.post("/api/v1/connectors/google/connect", headers=headers)
    assert reponse.status_code == 200, reponse.text
    url = reponse.json()["authorize_url"]

    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url
    assert "gmail.readonly" in url


def test_callback_refuse_un_state_inconnu(client) -> None:
    reponse = client.get(
        "/api/v1/connectors/callback?code=abc&state=inexistant",
        follow_redirects=False,
    )
    assert reponse.status_code == 303
    assert "erreur=state_invalide" in reponse.headers["location"]


def test_state_ne_sert_qu_une_fois(client, headers, connectors_env) -> None:
    debut = client.post("/api/v1/connectors/google/connect", headers=headers)
    state = debut.json()["state"]

    premier = client.get(
        f"/api/v1/connectors/callback?code=faux&state={state}", follow_redirects=False
    )
    assert premier.status_code == 303
    # Le state est consommé même si l'échange échoue (anti-replay).
    second = client.get(
        f"/api/v1/connectors/callback?code=faux&state={state}", follow_redirects=False
    )
    assert "erreur=state_invalide" in second.headers["location"]


def test_jeton_manuel_stocke_chiffre(
    client, headers, app, tmp_path, monkeypatch, db_session_factory
) -> None:
    key = tmp_path / "vault.key"
    key.write_bytes(b"une-cle-de-coffre-de-test-32-octets!!")
    monkeypatch.setenv("KWES_SECRETS_KEY_FILE", str(key))

    reponse = client.post(
        "/api/v1/connectors/telegram/token",
        json={"token": "123456:jeton-bot-tres-secret", "account_label": "Bot de test"},
        headers=headers,
    )
    assert reponse.status_code == 201, reponse.text

    # Le jeton n'apparaît ni dans la réponse, ni en clair dans la base.
    assert "jeton-bot-tres-secret" not in reponse.text
    from app.db.models import ConnectorSecret
    from sqlalchemy import select

    with db_session_factory() as session:
        ligne = session.execute(select(ConnectorSecret)).scalars().first()
        assert ligne is not None
        chiffre = ligne.ciphertext
    assert "jeton-bot-tres-secret" not in chiffre
    assert chiffre.startswith("v1:")


def test_test_de_connexion_et_revocation(client, headers, app, tmp_path, monkeypatch) -> None:
    key = tmp_path / "vault.key"
    key.write_bytes(b"une-cle-de-coffre-de-test-32-octets!!")
    monkeypatch.setenv("KWES_SECRETS_KEY_FILE", str(key))

    client.post(
        "/api/v1/connectors/telegram/token",
        json={"token": "123456:jeton-bot-tres-secret"},
        headers=headers,
    )
    test = client.post("/api/v1/connectors/telegram/test", headers=headers)
    assert test.status_code == 200
    assert test.json()["ok"] is True

    suppression = client.delete("/api/v1/connectors/telegram", headers=headers)
    assert suppression.status_code == 200
    assert suppression.json()["deleted"] is True

    # Après révocation, le test ne trouve plus rien.
    apres = client.post("/api/v1/connectors/telegram/test", headers=headers)
    assert apres.status_code == 404


def test_isolation_entre_utilisateurs(client, headers, headers_other, app, tmp_path, monkeypatch) -> None:
    key = tmp_path / "vault.key"
    key.write_bytes(b"une-cle-de-coffre-de-test-32-octets!!")
    monkeypatch.setenv("KWES_SECRETS_KEY_FILE", str(key))

    client.post(
        "/api/v1/connectors/telegram/token",
        json={"token": "123456:jeton-de-ada"},
        headers=headers,
    )
    autre = client.get("/api/v1/connectors", headers=headers_other)
    telegram = next(i for i in autre.json()["items"] if i["provider_id"] == "telegram")
    assert telegram["connection"] is None
