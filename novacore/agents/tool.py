from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from novacore.agents.loader import AgentLoader
from novacore.agents.tool_filter import (
    AgentToolFilterError,
    build_agent_registry,
)
from novacore.conversation import (
    ConversationManager,
)
from novacore.tools import (
    ToolCategory,
    ToolResult,
)


if TYPE_CHECKING:
    from novacore.agent import Agent


class AgentToolParams(BaseModel):
    subagent_type: str = Field(
        min_length=1,
        description=(
            "需要启动的子 Agent 类型"
        ),
    )

    prompt: str = Field(
        min_length=1,
        description=(
            "交给子 Agent 完成的具体任务"
        ),
    )

class AgentTool:
    name = "Agent"

    description = (
        "启动一个预定义的子 Agent，"
        "让它在独立对话中完成任务，"
        "并返回最终结果"
    )

    category: ToolCategory = "command"
    params_model = AgentToolParams

    def __init__(
        self,
        loader: AgentLoader,
        parent_agent: Agent,
    ) -> None:
        self.loader = loader
        self.parent_agent = parent_agent

    def get_schema(
        self,
    ) -> dict[str, Any]:
        parameters = (
            self.params_model.model_json_schema()
        )

        parameters.pop("title", None)

        description_lines = [
            self.description,
        ]

        catalog = self.loader.list_agents()

        if catalog:
            description_lines.extend(
                [
                    "",
                    "可用子 Agent：",
                ]
            )

            for agent_type, when_to_use in catalog:
                description_lines.append(
                    (
                        f"- {agent_type}: "
                        f"{when_to_use}"
                    )
                )

        full_description = "\n".join(
            description_lines
        )

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": full_description,
                "parameters": parameters,
            },
        }

    async def execute(
        self,
        params: AgentToolParams,
    ) -> ToolResult:
        subagent_type = (
            params.subagent_type.strip()
        )
        prompt = params.prompt.strip()

        if not subagent_type or not prompt:
            return ToolResult(
                output=(
                    "subagent_type 和 prompt "
                    "不能为空"
                ),
                is_error=True,
            )

        definition = self.loader.get(
            subagent_type
        )

        if definition is None:
            available = ", ".join(
                agent_type
                for agent_type, _when_to_use
                in self.loader.list_agents()
            )

            if not available:
                available = "无可用子 Agent"

            return ToolResult(
                output=(
                    f"未知子 Agent：{subagent_type}。"
                    f"可用类型：{available}"
                ),
                is_error=True,
            )

        try:
            child_registry = (
                build_agent_registry(
                    self.parent_agent.registry,
                    definition,
                )
            )
        except AgentToolFilterError as exc:
            return ToolResult(
                output=(
                    f"子 Agent 工具配置错误："
                    f"{exc}"
                ),
                is_error=True,
            )

        from novacore.agent import Agent

        child_agent = Agent(
            client=self.parent_agent.client,
            registry=child_registry,
            context_window=(
                self.parent_agent.context_window
            ),
            permission_checker=(
                self.parent_agent.permission_checker
            ),
            max_iterations=definition.max_turns,
            trace_manager=(
                self.parent_agent.trace_manager
            ),
            agent_type=definition.agent_type,
            parent_trace=(
                self.parent_agent.current_trace
            ),
        )

        conversation = ConversationManager()

        conversation.add_system_message(
            definition.system_prompt
        )

        try:
            result = await (
                child_agent.run_to_completion(
                    prompt,
                    conversation=conversation,
                )
            )
        except Exception as exc:
            return ToolResult(
                output=(
                    f"子 Agent 执行失败：{exc}"
                ),
                is_error=True,
            )

        return ToolResult(
            output=(
                f"[{definition.agent_type} "
                f"子 Agent 结果]\n"
                f"{result}"
            )
        )