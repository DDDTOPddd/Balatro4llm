"""Optional MCPServer (`mcp>=2.0`) adapter over `balatro4llm.core`."""

from __future__ import annotations

from typing import Any


def create_server(*args: Any, **kwargs: Any) -> Any:
    """Lazily construct the MCPServer instance so importing `balatro4llm` stays zero-dependency."""
    from balatro4llm.mcp.server import create_server as _create_server

    return _create_server(*args, **kwargs)


__all__ = ["create_server"]
