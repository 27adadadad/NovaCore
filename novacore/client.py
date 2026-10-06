from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

import json

from novacore.config import Config


@dataclass
class ToolCall:
    tool_id:str
    tool_name:str
    arguments:dict[str, Any]

@dataclass
class TextDelta:
    text:str

@dataclass
class ToolCallComplete:
    tool_call:ToolCall

StreamEvent = TextDelta | ToolCallComplete

@dataclass 
class ClientResponse:
    text:str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

class Client(Protocol):
    async def complete(
        self,
        messages:list[dict[str, Any]],
        tools:list[dict[str, Any]],
    )->ClientResponse:
        ...

    def stream(
        self,
        messages:list[dict[str,Any]],
        tools:list[dict[str,Any]],
    )->AsyncIterator[StreamEvent]:
        ...
        

class FakeClient:
    def __init__(
        self, 
        tool_name,
        tool_arguments:dict[str, Any],
        final_text:str,
    )->None:
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments
        self.final_text = final_text
        self.calls = 0

    async def complete(
        self, 
        messages:list[dict[str,Any]],
        tools:list[dict[str, Any]]
    )->ClientResponse:
        self.calls +=1
        has_tool_result = any(message["role"]=="tool" for message in messages)

        if not has_tool_result:
            return ClientResponse(
                tool_calls=[
                    ToolCall(
                        tool_id="call_1",
                        tool_name=self.tool_name,
                        arguments=self.tool_arguments,
                    )
                ]
            )
        
        return ClientResponse(text=self.final_text)
        

class DashScopeClient:
    def __init__(self, config:Config)->None:
        self._sdk = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model

    async def complete(
        self,
        messages:list[dict[str, Any]],
        tools:list[dict[str, Any]],
    )->ClientResponse:
        response = await self._sdk.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
        )

        message = response.choices[0].message

        tool_calls:list[ToolCall] = []

        for tool_call in message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    tool_id=tool_call.id,
                    tool_name=tool_call.function.name,
                    arguments=json.loads(
                        tool_call.function.arguments
                    ),
                )
            )
        
        return ClientResponse(
            text=message.content or "",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages:list[dict[str,Any]],
        tools:list[dict[str, Any]],
    )->AsyncIterator[StreamEvent]:
        stream = await self._sdk.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            stream=True
        )

        tool_buffers:dict[int, dict[str, str]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            
            if delta.content:
                yield TextDelta(text=delta.content)

            for tool_delta in delta.tool_calls or []:
                buffer = tool_buffers.setdefault(
                    tool_delta.index,
                    {
                        "id":"",
                        "name":"",
                        "arguments":"",
                    },
                )

                if tool_delta.id:
                    buffer["id"] = tool_delta.id

                if tool_delta.function:
                    buffer["name"]+=tool_delta.function.name or ""
                    buffer["arguments"]+=(
                        tool_delta.function.arguments or ""
                    )

        for index in sorted(tool_buffers):
            buffer = tool_buffers[index]

            if not buffer["id"] or not buffer["name"]:
                raise RuntimeError(
                    f"Incomplete tool call ar index {index}"
                )

            try:
                arguments = json.loads(
                    buffer["arguments"] or "{}"
                )

            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid arguments for tool call"
                    f"{buffer['id']}:{buffer['arguments']}"
                )from exc
            
            yield ToolCallComplete(
                tool_call=ToolCall(
                    tool_id=buffer["id"],
                    tool_name=buffer["name"],
                    arguments=arguments,
                )
            )
