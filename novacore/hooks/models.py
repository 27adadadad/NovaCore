from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from novacore.hooks.events import HookEvent


HookDecision = Literal[
    "continue",
    "reject",
]


@dataclass(frozen=True)
class HookResult:
    decision: HookDecision = "continue"
    reason: str = ""

@dataclass(frozen=True)
class HookContext:
    event: HookEvent
    agent_id: str = ""
    agent_type: str = ""
    parent_id: str | None = None
    trace_id: str = ""
    turn: int = 0
    tool_id: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(
        default_factory=dict
    )
    tool_output: str = ""
    tool_is_error: bool = False

# 记录 Hook 回调执行时发生的异常，供后续排查问题。
@dataclass(frozen=True)
class HookFailure:
    # 发生异常时正在处理的 Hook 事件。
    event: HookEvent

    # 抛出异常的回调函数名称。
    callback_name: str

    # 执行该回调的 Agent。
    agent_id: str

    # 发生异常时所在的模型轮次。
    turn: int

    # 工具事件对应的工具名；非工具事件可以为空字符串。
    tool_name: str

    # 捕获到的异常信息。
    error: str

# Hook 回调接收事件上下文，并异步返回处理决定或 None。
HookCallback = Callable[
    [HookContext],
    Awaitable[HookResult | None],
]