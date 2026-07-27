from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable
import shlex

from novacore.conversation import(
    ConversationManager,
)

CompactAction = Callable[
    [],
    Awaitable[str],
]

@dataclass
class CommandContext:
    conversation: ConversationManager
    session_id: str
    compact: CompactAction | None = None

@dataclass
class CommandInvocation:
    name:str
    arguments:list[str]

@dataclass
class CommandResult:
    content:str
    is_error:bool = False

CommandHandler = Callable[
    [
        CommandContext,
        list[str],
    ],
    Awaitable[CommandResult],
]

@dataclass
class CommandDefinition:
    name:str
    description:str
    handler:CommandHandler


def parse_command(
    text:str,
)->CommandInvocation | None:
    stripped = text.strip()

    if not stripped.startswith("/"):
        return None

    command_text = stripped[1:].strip()

    try:
        parts=shlex.split(command_text)

    except ValueError as exc:
        raise ValueError(
            f"Invalid command syntax: {exc}"
        ) from exc

    if not parts:
        raise ValueError(
            "Command name is required"
        )

    return CommandInvocation(
        name=parts[0].lower(),
        arguments=parts[1:],
    )

class CommandRegistry:
    def __init__(self)->None:
        self._commands:dict[
            str,
            CommandDefinition,
        ]={}

        self.register(
            CommandDefinition(
                name="help",
                description="Show available commands",
                handler=self._handle_help,
            )
        )
        self.register(
            CommandDefinition(
                name="status",
                description=(
                    "Show session and context status"
                ),
                handler=self._handle_status,
            )
        )
        self.register(
            CommandDefinition(
                name="compact",
                description=(
                    "Compact conversation context"
                ),
                handler=self._handle_compact,
            )
        )

    def register(
        self,
        command:CommandDefinition,
    )->None:
        name= command.name.strip().lower()

        if not name:
            raise ValueError(
                "Command name is required"
            )

        if name in self._commands:
            raise ValueError(
                f"Command already registered: /{name}"
            )

        self._commands[name]=command

    def build_help_text(self)->str:
        lines = [
            "Available commands"
        ]


        for name in sorted(self._commands):
            command=self._commands[name]

            lines.append(
                f"/{name} - {command.description}"
            )

        return "\n".join(lines)

    async def _handle_help(
        self,
        _context:CommandContext,
        arguments:list[str],
    )->CommandResult:
        if arguments:
            return CommandResult(
                content=(
                    "/help does not accept "
                    "arguments"
                ),
                is_error=True,
            )

        return CommandResult(
            content=self.build_help_text()
        )

    async def _handle_status(
        self,
        context:CommandContext,
        arguments:list[str]
    )->CommandResult:
        if arguments:
            return CommandResult(
                content=(
                    "/status does not accept "
                    "arguments"
                ),
                is_error=True,
            )

        messages = (
            context.conversation.get_messages()
        )

        message_count = len(messages)

        estimated_tokens = (
            context.conversation.current_tokens()
        )

        return CommandResult(
            content=(
                f"Session: {context.session_id}\n"
                f"Messages: {message_count}\n"
                "Estimated tokens: "
                f"{estimated_tokens:,}"
            )
        )

    async def _handle_compact(
        self,
        context:CommandContext,
        arguments:list[str],
    )->CommandResult:
        if arguments:
            return CommandResult(
                content=(
                    "/compact does not accept "
                    "arguments"
                ),
                is_error=True,
            )

        compact_action = context.compact

        if compact_action is None:
            return CommandResult(
                content=(
                    "Context compaction is "
                    "not available"
                ),
                is_error=True,
            )

        message=await compact_action()

        return CommandResult(
            content = message
        )

    async def execute(
        self,
        context:CommandContext,
        invocation:CommandInvocation,
    )->CommandResult:
        command = self._commands.get(
            invocation.name
        )
        if command is None:
            return CommandResult(
                content=(
                    "Unknown command "
                    f"/{invocation.name}"
                ),
                is_error=True,
            )

        return await command.handler(
            context,
            invocation.arguments
        )
