from __future__ import annotations
import re
import yaml

from typing import Literal
from dataclasses import dataclass, field
from pathlib import Path

VALID_AGENT_TYPE = re.compile(
    r"^[a-z][a-z0-9-]*$"
)

VALID_PERMISSION_MODES = frozenset(
    {
        "default",
        "acceptEdits",
        "bypassPermissions",
    }
)

VALID_ISOLATION_MODES = frozenset(
    {
        "",
        "worktree",
    }
)

AgentSource = Literal[
    "builtin",
    "user",
    "project",
]

class AgentParseError(Exception):
    """Agent 定义文件格式不正确。"""

@dataclass
class AgentDef:
    agent_type: str
    when_to_use: str
    system_prompt: str
    tools: list[str] = field(
        default_factory=list,
    )
    disallowed_tools: list[str] = field(
        default_factory=list,
    )

    model: str = "inherit"
    max_turns: int = 5
    permission_mode: str = "default"
    background: bool = False
    isolation: str = ""
    file_path: Path | None = None
    source: AgentSource = "project"

def _validate_metadata(
    metadata: dict[str, object],
) -> tuple[str, str, list[str], list[str], str, int, str, bool, str]:
    agent_type = metadata.get("name")

    if not isinstance(agent_type, str):
        raise AgentParseError(
            "name 必须是字符串"
        )

    agent_type = agent_type.strip()

    if not VALID_AGENT_TYPE.fullmatch(
        agent_type
    ):
        raise AgentParseError(
            "name 必须以小写字母开头，"
            "并且只能包含小写字母、数字和连字符"
        )

    when_to_use = metadata.get(
        "description"
    )

    if not isinstance(when_to_use, str):
        raise AgentParseError(
            "description 必须是字符串"
        )

    when_to_use = when_to_use.strip()

    if not when_to_use:
        raise AgentParseError(
            "description 不能为空"
        )

    raw_tools = metadata.get(
        "tools",
        [],
    )

    if not isinstance(raw_tools, list):
        raise AgentParseError(
            "tools 必须是列表"
        )

    tools: list[str] = []

    for tool_name in raw_tools:
        if (
            not isinstance(tool_name, str)
            or not tool_name.strip()
        ):
            raise AgentParseError(
                "tools 中的每一项都必须是非空字符串"
            )

        tools.append(
            tool_name.strip()
        )

    raw_disallowed_tools = metadata.get(
        "disallowedTools",
        [],
    )

    if not isinstance(
        raw_disallowed_tools,
        list,
    ):
        raise AgentParseError(
            "disallowedTools 必须是列表"
        )

    disallowed_tools: list[str] = []

    for tool_name in raw_disallowed_tools:
        if (
            not isinstance(tool_name, str)
            or not tool_name.strip()
        ):
            raise AgentParseError(
                "disallowedTools 中的每一项"
                "都必须是非空字符串"
            )

        disallowed_tools.append(
            tool_name.strip()
        )

    max_turns = metadata.get(
        "maxTurns",
        5,
    )

    raw_model = metadata.get(
        "model",
        "inherit",
    )

    if not isinstance(
        raw_model,
        str,
    ):
        raise AgentParseError(
            "model 必须是字符串"
        )

    model = raw_model.strip()

    if not model:
        raise AgentParseError(
            "model 不能为空"
        )

    raw_permission_mode = metadata.get(
        "permissionMode",
        "default",
    )

    if not isinstance(
        raw_permission_mode,
        str,
    ):
        raise AgentParseError(
            "permissionMode 必须是字符串"
        )

    permission_mode = (
        raw_permission_mode.strip()
    )

    if (
        permission_mode
        not in VALID_PERMISSION_MODES
    ):
        available = ", ".join(
            sorted(
                VALID_PERMISSION_MODES
            )
        )

        raise AgentParseError(
            (
                "permissionMode 必须是："
                f"{available}"
            )
        )

    raw_background = metadata.get(
        "background",
        False,
    )

    if not isinstance(
        raw_background,
        bool,
    ):
        raise AgentParseError(
            "background 必须是布尔值"
        )

    background = raw_background

    raw_isolation = metadata.get(
        "isolation",
        "",
    )

    if not isinstance(
        raw_isolation,
        str,
    ):
        raise AgentParseError(
            "isolation 必须是字符串"
        )

    isolation = raw_isolation.strip()

    if (
        isolation
        not in VALID_ISOLATION_MODES
    ):
        raise AgentParseError(
            (
                "isolation 必须为空字符串"
                "或 worktree"
            )
        )

    if (
        isinstance(max_turns, bool)
        or not isinstance(max_turns, int)
        or max_turns <= 0
    ):
        raise AgentParseError(
            "maxTurns 必须是正整数"
        )

    return (
        agent_type,
        when_to_use,
        tools,
        disallowed_tools,
        model,
        max_turns,
        permission_mode,
        background,
        isolation,
    )


def parse_frontmatter(
    raw: str,
) -> tuple[dict[str, object], str]:
    stripped = raw.lstrip()

    if not stripped.startswith("---"):
        raise AgentParseError(
            "Agent 文件必须以 --- 开始"
        )

    end = stripped.find("---", 3)

    if end == -1:
        raise AgentParseError(
            "没有找到 YAML 的结束标记 ---"
        )

    yaml_block = stripped[3:end]
    body = stripped[end + 3:].lstrip("\n")

    try:
        metadata = yaml.safe_load(
            yaml_block
        )
    except yaml.YAMLError as exc:
        raise AgentParseError(
            f"YAML 格式错误：{exc}"
        ) from exc

    if not isinstance(metadata, dict):
        raise AgentParseError(
            "YAML 必须是键值对结构"
        )

    return metadata, body


def parse_agent_file(
    path: Path,
    source: AgentSource = "project",
) -> AgentDef:
    try:
        raw = path.read_text(
            encoding="utf-8",
        )
    except OSError as exc:
        raise AgentParseError(
            f"无法读取 Agent 文件：{path}"
        ) from exc

    metadata, system_prompt = (
        parse_frontmatter(raw)
    )

    (
        agent_type,
        when_to_use,
        tools,
        disallowed_tools,
        model,
        max_turns,
        permission_mode,
        background,
        isolation,
    ) = _validate_metadata(metadata)

    return AgentDef(
        agent_type=agent_type,
        when_to_use=when_to_use,
        system_prompt=system_prompt,
        tools=tools,
        disallowed_tools=disallowed_tools,
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        background=background,
        isolation=isolation,
        file_path=path,
        source=source,
    )
