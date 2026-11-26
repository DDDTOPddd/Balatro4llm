"""Thin CLI adapter over `balatro4llm.core`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Sequence

from balatro4llm.core import (
    BalatroBatchError,
    BalatroClient,
    BalatroError,
    DEFAULT_AUTO_ADVANCE,
    DEFAULT_AUTO_CASH_OUT,
    DEFAULT_COMPACT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    add_action_subparsers,
    compute_legal_actions,
    format_ping,
    format_speed_receipt,
    format_state,
    namespace_to_action_spec,
    parse_batch_steps,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="balatro-cli",
        description="CLI bridge to control Balatro via the in-game balatro4llm Lua Mod",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Mod host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Mod port (default: {DEFAULT_PORT})")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds (default: 5.0)")
    parser.add_argument("--wait-timeout", type=float, default=30.0, help="Post-action stability wait timeout (default: 30.0s)")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for animations to finish after an action")
    parser.add_argument(
        "--compact",
        action="store_true",
        default=DEFAULT_COMPACT,
        help="Compact token-efficient text output (or set BALATRO4LLM_COMPACT=1)",
    )
    parser.add_argument(
        "--auto-cash-out",
        action="store_true",
        default=DEFAULT_AUTO_CASH_OUT,
        help="Automatically cash out when an action reaches ROUND_EVAL (or set BALATRO4LLM_AUTO_CASH_OUT=1)",
    )
    parser.add_argument(
        "--auto-advance",
        action="store_true",
        default=DEFAULT_AUTO_ADVANCE,
        help="Auto cash-out AND auto-select mandatory Boss Blind when it cannot be rerolled (or BALATRO4LLM_AUTO_ADVANCE=1)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output raw JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="Check connectivity to the in-game Mod")

    p_state = sub.add_parser("state", help="Inspect current Balatro game state")
    p_state.add_argument("--hands", action="store_true", help="Include full poker hand levels table")

    add_action_subparsers(sub)

    p_batch = sub.add_parser(
        "batch",
        help="Execute multiple deterministic actions in sequence, waiting until stable between steps",
    )
    p_batch.add_argument(
        "steps",
        nargs="+",
        help='Quoted action commands, e.g. "move-joker 2 5" "play 1 2 3 4 5"',
    )

    return parser


def _print_state_output(
    state: dict[str, Any],
    as_json: bool,
    *,
    compact: bool = False,
    receipt: dict[str, Any] | None = None,
    batch_steps: Sequence[dict[str, Any]] | None = None,
    auto_steps: Sequence[dict[str, Any]] | None = None,
    show_hands: bool = False,
) -> None:
    if as_json:
        out: dict[str, Any] = dict(state)
        out["legal_actions"] = compute_legal_actions(state)
        if receipt is not None:
            out["action_receipt"] = receipt
        if batch_steps is not None:
            out["batch_results"] = list(batch_steps)
        if auto_steps:
            out["auto_steps"] = list(auto_steps)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    speed_line = format_speed_receipt(receipt)
    if speed_line:
        print(speed_line)
    print(
        format_state(
            state,
            show_hands=show_hands,
            compact=compact,
            auto_steps=auto_steps,
            batch_steps=batch_steps,
        )
    )


def cmd_ping(client: BalatroClient, as_json: bool) -> int:
    t0 = time.perf_counter()
    data = client.ping()
    rtt_ms = (time.perf_counter() - t0) * 1000.0

    if as_json:
        out = dict(data)
        out["rtt_ms"] = round(rtt_ms, 2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(format_ping(data, rtt_ms))
    return 0


def _configure_utf8_stdio() -> None:
    """Force UTF-8 stdout/stderr so Windows shells/pipes never emit GBK mojibake."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    wait = not args.no_wait
    wt = args.wait_timeout
    compact = bool(args.compact)
    auto_cash_out = bool(args.auto_cash_out or args.auto_advance)
    auto_select_boss = bool(args.auto_advance)

    try:
        with BalatroClient(host=args.host, port=args.port, timeout=args.timeout) as client:
            cmd = args.command
            if cmd == "ping":
                return cmd_ping(client, as_json=args.as_json)
            if cmd == "state":
                state = client.get_state()
                _print_state_output(state, args.as_json, compact=compact, show_hands=args.hands)
                return 0

            if cmd == "batch":
                specs = parse_batch_steps(args.steps)
                completed, auto_steps, state = client.run_batch(
                    specs,
                    wait_timeout=wt,
                    auto_cash_out=auto_cash_out,
                    auto_select_boss=auto_select_boss,
                )
                _print_state_output(
                    state,
                    args.as_json,
                    compact=compact,
                    batch_steps=completed,
                    auto_steps=auto_steps,
                )
                return 0

            action_name, params = namespace_to_action_spec(args)
            receipt, state = client.perform_action(
                action_name,
                params,
                wait=wait,
                wait_timeout=wt,
                auto_cash_out=auto_cash_out,
                auto_select_boss=auto_select_boss,
            )
            auto_steps = receipt.get("auto_steps")
            b_steps = receipt.get("batch_steps")
            _print_state_output(
                state,
                args.as_json,
                compact=compact,
                receipt=receipt,
                batch_steps=b_steps,
                auto_steps=auto_steps,
            )
            return 0
    except BalatroBatchError as exc:
        if args.as_json:
            err_out: dict[str, Any] = {
                "error": str(exc),
                "failed_index": exc.failed_index,
                "failed_action": exc.action_name,
                "completed_steps": exc.completed,
            }
            if exc.last_state is not None:
                err_out["state"] = exc.last_state
                err_out["legal_actions"] = compute_legal_actions(exc.last_state)
            print(json.dumps(err_out, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
            if exc.completed:
                done = " -> ".join(str(s.get("action")) for s in exc.completed)
                print(f"Completed before failure: {done}", file=sys.stderr)
            if exc.last_state is not None:
                print(format_state(exc.last_state, compact=compact))
        return 1
    except BalatroError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
