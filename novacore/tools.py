from __future__ import annotations

import re

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Literal

from pydantic import BaseModel, Field, ValidationError

import asyncio

ToolCategory = Literal["read", "write", "command"]
MAX_COMMAND_TIMEOUT=600
VALID_TOOL_NAME = re.compile(
    r"^[A-Za-z0-9_-]{1,64}$"
)
SKIP_SEARCH_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
}


def _resolve_work_path(
    work_dir: str | Path,
    requested_path: str | Path,
) -> Path:
    """把工具路径解析到固定工作目录内。"""

    root = (
        Path(work_dir)
        .expanduser()
        .resolve()
    )
    candidate = (
        Path(requested_path)
        .expanduser()
    )

    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        resolved = candidate.resolve()
    except (
        OSError,
        RuntimeError,
    ) as exc:
        raise ValueError(
            "could not resolve path: "
            f"{requested_path}"
        ) from exc

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "path must stay inside work_dir: "
            f"{requested_path}"
        ) from exc

    return resolved

@dataclass
class ToolResult:
    output:str
    is_error:bool = False

class ReadFileParams(BaseModel):
    file_path:str = Field(description="Abslute or reletive pathto the file to read")
    offset:int = Field(default = 0, description="Line offset to start reading from")
    limit: int = Field(default=2000, description="Maximum number of lines to read")

class WriteFileParams(BaseModel):
    file_path: str = Field(
        description="Path to the file to write"
    )
    content: str = Field(
        description="Content to write to the file"
    )

class BashParams(BaseModel):
    command: str = Field(
        description="Shell command to execute"
    )
    timeout: int = Field(
        default=120,
        gt=0,
        description="Timeout in seconds, maximum 600"
    )

class GlobParams(BaseModel):
    pattern: str = Field(
        min_length=1,
        description=(
            "Glob pattern used to match files, "
            "for example '**/*.py'"
        ),
    )

    path: str = Field(
        default=".",
        min_length=1,
        description=(
            "Base directory to search from"
        ),
    )

    limit: int = Field(
        default=200,
        gt=0,
        le=1000,
        description=(
            "Maximum number of matched files "
            "to return"
        ),
    )

class GrepParams(BaseModel):
    pattern: str = Field(
        min_length=1,
        description=(
            "Regular expression used to "
            "search file contents"
        ),
    )

    path: str = Field(
        default=".",
        min_length=1,
        description=(
            "Base directory to search from"
        ),
    )

    include: str = Field(
        default="",
        description=(
            "Optional glob pattern used to "
            "filter filenames, for example '*.py'"
        ),
    )

    limit: int = Field(
        default=200,
        gt=0,
        le=1000,
        description=(
            "Maximum number of matching "
            "lines to return"
        ),
    )

class Tool(Protocol):
    name:str
    description:str
    category:ToolCategory
    params_model:type[BaseModel]

    def get_schema(self)->dict[str, Any]:
        ...

    async def execute(self, params:BaseModel)->ToolResult:
        ...

class ReadFile:
    name = "ReadFile"
    description = "Read a file and return its contents with line numbers"
    category:ToolCategory = "read"
    params_model = ReadFileParams

    def __init__(
        self,
        work_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else Path.cwd().resolve()
        )

    def get_schema(self)->dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":schema,
            }
        }
    
    async def execute(self, params:ReadFileParams)->ToolResult:
        try:
            path = _resolve_work_path(
                self.work_dir,
                params.file_path,
            )
        except ValueError as exc:
            return ToolResult(
                output=f"Error reading file: {exc}",
                is_error=True,
            )

        if not path.exists():
            return ToolResult(
                output=f"Error: file not found:{params.file_path}",
                is_error=True,
            )

        if not path.is_file():
            return ToolResult(
                output=f"Error:not a file:{params.file_path}",
                is_error=True,
            )

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(
                output=f"Error reading file:{exc}",
                is_error=True,
            )
        
        lines = text.splitlines()
        selected = lines[params.offset: params.offset+params.limit]
        numbered = [
            f"{index + params.offset + 1}\t{line}"
            for index, line in enumerate(selected)
        ]

        return ToolResult(output="\n".join(numbered))

class Glob:
    name = "Glob"

    description = (
        "Find files matching a glob pattern "
        "and return their relative paths"
    )

    category: ToolCategory = "read"
    params_model = GlobParams

    def __init__(
        self,
        work_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else Path.cwd().resolve()
        )

    def get_schema(
        self,
    ) -> dict[str, Any]:
        schema = (
            self.params_model.model_json_schema()
        )

        schema.pop("title", None)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    async def execute(
        self,
        params: GlobParams,
    ) -> ToolResult:
        try:
            base = _resolve_work_path(
                self.work_dir,
                params.path,
            )
        except ValueError as exc:
            return ToolResult(
                output=(
                    f"Error searching files: {exc}"
                ),
                is_error=True,
            )

        if not base.exists():
            return ToolResult(
                output=(
                    "Error: search path not found: "
                    f"{params.path}"
                ),
                is_error=True,
            )

        if not base.is_dir():
            return ToolResult(
                output=(
                    "Error: search path is not "
                    f"a directory: {params.path}"
                ),
                is_error=True,
            )

        pattern_path = Path(
            params.pattern
        )

        if (
            pattern_path.is_absolute()
            or ".." in pattern_path.parts
        ):
            return ToolResult(
                output=(
                    "Error: glob pattern must "
                    "stay inside the search path"
                ),
                is_error=True,
            )

        matches: list[str] = []

        try:
            for candidate in base.glob(
                params.pattern
            ):
                if not candidate.is_file():
                    continue

                if any(
                    part in SKIP_SEARCH_DIRS
                    for part in candidate.parts
                ):
                    continue

                try:
                    relative = (
                        candidate.resolve()
                        .relative_to(
                            self.work_dir
                        )
                    )
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                ):
                    continue

                matches.append(
                    relative.as_posix()
                )

        except (
            OSError,
            ValueError,
            NotImplementedError,
        ) as exc:
            return ToolResult(
                output=(
                    "Error searching files: "
                    f"{exc}"
                ),
                is_error=True,
            )

        matches.sort()

        if not matches:
            return ToolResult(
                output=(
                    "No files matched the pattern."
                )
            )

        total_matches = len(matches)

        visible_matches = matches[
            :params.limit
        ]

        output = "\n".join(
            visible_matches
        )

        if total_matches > params.limit:
            omitted = (
                total_matches
                - params.limit
            )

            output += (
                "\n"
                f"... {omitted} more files "
                "were omitted"
            )

        return ToolResult(
            output=output
        )

class Grep:
    name = "Grep"

    description = (
        "Search file contents using a regular "
        "expression and return matching lines"
    )

    category: ToolCategory = "read"
    params_model = GrepParams

    def __init__(
        self,
        work_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else Path.cwd().resolve()
        )

    def get_schema(
        self,
    ) -> dict[str, Any]:
        schema = (
            self.params_model.model_json_schema()
        )

        schema.pop("title", None)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    async def execute(
        self,
        params: GrepParams,
    ) -> ToolResult:
        try:
            base = _resolve_work_path(
                self.work_dir,
                params.path,
            )
        except ValueError as exc:
            return ToolResult(
                output=(
                    f"Error searching files: {exc}"
                ),
                is_error=True,
            )

        if not base.exists():
            return ToolResult(
                output=(
                    "Error: search path not found: "
                    f"{params.path}"
                ),
                is_error=True,
            )

        if not base.is_dir():
            return ToolResult(
                output=(
                    "Error: search path is not "
                    f"a directory: {params.path}"
                ),
                is_error=True,
            )

        try:
            regex = re.compile(
                params.pattern
            )
        except re.error as exc:
            return ToolResult(
                output=(
                    "Error: invalid regular "
                    f"expression: {exc}"
                ),
                is_error=True,
            )

        file_pattern = (
            params.include.strip()
            or "*"
        )

        include_path = Path(
            file_pattern
        )

        if (
            include_path.is_absolute()
            or ".." in include_path.parts
        ):
            return ToolResult(
                output=(
                    "Error: include pattern must "
                    "stay inside the search path"
                ),
                is_error=True,
            )

        results: list[str] = []

        try:
            file_paths = sorted(
                base.rglob(
                    file_pattern
                )
            )

            for file_path in file_paths:
                if not file_path.is_file():
                    continue

                if any(
                    part in SKIP_SEARCH_DIRS
                    for part in file_path.parts
                ):
                    continue

                try:
                    resolved_file = (
                        file_path.resolve()
                    )

                    relative_file = (
                        resolved_file.relative_to(
                            self.work_dir
                        )
                    )
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                ):
                    continue

                try:
                    text = (
                        resolved_file.read_text(
                            encoding="utf-8",
                            errors="ignore",
                        )
                    )
                except OSError:
                    continue

                for line_number, line in enumerate(
                    text.splitlines(),
                    start=1,
                ):
                    if not regex.search(line):
                        continue

                    results.append(
                        (
                            f"{relative_file.as_posix()}"
                            f":{line_number}:{line}"
                        )
                    )

                    if len(results) >= params.limit:
                        break

                if len(results) >= params.limit:
                    break

        except (
            OSError,
            ValueError,
            NotImplementedError,
        ) as exc:
            return ToolResult(
                output=(
                    "Error searching file "
                    f"contents: {exc}"
                ),
                is_error=True,
            )

        if not results:
            return ToolResult(
                output=(
                    "No matching lines found."
                )
            )

        output = "\n".join(
            results
        )

        if len(results) >= params.limit:
            output += (
                "\n"
                "Result limit reached; "
                "more matches may exist."
            )

        return ToolResult(
            output=output
        )

    
class WriteFile:
    name = "WriteFile"
    description = (
        "Write content to a file, creating parent "
        "directories if needed. Overwrites existing files."
    )
    category:ToolCategory = "write"
    params_model = WriteFileParams

    def __init__(
        self,
        work_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else Path.cwd().resolve()
        )

    def get_schema(self)->dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)

        return {
            "type":"function",
            "function": {
                "name":self.name,
                "description":self.description,
            "parameters":schema,
            },
        }
    
    async def execute(
        self, 
        params:WriteFileParams,
    )->ToolResult:
        try:
            path = _resolve_work_path(
                self.work_dir,
                params.file_path,
            )
        except ValueError as exc:
            return ToolResult(
                output=f"Error writing file: {exc}",
                is_error=True,
            )

        try:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_text(
                params.content,
                encoding="utf-8",
            )

        except Exception as exc:
            return ToolResult(
                output=f"Error writing file: {exc}",
                is_error=True,
            )
        
        return ToolResult(
            output=(
                f"Successfully wrote to "
                f"{params.file_path}"
            )
        )
    
class Bash:
    name = "Bash"
    description = (
        "Execute a shell command and return its output"
    )
    category:ToolCategory = "command"
    params_model = BashParams

    def __init__(
        self,
        work_dir:str | Path | None = None
    )->None:
        self.work_dir = (
            Path(work_dir).resolve()
            if work_dir is not None
            else Path.cwd()
        )

    def get_schema(self)->dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)

        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":schema,
            }
        }

    async def execute(
        self,
        params:BashParams,
    )->ToolResult:
        timeout = min(
            params.timeout,
            MAX_COMMAND_TIMEOUT,
        )

        process:asyncio.subprocess.Process | None = None

        try:
            process = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.work_dir,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            if (
                process is not None 
                and process.returncode is None 
            ):
                process.kill()
                await process.wait()

            return ToolResult(
                output=(
                    f"Error: command timed out "
                    f"after {timeout}s"
                ),
                is_error=True
            )
        
        except Exception as exc:
            return ToolResult(
                output=f"Error executing command: {exc}",
                is_error=True,
            )

        output = (
            stdout.decode(errors="replace")
            if stdout
            else "(no output)"
        )

        exit_code = process.returncode or 0

        if exit_code != 0:
            output = (
                f"{output.rstrip()}\n\n"
                f"Exit code {exit_code}"
            )

        return ToolResult(
            output=output,
            is_error=False,
        )

class ToolRegistry:
    def __init__(self)-> None:
        self._tools:dict[str, Tool] = {}
        self._discovered: set[str] = set()

    def register(
        self,
        tool: Tool,
        deferred: bool = False,
    ) -> None:
        """注册工具；deferred 工具在被发现前不会暴露给模型。"""

        name = tool.name

        if not VALID_TOOL_NAME.fullmatch(name):
            raise ValueError(
                "Tool name must contain only letters, numbers, "
                "underscores, or hyphens and be at most "
                f"64 characters: {name!r}"
            )

        if name in self._tools:
            raise ValueError(
                f"Tool already registered: {name}"
            )

        self._tools[name] = tool

        if not deferred:
            self._discovered.add(name)

    def get(self, name:str)-> Tool | None:
        if name not in self._discovered:
            return None

        return self._tools.get(name)

    def contains(self, name: str) -> bool:
        """无论是否已发现，都检查工具名称是否已注册。"""

        return name in self._tools

    def list_tools(
        self,
        include_deferred: bool = False,
    ) -> list[Tool]:
        if include_deferred:
            return list(self._tools.values())

        return [
            tool
            for name, tool in self._tools.items()
            if name in self._discovered
        ]

    def get_deferred_tool_names(
        self,
    ) -> tuple[str, ...]:
        """返回尚未向模型暴露的工具名。"""

        return tuple(
            sorted(
                name
                for name in self._tools
                if name not in self._discovered
            )
        )

    def discover(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        """激活一个 deferred 工具并返回其完整 schema。"""

        tool = self._tools.get(name)

        if (
            tool is None
            or name in self._discovered
        ):
            return None

        schema = tool.get_schema()
        self._discovered.add(name)
        return schema

    def discover_many(
        self,
        names: list[str],
    ) -> list[dict[str, Any]]:
        """按给定顺序激活多个工具，自动忽略重复名称。"""

        schemas: list[dict[str, Any]] = []
        seen: set[str] = set()

        for name in names:
            if name in seen:
                continue

            seen.add(name)
            schema = self.discover(name)

            if schema is not None:
                schemas.append(schema)

        return schemas

    def search_deferred(
        self,
        query: str,
        limit: int,
    ) -> list[str]:
        """按名称和描述对 deferred 工具进行简单相关性排序。"""

        terms = [
            term
            for term in re.split(
                r"\s+",
                query.strip().lower(),
            )
            if term
        ]

        if not terms:
            return []

        scored: list[tuple[int, str]] = []

        for name in self.get_deferred_tool_names():
            tool = self._tools[name]
            lowered_name = name.lower()
            haystack = (
                f"{name} {tool.description}"
                .lower()
            )
            score = sum(
                3 if term in lowered_name else 1
                for term in terms
                if term in haystack
            )

            if score:
                scored.append((score, name))

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )
        return [
            name
            for _score, name in scored[:limit]
        ]
    
    def get_all_schemas(self)->list[dict[str, Any]]:
        return [
            tool.get_schema()
            for tool in self.list_tools()
        ]
    
    async def execute(self, name:str, arguments:dict[str, Any])->ToolResult:
        tool = self.get(name)

        if tool is None:
            return ToolResult(
                output=f"Error: unknown tool '{name}'",
                is_error = True,
            )
        
        try:
            params = tool.params_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                output=f"Parameter validation error: {exc}",
                is_error=True,
            )
        
        return await tool.execute(params)
    
def create_default_registry(
    work_dir:str | Path | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ReadFile(work_dir=work_dir)
    )
    registry.register(Glob(work_dir=work_dir))
    registry.register(Grep(work_dir=work_dir))
    registry.register(
        WriteFile(work_dir=work_dir)
    )
    registry.register(Bash(work_dir=work_dir))
    return registry


def create_worktree_registry(
    work_dir: str | Path,
) -> ToolRegistry:
    """创建只包含安全路径工具的独立 Registry。"""

    root = (
        Path(work_dir)
        .expanduser()
        .resolve()
    )

    if not root.is_dir():
        raise ValueError(
            "worktree root must be an "
            f"existing directory: {root}"
        )

    registry = ToolRegistry()
    registry.register(
        ReadFile(work_dir=root)
    )
    registry.register(
        WriteFile(work_dir=root)
    )
    registry.register(
        Glob(work_dir=root)
    )
    registry.register(
        Grep(work_dir=root)
    )

    return registry

