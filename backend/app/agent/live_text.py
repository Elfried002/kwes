"""Raisonnement de Kwes via l'API Live de Gemini — un seul fournisseur, deux modèles.

Contrainte du brief : `gemini-3.8-live` et `gemini-3.8-live-extended-thinking`
sont les deux seuls modèles autorisés. Or ces modèles n'exposent pas
`generateContent` : ils ne parlent que l'API Live (`bidiGenerateContent`).
Le texte passe donc par une session Live en modalité TEXT, sans audio.

Un appel = une session courte : ouverture, envoi du tour, lecture jusqu'à
`turn_complete`, fermeture. Aucun repli vers un autre modèle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Sequence

from google import genai
from google.genai import types

from app.core.config import Settings

logger = logging.getLogger("kwes.live_text")


def _tool_calls_of(message: Any) -> list[dict[str, Any]]:
    call = getattr(message, "tool_call", None)
    calls: list[dict[str, Any]] = []
    for item in getattr(call, "function_calls", None) or []:
        calls.append(
            {
                "id": str(getattr(item, "id", "") or f"call_{len(calls)}"),
                "name": str(getattr(item, "name", "") or ""),
                "arguments": dict(getattr(item, "args", None) or {}),
            }
        )
    return calls


def _to_turns(messages: Sequence[dict[str, Any]]) -> tuple[str, list[types.Content]]:
    """Sépare les consignes système de l'historique conversationnel."""
    system_parts: list[str] = []
    turns: list[types.Content] = []
    for message in messages:
        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "assistant":
            parts: list[types.Part] = []
            if text:
                parts.append(types.Part(text=text))
            for call in message.get("tool_calls") or []:
                function = call.get("function") or call
                name = str(function.get("name") or "")
                if not name:
                    continue
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    import json

                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=name, args=dict(arguments or {}))
                    )
                )
            if parts:
                turns.append(types.Content(role="model", parts=parts))
            continue
        if role == "tool":
            turns.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=str(message.get("name") or "outil"),
                                response={"result": text[:6000]},
                            )
                        )
                    ],
                )
            )
            continue
        turns.append(types.Content(role="user", parts=[types.Part(text=text)]))
    return "\n\n".join(system_parts).strip(), turns


def _config(system: str, tools: Sequence[dict[str, Any]] | None) -> types.LiveConnectConfig:
    declarations = []
    for item in tools or []:
        function = item.get("function") or item
        name = function.get("name")
        if not name:
            continue
        declarations.append(
            types.FunctionDeclaration(
                name=str(name),
                description=str(function.get("description") or "")[:400],
                parameters_json_schema=function.get("parameters") or {"type": "object"},
            )
        )
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=types.Content(parts=[types.Part(text=system)]) if system else None,
        tools=[types.Tool(function_declarations=declarations)] if declarations else None,
    )


class LiveTextClient:
    """Une session Live par appel, en modalité texte."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None

    @property
    def model_fast(self) -> str:
        # gemini-3.8-live refuse generate_content : modèle texte avec grounding.
        return self.settings.google_text_model

    @property
    def model_thinking(self) -> str:
        return self.settings.google_text_model

    def _sdk(self) -> Any:
        if self._client is None:
            key = self.settings.gemini_api_key
            if not key:
                raise RuntimeError("Clé Gemini absente.")
            self._client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
        return self._client

    def model_for(self, purpose: str) -> str:
        """Mission ou planification = modèle approfondi ; le reste = modèle rapide."""
        return self.model_thinking if purpose in {"plan", "mission"} else self.model_fast

    async def _generate_grounded(
        self,
        model: str,
        system: str,
        turns: Sequence[Any],
        tools: Sequence[dict[str, Any]] | None,
        limit: float,
    ) -> tuple[str, list[dict[str, Any]], str]:
        """Un seul appel, avec recherche Google et appels de fonctions."""
        from app.agent.gemini_live import build_tools  # évite un import circulaire

        declarations = build_tools(tools)
        outillage = list(declarations or [])
        outillage.append(types.Tool(google_search=types.GoogleSearch()))
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=outillage,
            temperature=self.settings.gemini_temperature,
        )
        response = await asyncio.wait_for(
            self._sdk().aio.models.generate_content(
                model=model, contents=list(turns), config=config
            ),
            timeout=limit,
        )
        calls: list[dict[str, Any]] = []
        for index, appel in enumerate(getattr(response, "function_calls", None) or []):
            calls.append(
                {
                    "id": getattr(appel, "id", None) or f"call-{index}",
                    "name": getattr(appel, "name", ""),
                    "arguments": dict(getattr(appel, "args", None) or {}),
                }
            )
        return (response.text or ""), calls, model

    async def generate(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        purpose: str = "chat",
        tools: Sequence[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, list[dict[str, Any]], str]:
        """Renvoie (texte, appels d'outils, modèle réellement utilisé)."""
        model = self.model_for(purpose)
        system, turns = _to_turns(messages)
        if not turns:
            return "", [], model
        limit = timeout or self.settings.gemini_timeout_seconds

        # Recherche native : le modèle interroge Google lui-même. La session
        # Live n'exécute pas ce grounding (vérifié en production), alors que
        # generate_content le fait réellement.
        if self.settings.native_search_enabled:
            return await self._generate_grounded(model, system, turns, tools, limit)

        async def _run() -> tuple[str, list[dict[str, Any]]]:
            async with self._sdk().aio.live.connect(
                model=model, config=_config(system, tools)
            ) as session:
                # Historique : on rejoue les tours précédents, puis le dernier.
                for turn in turns[:-1]:
                    await session.send_client_content(turns=turn, turn_complete=False)
                await session.send_client_content(turns=turns[-1], turn_complete=True)

                text_parts: list[str] = []
                calls: list[dict[str, Any]] = []
                async for message in session.receive():
                    content = getattr(message, "server_content", None)
                    if content is not None:
                        turn = getattr(content, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            if getattr(part, "text", None):
                                text_parts.append(str(part.text))
                        transcription = getattr(content, "output_transcription", None)
                        if transcription is not None and getattr(transcription, "text", None):
                            text_parts.append(str(transcription.text))
                        if getattr(content, "turn_complete", False):
                            break
                    tool_call = getattr(message, "tool_call", None)
                    if tool_call is not None:
                        calls.extend(_tool_calls_of(message))
                return "".join(text_parts).strip(), calls

        try:
            text, calls = await asyncio.wait_for(_run(), timeout=limit)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Gemini Live ({model}) n'a pas répondu en {limit:.0f} s.") from exc
        return text, calls, model

    async def stream(
        self, messages: Sequence[dict[str, Any]], *, purpose: str = "chat", timeout: float | None = None
    ) -> AsyncIterator[str]:
        model = self.model_for(purpose)
        system, turns = _to_turns(messages)
        if not turns:
            return
        async with self._sdk().aio.live.connect(model=model, config=_config(system, None)) as session:
            await session.send_client_content(turns=turns[-1], turn_complete=True)
            async for message in session.receive():
                content = getattr(message, "server_content", None)
                if content is None:
                    continue
                transcription = getattr(content, "output_transcription", None)
                text = str(getattr(transcription, "text", "") or "")
                if text:
                    yield text
                if getattr(content, "turn_complete", False):
                    return
