from __future__ import annotations

from collections import deque

from novacore.hooks.events import HookEvent
from novacore.hooks.models import (
    HookCallback,
    HookFailure,
    HookContext,
    HookResult,
)


# 按事件管理 Hook 回调，并保存最近的回调失败记录。
class HookEngine:
    def __init__(
        self,
        max_failures: int = 100,
    ) -> None:
        # 失败记录上限必须是正数。
        if max_failures <= 0:
            raise ValueError(
                "max_failures must be greater than zero"
            )

        # 每种事件都有自己的回调列表，列表顺序就是执行顺序。
        self._callbacks: dict[
            HookEvent,
            list[HookCallback],
        ] = {
            event: []
            for event in HookEvent
        }

        # 达到上限后，deque 会自动删除最早的失败记录。
        self._failures: deque[HookFailure] = deque(
            maxlen=max_failures
        )

    # 将回调加入对应事件的列表，注册顺序就是执行顺序。
    def register(
        self,
        event: HookEvent,
        callback: HookCallback,
    ) -> None:
        self._callbacks[event].append(
            callback
        )

    # 返回失败记录的只读快照，不暴露内部 deque。
    @property
    def failures(
        self,
    ) -> tuple[HookFailure, ...]:
        return tuple(
            self._failures
        )

    # 丢弃当前保存的所有失败记录。
    def clear_failures(self) -> None:
        self._failures.clear()

    # 取出当前失败记录，并同时清空内部记录。
    def drain_failures(
        self,
    ) -> list[HookFailure]:
        failures = list(
            self._failures
        )
        self._failures.clear()
        return failures

    # 按注册顺序执行当前事件的所有 Hook 回调。
    async def emit(
        self,
        context: HookContext,
    ) -> HookResult:
        # 使用快照，避免回调执行期间注册新回调影响本轮。
        callbacks = tuple(
            self._callbacks[context.event]
        )

        for callback in callbacks:
            try:
                result = await callback(
                    context
                )

                # 类型注解不负责运行时检查，因此这里主动校验。
                if (
                    result is not None
                    and not isinstance(result, HookResult)
                ):
                    raise TypeError(
                        "Hook callback must return "
                        "HookResult or None"
                    )

                if (
                    result is not None
                    and result.decision
                    not in {"continue", "reject"}
                ):
                    raise ValueError(
                        "Unknown Hook decision: "
                        f"{result.decision!r}"
                    )

            except Exception as exc:
                # 普通 Hook 异常只保存记录，不终止 Agent。
                callback_name = getattr(
                    callback,
                    "__name__",
                    type(callback).__name__,
                )
                self._failures.append(
                    HookFailure(
                        event=context.event,
                        callback_name=callback_name,
                        agent_id=context.agent_id,
                        turn=context.turn,
                        tool_name=context.tool_name,
                        error=(
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
                continue

            # 只有工具执行前的明确拒绝才能阻止后续流程。
            if (
                context.event
                == HookEvent.PRE_TOOL_USE
                and result is not None
                and result.decision == "reject"
            ):
                return result

        # 没有拒绝，或者没有注册回调时，默认继续。
        return HookResult()