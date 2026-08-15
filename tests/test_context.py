from __future__ import annotations

from novacore.context import split_for_compaction
from novacore.conversation import Message, ToolResultBlock, ToolUseBlock


def test_compaction_keeps_tool_use_with_its_result():
    messages = [
        Message(role="user", content="old context " * 500),
        Message(
            role="assistant",
            content="",
            tool_uses=[
                ToolUseBlock("call-1", "ReadFile", {"file_path": "a.py"})
            ],
        ),
        Message(
            role="user",
            content="",
            tool_results=[ToolResultBlock("call-1", "file contents")],
        ),
        Message(role="assistant", content="continue"),
        Message(role="user", content="next instruction"),
        Message(role="assistant", content="working"),
        Message(role="user", content="finish"),
    ]

    _old, keep_recent = split_for_compaction(messages)

    assert keep_recent[0].role == "assistant"
    assert keep_recent[0].tool_uses[0].tool_use_id == "call-1"
    assert keep_recent[1].tool_results[0].tool_use_id == "call-1"

