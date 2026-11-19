"""Raisonnement de Kwes : API Live de Gemini, **deux modèles autorisés seulement**.

Le brief n'autorise que `gemini-3.8-live` et `gemini-3.8-live-extended-thinking`.
Ces deux modèles sont audio-natifs : ils refusent `generateContent` et refusent
même une sortie texte seule (« The requested combination of response modalities
(TEXT) is not supported »). La seule voie conforme est donc une session Live en
modalité AUDIO, dont on exploite :

- la **transcription de sortie** pour le texte visible ;
- les **appels de fonction** pour tout ce qui doit être structuré (plan, document).

Aucun repli, aucun troisième modèle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Sequence

from google import genai
from google.genai import types

from app.core.config import Settings

logger = logging.getLogger("kwes.live_reasoner")


def _turns(messages: Sequence[dict[str, Any]]) -> tuple[str, list[types.Content]]:
    """Historique interne -> consignes système + tours Live.

    Les résultats d'outils sont réinjectés comme texte : une session neuve par
    appel ne peut pas recevoir de `function_response` sans le tour d'origine.
    """
    system_parts: list[str] = []
    turns: list[types.Content] = []
    for message in messages:
        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            name = str(message.get("name") or "outil")
            turns.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"[Résultat de l'outil {name}]\n{text[:6000]}")],
                )
            )
            continue
        if role == "assistant":
            notes = []
            if text:
                notes.append(text)
            for call in message.get("tool_calls") or []:
                function = call.get("function") or call
                name = str(function.get("name") or "")
                if name:
                    notes.append(f"[appel de l'outil {name}]")
            if notes:
                turns.append(types.Content(role="model", parts=[types.Part(text="\n".join(notes))]))
            continue
        turns.append(types.Content(role="user", parts=[types.Part(text=text)]))
    return "\n\n".join(system_parts).strip(), turns


def _declarations(tools: Sequence[dict[str, Any]] | None) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
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
    return declarations


class LiveReasoner:
    """Une session Live audio par appel ; on ne garde que le texte et les appels."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None

    @property
    def model_fast(self) -> str:
        return self.settings.google_live_model

    @property
    def model_thinking(self) -> str:
        return self.settings.google_live_thinking_model

    def model_for(self, purpose: str, *, has_tools: bool = False) -> str:
        """Choix du modèle, limité aux capacités réellement mesurées.

        Vérifié le 18/11 : `gemini-3.8-live-extended-thinking` n'émet aucun appel
        d'outil en session Live (0,8 s, zéro `function_call`, quel que soit le
        niveau de réflexion). Dès qu'un outil est requis — plan, recherche,
        document — le modèle rapide est donc obligatoire ; le modèle approfondi
        reste utilisé pour le raisonnement sans outil.
        """
        if has_tools:
            return self.model_fast
        return self.model_thinking if purpose in {"plan", "mission"} else self.model_fast

    def _sdk(self) -> Any:
        if self._client is None:
            key = self.settings.gemini_api_key
            if not key:
                raise RuntimeError("Clé Gemini absente.")
            # Sans délai explicite, la bibliothèque coupe la poignée de main à
            # 10 s : le fournisseur peut légitimement en mettre 25, et l'utilisateur
            # recevait alors « service indisponible » au lieu d'une réponse.
            self._client = genai.Client(
                api_key=key,
                http_options={
                    "api_version": "v1beta",
                    "timeout": int(self.settings.gemini_timeout_seconds * 1000),
                },
            )
        return self._client

    def _config(
        self,
        system: str,
        tools: Sequence[dict[str, Any]] | None,
        *,
        thinking: bool,
        speech: bool = True,
        force_tool: str | None = None,
    ) -> types.LiveConnectConfig:
        declarations = _declarations(tools)
        options: dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "system_instruction": types.Content(parts=[types.Part(text=system)]) if system else None,
            "output_audio_transcription": types.AudioTranscriptionConfig(),
            "tools": [types.Tool(function_declarations=declarations)] if declarations else None,
        }
        if speech:
            options["speech_config"] = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.settings.google_voice
                    )
                )
            )
        if thinking:
            options["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel[self.settings.google_thinking_level]
            )
        return types.LiveConnectConfig(**options)

    async def generate(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        purpose: str = "chat",
        tools: Sequence[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, list[dict[str, Any]], str]:
        """Renvoie (texte, appels d'outils, modèle utilisé)."""
        model = self.model_for(purpose, has_tools=bool(tools))
        system, turns = _turns(messages)
        if not turns:
            return "", [], model
        limit = timeout or self.settings.gemini_timeout_seconds
        # La réflexion n'est envoyée qu'au modèle qui la supporte.
        thinking = purpose in {"plan", "mission"} and model == self.model_thinking
        force_tool = "propose_plan" if purpose == "plan" and tools else None

        async def _read(session: Any, parts: list[str], calls: list[dict[str, Any]]) -> None:
            """Lit un tour : transcription + appels d'outils, jusqu'à turn_complete."""
            async for message in session.receive():
                tool_call = getattr(message, "tool_call", None)
                if tool_call is not None:
                    for item in getattr(tool_call, "function_calls", None) or []:
                        calls.append(
                            {
                                "id": str(getattr(item, "id", "") or f"call_{len(calls)}"),
                                "name": str(getattr(item, "name", "") or ""),
                                "arguments": dict(getattr(item, "args", None) or {}),
                            }
                        )
                content = getattr(message, "server_content", None)
                if content is None:
                    continue
                transcription = getattr(content, "output_transcription", None)
                chunk = str(getattr(transcription, "text", "") or "") if transcription else ""
                if chunk:
                    parts.append(chunk)
                if getattr(content, "turn_complete", False):
                    break

        async def _run() -> tuple[str, list[dict[str, Any]]]:
            async with self._sdk().aio.live.connect(
                model=model, config=self._config(system, tools, thinking=thinking)
            ) as session:
                await session.send_client_content(turns=turns[-1], turn_complete=True)
                parts: list[str] = []
                calls: list[dict[str, Any]] = []
                await _read(session, parts, calls)
                # Le modèle approfondi répond parfois en texte au lieu d'appeler
                # l'outil : on le relance dans la même session, une seule fois.
                if force_tool and not calls:
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[
                                types.Part(
                                    text=(
                                        "Tu n'as pas appelé l'outil. Appelle maintenant "
                                        f"{force_tool} avec le plan complet, sans parler."
                                    )
                                )
                            ],
                        ),
                        turn_complete=True,
                    )
                    await _read(session, parts, calls)
                return "".join(parts).strip(), calls

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                text, calls = await asyncio.wait_for(_run(), timeout=limit)
                return text, calls, model
            except asyncio.TimeoutError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001 — réseau, poignée de main, quota
                last_error = exc
            # Un incident passager ne doit pas coûter la réponse : une seconde
            # tentative, puis on remonte l'erreur normalisée.
            await asyncio.sleep(0.5)
        if isinstance(last_error, asyncio.TimeoutError):
            raise TimeoutError(f"Gemini Live ({model}) sans réponse en {limit:.0f} s.") from last_error
        # Import local : `llm` importe ce module, un import en tête créerait un cycle.
        from app.agent.llm import LLMError

        raise LLMError(
            "Le service de réponse est momentanément indisponible.", retryable=True
        ) from last_error

    async def stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        purpose: str = "chat",
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        model = self.model_for(purpose)
        system, turns = _turns(messages)
        if not turns:
            return
        async with self._sdk().aio.live.connect(
            model=model, config=self._config(system, None, thinking=purpose in {"plan", "mission"})
        ) as session:
            await session.send_client_content(turns=turns[-1], turn_complete=True)
            async for message in session.receive():
                content = getattr(message, "server_content", None)
                if content is None:
                    continue
                transcription = getattr(content, "output_transcription", None)
                chunk = str(getattr(transcription, "text", "") or "") if transcription else ""
                if chunk:
                    yield chunk
                if getattr(content, "turn_complete", False):
                    return
