from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import asyncio
from enum import Enum
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
        permission_checker: PermissionChecker | None = None,
        max_iterations:int = 5,
    )->None:
        self.client = client
        self.registry = registry
        self.permission_checker = (
            permission_checker
            if permission_checker is not None
            else PermissionChecker()
        )
        self.max_iterations = max_iterations

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
    )->str:
        conversation = conversation or ConversationManager()
        conversation.add_user_message(prompt)

        for _iteration in range(self.max_iterations):
            messages = build_chat_completion_messages(
                conversation.get_messages()
            )

            response = await self.client.complete(
                messages,
                tools=self.registry.get_all_schemas(),
            )

            if not response.tool_calls:
                conversation.add_assistant_message(response.text)
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
                result = await self._execute_tool_noninteractive(
                    tool_call
                )

                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=tool_call.tool_id,
                        content=result.output,
                        is_error=result.is_error,
                    )
                )
            conversation.add_tool_results_message(tool_results)

        raise RuntimeError("Agent reached maximum iterations")
    
    async def stream_to_completion(
            self,
            prompt:str,
            conversation:ConversationManager | None = None
    )->AsyncIterator[AgentEvent]:
        conversation = conversation or ConversationManager()
        conversation.add_user_message(prompt)

        for _iteration in range(self.max_iterations):
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

            if not response.tool_calls:
                conversation.add_assistant_message(response.text)

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
                result : ToolResult | None = None

                async for item in self._execute_tool_interactive(
                    tool_call
                ):
                    if isinstance(item, PermissionRequest):
                        yield item
                    else:result = item

                if result is None:
                    result = ToolResult(
                        output = ("Error :tool produced no result"),
                        is_error=True,
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

            yield TurnComplete(
                turn=_iteration+1,
            )

        yield ErrorEvent(
            message=(
                f"Agent reached maximum iterations " 
                f"({self.max_iterations})"
            )
        )
