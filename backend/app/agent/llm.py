"""Client LLM unique de Kwes : Google Gemini (texte, outils, planification).

Il n'y a plus de second fournisseur de raisonnement. Ce module contient :
- les types partagés (`LLMError`, `LLMResult`, `LLMClient`) ;
- `GeminiTextClient`, qui parle à l'API Gemini via le SDK officiel ;
- un mode hors ligne déterministe quand aucune clé n'est configurée (tests,
  poste de développement) : il ne simule jamais une exécution d'outil, il produit
  seulement un texte et un plan reproductibles, explicitement marqués.

Les outils sont déclarés au modèle par le registre (schémas JSON), et les appels
sont normalisés au format interne `{id, name, arguments}` — le Policy Engine
reste seul juge de leur exécution.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, Sequence

from google import genai
from google.genai import types

from app.core.config import Settings

logger = logging.getLogger("kwes.llm")

MOCK_MARKER = "[MODE HORS LIGNE] Réponse déterministe — aucune clé Gemini configurée."

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
        if not text.startswith("{"):
            # Certains modèles ajoutent une phrase avant le JSON : on isole l'objet.
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                text = text[start : end + 1]
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
        schema: dict[str, Any] | None = None,
    ) -> LLMResult: ...


def chunk_for_stream(text: str, *, size: int = 18) -> list[str]:
    """Découpe un texte en morceaux de taille bornée, sans couper les mots."""
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
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _system_text(messages: Sequence[dict[str, Any]]) -> str:
    return "\n\n".join(
        str(m.get("content") or "") for m in messages if m.get("role") == "system"
    ).strip()


def _tool_declarations(tools: Sequence[dict[str, Any]] | None) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
    for item in tools or []:
        function = item.get("function") or item
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        declarations.append(
            types.FunctionDeclaration(
                name=name,
                description=str(function.get("description") or "")[:400],
                parameters_json_schema=function.get("parameters") or {"type": "object"},
            )
        )
    return declarations


def _to_contents(messages: Sequence[dict[str, Any]]) -> list[types.Content]:
    """Convertit l'historique interne (OpenAI-like) en `contents` Gemini."""
    contents: list[types.Content] = []
    names_by_id: dict[str, str] = {}
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            name = names_by_id.get(call_id) or str(message.get("name") or "outil")
            payload = str(message.get("content") or "")
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=name, response={"result": payload[:6000]}
                            )
                        )
                    ],
                )
            )
            continue
        if role == "assistant":
            parts: list[types.Part] = []
            text = str(message.get("content") or "")
            if text:
                parts.append(types.Part(text=text))
            for call in message.get("tool_calls") or []:
                # Deux formes circulent : OpenAI (`function.name`) et la forme
                # normalisée interne (`name`). Les deux doivent être acceptées,
                # sinon Gemini reçoit un FunctionCall sans nom et renvoie 400.
                function = call.get("function") or call
                call_id = str(call.get("id") or "")
                name = str(function.get("name") or "")
                if name:
                    names_by_id[call_id] = name
                raw_args = function.get("arguments") or call.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}
                signature = call.get("thought_signature") or function.get("thought_signature")
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=name, args=args),
                        **({"thought_signature": signature} if signature else {}),
                    )
                )
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue
        contents.append(
            types.Content(role="user", parts=[types.Part(text=str(message.get("content") or ""))])
        )
    return contents


class GeminiTextClient:
    """Raisonnement, planification et appels d'outils via Gemini."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        # Modèles en échec récent : on les laisse se reposer 2 minutes au lieu de
        # repayer 9 s de délai à chaque message.
        self._cooldown: dict[str, float] = {}
        if settings.llm_is_mock:
            logger.warning(
                "Aucune clé Gemini : mode hors ligne déterministe (aucun appel réseau, "
                "réponses marquées X-Kwes-Mock: 1)."
            )

    # ------------------------------------------------------------------
    @property
    def mock(self) -> bool:
        return self.settings.llm_is_mock

    @property
    def models(self) -> list[str]:
        """Chaîne de modèles : le principal, puis les replis documentés."""
        chain = [self.settings.gemini_text_model]
        for item in self.settings.gemini_text_fallbacks.split(","):
            name = item.strip()
            if name and name not in chain:
                chain.append(name)
        return chain

    def _available(self) -> list[str]:
        now = time.monotonic()
        ready = [m for m in self.models if self._cooldown.get(m, 0.0) <= now]
        return ready or [self.models[-1]]

    def _cool(self, model: str) -> None:
        self._cooldown[model] = time.monotonic() + 120.0

    def _sdk(self) -> Any:
        if self._client is None:
            key = self.settings.gemini_api_key
            if not key:
                raise LLMError("Fournisseur LLM non configuré correctement.")
            self._client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
        return self._client

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
        if self.mock:
            return self._mock(messages, json_mode=json_mode, purpose=purpose, tools=tools)

        declarations = _tool_declarations(tools)
        # Un seul appel par message. La profondeur de réflexion dépend de l'usage :
        # échange simple = LOW (latence), mission complexe = HIGH (raisonnement).
        thinking = (
            types.ThinkingLevel.HIGH if purpose in {"plan", "mission"} else types.ThinkingLevel.LOW
        )

        def _config(model: str) -> types.GenerateContentConfig:
            # Les variantes « lite » ne gèrent pas la réflexion : la config est omise.
            supports_thinking = model.startswith("gemini-3.") and "lite" not in model
            return types.GenerateContentConfig(
                system_instruction=_system_text(messages) or None,
                temperature=self.settings.gemini_temperature if temperature is None else temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if json_mode else None,
                response_json_schema=schema if json_mode else None,
                tools=[types.Tool(function_declarations=declarations)] if declarations else None,
                thinking_config=types.ThinkingConfig(thinking_level=thinking)
                if supports_thinking
                else None,
            )
        deadline = asyncio.get_running_loop().time() + self.settings.gemini_total_timeout_seconds
        contents = _to_contents(messages)
        last_error: LLMError | None = None
        for model in self._available():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 1:
                break
            try:
                response = await asyncio.wait_for(
                    self._sdk().aio.models.generate_content(
                        model=model, contents=contents, config=_config(model)
                    ),
                    timeout=min(timeout or self.settings.gemini_timeout_seconds, remaining),
                )
            except asyncio.TimeoutError:
                last_error = LLMTimeout()
                self._cool(model)
                logger.warning("Gemini %s : délai dépassé, repli suivant", model)
                continue
            except Exception as exc:  # noqa: BLE001 — erreurs SDK variées
                message = str(exc)
                retryable = any(code in message for code in ("429", "500", "503", "UNAVAILABLE"))
                last_error = LLMError("Fournisseur LLM indisponible.", retryable=retryable)
                logger.warning("Gemini %s : %s", model, type(exc).__name__)
                if not retryable:
                    raise last_error from exc
                self._cool(model)
                continue
            result = self._parse(response)
            if model != self.settings.gemini_text_model:
                logger.info("Réponse produite par le modèle de repli %s", model)
            return result

        raise last_error or LLMError("Fournisseur LLM indisponible.", retryable=True)

    async def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int = 1200,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        if self.mock:
            result = self._mock(messages, json_mode=False, purpose="chat", tools=None)
            for chunk in chunk_for_stream(result.content):
                yield chunk
                await asyncio.sleep(0)
            return

        config = types.GenerateContentConfig(
            system_instruction=_system_text(messages) or None,
            temperature=self.settings.gemini_temperature if temperature is None else temperature,
            max_output_tokens=max_tokens,
        )
        contents = _to_contents(messages)
        last_error: LLMError | None = None
        for model in self._available():
            emitted = False
            try:
                stream = await asyncio.wait_for(
                    self._sdk().aio.models.generate_content_stream(
                        model=model, contents=contents, config=config
                    ),
                    timeout=timeout or self.settings.gemini_timeout_seconds,
                )
                async for chunk in stream:
                    text = getattr(chunk, "text", None)
                    if text:
                        emitted = True
                        yield text
                return
            except asyncio.TimeoutError as exc:
                last_error = LLMTimeout()
                if emitted:
                    raise last_error from exc
                self._cool(model)
                logger.warning("Gemini %s (flux) : délai dépassé, repli suivant", model)
                continue
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                retryable = any(code in message for code in ("429", "500", "503", "UNAVAILABLE"))
                last_error = LLMError("Flux LLM interrompu.", retryable=retryable)
                logger.warning("Gemini %s (flux) : %s", model, type(exc).__name__)
                if emitted or not retryable:
                    raise last_error from exc
                self._cool(model)
                continue
        raise last_error or LLMError("Flux LLM interrompu.", retryable=True)

    # ------------------------------------------------------------------
    def _parse(self, response: Any) -> LLMResult:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None):
                    text_parts.append(str(part.text))
                call = getattr(part, "function_call", None)
                if call is not None and getattr(call, "name", None):
                    tool_calls.append(
                        {
                            "id": f"call_{len(tool_calls)}",
                            "name": str(call.name),
                            "arguments": dict(getattr(call, "args", None) or {}),
                            # Gemini 3.x exige de rejouer la signature de pensée avec
                            # l'appel, sinon la requête suivante est refusée en 400.
                            "thought_signature": getattr(part, "thought_signature", None),
                        }
                    )
        usage_meta = getattr(response, "usage_metadata", None)
        usage = {
            "prompt_tokens": int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            "completion_tokens": int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            "total_tokens": int(getattr(usage_meta, "total_token_count", 0) or 0),
        }
        return LLMResult(
            content="".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            model=str(getattr(response, "model_version", None) or self.settings.gemini_text_model),
            mock=False,
        )

    # -- MODE HORS LIGNE -------------------------------------------------
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
            model=f"{self.settings.gemini_text_model}-hors-ligne",
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
        prompt = (
            "Classe la demande en un seul mot : mission (plusieurs étapes ou un livrable), "
            "outil (un seul outil suffit) ou direct (réponse immédiate).\n"
            f"Demande : {message[:500]}"
        )
        try:
            result = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                json_mode=True,
                purpose="classify",
                max_tokens=60,
            )
            intent = str(result.json().get("intent") or "").strip().lower()
            if intent in {"mission", "outil", "direct"}:
                return intent
        except LLMError:
            pass
        return _classify(message)
