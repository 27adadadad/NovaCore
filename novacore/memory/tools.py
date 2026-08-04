from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from novacore.memory.store import (
    MAX_MEMORY_ENTRY_CHARS,
    MemoryStoreError,
    MAX_MEMORY_INJECTION_CHARS,
    MemoryScope,
    MemoryStore,
)
from novacore.tools import ToolCategory, ToolResult


class RecallMemoryParams(BaseModel):
    query: str = Field(
        default="",
        description=(
            "Optional text to search for. Empty returns "
            "the current memory content."
        ),
    )
    scope: Literal["all", "project", "user"] = Field(
        default="all",
        description="Memory scope to read",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum search result lines",
    )


class RememberParams(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=MAX_MEMORY_ENTRY_CHARS,
        description="Durable fact or preference to remember",
    )
    scope: MemoryScope = Field(
        default="project",
        description=(
            "project for repository-specific knowledge; "
            "user for preferences shared across projects"
        ),
    )


def _schema(
    name: str,
    description: str,
    model: type[BaseModel],
) -> dict[str, Any]:
    parameters = model.model_json_schema()
    parameters.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


class RecallMemory:
    name = "RecallMemory"
    description = (
        "Read or search durable user and project memory."
    )
    category: ToolCategory = "read"
    params_model = RecallMemoryParams

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name,
            self.description,
            self.params_model,
        )

    async def execute(
        self,
        params: RecallMemoryParams,
    ) -> ToolResult:
        scopes: tuple[MemoryScope, ...]

        if params.scope == "all":
            scopes = ("user", "project")
        else:
            scopes = (params.scope,)

        try:
            if params.query.strip():
                matches = self.store.search(
                    params.query,
                    scopes,
                    params.limit,
                )
                return ToolResult(
                    output=(
                        "\n".join(matches)
                        if matches
                        else "No matching memory"
                    )
                )

            sections = [
                f"## {scope}\n{self.store.read(scope) or '(empty)'}"
                for scope in scopes
            ]
            output = "\n\n".join(sections)

            if len(output) > MAX_MEMORY_INJECTION_CHARS:
                marker = "[Older memory omitted]\n\n"
                output = (
                    marker
                    + output[-(
                        MAX_MEMORY_INJECTION_CHARS
                        - len(marker)
                    ):]
                )

            return ToolResult(
                output=output
            )
        except MemoryStoreError as exc:
            return ToolResult(
                output=f"Could not recall memory: {exc}",
                is_error=True,
            )


class Remember:
    name = "Remember"
    description = (
        "Store a durable fact or preference in fixed NovaCore memory."
    )
    category: ToolCategory = "write"
    params_model = RememberParams

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name,
            self.description,
            self.params_model,
        )

    async def execute(
        self,
        params: RememberParams,
    ) -> ToolResult:
        try:
            self.store.append(
                params.scope,
                params.content,
            )
        except MemoryStoreError as exc:
            return ToolResult(
                output=f"Could not store memory: {exc}",
                is_error=True,
            )
        return ToolResult(
            output=(
                f"Stored memory in {params.scope} scope"
            )
        )
