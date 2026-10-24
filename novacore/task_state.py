"""Small runtime-owned task facts, separate from model claims and long-term memory."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

TASK_STATE_PREFIX = "[novacore-task-state]\n"
MAX_IDENTICAL_FAILURES = 3
_PHASES = {"running", "response_returned", "iteration_limit", "cancelled", "error"}
_VALIDATION = {"not_applicable", "passed", "failed", "skipped", "checker_error"}


@dataclass
class TaskState:
    revision: int = 0
    goal: str = ""
    phase: str = "running"
    attempts: int = 0
    last_tool: str = ""
    last_tool_id: str = ""
    last_operation: str = "none"
    last_validation: str = "not_applicable"
    signature: str = ""
    identical_failures: int = 0

    @classmethod
    def from_payload(cls, payload: Any) -> TaskState | None:
        if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload.get("schema") != 1:
            return None
        fields = {key: payload.get(key) for key in cls.__dataclass_fields__}
        for key in ("revision", "attempts", "identical_failures"):
            if type(fields[key]) is not int or not 0 <= fields[key] <= 1_000_000:
                return None
        for key, limit in (("goal", 800), ("last_tool", 64), ("last_tool_id", 128), ("signature", 64)):
            if not isinstance(fields[key], str) or len(fields[key]) > limit:
                return None
        if any(not isinstance(fields[key], str) for key in ("phase", "last_validation", "last_operation")):
            return None
        if (fields["phase"] not in _PHASES or fields["last_validation"] not in _VALIDATION
                or fields["last_operation"] not in {"none", "succeeded", "failed"}):
            return None
        return cls(**fields)

    def begin(self, prompt: str) -> None:
        if not self.goal or prompt.strip().lower() not in {"continue", "resume", "继续", "接着做"}:
            revision = self.revision
            self.__dict__.update(TaskState(revision=revision, goal=prompt[:800]).__dict__)
        self.phase = "running"

    @staticmethod
    def fingerprint(name: str, arguments: dict) -> str:
        data = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def blocks(self, name: str, arguments: dict) -> bool:
        return (self.identical_failures >= MAX_IDENTICAL_FAILURES
                and self.signature == self.fingerprint(name, arguments))

    def observe(self, tool_id: str, name: str, arguments: dict, output: str, is_error: bool) -> None:
        signature = self.fingerprint(name, arguments)
        validation = "not_applicable"
        if name == "WriteFile" and not is_error:
            try:
                data = json.loads(output)
                value = data.get("validation", {}).get("status")
                if data.get("write_status") == "saved" and value in _VALIDATION:
                    validation = value
            except (ValueError, TypeError, AttributeError):
                pass
        failed = is_error or validation in {"failed", "checker_error"}
        self.identical_failures = (
            min(self.identical_failures + 1, 1_000_000) if failed and signature == self.signature
            else 1 if failed else 0
        )
        self.signature = signature
        self.attempts = min(self.attempts + 1, 1_000_000)
        self.last_tool = name[:64]
        self.last_tool_id = tool_id[:128]
        self.last_operation = "failed" if is_error else "succeeded"
        self.last_validation = validation

    def payload(self) -> dict:
        if self.phase == "response_returned":
            next_action = "Answer returned; task correctness is not independently verified."
        elif self.identical_failures >= MAX_IDENTICAL_FAILURES:
            next_action = "Do not repeat the identical failed operation; change approach or ask the user."
        elif self.last_validation == "failed":
            next_action = "Inspect tool diagnostics, repair the file and revalidate before claiming correctness."
        elif self.last_validation == "checker_error":
            next_action = "Resolve checker availability; do not claim validation passed."
        else:
            next_action = "Continue the task; tool success alone does not establish task completion."
        return {"schema": 1, **asdict(self), "next_action": next_action,
                "note": "Runtime context, not a new user request. Only the newest snapshot is current."}


def render_task_state(payload: dict) -> str:
    return TASK_STATE_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)
