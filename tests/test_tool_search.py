from __future__ import annotations

from pydantic import BaseModel

from novacore.agent import Agent
from novacore.client import ClientResponse, ToolCall
from novacore.tool_search import ToolSearch
from novacore.tools import ToolRegistry, ToolResult


class _Params(BaseModel):
    query: str


class _DeferredTool:
    name = "SearchDocs"
    description = "Search technical documentation"
    category = "read"
    params_model = _Params

    def get_schema(self):
        return {"type": "function", "function": {"name": self.name}}

    async def execute(self, params):
        return ToolResult(output=params.query)


async def test_search_activates_only_matching_deferred_tool():
    registry = ToolRegistry()
    registry.register(_DeferredTool(), deferred=True)
    search = ToolSearch(registry)

    result = await search.execute(search.params_model(query="documentation"))

    assert "Loaded 1 tool(s)" in result.output
    assert registry.get("SearchDocs") is not None


async def test_search_normalizes_small_synonym_variations():
    registry = ToolRegistry()
    registry.register(_DeferredTool(), deferred=True)
    search = ToolSearch(registry)

    result = await search.execute(search.params_model(query="find manuals"))

    assert "Loaded 1 tool(s)" in result.output
    assert registry.get("SearchDocs") is not None


class _DiscoverySequenceClient:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(tools)
        if len(self.calls) == 1:
            return ClientResponse(
                tool_calls=[
                    ToolCall(
                        tool_id="search-call",
                        tool_name="ToolSearch",
                        arguments={"query": "documentation"},
                    )
                ]
            )
        return ClientResponse(text="done")


async def test_discovered_schema_is_exposed_on_the_next_model_turn():
    registry = ToolRegistry()
    search = ToolSearch(registry)
    registry.register(search)
    registry.register(_DeferredTool(), deferred=True)
    client = _DiscoverySequenceClient()

    result = await Agent(
        client=client,
        registry=registry,
        context_window=100_000,
    ).run_to_completion("find documentation")

    assert result == "done"
    assert [tool["function"]["name"] for tool in client.calls[0]] == [
        "ToolSearch"
    ]
    assert [tool["function"]["name"] for tool in client.calls[1]] == [
        "ToolSearch",
        "SearchDocs",
    ]

