from __future__ import annotations

import asyncio

from novacore.hooks import (
    HookContext,
    HookEngine,
    HookEvent,
    HookResult,
)


# 第一个回调只观察并打印工具请求。
async def log_tool_call(
    context: HookContext,
) -> None:
    print(
        f"[hook] {context.event.value}: "
        f"{context.tool_name} "
        f"{context.tool_arguments}"
    )


# 这个回调故意失败，用来观察 HookFailure。
async def failing_audit_hook(
    context: HookContext,
) -> None:
    raise RuntimeError(
        "demo audit failure"
    )


# Bash 工具执行前返回明确拒绝。
async def block_bash(
    context: HookContext,
) -> HookResult | None:
    if context.tool_name != "Bash":
        return None

    return HookResult(
        decision="reject",
        reason="Bash is blocked by the demo Hook",
    )


# PRE 的首次拒绝会停止后续回调，因此它不应该运行。
async def should_not_run(
    context: HookContext,
) -> None:
    print("[unexpected] callback ran after reject")


async def main() -> None:
    engine = HookEngine()

    # 注册顺序就是本次 emit 的执行顺序。
    engine.register(
        HookEvent.PRE_TOOL_USE,
        log_tool_call,
    )
    engine.register(
        HookEvent.PRE_TOOL_USE,
        failing_audit_hook,
    )
    engine.register(
        HookEvent.PRE_TOOL_USE,
        block_bash,
    )
    engine.register(
        HookEvent.PRE_TOOL_USE,
        should_not_run,
    )

    # 模拟 Agent 即将调用 Bash。
    context = HookContext(
        event=HookEvent.PRE_TOOL_USE,
        agent_id="demo-agent",
        agent_type="main",
        trace_id="demo-trace",
        turn=1,
        tool_id="demo-call",
        tool_name="Bash",
        tool_arguments={
            "command": "echo hello",
        },
    )

    result = await engine.emit(
        context
    )

    print(f"decision: {result.decision}")
    print(f"reason: {result.reason}")
    print(f"failures: {len(engine.failures)}")

    # 普通回调异常被保存，但不会阻止后续 block_bash。
    for failure in engine.failures:
        print(
            f"failure: {failure.callback_name} "
            f"-> {failure.error}"
        )


if __name__ == "__main__":
    # 普通脚本入口负责创建异步事件循环。
    asyncio.run(main())