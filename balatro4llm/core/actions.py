"""Unified action registry, command string parser, and batch step expander.

Shared as the Single Source of Truth across CLI, CLI `batch`, MCP `balatro_act`,
and MCP `balatro_batch` so every interface supports the exact same command grammar.
"""

from __future__ import annotations

import argparse
import shlex
from typing import Any, IO, NoReturn, Sequence

from balatro4llm.core.errors import BalatroError


class _SilentArgumentParser(argparse.ArgumentParser):
    """ArgumentParser variant that raises BalatroError instead of printing usage or exiting."""

    def error(self, message: str) -> NoReturn:
        raise BalatroError(message)

    def print_usage(self, file: IO[str] | None = None) -> None:
        return

    def print_help(self, file: IO[str] | None = None) -> None:
        return


def add_action_subparsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register all executable action subcommands (shared by root CLI, `batch`, and MCP)."""
    p_start = sub.add_parser("start", aliases=["new-run"], help="Start a new run (from Main Menu, Win screen, or Game Over)")
    p_start.add_argument("--deck", default=None, help="Deck key or name (e.g. b_red, 'Red Deck', '红色牌组')")
    p_start.add_argument("--stake", default="1", help="Stake 1..8, 'max' (highest unlocked for deck), or name (e.g. green, 绿注)")
    p_start.add_argument("--seed", default=None, help="Optional run seed")

    sub.add_parser("continue", help="Continue saved run from main menu")
    sub.add_parser("endless", help="Continue into Endless Mode from the Ante 8 Win screen")
    sub.add_parser("main-menu", help="Return to the main menu")
    sub.add_parser("dismiss-overlay", help="Dismiss active overlay menu (pause/tutorial/win popup)")

    p_speed = sub.add_parser(
        "set-speed",
        help="Set Balatro game speed multiplier (0.5, 1, 2, 4 native/saved; 8, 16 runtime turbo)",
    )
    p_speed.add_argument(
        "speed",
        type=float,
        choices=(0.5, 1.0, 2.0, 4.0, 8.0, 16.0),
        help="Speed multiplier: 0.5, 1, 2, 4, 8, or 16",
    )

    sub.add_parser("select-blind", help="Select the current on-deck blind")
    sub.add_parser("skip-blind", help="Skip the current Small or Big blind for its Tag")
    sub.add_parser("reroll-boss", help="Reroll the Boss Blind ($10, requires Director's Cut or Retcon)")

    p_play = sub.add_parser("play", help="Play 1..5 hand cards by 1-based index")
    p_play.add_argument("cards", nargs="+", type=int, help="1-based hand card indices (e.g. 1 2 5)")

    p_discard = sub.add_parser("discard", help="Discard 1..5 hand cards by 1-based index")
    p_discard.add_argument("cards", nargs="+", type=int, help="1-based hand card indices (e.g. 3 4)")

    p_sort = sub.add_parser("sort-hand", help="Sort hand by rank or suit")
    p_sort.add_argument("by", choices=("rank", "suit"), help="Sort criterion")

    p_mj = sub.add_parser("move-joker", help="Move a single Joker from one 1-based slot to another")
    p_mj.add_argument("from_idx", metavar="from", type=int, help="Current 1-based Joker slot")
    p_mj.add_argument("to_idx", metavar="to", type=int, help="Target 1-based Joker slot")

    p_mh = sub.add_parser("move-hand", help="Move a single hand card from one 1-based slot to another")
    p_mh.add_argument("from_idx", metavar="from", type=int, help="Current 1-based hand slot")
    p_mh.add_argument("to_idx", metavar="to", type=int, help="Target 1-based hand slot")

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
    p_next = sub.add_parser("next-round", help="Leave shop and advance to Blind Select (or enter/skip directly)")
    p_next_grp = p_next.add_mutually_exclusive_group()
    p_next_grp.add_argument(
        "--select",
        action="store_true",
        help="Leave shop and immediately select/enter the next blind",
    )
    p_next_grp.add_argument(
        "--skip",
        action="store_true",
        help="Leave shop and immediately skip the next Small/Big blind for its Skip Tag",
    )

    p_pick = sub.add_parser("pick", help="Pick a card from an open booster pack by 1-based index")
    p_pick.add_argument("index", type=int, help="1-based index in Booster Pack")
    p_pick.add_argument("targets", nargs="*", type=int, help="Optional 1-based hand indices for targeted Tarot/Spectral cards")

    sub.add_parser("skip-pack", help="Skip the current booster pack")


def namespace_to_action_spec(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    """Convert a parsed CLI action namespace into a `(mod_action_name, params)` pair."""
    cmd = args.command
    if cmd in ("start", "new-run"):
        raw_stake = str(args.stake).strip()
        stake_val: int | str = int(raw_stake) if raw_stake.isdigit() else raw_stake
        params: dict[str, Any] = {"stake": stake_val}
        if args.deck:
            params["deck"] = args.deck
        if args.seed:
            params["seed"] = args.seed
        return "start", params
    if cmd == "continue":
        return "continue", {}
    if cmd == "endless":
        return "endless", {}
    if cmd == "main-menu":
        return "main_menu", {}
    if cmd == "dismiss-overlay":
        return "dismiss_overlay", {}
    if cmd == "set-speed":
        spd = float(args.speed)
        return "set_speed", {"speed": int(spd) if spd.is_integer() else spd}
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
    if cmd == "move-joker":
        return "move_joker", {"from": args.from_idx, "to": args.to_idx}
    if cmd == "move-hand":
        return "move_hand", {"from": args.from_idx, "to": args.to_idx}
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
        p_nr: dict[str, Any] = {}
        if getattr(args, "select", False):
            p_nr["select"] = True
        elif getattr(args, "skip", False):
            p_nr["skip"] = True
        return "next_round", p_nr
    if cmd == "pick":
        p = {"index": args.index}
        if args.targets:
            p["targets"] = list(args.targets)
        return "pick", p
    if cmd == "skip-pack":
        return "skip_pack", {}
    raise BalatroError(f"Unsupported action command: {cmd}")


def _build_action_only_parser() -> _SilentArgumentParser:
    p = _SilentArgumentParser(prog="balatro-action", add_help=False, exit_on_error=False)
    sub = p.add_subparsers(dest="command", required=True)
    add_action_subparsers(sub)
    return p


_ACTION_PARSER = _build_action_only_parser()


def parse_action_command(command: str) -> tuple[str, dict[str, Any]]:
    """Parse a single action command string (e.g. `'play 1 2 3'`) into `(action_name, params)`."""
    if not isinstance(command, str):
        raise BalatroError("Action command must be a string.")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise BalatroError(f"Command syntax error ({command!r}): {exc}") from exc
    if not tokens:
        raise BalatroError("Action command must not be empty.")
    try:
        ns = _ACTION_PARSER.parse_args(tokens)
    except (argparse.ArgumentError, SystemExit) as exc:
        raise BalatroError(f"Invalid action command ({command!r}): {exc}") from exc
    except BalatroError as exc:
        raise BalatroError(f"Invalid action command ({command!r}): {exc}") from exc
    return namespace_to_action_spec(ns)


def parse_batch_steps(step_strings: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    """Validate and parse every step string in a batch invocation before executing any action."""
    if not step_strings:
        raise BalatroError("Batch must contain at least one action step.")
    parsed: list[tuple[str, dict[str, Any]]] = []
    for i, raw in enumerate(step_strings, start=1):
        try:
            parsed.append(parse_action_command(raw))
        except BalatroError as exc:
            raise BalatroError(f"Batch step #{i} invalid command ({raw!r}): {exc}") from exc
    return parsed


def expand_action_steps(
    steps: Sequence[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Expand high-level composite commands (such as `next-round --select|--skip`) into atomic steps."""
    expanded: list[tuple[str, dict[str, Any]]] = []
    for action_name, raw_params in steps:
        params = dict(raw_params or {})
        if action_name == "next_round" and (params.get("select") or params.get("skip")):
            if params.get("select") and params.get("skip"):
                raise BalatroError("next_round cannot set both select=True and skip=True")
            follow = "select_blind" if params.get("select") else "skip_blind"
            expanded.append(("next_round", {}))
            expanded.append((follow, {}))
        else:
            expanded.append((action_name, params))
    return expanded
