from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novacore.conversation import Message, estimate_tokens, ConversationManager
from novacore.serialization import (
    build_chat_completion_messages,
)
from novacore.client import Client




SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_SAFETY_MARGIN = 13_000
MANUAL_COMPACT_SAFETY_MARGIN = 3_000


KEEP_RECENT_TOKENS = 10_000
MIN_KEEP_MESSAGES = 5
KEEP_MAX_TOKENS = 40_000
MIN_SUMMARIZE_PREFIX_TOKENS = 2_000

SUMMARY_PROMPT = """
Summarize the earlier conversation so another assistant
can continue the work without reading the original messages.

Return plain text only. Do not call any tools.

Preserve:
- the user's goals and explicit constraints
- important architecture and implementation decisions
- files, classes, functions, and commands involved
- completed work and verification results
- unresolved problems and the exact next step
""".strip()

@dataclass
class CompactBoundary:
    """保存生成的摘要和需要原样保留的最近消息。"""

    summary:str
    keep:list[Message]

@dataclass
class CompactEvent:
    """记录一次会话压缩的结果。"""

    before_tokens:int
    boundary:CompactBoundary | None = None

def _message_tokens(
    message:Message,
)->int:
    """估算一条内部消息的 token 数。"""

    return estimate_tokens([message])

def _compute_keep_start_index(
    messages: list[Message],
)->int:
    """计算需要原样保留的最近消息从哪里开始。"""

    message_count = len(messages)

    if message_count == 0:
        return 0

    kept_tokens = 0
    kept_count = 0
    keep_start = message_count

    for index in range(message_count-1,-1,-1):
        message_tokens = _message_tokens(
            messages[index]
        )

        if (
            kept_count > 0
            and kept_tokens + message_tokens> KEEP_MAX_TOKENS
        ):
            break

        kept_tokens += message_tokens
        kept_count += 1
        keep_start = index

        if (
            kept_tokens >= KEEP_RECENT_TOKENS
            or kept_count>=MIN_KEEP_MESSAGES
        ):
            break

    return _align_keep_start_to_tool_pair(
        messages,
        keep_start,
    )

def _align_keep_start_to_tool_pair(
    messages:list[Message],
    keep_start:int,
)->int:
    """避免把工具调用和对应的工具结果拆开。"""

    while (
        0 < keep_start <len(messages)
    ):
        message = messages[keep_start]

        if (
            message.role == "user"
            and message.tool_results
        ):
            previous = messages[keep_start - 1]

            if(
                previous.role == "assistant"
                and previous.tool_uses
            ):
                keep_start -= 1
                continue

        break

    return keep_start

def split_for_compaction(
    messages:list[Message],
)->tuple[list[Message], list[Message]]:
    """把历史切分为待摘要消息和原样保留消息。"""

    keep_start = _compute_keep_start_index(
        messages
    )

    to_summarize = messages[:keep_start]
    keep_recent = messages[keep_start:]

    return to_summarize, keep_recent


def _prefix_too_small_to_compact(
    prefix:list[Message],
)->bool:
    """判断待摘要的旧消息是否太少。"""

    if not prefix:
        return True

    return (
        estimate_tokens(prefix)
        <MIN_SUMMARIZE_PREFIX_TOKENS
    )

def compute_compact_threshold(
    context_window:int,
    manual:bool=False,
)->int:
    """计算触发压缩的 token 阈值。"""

    effective_window = (
        context_window - SUMMARY_OUTPUT_RESERVE
    )

    margin = (
        MANUAL_COMPACT_SAFETY_MARGIN
        if manual
        else AUTO_COMPACT_SAFETY_MARGIN
    )

    return effective_window - margin


def build_compact_messages(
    summary:str,
    has_keep_recent:bool,
)->list[Message]:
    """把生成的摘要包装成内部会话消息。"""

    content = (
        "This conversation continues from earlier "
        "messages that were compacted because the "
        "context window was becoming full.\n\n"
        "Earlier conversation summary:\n\n"
        f"{summary}"
    )

    if has_keep_recent:
        content += (
            "\n\nRecent messages are preserved "
            "verbatim below."
        )

    return [
        Message(
            role="user",
            content=content,
        )
    ]


def build_summary_messages(
    to_summarize:list[Message],
)->list[dict[str,Any]]:
    """构造用于生成摘要的序列化模型请求。"""

    summary_messages: list[dict[str,Any]] = [
        {
            "role":"system",
            "content":SUMMARY_PROMPT,
        }
    ]

    serialized_history = (
        build_chat_completion_messages(
            to_summarize
        )
    )

    summary_messages.extend(
        serialized_history
    )

    summary_messages.append(
        {
            "role": "user",
            "content": (
                "Produce the continuation summary now."
            ),
        }
    )

    return summary_messages

async def _generate_summary(
    client:Client,
    to_summarize:list[Message],
)->str:
    """请求模型总结选中的旧消息。"""

    summary_messages = build_summary_messages(to_summarize)

    response = await client.complete(
        summary_messages,
        tools=[]
    )

    if response.tool_calls:
        raise RuntimeError(
            "Summary model attempted to call a tool"
        )

    summary = response.text.strip()

    if not summary:
        raise RuntimeError(
            "Summary model returned empty text"
        )

    return summary


def should_auto_compact(
    current_tokens:int,
    context_window:int,
)->bool:
    """判断当前会话是否达到自动压缩阈值。"""

    threshold = compute_compact_threshold(
        context_window
    )

    return current_tokens >= threshold


async def compact_conversation(
    conversation:ConversationManager,
    client:Client,
    context_window:int,
    manual:bool = False,
)->CompactEvent | None :
    """把旧历史压缩成摘要，同时原样保留最近消息。"""

    before_tokens = conversation.current_tokens()

    if (
        not manual
        and not should_auto_compact(
            before_tokens,
            context_window,
        )
    ):
        return None

    to_summarize, keep_recent = split_for_compaction(
        conversation.get_messages()
    )

    if _prefix_too_small_to_compact(to_summarize):
        return None

    summary = await _generate_summary(
        client,
        to_summarize,
    )

    new_messages = build_compact_messages(
        summary,
        has_keep_recent=bool(keep_recent)
    )

    new_messages.extend(keep_recent)

    conversation.replace_history(
        new_messages
    )

    boundary = CompactBoundary(
        summary=summary,
        keep=list(keep_recent)
    )

    return CompactEvent(
        before_tokens=before_tokens,
        boundary=boundary,
    )
