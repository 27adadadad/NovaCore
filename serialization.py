from __future__ import annotations

import json
from typing import Any

from novacore.conversation import Message

def build_chat_completion_messages(messages:list[Message])->list[dict[str, Any]]:
    result:list[dict[str, Any]]=[]

    for message in messages:
        if message.tool_uses:
            tool_calls = []

            for tool_use in message.tool_uses:
                tool_calls.append(
                    {
                        "id":tool_use.tool_use_id,
                        "type":"function",
                        "function":{
                            "name":tool_use.tool_name,
                            "arguments":json.dumps(tool_use.arguments),
                        },
                    }
                )

            result.append(
                {
                    "role":"assistant",
                    "content":message.content,
                    "tool_calls":tool_calls,
                }
            )

        elif message.tool_results:
            for tool_result in message.tool_results:
                result.append(
                    {
                        "role":"tool",
                        "tool_call_id":tool_result.tool_use_id,
                        "content":tool_result.content,
                    }
                )

        else:
            result.append(
                {
                    "role":message.role,
                    "content":message.content,
                }
            )

    return result
