"""Sérialisation des ressources (formes stables pour le frontend)."""

from __future__ import annotations

from typing import Any

from app.core.utils import iso_utc
from app.db.models import (
    Approval,
    Conversation,
    Document,
    Message,
    Memory,
    Notification,
    Skill,
    Task,
    TaskStep,
)

META_KEY = "_meta"


def strip_meta(input_json: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(input_json or {})
    payload.pop(META_KEY, None)
    return payload


def conversation_dict(row: Conversation, *, message_count: int | None = None) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "title": row.title,
        "status": row.status,
        "language": row.language,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }
    if message_count is not None:
        data["message_count"] = message_count
    return data


def message_dict(row: Message) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "user_id": str(row.user_id),
        "role": row.role,
        "content": row.content,
        "content_type": row.content_type,
        "metadata": row.meta or {},
        "created_at": iso_utc(row.created_at),
    }


def step_dict(row: TaskStep) -> dict[str, Any]:
    meta = (row.input_json or {}).get(META_KEY) or {}
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "step_key": row.step_key,
        "title": row.title,
        "skill": meta.get("skill"),
        "status": row.status,
        "input": strip_meta(row.input_json),
        "output": row.output_json or {},
        "declared_risk": meta.get("declared_risk"),
        "depends_on": list(row.depends_on or []),
        "attempt_count": row.attempt_count,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }


def task_dict(row: Task, *, include_steps: bool = False) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "title": row.title,
        "goal": row.goal,
        "status": row.status,
        "priority": row.priority,
        "progress": row.progress,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
        "started_at": iso_utc(row.started_at),
        "completed_at": iso_utc(row.completed_at),
        "result_summary": row.result_summary,
        "error_code": row.error_code,
    }
    if include_steps:
        data["steps"] = [step_dict(s) for s in sorted(row.steps, key=lambda s: (s.created_at, s.step_key))]
    return data


def skill_dict(row: Skill) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "current_version": row.current_version,
        "enabled": row.enabled,
        "created_at": iso_utc(row.created_at),
        "versions": [
            {
                "id": str(v.id),
                "version": v.version,
                "status": v.status,
                "artifact_hash": v.artifact_hash,
                "created_at": iso_utc(v.created_at),
                "approved_at": iso_utc(v.approved_at),
            }
            for v in getattr(row, "versions", []) or []
        ],
    }


def document_dict(row: Document, *, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "title": row.title,
        "format": row.format,
        "chars": row.chars,
        "source": row.source,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }
    if include_content:
        data["content"] = row.content
    else:
        data["preview"] = " ".join((row.content or "").split())[:200]
    return data


def memory_dict(row: Memory) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "category": row.category,
        "content": row.content,
        "source_type": row.source_type,
        "source_id": str(row.source_id) if row.source_id else None,
        "confidence": row.confidence,
        "sensitivity": row.sensitivity,
        "expires_at": iso_utc(row.expires_at),
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }


def approval_dict(row: Approval) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "task_id": str(row.task_id) if row.task_id else None,
        "action_type": row.action_type,
        "payload_hash": row.payload_hash,
        "summary": row.summary,
        "status": row.status,
        "expires_at": iso_utc(row.expires_at),
        "decided_at": iso_utc(row.decided_at),
    }


def notification_dict(row: Notification) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "read_at": iso_utc(row.read_at),
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "created_at": iso_utc(row.created_at),
    }
