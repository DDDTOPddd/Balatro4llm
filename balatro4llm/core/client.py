"""Core Python client communicating with the in-game balatro4llm Lua Mod via NDJSON/TCP.

Provides:
- Thread-safe persistent keep-alive NDJSON/TCP transport with transparent reconnect (`ping`, `get_state`, `execute_action`)
- Post-action stability wait loop (`wait_until_stable`) polling G.E_MANAGER / locks / state readiness
- Optional auto-advancement of mandatory zero-choice transitions (`auto_cash_out`, `auto_select_boss`)
- Deterministic sequential batch execution (`run_batch`) with fail-fast state reporting
- High-level game action methods reusable by both CLI and MCP server
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import threading
import time
from typing import Any, Sequence

from balatro4llm.core.actions import expand_action_steps
from balatro4llm.core.errors import (
    BalatroBatchError,
    BalatroCommandError,
    BalatroConnectionError,
    BalatroError,
    BalatroTimeoutError,
)


DEFAULT_HOST = os.environ.get("BALATRO4LLM_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("BALATRO4LLM_PORT", "12345"))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


DEFAULT_COMPACT = _env_flag("BALATRO4LLM_COMPACT")
DEFAULT_AUTO_CASH_OUT = _env_flag("BALATRO4LLM_AUTO_CASH_OUT")
DEFAULT_AUTO_ADVANCE = _env_flag("BALATRO4LLM_AUTO_ADVANCE")

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


def is_win_screen(state: dict[str, Any]) -> bool:
    """Return True when the Ante 8 victory overlay menu is currently open."""
    ready = state.get("ready") or {}
    if ready.get("is_win_screen"):
        return True
    run = state.get("run") or {}
    return bool(
        ready.get("has_overlay_menu")
        and run.get("won")
        and state.get("state_name") != "GAME_OVER"
    )


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

    if ready.get("controller_locked") or ready.get("active_locks"):
        return False

    # Paused modal overlays (Ante 8 Win screen, Game Over, pause menu) freeze non-pause
    # events in G.E_MANAGER.queues.base until dismissed, so they are immediately interactive.
    if ready.get("has_overlay_menu") and (ready.get("paused") or state_name == "GAME_OVER"):
        return True

    if ready.get("in_tutorial"):
        return True

    if state_name in TRANSIENT_STATES:
        return False

    if eq.get("base_blocking", 0) > 0:
        return False

    if state_name == "GAME_OVER":
        return bool(state.get("state_complete"))

    if ready.get("has_overlay_menu"):
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
        if state_name in ("TAROT_PACK", "SPECTRAL_PACK"):
            hand = state.get("hand") or {}
            deck = state.get("deck") or {}
            if not hand.get("cards") and (deck.get("remaining", 0) > 0) and (hand.get("limit", 0) > 0):
                return False
        return True

    return True


class BalatroClient:
    """Thread-safe NDJSON-over-TCP client for the Balatro in-game Lua Mod."""

    _expand_action_steps = staticmethod(expand_action_steps)

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 5.0,
        persistent: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.persistent = persistent
        self._req_ids = itertools.count(1)
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._rx_buf = bytearray()

    def __enter__(self) -> "BalatroClient":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close any cached persistent socket."""
        with self._lock:
            self._drop_socket()

    def _drop_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._rx_buf.clear()

    def _open_socket(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    def _ensure_connected(self) -> tuple[socket.socket, bool]:
        if self._sock is not None:
            self._sock.settimeout(self.timeout)
            return self._sock, True
        self._sock = self._open_socket()
        self._rx_buf.clear()
        return self._sock, False

    @staticmethod
    def _recv_line_from_buf(sock: socket.socket, buf: bytearray) -> str:
        while True:
            nl = buf.find(b"\n")
            if nl != -1:
                raw = bytes(buf[:nl]).rstrip(b"\r")
                del buf[: nl + 1]
                if not raw:
                    raise BalatroConnectionError("Received empty response line from Mod.")
                return raw.decode("utf-8")
            chunk = sock.recv(65536)
            if not chunk:
                if buf:
                    raw = bytes(buf).rstrip(b"\r")
                    buf.clear()
                    return raw.decode("utf-8")
                raise BalatroConnectionError("Connection closed before receiving a response line.")
            buf.extend(chunk)

    def _request_once_one_shot(self, wire: bytes) -> str:
        with self._open_socket() as sock:
            sock.sendall(wire)
            return self._recv_line_from_buf(sock, bytearray())

    def _request_persistent(self, cmd: str, req_id: int, wire: bytes) -> str:
        for attempt in range(2):
            sock, reused = self._ensure_connected()
            sending = True
            try:
                sock.sendall(wire)
                sending = False
                return self._recv_line_from_buf(sock, self._rx_buf)
            except (OSError, BalatroConnectionError) as exc:
                self._drop_socket()
                can_retry = (
                    attempt == 0
                    and reused
                    and (
                        cmd in ("ping", "state")
                        or sending
                        or isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError))
                        or "Connection closed" in str(exc)
                    )
                )
                if can_retry:
                    continue
                raise BalatroConnectionError(
                    f"Cannot reach Balatro Mod at {self.host}:{self.port} ({exc}). "
                    "Make sure Balatro is running with Lovely and the balatro4llm mod installed."
                ) from exc
        raise BalatroConnectionError(f"Failed to complete request #{req_id} to {self.host}:{self.port}")

    def request(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = next(self._req_ids)
        payload = {"id": req_id, "cmd": cmd, "args": args or {}}
        wire = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")

        with self._lock:
            try:
                if self.persistent:
                    line = self._request_persistent(cmd, req_id, wire)
                else:
                    line = self._request_once_one_shot(wire)
            except BalatroConnectionError:
                raise
            except OSError as exc:
                raise BalatroConnectionError(
                    f"Cannot reach Balatro Mod at {self.host}:{self.port} ({exc}). "
                    "Make sure Balatro is running with Lovely and the balatro4llm mod installed."
                ) from exc

            try:
                resp = json.loads(line)
            except json.JSONDecodeError as exc:
                self._drop_socket()
                raise BalatroConnectionError(f"Invalid JSON received from Mod: {exc}") from exc

            if not isinstance(resp, dict):
                self._drop_socket()
                raise BalatroConnectionError(f"Unexpected response type from Mod: {type(resp).__name__}")

            resp_id = resp.get("id")
            if resp_id is not None and resp_id != req_id:
                self._drop_socket()
                raise BalatroConnectionError(f"Response ID mismatch: expected {req_id}, got {resp_id}")

        if not resp.get("ok"):
            raise BalatroCommandError(cmd, str(resp.get("error", "unknown error")), resp)

        data = resp.get("data")
        if not isinstance(data, dict):
            return {"value": data}
        return data

    # --- Low-level commands ---

    def ping(self) -> dict[str, Any]:
        return self.request("ping")

    def get_state(self) -> dict[str, Any]:
        return self.request("state")

    def execute_action(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(params or {})
        args["name"] = name
        try:
            return self.request("action", args)
        except BalatroCommandError as exc:
            # Graceful fallback when `endless` is sent to an already-running v0.5.0 Mod instance
            if name == "endless" and "unknown action" in exc.message:
                cur = self.get_state()
                if is_win_screen(cur):
                    return self.request("action", {"name": "dismiss_overlay"})
            raise

    def wait_until_stable(
        self,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.03,
        initial_delay: float = 0.04,
        required_streak: int = 2,
    ) -> dict[str, Any]:
        """Poll `state` until animations/events finish and the game settles into an actionable state."""
        deadline = time.monotonic() + timeout
        if initial_delay > 0:
            time.sleep(initial_delay)

        streak = 0
        last_key: tuple[Any, ...] | None = None
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

    def auto_advance_state(
        self,
        state: dict[str, Any],
        *,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
        wait_timeout: float = 30.0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Automatically advance trivial zero-choice states (ROUND_EVAL cash-out / mandatory Boss select)."""
        steps: list[dict[str, Any]] = []
        if not auto_cash_out and not auto_select_boss:
            return steps, state

        for _ in range(3):
            ready = state.get("ready") or {}
            if ready.get("has_overlay_menu") or ready.get("in_tutorial"):
                break
            state_name = state.get("state_name")

            if auto_cash_out and state_name == "ROUND_EVAL" and ready.get("round_eval_ready"):
                receipt = self.execute_action("cash_out", {})
                steps.append(receipt)
                state = self.wait_until_stable(timeout=wait_timeout, initial_delay=0.04)
                continue

            if auto_select_boss and state_name == "BLIND_SELECT" and ready.get("blind_select_ready"):
                blind = state.get("blind") or {}
                if blind.get("on_deck") == "Boss" and not blind.get("can_reroll_boss"):
                    receipt = self.execute_action("select_blind", {})
                    steps.append(receipt)
                    state = self.wait_until_stable(timeout=wait_timeout, initial_delay=0.04)
                    continue

            break

        return steps, state

    def _wait_after_action(self, name: str, wait_timeout: float) -> dict[str, Any]:
        if name in ("sort_hand", "reorder_jokers", "reorder_hand", "move_joker", "move_hand", "set_speed"):
            return self.wait_until_stable(timeout=wait_timeout, initial_delay=0.025, required_streak=1)
        init_delay = 0.25 if name in ("start", "continue", "main_menu") else 0.04
        return self.wait_until_stable(timeout=wait_timeout, initial_delay=init_delay)

    def perform_action(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute an atomic (or composite) action, optionally wait + auto-advance, and return (receipt, state)."""
        expanded = self._expand_action_steps([(name, params or {})])
        if len(expanded) > 1:
            if not wait:
                raise BalatroError(f"Composite action '{name}' requires waiting between steps (cannot use --no-wait).")
            completed, auto_steps, state = self.run_batch(
                expanded,
                wait_timeout=wait_timeout,
                auto_cash_out=auto_cash_out,
                auto_select_boss=auto_select_boss,
            )
            receipt = dict(completed[0])
            receipt["batch_steps"] = completed
            if auto_steps:
                receipt["auto_steps"] = auto_steps
            return receipt, state

        act_name, act_params = expanded[0]
        receipt = self.execute_action(act_name, act_params)
        if wait:
            state = self._wait_after_action(act_name, wait_timeout)
            auto_steps, state = self.auto_advance_state(
                state,
                auto_cash_out=auto_cash_out,
                auto_select_boss=auto_select_boss,
                wait_timeout=wait_timeout,
            )
            if auto_steps:
                receipt = dict(receipt)
                receipt["auto_steps"] = auto_steps
        else:
            state = self.get_state()
        return receipt, state

    def run_batch(
        self,
        steps: Sequence[tuple[str, dict[str, Any]]],
        *,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Execute a deterministic sequence of actions, waiting until stable after each step.

        Fail-fast: if any step fails, immediately fetches current state and raises BalatroBatchError.
        Returns (completed_receipts, auto_steps, final_state).
        """
        expanded = self._expand_action_steps(steps)
        if not expanded:
            raise BalatroError("Batch must contain at least one action step.")

        completed: list[dict[str, Any]] = []
        state: dict[str, Any] | None = None

        for idx, (action_name, params) in enumerate(expanded, start=1):
            try:
                receipt = self.execute_action(action_name, params)
                state = self._wait_after_action(action_name, wait_timeout)
                completed.append(receipt)
            except BalatroError as exc:
                live_state = getattr(exc, "last_state", None)
                if live_state is None:
                    try:
                        live_state = self.get_state()
                    except BalatroError:
                        live_state = state
                raise BalatroBatchError(idx, action_name, str(exc), completed, live_state) from exc

        assert state is not None
        auto_steps, state = self.auto_advance_state(
            state,
            auto_cash_out=auto_cash_out,
            auto_select_boss=auto_select_boss,
            wait_timeout=wait_timeout,
        )
        return completed, auto_steps, state

    # --- High-level action methods (shared by CLI, MCP, and scripts) ---

    def start_run(
        self,
        *,
        deck: str | None = None,
        stake: int | str = 1,
        seed: str | None = None,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"stake": stake}
        if deck:
            params["deck"] = deck
        if seed:
            params["seed"] = seed
        return self.perform_action(
            "start", params, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def continue_run(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "continue", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def go_to_menu(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("main_menu", {}, wait=wait, wait_timeout=wait_timeout)

    def enter_endless(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "endless", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def dismiss_overlay(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "dismiss_overlay", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def select_blind(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("select_blind", {}, wait=wait, wait_timeout=wait_timeout)

    def skip_blind(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "skip_blind", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def reroll_boss(
        self, *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("reroll_boss", {}, wait=wait, wait_timeout=wait_timeout)

    def play(
        self,
        cards: Sequence[int],
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "play", {"cards": list(cards)}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def discard(
        self, cards: Sequence[int], *, wait: bool = True, wait_timeout: float = 30.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("discard", {"cards": list(cards)}, wait=wait, wait_timeout=wait_timeout)

    def sort_hand(
        self, by: str = "rank", *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action("sort_hand", {"by": by}, wait=wait, wait_timeout=wait_timeout)

    def set_speed(
        self, speed: float, *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        spd = int(speed) if float(speed).is_integer() else float(speed)
        return self.perform_action("set_speed", {"speed": spd}, wait=wait, wait_timeout=wait_timeout)

    def move_joker(
        self, from_index: int, to_index: int, *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "move_joker", {"from": from_index, "to": to_index}, wait=wait, wait_timeout=wait_timeout
        )

    def move_hand(
        self, from_index: int, to_index: int, *, wait: bool = True, wait_timeout: float = 10.0
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "move_hand", {"from": from_index, "to": to_index}, wait=wait, wait_timeout=wait_timeout
        )

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
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"index": index}
        if targets:
            params["targets"] = list(targets)
        return self.perform_action(
            "use", params, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def cash_out(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "cash_out", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def buy(
        self,
        index: int,
        *,
        use: bool = False,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "buy", {"index": index, "use": use}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

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
        self,
        *,
        select: bool = False,
        skip: bool = False,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if select and skip:
            raise BalatroError("next_round cannot set both select=True and skip=True")
        params: dict[str, Any] = {}
        if select:
            params["select"] = True
        elif skip:
            params["skip"] = True
        return self.perform_action(
            "next_round", params, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def pick(
        self,
        index: int,
        targets: Sequence[int] | None = None,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"index": index}
        if targets:
            params["targets"] = list(targets)
        return self.perform_action(
            "pick", params, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )

    def skip_pack(
        self,
        *,
        wait: bool = True,
        wait_timeout: float = 30.0,
        auto_cash_out: bool = False,
        auto_select_boss: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.perform_action(
            "skip_pack", {}, wait=wait, wait_timeout=wait_timeout,
            auto_cash_out=auto_cash_out, auto_select_boss=auto_select_boss,
        )
