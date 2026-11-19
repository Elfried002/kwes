"""Outils de connecteurs : disponible seulement si le tenant est connecté."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.connectors import tools as ct
from app.connectors.vault import encrypt, reference
from app.db.models import ConnectorSecret, ConnectorCatalog, TenantConnection


@pytest.fixture()
def vault_key(tmp_path, monkeypatch):
    key = tmp_path / "vault.key"
    key.write_bytes(b"cle-de-test-pour-le-coffre-32-octets!!")
    monkeypatch.setenv("KWES_SECRETS_KEY_FILE", str(key))
    return key


def _connecter(factory, tenant_id, user_id, provider, secret):
    with factory() as session:
        if session.get(ConnectorCatalog, provider) is None:
            session.add(
                ConnectorCatalog(
                    provider_id=provider,
                    display_name=provider,
                    category="messagerie",
                    auth_mode="bot_token",
                    status="available",
                )
            )
        session.add(
            ConnectorSecret(
                tenant_id=tenant_id,
                ref=reference(tenant_id, provider, user_id),
                provider_id=provider,
                ciphertext=encrypt(type("S", (), {})(), secret),
            )
        )
        session.add(
            TenantConnection(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                provider_id=provider,
                status="active",
                secret_ref=reference(tenant_id, provider, user_id),
            )
        )
        session.commit()


def test_aucune_connexion_aucun_outil(app, client, user_id) -> None:
    import asyncio

    outils = asyncio.get_event_loop().run_until_complete(
        ct.active_tools(app.state.db, user_id, user_id)
    ) if False else None
    # Appel asynchrone via l'API interne pour éviter deux boucles : on teste
    # directement la fonction avec une session applicative.
    async def _run():
        return await ct.active_tools(app.state.db, user_id, user_id)

    outils = asyncio.run(_run())
    assert outils == []


def test_connexion_telegram_expose_l_outil(app, client, user_id, db_session_factory, vault_key) -> None:
    import asyncio

    _connecter(
        db_session_factory, user_id, user_id, "telegram", {"token": "123:secret"}
    )

    async def _run():
        return await ct.active_tools(app.state.db, user_id, user_id)

    outils = asyncio.run(_run())
    assert outils == ["telegram.send"]
    assert ct.definitions(outils)[0]["function"]["name"] == "telegram.send"


def test_telegram_envoie_et_renvoie_un_identifiant(app, client, user_id, db_session_factory, vault_key, monkeypatch) -> None:
    import asyncio

    _connecter(db_session_factory, user_id, user_id, "telegram", {"token": "123:secret"})

    class FauxClient:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            assert json == {"chat_id": "42", "text": "Bonjour"}
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7, "chat": {"id": 42}}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(ct.httpx, "AsyncClient", FauxClient)

    ctx = type("C", (), {"db": app.state.db, "settings": app.state.settings,
                         "tenant_id": user_id, "user_id": user_id})()

    async def _run():
        return await ct.call("telegram.send", {"chat_id": "42", "text": "Bonjour"}, ctx)

    resultat = asyncio.run(_run())
    assert resultat["sent"] is True
    assert resultat["message_id"] == 7


def test_outil_refuse_sans_secret(app, client, user_id, db_session_factory, vault_key) -> None:
    import asyncio

    ctx = type("C", (), {"db": app.state.db, "settings": app.state.settings,
                         "tenant_id": user_id, "user_id": user_id})()

    async def _run():
        with pytest.raises(ct.ConnectorToolError) as info:
            await ct.call("telegram.send", {"chat_id": "1", "text": "x"}, ctx)
        return info.value.code

    assert asyncio.run(_run()) == "CONNECTOR_NOT_CONNECTED"
