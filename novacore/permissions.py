from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from novacore.tools import Tool, ToolCategory
from novacore.path_sandbox import PathSandbox
from novacore.command_safety import DangerousCommandDetector


DecisionEffect = Literal["allow", "ask", "deny"]


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS = "bypassPermissions"

_MODE_MATRIX:dict[
    PermissionMode,
    dict[ToolCategory, DecisionEffect]
]={
    PermissionMode.DEFAULT:{
        "read":"allow",
        "write":"ask",
        "command":"ask",
    },
    PermissionMode.ACCEPT_EDITS:{
        "read":"allow",
        "write":"allow",
        "command":"ask",
    },
    PermissionMode.BYPASS:{
        "read":"allow",
        "write":"allow",
        "command":"allow",
    },
}

def mode_decide(
    mode:PermissionMode,
    category:ToolCategory,
)->DecisionEffect:
    return _MODE_MATRIX[mode][category]

@dataclass
class Decision:
    effect : DecisionEffect
    reason: str

class PermissionChecker:
    def __init__(
        self,
        detector:DangerousCommandDetector,
        sandbox:PathSandbox,
        mode: PermissionMode = PermissionMode.DEFAULT,
        enforce_sandbox: bool = False,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.mode = mode
        self.enforce_sandbox = enforce_sandbox
    
    def check(
        self,
        tool: Tool,
        arguments:dict[str, Any]
    )->Decision:
        if tool.category =="command":
            command = arguments.get("command")

            if isinstance(command, str):
                dangerous, reason = self.detector.detect(
                    command
                )

                if dangerous:
                    return Decision(
                        effect="deny",
                        reason=(
                            "Dangerous command blocked: "
                            f"{reason}"
                        ),
                    )

        if (
            tool.category in ("read", "write")
            and (
                self.enforce_sandbox
                or self.mode != PermissionMode.BYPASS
            )
        ):
            for path_key in (
                "file_path",
                "path",
            ):
                requested_path = (
                    arguments.get(path_key)
                )

                if not isinstance(
                    requested_path,
                    str,
                ):
                    continue

                allowed, reason = (
                    self.sandbox.check(
                        requested_path
                    )
                )

                if not allowed:
                    return Decision(
                        effect=(
                            "deny"
                            if self.enforce_sandbox
                            else "ask"
                        ),
                        reason=(
                            "Strict path sandbox blocked "
                            f"the request: {reason}"
                            if self.enforce_sandbox
                            else reason
                        ),
                    )
        
        effect = mode_decide(
           self.mode,
           tool.category,
        
        )

        return Decision(
            effect=effect,
            reason=(
                f"Permission mode {self.mode.value} "
                f"decided {effect}"                
            )
        )
