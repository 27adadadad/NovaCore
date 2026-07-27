from __future__ import annotations
import re
import json
import random
import string
from pathlib import Path

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, IO

from novacore.conversation import Message, ToolResultBlock, ToolUseBlock
from novacore.context import(
    build_compact_messages,
)

SESSIONS_DIR = (
    Path(".novacore")
    / "sessions"
)

_SESSION_ID_PATTERN = re.compile(
    r"^session_\d{8}_\d{6}_[a-z0-9]{4}$"
)

def _is_valid_session_id(
    session_id: str,
) -> bool:
    return (
        _SESSION_ID_PATTERN.fullmatch(
            session_id
        )
        is not None
    )

def _generate_session_id() -> str:
    now = datetime.now()

    alphabet = (
        string.ascii_lowercase
        + string.digits
    )

    suffix = "".join(
        random.choices(
            alphabet,
            k=4,
        )
    )

    return (
        "session_"
        f"{now.strftime('%Y%m%d_%H%M%S')}_"
        f"{suffix}"
    )

class RecordType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    COMPACT_BOUNDARY = "compact_boundary"

@dataclass
class SessionRecord:
    type:RecordType
    content:Any
    timestamp:datetime
    tool_use_id:str | None = None
    is_error:bool = False

    def to_jsonl(self)->str:
        data:dict[str, Any]={
            "type":self.type.value,
            "content":self.content,
            "timestamp":self.timestamp.isoformat(),
        }

        if self.tool_use_id is not None:
            data["tool_use_id"] = self.tool_use_id

        if self.type == RecordType.TOOL_RESULT:
            data["is_error"] = self.is_error

        return json.dumps(
            data,
            ensure_ascii=False,
        )

    @classmethod
    def from_jsonl(
        cls,
        line:str,
    )->SessionRecord | None:
        try:
            data = json.loads(line)

            return cls(
                type=RecordType(data["type"]),
                content=data["content"],
                timestamp=datetime.fromisoformat(
                    data["timestamp"]
                ),
                tool_use_id=data.get("tool_use_id"),
                is_error=data.get(
                    "is_error",
                    False,
                ),
            )

        except(
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return None


    @classmethod
    def from_message(
        cls,
        message:Message,
    )->list[SessionRecord]:
        now = datetime.now(timezone.utc)
        records:list[SessionRecord]=[]

        if message.tool_results:
            for tool_result in message.tool_results:
                records.append(
                    cls(
                        type=RecordType.TOOL_RESULT,
                        content=tool_result.content,
                        timestamp=now,
                        tool_use_id=tool_result.tool_use_id,
                        is_error=tool_result.is_error,
                    )
                )

            return records

        if message.tool_uses:
            content_blocks: list[dict[str, Any]] = []

            if message.content:
                content_blocks.append(
                    {
                        "type":"text",
                        "text":message.content,
                    }
                )

            for tool_use in message.tool_uses:
                content_blocks.append(
                    {
                        "type":"tool_use",
                        "id":tool_use.tool_use_id,
                        "name":tool_use.tool_name,
                        "input":tool_use.arguments,
                    }
                )

            records.append(
                cls(
                    type=RecordType.ASSISTANT,
                    content=content_blocks,
                    timestamp=now,
                )
            )

            return records

        record_type = (
            RecordType.ASSISTANT
            if message.role == "assistant"
            else RecordType.USER
        )

        records.append(
            cls(
                type=record_type,
                content=message.content,
                timestamp=now
            )
        )

        return records

def _message_to_record_dicts(
    message:Message,
)->list[dict[str, Any]]:
    record_dicts:list[dict[str, Any]] = []

    records = SessionRecord.from_message(
        message
    )

    for record in records:
        data:dict[str, Any] = {
            "type":record.type.value,
            "content":record.content,
        }

        if record.tool_use_id is not None:
            data["tool_use_id"] = (
                record.tool_use_id
            )

        if record.type ==RecordType.TOOL_RESULT:
            data["is_error"] = record.is_error

        record_dicts.append(data)

    return record_dicts

def make_compact_boundary(
    summary:str,
    keep:list[Message],
)->SessionRecord:
    keep_records:list[dict[str, Any]]= []

    for message in keep:
        keep_records.extend(
            _message_to_record_dicts(
                message
            )
        )

    payload:dict[str, Any] = {
        "summary":summary,
        "keep":keep_records,
    }

    return SessionRecord(
        type=RecordType.COMPACT_BOUNDARY,
        content=payload,
        timestamp=datetime.now(timezone.utc),
    )

def parse_compact_boundary(
    record:SessionRecord,
)->tuple[str, list[Message]]:

    if record.type != RecordType.COMPACT_BOUNDARY:
        return "",[]

    content = record.content

    if not isinstance(content, dict):
        return "",[]

    summary = content.get(
        "summary",
        "",
    )

    if not isinstance(summary, str):
        summary = ""


    keep_raw = content.get(
        "keep",
        [],
    )

    if not isinstance(keep_raw, list):
        keep_raw=[]

    keep_records:list[SessionRecord] = []

    for item in keep_raw:
        if not isinstance(item, dict):
            continue

        try:
            record_type=RecordType(
                item["type"]
            )

        except(
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        tool_use_id = item.get(
            "tool_use_id"
        )

        if not isinstance(
            tool_use_id,
            (str, type(None)),
        ):
            tool_use_id = None

        keep_records.append(
            SessionRecord(
                type=record_type,
                content=item.get("content"),
                timestamp=record.timestamp,
                tool_use_id=tool_use_id,
                is_error=item.get(
                    "is_error",
                    False,
                )
            )
        )

    keep_messages=records_to_messages(
        keep_records
    )
    return summary, keep_messages

def records_to_messages(
    records: list[SessionRecord],
) -> list[Message]:
    messages: list[Message] = []
    pending_tool_results: list[ToolResultBlock] = []

    for record in records:
        if record.type == RecordType.TOOL_RESULT:
            content = (
                record.content
                if isinstance(record.content, str)
                else json.dumps(
                    record.content,
                    ensure_ascii=False,
                )
            )

            pending_tool_results.append(
                ToolResultBlock(
                    tool_use_id=record.tool_use_id or "",
                    content=content,
                    is_error=record.is_error,
                )
            )

            continue

        if pending_tool_results:
            messages.append(
                Message(
                    role="user",
                    content="",
                    tool_results=pending_tool_results,
                )
            )
            pending_tool_results = []

        if record.type == RecordType.COMPACT_BOUNDARY:
            summary, keep_messages = (
                parse_compact_boundary(
                    record
                )
            )

            if not summary and not keep_messages:
                continue

            compact_messages = (
                build_compact_messages(
                    summary,
                    has_keep_recent=bool(
                        keep_messages
                    ),
                )
            )

            messages.extend(
                compact_messages,
            )

            messages.extend(
                keep_messages
            )

            continue

        if record.type == RecordType.USER:
            content = (
                record.content
                if isinstance(record.content, str)
                else ""
            )

            messages.append(
                Message(
                    role="user",
                    content=content,
                )
            )

            continue

        if record.type == RecordType.ASSISTANT:
            if isinstance(record.content, list):
                text = ""
                tool_uses: list[ToolUseBlock] = []

                for block in record.content:
                    if not isinstance(block, dict):
                        continue

                    if block.get("type") == "text":
                        block_text = block.get(
                            "text",
                            "",
                        )

                        if isinstance(block_text, str):
                            text += block_text

                    elif block.get("type") == "tool_use":
                        arguments = block.get(
                            "input",
                            {},
                        )

                        if not isinstance(arguments, dict):
                            arguments = {}

                        tool_uses.append(
                            ToolUseBlock(
                                tool_use_id=block.get(
                                    "id",
                                    "",
                                ),
                                tool_name=block.get(
                                    "name",
                                    "",
                                ),
                                arguments=arguments,
                            )
                        )

                messages.append(
                    Message(
                        role="assistant",
                        content=text,
                        tool_uses=tool_uses,
                    )
                )

            else:
                content = (
                    record.content
                    if isinstance(record.content, str)
                    else ""
                )

                messages.append(
                    Message(
                        role="assistant",
                        content=content,
                    )
                )

    if pending_tool_results:
        messages.append(
            Message(
                role="user",
                content="",
                tool_results=pending_tool_results,
            )
        )

    return messages

class Session:
    def __init__(
        self,
        session_id:str,
        file:IO[str]
    )->None:
        self.session_id = session_id
        self._file = file

    def append(
        self,
        message:Message
    )->None:
        records = SessionRecord.from_message(
            message
        )

        for record in records:
            self._file.write(
                record.to_jsonl() + "\n"
            )

        self._file.flush()

    def append_record(
        self,
        record:SessionRecord,
    )->None:
        self._file.write(
            record.to_jsonl()+"\n"
        )

        self._file.flush()

    def close(self)->None:
        if self._file.closed:
            return

        self._file.flush()
        self._file.close()

@dataclass
class ResumeResult:
    session:Session
    messages:list[Message]

class SessionManager:
    def __init__(
        self,
        work_dir: str | Path,
    )->None:
        self._sessions_dir = (
            Path(work_dir)
            / SESSIONS_DIR
        )

        self._sessions_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


    def create(self)->Session:
        session_id = _generate_session_id()

        jsonl_path = (
            self._sessions_dir
            / f"{session_id}.jsonl"
        )

        file = jsonl_path.open(
            "a",
            encoding="utf-8",
        )


        return Session(
            session_id=session_id,
            file=file
        )

    def resume(
        self,
        session_id:str,
    )->ResumeResult | None:
        if not _is_valid_session_id(
            session_id
        ):
            return None

        jsonl_path = (
            self._sessions_dir
            / f"{session_id}.jsonl"
        )

        if not jsonl_path.exists():
            return None

        records:list[SessionRecord]=[]

        with jsonl_path.open(
            "r",
            encoding="utf-8",
        ) as read_file:
            for line in read_file:
                line = line.strip()

                if not line:
                    continue

                record = SessionRecord.from_jsonl(
                    line
                )

                if record is not None:
                    records.append(record)

        last_boundary_index:int | None = None

        for index ,record in enumerate(
            records
        ):
            if(
                record.type == RecordType.COMPACT_BOUNDARY
            ):
                last_boundary_index=index

        if last_boundary_index is not None:
            records = records[
                last_boundary_index:
            ]

        messages = records_to_messages(
            records
        )

        file = jsonl_path.open(
            "a",
            encoding="utf-8",
        )

        session = Session(
            session_id=session_id,
            file=file,
        )

        return ResumeResult(
            session=session,
            messages=messages,
        )
