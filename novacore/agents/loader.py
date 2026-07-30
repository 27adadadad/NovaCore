from __future__ import annotations
from importlib import resources
from pathlib import Path

import logging

from novacore.agents.parser import (
    AgentDef,
    AgentParseError,
    parse_agent_file,
)


log = logging.getLogger(__name__)


class AgentLoader:
    def __init__(
        self,
        work_dir: str | Path,
    ) -> None:
        self.work_dir = Path(work_dir)

        self.agents_dir = (
            self.work_dir
            / ".novacore"
            / "agents"
        )

        self._agents: dict[str, AgentDef] = {}

    def _load_builtins(
        self,
    ) -> list[AgentDef]:
        definitions: list[AgentDef] = []

        try:
            package_files = resources.files(
                "novacore.agents.builtins"
            )
        except (ModuleNotFoundError, TypeError):
            log.warning(
                "无法加载内置 Agent 包"
            )
            return definitions

        for item in sorted(
            package_files.iterdir(),
            key=lambda current: current.name,
        ):
            if not item.name.endswith(".md"):
                continue

            try:
                with resources.as_file(
                    item
                ) as agent_file:
                    definition = parse_agent_file(
                        agent_file,
                        source="builtin",
                    )
            except (AgentParseError, OSError) as exc:
                log.warning(
                    "跳过无法解析的内置 Agent %s：%s",
                    item.name,
                    exc,
                )
                continue

            definition.file_path = None
            definitions.append(definition)

        return definitions

    def load_all(
        self,
    ) -> dict[str, AgentDef]:
        loaded: dict[str, AgentDef] = {}

        for definition in self._load_builtins():
            loaded[definition.agent_type] = (
                definition
            )

        if not self.agents_dir.is_dir():
            self._agents = loaded
            return loaded

        for agent_file in sorted(
            self.agents_dir.iterdir()
        ):
            if (
                not agent_file.is_file()
                or agent_file.suffix.lower() != ".md"
            ):
                continue

            try:
                definition = parse_agent_file(
                    agent_file,
                    source="project",
                )
            except AgentParseError as exc:
                log.warning(
                    "跳过无法解析的 Agent %s：%s",
                    agent_file.name,
                    exc,
                )
                continue

            existing = loaded.get(
                definition.agent_type
            )

            if (
                existing is not None
                and existing.source == "project"
            ):
                log.warning(
                    "跳过重复的项目 Agent：%s",
                    definition.agent_type,
                )
                continue

            loaded[definition.agent_type] = (
                definition
            )

        self._agents = loaded
        return loaded


    def get(
        self,
        agent_type: str,
    ) -> AgentDef | None:
        cached = self._agents.get(
            agent_type
        )

        if cached is None:
            return None

        if (
            cached.file_path is None
            or not cached.file_path.exists()
        ):
            return cached

        try:
            reloaded = parse_agent_file(
                cached.file_path,
                source=cached.source,
            )
        except AgentParseError as exc:
            log.warning(
                "重新加载 Agent %s 失败：%s",
                agent_type,
                exc,
            )
            return cached

        self._agents[agent_type] = reloaded
        return reloaded


    def list_agents(
        self,
    ) -> list[tuple[str, str]]:
        return [
            (
                agent_type,
                self._agents[
                    agent_type
                ].when_to_use,
            )
            for agent_type in sorted(
                self._agents
            )
        ]