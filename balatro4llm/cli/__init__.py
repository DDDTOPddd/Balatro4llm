"""CLI adapter package (zero third-party dependencies)."""

from balatro4llm.cli.main import build_parser, main
from balatro4llm.core.actions import namespace_to_action_spec, parse_batch_steps

__all__ = [
    "build_parser",
    "main",
    "namespace_to_action_spec",
    "parse_batch_steps",
]
