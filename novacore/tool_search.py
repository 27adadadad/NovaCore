from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from novacore.tools import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
)

if TYPE_CHECKING:
    from novacore.conversation import Message


class ToolSearchParams(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "Search keywords, or select:ToolA,ToolB "
            "to load exact deferred tool names"
        ),
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of tools to discover",
    )


class ToolSearch:
    """让模型按需发现并激活延迟工具。"""

    name = "ToolSearch"
    description = (
        "Search for additional tools that are not currently loaded. "
        "Use 'select:ToolName' when you know the exact tool name."
    )
    category: ToolCategory = "read"
    params_model = ToolSearchParams

    def __init__(
        self,
        registry: ToolRegistry,
    ) -> None:
        self.registry = registry

    def get_schema(self) -> dict[str, Any]:
        parameters = self.params_model.model_json_schema()
        parameters.pop("title", None)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    async def execute(
        self,
        params: ToolSearchParams,
    ) -> ToolResult:
        query = params.query.strip()

        if query.lower().startswith("select:"):
            names = [
                name.strip()
                for name in query[7:].split(",")
                if name.strip()
            ]
        else:
            names = self.registry.search_deferred(
                query,
                params.max_results,
            )

        schemas = self.registry.discover_many(
            names[:params.max_results]
        )

        if not schemas:
            available = ", ".join(
                self.registry.get_deferred_tool_names()
            )
            return ToolResult(
                output=(
                    f"No deferred tools matched '{query}'. "
                    f"Available: {available or '(none)'}"
                )
            )

        return ToolResult(
            output=(
                f"Loaded {len(schemas)} tool(s). "
                "Their schemas will be available on the next model turn:\n"
                + json.dumps(
                    schemas,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        )


def restore_discovered_tools(
    registry: ToolRegistry,
    messages: list[Message],
) -> tuple[str, ...]:
    """根据已持久化的真实 tool use 恢复 deferred 激活状态。"""

    restored: list[str] = []

    for message in messages:
        for tool_use in message.tool_uses:
            name = tool_use.tool_name

            if not registry.contains(name):
                continue

            schema = registry.discover(name)

            if schema is not None:
                restored.append(name)

    return tuple(restored)
