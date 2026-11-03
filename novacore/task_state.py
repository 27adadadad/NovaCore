"""Small runtime-owned task facts, separate from model claims and long-term memory."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any

TASK_STATE_PREFIX = "[novacore-task-state]\n"
MAX_IDENTICAL_FAILURES = 3
MAX_COUNTED_TOOLS = 128
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
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
    tool_counts: dict[str, int] = field(default_factory=dict)
    tool_counts_complete: bool = True

    @classmethod
    def from_payload(cls, payload: Any) -> TaskState | None:
        if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload.get("schema") != 1:
            return None
        fields = {key: payload.get(key) for key in cls.__dataclass_fields__}
        counts = payload.get("tool_counts", {})
        if not isinstance(counts, dict) or len(counts) > MAX_COUNTED_TOOLS:
            return None
        for name, count in counts.items():
            if (not isinstance(name, str) or not _TOOL_NAME.fullmatch(name)
                    or type(count) is not int or not 1 <= count <= 1_000_000):
                return None
        fields["tool_counts"] = dict(counts)
        # Older snapshots have no per-tool history. Do not infer a distribution
        # from their aggregate attempts or silently label it complete.
        fields["tool_counts_complete"] = payload.get(
            "tool_counts_complete", "tool_counts" in payload or payload.get("attempts") == 0)
        if type(fields["tool_counts_complete"]) is not bool:
            return None
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
        if _TOOL_NAME.fullmatch(name) and (name in self.tool_counts or len(self.tool_counts) < MAX_COUNTED_TOOLS):
            count = self.tool_counts.get(name, 0)
            self.tool_counts[name] = min(count + 1, 1_000_000)
            if count == 1_000_000:
                self.tool_counts_complete = False
        else:
            self.tool_counts_complete = False
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
            next_action = (
                "Use the existing evidence and the user's acceptance criteria to decide whether work remains. "
                "When requirements are satisfied, return the final answer without extra completion artifacts."
            )
        count = self.tool_counts.get(self.last_tool)
        label = (f"Tool call #{count} for '{self.last_tool}' (observed task attempts)"
                 if count is not None else None)
        return {"schema": 1, **asdict(self), "next_action": next_action,
                "counter_scope": "handled_task_attempts", "tool_call_label": label,
                "note": (
                    "Read-only runtime context, not a new user request. Only the newest snapshot is current. "
                    "This snapshot does not request file writes or additional verification beyond the user's task."
                )}


def render_task_state(payload: dict) -> str:
    return TASK_STATE_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)
