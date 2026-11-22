"""Séquence de présentation du premier contact.

Kwes ne doit pas accueillir un nouvel utilisateur par un formulaire. La règle
produit : une phrase de présentation, **une** question à la fois, trois au
maximum, puis un résumé de ce qui a été retenu. La phase s'arrête dès qu'un fait
durable existe en mémoire et ne se rejoue jamais ensuite (état persisté dans
`user_onboarding`).

Ce module ne parle pas au modèle : il calcule un plan (`DiscoveryPlan`) que
l'orchestrateur traduit en consignes de prompt. La détection est une fonction
pure, donc testable sans base ni LLM.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory, UserOnboarding
from app.core.utils import utcnow

#: Nombre de questions de la phase de découverte (jamais une liste).
MAX_QUESTIONS = 3

#: Nombre de messages (celui de l'utilisateur inclus) au-delà duquel on ne
#: démarre plus la découverte dans une conversation : le premier contact est
#: passé, l'engager à retardement serait intrusif.
FIRST_CONTACT_MAX_MESSAGES = 4

#: Clés de sujets, dans l'ordre où ils sont posés.
TOPICS: tuple[str, ...] = ("nom", "activite", "priorite")

QUESTIONS_FR: dict[str, str] = {
    "nom": "Comment souhaitez-vous que je vous appelle ?",
    "activite": "Qu'est-ce que vous faites — votre métier ou votre activité principale ?",
    "priorite": "Qu'attendez-vous de moi en priorité ?",
}


@dataclass(frozen=True)
class DiscoveryPlan:
    """Ce que le prompt doit faire à ce tour."""

    active: bool
    step: int  # nombre de questions déjà posées (0..3)
    question_key: str | None  # sujet de la question à poser maintenant
    closing: bool  # dernier tour : résumé, plus aucune question

    def as_meta(self) -> dict[str, object]:
        return {
            "active": self.active,
            "step": self.step,
            "question": self.question_key,
            "closing": self.closing,
        }


def question_for(step: int) -> str | None:
    """Sujet de la question à poser pour une étape donnée (None si terminé)."""
    if step < 0 or step >= MAX_QUESTIONS:
        return None
    return TOPICS[step]


def is_first_contact(
    *,
    fact_count: int,
    conversation_messages: int,
    onboarding: UserOnboarding | None,
) -> bool:
    """Décide si la phase de découverte s'applique à ce tour.

    Trois conditions, dans cet ordre de priorité :

    1. une séquence a déjà été menée à son terme → jamais rejouée ;
    2. une séquence est en cours → on la reprend là où elle s'est arrêtée, même
       dans une nouvelle conversation (c'est elle qui produit les faits) ;
    3. sinon, premier contact seulement si aucun fait durable n'existe et que la
       conversation est encore courte (`<= 4` messages).
    """
    if onboarding is not None:
        if onboarding.completed_at is not None:
            return False
        return onboarding.step <= MAX_QUESTIONS
    if fact_count > 0:
        return False
    return conversation_messages <= FIRST_CONTACT_MAX_MESSAGES


def plan_for(
    *,
    fact_count: int,
    conversation_messages: int,
    onboarding: UserOnboarding | None,
) -> DiscoveryPlan:
    """Plan de découverte du tour courant."""
    active = is_first_contact(
        fact_count=fact_count,
        conversation_messages=conversation_messages,
        onboarding=onboarding,
    )
    if not active:
        return DiscoveryPlan(active=False, step=MAX_QUESTIONS, question_key=None, closing=False)
    step = onboarding.step if onboarding is not None else 0
    step = max(0, min(step, MAX_QUESTIONS))
    key = question_for(step)
    return DiscoveryPlan(active=True, step=step, question_key=key, closing=key is None)


def advance_for_answers(step: int, answered: set[str]) -> int:
    """Fait avancer l'étape au-delà des sujets déjà renseignés par l'utilisateur.

    Si la personne donne son prénom et son activité dans son premier message,
    redemander « comment vous appelez-vous ? » serait une faute de ton. On saute
    donc les questions dont la réponse vient d'être mémorisée.
    """
    current = max(0, min(step, MAX_QUESTIONS))
    while current < MAX_QUESTIONS and TOPICS[current] in answered:
        current += 1
    return current


def prompt_block(plan: DiscoveryPlan) -> str:
    """Consignes injectées dans le prompt système (français ; la langue de
    réponse reste celle de la personne, traitée ailleurs)."""
    if not plan.active:
        return ""
    lignes = [
        "\nPHASE DE DÉCOUVERTE (votre toute première conversation avec cette personne).",
        "Règles absolues : une seule question par réponse, jamais deux, jamais une liste, "
        "jamais un formulaire. Trois questions au maximum pour toute cette phase. "
        "Rebondis en une phrase sur ce que la personne vient de dire avant de poser la "
        "question suivante. Si elle te demande quelque chose de précis, réponds d'abord à "
        "sa demande, puis pose la question en une seule phrase.",
    ]
    if plan.closing:
        lignes.append(
            "Dernier tour : ne pose plus AUCUNE question. Résume en une phrase ce que tu as "
            "retenu de la conversation, uniquement à partir des faits listés plus haut. Si "
            "tu n'as retenu aucun fait solide, dis-le simplement et propose de commencer."
        )
        return "\n".join(lignes)
    question = QUESTIONS_FR.get(plan.question_key or "", "")
    lignes.append(
        f"Étape {plan.step + 1}/{MAX_QUESTIONS}. Présente-toi en une phrase courte si ce "
        f"n'est pas déjà fait, puis pose cette unique question : « {question} »"
    )
    return "\n".join(lignes)


async def load_onboarding(
    session: AsyncSession, user_id: uuid.UUID
) -> UserOnboarding | None:
    return await session.get(UserOnboarding, user_id)


async def count_user_facts(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Faits durables réellement possédés par cet utilisateur (jamais ceux
    d'un collègue du même espace)."""
    return int(
        (
            await session.execute(
                select(func.count(Memory.id)).where(Memory.user_id == user_id)
            )
        ).scalar_one()
        or 0
    )


async def ensure_onboarding(
    session: AsyncSession, user_id: uuid.UUID
) -> UserOnboarding:
    """Récupère ou crée la ligne d'état (une par utilisateur)."""
    row = await session.get(UserOnboarding, user_id)
    if row is None:
        row = UserOnboarding(user_id=user_id, step=0)
        session.add(row)
        await session.flush()
    return row


def record_question_asked(row: UserOnboarding, step: int) -> None:
    row.step = max(row.step, min(step + 1, MAX_QUESTIONS))
    row.updated_at = utcnow()


def record_closed(row: UserOnboarding) -> None:
    row.step = MAX_QUESTIONS
    row.completed_at = utcnow()
    row.updated_at = utcnow()
