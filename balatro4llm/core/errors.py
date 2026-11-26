"""Custom exceptions raised by balatro4llm clients and parsers."""

from __future__ import annotations

from typing import Any


class BalatroError(Exception):
    """Base error for balatro4llm client."""


class BalatroConnectionError(BalatroError):
    """Raised when unable to connect to or communicate with the in-game Mod."""


class BalatroCommandError(BalatroError):
    """Raised when the Mod returns ok=false for a command."""

    def __init__(self, cmd: str, message: str, raw_response: dict[str, Any] | None = None) -> None:
        super().__init__(f"Command '{cmd}' failed: {message}")
        self.cmd = cmd
        self.message = message
        self.raw_response = raw_response or {}


class BalatroTimeoutError(BalatroError):
    """Raised when waiting for a stable interactive game state times out."""

    def __init__(self, message: str, last_state: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.last_state = last_state


class BalatroBatchError(BalatroError):
    """Raised when a step inside `run_batch` fails; preserves completed receipts and live state."""

    def __init__(
        self,
        failed_index: int,
        action_name: str,
        message: str,
        completed: list[dict[str, Any]],
        last_state: dict[str, Any] | None,
    ) -> None:
        super().__init__(f"Batch failed at step #{failed_index} ({action_name}): {message}")
        self.failed_index = failed_index
        self.action_name = action_name
        self.reason = message
        self.completed = completed
        self.last_state = last_state
