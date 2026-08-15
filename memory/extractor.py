from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


MemoryScope = Literal["user", "project"]
MemoryCategory = Literal[
    "preference",
    "feedback",
    "constraint",
    "reference",
]
MAX_CANDIDATES = 3
_SENSITIVE_PATTERN = re.compile(
    r"(?:[A-Z0-9_]*API[_-]?KEY|[A-Z0-9_]*ACCESS[_-]?TOKEN|"
    r"[A-Z0-9_]*SECRET|[A-Z0-9_]*PASSWORD)\s*[:=]",
    re.IGNORECASE,
)


class MemoryCandidate(BaseModel):
    """经过校验、可安全写入长期记忆的一条候选信息。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope: MemoryScope
    category: MemoryCategory
    title: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    content: str = Field(min_length=1, max_length=4_000)


def parse_candidates(
    text: str,
    max_candidates: int = MAX_CANDIDATES,
) -> list[MemoryCandidate]:
    """解析模型 JSON 输出，并丢弃无效或疑似敏感的候选记忆。"""

    if max_candidates <= 0:
        return []

    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    candidates: list[MemoryCandidate] = []
    for item in payload:
        try:
            candidate = MemoryCandidate.model_validate(item)
        except ValidationError:
            continue

        if _SENSITIVE_PATTERN.search(candidate.content):
            continue

        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break

    return candidates
