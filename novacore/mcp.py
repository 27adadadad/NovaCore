from __future__ import annotations
import json
from pydantic import BaseModel, ConfigDict, ValidationError
from collections.abc import Awaitable, Callable
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import AsyncExitStack
from mcp import StdioServerParameters, ClientSession
from mcp.client.stdio import stdio_client


from mcp.types import (
    PaginatedRequestParams,
    Tool as MCPTool,
    TextContent,
)

from novacore.tools import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
    VALID_TOOL_NAME,
)

MCPToolExecutor = Callable[
    [str, dict[str, Any]],
    Awaitable[ToolResult]
]

class MCPToolParams(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )

@dataclass
class MCPServerConfig:
    name:str
    command:str
    args:list[str] = field(
        default_factory=list,
    )
    env:dict[str, str] | None = None
    cwd:str | Path | None = None

    def to_stdio_parameters(
        self,
    )->StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
        )

class MCPConfigFile(BaseModel):
    servers: list[MCPServerConfig]

def load_mcp_server_configs(
    path: str | Path,
) -> list[MCPServerConfig]:
    config_path = Path(path)

    try:
        raw_text = config_path.read_text(
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not read MCP config "
            f"'{config_path}': {exc}"
        ) from exc

    try:
        config_file = (
            MCPConfigFile.model_validate_json(
                raw_text
            )
        )
    except ValidationError as exc:
        raise RuntimeError(
            f"Invalid MCP config "
            f"'{config_path}': {exc}"
        ) from exc

    names: set[str] = set()

    for server in config_file.servers:
        if not server.name.strip():
            raise RuntimeError(
                "MCP server name cannot be empty"
            )

        if not server.command.strip():
            raise RuntimeError(
                f"MCP server '{server.name}' "
                "command cannot be empty"
            )

        if server.name in names:
            raise RuntimeError(
                f"Duplicate MCP server name: "
                f"{server.name}"
            )

        names.add(server.name)

    return list(config_file.servers)

class MCPClient:
    def __init__(
        self,
        config:MCPServerConfig,
    )->None:
        self.config = config
        # 管理需要长期保持打开的异步资源
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def connect(
        self,
    )->None:
        if self._session is not None:
            return

        parameters = (
            self.config.to_stdio_parameters()
        )


        try:
            read_stream, write_stream = await(
                self._exit_stack.enter_async_context(
                    stdio_client(parameters)
                )
            )

            session = await(
                self._exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                    )
                )
            )

            await session.initialize()

        except BaseException:
            await self.close()
            raise

        self._session = session

    def _require_session(
        self,
    )->ClientSession:
        session = self._session

        if session is None:
            raise RuntimeError(
                f"MCP server "
                f"'{self.config.name}' "
                "is not connected"
            )

        return session

    async def list_tools(
        self,
    ) -> list[MCPTool]:
        session = self._require_session()

        tools: list[MCPTool] = []
        cursor: str | None = None

        while True:
            params = PaginatedRequestParams(
                cursor=cursor,
            )

            result = await session.list_tools(
                params=params,
            )

            tools.extend(result.tools)
            cursor = result.nextCursor

            if cursor is None:
                break

        return tools

    async def create_tool_adapters(
        self,
    )->list[MCPToolAdapter]:
        remote_tools = await self.list_tools()
        adapters:list[MCPToolAdapter] = []

        for tool in remote_tools:
            public_name = (
                f"{self.config.name}_{tool.name}"
            )
            description = (
                tool.description
                or(
                    f"MCP tool '{tool.name}' "
                    f"from '{self.config.name}'"
                )
            )

            adapter = MCPToolAdapter(
                public_name=public_name,
                remote_name=tool.name,
                description=description,
                input_schema=tool.inputSchema,
                executor=self.call_tool,
            )

            adapters.append(adapter)

        return adapters

    async def call_tool(
        self,
        name:str,
        arguments:dict[str, Any],
    )->ToolResult:
        session = self._require_session()

        try:
            result = await session.call_tool(
                name,
                arguments=arguments,
            )
        except Exception as exc:
            return ToolResult(
                output=(
                    f"MCP tool '{name}' failed: "
                    f"{exc}"
                ),
                is_error=True,
            )

        parts:list[str] = []

        for content in result.content:
            if isinstance(content, TextContent):
                parts.append(content.text)
            else:
                parts.append(
                    content.model_dump_json(
                        by_alias=True,
                    )
                )

        if result.structuredContent is not None:
            structured_text = json.dumps(
                result.structuredContent,
                ensure_ascii=False,
            )
            parts.append(structured_text)

        output = "\n".join(parts)

        if not output:
            output = "(no output)"

        return ToolResult(
            output=output,
            is_error=result.isError,
        )

    async def close(
        self,
    )->None:
        try:
            await self._exit_stack.aclose()
        finally:
            self._session = None
            self._exit_stack = AsyncExitStack()


class MCPToolAdapter:
    category:ToolCategory = "command"
    params_model = MCPToolParams

    def __init__(
        self,
        public_name:str,
        remote_name:str,
        description:str,
        input_schema:dict[str, Any],
        executor:MCPToolExecutor
    )->None:
        self.name = public_name
        self.remote_name = remote_name
        self.description = description
        self.input_schema = input_schema
        self._executor = executor

    def get_schema(self)->dict[str, Any]:
        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":self.input_schema,
            }
        }

    async def execute(
        self,
        params:MCPToolParams,
    )->ToolResult:
        arguments = params.model_dump()

        return await self._executor(
            self.remote_name,
            arguments,
        )

class MCPManager:
    def __init__(
        self,
        registry:ToolRegistry,
    )->None:
        self.registry = registry
        self._clients:dict[
            str,
            MCPClient,
        ]={}

    async def connect_server(
        self,
        config: MCPServerConfig,
    ) -> list[str]:
        if config.name in self._clients:
            raise RuntimeError(
                f"MCP server already connected: "
                f"{config.name}"
            )

        client = MCPClient(config)

        try:
            await client.connect()
            adapters = (
                await client.create_tool_adapters()
            )

            seen_names: set[str] = set()

            for adapter in adapters:
                if not VALID_TOOL_NAME.fullmatch(
                    adapter.name
                ):
                    raise RuntimeError(
                        "MCP public tool name is not valid for "
                        f"the model protocol: {adapter.name!r}"
                    )

                if adapter.name in seen_names:
                    raise RuntimeError(
                        f"Duplicate MCP tool name: "
                        f"{adapter.name}"
                    )

                if self.registry.contains(
                    adapter.name
                ):
                    raise RuntimeError(
                        f"MCP tool name conflicts "
                        f"with existing tool: "
                        f"{adapter.name}"
                    )

                seen_names.add(adapter.name)

            for adapter in adapters:
                self.registry.register(
                    adapter,
                    deferred=True,
                )

        except BaseException:
            await client.close()
            raise

        self._clients[config.name] = client

        return [
            adapter.name
            for adapter in adapters
        ]

    async def close(
        self,
    ) -> None:
        clients = list(
            self._clients.values()
        )
        self._clients.clear()

        first_error: BaseException | None = None

        for client in reversed(clients):
            try:
                await client.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error
