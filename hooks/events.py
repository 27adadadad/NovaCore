from __future__ import annotations

from enum import StrEnum


class HookEvent(StrEnum):
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"