"""Thin CLI wrapper over balatro4llm.client."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from typing import Any, Sequence

from balatro4llm.client import (
    BalatroBatchError,
    BalatroClient,
    BalatroError,
    DEFAULT_AUTO_ADVANCE,
    DEFAULT_AUTO_CASH_OUT,
    DEFAULT_COMPACT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    compute_legal_actions,
    format_state,
)


def _add_action_subparsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register all executable action subcommands (shared by root CLI and `batch` validator)."""
    p_start = sub.add_parser("start", help="Start a new run")
    p_start.add_argument("--deck", default=None, help="Deck key or name (e.g. b_red, 'Blue Deck')")
    p_start.add_argument("--stake", type=int, default=1, help="Stake level 1..8 (default: 1 White Chip)")
    p_start.add_argument("--seed", default=None, help="Optional run seed")

    sub.add_parser("continue", help="Continue saved run from main menu")
    sub.add_parser("main-menu", help="Return to the main menu")
    sub.add_parser("dismiss-overlay", help="Dismiss active overlay menu (e.g. continue Endless Mode after win)")

    sub.add_parser("select-blind", help="Select the current on-deck blind")
    sub.add_parser("skip-blind", help="Skip the current Small or Big blind for its Tag")
    sub.add_parser("reroll-boss", help="Reroll the Boss Blind ($10, requires Director's Cut or Retcon)")

    p_play = sub.add_parser("play", help="Play 1..5 hand cards by 1-based index")
    p_play.add_argument("cards", nargs="+", type=int, help="1-based hand card indices (e.g. 1 2 5)")

    p_discard = sub.add_parser("discard", help="Discard 1..5 hand cards by 1-based index")
    p_discard.add_argument("cards", nargs="+", type=int, help="1-based hand card indices (e.g. 3 4)")

    p_sort = sub.add_parser("sort-hand", help="Sort hand by rank or suit")
    p_sort.add_argument("by", choices=("rank", "suit"), help="Sort criterion")

    p_rj = sub.add_parser("reorder-jokers", help="Reorder Jokers by specifying the new 1-based index permutation")
    p_rj.add_argument("order", nargs="+", type=int, help="Full 1-based permutation of current Joker slots (e.g. 1 2 4 3)")

    p_rh = sub.add_parser("reorder-hand", help="Reorder hand cards by specifying the new 1-based index permutation")
    p_rh.add_argument("order", nargs="+", type=int, help="Full 1-based permutation of current hand slots")

    p_sj = sub.add_parser("sell-joker", help="Sell an owned Joker by 1-based index")
    p_sj.add_argument("index", type=int, help="1-based index in Jokers")

    p_sc = sub.add_parser("sell-consumable", help="Sell an owned consumable by 1-based index")
    p_sc.add_argument("index", type=int, help="1-based index in Consumables")

    p_use = sub.add_parser("use", help="Use an owned Tarot/Planet/Spectral consumable by 1-based index")
    p_use.add_argument("index", type=int, help="1-based index in Consumables")
    p_use.add_argument("targets", nargs="*", type=int, help="Optional 1-based hand indices for targeted consumables")

    sub.add_parser("cash-out", help="Collect round reward and enter the shop")

    p_buy = sub.add_parser("buy", help="Buy a shop card (Joker/Consumable/Playing card) by 1-based index")
    p_buy.add_argument("index", type=int, help="1-based index in Shop Cards")
    p_buy.add_argument("--use", action="store_true", help="Buy and immediately use (for consumables)")

    p_voucher = sub.add_parser("buy-voucher", help="Redeem a shop voucher by 1-based index (default: 1)")
    p_voucher.add_argument("index", nargs="?", type=int, default=1, help="1-based index in Vouchers (default: 1)")

    p_pack = sub.add_parser("buy-pack", help="Buy and open a booster pack by 1-based index")
    p_pack.add_argument("index", type=int, help="1-based index in Booster Packs")

    sub.add_parser("reroll", help="Reroll shop cards")
    sub.add_parser("next-round", help="Leave shop and advance to Blind Select")

    p_pick = sub.add_parser("pick", help="Pick a card from an open booster pack by 1-based index")
    p_pick.add_argument("index", type=int, help="1-based index in Booster Pack")
    p_pick.add_argument("targets", nargs="*", type=int, help="Optional 1-based hand indices for targeted Tarot/Spectral cards")

    sub.add_parser("skip-pack", help="Skip the current booster pack")


def _namespace_to_action_spec(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    """Convert a parsed CLI action namespace into a `(mod_action_name, params)` pair."""
    cmd = args.command
    if cmd == "start":
        params: dict[str, Any] = {"stake": args.stake}
        if args.deck:
            params["deck"] = args.deck
        if args.seed:
            params["seed"] = args.seed
        return "start", params
    if cmd == "continue":
        return "continue", {}
    if cmd == "main-menu":
        return "main_menu", {}
    if cmd == "dismiss-overlay":
        return "dismiss_overlay", {}
    if cmd == "select-blind":
        return "select_blind", {}
    if cmd == "skip-blind":
        return "skip_blind", {}
    if cmd == "reroll-boss":
        return "reroll_boss", {}
    if cmd == "play":
        return "play", {"cards": list(args.cards)}
    if cmd == "discard":
        return "discard", {"cards": list(args.cards)}
    if cmd == "sort-hand":
        return "sort_hand", {"by": args.by}
    if cmd == "reorder-jokers":
        return "reorder_jokers", {"order": list(args.order)}
    if cmd == "reorder-hand":
        return "reorder_hand", {"order": list(args.order)}
    if cmd == "sell-joker":
        return "sell_joker", {"index": args.index}
    if cmd == "sell-consumable":
        return "sell_consumable", {"index": args.index}
    if cmd == "use":
        p: dict[str, Any] = {"index": args.index}
        if args.targets:
            p["targets"] = list(args.targets)
        return "use", p
    if cmd == "cash-out":
        return "cash_out", {}
    if cmd == "buy":
        return "buy", {"index": args.index, "use": bool(args.use)}
    if cmd == "buy-voucher":
        return "buy_voucher", {"index": args.index}
    if cmd == "buy-pack":
        return "buy_pack", {"index": args.index}
    if cmd == "reroll":
        return "reroll", {}
    if cmd == "next-round":
        return "next_round", {}
    if cmd == "pick":
        p = {"index": args.index}
        if args.targets:
            p["targets"] = list(args.targets)
        return "pick", p
    if cmd == "skip-pack":
        return "skip_pack", {}
    raise BalatroError(f"Unsupported action command: {cmd}")


def _build_action_only_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="batch-step", add_help=False, exit_on_error=False)
    sub = p.add_subparsers(dest="command", required=True)
    _add_action_subparsers(sub)
    return p


def parse_batch_steps(step_strings: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    """Validate and parse every step string in a `batch` invocation before executing any action."""
    step_parser = _build_action_only_parser()
    parsed: list[tuple[str, dict[str, Any]]] = []
    for i, raw in enumerate(step_strings, start=1):
        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            raise BalatroError(f"Batch step #{i} syntax error ({raw!r}): {exc}") from exc
        if not tokens:
            raise BalatroError(f"Batch step #{i} is empty.")
        try:
            ns = step_parser.parse_args(tokens)
        except (argparse.ArgumentError, SystemExit) as exc:
            raise BalatroError(f"Batch step #{i} invalid command ({raw!r}): {exc}") from exc
        parsed.append(_namespace_to_action_spec(ns))
    return parsed


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

    _add_action_subparsers(sub)

    p_batch = sub.add_parser(
        "batch",
        help="Execute multiple deterministic actions in sequence, waiting until stable between steps",
    )
    p_batch.add_argument(
        "steps",
        nargs="+",
        help='Quoted action commands, e.g. "reorder-jokers 1 2 3 5 4" "play 1 2 3 4 5"',
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

    stage_name = data.get("stage_name") or str(data.get("stage"))
    state_name = data.get("state_name") or str(data.get("state"))
    print(f"PONG from balatro4llm v{data.get('mod_version')} ({rtt_ms:.1f} ms)")
    print(f"  Game Version : {data.get('game_version')}")
    print(f"  Stage / State: {stage_name} ({data.get('stage')}) / {state_name} ({data.get('state')})")
    print(f"  State Ready  : {data.get('state_complete')} | Paused: {data.get('paused')}")
    print(f"  FPS / Uptime : {data.get('fps')} fps / {data.get('uptime', 0):.1f}s")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = BalatroClient(host=args.host, port=args.port, timeout=args.timeout)
    wait = not args.no_wait
    wt = args.wait_timeout
    compact = bool(args.compact)
    auto_cash_out = bool(args.auto_cash_out or args.auto_advance)
    auto_select_boss = bool(args.auto_advance)

    try:
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

        action_name, params = _namespace_to_action_spec(args)
        receipt, state = client.perform_action(
            action_name,
            params,
            wait=wait,
            wait_timeout=wt,
            auto_cash_out=auto_cash_out,
            auto_select_boss=auto_select_boss,
        )
        auto_steps = receipt.get("auto_steps")
        _print_state_output(
            state,
            args.as_json,
            compact=compact,
            receipt=receipt,
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
