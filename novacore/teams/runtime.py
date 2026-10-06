from __future__ import annotations

from dataclasses import dataclass

from novacore.agent import Agent
from novacore.agents import (
    AgentLoader,
    AgentToolFilterError,
    build_agent_registry,
)
from novacore.conversation import (
    ConversationManager,
    Message,
)
from novacore.path_sandbox import PathSandbox
from novacore.permissions import (
    PermissionChecker,
    PermissionMode,
)
from novacore.session import Session
from novacore.teams.models import Teammate
from novacore.tools import create_worktree_registry


class TeammateRuntimeError(RuntimeError):
    """无法为 Teammate 构造受限运行时。"""


@dataclass(frozen=True)
class TeammateRuntime:
    """一名队友在当前进程中的不可持久化对象。"""

    agent: Agent
    conversation: ConversationManager


class TeammateRuntimeFactory:
    """根据持久 Teammate 快照重建 Agent 与 Conversation。"""

    def __init__(
        self,
        parent_agent: Agent,
        agent_loader: AgentLoader,
    ) -> None:
        self.parent_agent = parent_agent
        self.agent_loader = agent_loader

    def build(
        self,
        teammate: Teammate,
        history: list[Message] | None = None,
        session: Session | None = None,
    ) -> TeammateRuntime:
        """构造严格绑定到 Teammate Worktree 的运行时。"""

        definition = self.agent_loader.get(
            teammate.agent_type
        )
        if definition is None:
            raise TeammateRuntimeError(
                "unknown teammate agent type: "
                f"{teammate.agent_type}"
            )

        try:
            safe_registry = create_worktree_registry(
                teammate.worktree.path
            )
            registry = build_agent_registry(
                safe_registry,
                definition,
            )
        except (AgentToolFilterError, ValueError) as exc:
            raise TeammateRuntimeError(
                "could not build teammate tool registry: "
                f"{exc}"
            ) from exc

        checker = PermissionChecker(
            detector=(
                self.parent_agent
                .permission_checker
                .detector
            ),
            sandbox=PathSandbox(
                teammate.worktree.path
            ),
            mode=PermissionMode(
                definition.permission_mode
            ),
            enforce_sandbox=True,
        )
        agent = Agent(
            client=self.parent_agent.client,
            registry=registry,
            context_window=(
                self.parent_agent.context_window
            ),
            permission_checker=checker,
            max_iterations=definition.max_turns,
            trace_manager=(
                self.parent_agent.trace_manager
            ),
            agent_type=definition.agent_type,
            parent_trace=(
                self.parent_agent.current_trace
            ),
            hook_engine=self.parent_agent.hook_engine,
        )

        # SessionRecord 暂无 system 类型，系统提示在恢复时由 AgentDef 重建。
        conversation = ConversationManager()
        conversation.add_system_message(
            definition.system_prompt
        )
        conversation.add_system_message(
            "你是 Team 中的独立队友。所有文件工具都以你的 "
            "Git Worktree 为根目录；只处理 Coordinator 分配的任务。"
        )

        if history is not None:
            conversation.history.extend(history)

        if session is not None:
            conversation.on_message = session.append

        return TeammateRuntime(
            agent=agent,
            conversation=conversation,
        )
