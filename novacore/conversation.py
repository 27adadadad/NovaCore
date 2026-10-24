from __future__ import annotations

from collections.abc import Callable

import json



from dataclasses import dataclass, field
from typing import Any 
from novacore.task_state import TaskState, render_task_state

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
    # Typed runtime metadata: never infer this field from user/model text.
    task_state: dict[str, Any] | None = None

MessageCallback = Callable[[Message], None]

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
    on_message: MessageCallback | None = field(
        default=None,
        repr=False,
    )
    task_state: TaskState | None = field(default=None, repr=False)

    def begin_task(self, prompt: str) -> None:
        if self.task_state is None:
            for message in reversed(self.history):
                restored = TaskState.from_payload(message.task_state)
                if restored is not None:
                    self.task_state = restored
                    break
        if self.task_state is None:
            self.task_state = TaskState()
        self.task_state.begin(prompt)

    def publish_task_state(self) -> None:
        if self.task_state is None:
            return
        # Do not insert a reminder between a tool-call group and its results.
        result_ids: set[str] = set()
        for message in reversed(self.history):
            result_ids.update(item.tool_use_id for item in message.tool_results)
            if message.role == "assistant":
                if message.tool_uses and not {item.tool_use_id for item in message.tool_uses} <= result_ids:
                    return
                break
        payload = self.task_state.payload()
        previous = next((m.task_state for m in reversed(self.history)
                         if TaskState.from_payload(m.task_state) is not None), None)
        if previous is not None:
            comparable = dict(previous)
            comparable["revision"] = payload["revision"]
            if comparable == payload:
                return
        self.task_state.revision += 1
        payload = self.task_state.payload()
        self._append_message(Message(role="user", content=render_task_state(payload), task_state=payload))

    def _append_message(
        self,
        message: Message,
    ) -> None:
        self.history.append(message)

        if self.on_message is not None:
            self.on_message(message)

    def current_tokens(self)->int:
        return estimate_tokens(self.history)

    def replace_history(
        self,
        messages: list[Message],
    ) -> None:
        self.history = list(messages)

    def add_system_message(
        self,
        content: str,
    ) -> None:
        self._append_message(
            Message(
                role="system",
                content=content,
            )
        )

    def prepend_system_message(
        self,
        content: str,
    ) -> None:
        """加入仅属于当前进程的 system 上下文，不触发持久化回调。"""

        self.history.insert(
            0,
            Message(
                role="system",
                content=content,
            ),
        )

    def add_user_message(self, content:str):
        self._append_message(Message(role="user", content = content))

    def add_assistant_message(
        self,
        content:str,    
        tool_uses:list[ToolUseBlock] | None=None
    )->None:
        self._append_message(
            Message(
                role="assistant",
                content=content,
                tool_uses=tool_uses or [],
            )
        )

    def add_tool_results_message(self, tool_results:list[ToolResultBlock])->None:
        self._append_message(
            Message(
                role="user",
                content="",
                tool_results=tool_results
            )
        )

    def get_messages(self)->list[Message]:
        return list(self.history)
