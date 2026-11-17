"""Planification : validation stricte, réparation et repli sûr."""

from __future__ import annotations

import pytest

from app.agent.llm import LLMResult
from app.agent.planner import (
    Plan,
    PlanStep,
    Planner,
    PlanValidationError,
    validate_plan,
)
from app.core.events import envelope


def _step(step_id: str, depends_on: list[str] | None = None, skill: str = "business_planning") -> PlanStep:
    payload = {"objective": f"Étape {step_id} de test"}
    return PlanStep(id=step_id, skill=skill, input=payload, risk="R1", depends_on=depends_on or [])


def test_validate_plan_accepts_valid_plan(app) -> None:
    plan = Plan(goal="Objectif", steps=[_step("step_1"), _step("step_2", ["step_1"])])
    validated = validate_plan(plan, app.state.registry, max_steps=6)
    assert [s.id for s in validated.plan.steps] == ["step_1", "step_2"]


def test_validate_plan_rejects_forward_dependency(app) -> None:
    plan = Plan(goal="Objectif", steps=[_step("step_1", ["step_2"]), _step("step_2")])
    with pytest.raises(PlanValidationError):
        validate_plan(plan, app.state.registry, max_steps=6)


def test_validate_plan_rejects_unknown_skill(app) -> None:
    plan = Plan(goal="Objectif", steps=[_step("step_1", skill="shell_exec")])
    with pytest.raises(PlanValidationError):
        validate_plan(plan, app.state.registry, max_steps=6)


def test_validate_plan_rejects_too_many_steps(app) -> None:
    plan = Plan(goal="Objectif", steps=[_step(f"step_{i}") for i in range(1, 8)])
    with pytest.raises(PlanValidationError):
        validate_plan(plan, app.state.registry, max_steps=6)


def test_plan_rejects_duplicate_ids() -> None:
    with pytest.raises(Exception):
        Plan(goal="Objectif", steps=[_step("step_1"), _step("step_1")])


async def test_planner_falls_back_on_invalid_json(app, settings) -> None:
    class BrokenLLM:
        async def chat(self, *args, **kwargs) -> LLMResult:
            return LLMResult(content="pas du json", mock=True)

    planner = Planner(settings, BrokenLLM(), app.state.registry)
    plan = await planner.build_plan("Objectif de repli")
    assert len(plan.steps) == 1
    assert plan.steps[0].skill == "business_planning"


async def test_planner_repairs_invalid_plan(app, settings) -> None:
    calls = {"count": 0}

    class RepairingLLM:
        async def chat(self, messages, **kwargs) -> LLMResult:
            calls["count"] += 1
            if calls["count"] == 1:
                return LLMResult(content='{"goal": "x", "steps": [{"id": "step_1", "skill": "unknown", "input": {}}]}', mock=True)
            return LLMResult(
                content=(
                    '{"goal": "x", "steps": [{"id": "step_1", "skill": "business_planning",'
                    ' "input": {"objective": "objectif corrigé"}, "risk": "R1", "depends_on": []}]}'
                ),
                mock=True,
            )

    planner = Planner(settings, RepairingLLM(), app.state.registry)
    plan = await planner.build_plan("Objectif")
    assert calls["count"] == 2
    assert plan.steps[0].skill == "business_planning"


def test_envelope_rejects_unknown_event() -> None:
    with pytest.raises(ValueError):
        envelope("task.hacked", {"x": 1})
