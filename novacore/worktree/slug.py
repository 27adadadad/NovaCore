from __future__ import annotations

import re
import secrets


MAX_SLUG_LENGTH = 64
_SEGMENT_RE = re.compile(
    r"^[a-zA-Z0-9._-]+$",
)


def validate_slug(
    name: str,
) -> str | None:
    """校验名称能否安全用于 Worktree 路径和分支。"""

    if not name:
        return "name cannot be empty"

    if len(name) > MAX_SLUG_LENGTH:
        return (
            "name too long "
            f"(max {MAX_SLUG_LENGTH} characters)"
        )

    for segment in name.split("/"):
        if not segment:
            return "name contains an empty segment"

        if segment in {".", ".."}:
            return (
                "name cannot contain "
                "'.' or '..' segments"
            )

        if not _SEGMENT_RE.fullmatch(
            segment,
        ):
            return (
                "invalid name segment: "
                f"{segment!r}"
            )

    return None


def flatten_slug(
    name: str,
) -> str:
    """把分段名称转换为单层目录名称。"""

    return name.replace("/", "+")


def generate_worktree_name(
    agent_type: str,
) -> str:
    """根据 Agent 类型生成不易冲突的临时名称。"""

    name = (
        f"{agent_type}-"
        f"{secrets.token_hex(4)}"
    )

    error = validate_slug(name)

    if error is not None:
        raise ValueError(error)

    return name
