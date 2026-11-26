"""Thin CLI wrapper over balatro4llm.client."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Sequence

from balatro4llm.client import (
    BalatroClient,
    BalatroError,
    DEFAULT_HOST,
    DEFAULT_PORT,
    compute_legal_actions,
    format_state,
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
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output raw JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="Check connectivity to the in-game Mod")

    p_state = sub.add_parser("state", help="Inspect current Balatro game state")
    p_state.add_argument("--hands", action="store_true", help="Include full poker hand levels table")

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

    return parser


def _print_state_output(state: dict[str, Any], as_json: bool, *, receipt: dict[str, Any] | None = None, show_hands: bool = False) -> None:
    if as_json:
        out: dict[str, Any] = dict(state)
        out["legal_actions"] = compute_legal_actions(state)
        if receipt is not None:
            out["action_receipt"] = receipt
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(format_state(state, show_hands=show_hands))


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

    try:
        cmd = args.command
        if cmd == "ping":
            return cmd_ping(client, as_json=args.as_json)
        if cmd == "state":
            state = client.get_state()
            _print_state_output(state, args.as_json, show_hands=args.hands)
            return 0

        if cmd == "start":
            receipt, state = client.start_run(deck=args.deck, stake=args.stake, seed=args.seed, wait=wait, wait_timeout=wt)
        elif cmd == "continue":
            receipt, state = client.continue_run(wait=wait, wait_timeout=wt)
        elif cmd == "main-menu":
            receipt, state = client.go_to_menu(wait=wait, wait_timeout=wt)
        elif cmd == "dismiss-overlay":
            receipt, state = client.dismiss_overlay(wait=wait, wait_timeout=wt)
        elif cmd == "select-blind":
            receipt, state = client.select_blind(wait=wait, wait_timeout=wt)
        elif cmd == "skip-blind":
            receipt, state = client.skip_blind(wait=wait, wait_timeout=wt)
        elif cmd == "reroll-boss":
            receipt, state = client.reroll_boss(wait=wait, wait_timeout=wt)
        elif cmd == "play":
            receipt, state = client.play(args.cards, wait=wait, wait_timeout=wt)
        elif cmd == "discard":
            receipt, state = client.discard(args.cards, wait=wait, wait_timeout=wt)
        elif cmd == "sort-hand":
            receipt, state = client.sort_hand(args.by, wait=wait, wait_timeout=wt)
        elif cmd == "reorder-jokers":
            receipt, state = client.reorder_jokers(args.order, wait=wait, wait_timeout=wt)
        elif cmd == "reorder-hand":
            receipt, state = client.reorder_hand(args.order, wait=wait, wait_timeout=wt)
        elif cmd == "sell-joker":
            receipt, state = client.sell_joker(args.index, wait=wait, wait_timeout=wt)
        elif cmd == "sell-consumable":
            receipt, state = client.sell_consumable(args.index, wait=wait, wait_timeout=wt)
        elif cmd == "use":
            receipt, state = client.use_consumable(args.index, targets=args.targets or None, wait=wait, wait_timeout=wt)
        elif cmd == "cash-out":
            receipt, state = client.cash_out(wait=wait, wait_timeout=wt)
        elif cmd == "buy":
            receipt, state = client.buy(args.index, use=args.use, wait=wait, wait_timeout=wt)
        elif cmd == "buy-voucher":
            receipt, state = client.buy_voucher(args.index, wait=wait, wait_timeout=wt)
        elif cmd == "buy-pack":
            receipt, state = client.buy_pack(args.index, wait=wait, wait_timeout=wt)
        elif cmd == "reroll":
            receipt, state = client.reroll(wait=wait, wait_timeout=wt)
        elif cmd == "next-round":
            receipt, state = client.next_round(wait=wait, wait_timeout=wt)
        elif cmd == "pick":
            receipt, state = client.pick(args.index, targets=args.targets or None, wait=wait, wait_timeout=wt)
        elif cmd == "skip-pack":
            receipt, state = client.skip_pack(wait=wait, wait_timeout=wt)
        else:
            parser.error(f"Unknown command: {cmd}")

        _print_state_output(state, args.as_json, receipt=receipt)
        return 0
    except BalatroError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
