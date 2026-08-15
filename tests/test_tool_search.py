from __future__ import annotations

from pydantic import BaseModel

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

