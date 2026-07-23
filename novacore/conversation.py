from __future__ import annotations

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

@dataclass
class ConversationManager:
    history:list[Message] = field(default_factory=list)

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