from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    api_key:str
    base_url:str
    model:str
    context_window:int


@dataclass(frozen=True)
class AutoMemorySettings:
    enabled: bool = False
    max_candidates: int = 3


def load_auto_memory_settings() -> AutoMemorySettings:
    raw_enabled = os.getenv("AUTO_MEMORY_ENABLED", "false").strip().lower()
    if raw_enabled not in {"true", "false"}:
        raise RuntimeError("AUTO_MEMORY_ENABLED must be true or false")

    try:
        max_candidates = int(
            os.getenv("AUTO_MEMORY_MAX_CANDIDATES", "3")
        )
    except ValueError as exc:
        raise RuntimeError(
            "AUTO_MEMORY_MAX_CANDIDATES must be an integer"
        ) from exc

    if not 1 <= max_candidates <= 3:
        raise RuntimeError(
            "AUTO_MEMORY_MAX_CANDIDATES must be between 1 and 3"
        )

    return AutoMemorySettings(
        enabled=raw_enabled == "true",
        max_candidates=max_candidates,
    )


def load_config()->Config:
    api_key = os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Environment variable DASHSCOPE_API_KEY is required"
        )
    
    return Config(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        context_window=128_000,
    )
