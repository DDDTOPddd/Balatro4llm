"""Core Python client communicating with the in-game balatro4llm Lua Mod via NDJSON/TCP.

Provides:
- Low-level NDJSON/TCP transport (`ping`, `get_state`, `execute_action`)
- Post-action stability wait loop (`wait_until_stable`) polling G.E_MANAGER / locks / state readiness
- High-level game action methods (reusable by both CLI and future MCP server)
- Legal-action inference and compact LLM-friendly state formatting
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import time
from typing import Any, Sequence


DEFAULT_HOST = os.environ.get("BALATRO4LLM_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("BALATRO4LLM_PORT", "12345"))

PACK_STATES = frozenset({
    "TAROT_PACK",
    "PLANET_PACK",
    "SPECTRAL_PACK",
    "STANDARD_PACK",
    "BUFFOON_PACK",
})

TRANSIENT_STATES = frozenset({
    "HAND_PLAYED",
    "DRAW_TO_HAND",
    "NEW_ROUND",
    "PLAY_TAROT",
    "SPLASH",
})


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


def is_state_stable(state: dict[str, Any]) -> bool:
    """Return True when the game has finished animations/transitions and can accept input."""
    stage_name = state.get("stage_name")
    state_name = state.get("state_name")
    ready = state.get("ready") or {}
    eq = ready.get("event_queues") or {}

    if stage_name == "MAIN_MENU":
        return (
            state_name == "MENU"
            and eq.get("base_blocking", 0) == 0
            and not ready.get("controller_locked")
        )

    if stage_name != "RUN":
        return False

    if state_name in TRANSIENT_STATES:
        return False

    if eq.get("base_blocking", 0) > 0:
        return False

    if ready.get("controller_locked") or ready.get("active_locks"):
        return False

    if state_name == "GAME_OVER":
        return bool(state.get("state_complete"))

    # Win popup or pause overlay: stop waiting so caller can inspect it.
    if ready.get("has_overlay_menu") or ready.get("in_tutorial"):
        return True

    if not state.get("state_complete"):
        return False

    if state_name == "SELECTING_HAND":
        hand_cards = (state.get("hand") or {}).get("cards") or []
        return bool(hand_cards) and not ready.get("block_play")

    if state_name == "BLIND_SELECT":
        return bool(ready.get("blind_select_ready"))

    if state_name == "ROUND_EVAL":
        return bool(ready.get("round_eval_ready"))

    if state_name == "SHOP":
        return bool(ready.get("shop_ready"))

    if state_name in PACK_STATES:
        if not ready.get("pack_ready"):
            return False
        # Arcana & Spectral packs also draw hand cards before interaction.
        if state_name in ("TAROT_PACK", "SPECTRAL_PACK"):
            hand = state.get("hand") or {}
            deck = state.get("deck") or {}
            if not hand.get("cards") and (deck.get("remaining", 0) > 0) and (hand.get("limit", 0) > 0):
                return False
        return True

    return True


class BalatroClient:
    """Synchronous NDJSON-over-TCP client for the Balatro in-game Lua Mod."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._req_ids = itertools.count(1)

    def request(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = next(self._req_ids)
        payload = {"id": req_id, "cmd": cmd, "args": args or {}}
        wire = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.sendall(wire)
                line = self._recv_line(sock)
        except OSError as exc:
            raise BalatroConnectionError(
                f"Cannot reach Balatro Mod at {self.host}:{self.port} ({exc}). "
                "Make sure Balatro is running with Lovely and the balatro4llm mod installed."
            ) from exc

        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BalatroConnectionError(f"Invalid JSON received from Mod: {exc}") from exc

        if not isinstance(resp, dict):
            raise BalatroConnectionError(f"Unexpected response type from Mod: {type(resp).__name__}")

        if not resp.get("ok"):
            raise BalatroCommandError(cmd, str(resp.get("error", "unknown error")), resp)

        data = resp.get("data")
        if not isinstance(data, dict):
            return {"value": data}
        return data

    @staticmethod
    def _recv_line(sock: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            nl = chunk.find(b"\n")
            if nl != -1:
                chunks.append(chunk[:nl])
                break
            chunks.append(chunk)
        raw = b"".join(chunks).rstrip(b"\r")
        if not raw:
            raise BalatroConnectionError("Connection closed before receiving a response line.")
        return raw.decode("utf-8")

    # --- Low-level commands ---

    def ping(self) -> dict[str, Any]:
        return self.request("ping")

    def get_state(self) -> dict[str, Any]:
        return self.request("state")

    def execute_action(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(params or {})
        args["name"] = name
        return self.request("action", args)

    def wait_until_stable(
        self,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.10,
        initial_delay: float = 0.15,
        required_streak: int = 2,
    ) -> dict[str, Any]:
        """Poll `state` until animations/events finish and the game settles into an actionable state."""
        deadline = time.monotonic() + timeout
        if initial_delay > 0:
            time.sleep(initial_delay)

        streak = 0
        last_key: tuple[Any, Any, int] | None = None
        last_state: dict[str, Any] | None = None

        while True:
            state = self.get_state()
            last_state = state
            if is_state_stable(state):
                run = state.get("run") or {}
                shop = state.get("shop") or {}
                pack = state.get("pack") or {}
                key = (
                    state.get("stage_name"),
                    state.get("state_name"),
                    int(run.get("dollars", 0)),
                    int(run.get("chips", 0)),
                    int(run.get("hands_left", 0)),
                    int(run.get("discards_left", 0)),
                    len((state.get("hand") or {}).get("cards") or []),
                    len((state.get("jokers") or {}).get("cards") or []),
                    len(shop.get("jokers") or []),
                    int(pack.get("choices_left", 0)),
                )
                if key == last_key:
                    streak += 1
                else:
                    streak = 1
                    last_key = key
                if streak >= required_streak:
                    return state
            else:
                streak = 0
                last_key = None

            if time.monotonic() >= deadline:
                sname = state.get("state_name")
                ready = state.get("ready") or {}
                eq = ready.get("event_queues") or {}
                raise BalatroTimeoutError(
                    f"Timed out after {timeout:.1f}s waiting for stable state "
                    f"(last: {state.get('stage_name')}/{sname}, "
                    f"base_blocking={eq.get('base_blocking')}, locks={ready.get('active_locks')})",
                    last_state=last_state,
                )
            time.sleep(poll_interval)

    def perform_action(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute an atomic action, optionally wait until animations finish, and return (receipt, state)."""
        receipt = self.execute_action(name, params)
        if wait:
            if name in ("sort_hand", "reorder_jokers", "reorder_hand"):
                state = self.wait_until_stable(timeout=wait_timeout, initial_delay=0.05, required_streak=1)
            else:
                init_delay = 0.35 if name in ("start", "continue", "main_menu") else 0.15
                state = self.wait_until_stable(timeout=wait_timeout, initial_delay=init_delay)
        else:
            state = self.get_state()
        return receipt, state

    # --- High-level action methods (shared by CLI and future MCP server) ---

    def start_run(
        self,
        *,
        deck: str | None = None,
        stake: int = 1,
        seed: str | None = None,
        wait: bool = True,
        wait_timeout: float = 30.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"stake": stake}
        if deck:
            params["deck"] = deck
        if seed:
            params["seed"] = seed
        return self.perform_action("start", params, wait=wait, wait_timeout=wait_timeout)

    def continue_run(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("continue", {}, wait=wait, wait_timeout=wait_timeout)

    def go_to_menu(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("main_menu", {}, wait=wait, wait_timeout=wait_timeout)

    def dismiss_overlay(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("dismiss_overlay", {}, wait=wait, wait_timeout=wait_timeout)

    def select_blind(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("select_blind", {}, wait=wait, wait_timeout=wait_timeout)

    def skip_blind(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("skip_blind", {}, wait=wait, wait_timeout=wait_timeout)

    def reroll_boss(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("reroll_boss", {}, wait=wait, wait_timeout=wait_timeout)

    def play(
        self, cards: Sequence[int], *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("play", {"cards": list(cards)}, wait=wait, wait_timeout=wait_timeout)

    def discard(
        self, cards: Sequence[int], *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("discard", {"cards": list(cards)}, wait=wait, wait_timeout=wait_timeout)

    def sort_hand(
        self, by: str = "rank", *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("sort_hand", {"by": by}, wait=wait, wait_timeout=wait_timeout)

    def reorder_jokers(
        self, order: Sequence[int], *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("reorder_jokers", {"order": list(order)}, wait=wait, wait_timeout=wait_timeout)

    def reorder_hand(
        self, order: Sequence[int], *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("reorder_hand", {"order": list(order)}, wait=wait, wait_timeout=wait_timeout)

    def sell_joker(
        self, index: int, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("sell_joker", {"index": index}, wait=wait, wait_timeout=wait_timeout)

    def sell_consumable(
        self, index: int, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("sell_consumable", {"index": index}, wait=wait, wait_timeout=wait_timeout)

    def use_consumable(
        self,
        index: int,
        targets: Sequence[int] | None = None,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"index": index}
        if targets:
            params["targets"] = list(targets)
        return self.perform_action("use", params, wait=wait, wait_timeout=wait_timeout)

    def cash_out(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("cash_out", {}, wait=wait, wait_timeout=wait_timeout)

    def buy(
        self, index: int, *, use: bool = False, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("buy", {"index": index, "use": use}, wait=wait, wait_timeout=wait_timeout)

    def buy_voucher(
        self, index: int = 1, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("buy_voucher", {"index": index}, wait=wait, wait_timeout=wait_timeout)

    def buy_pack(
        self, index: int, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("buy_pack", {"index": index}, wait=wait, wait_timeout=wait_timeout)

    def reroll(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("reroll", {}, wait=wait, wait_timeout=wait_timeout)

    def next_round(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("next_round", {}, wait=wait, wait_timeout=wait_timeout)

    def pick(
        self,
        index: int,
        targets: Sequence[int] | None = None,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"index": index}
        if targets:
            params["targets"] = list(targets)
        return self.perform_action("pick", params, wait=wait, wait_timeout=wait_timeout)

    def skip_pack(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("skip_pack", {}, wait=wait, wait_timeout=wait_timeout)


def _display_name(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "")
    loc = str(item.get("loc_name") or "")
    if loc and loc != name and loc != "ERROR":
        return f"{loc} ({name})"
    return name or loc or "?"


def _format_num(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _format_playing_card(card: dict[str, Any]) -> str:
    idx = card.get("index", "?")
    if card.get("face_down"):
        tags = ["face-down"]
        if card.get("highlighted"):
            tags.append("SELECTED")
        if card.get("forced_selection"):
            tags.append("FORCED")
        return f"[{idx}] ?? ({', '.join(tags)})"

    short = card.get("short", "?")
    mods: list[str] = []
    if card.get("enhancement"):
        mods.append(str(card["enhancement"]).replace(" Card", ""))
    if card.get("edition"):
        mods.append(str(card["edition"]))
    if card.get("seal"):
        mods.append(f"{card['seal']}Seal")
    if card.get("perma_bonus"):
        mods.append(f"+{card['perma_bonus']}c")
    if card.get("debuff"):
        mods.append("DEBUFF")
    if card.get("forced_selection"):
        mods.append("FORCED")
    if card.get("highlighted"):
        mods.append("*")

    suffix = f" ({', '.join(mods)})" if mods else ""
    return f"[{idx}] {short}{suffix}"


def _format_item_card(card: dict[str, Any], *, show_price: bool = False, show_sell: bool = False) -> str:
    idx = card.get("index", "?")
    if card.get("kind") == "PlayingCard":
        base = _format_playing_card(card)
        if show_price:
            afford = "" if card.get("can_buy", True) else " [cannot afford]"
            return f"{base} - ${card.get('cost', 0)}{afford}"
        return base

    title = _display_name(card)
    tags: list[str] = []
    if card.get("kind") and card.get("kind") not in ("Joker", "Voucher", "Booster"):
        tags.append(str(card["kind"]))
    if card.get("edition"):
        tags.append(str(card["edition"]))
    if card.get("eternal"):
        tags.append("Eternal")
    if card.get("perishable"):
        tally = card.get("perish_tally")
        tags.append(f"Perishable:{tally}" if tally is not None else "Perishable")
    if card.get("rental"):
        tags.append("Rental")
    if card.get("debuff"):
        tags.append("DEBUFF")
    if show_price:
        afford = "" if card.get("can_buy", True) else " [locked/no $]"
        tags.append(f"${card.get('cost', 0)}{afford}")
    if show_sell:
        sell_tag = f"sell ${card.get('sell_cost', 0)}"
        if not card.get("can_sell", True):
            sell_tag += "/unsellable"
        tags.append(sell_tag)
    if card.get("can_use") is not None:
        max_h = card.get("max_highlighted")
        min_h = card.get("min_highlighted") or 1
        if card.get("can_use"):
            use_str = "usable"
        elif card.get("can_use_with_targets") and max_h:
            if min_h == max_h:
                use_str = f"usable (select {max_h} hand card{'s' if max_h > 1 else ''})"
            else:
                use_str = f"usable (select {min_h}..{max_h} hand cards)"
        else:
            use_str = "not-usable"
            if max_h:
                if min_h == max_h:
                    use_str += f" (needs {max_h} hand card{'s' if max_h > 1 else ''})"
                else:
                    use_str += f" (needs {min_h}..{max_h} hand cards)"
        tags.append(use_str)

    tag_str = f" [{', '.join(tags)}]" if tags else ""
    desc = card.get("description")
    desc_str = f" — {desc}" if desc else ""
    return f"[{idx}] {title}{tag_str}{desc_str}"


def compute_legal_actions(state: dict[str, Any]) -> list[str]:
    """Infer high-level legal CLI actions from a state snapshot."""
    stage_name = state.get("stage_name")
    state_name = state.get("state_name")
    ready = state.get("ready") or {}
    eq = ready.get("event_queues") or {}
    actions: list[str] = []

    if ready.get("in_tutorial"):
        actions.append("wait / advance tutorial overlay (tutorial active)")
    if stage_name == "MAIN_MENU":
        menu = state.get("menu") or {}
        if menu.get("has_saved_run"):
            actions.append("continue (resume saved run)")
        actions.append("start [--deck <key>] [--stake <1-8>] [--seed <seed>]")
        return actions

    if stage_name != "RUN":
        return ["wait (non-interactive stage)"]

    if state_name == "GAME_OVER":
        return ["start (new run)", "main-menu"]

    if ready.get("has_overlay_menu") and state_name != "GAME_OVER":
        return ["dismiss-overlay (continue endless / close popup)", "main-menu"]

    if eq.get("base_blocking", 0) > 0 or ready.get("controller_locked"):
        return [
            f"wait (animating: base_blocking={eq.get('base_blocking', 0)}, "
            f"locked={ready.get('controller_locked')})"
        ]

    if state_name == "BLIND_SELECT":
        blind = state.get("blind") or {}
        on_deck = blind.get("on_deck")
        actions.append(f"select-blind ({on_deck or 'current'})")
        if on_deck in ("Small", "Big"):
            actions.append(f"skip-blind ({on_deck})")
        if blind.get("can_reroll_boss"):
            actions.append("reroll-boss ($10)")
    elif state_name == "SELECTING_HAND":
        run = state.get("run") or {}
        hand_cards = (state.get("hand") or {}).get("cards") or []
        if hand_cards and not ready.get("block_play"):
            actions.append("play <idx...> (1..5 cards)")
        if hand_cards and (run.get("discards_left") or 0) > 0:
            actions.append("discard <idx...> (1..5 cards)")
        actions.append("sort-hand <rank|suit>")
        if len(hand_cards) > 1:
            actions.append("reorder-hand <order...>")
    elif state_name == "ROUND_EVAL":
        if ready.get("round_eval_ready"):
            dollars = (state.get("round_eval") or {}).get("cash_out_dollars", 0)
            actions.append(f"cash-out (+${dollars})")
        else:
            actions.append("wait (round evaluation tallying)")
    elif state_name == "SHOP":
        shop = state.get("shop") or {}
        shop_ready = bool(ready.get("shop_ready")) or (
            bool(state.get("state_complete"))
            and eq.get("base_blocking", 0) == 0
            and bool(shop)
        )
        if not shop_ready:
            return ["wait (shop loading)"]
        if any(c.get("can_buy") for c in shop.get("jokers") or []):
            actions.append("buy <idx> [--use]")
        if any(c.get("can_buy") for c in shop.get("vouchers") or []):
            actions.append("buy-voucher [idx]")
        if any(c.get("can_buy") for c in shop.get("boosters") or []):
            actions.append("buy-pack <idx>")
        if shop.get("can_reroll"):
            actions.append(f"reroll (${shop.get('reroll_cost', 0)})")
        actions.append("next-round")
    elif state_name in PACK_STATES:
        pack = state.get("pack") or {}
        if not ready.get("pack_ready"):
            return ["wait (pack opening)"]
        if any(c.get("can_select", True) for c in pack.get("cards") or []):
            actions.append("pick <idx> [target_hand_idx...]")
        if pack.get("can_skip"):
            actions.append("skip-pack")
        hand_cards = (state.get("hand") or {}).get("cards") or []
        if len(hand_cards) > 1:
            actions.append("reorder-hand <order...>")
    else:
        return [f"wait (transient state: {state_name})"]

    # Always-available inventory actions in stable RUN states
    if state_name in ("SELECTING_HAND", "SHOP", "BLIND_SELECT") or state_name in PACK_STATES:
        jokers = (state.get("jokers") or {}).get("cards") or []
        if any(j.get("can_sell") for j in jokers):
            actions.append("sell-joker <idx>")
        if len(jokers) > 1:
            actions.append("reorder-jokers <order...>")
        cons = (state.get("consumeables") or {}).get("cards") or []
        if any(c.get("can_use") or c.get("can_use_with_targets") for c in cons):
            actions.append("use <idx> [target_hand_idx...]")
        if any(c.get("can_sell") for c in cons):
            actions.append("sell-consumable <idx>")

    return actions


def format_state(state: dict[str, Any], *, show_hands: bool = False) -> str:
    """Format a state snapshot into concise, LLM-friendly text."""
    lines: list[str] = []
    stage_name = state.get("stage_name") or str(state.get("stage"))
    state_name = state.get("state_name") or str(state.get("state"))
    ready = state.get("ready") or {}
    eq = ready.get("event_queues") or {}

    header = f"=== BALATRO [{stage_name} / {state_name}]"
    flags: list[str] = []
    if ready.get("paused"):
        flags.append("PAUSED")
    if ready.get("has_overlay_menu"):
        flags.append("OVERLAY")
    if ready.get("in_tutorial"):
        flags.append("TUTORIAL")
    if eq.get("base_blocking", 0) > 0:
        flags.append(f"BUSY:{eq['base_blocking']}")
    if ready.get("active_locks"):
        flags.append(f"LOCKS:{','.join(ready['active_locks'])}")
    if flags:
        header += f" ({' | '.join(flags)})"
    header += " ==="
    lines.append(header)

    if stage_name == "MAIN_MENU":
        menu = state.get("menu") or {}
        sel = menu.get("selected_deck") or {}
        lines.append(f"Profile: {menu.get('profile')} | Saved Run: {menu.get('has_saved_run')}")
        lines.append(f"Selected Deck: {_display_name(sel)} [{sel.get('key')}]")
        decks = menu.get("unlocked_decks") or []
        if decks:
            deck_str = ", ".join(f"{d.get('key')}({_display_name(d)})" for d in decks)
            lines.append(f"Unlocked Decks ({len(decks)}): {deck_str}")
        lines.append("Legal Actions: " + " | ".join(compute_legal_actions(state)))
        return "\n".join(lines)

    run = state.get("run") or {}
    blind = state.get("blind") or {}
    deck = state.get("deck") or {}

    if run:
        dk = run.get("deck") or {}
        lines.append(
            f"Ante {run.get('ante')}/{run.get('win_ante')} | Round {run.get('round')} | "
            f"${run.get('dollars', 0)} (min ${run.get('bankrupt_at', 0)}) | "
            f"Hands: {run.get('hands_left')} | Discards: {run.get('discards_left')} | "
            f"Deck: {deck.get('remaining', 0)}/{deck.get('total', 0)} "
            f"[{_display_name(dk)}, {run.get('stake_name')}]"
        )

    active_blind = blind.get("active")
    if active_blind and state_name in ("SELECTING_HAND", "HAND_PLAYED", "DRAW_TO_HAND", "NEW_ROUND", "ROUND_EVAL", "GAME_OVER"):
        bname = _display_name(active_blind)
        status = " [DISABLED]" if active_blind.get("disabled") else ""
        debuff = f" — {active_blind['debuff_text']}" if active_blind.get("debuff_text") else ""
        lines.append(
            f"Blind: {bname}{status} | Score: {_format_num(run.get('chips', 0))} / "
            f"{_format_num(active_blind.get('chips', 0))} (Reward ${active_blind.get('dollars', 0)}){debuff}"
        )

    if state_name == "BLIND_SELECT":
        lines.append(f"\nBlind Select (Next: {blind.get('on_deck')}):")
        for ch in blind.get("choices") or []:
            marker = ">>" if ch.get("status") == "Select" else "  "
            bname = _display_name(ch)
            extra = f" | Effect: {ch['debuff_text']}" if ch.get("debuff_text") else ""
            tag = ch.get("skip_tag")
            tag_str = ""
            if tag:
                tdesc = f" — {tag['description']}" if tag.get("description") else ""
                tag_str = f" | Skip Tag: {_display_name(tag)}{tdesc}"
            lines.append(
                f"  {marker} [{ch.get('slot')}] {bname} ({ch.get('status')}) — "
                f"Target {_format_num(ch.get('chips', 0))}, Reward ${ch.get('dollars', 0)}{extra}{tag_str}"
            )

    if state_name == "ROUND_EVAL":
        reval = state.get("round_eval") or {}
        rstatus = "READY" if reval.get("ready") else "TALLYING"
        lines.append(f"\nRound Eval [{rstatus}]: Cash Out = +${reval.get('cash_out_dollars', 0)}")

    # Jokers
    jokers_obj = state.get("jokers")
    if jokers_obj is not None:
        jcards = jokers_obj.get("cards") or []
        lines.append(f"\nJokers ({len(jcards)}/{jokers_obj.get('limit', 0)}):")
        if jcards:
            for c in jcards:
                lines.append("  " + _format_item_card(c, show_sell=True))
        else:
            lines.append("  (none)")

    # Consumables
    cons_obj = state.get("consumeables")
    if cons_obj is not None:
        ccards = cons_obj.get("cards") or []
        lines.append(f"\nConsumables ({len(ccards)}/{cons_obj.get('limit', 0)}):")
        if ccards:
            for c in ccards:
                lines.append("  " + _format_item_card(c, show_sell=True))
        else:
            lines.append("  (none)")

    # Hand
    hand_obj = state.get("hand")
    if hand_obj is not None and (hand_obj.get("cards") or state_name == "SELECTING_HAND"):
        hcards = hand_obj.get("cards") or []
        lines.append(
            f"\nHand ({len(hcards)}/{hand_obj.get('limit', 0)}, sort={hand_obj.get('sort')}):"
        )
        if hcards:
            lines.append("  " + "  ".join(_format_playing_card(c) for c in hcards))
        else:
            lines.append("  (empty)")
        preview = run.get("current_hand_preview") or {}
        if preview.get("hand_name"):
            warn = " [BOSS DEBUFFED - WILL NOT SCORE]" if preview.get("boss_debuffed") else ""
            lines.append(
                f"  Selected Preview: {preview['hand_name']} {preview.get('hand_level', '')} "
                f"({preview.get('chips')} x {preview.get('mult')}){warn}"
            )

    # Shop
    shop = state.get("shop")
    if shop and state_name == "SHOP":
        reroll_note = "FREE" if shop.get("reroll_cost", 0) == 0 else f"${shop.get('reroll_cost', 0)}"
        is_shop_ready = bool(shop.get("ready")) or (
            bool(state.get("state_complete")) and eq.get("base_blocking", 0) == 0
        )
        lines.append(
            f"\nShop [{'READY' if is_shop_ready else 'LOADING'}] | "
            f"Reroll: {reroll_note} ({'available' if shop.get('can_reroll') else 'no $'})"
        )
        lines.append("  Shop Cards:")
        if shop.get("jokers"):
            for c in shop["jokers"]:
                lines.append("    " + _format_item_card(c, show_price=True))
        else:
            lines.append("    (empty)")
        lines.append("  Vouchers:")
        if shop.get("vouchers"):
            for c in shop["vouchers"]:
                lines.append("    " + _format_item_card(c, show_price=True))
        else:
            lines.append("    (empty)")
        lines.append("  Booster Packs:")
        if shop.get("boosters"):
            for c in shop["boosters"]:
                lines.append("    " + _format_item_card(c, show_price=True))
        else:
            lines.append("    (empty)")

    # Booster Pack
    pack = state.get("pack")
    if pack and state_name in PACK_STATES:
        lines.append(
            f"\nBooster Pack [{pack.get('type')}] — Choices Left: {pack.get('choices_left')} | "
            f"Can Skip: {pack.get('can_skip')}"
        )
        pcards = pack.get("cards") or []
        if pcards:
            for c in pcards:
                lines.append("  " + _format_item_card(c))
        else:
            lines.append("  (empty)")

    # Vouchers & Tags (compact)
    vouchers = run.get("vouchers") or []
    tags = run.get("tags") or []
    if vouchers:
        lines.append("\nOwned Vouchers: " + ", ".join(_display_name(v) for v in vouchers))
    if tags:
        lines.append(
            "Active Tags: "
            + ", ".join(
                f"{_display_name(t)} ({t['description']})" if t.get("description") else _display_name(t)
                for t in tags
            )
        )

    # Poker Hands
    poker_hands = run.get("poker_hands") or []
    if poker_hands:
        if show_hands:
            lines.append("\nPoker Hands:")
            for h in poker_hands:
                lines.append(
                    f"  {h['name']:16s} Lv.{h['level']:<2d}  "
                    f"{h['chips']:>4} x {h['mult']:<4}  (played: {h['played']})"
                )
        else:
            leveled = [h for h in poker_hands if (h.get("level") or 1) > 1]
            if leveled:
                lines.append(
                    "\nUpgraded Hands: "
                    + ", ".join(f"{h['name']} Lv.{h['level']} ({h['chips']}x{h['mult']})" for h in leveled)
                )

    lines.append("\nLegal Actions: " + " | ".join(compute_legal_actions(state)))
    return "\n".join(lines)
