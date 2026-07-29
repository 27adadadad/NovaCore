from __future__ import annotations

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

    def load_all(
        self,
    ) -> dict[str, AgentDef]:
        loaded: dict[str, AgentDef] = {}

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
                    agent_file
                )
            except AgentParseError as exc:
                log.warning(
                    "跳过无法解析的 Agent %s：%s",
                    agent_file.name,
                    exc,
                )
                continue

            if definition.agent_type in loaded:
                log.warning(
                    "跳过重复的 Agent：%s",
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
        return self._agents.get(
            agent_type
        )


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