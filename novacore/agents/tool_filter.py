from __future__ import annotations
from typing import TYPE_CHECKING

from novacore.tools import ToolRegistry

if TYPE_CHECKING:
    from novacore.agents.parser import (
        AgentDef,
    )

ALWAYS_DISALLOWED_TOOLS = frozenset(
    {
        "Agent",
    }
)


class AgentToolFilterError(ValueError):
    """子 Agent 的工具配置不合法。"""



def build_agent_registry(
    parent_registry: ToolRegistry,
    definition: AgentDef,
) -> ToolRegistry:
    all_tools = {
        tool.name: tool
        for tool in parent_registry.list_tools()
    }

    if "Agent" in definition.tools:
        raise AgentToolFilterError(
            "子 Agent 不能使用 Agent 工具"
        )

    unknown_tools = [
        tool_name
        for tool_name in definition.tools
        if tool_name not in all_tools
    ]

    if unknown_tools:
        raise AgentToolFilterError(
            (
                "未知工具："
                + ", ".join(unknown_tools)
            )
        )

    for tool_name in ALWAYS_DISALLOWED_TOOLS:
        all_tools.pop(
            tool_name,
            None,
        )

    for tool_name in (
        definition.disallowed_tools
    ):
        all_tools.pop(
            tool_name,
            None,
        )

    if definition.tools:
        allowed_tools = set(
            definition.tools
        )

        all_tools = {
            tool_name: tool
            for tool_name, tool
            in all_tools.items()
            if tool_name in allowed_tools
        }

    child_registry = ToolRegistry()

    for tool in all_tools.values():
        child_registry.register(
            tool
        )

    return child_registry
