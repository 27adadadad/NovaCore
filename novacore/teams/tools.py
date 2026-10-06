from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from novacore.teams.coordinator import (
    Coordinator,
)
from novacore.tools import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
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


class EmptyParams(BaseModel):
    pass


class TeamCreateParams(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="Human-readable team name",
    )


class TeammateAddParams(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="Human-readable teammate name",
    )
    agent_type: str = Field(
        min_length=1,
        description="Predefined Agent type to run",
    )


class TeamTaskCreateParams(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short task title",
    )
    description: str = Field(
        default="",
        max_length=8_000,
        description="Complete instructions for the teammate",
    )


class TeamTaskAssignParams(BaseModel):
    task_id: str = Field(description="Shared task ID")
    teammate_id: str = Field(description="Target teammate ID")


class TeamTaskIdParams(BaseModel):
    task_id: str = Field(description="Shared task ID")


class _TeamTool:
    category: ToolCategory = "command"

    def __init__(self, coordinator: Coordinator) -> None:
        self.coordinator = coordinator

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name,
            self.description,
            self.params_model,
        )

    def _error(self, exc: Exception) -> ToolResult:
        return ToolResult(
            output=(
                f"{self.name} failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            is_error=True,
        )


class TeamCreate(_TeamTool):
    name = "TeamCreate"
    description = "Create a persistent in-process Agent team."
    params_model = TeamCreateParams

    async def execute(
        self,
        params: TeamCreateParams,
    ) -> ToolResult:
        try:
            team = await self.coordinator.create_team(
                params.name
            )
        except Exception as exc:
            return self._error(exc)

        return ToolResult(
            output=(
                f"Created team {team.name} "
                f"with ID {team.team_id}"
            )
        )


class TeammateAdd(_TeamTool):
    name = "TeammateAdd"
    description = (
        "Add a predefined Agent teammate with its own Git Worktree."
    )
    params_model = TeammateAddParams

    async def execute(
        self,
        params: TeammateAddParams,
    ) -> ToolResult:
        try:
            teammate = await self.coordinator.add_teammate(
                params.name,
                params.agent_type,
            )
        except Exception as exc:
            return self._error(exc)

        return ToolResult(
            output=(
                f"Added teammate {teammate.name} "
                f"with ID {teammate.teammate_id}; "
                f"worktree={teammate.worktree.path}"
            )
        )


class TeamTaskCreate(_TeamTool):
    name = "TeamTaskCreate"
    description = "Create a persistent shared task for the team."
    params_model = TeamTaskCreateParams

    async def execute(
        self,
        params: TeamTaskCreateParams,
    ) -> ToolResult:
        try:
            task = await self.coordinator.create_task(
                params.title,
                params.description,
            )
        except Exception as exc:
            return self._error(exc)

        return ToolResult(
            output=(
                f"Created shared task {task.task_id}: "
                f"{task.title}"
            )
        )


class TeamTaskAssign(_TeamTool):
    name = "TeamTaskAssign"
    description = "Assign one pending shared task to an idle teammate."
    params_model = TeamTaskAssignParams

    async def execute(
        self,
        params: TeamTaskAssignParams,
    ) -> ToolResult:
        try:
            task = await self.coordinator.assign_task(
                params.task_id,
                params.teammate_id,
            )
        except Exception as exc:
            return self._error(exc)

        return ToolResult(
            output=(
                f"Assigned {task.task_id} to "
                f"{task.assignee_id}"
            )
        )


class TeamTaskStart(_TeamTool):
    name = "TeamTaskStart"
    description = "Start one assigned team task in the background."
    params_model = TeamTaskIdParams

    async def execute(
        self,
        params: TeamTaskIdParams,
    ) -> ToolResult:
        try:
            background_id = await self.coordinator.start_task(
                params.task_id
            )
        except Exception as exc:
            return self._error(exc)

        return ToolResult(
            output=(
                f"Started shared task {params.task_id}; "
                f"background ID {background_id}"
            )
        )


class TeamStatusTool(_TeamTool):
    name = "TeamStatus"
    description = "Show the current team, teammates, and shared tasks."
    category: ToolCategory = "read"
    params_model = EmptyParams

    async def execute(
        self,
        _params: EmptyParams,
    ) -> ToolResult:
        team = self.coordinator.team

        if team is None:
            return ToolResult(output="No team is loaded")

        lines = [
            f"Team {team.name} [{team.team_id}] - {team.status.value}",
            "Teammates:",
        ]
        teammates = self.coordinator.list_teammates()
        lines.extend(
            (
                f"- {item.name} [{item.teammate_id}] "
                f"{item.status.value} task={item.current_task_id or '-'}"
            )
            for item in teammates
        )
        lines.append("Tasks:")
        lines.extend(
            (
                f"- {item.title} [{item.task_id}] "
                f"{item.status.value} assignee={item.assignee_id or '-'}"
            )
            for item in self.coordinator.list_tasks()
        )

        if not teammates:
            lines.insert(2, "- (none)")

        if not self.coordinator.list_tasks():
            lines.append("- (none)")

        return ToolResult(output="\n".join(lines))


class TeamTaskCancel(_TeamTool):
    name = "TeamTaskCancel"
    description = "Cancel one currently running team task."
    params_model = TeamTaskIdParams

    async def execute(
        self,
        params: TeamTaskIdParams,
    ) -> ToolResult:
        try:
            cancelled = await self.coordinator.cancel_task(
                params.task_id
            )
        except Exception as exc:
            return self._error(exc)

        if not cancelled:
            return ToolResult(
                output=(
                    f"Could not cancel shared task "
                    f"{params.task_id}"
                ),
                is_error=True,
            )

        return ToolResult(
            output=f"Cancelled shared task {params.task_id}"
        )


class TeamClose(_TeamTool):
    name = "TeamClose"
    description = (
        "Close the current team and safely clean unchanged Worktrees."
    )
    params_model = EmptyParams

    async def execute(
        self,
        _params: EmptyParams,
    ) -> ToolResult:
        try:
            results = await self.coordinator.close_team()
        except Exception as exc:
            return self._error(exc)

        lines = ["Team closed"]
        lines.extend(
            (
                f"- {item.worktree.path}: {item.reason}"
            )
            for item in results
        )
        return ToolResult(output="\n".join(lines))


TEAM_TOOL_TYPES = (
    TeamCreate,
    TeammateAdd,
    TeamTaskCreate,
    TeamTaskAssign,
    TeamTaskStart,
    TeamStatusTool,
    TeamTaskCancel,
    TeamClose,
)


def register_team_tools(
    registry: ToolRegistry,
    coordinator: Coordinator,
    deferred: bool = True,
) -> tuple[str, ...]:
    """把 Teams 管理工具注册到同一个 Registry。"""

    names: list[str] = []

    for tool_type in TEAM_TOOL_TYPES:
        tool = tool_type(coordinator)
        registry.register(
            tool,
            deferred=deferred,
        )
        names.append(tool.name)

    return tuple(names)
