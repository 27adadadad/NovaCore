from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from novacore.agents.loader import AgentLoader

from novacore.conversation import (
    ConversationManager,
)
from novacore.tools import (
    ToolCategory,
    ToolResult,
)
from novacore.permissions import (
    PermissionChecker,
    PermissionMode,
)

if TYPE_CHECKING:
    from novacore.agent import Agent
    from novacore.agents.task_manager import TaskManager

from novacore.agents.tool_filter import (
    AgentToolFilterError,
    build_agent_registry,
    build_fork_registry,
)
from novacore.agents.fork import (
    ForkError,
    build_fork_prompt,
    build_forked_conversation,
)


class AgentToolParams(BaseModel):
    subagent_type: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "预定义子 Agent 类型。"
            "省略时复制当前会话并创建 fork"
        ),
    )

    prompt: str = Field(
        min_length=1,
        description=(
            "交给子 Agent 完成的具体任务"
        ),
    )

    run_in_background: bool = Field(
        default=False,
        description=(
            "是否在后台运行。"
            "后台运行时，当前 Agent 不等待子 Agent 结束"
        ),
    )

class AgentTool:
    name = "Agent"

    description = (
        "启动一个预定义的子 Agent；"
        "省略 subagent_type 时，"
        "复制当前会话并在后台启动 fork"
    )

    category: ToolCategory = "command"
    params_model = AgentToolParams

    def __init__(
        self,
        loader: AgentLoader,
        parent_agent: Agent,
        task_manager: TaskManager,
    ) -> None:
        self.loader = loader
        self.parent_agent = parent_agent
        self.task_manager = task_manager

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

    async def _execute_fork(
        self,
        prompt: str,
    ) -> ToolResult:
        parent_conversation = (
            self.parent_agent
            ._current_conversation
        )

        if parent_conversation is None:
            return ToolResult(
                output=(
                    "无法创建 fork："
                    "父 Agent 当前没有活动会话"
                ),
                is_error=True,
            )

        try:
            conversation = (
                build_forked_conversation(
                    parent_conversation
                )
            )

            fork_prompt = build_fork_prompt(
                prompt
            )

        except ForkError as exc:
            return ToolResult(
                output=f"Fork 创建失败：{exc}",
                is_error=True,
            )

        from novacore.agent import Agent

        child_registry = build_fork_registry(
            self.parent_agent.registry
        )

        child_permission_checker = (
            PermissionChecker(
                detector=(
                    self.parent_agent
                    .permission_checker
                    .detector
                ),
                sandbox=(
                    self.parent_agent
                    .permission_checker
                    .sandbox
                ),
                mode=(
                    self.parent_agent
                    .permission_checker
                    .mode
                ),
            )
        )

        child_agent = Agent(
            client=self.parent_agent.client,
            registry=child_registry,
            context_window=(
                self.parent_agent.context_window
            ),
            permission_checker=(
                child_permission_checker
            ),
            max_iterations=(
                self.parent_agent.max_iterations
            ),
            trace_manager=(
                self.parent_agent.trace_manager
            ),
            agent_type="fork",
            parent_trace=(
                self.parent_agent.current_trace
            ),
            # 父子 Agent 共享同一个 HookEngine。
            hook_engine=(
                self.parent_agent.hook_engine
            ),
        )

        task_id = self.task_manager.launch(
            agent=child_agent,
            conversation=conversation,
            prompt=fork_prompt,
            name="fork",
        )

        return ToolResult(
            output=(
                "[fork 子 Agent 已在后台启动]\n"
                f"task_id: {task_id}"
            )
        )

    async def execute(
        self,
        params: AgentToolParams,
    ) -> ToolResult:
        prompt = params.prompt.strip()

        if not prompt:
            return ToolResult(
                output="prompt 不能为空",
                is_error=True,
            )

        if params.subagent_type is None:
            return await self._execute_fork(
                prompt
            )

        subagent_type = (
            params.subagent_type.strip()
        )

        if not subagent_type:
            return ToolResult(
                output=(
                    "subagent_type "
                    "不能是空字符串"
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

        run_in_background = (
            params.run_in_background
            or definition.background
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

        child_permission_checker = (
            PermissionChecker(
                detector=(
                    self.parent_agent
                    .permission_checker
                    .detector
                ),
                sandbox=(
                    self.parent_agent
                    .permission_checker
                    .sandbox
                ),
                mode=PermissionMode(
                    definition.permission_mode
                ),
            )
        )

        child_agent = Agent(
            client=self.parent_agent.client,
            registry=child_registry,
            context_window=(
                self.parent_agent.context_window
            ),
            permission_checker=(
                child_permission_checker
            ),
            max_iterations=definition.max_turns,
            trace_manager=(
                self.parent_agent.trace_manager
            ),
            agent_type=definition.agent_type,
            parent_trace=(
                self.parent_agent.current_trace
            ),
            # 父子 Agent 共享同一个 HookEngine。
            hook_engine=(
                self.parent_agent.hook_engine
            ),
        )

        conversation = ConversationManager()

        conversation.add_system_message(
            definition.system_prompt
        )

        if run_in_background:
            task_id = self.task_manager.launch(
                agent=child_agent,
                conversation=conversation,
                prompt=prompt,
                name=definition.agent_type,
            )

            return ToolResult(
                output=(
                    f"[{definition.agent_type} "
                    f"子 Agent 已在后台启动]\n"
                    f"task_id: {task_id}"
                )
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
