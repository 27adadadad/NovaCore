from __future__ import annotations
import yaml
import re

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class SkillParseError(Exception):
    """Skill 文件格式不正确。"""

VALID_SKILL_NAME = re.compile(
    r"^[a-z][a-z0-9-]*$"
)

SkillSource = Literal[
    "builtin",
    "user",
    "project",
]


@dataclass
class SkillDef:
    name: str
    description: str
    prompt_body: str
    source_path: Path
    source: SkillSource = "project"

def parse_frontmatter(
    raw: str,
) -> tuple[dict[str, object], str]:
    stripped = raw.lstrip()

    if not stripped.startswith("---"):
        raise SkillParseError(
            "Skill 文件必须以 --- 开始"
        )

    end = stripped.find("---", 3)

    if end == -1:
        raise SkillParseError(
            "没有找到 YAML 的结束标记 ---"
        )

    yaml_block = stripped[3:end]
    body = stripped[end + 3:].lstrip("\n")

    try:
        metadata = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        raise SkillParseError(
            f"YAML 格式错误：{exc}"
        ) from exc

    if not isinstance(metadata, dict):
        raise SkillParseError(
            "YAML 必须是键值对结构"
        )

    return metadata, body


def validate_metadata(
    metadata: dict[str, object],
) -> tuple[str, str]:
    name = metadata.get("name")

    if not isinstance(name, str):
        raise SkillParseError(
            "name 必须是字符串"
        )

    name = name.strip()

    if not VALID_SKILL_NAME.fullmatch(name):
        raise SkillParseError(
            "name 必须以小写字母开头，"
            "并且只能包含小写字母、数字和连字符"
        )

    description = metadata.get("description")

    if not isinstance(description, str):
        raise SkillParseError(
            "description 必须是字符串"
        )

    description = description.strip()

    if not description:
        raise SkillParseError(
            "description 不能为空"
        )

    return name, description

def parse_skill_file(
    path: Path,
    source: SkillSource = "project",
) -> SkillDef:
    try:
        raw = path.read_text(
            encoding="utf-8",
        )
    except OSError as exc:
        raise SkillParseError(
            f"无法读取 Skill 文件：{path}"
        ) from exc

    metadata, body = parse_frontmatter(raw)

    name, description = validate_metadata(
        metadata
    )

    return SkillDef(
        name=name,
        description=description,
        prompt_body=body,
        source_path=path,
        source=source,
    )
