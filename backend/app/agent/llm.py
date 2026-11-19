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
from app.agent.live_reasoner import LiveReasoner

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
    """Raisonnement via l'API Live de Gemini (deux modèles autorisés).

    Aucun appel `generateContent`, aucun repli : le brief n'autorise que
    `gemini-3.8-live` et `gemini-3.8-live-extended-thinking`. Le texte visible
    provient de la transcription de sortie de la session Live, les structures
    (plan, document) des appels de fonction.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._reasoner: LiveReasoner | None = None
        if settings.llm_is_mock:
            logger.warning(
                "Aucune clé Gemini : mode hors ligne déterministe (aucun appel réseau, "
                "réponses marquées X-Kwes-Mock: 1)."
            )

    @property
    def mock(self) -> bool:
        return self.settings.llm_is_mock

    def _live(self) -> LiveReasoner:
        if self._reasoner is None:
            self._reasoner = LiveReasoner(self.settings)
        return self._reasoner

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
        try:
            text, calls, model = await self._live().generate(
                messages, purpose=purpose, tools=tools, timeout=timeout
            )
        except TimeoutError as exc:
            raise LLMTimeout() from exc
        except Exception as exc:  # noqa: BLE001 — erreurs SDK variées
            logger.warning("Gemini Live en échec (%s)", type(exc).__name__)
            raise LLMError("Fournisseur LLM indisponible.", retryable=True) from exc
        return LLMResult(content=text, tool_calls=calls, model=model, mock=False)

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
        try:
            async for chunk in self._live().stream(messages, timeout=timeout):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini Live (flux) en échec (%s)", type(exc).__name__)
            raise LLMError("Flux LLM interrompu.", retryable=True) from exc

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
            model="hors-ligne",
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
    """Oriente une demande : mission (plusieurs étapes) ou outil (une action).

    L'ancienne version classait « recherche » comme une mission : demander un prix
    créait une mission dont le plan était vide, au lieu de chercher réellement.
    Une demande d'information simple doit passer par les outils, pas par un plan.
    """
    lowered = text.lower()
    # Une mission suppose plusieurs étapes explicites, pas une simple question.
    multi_step_markers = (
        "mission", "rapport", "plan d'action", "stratégie", "strategie",
        "organise", "prépare", "prepare", "étude de marché", "etude de marche",
        "analyse approfondie", "compare plusieurs", "veille", "synthèse complète",
        "synthese complete", "business plan", "proposition commerciale",
    )
    tool_markers = (
        "cherche", "recherche", "trouve", "actualité", "actualités", "nouvelle",
        "prix", "combien", "c'est quoi", "qu'est-ce que", "qui est", "où en est",
        "note que", "retiens", "souviens", "rédige", "redige", "écris", "ecris",
        "document", "vérifie", "verifie", "météo", "meteo", "lis cette page",
        "http://", "https://", "source", "compare",
    )
    if any(marker in lowered for marker in multi_step_markers) and len(text.strip()) > 25:
        return "mission"
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
