from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from novacore.skills.parser import (
    SkillDef,
    SkillParseError,
    SkillSource,
    parse_skill_file,
)


log = logging.getLogger(__name__)


class SkillLoader:
    def __init__(
        self,
        work_dir: str | Path,
        user_skills_dir: str | Path | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)

        self.skills_dir = (
            self.work_dir
            / ".novacore"
            / "skills"
        )
        self.user_skills_dir = (
            Path(user_skills_dir)
            if user_skills_dir is not None
            else Path.home() / ".novacore" / "skills"
        ).expanduser()

        self._skills: dict[str, SkillDef] = {}
        self._loaded_signature: tuple[
            tuple[str, int, int], ...
        ] = ()

    def _definition_signature(
        self,
    ) -> tuple[tuple[str, int, int], ...]:
        """记录用户级和项目级 SKILL.md 的当前状态。"""

        entries: list[tuple[str, int, int]] = []

        for directory in (
            self.user_skills_dir,
            self.skills_dir,
        ):
            if not directory.is_dir():
                continue

            try:
                children = sorted(directory.iterdir())
            except OSError:
                entries.append((str(directory), -1, -1))
                continue

            for child in children:
                skill_file = child / "SKILL.md"

                if not child.is_dir() or not skill_file.is_file():
                    continue

                try:
                    stat = skill_file.stat()
                except OSError:
                    entries.append((str(skill_file), -1, -1))
                    continue

                entries.append(
                    (
                        str(skill_file),
                        stat.st_mtime_ns,
                        stat.st_size,
                    )
                )

        return tuple(entries)

    def _refresh_if_changed(self) -> None:
        """仅在定义目录变化时重建覆盖后的 Skill 清单。"""

        if self._definition_signature() != self._loaded_signature:
            self.load_all()

    def _load_directory(
        self,
        directory: Path,
        source: SkillSource,
    ) -> list[SkillDef]:
        """读取一个 Skill 目录层级。"""

        loaded: list[SkillDef] = []
        seen: set[str] = set()

        if not directory.is_dir():
            return loaded

        try:
            children = sorted(directory.iterdir())
        except OSError as exc:
            log.warning(
                "无法读取 %s Skill 目录 %s：%s",
                source,
                directory,
                exc,
            )
            return loaded

        for skill_dir in children:
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"

            if not skill_file.is_file():
                continue

            try:
                skill = parse_skill_file(
                    skill_file,
                    source=source,
                )
            except SkillParseError as exc:
                log.warning(
                    "跳过无法解析的 %s Skill %s：%s",
                    source,
                    skill_dir.name,
                    exc,
                )
                continue

            if skill.name in seen:
                log.warning(
                    "跳过重复的 %s Skill：%s",
                    source,
                    skill.name,
                )
                continue

            seen.add(skill.name)
            loaded.append(skill)

        return loaded

    def _load_builtins(self) -> list[SkillDef]:
        """读取可选的包内置 Skills。"""

        try:
            package_files = resources.files(
                "novacore.skills.builtins"
            )
        except (ModuleNotFoundError, TypeError):
            return []

        definitions: list[SkillDef] = []

        for item in sorted(
            package_files.iterdir(),
            key=lambda current: current.name,
        ):
            skill_file = item / "SKILL.md"

            if not skill_file.is_file():
                continue

            try:
                with resources.as_file(
                    skill_file
                ) as path:
                    definitions.append(
                        parse_skill_file(
                            path,
                            source="builtin",
                        )
                    )
            except (SkillParseError, OSError) as exc:
                log.warning(
                    "跳过无法解析的内置 Skill %s：%s",
                    item.name,
                    exc,
                )

        return definitions

    def load_all(
        self,
    ) -> dict[str, SkillDef]:
        loaded: dict[str, SkillDef] = {}

        for skill in self._load_builtins():
            loaded[skill.name] = skill

        for skill in self._load_directory(
            self.user_skills_dir,
            "user",
        ):
            loaded[skill.name] = skill

        for skill in self._load_directory(
            self.skills_dir,
            "project",
        ):
            loaded[skill.name] = skill

        self._skills = loaded
        self._loaded_signature = (
            self._definition_signature()
        )
        return loaded

    def get(
        self,
        name:str,
    )->SkillDef | None:
        self._refresh_if_changed()

        cached = self._skills.get(name)

        if cached is None:
            return None

        if not cached.source_path.exists():
            return cached

        try:
            reloaded = parse_skill_file(
                cached.source_path,
                source=cached.source,
            )
        except SkillParseError as exc:
            log.warning(
                "重新加载 Skill %s 失败：%s",
                name,
                exc,
            )
            return cached

        self._skills[name] = reloaded
        return reloaded

    def get_catalog(
        self,
    ) -> list[tuple[str, str]]:
        self._refresh_if_changed()

        return [
            (
                name,
                self._skills[name].description,
            )
            for name in sorted(self._skills)
        ]
