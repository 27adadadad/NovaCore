from __future__ import annotations

import time
import uuid

from dataclasses import dataclass, field
from typing import Literal


TraceStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
]

FinalTraceStatus = Literal[
    "completed",
    "failed",
    "cancelled",
]


@dataclass
class TraceNode:
    agent_id: str
    parent_id: str | None
    trace_id: str
    agent_type: str

    total_turns: int = 0
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    start_time: float = field(
        default_factory=time.monotonic,
    )
    end_time: float | None = None
    status: TraceStatus = "running"
    @property
    def duration_seconds(
        self,
    ) -> float | None:
        if self.end_time is None:
            return None

        return (
            self.end_time
            - self.start_time
        )

class TraceManager:
    def __init__(
        self,
    ) -> None:
        self._nodes: dict[
            str,
            TraceNode,
        ] = {}

    def create(
        self,
        agent_type: str,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> TraceNode:
        agent_id = uuid.uuid4().hex[:12]

        if trace_id is None:
            trace_id = uuid.uuid4().hex[:12]

        node = TraceNode(
            agent_id=agent_id,
            parent_id=parent_id,
            trace_id=trace_id,
            agent_type=agent_type,
        )

        self._nodes[agent_id] = node
        return node

    def get(
        self,
        agent_id: str,
    ) -> TraceNode | None:
        return self._nodes.get(
            agent_id
        )

    def get_tree(
        self,
        trace_id: str,
    ) -> list[TraceNode]:
        return [
            node
            for node in self._nodes.values()
            if node.trace_id == trace_id
        ]

    def update(
        self,
        agent_id: str,
        total_turns: int | None = None,
        tool_call_count: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        node = self._nodes.get(
            agent_id
        )

        if node is None:
            return

        if total_turns is not None:
            node.total_turns = total_turns

        if tool_call_count is not None:
            node.tool_call_count = (
                tool_call_count
            )

        if input_tokens is not None:
            node.input_tokens = input_tokens

        if output_tokens is not None:
            node.output_tokens = output_tokens

    def complete(
        self,
        agent_id: str,
        status: FinalTraceStatus = "completed",
    ) -> None:
        node = self._nodes.get(
            agent_id
        )

        if (
            node is None
            or node.end_time is not None
        ):
            return

        node.end_time = time.monotonic()
        node.status = status
