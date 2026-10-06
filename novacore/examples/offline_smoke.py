"""Exercise the real tool loop and session recovery without a model or API key."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novacore.agent import Agent
from novacore.client import FakeClient
from novacore.command_safety import DangerousCommandDetector
from novacore.conversation import ConversationManager
from novacore.path_sandbox import PathSandbox
from novacore.permissions import PermissionChecker
from novacore.session import SessionManager
from novacore.tools import ReadFile, ToolRegistry


async def run_smoke() -> dict:
    with TemporaryDirectory(prefix="novacore-offline-") as directory:
        root = Path(directory)
        (root / "sample.txt").write_text(
            "NovaCore offline sample\n", encoding="utf-8"
        )
        registry = ToolRegistry()
        registry.register(ReadFile(work_dir=root))
        client = FakeClient(
            tool_name="ReadFile",
            tool_arguments={"file_path": "sample.txt"},
            final_text="Offline tool loop completed.",
        )
        manager = SessionManager(root)
        session = manager.create()
        conversation = ConversationManager(on_message=session.append)
        try:
            answer = await Agent(
                client=client,
                registry=registry,
                context_window=100_000,
                permission_checker=PermissionChecker(
                    detector=DangerousCommandDetector(),
                    sandbox=PathSandbox(root),
                ),
            ).run_to_completion("Read the temporary sample.", conversation)
        finally:
            session.close()

        resumed = manager.resume(session.session_id)
        if resumed is None:
            raise RuntimeError("offline session could not be resumed")
        try:
            uses = [use for message in resumed.messages for use in message.tool_uses]
            results = [
                result
                for message in resumed.messages
                for result in message.tool_results
            ]
            paired = (
                len(uses) == len(results) == 1
                and uses[0].tool_use_id == results[0].tool_use_id
                and not results[0].is_error
            )
            if not paired or "NovaCore offline sample" not in results[0].content:
                raise RuntimeError("offline tool execution or result pairing failed")
            return {
                "mode": "offline-fake-client",
                "model_calls": client.calls,
                "tool_name": uses[0].tool_name,
                "tool_output": results[0].content,
                "final_answer": answer,
                "session_restored": resumed.messages[-1].content == answer,
                "call_result_pair_preserved": paired,
            }
        finally:
            resumed.session.close()


def main() -> None:
    print(json.dumps(asyncio.run(run_smoke()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
