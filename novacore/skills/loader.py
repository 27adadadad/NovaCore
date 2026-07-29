from __future__ import annotations

import logging
from pathlib import Path

from novacore.skills.parser import (
    SkillDef,
    SkillParseError,
    parse_skill_file,
)


log = logging.getLogger(__name__)


class SkillLoader:
    def __init__(
        self,
        work_dir: str | Path,
    ) -> None:
        self.work_dir = Path(work_dir)

        self.skills_dir = (
            self.work_dir
            / ".novacore"
            / "skills"
        )

        self._skills: dict[str, SkillDef] = {}

    def load_all(
        self,
    ) -> dict[str, SkillDef]:
        loaded: dict[str, SkillDef] = {}

        if not self.skills_dir.is_dir():
            self._skills = loaded
            return loaded

        for skill_dir in sorted(
            self.skills_dir.iterdir()
        ):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"

            if not skill_file.is_file():
                continue

            try:
                skill = parse_skill_file(
                    skill_file
                )
            except SkillParseError as exc:
                log.warning(
                    "跳过无法解析的 Skill %s：%s",
                    skill_dir.name,
                    exc,
                )
                continue

            if skill.name in loaded:
                log.warning(
                    "跳过重复的 Skill：%s",
                    skill.name,
                )
                continue

            loaded[skill.name] = skill

        self._skills = loaded
        return loaded

    def get(
        self,
        name:str,
    )->SkillDef | None:
        return self._skills.get(name)

    def get_catalog(
        self,
    ) -> list[tuple[str, str]]:
        return [
            (
                name,
                self._skills[name].description,
            )
            for name in sorted(self._skills)
        ]