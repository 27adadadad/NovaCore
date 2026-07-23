from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Literal

from pydantic import BaseModel, Field, ValidationError

import asyncio

ToolCategory = Literal["read", "write", "command"]
MAX_COMMAND_TIMEOUT=600

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
        path = Path(params.file_path)

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
    
class WriteFile:
    name = "WriteFile"
    description = (
        "Write content to a file, creating parent "
        "directories if needed. Overwrites existing files."
    )
    category:ToolCategory = "write"
    params_model = WriteFileParams

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
        path = Path(params.file_path)
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

    def register(self, tool:Tool)->None:
        self._tools[tool.name]=tool

    def get(self, name:str)-> Tool | None:
        return self._tools.get(name)
    
    def get_all_schemas(self)->list[dict[str, Any]]:
        return [tool.get_schema() for tool in self._tools.values()]
    
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
    registry.register(ReadFile())
    registry.register(WriteFile())
    registry.register(Bash(work_dir=work_dir))
    return registry

