from __future__ import annotations
from importlib import resources
from pathlib import Path

import logging

from novacore.agents.parser import (
    AgentDef,
    AgentParseError,
    AgentSource,
    parse_agent_file,
)


log = logging.getLogger(__name__)


class AgentLoader:
    def __init__(
        self,
        work_dir: str | Path,
        user_agents_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)

        self.agents_dir = (
            self.work_dir
            / ".novacore"
            / "agents"
        )
        self.user_agents_dir = (
            Path(user_agents_dir)
            if user_agents_dir is not None
            else Path.home() / ".novacore" / "agents"
        ).expanduser()

        self._agents: dict[str, AgentDef] = {}
        self._loaded_signature: tuple[
            tuple[str, int, int], ...
        ] = ()

    def _definition_signature(
        self,
    ) -> tuple[tuple[str, int, int], ...]:
        """记录用户级和项目级 Agent 文件的当前状态。"""

        entries: list[tuple[str, int, int]] = []

        for directory in (
            self.user_agents_dir,
            self.agents_dir,
        ):
            if not directory.is_dir():
                continue

            try:
                files = sorted(directory.iterdir())
            except OSError:
                entries.append((str(directory), -1, -1))
                continue

            for path in files:
                if (
                    not path.is_file()
                    or path.suffix.lower() != ".md"
                ):
                    continue

                try:
                    stat = path.stat()
                except OSError:
                    entries.append((str(path), -1, -1))
                    continue

                entries.append(
                    (
                        str(path),
                        stat.st_mtime_ns,
                        stat.st_size,
                    )
                )

        return tuple(entries)

    def _refresh_if_changed(self) -> None:
        """仅在定义目录变化时重建覆盖后的 Agent 清单。"""

        if self._definition_signature() != self._loaded_signature:
            self.load_all()

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

    def _load_directory(
        self,
        directory: Path,
        source: AgentSource,
    ) -> list[AgentDef]:
        """从单个目录读取 Agent，并拒绝目录内重复名称。"""

        definitions: list[AgentDef] = []
        seen: set[str] = set()

        if not directory.is_dir():
            return definitions

        try:
            files = sorted(directory.iterdir())
        except OSError as exc:
            log.warning(
                "无法读取 %s Agent 目录 %s：%s",
                source,
                directory,
                exc,
            )
            return definitions

        for agent_file in files:
            if (
                not agent_file.is_file()
                or agent_file.suffix.lower() != ".md"
            ):
                continue

            try:
                definition = parse_agent_file(
                    agent_file,
                    source=source,
                )
            except AgentParseError as exc:
                log.warning(
                    "跳过无法解析的 %s Agent %s：%s",
                    source,
                    agent_file.name,
                    exc,
                )
                continue

            if definition.agent_type in seen:
                log.warning(
                    "跳过重复的 %s Agent：%s",
                    source,
                    definition.agent_type,
                )
                continue

            seen.add(definition.agent_type)
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

        for definition in self._load_directory(
            self.user_agents_dir,
            "user",
        ):
            loaded[definition.agent_type] = (
                definition
            )

        for definition in self._load_directory(
            self.agents_dir,
            "project",
        ):
            loaded[definition.agent_type] = definition

        self._agents = loaded
        self._loaded_signature = (
            self._definition_signature()
        )
        return loaded


    def get(
        self,
        agent_type: str,
    ) -> AgentDef | None:
        self._refresh_if_changed()

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
        self._refresh_if_changed()

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
