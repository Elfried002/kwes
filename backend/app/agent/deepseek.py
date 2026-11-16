"""Adaptateur DeepSeek (API OpenAI-compatible) avec bascule MOCK explicite.

- Si DEEPSEEK_API_KEY est absente : mode MOCK déterministe (aucune invention de
  résultat d'exécution, seulement du texte/plan reproductible), log WARNING, et
  en-tête `X-Kwes-Mock: 1` ajouté par le middleware HTTP.
- Si la clé est présente : appels réels `/chat/completions`, timeout, retries
  bornés sur 429/5xx/erreurs réseau, erreurs normalisées en LLMError.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, Sequence

import httpx

from app.core.config import Settings

logger = logging.getLogger("kwes.llm")

MOCK_MARKER = "[MOCK] Réponse simulée — DEEPSEEK_API_KEY absente."

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, code: str = "PROVIDER_UNAVAILABLE") -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.code = code


class LLMTimeout(LLMError):
    def __init__(self, message: str = "Le fournisseur LLM n'a pas répondu à temps.") -> None:
        super().__init__(message, retryable=True)


@dataclass
class LLMResult:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    mock: bool = False

    def json(self) -> dict[str, Any]:
        """Parse le contenu comme objet JSON (mode json_object)."""
        text = self.content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Sortie JSON invalide du modèle.", retryable=True, code="INVALID_OUTPUT") from exc
        if not isinstance(payload, dict):
            raise LLMError("Sortie JSON non-objet.", retryable=True, code="INVALID_OUTPUT")
        return payload


class LLMClient(Protocol):
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
    ) -> LLMResult: ...


def chunk_for_stream(text: str, *, size: int = 18) -> list[str]:
    """Découpe un texte en morceaux de taille bornée, sans couper les mots.

    Utilisé pour le mode MOCK : ce n'est pas une simulation d'exécution, c'est
    le même texte déterministe servi en plusieurs événements SSE. Le mode réel
    utilise les tokens du fournisseur.
    """
    chunks: list[str] = []
    buffer = ""
    for word in text.split(" "):
        candidate = f"{buffer} {word}" if buffer else word
        if len(candidate) > size and buffer:
            chunks.append(buffer + " ")
            buffer = word
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)
    return [c for c in chunks if c]


def _last_user_message(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(list(messages)):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


class DeepSeekClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        if settings.llm_is_mock:
            logger.warning(
                "DEEPSEEK_API_KEY absente : adaptateur DeepSeek en mode MOCK déterministe "
                "(aucun appel réseau, réponses simulées marquées X-Kwes-Mock: 1)."
            )

    # ------------------------------------------------------------------
    @property
    def mock(self) -> bool:
        return self.settings.llm_is_mock

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
    ) -> LLMResult:
        if self.mock:
            return self._mock(messages, json_mode=json_mode, purpose=purpose, tools=tools)

        body: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": [dict(m) for m in messages],
            "temperature": self.settings.deepseek_temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        payload = await self._post(body, timeout=timeout)
        try:
            choice = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Réponse du fournisseur LLM illisible.") from exc

        return LLMResult(
            content=str(choice.get("content") or ""),
            tool_calls=self._normalize_tool_calls(choice.get("tool_calls") or []),
            usage=payload.get("usage") or {},
            model=str(payload.get("model") or self.settings.deepseek_model),
            mock=False,
        )

    # ------------------------------------------------------------------
    async def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int = 1200,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Diffuse la réponse du modèle token par token (SSE OpenAI-compatible).

        Mode MOCK : le texte déterministe est servi en morceaux de mots, jamais
        un contenu inventé. Toute erreur fournisseur est remontée en LLMError.
        """
        if self.mock:
            result = self._mock(messages, json_mode=False, purpose="chat", tools=None)
            for chunk in chunk_for_stream(result.content):
                yield chunk
                await asyncio.sleep(0)
            return

        body: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": [dict(m) for m in messages],
            "temperature": self.settings.deepseek_temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        request_timeout = timeout or self.settings.deepseek_timeout_seconds

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout), transport=self._transport
        ) as client:
            try:
                async with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        logger.warning("DeepSeek stream status=%s", response.status_code)
                        raise LLMError(
                            "Fournisseur LLM saturé ou indisponible.",
                            retryable=response.status_code == 429 or response.status_code >= 500,
                        )
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload_text = line[5:].strip()
                        if not payload_text or payload_text == "[DONE]":
                            if payload_text == "[DONE]":
                                break
                            continue
                        try:
                            payload = json.loads(payload_text)
                        except json.JSONDecodeError:
                            logger.warning("Flux LLM : ligne JSON ignorée.")
                            continue
                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        chunk = delta.get("content")
                        if isinstance(chunk, str) and chunk:
                            yield chunk
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                raise LLMTimeout() from exc
            except httpx.HTTPError as exc:
                raise LLMError("Connexion au fournisseur LLM impossible.", retryable=True) from exc

    # ------------------------------------------------------------------
    async def _post(self, body: dict[str, Any], *, timeout: float | None) -> dict[str, Any]:
        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request_timeout = timeout or self.settings.deepseek_timeout_seconds
        attempts = max(0, self.settings.deepseek_max_retries) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(request_timeout),
                    transport=self._transport,
                ) as client:
                    response = await client.post(url, json=body, headers=headers)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                last_error = LLMTimeout()
            except httpx.HTTPError as exc:
                last_error = LLMError("Connexion au fournisseur LLM impossible.", retryable=True)
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMError("Réponse LLM non-JSON.") from exc
                if response.status_code in (401, 403):
                    # Jamais de détail fournisseur renvoyé à l'utilisateur.
                    logger.error("DeepSeek auth failure status=%s", response.status_code)
                    raise LLMError("Fournisseur LLM non configuré correctement.")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = LLMError("Fournisseur LLM saturé ou indisponible.", retryable=True)
                    logger.warning("DeepSeek retryable status=%s attempt=%s", response.status_code, attempt + 1)
                else:
                    logger.error("DeepSeek client error status=%s", response.status_code)
                    raise LLMError("Requête refusée par le fournisseur LLM.")

            if attempt < attempts - 1:
                await asyncio.sleep(0.3 * (2**attempt))

        assert last_error is not None
        raise last_error

    @staticmethod
    def _normalize_tool_calls(raw: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in raw:
            function = item.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str):
                continue
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Tool call ignoré : arguments non-JSON pour %s", name)
                continue
            if not isinstance(arguments, dict):
                continue
            normalized.append({"id": item.get("id") or "", "name": name, "arguments": arguments})
        return normalized

    # -- MOCK ------------------------------------------------------------
    def _mock(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        json_mode: bool,
        purpose: str,
        tools: list[dict[str, Any]] | None,
    ) -> LLMResult:
        user_text = _last_user_message(messages)
        if json_mode or purpose == "plan":
            content = json.dumps(self._mock_plan(user_text), ensure_ascii=False)
        elif purpose == "classify":
            content = json.dumps({"intent": _classify(user_text), "language": "fr"}, ensure_ascii=False)
        else:
            content = self._mock_answer(user_text)
        return LLMResult(
            content=content,
            tool_calls=[],
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "mock": True},
            model=f"{self.settings.deepseek_model}-mock",
            mock=True,
        )

    @staticmethod
    def _mock_answer(user_text: str) -> str:
        snippet = user_text.strip().replace("\n", " ")[:180] or "votre demande"
        variant = _digest(user_text) % 3
        openings = (
            "J'ai bien compris votre demande.",
            "Très clair, je peux avancer sur ce point.",
            "Bien reçu, voici comment je procède.",
        )
        bodies = (
            "Je peux vous répondre directement ici, ou lancer une mission suivie "
            "étape par étape si vous voulez un livrable complet.",
            "Je vous propose soit une réponse immédiate, soit une mission avec "
            "recherche, analyse et compte rendu à la fin.",
            "Deux options : une réponse rapide maintenant, ou une mission "
            "structurée avec des étapes vérifiables.",
        )
        return (
            f"{openings[variant]} « {snippet} ».\n\n{bodies[variant]}\n\n"
            "Dites-moi « lance une mission » si vous préférez la version complète.\n\n"
            f"{MOCK_MARKER}"
        )

    @staticmethod
    def _mock_plan(user_text: str) -> dict[str, Any]:
        """Plan déterministe et plausible, dérivé de la demande (aucun aléatoire)."""
        text = user_text.strip()
        lowered = text.lower()
        goal = text[:200] or "Accompagner la demande de l'utilisateur"
        steps: list[dict[str, Any]] = []

        urls = _URL_RE.findall(text)
        publish_words = ("publie", "publier", "publication", "envoie", "envoyer", "partage", "partager")
        research_words = (
            "recherche", "veille", "étude", "etude", "marché", "marche", "concurrent",
            "concurrence", "analyse", "sources", "actualité", "actualite",
        )
        planning_words = ("plan", "stratégie", "strategie", "business", "feuille de route", "modèle économique")

        if urls:
            steps.append(
                {
                    "id": "step_1",
                    "skill": "browser_readonly",
                    "title": "Lecture de la page fournie",
                    "input": {"url": urls[0], "objective": goal},
                    "risk": "R0",
                    "depends_on": [],
                }
            )
        if any(word in lowered for word in research_words):
            steps.append(
                {
                    "id": f"step_{len(steps) + 1}",
                    "skill": "web_research",
                    "title": "Recherche de sources",
                    "input": {
                        "query": text[:300] or goal,
                        "scope": "Afrique de l'Ouest" if "afrique" in lowered else None,
                        "depth": "standard",
                    },
                    "risk": "R0",
                    "depends_on": [],
                }
            )
        if any(word in lowered for word in planning_words) or not steps or any(
            s["skill"] == "web_research" for s in steps
        ):
            previous = [s["id"] for s in steps]
            objective = (
                f"Synthétiser les sources collectées et proposer un plan d'action : {goal}"
                if any(s["skill"] == "web_research" for s in steps)
                else goal
            )
            steps.append(
                {
                    "id": f"step_{len(steps) + 1}",
                    "skill": "business_planning",
                    "title": "Synthèse et plan d'action",
                    "input": {
                        "objective": objective[:900],
                        "context": text[:500] or None,
                        "constraints": [],
                    },
                    "risk": "R1",
                    "depends_on": previous[-1:] if previous else [],
                }
            )

        if any(word in lowered for word in publish_words):
            previous = [s["id"] for s in steps]
            # Risque volontairement sous-déclaré : le policy engine escalade en R2.
            steps.append(
                {
                    "id": f"step_{len(steps) + 1}",
                    "skill": "business_planning",
                    "title": "Préparation de la publication externe",
                    "input": {
                        "objective": goal,
                        "publish_external": True,
                        "context": text[:300] or None,
                    },
                    "risk": "R1",
                    "depends_on": previous[-1:] if previous else [],
                }
            )

        for index, step in enumerate(steps, start=1):
            step["id"] = f"step_{index}"

        return {"goal": goal, "steps": steps}


def _classify(text: str) -> str:
    """Repli heuristique (LLM indisponible) : mission > outil > direct."""
    lowered = text.lower()
    mission_markers = (
        "mission", "prépare", "prepare", "recherche", "étude", "etude", "analyse",
        "plan", "stratégie", "strategie", "business", "compare", "veille",
        "publie", "envoie", "partage", "rapport", "synthèse", "synthese",
    )
    if any(marker in lowered for marker in mission_markers) and len(text.strip()) > 12:
        return "mission"
    tool_markers = (
        "cherche", "trouve", "actualité", "actualités", "nouvelle", "prix",
        "combien coûte", "note que", "retiens", "souviens", "rédige", "redige",
        "écris", "ecris", "document", "vérifie", "verifie", "météo", "meteo",
        "lis cette page", "http://", "https://",
    )
    if any(marker in lowered for marker in tool_markers):
        return "outil"
    return "direct"


class IntentClassifier:
    """Classification d'intention côté serveur (LLM en appui, jamais décideur seul)."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def classify(self, message: str) -> str:
        try:
            result = await self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Tu classes une demande en trois catégories :\n"
                            "- 'direct' : conversation, explication, avis, reformulation. "
                            "Aucune donnée à chercher, aucune action à exécuter.\n"
                            "- 'outil' : la réponse exige un outil tout de suite : recherche "
                            "web, actualité, prix, comparaison de sources, lecture d'une page "
                            "précise, mémorisation d'un fait durable sur la personne, production "
                            "d'un document (note, lettre, plan, compte rendu).\n"
                            "- 'mission' : travail multi-étapes suivi, avec livrable et "
                            "avancement (veille récurrente, analyse longue, plusieurs actions "
                            "enchaînées).\n"
                            'Réponds uniquement en JSON: {"intent":"direct|outil|mission"}.'
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                json_mode=True,
                purpose="classify",
                max_tokens=60,
                timeout=10.0,
            )
            intent = str(result.json().get("intent", "")).strip().lower()
            if intent in ("direct", "outil", "mission"):
                return intent
        except LLMError as exc:
            logger.warning("Classification LLM indisponible (%s), repli heuristique.", exc.code)
        return _classify(message)
