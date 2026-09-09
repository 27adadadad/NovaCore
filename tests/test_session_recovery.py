from __future__ import annotations

from pydantic import BaseModel

from novacore.conversation import Message, ToolResultBlock, ToolUseBlock
from novacore.session import SessionManager
from novacore.tool_search import restore_discovered_tools
from novacore.tools import ToolRegistry, ToolResult


class _Params(BaseModel):
    query: str


class _DeferredTool:
    name = "SearchDocs"
    description = "Search technical documentation"
    category = "read"
    params_model = _Params

    def get_schema(self):
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description},
        }

    async def execute(self, params):
        return ToolResult(output=params.query)


def test_session_round_trip_preserves_tool_pair_and_restores_deferred_tool(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.create()
    session.append(Message(role="user", content="search docs"))
    session.append(
        Message(
            role="assistant",
            content="",
            tool_uses=[
                ToolUseBlock("call-1", "SearchDocs", {"query": "docs"})
            ],
        )
    )
    session.append(
        Message(
            role="user",
            content="",
            tool_results=[ToolResultBlock("call-1", "found")],
        )
    )
    session.close()

    resumed = manager.resume(session.session_id)
    assert resumed is not None
    assert resumed.messages[1].tool_uses[0].tool_use_id == "call-1"
    assert resumed.messages[2].tool_results[0].tool_use_id == "call-1"

    registry = ToolRegistry()
    registry.register(_DeferredTool(), deferred=True)
    restored = restore_discovered_tools(registry, resumed.messages)

    assert restored == ("SearchDocs",)
    assert registry.get("SearchDocs") is not None
