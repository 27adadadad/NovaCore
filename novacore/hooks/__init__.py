# 暴露 Hooks 模块对外使用的公共接口。
from novacore.hooks.engine import HookEngine
from novacore.hooks.events import HookEvent
from novacore.hooks.models import (
    HookCallback,
    HookContext,
    HookDecision,
    HookFailure,
    HookResult,
)


# 明确哪些名称属于 Hooks 模块的公共 API。
__all__ = [
    "HookCallback",
    "HookContext",
    "HookDecision",
    "HookEngine",
    "HookEvent",
    "HookFailure",
    "HookResult",
]