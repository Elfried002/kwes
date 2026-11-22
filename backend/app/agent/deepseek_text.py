"""Client texte DeepSeek — implémentation du `Protocol LLMClient` de Kwes.

DeepSeek expose une API compatible OpenAI (`POST /chat/completions`). Ce client
sert à un usage précis et borné : la **synthèse d'une recherche approfondie**
multi-sources (plusieurs requêtes, plusieurs pages réellement lues), là où il
faut rédiger un texte long et cité. Il ne remplace pas Gemini : le chat, la voix,
les documents et les missions restent sur le client existant. Aucun routage
automatique ne bascule d'un fournisseur à l'autre.

Règles tenues ici :

- la clé vient des settings (`deepseek_api_key`, alimenté par
  `DEEPSEEK_API_KEY`), jamais d'un littéral, jamais d'un log ;
- les jetons renvoyés par le fournisseur sont enregistrés tels quels dans
  l'instrumentation de consommation (`app.agent.usage`), sans estimation ;
- les échecs sont typés (`LLMTimeout`, `LLMError` avec un code) pour que
  l'appelant distingue une clé refusée (401/403), un solde épuisé (402), une
  limite de débit (429) d'une panne réseau — et le dise sans simuler.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Sequence

import httpx

from app.agent import usage
from app.agent.llm import LLMError, LLMResult, LLMTimeout
from app.core.config import Settings

logger = logging.getLogger("kwes.deepseek")

DEFAULT_BASE_URL = "https://api.deepseek.com"


def _normalize_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convertit l'historique interne (OpenAI-like) en messages OpenAI stricts.

    Deux formes circulent dans le backend : la normalisée interne
    (`{"id", "name", "arguments": dict}`) et la forme OpenAI sérialisée
    (`{"id", "type", "function": {"name", "arguments": str}}`). DeepSeek
    n'accepte que la seconde ; une conversion incomplète produit un 400
    « messages with role tool must be a response to a preceding message with
    tool_calls », qui ressemble à une erreur de modèle.
    """
    output: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "system":
            output.append({"role": "system", "content": str(content or "")})
            continue
        if role == "tool":
            output.append(
                {
                    "role": "tool",
                    "tool_call_id": str(message.get("tool_call_id") or ""),
                    "content": str(content or ""),
                }
            )
            continue
        if role == "assistant":
            calls = []
            for index, call in enumerate(message.get("tool_calls") or []):
                function = call.get("function") or call
                name = str(function.get("name") or "")
                if not name:
                    continue
                arguments = function.get("arguments")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments or {}, ensure_ascii=False)
                calls.append(
                    {
                        "id": str(call.get("id") or f"call_{index}"),
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
            payload: dict[str, Any] = {"role": "assistant", "content": str(content or "") or None}
            if calls:
                payload["tool_calls"] = calls
            output.append(payload)
            continue
        output.append({"role": "user", "content": str(content or "")})
    return output


def _normalize_tools(tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for item in tools or []:
        function = item.get("function") or item
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(function.get("description") or "")[:400],
                    "parameters": function.get("parameters") or {"type": "object"},
                },
            }
        )
    return definitions


def _usage_of(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("usage") or {}
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    total = raw.get("total_tokens")
    details = raw.get("completion_tokens_details") or {}
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        # Modèle de raisonnement : une part des jetons de sortie part dans le
        # raisonnement interne. Le dire évite de croire à une réponse tronquée.
        "reasoning_tokens": details.get("reasoning_tokens"),
    }


class DeepSeekTextClient:
    """Client texte DeepSeek (API compatible OpenAI), asynchrone via httpx."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    # -- disponibilité ---------------------------------------------------
    @property
    def api_key(self) -> str:
        return self.settings.deepseek_key

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def model(self) -> str:
        return self.settings.deepseek_model

    # -- HTTP ------------------------------------------------------------
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            base_url = (self.settings.deepseek_base_url or DEFAULT_BASE_URL).rstrip("/")
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(self.settings.deepseek_timeout_seconds, connect=10.0),
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    # -- LLMClient -------------------------------------------------------
    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        purpose: str = "chat",
        temperature: float | None = None,
        max_tokens: int = 1200,
        timeout: float | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        if not self.available:
            raise LLMError(
                "Aucune clé DeepSeek configurée.", retryable=False, code="PROVIDER_NOT_CONFIGURED"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _normalize_messages(messages),
            "max_tokens": max_tokens,
            "temperature": (
                self.settings.deepseek_temperature if temperature is None else temperature
            ),
            "stream": False,
        }
        definitions = _normalize_tools(tools)
        if definitions:
            payload["tools"] = definitions
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if schema and json_mode:
            # DeepSeek n'accepte pas `json_schema` : le schéma est rappelé dans
            # le prompt système par l'appelant, jamais ignoré en silence.
            logger.debug("Schéma JSON transmis en consigne, pas en response_format.")

        started = time.monotonic()
        limit = timeout or self.settings.deepseek_timeout_seconds
        try:
            response = await self._http().post(
                "/chat/completions", json=payload, timeout=limit
            )
        except httpx.TimeoutException as exc:
            logger.warning("DeepSeek : délai dépassé (%.0f s).", limit)
            raise LLMTimeout(f"DeepSeek n'a pas répondu en {limit:.0f} s.") from exc
        except httpx.HTTPError as exc:
            logger.warning("DeepSeek : erreur réseau (%s).", type(exc).__name__)
            raise LLMError(
                "Fournisseur DeepSeek injoignable.", retryable=True, code="PROVIDER_UNAVAILABLE"
            ) from exc

        if response.status_code >= 400:
            raise self._error_for(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(
                "Réponse DeepSeek illisible.", retryable=True, code="INVALID_OUTPUT"
            ) from exc

        choice = (data.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        calls: list[dict[str, Any]] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            raw_arguments = function.get("arguments")
            try:
                if isinstance(raw_arguments, str):
                    arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
                elif isinstance(raw_arguments, dict):
                    arguments = dict(raw_arguments)
                else:
                    arguments = {}
            except (ValueError, TypeError):
                arguments = {}
            calls.append(
                {
                    "id": str(call.get("id") or f"call_{index}"),
                    "name": str(function.get("name") or ""),
                    "arguments": arguments,
                }
            )

        if not content.strip() and not calls:
            # `deepseek-flash` est un modèle de raisonnement : un plafond trop
            # bas consomme tout dans `reasoning_content` et rend un contenu vide.
            # On le dit (code distinct) au lieu de faire croire à une panne.
            reasoning = str(message.get("reasoning_content") or "")
            if reasoning or choice.get("finish_reason") == "length":
                raise LLMError(
                    "DeepSeek a épuisé son budget de jetons en raisonnement avant de rédiger "
                    "(augmenter max_tokens).",
                    retryable=False,
                    code="OUTPUT_TRUNCATED",
                )
            raise LLMError("DeepSeek a renvoyé une réponse vide.", retryable=True, code="INVALID_OUTPUT")

        consommation = _usage_of(data)
        model = str(data.get("model") or self.model)
        usage.record(
            model=model,
            input_tokens=consommation.get("input_tokens"),
            output_tokens=consommation.get("output_tokens"),
            purpose=purpose,
            duration_ms=int((time.monotonic() - started) * 1000),
            provider="deepseek",
        )
        logger.info(
            "DeepSeek %s : %s -> %s jetons en %.0f ms.",
            model,
            consommation.get("input_tokens"),
            consommation.get("output_tokens"),
            (time.monotonic() - started) * 1000,
        )
        return LLMResult(
            content=content.strip(),
            tool_calls=calls,
            usage=consommation,
            model=model,
            mock=False,
        )

    # -- erreurs ---------------------------------------------------------
    @staticmethod
    def _error_for(response: httpx.Response) -> LLMError:
        status = response.status_code
        detail = ""
        try:
            body = response.json()
            detail = str((body.get("error") or {}).get("message") or "")[:200]
        except ValueError:
            detail = (response.text or "")[:200]
        suffix = f" ({detail})" if detail else ""
        if status in (401, 403):
            return LLMError(
                f"Clé DeepSeek refusée ({status}){suffix}.",
                retryable=False,
                code="PROVIDER_AUTH",
            )
        if status == 402:
            return LLMError(
                f"Solde DeepSeek insuffisant (402){suffix}.",
                retryable=False,
                code="PROVIDER_BALANCE",
            )
        if status == 429:
            return LLMError(
                "Limite de débit DeepSeek atteinte (429).", retryable=True, code="RATE_LIMITED"
            )
        if status >= 500:
            return LLMError(
                f"DeepSeek indisponible ({status}){suffix}.",
                retryable=True,
                code="PROVIDER_UNAVAILABLE",
            )
        return LLMError(
            f"Requête DeepSeek refusée ({status}){suffix}.",
            retryable=False,
            code="PROVIDER_REJECTED",
        )
