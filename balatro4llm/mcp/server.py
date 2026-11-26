"""Persistent MCP Server (`mcp>=2.0` MCPServer) exposing Balatro control over stdio or HTTP.

Reuses a single persistent keep-alive NDJSON/TCP connection to the in-game Lua Mod
via `balatro4llm.core.BalatroClient`, eliminating per-call shell/Python cold starts.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal, Sequence

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "MCP support requires the optional 'mcp>=2.0' extra. "
        "Install it with: pip install -e \".[mcp]\""
    ) from exc

from balatro4llm import __version__
from balatro4llm.core import (
    BalatroBatchError,
    BalatroClient,
    BalatroError,
    DEFAULT_HOST,
    DEFAULT_PORT,
    compute_legal_actions,
    format_batch_error,
    format_ping,
    format_speed_receipt,
    format_state,
    parse_action_command,
    parse_batch_steps,
)


MCP_INSTRUCTIONS = (
    "Zero-vision Balatro bridge. Read `balatro://guide` once if unfamiliar with rules/commands. "
    "Use `balatro_state` to inspect, `balatro_act` for single CLI-grammar actions "
    "(e.g. 'play 1 2 3 4 5', 'next-round --select', 'buy 2 --use', 'move-joker 1 5'), "
    "and `balatro_batch` for deterministic multi-step sequences with known indices."
)


def _read_skill_guide() -> str:
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    try:
        if skill_path.is_file():
            return skill_path.read_text(encoding="utf-8")
    except OSError:
        pass
    return MCP_INSTRUCTIONS


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING",
) -> MCPServer:
    """Create and configure the `balatro4llm` MCPServer instance."""
    client = BalatroClient(host=host, port=port, timeout=timeout, persistent=True)
    atexit.register(client.close)
    action_lock = asyncio.Lock()

    @asynccontextmanager
    async def _lifespan(_srv: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            client.close()

    mcp = MCPServer(
        "balatro4llm",
        version=__version__,
        instructions=MCP_INSTRUCTIONS,
        log_level=log_level,
        lifespan=_lifespan,
    )

    @mcp.tool(structured_output=False)
    async def balatro_ping() -> str:
        """Check in-game Lua Mod connectivity, version, stage/state, game speed, and TCP RTT."""
        try:
            t0 = time.perf_counter()
            data = await asyncio.to_thread(client.ping)
            rtt_ms = (time.perf_counter() - t0) * 1000.0
            return format_ping(data, rtt_ms)
        except BalatroError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(structured_output=False)
    async def balatro_state(
        compact: bool = True,
        show_hands: bool = False,
        as_json: bool = False,
    ) -> str:
        """Inspect live Balatro state, Deck Left composition, blind previews, and legal actions."""
        try:
            state = await asyncio.to_thread(client.get_state)
            if as_json:
                out = dict(state)
                out["legal_actions"] = compute_legal_actions(state)
                return json.dumps(out, ensure_ascii=False, indent=2)
            return format_state(state, show_hands=show_hands, compact=compact)
        except BalatroError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(structured_output=False)
    async def balatro_act(
        command: str,
        auto_advance: bool = True,
        compact: bool = True,
        wait_timeout: float = 30.0,
    ) -> str:
        """Execute one CLI-grammar command (e.g. 'play 1 2 3', 'buy 2 --use', 'next-round --select') and wait until stable."""
        try:
            action_name, params = parse_action_command(command)
            async with action_lock:
                receipt, state = await asyncio.to_thread(
                    client.perform_action,
                    action_name,
                    params,
                    wait=True,
                    wait_timeout=wait_timeout,
                    auto_cash_out=auto_advance,
                    auto_select_boss=auto_advance,
                )
            lines: list[str] = []
            speed_line = format_speed_receipt(receipt)
            if speed_line:
                lines.append(speed_line)
            lines.append(
                format_state(
                    state,
                    compact=compact,
                    auto_steps=receipt.get("auto_steps"),
                    batch_steps=receipt.get("batch_steps"),
                )
            )
            return "\n".join(lines)
        except BalatroBatchError as exc:
            raise ToolError(format_batch_error(exc, compact=compact)) from exc
        except BalatroError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(structured_output=False)
    async def balatro_batch(
        steps: list[str],
        auto_advance: bool = True,
        compact: bool = True,
        wait_timeout: float = 30.0,
    ) -> str:
        """Run deterministic sequential actions when all indices are known, failing fast with live state on error."""
        try:
            specs = parse_batch_steps(steps)
            async with action_lock:
                completed, auto_steps, state = await asyncio.to_thread(
                    client.run_batch,
                    specs,
                    wait_timeout=wait_timeout,
                    auto_cash_out=auto_advance,
                    auto_select_boss=auto_advance,
                )
            return format_state(
                state,
                compact=compact,
                batch_steps=completed,
                auto_steps=auto_steps,
            )
        except BalatroBatchError as exc:
            raise ToolError(format_batch_error(exc, compact=compact)) from exc
        except BalatroError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.resource("balatro://state", mime_type="text/plain")
    async def resource_state() -> str:
        """Live compact Balatro game state snapshot."""
        state = await asyncio.to_thread(client.get_state)
        return format_state(state, compact=True)

    @mcp.resource("balatro://guide", mime_type="text/markdown")
    def resource_guide() -> str:
        """Complete Balatro4llm operating rules, commands, and mechanics guide (SKILL.md)."""
        return _read_skill_guide()

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="balatro-mcp",
        description="Persistent MCP Server bridging AI Agents to the in-game balatro4llm Lua Mod",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Mod host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Mod port (default: {DEFAULT_PORT})")
    parser.add_argument("--timeout", type=float, default=5.0, help="Mod TCP timeout in seconds (default: 5.0)")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument("--mcp-host", default="127.0.0.1", help="HTTP bind host for streamable-http (default: 127.0.0.1)")
    parser.add_argument("--mcp-port", type=int, default=8765, help="HTTP bind port for streamable-http (default: 8765)")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="WARNING",
        help="MCP server stderr log level (default: WARNING)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    server = create_server(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        log_level=args.log_level,
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.mcp_host, port=args.mcp_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
