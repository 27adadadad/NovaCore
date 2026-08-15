from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
import asyncio
from enum import Enum
from copy import deepcopy
from novacore.client import StreamEvent

from novacore.client import (
    Client,
    TextDelta,
    ToolCall,
    ToolCallComplete,
)
from novacore.conversation import (
    ConversationManager,
    ToolResultBlock,
    ToolUseBlock,
)

from novacore.tools import ToolRegistry, ToolResult
from novacore.serialization import build_chat_completion_messages

from novacore.permissions import PermissionChecker
from novacore.context import compact_conversation, CompactBoundary
from novacore.agents.trace import (
    TraceManager,
    TraceNode,
)
from novacore.hooks import (
    HookContext,
    HookEngine,
    HookEvent,
)

@dataclass 
class StreamText:
    text:str

@dataclass
class ToolUseEvent:
    tool_name:str
    tool_id:str
    arguments:dict

@dataclass
class ToolResultEvent:
    tool_id:str
    tool_name:str
    output:str
    is_error:bool

@dataclass
class TurnComplete:
    turn:int

@dataclass 
class LoopComplete:
    total_turns:int

@dataclass
class ErrorEvent:
    message:str

@dataclass
class CompactNotification:
    before_tokens: int
    message:str
    boundary:CompactBoundary | None = None

CompactCallback = Callable[
    [CompactBoundary],
    None,
]


class PermissionResponse(Enum):
    ALLOW = "allow"
    DENY = "deny"

@dataclass
class PermissionRequest:
    tool_id:str
    tool_name:str
    description:str
    reason:str
    future:asyncio.Future[PermissionResponse]

AgentEvent = (
    StreamText
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | LoopComplete
    | ErrorEvent
    | PermissionRequest
    | CompactNotification
)



@dataclass
class LLMResponse:
    text:str = "" 
    tool_calls: list[ToolCall] = field(default_factory=list)

class StreamCollector:
    def __init__(self) -> None:
        self.response = LLMResponse()

    async def consume(
        self,
        stream:AsyncIterator[StreamEvent],
    )->AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text
                yield StreamText(text=event.text)

            elif isinstance(event, ToolCallComplete):
                tool_call = event.tool_call
                self.response.tool_calls.append(tool_call)

                yield ToolUseEvent(
                    tool_name=tool_call.tool_name,
                    tool_id=tool_call.tool_id,
                    arguments=tool_call.arguments,
                )
            
                

            

class Agent:
    def __init__(
        self,
        client:Client,
        registry:ToolRegistry,
        context_window:int,
        permission_checker: PermissionChecker | None = None,
        max_iterations:int = 5,
        trace_manager: TraceManager | None = None,
        agent_type: str = "main",
        parent_trace: TraceNode | None = None,
        # 允许父 Agent 把已有的 HookEngine 传给子 Agent。
        hook_engine: HookEngine | None = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.context_window = context_window
        self.permission_checker = (
            permission_checker
            if permission_checker is not None
            else PermissionChecker()
        )
        self.max_iterations = max_iterations
        self.trace_manager = (
            trace_manager
            if trace_manager is not None
            else TraceManager()
        )
        self.agent_type = agent_type
        self.parent_trace = parent_trace
        self.current_trace: TraceNode | None = None
        self._current_conversation: ConversationManager | None = None
        # 未传入时，为当前主 Agent 创建独立的 HookEngine。
        self.hook_engine = (
            hook_engine
            if hook_engine is not None
            else HookEngine()
        )

    def _start_trace(
        self,
    ) -> TraceNode:
        parent = self.parent_trace

        node = self.trace_manager.create(
            agent_type=self.agent_type,
            parent_id=(
                parent.agent_id
                if parent is not None
                else None
            ),
            trace_id=(
                parent.trace_id
                if parent is not None
                else None
            ),
        )

        self.current_trace = node
        return node


    async def _execute_tool_noninteractive(
        self,
        tool_call:ToolCall,
    )->ToolResult:
        tool = self.registry.get(
            tool_call.tool_name
        )

        if tool is None:
            return ToolResult(
                output=(
                    f"Error: unknown tool "
                    f"'{tool_call.tool_name}'"
                ),
                is_error=True,
            )
        
        decision = self.permission_checker.check(
            tool,
            tool_call.arguments
        )

        if decision.effect == "deny":
            return ToolResult(
                output=(
                    f"Permission denied: "
                    f"{decision.reason}"
                ),
                is_error=True,
            )
        
        if decision.effect == "ask":
            return ToolResult(
                output=(
                    "Permission denied: "
                    "non-interactive mode cannot "
                    f"ask user; {decision.reason}"
                ),
                is_error=True,
            )
        
        return await self.registry.execute(
            tool_call.tool_name,
            tool_call.arguments,
        )

    # 根据当前 Trace、轮次和工具数据创建 Hook 事件上下文。
    def _build_hook_context(
        self,
        event: HookEvent,
        trace: TraceNode,
        turn: int,
        tool_call: ToolCall | None = None,
        tool_result: ToolResult | None = None,
    ) -> HookContext:
        return HookContext(
            event=event,

            # Trace 字段用于区分父 Agent、子 Agent和调用链。
            agent_id=trace.agent_id,
            agent_type=trace.agent_type,
            parent_id=trace.parent_id,
            trace_id=trace.trace_id,
            turn=turn,

            # 非工具事件没有 tool_call，因此使用空值。
            tool_id=(
                tool_call.tool_id
                if tool_call is not None
                else ""
            ),
            tool_name=(
                tool_call.tool_name
                if tool_call is not None
                else ""
            ),
            tool_arguments=(
                deepcopy(tool_call.arguments)
                if tool_call is not None
                else {}
            ),

            # PRE_TOOL_USE 没有结果；POST_TOOL_USE 才传入结果。
            tool_output=(
                tool_result.output
                if tool_result is not None
                else ""
            ),
            tool_is_error=(
                tool_result.is_error
                if tool_result is not None
                else False
            ),
        )
    
    async def _execute_tool_interactive(
        self,
        tool_call:ToolCall,
    )->AsyncIterator[
        PermissionRequest | ToolResult
    ]:
        tool = self.registry.get(
            tool_call.tool_name
        )

        if tool is None:
            yield ToolResult(
                output=(
                    f"Error: unknown tool "
                    f"'{tool_call.tool_name}'"
                ),
                is_error=True
            )
            return

        decision = self.permission_checker.check(
            tool,
            tool_call.arguments,
        )

        if decision.effect =="deny":
            yield ToolResult(
                output=(
                    f"Permission denied: "
                    f"{decision.reason}"
                ),
                is_error=True
            )
            return
        
        if decision.effect == "ask":
            loop = asyncio.get_running_loop()

            future:asyncio.Future[PermissionResponse] = (
                loop.create_future()
            )

            yield PermissionRequest(
                tool_id=tool_call.tool_id,
                tool_name = tool_call.tool_name,
                description=(
                    f"{tool_call.tool_name}: "
                    f"{tool_call.arguments}"
                ),
                reason=decision.reason,
                future=future,
            )

            response = await future

            if response == PermissionResponse.DENY:
                yield ToolResult(
                    output="Permission denied by user",
                    is_error=True,
                )
                return
            
        result = await self.registry.execute(
            tool_call.tool_name,
            tool_call.arguments,
        )
        
        yield result


    async def run_to_completion(
            self, 
            prompt:str,
            conversation:ConversationManager | None = None,
            on_compact: CompactCallback | None = None,
    )->str:
        trace = self._start_trace()

        try:
            if conversation is None:
                conversation = ConversationManager()

            self._current_conversation = conversation
            conversation.add_user_message(prompt)

            for _iteration in range(self.max_iterations):
                # 每轮模型调用开始前触发 TURN_START。
                await self.hook_engine.emit(
                    self._build_hook_context(
                        event=HookEvent.TURN_START,
                        trace=trace,
                        turn=_iteration + 1,
                    )
                )

                compact_event = await compact_conversation(
                    conversation,
                    self.client,
                    self.context_window,
                )

                if (
                    compact_event is not None
                    and compact_event.boundary is not None
                    and on_compact is not None
                ):
                    on_compact(compact_event.boundary)

                messages = build_chat_completion_messages(
                    conversation.get_messages()
                )

                response = await self.client.complete(
                    messages,
                    tools=self.registry.get_all_schemas(),
                )

                self.trace_manager.update(
                    trace.agent_id,
                    total_turns=_iteration + 1,
                    tool_call_count=(
                        trace.tool_call_count
                        + len(response.tool_calls)
                    ),
                )

                if not response.tool_calls:
                    conversation.add_assistant_message(response.text)

                    # 最终助手消息保存后，本轮处理结束。
                    await self.hook_engine.emit(
                        self._build_hook_context(
                            event=HookEvent.TURN_END,
                            trace=trace,
                            turn=_iteration + 1,
                        )
                    )

                    self.trace_manager.complete(
                        trace.agent_id
                    )
                    return response.text

                tool_uses = [
                    ToolUseBlock(
                        tool_use_id=tool_call.tool_id,
                        tool_name=tool_call.tool_name,
                        arguments=tool_call.arguments,
                    )
                    for tool_call in response.tool_calls
                ]

                conversation.add_assistant_message(response.text, tool_uses)

                tool_results:list[ToolResultBlock]=[]

                for tool_call in response.tool_calls:
                    # 在权限检查和工具执行前触发 Hook。
                    hook_result = await self.hook_engine.emit(
                        self._build_hook_context(
                            event=HookEvent.PRE_TOOL_USE,
                            trace=trace,
                            turn=_iteration + 1,
                            tool_call=tool_call,
                        )
                    )

                    # Hook 明确拒绝时，不再检查权限，也不执行工具。
                    if hook_result.decision == "reject":
                        result = ToolResult(
                            output=(
                                "Tool call rejected by Hook: "
                                f"{hook_result.reason or 'no reason provided'}"
                            ),
                            is_error=True,
                        )
                    else:
                        # Hook 没有拒绝，继续原来的权限及工具执行流程。
                        result = await (
                            self._execute_tool_noninteractive(
                                tool_call
                            )
                        )

                    # 只有真正进入工具执行流程后才触发 POST_TOOL_USE。
                    if hook_result.decision != "reject":
                        await self.hook_engine.emit(
                            self._build_hook_context(
                                event=HookEvent.POST_TOOL_USE,
                                trace=trace,
                                turn=_iteration + 1,
                                tool_call=tool_call,
                                tool_result=result,
                            )
                        )

                    tool_results.append(
                        ToolResultBlock(
                            tool_use_id=tool_call.tool_id,
                            content=result.output,
                            is_error=result.is_error,
                        )
                    )
                conversation.add_tool_results_message(tool_results)

                # 工具结果保存后，本轮处理结束。
                await self.hook_engine.emit(
                    self._build_hook_context(
                        event=HookEvent.TURN_END,
                        trace=trace,
                        turn=_iteration + 1,
                    )
                )

            self.trace_manager.complete(
                trace.agent_id,
                status="failed",
            )



            raise RuntimeError("Agent reached maximum iterations")

        except asyncio.CancelledError:
            self.trace_manager.complete(
                trace.agent_id,
                status="cancelled",
            )
            raise

        finally:
            if self._current_conversation is conversation:
                self._current_conversation = None

            if trace.end_time is None:
                self.trace_manager.complete(
                    trace.agent_id,
                    status="failed",
                )

    
    async def stream_to_completion(
            self,
            prompt:str,
            conversation:ConversationManager | None = None
    )->AsyncIterator[AgentEvent]:
        trace = self._start_trace()

        try:

            if conversation is None:
                conversation = ConversationManager()

            self._current_conversation = conversation
            conversation.add_user_message(prompt)

            for _iteration in range(self.max_iterations):
                # 流式模式也必须触发相同的 TURN_START。
                await self.hook_engine.emit(
                    self._build_hook_context(
                        event=HookEvent.TURN_START,
                        trace=trace,
                        turn=_iteration + 1,
                    )
                )

                compact_event = await compact_conversation(
                    conversation,
                    self.client,
                    self.context_window,
                )

                if compact_event is not None:
                    yield CompactNotification(
                        before_tokens=compact_event.before_tokens,
                        message=(
                            "上下文已压缩"
                            f"（压缩前 {compact_event.before_tokens:,} tokens）"
                        ),
                        boundary=compact_event.boundary,
                    )

                messages = build_chat_completion_messages(
                    conversation.get_messages()
                )

                collector = StreamCollector()

                stream = self.client.stream(
                    messages,
                    tools=self.registry.get_all_schemas(),
                )

                async for event in collector.consume(stream):
                    yield event

                response = collector.response

                self.trace_manager.update(
                    trace.agent_id,
                    total_turns=_iteration + 1,
                    tool_call_count=(
                        trace.tool_call_count
                        + len(response.tool_calls)
                    ),
                )

                if not response.tool_calls:
                    conversation.add_assistant_message(response.text)

                    # 最终助手消息保存后，本轮处理结束。
                    await self.hook_engine.emit(
                        self._build_hook_context(
                            event=HookEvent.TURN_END,
                            trace=trace,
                            turn=_iteration + 1,
                        )
                    )

                    self.trace_manager.complete(
                        trace.agent_id
                    )

                    yield LoopComplete(
                        total_turns=_iteration + 1,
                    )
                    return

                tool_uses = [
                    ToolUseBlock(
                        tool_use_id=tool_call.tool_id,
                        tool_name=tool_call.tool_name,
                        arguments=tool_call.arguments,
                    )
                    for tool_call in response.tool_calls
                ]

                conversation.add_assistant_message(
                    response.text,
                    tool_uses,
                )

                tool_results:list[ToolResultBlock] = []

                for tool_call in response.tool_calls:
                    # 在权限询问和工具执行前触发 Hook。
                    hook_result = await self.hook_engine.emit(
                        self._build_hook_context(
                            event=HookEvent.PRE_TOOL_USE,
                            trace=trace,
                            turn=_iteration + 1,
                            tool_call=tool_call,
                        )
                    )

                    result: ToolResult | None = None

                    # Hook 拒绝时，不再产生 PermissionRequest。
                    if hook_result.decision == "reject":
                        result = ToolResult(
                            output=(
                                "Tool call rejected by Hook: "
                                f"{hook_result.reason or 'no reason provided'}"
                            ),
                            is_error=True,
                        )
                    else:
                        # Hook 允许后，继续原来的交互式权限流程。
                        async for item in (
                            self._execute_tool_interactive(
                                tool_call
                            )
                        ):
                            if isinstance(
                                item,
                                PermissionRequest,
                            ):
                                yield item
                            else:
                                result = item

                    # 防止工具执行流程没有产生 ToolResult。
                    if result is None:
                        result = ToolResult(
                            output=(
                                "Error: tool produced no result"
                            ),
                            is_error=True,
                        )

                    # 工具产生结果后触发 POST_TOOL_USE。
                    if hook_result.decision != "reject":
                        await self.hook_engine.emit(
                            self._build_hook_context(
                                event=HookEvent.POST_TOOL_USE,
                                trace=trace,
                                turn=_iteration + 1,
                                tool_call=tool_call,
                                tool_result=result,
                            )
                        )

                    yield ToolResultEvent(
                        tool_id = tool_call.tool_id,
                        tool_name=tool_call.tool_name,
                        output = result.output,
                        is_error = result.is_error,
                    )

                    tool_results.append(
                        ToolResultBlock(
                            tool_use_id=tool_call.tool_id,
                            content=result.output,
                            is_error=result.is_error,
                        )
                    )

                conversation.add_tool_results_message(
                    tool_results
                )

                # 工具结果保存后，本轮处理结束。
                await self.hook_engine.emit(
                    self._build_hook_context(
                        event=HookEvent.TURN_END,
                        trace=trace,
                        turn=_iteration + 1,
                    )
                )

                yield TurnComplete(
                    turn=_iteration+1,
                )

            self.trace_manager.complete(
                trace.agent_id,
                status="failed",
            )

            yield ErrorEvent(
                message=(
                    f"Agent reached maximum iterations "
                    f"({self.max_iterations})"
                )
            )

        except asyncio.CancelledError:
            self.trace_manager.complete(
                trace.agent_id,
                status="cancelled",
            )
            raise

        finally:
            if self._current_conversation is conversation:
                self._current_conversation = None

            if trace.end_time is None:
                self.trace_manager.complete(
                    trace.agent_id,
                    status="failed",
                )
