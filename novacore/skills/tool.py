from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any
from novacore.skills.loader import SkillLoader
from novacore.tools import ToolCategory, ToolResult


class LoadSkillParams(BaseModel):
    name: str = Field(
        description="需要加载的 Skill 名称"
    )


class LoadSkill:
    name = "LoadSkill"

    description = (
        "按名称加载一个 Skill，"
        "并返回它的完整指令正文"
    )

    category: ToolCategory = "read"
    params_model = LoadSkillParams

    def __init__(
        self,
        loader: SkillLoader,
    ) -> None:
        self.loader = loader

    def get_schema(
        self,
    ) -> dict[str, Any]:
        parameters = (
            self.params_model.model_json_schema()
        )

        parameters.pop("title", None)

        catalog = self.loader.get_catalog()

        description_lines = [
            self.description,
        ]

        if catalog:
            description_lines.extend(
                [
                    "",
                    "可用 Skills：",
                ]
            )

            for name, description in catalog:
                description_lines.append(
                    f"- {name}: {description}"
                )

        full_description = "\n".join(
            description_lines
        )

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": full_description,
                "parameters": parameters,
            },
        }

    async def execute(
        self,
        params: LoadSkillParams,
    ) -> ToolResult:
        skill = self.loader.get(
            params.name
        )

        if skill is None:
            available = ", ".join(
                name
                for name, _description
                in self.loader.get_catalog()
            )

            if not available:
                available = "无可用 Skill"

            return ToolResult(
                output=(
                    f"找不到 Skill：{params.name}。"
                    f"可用 Skill：{available}"
                ),
                is_error=True,
            )

        return ToolResult(
            output=(
                f"# Skill: {skill.name}\n\n"
                f"{skill.prompt_body}"
            )
        )