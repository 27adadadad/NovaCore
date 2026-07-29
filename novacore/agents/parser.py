from __future__ import annotations
import re
import yaml


from dataclasses import dataclass, field
from pathlib import Path

VALID_AGENT_TYPE = re.compile(
    r"^[a-z][a-z0-9-]*$"
)

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
    max_turns: int = 5
    file_path: Path | None = None

def _validate_metadata(
    metadata: dict[str, object],
) -> tuple[str, str, list[str], int]:
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

    max_turns = metadata.get(
        "maxTurns",
        5,
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
        max_turns,
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
        max_turns,
    ) = _validate_metadata(metadata)

    return AgentDef(
        agent_type=agent_type,
        when_to_use=when_to_use,
        system_prompt=system_prompt,
        tools=tools,
        max_turns=max_turns,
        file_path=path,
    )