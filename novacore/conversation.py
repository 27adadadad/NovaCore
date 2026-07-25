from __future__ import annotations

import json



from dataclasses import dataclass, field
from typing import Any 

@dataclass
class ToolUseBlock:
    tool_use_id:str
    tool_name:str
    arguments:dict[str, Any]

@dataclass 
class ToolResultBlock:
    tool_use_id:str
    content:str
    is_error:bool=False

@dataclass
class Message:
    role:str
    content:str
    tool_uses:list[ToolUseBlock]=field(default_factory=list)
    tool_results:list[ToolResultBlock]=field(default_factory=list)

_CHARS_PER_TOKEN = 3.5

def _message_chars(message:Message)->int:
    total = len(message.content)

    for tool_use in message.tool_uses:
        total += len(tool_use.tool_name)
        total += len(
            json.dumps(
                tool_use.arguments,
                ensure_ascii=False,
            )
        )

    for tool_result in message.tool_results:
        total += len(tool_result.content)

    return total

def estimate_tokens(
    messages: list[Message],
)->int:
    total_chars = sum(
        _message_chars(message)
        for message in messages
    )

    return int(
        total_chars / _CHARS_PER_TOKEN
    )

@dataclass
class ConversationManager:
    history:list[Message] = field(default_factory=list)

    def current_tokens(self)->int:
        return estimate_tokens(self.history)

    def replace_history(
        self,
        messages: list[Message],
    ) -> None:
        self.history = list(messages)

    def add_user_message(self, content:str):
        self.history.append(Message(role="user", content = content))

    def add_assistant_message(
        self,
        content:str,    
        tool_uses:list[ToolUseBlock] | None=None
    )->None:
        self.history.append(
            Message(
                role="assistant",
                content=content,
                tool_uses=tool_uses or [],
            )
        )

    def add_tool_results_message(self, tool_results:list[ToolResultBlock])->None:
        self.history.append(
            Message(
                role="user",
                content="",
                tool_results=tool_results
            )
        )

    def get_messages(self)->list[Message]:
        return list(self.history)