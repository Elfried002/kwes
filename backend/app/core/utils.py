"""Petites utilitaires partagés : temps ISO, hash de charge utile, expurgation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|authorization|cookie|iban|card|cvv|session)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def payload_hash(task_id: str | None, action_type: str, payload: dict[str, Any] | None) -> str:
    canonical = json.dumps(
        {"task_id": str(task_id) if task_id else None, "action_type": action_type, "payload": payload or {}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact(value: Any, depth: int = 0) -> Any:
    """Expurge récursivement les clés sensibles et les motifs de secrets."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = redact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        cleaned = value
        for pattern in SECRET_VALUE_PATTERNS:
            cleaned = pattern.sub("[REDACTED]", cleaned)
        return cleaned[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def truncate(text: str | None, limit: int = 500) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
