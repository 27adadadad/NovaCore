from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    api_key:str
    base_url:str
    model:str
    context_window:int


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