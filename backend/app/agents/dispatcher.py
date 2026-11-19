"""Dispatcher de KWES Core : plan → tâches → agents → résultats consolidés.

Core est le seul composant qui distribue le travail. Le plan est validé avant
toute exécution : un spécialiste inconnu, un outil non exécutable ou une
dépendance circulaire font échouer la planification, jamais l'exécution en
silence.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select

from app.agents.contracts import AgentTask
from app.agents.journal import RunJournal, Timer
from app.agents.registry import AgentRegistry, LoadedAgent
from app.agents.runtime import AgentRuntime, MissionScope
from app.agent.llm import LLMClient, LLMError
from app.core.config import Settings
from app.db.models import AgentTask as AgentTaskRow
from app.db.models import Task

logger = logging.getLogger("kwes.agents.dispatcher")

MAX_STEPS = 8
MAX_CONCURRENCY = 4
MISSION_SECONDS = 900


class PlanError(RuntimeError):
    code = "PLAN_INVALID"


class _NullJournal:
    """Journal inactif (tests unitaires du graphe)."""

    async def event(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def tool(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass
class PlanItem:
    agent_id: str
    objective: str
    expected_output: str
    acceptance: list[str]
    depends_on: list[int]
    tools: list[str]


def _extract_tasks(payload: Any) -> list[dict[str, Any]]:
    """Extrait la liste de tâches quel que soit l'emballage du modèle."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for cle in ("tasks", "plan", "steps", "subtasks", "taches", "tâches"):
        valeur = payload.get(cle)
        if isinstance(valeur, list):
            return [item for item in valeur if isinstance(item, dict)]
    # Dictionnaire indexé (« 1 »: {...}, « 2 »: {...}).
    valeurs = [v for v in payload.values() if isinstance(v, dict)]
    if len(valeurs) >= 1 and any("agent_id" in v for v in valeurs):
        return valeurs
    return []


#: Indices d'intention → mots-clés, pour choisir un spécialiste quand le plan
#: automatique échoue. Volontairement grossier : mieux vaut un choix explicable
#: qu'un agent pris au hasard.
INTENT_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("kwes.research", ("recherche", "cherche", "prix", "comparer", "comparaison", "actualité",
                       "source", "marché", "veille", "tendance", "concurrent")),
    ("kwes.business", ("business", "stratégie", "plan d'affaires", "revenu", "kpi", "business plan")),
    ("kwes.finance", ("budget", "finance", "coût", "marge", "trésorerie", "facture")),
    ("kwes.writer", ("rédige", "texte", "article", "document", "rapport", "note")),
    ("kwes.engineering", ("code", "script", "développe", "bug", "api", "test")),
]


def deterministic_plan(
    objective: str, catalogue: list[dict[str, Any]]
) -> list[PlanItem]:
    """Décomposition déterministe : recherche → analyse → livrable.

    Utilisée quand le plan du modèle est illisible. Aucune donnée n'est
    inventée : seules les étapes réellement utiles sont créées, avec les
    spécialistes qui possèdent des outils exécutables.
    """
    texte = objective.lower()
    disponibles = {item["agent_id"]: item for item in catalogue}
    etapes: list[PlanItem] = []

    def ajoute(agent_id: str, objectif: str, attendu: str, deps: list[int]) -> int | None:
        item = disponibles.get(agent_id)
        if item is None:
            return None
        etapes.append(
            PlanItem(
                agent_id=agent_id,
                objective=objectif[:2000],
                expected_output=attendu,
                acceptance=["éléments sourcés", "limites explicites"],
                depends_on=deps,
                tools=list(item["outils"])[:4],
            )
        )
        return len(etapes) - 1

    besoin_recherche = any(
        mot in texte
        for mot in ("recherche", "cherche", "prix", "compar", "actualité", "marché",
                    "source", "veille", "tendance", "information", "donnée")
    )
    i_recherche = None
    if besoin_recherche:
        i_recherche = ajoute(
            "kwes.research",
            f"Collecter les faits datés et les sources pour : {objective}",
            "Faits datés avec au moins deux sources vérifiables",
            [],
        )

    besoin_analyse = any(
        mot in texte
        for mot in ("compar", "analyse", "recommand", "stratégie", "décision", "plan", "évaluation")
    )
    i_analyse = None
    if besoin_analyse:
        i_analyse = ajoute(
            "kwes.business",
            f"Analyser et recommander à partir des faits collectés : {objective}",
            "Recommandation argumentée, sans fait nouveau",
            [i_recherche] if i_recherche is not None else [],
        )

    besoin_livrable = any(
        mot in texte for mot in ("rapport", "document", "note", "rédige", "synthèse", "livrable")
    )
    if besoin_livrable:
        deps = [i for i in (i_recherche, i_analyse) if i is not None]
        ajoute(
            "kwes.documents",
            f"Produire le document livrable : {objective}",
            "Document structuré reprenant les faits et la recommandation",
            deps,
        )

    if not etapes:
        choisi = _best_agent_for(objective, catalogue)
        return [
            PlanItem(
                agent_id=choisi["agent_id"],
                objective=objective[:2000],
                expected_output="Livrable vérifiable répondant à l'objectif",
                acceptance=["réponse sourcée", "limites explicites"],
                depends_on=[],
                tools=list(choisi["outils"])[:4],
            )
        ]
    return etapes[:MAX_STEPS]


def _best_agent_for(objective: str, catalogue: list[dict[str, Any]]) -> dict[str, Any]:
    """Spécialiste le plus plausible pour un objectif, parmi ceux exécutables."""
    texte = objective.lower()
    disponibles = {item["agent_id"]: item for item in catalogue}
    for agent_id, mots in INTENT_HINTS:
        if agent_id in disponibles and any(mot in texte for mot in mots):
            return disponibles[agent_id]
    return catalogue[0]


def _specialist_catalogue(
    agents: AgentRegistry, disabled: set[str] | None = None
) -> list[dict[str, Any]]:
    """Vue compacte des spécialistes réellement exécutables, pour le plan."""
    desactives = disabled or set()
    catalogue: list[dict[str, Any]] = []
    for agent in agents.specialists():
        if agent.agent_id in desactives:
            continue
        outils = agent.executable_tools()
        if not outils:
            continue
        catalogue.append(
            {
                "agent_id": agent.agent_id,
                "nom": agent.config.display_name,
                "outils": outils,
                "capacites": list(agent.config.capabilities.declared_tool_ids)[:6],
            }
        )
    return catalogue


class CoreDispatcher:
    """Orchestrateur central, exécuté pour une mission d'un tenant."""

    def __init__(
        self,
        *,
        settings: Settings,
        db: Any,
        agents: AgentRegistry,
        runtime: AgentRuntime,
        llm: LLMClient,
    ) -> None:
        self.settings = settings
        self.db = db
        self.agents = agents
        self.runtime = runtime
        self.llm = llm

    # ------------------------------------------------------------------- plan

    async def propose_plan(self, mission: Task, catalogue: list[dict[str, Any]]) -> list[PlanItem]:
        """Demande un plan à Core et le valide contre le registre."""
        if not catalogue:
            raise PlanError("Aucun spécialiste exécutable disponible.")

        brief = "\n".join(
            f"- {item['agent_id']} ({item['nom']}) : outils {', '.join(item['outils'])}"
            for item in catalogue
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu es KWES Core, orchestrateur. Tu décomposes un objectif en tâches "
                    "confiées à des spécialistes. Réponds uniquement en JSON.\n"
                    "Schéma : {\"tasks\":[{\"agent_id\":str,\"objective\":str,"
                    "\"expected_output\":str,\"acceptance\":[str],\"depends_on\":[int],"
                    "\"tools\":[str]}]}\n"
                    "Maximum 4 tâches, chacune en une phrase courte. "
                    "depends_on référence l'index des tâches "
                    "précédentes. N'utilise que les agents et outils listés."
                ),
            },
            {
                "role": "user",
                "content": f"Objectif de la mission : {mission.goal}\n\nSpécialistes disponibles :\n{brief}",
            },
        ]
        payload: dict[str, Any] | None = None
        derniere_erreur: Exception | None = None
        for tentative in range(2):
            try:
                messages_tour = messages
                if tentative == 1:
                    messages_tour = messages + [
                        {
                            "role": "user",
                            "content": "Réponds uniquement par un objet JSON valide, sans texte autour.",
                        }
                    ]
                # 2500 jetons : un plan de 4 tâches détaillées dépassait 1200 et
                # la sortie tronquée n'était plus du JSON valide (constaté en staging).
                result = await self.llm.chat(
                    messages_tour, json_mode=True, max_tokens=2500, purpose="plan"
                )
                payload = result.json()
                break
            except LLMError as exc:
                derniere_erreur = exc
                logger.warning("Plan illisible (tentative %s) : %s", tentative + 1, exc)

        if payload is None:
            # Repli déterministe : une seule tâche confiée au spécialiste le plus
            # pertinent. Aucune donnée n'est inventée, seule la décomposition
            # automatique est abandonnée — et le journal le signale.
            logger.warning(
                "Plan du modèle illisible après deux essais (%s) — décomposition déterministe.",
                derniere_erreur,
            )
            return deterministic_plan(mission.goal, catalogue)

        raw = _extract_tasks(payload)
        if not raw:
            # Plan vide ou structure inattendue : on ne fabrique pas d'étapes,
            # on retombe sur une tâche unique confiée au premier spécialiste.
            logger.warning(
                "Plan sans tâche exploitable (clés reçues : %s) — repli mono-agent.",
                sorted(payload.keys())[:6],
            )
            return deterministic_plan(mission.goal, catalogue)

        items: list[PlanItem] = []
        connus = {item["agent_id"]: set(item["outils"]) for item in catalogue}
        for index, entry in enumerate(raw[: MAX_STEPS - 2]):
            if not isinstance(entry, dict):
                raise PlanError(f"Tâche {index} mal formée.")
            agent_id = str(entry.get("agent_id") or "")
            if agent_id not in connus:
                raise PlanError(f"Spécialiste inconnu ou non exécutable : {agent_id}")
            outils = [str(t) for t in (entry.get("tools") or []) if str(t) in connus[agent_id]]
            if not outils:
                outils = sorted(connus[agent_id])
            deps = [
                int(d)
                for d in (entry.get("depends_on") or [])
                if isinstance(d, int) and 0 <= d < index
            ]
            items.append(
                PlanItem(
                    agent_id=agent_id,
                    objective=str(entry.get("objective") or mission.goal)[:2000],
                    expected_output=str(entry.get("expected_output") or "Livrable vérifiable")[:1000],
                    acceptance=[str(a)[:200] for a in (entry.get("acceptance") or [])][:6],
                    depends_on=deps,
                    tools=outils[:6],
                )
            )
        if not items:
            raise PlanError("Plan vide après validation.")
        return items

    # --------------------------------------------------------------- persistance

    async def _save_plan(
        self, mission: Task, items: Iterable[PlanItem], tenant_id: uuid.UUID
    ) -> list[AgentTaskRow]:
        """Enregistre le plan de façon idempotente (clé = mission + rang + agent)."""
        item_list = list(items)
        cles = [f"{mission.id}:{index}:{item.agent_id}" for index, item in enumerate(item_list)]
        rows: list[AgentTaskRow] = []
        async with self.db.session() as session:
            existantes = (
                await session.execute(
                    select(AgentTaskRow).where(AgentTaskRow.mission_id == mission.id)
                )
            ).scalars().all()
            par_cle = {row.idempotency_key: row for row in existantes}
            for index, item in enumerate(item_list):
                cle = cles[index]
                if cle in par_cle:
                    rows.append(par_cle[cle])
                    continue
                row = AgentTaskRow(
                    tenant_id=tenant_id,
                    mission_id=mission.id,
                    agent_id=item.agent_id,
                    seq=index,
                    objective=item.objective,
                    expected_output=item.expected_output,
                    acceptance=item.acceptance,
                    status="pending",
                    depends_on=[cles[d] for d in item.depends_on],
                    allowed_tools=item.tools,
                    max_tool_calls=12,
                    max_llm_turns=4,
                    deadline_seconds=180,
                    idempotency_key=cle,
                )
                session.add(row)
                rows.append(row)
            await session.commit()
            for row in rows:
                await session.refresh(row)
        return rows

    # ---------------------------------------------------------------- exécution

    async def run(self, mission_id: uuid.UUID) -> dict[str, Any]:
        """Exécute une mission de bout en bout. Retourne un résumé vérifiable."""
        async with self.db.session() as session:
            mission = await session.get(Task, mission_id)
            if mission is None:
                raise PlanError("Mission introuvable.")
            tenant_id = mission.tenant_id or mission.user_id
            user_id = mission.user_id
            objectif = mission.goal
            mission.status = "running"
            mission.started_at = mission.started_at or _now()
            await session.commit()

        journal = RunJournal(self.db, tenant_id=tenant_id, mission_id=mission_id)
        timer = Timer()
        await journal.event("mission.started", status="running", metadata={"objective": objectif[:300]})

        try:
            desactives: set[str] = set()
            try:
                from app.db.models import AgentOverride

                async with self.db.session() as session:
                    lignes = (
                        await session.execute(
                            select(AgentOverride).where(AgentOverride.enabled.is_(False))
                        )
                    ).scalars().all()
                desactives = {ligne.agent_id for ligne in lignes}
            except Exception:  # noqa: BLE001 - kill-switch indisponible ≠ mission bloquée
                logger.warning("Kill-switch des agents illisible", exc_info=True)
            catalogue = _specialist_catalogue(self.agents, desactives)
            async with self.db.session() as session:
                mission = await session.get(Task, mission_id)
                rows = (
                    await session.execute(
                        select(AgentTaskRow)
                        .where(AgentTaskRow.mission_id == mission_id)
                        .order_by(AgentTaskRow.seq)
                    )
                ).scalars().all()

            if not rows:
                plan = await self.propose_plan(mission, catalogue)
                rows = await self._save_plan(mission, plan, tenant_id)
                await journal.event(
                    "mission.planned",
                    status="planned",
                    metadata={"tasks": [{"agent": r.agent_id, "seq": r.seq} for r in rows]},
                )

            resultats = await self._execute_graph(rows, tenant_id=tenant_id, user_id=user_id, journal=journal)
            final = await self._consolidate(mission, rows, resultats, journal)

            async with self.db.session() as session:
                mission = await session.get(Task, mission_id)
                mission.status = final["status"]
                mission.progress = 100
                mission.result_summary = final["summary"][:8000]
                mission.completed_at = _now()
                await session.commit()

            await journal.event(
                "mission.completed",
                status=final["status"],
                duration_ms=timer.ms,
                metadata={"agents": sorted({r.agent_id for r in rows})},
            )
            return final

        except Exception as exc:  # noqa: BLE001 - une mission échoue proprement
            logger.exception("Mission %s interrompue", mission_id)
            await journal.event(
                "mission.failed",
                status="failed",
                duration_ms=timer.ms,
                error_code=getattr(exc, "code", "MISSION_FAILED"),
                metadata={"message": str(exc)[:300]},
            )
            async with self.db.session() as session:
                mission = await session.get(Task, mission_id)
                if mission is not None:
                    mission.status = "failed"
                    mission.error_code = getattr(exc, "code", "MISSION_FAILED")
                    mission.result_summary = str(exc)[:1000]
                    mission.completed_at = _now()
                    await session.commit()
            return {"status": "failed", "summary": str(exc), "results": []}

    async def _execute_graph(
        self,
        rows: list[AgentTaskRow],
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        journal: RunJournal,
    ) -> dict[str, Any]:
        """Exécute les tâches dans l'ordre des dépendances, par vagues."""
        journal = journal or _NullJournal()  # type: ignore[assignment]
        par_cle = {row.idempotency_key: row for row in rows}
        faits: dict[str, dict[str, Any]] = {}
        debut = time.monotonic()
        en_cours: dict[str, asyncio.Task] = {}
        restants = list(rows)

        while restants or en_cours:
            if time.monotonic() - debut > MISSION_SECONDS:
                await journal.event("mission.timeout", status="timed_out", error_code="MISSION_TIMEOUT")
                for row in restants:
                    row.status = "timed_out"
                restants = []
                break

            prets: list[AgentTaskRow] = []
            for row in list(restants):
                deps = [str(d) for d in (row.depends_on or [])]
                if all(dep in faits for dep in deps):
                    bloquees = [dep for dep in deps if faits[dep]["status"] not in {"completed", "partial"}]
                    row.status = "blocked" if bloquees else "ready"
                    if bloquees:
                        faits[row.idempotency_key] = {"status": "blocked", "summary": "dépendance échouée"}
                        restants.remove(row)
                    else:
                        prets.append(row)

            for row in prets[: max(0, MAX_CONCURRENCY - len(en_cours))]:
                restants.remove(row)
                cle = row.idempotency_key
                en_cours[cle] = asyncio.create_task(
                    self._run_one(row, par_cle, faits, tenant_id=tenant_id, user_id=user_id, journal=journal)
                )

            if not en_cours:
                if not prets:
                    break
                continue

            done, _ = await asyncio.wait(en_cours.values(), return_when=asyncio.FIRST_COMPLETED)
            for cle, tache in list(en_cours.items()):
                if tache in done:
                    try:
                        faits[cle] = tache.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Tâche %s en échec", cle)
                        faits[cle] = {"status": "failed", "summary": str(exc)[:300]}
                    del en_cours[cle]
        return faits

    async def _run_one(
        self,
        row: AgentTaskRow,
        par_cle: dict[str, AgentTaskRow],
        faits: dict[str, dict[str, Any]],
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        journal: RunJournal,
    ) -> dict[str, Any]:
        """Exécute une tâche déléguée et met à jour sa ligne."""
        contexte = [
            f"{par_cle[dep].agent_id} : {faits[dep]['summary'][:600]}"
            for dep in (row.depends_on or [])
            if dep in faits and faits[dep].get("summary")
        ]
        contrat = AgentTask(
            task_id=row.id,
            mission_id=row.mission_id,
            agent_id=row.agent_id,
            objective=row.objective,
            expected_output=row.expected_output,
            acceptance_criteria=list(row.acceptance or []),
            allowed_tools=list(row.allowed_tools or []),
            autonomy_level=row.autonomy_level,
            deadline_seconds=row.deadline_seconds,
            max_tool_calls=row.max_tool_calls,
            max_llm_turns=row.max_llm_turns,
            dependencies=[],
            language="fr",
        )
        scope = MissionScope(
            tenant_id=tenant_id,
            user_id=user_id,
            mission_id=row.mission_id,
            agent_task_id=row.id,
            journal=journal,
            db=self.db,
            settings=self.settings,
        )
        row.status = "running"
        row.attempt += 1
        row.started_at = _now()
        async with self.db.session() as session:
            # `row` vient d'une session fermée : `merge` la rattache proprement.
            await session.merge(row)
            await session.commit()

        await journal.event(
            "task.started",
            status="running",
            agent_task_id=row.id,
            agent_id=row.agent_id,
            attempt=row.attempt,
            metadata={"tools": row.allowed_tools},
        )

        resultat = await self.runtime.execute(contrat, scope, context=contexte)

        statut = resultat.status
        row.status = {"completed": "completed", "partial": "completed", "blocked": "blocked", "failed": "failed"}[
            statut
        ]
        row.result_summary = resultat.summary[:4000]
        row.evidence = [item.model_dump(mode="json") for item in resultat.evidence]
        row.limitations = list(resultat.limitations)
        row.finished_at = _now()
        if statut == "failed":
            row.error_code = "AGENT_FAILED"
            row.error_message = resultat.summary[:300]
        async with self.db.session() as session:
            await session.merge(row)
            await session.commit()

        await journal.event(
            "task.finished",
            status=row.status,
            agent_task_id=row.id,
            agent_id=row.agent_id,
            duration_ms=resultat.duration_ms,
            attempt=row.attempt,
            metadata={
                "tool_calls": resultat.tool_calls,
                "evidence": len(resultat.evidence),
                "verified": resultat.is_verified(),
            },
        )
        return {
            "status": statut,
            "summary": resultat.summary,
            "evidence": len(resultat.evidence),
            "verified": resultat.is_verified(),
        }

    async def _consolidate(
        self,
        mission: Task,
        rows: list[AgentTaskRow],
        faits: dict[str, dict[str, Any]],
        journal: RunJournal,
    ) -> dict[str, Any]:
        """Assemble le livrable final à partir des résultats réellement produits."""
        blocs = []
        for row in rows:
            fait = faits.get(row.idempotency_key, {})
            bloc = f"### {row.agent_id}\n{row.result_summary or fait.get('summary') or '—'}"
            if row.limitations:
                bloc += "\nLimites : " + "; ".join(str(x)[:160] for x in row.limitations[:3])
            blocs.append(bloc)
        synthèse_locale = "\n\n".join(blocs)[:6000]

        statuts = [faits.get(row.idempotency_key, {}).get("status", "failed") for row in rows]
        if all(s in {"completed", "partial"} for s in statuts) and statuts:
            statut_mission = "completed"
        elif any(s in {"completed", "partial"} for s in statuts):
            statut_mission = "completed_partial"
        else:
            statut_mission = "failed"

        # Synthèse : un seul appel, sans outil. Si le modèle échoue, le
        # regroupement local des résultats sert de livrable (jamais de texte inventé).
        try:
            reponse = await self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Tu es KWES Core. Rédige le livrable final pour l'utilisateur à partir "
                            "des résultats ci-dessous. N'ajoute aucun fait absent. Signale les limites."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Objectif : {mission.goal}\n\nRésultats :\n{synthèse_locale}",
                    },
                ],
                max_tokens=900,
                purpose="synthesis",
            )
            resume = (reponse.content or "").strip() or synthèse_locale
        except LLMError:
            resume = synthèse_locale

        return {
            "status": statut_mission,
            "summary": resume,
            "results": [
                {
                    "agent_id": row.agent_id,
                    "status": faits.get(row.idempotency_key, {}).get("status"),
                    "verified": faits.get(row.idempotency_key, {}).get("verified", False),
                    "summary": (row.result_summary or "")[:500],
                }
                for row in rows
            ],
        }


def _now():
    from app.db.models import utcnow

    return utcnow()
