from __future__ import annotations

from novacore.tools import ToolRegistry


class AgentToolFilterError(ValueError):
    """子 Agent 的工具配置不合法。"""


def build_agent_registry(
    parent_registry: ToolRegistry,
    allowed_tools: list[str],
) -> ToolRegistry:
    child_registry = ToolRegistry()

    for tool_name in allowed_tools:
        if tool_name == "Agent":
            raise AgentToolFilterError(
                "子 Agent 不能使用 Agent 工具"
            )

        tool = parent_registry.get(
            tool_name
        )

        if tool is None:
            raise AgentToolFilterError(
                f"未知工具：{tool_name}"
            )

        child_registry.register(tool)

    return child_registry