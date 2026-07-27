from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import (
    Horizontal,
    Vertical,
    VerticalScroll,
)
from textual.widgets import Input, Static, Button

from novacore.agent import (
    Agent,
    ErrorEvent,
    PermissionRequest,
    PermissionResponse,
    StreamText,
    ToolResultEvent,
    ToolUseEvent,
    CompactNotification,
)

from novacore.conversation import ConversationManager
from novacore.session import Session, make_compact_boundary
from novacore.commands import (
    CommandContext,
    CommandInvocation,
    CommandRegistry,
    parse_command,
)
from novacore.context import (
    compact_conversation,
)

import asyncio

class NovaCoreApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #chat {
        height: 1fr;
        padding: 1;
    }

    #prompt {
        dock: bottom;
    }

    .user-message {
        color:cyan;
        margin-bottom:1;
    }

    .system-message {
        color: $text-muted;
        margin-bottom: 1;
    }

    .assistant-message {
        margin-bottom: 1;
    }

    .tool-message {
        color: $warning;
        margin-bottom: 1;
    }

    .tool-result {
        color: $success;
        margin-bottom: 1;
    }

    .permission-panel {
        height:auto;
        border: solid $warning;
        padding:1;
        margin-bottom:1;
    }

    .permission-actions {
        height:auto;
        margin-top:1;
    }

    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        agent:Agent,
        conversation:ConversationManager,
        session:Session,
    )->None:
        super().__init__()
        self.agent=agent
        self.conversation = conversation
        self.session = session
        self.command_registry = CommandRegistry()

        self.command_context=CommandContext(
            conversation=self.conversation,
            session_id=self.session.session_id,
            compact=self._compact_context,
        )

        self._active_task:asyncio.Task[None] | None = None
        self._pending_permission: PermissionRequest | None = None
        self._permission_panel:Vertical | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat"):
            yield Static(
                "NovaCore is ready",
                classes = "system-message",
            )

        yield Input(
            placeholder="Enter a prompt",
            id="prompt",
        )

    async def on_input_submitted(
        self,
        event:Input.Submitted,
    )->None:
        prompt = event.value.strip()

        if not prompt:
            return
        
        if(
            self._active_task is not None
            and not self._active_task.done()
        ):
            return 
        
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.value = ""

        chat = self.query_one(
            "#chat",
            VerticalScroll,
        )

        await chat.mount(
            Static(
                f"You: {prompt}",
                classes="user-message",
                markup=False,
            )
        )

        chat.scroll_end(animate=False)

        try:
            invocation = parse_command(
                prompt
            )
        except ValueError as exc:
            await chat.mount(
                Static(
                    f"[Command error] {exc}",
                    classes="system-message",
                    markup=False,
                )
            )
            chat.scroll_end(animate=False)
            return

        if invocation is not None:
            prompt_input.disabled=True

            self._active_task = asyncio.create_task(
                self._run_command(
                    invocation
                )
            )

            return

        prompt_input.disabled = True

        self._active_task = asyncio.create_task(
            self._run_agent(prompt)
        )

    async def on_button_pressed(
        self, 
        event: Button.Pressed,
    )->None:
        request = self._pending_permission

        if request is None:
            return

        if event.button.id == "permission-allow":
            response = PermissionResponse.ALLOW
        elif event.button.id == "permission-deny":
            response = PermissionResponse.DENY
        else:
            return

        panel = self._permission_panel

        self._pending_permission = None
        self._permission_panel = None

        if panel is not None:
            await panel.remove()

        if not request.future.done():
            request.future.set_result(response)

    async def _compact_context(
        self,
    )->str:
        compact_event = await compact_conversation(
            self.conversation,
            self.agent.client,
            self.agent.context_window,
            manual=True,
        )

        if (
            compact_event is None
            or compact_event.boundary is None
        ):
            return(
                "Context is too small "
                "to compact"
            )

        boundary = compact_event.boundary

        record = make_compact_boundary(
            boundary.summary,
            boundary.keep,
        )

        self.session.append_record(record)

        return (
            "Context compacted "
            f"({compact_event.before_tokens:,} "
            "tokens before compaction)"
        )

    async def _run_command(
        self,
        invocation:CommandInvocation,
    )->None:
        chat = self.query_one(
            "#chat",
            VerticalScroll,
        )
        prompt_input = self.query_one(
            "#prompt",
            Input,
        )
        try:
            result = await (
                self.command_registry.execute(
                    self.command_context,
                    invocation
                )
            )

            label = (
                "Command error"
                if result.is_error
                else "Command"
            )

            await chat.mount(
                Static(
                    f"[{label}] {result.content}",
                    classes="system-message",
                    markup=False,
                )
            )

        except Exception as exc:
            await chat.mount(
                Static(
                    f"[Command error] {exc}",
                    classes="system-message",
                    markup=False,
                )
            )

        finally:
            prompt_input.disabled = False
            prompt_input.focus()

            self._active_task = None
            chat.scroll_end(animate=False)

    async def _run_agent(
        self,
        prompt:str,
    )->None:
        chat = self.query_one(
            "#chat",
            VerticalScroll,
        )

        prompt_input = self.query_one(
            "#prompt",
            Input,
        )

        assistant_message = Static(
            "Assistant: ",
            classes="assistant-message",
            markup=False,
        )

        await chat.mount(assistant_message)

        text_parts: list[str] = []

        try:
            async for event in (
                self.agent.stream_to_completion(
                    prompt,
                    conversation=self.conversation,
                )
            ):
                if isinstance(event, StreamText):
                    text_parts.append(event.text)
                    full_text = "".join(text_parts)

                    assistant_message.update(
                        f"Assistant: {full_text}"
                    )

                    chat.scroll_end(
                        animate=False
                    )

                elif isinstance(
                    event,
                    CompactNotification,
                ):
                    if event.boundary is not None:
                        record = make_compact_boundary(
                            event.boundary.summary,
                            event.boundary.keep,
                        )
                        self.session.append_record(record)

                    await chat.mount(
                        Static(
                            f"[Context] {event.message}",
                            classes="system-message",
                            markup=False,
                        ),
                        before=assistant_message,
                    )
                    chat.scroll_end(
                        animate=False
                    )

                elif isinstance(event, ToolUseEvent):
                    await chat.mount(
                        Static(
                            (
                                f"[Tool] calling {event.tool_name}\n"
                                f"id: {event.tool_id}\n"
                                f"arguments: {event.arguments}"
                            ),
                            classes="tool-message",
                            markup=False,
                        )
                    )

                    chat.scroll_end(animate=False)

                elif isinstance(
                    event,
                    PermissionRequest,
                ):
                    self._pending_permission = event

                    permission_panel = Vertical(
                        Static(
                            (
                                f"Permission required\n"
                                f"{event.description}\n"
                                f"Reason: {event.reason}"
                            ),
                            markup=False,
                        ),
                        Horizontal(
                            Button(
                                "Allow",
                                id="permission-allow",
                                variant="success",
                            ),
                            Button(
                                "Deny",
                                id="permission-deny",
                                variant="error"
                            ),
                            classes="permission-actions",
                        ),
                        classes="permission-panel"
                    )

                    self._permission_panel = permission_panel
                    await chat.mount(permission_panel)
                    chat.scroll_end(animate=False)


                elif isinstance(event, ToolResultEvent):
                    status = (
                        "failed"
                        if event.is_error
                        else "completed"
                    )

                    await chat.mount(
                        Static(
                            (
                                f"[Tool] {event.tool_name} {status}\n"
                                f"id: {event.tool_id}\n"
                                f"{event.output}"
                            ),
                            classes="tool-result",
                            markup=False,
                        )
                    )
                    chat.scroll_end(animate=False)

                

                elif isinstance(event, ErrorEvent):
                    assistant_message.update(
                        f"Error:{event.message}"
                    )

        except Exception as exc:
            assistant_message.update(
                f"Error: {exc}"
            )
        
        finally:
            prompt_input.disabled = False
            prompt_input.focus()

            self._active_task=None
            chat.scroll_end(animate=False)


async def run_tui(
    agent:Agent,
    conversation:ConversationManager,
    session:Session,
)->None:
    await NovaCoreApp(
        agent,
        conversation,
        session,
    ).run_async()
