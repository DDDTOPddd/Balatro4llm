"""LLM-friendly state, ping, speed receipt, and legal-action formatters."""

from __future__ import annotations

from typing import Any, Sequence

from balatro4llm.core.client import PACK_STATES, is_win_screen
from balatro4llm.core.errors import BalatroBatchError


RANK_ORDER = ("A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2")

HAND_SHORT: dict[str, str] = {
    "High Card": "HC",
    "Pair": "Pair",
    "Two Pair": "2Pair",
    "Three of a Kind": "3oaK",
    "Straight": "Straight",
    "Flush": "Flush",
    "Full House": "FullHouse",
    "Four of a Kind": "4oaK",
    "Straight Flush": "StrFlush",
    "Five of a Kind": "5oaK",
    "Flush House": "FlushHouse",
    "Flush Five": "Flush5",
}


def _display_name(item: dict[str, Any], *, compact: bool = False) -> str:
    name = str(item.get("name") or "")
    loc = str(item.get("loc_name") or "")
    if compact:
        if name and name != "ERROR":
            return name
        if loc and loc != "ERROR":
            return loc
        return "?"
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


def format_ping(data: dict[str, Any], rtt_ms: float) -> str:
    """Format a ping response into concise health telemetry."""
    stage_name = data.get("stage_name") or str(data.get("stage"))
    state_name = data.get("state_name") or str(data.get("state"))
    gs = data.get("gamespeed")
    gs_str = f"{float(gs):g}x" if isinstance(gs, (int, float)) else "?"
    lines = [
        f"PONG from balatro4llm v{data.get('mod_version')} ({rtt_ms:.1f} ms)",
        f"  Game Version : {data.get('game_version')}",
        f"  Stage / State: {stage_name} ({data.get('stage')}) / {state_name} ({data.get('state')})",
        f"  State Ready  : {data.get('state_complete')} | Paused: {data.get('paused')}",
        f"  Game Speed   : {gs_str}",
        f"  FPS / Uptime : {data.get('fps')} fps / {data.get('uptime', 0):.1f}s",
    ]
    return "\n".join(lines)


def format_speed_receipt(receipt: dict[str, Any] | None) -> str | None:
    """Return a formatted speed transition line when receipt came from `set_speed`."""
    if not receipt or receipt.get("action") != "set_speed":
        return None
    prev_s = receipt.get("previous_speed", "?")
    new_s = receipt.get("speed", "?")
    note = "saved" if receipt.get("persisted") else "runtime-only turbo"
    if isinstance(prev_s, (int, float)) and isinstance(new_s, (int, float)):
        return f"[speed] {prev_s:g}x -> {new_s:g}x ({note})"
    return f"[speed] {prev_s}x -> {new_s}x ({note})"


def format_batch_error(exc: BalatroBatchError, *, compact: bool = False) -> str:
    """Format a fail-fast batch error including completed steps and live game state."""
    parts = [f"Error: {exc}"]
    if exc.completed:
        done = " -> ".join(str(s.get("action")) for s in exc.completed)
        parts.append(f"Completed before failure: {done}")
    if exc.last_state is not None:
        parts.append(format_state(exc.last_state, compact=compact))
    return "\n".join(parts)


def format_deck_composition(deck: dict[str, Any] | None) -> str | None:
    """Format remaining draw-pile composition into a single compact ~35-token line."""
    if not deck or not isinstance(deck.get("composition"), dict):
        return None
    comp = deck["composition"]
    suits = comp.get("suits") or {}
    ranks = comp.get("ranks") or {}
    special = comp.get("special") or []

    rem = int(deck.get("remaining", 0))
    tot = int(deck.get("total", 0))
    prefix = f"Deck Left ({rem})" if rem < tot else f"Deck ({rem})"

    suit_parts = [f"{s}:{suits.get(s, 0)}" for s in ("S", "H", "C", "D")]
    if suits.get("Stone", 0):
        suit_parts.append(f"Stone:{suits['Stone']}")

    rank_parts = [f"{r}:{ranks[r]}" for r in RANK_ORDER if ranks.get(r, 0) > 0]

    segments = [f"{prefix}: {' '.join(suit_parts)}"]
    if rank_parts:
        segments.append(" ".join(rank_parts))
    if special:
        spec_parts = [
            f"{sp['label']}x{sp['count']}" if sp.get("count", 1) > 1 else str(sp["label"])
            for sp in special
        ]
        segments.append("Special: " + ", ".join(spec_parts))
    return " | ".join(segments)


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


def _resolve_next_blind_slot(blind: dict[str, Any]) -> str | None:
    """Resolve the next active/upcoming blind slot even while in SHOP (before BLIND_SELECT updates blind_on_deck)."""
    on_deck = blind.get("on_deck")
    choices = blind.get("choices") or []
    by_slot = {ch.get("slot"): ch for ch in choices if ch.get("slot")}
    if on_deck and on_deck in by_slot:
        st = by_slot[on_deck].get("status")
        if st not in ("Defeated", "Skipped", "Hide"):
            return str(on_deck)
    for slot in ("Small", "Big", "Boss"):
        ch = by_slot.get(slot)
        if ch and ch.get("status") not in ("Defeated", "Skipped", "Hide"):
            return slot
    return str(on_deck) if on_deck else None


def _format_shop_blind_preview(blind: dict[str, Any], *, compact: bool = False) -> list[str]:
    """Build 1-2 compact preview lines of the next blind (with Skip Tag) and Ante Boss while in SHOP."""
    choices = blind.get("choices") or []
    if not choices:
        return []
    by_slot = {ch.get("slot"): ch for ch in choices if ch.get("slot")}
    next_slot = _resolve_next_blind_slot(blind)
    next_ch = by_slot.get(next_slot) if next_slot else None
    boss_ch = by_slot.get("Boss")
    reroll_tag = " [can reroll-boss $10]" if blind.get("can_reroll_boss") else ""

    out: list[str] = []
    if next_ch and next_ch.get("slot") != "Boss":
        bname = _display_name(next_ch, compact=compact)
        tag = next_ch.get("skip_tag")
        tag_str = ""
        if tag:
            tdesc = f" — {tag['description']}" if tag.get("description") else ""
            tag_str = f" | Skip: {_display_name(tag, compact=compact)}{tdesc}"
        out.append(
            f"Next: [{next_ch.get('slot')}] {bname} "
            f"({_format_num(next_ch.get('chips', 0))}, ${next_ch.get('dollars', 0)}{tag_str})"
        )
        if boss_ch:
            boss_name = _display_name(boss_ch, compact=compact)
            debuff = f" — {boss_ch['debuff_text']}" if boss_ch.get("debuff_text") else ""
            out.append(
                f"Boss: {boss_name} "
                f"({_format_num(boss_ch.get('chips', 0))}, ${boss_ch.get('dollars', 0)}){debuff}{reroll_tag}"
            )
    elif boss_ch:
        boss_name = _display_name(boss_ch, compact=compact)
        debuff = f" — {boss_ch['debuff_text']}" if boss_ch.get("debuff_text") else ""
        out.append(
            f"Next: [Boss] {boss_name} "
            f"({_format_num(boss_ch.get('chips', 0))}, ${boss_ch.get('dollars', 0)}){debuff}{reroll_tag}"
        )
    return out


def _fallback_joker_hand_stats(
    card: dict[str, Any],
    poker_hands: Sequence[dict[str, Any]] | None,
    *,
    in_selecting: bool = False,
) -> str | None:
    """Compute live hand-count stats from `run.poker_hands` when older Mod snapshots omit them."""
    if not poker_hands:
        return None
    name = card.get("name")
    existing = str(card.get("compact_stats") or "")
    if name == "Supernova" and not existing:
        played = [h for h in poker_hands if (h.get("played") or 0) > 0]
        played.sort(key=lambda h: -(h.get("played") or 0))
        if not played:
            return "+0M"
        return "/".join(
            f"{HAND_SHORT.get(h['name'], h['name'])}:+{h['played']}M"
            for h in played[:2]
        )
    if name == "Obelisk" and "avoid:" not in existing:
        max_p = max((int(h.get("played") or 0) for h in poker_hands), default=0)
        if max_p > 0:
            avoid = [
                HAND_SHORT.get(h["name"], h["name"])
                for h in poker_hands
                if int(h.get("played") or 0) == max_p
            ][:3]
            avoid_str = f"avoid:{'/'.join(avoid)}({max_p})"
            return f"{existing},{avoid_str}" if existing else avoid_str
    if name == "Card Sharp" and in_selecting and "on:" not in existing:
        armed = [
            HAND_SHORT.get(h["name"], h["name"])
            for h in poker_hands
            if int(h.get("played_this_round") or 0) > 0
        ]
        if armed:
            base = existing or "X3M"
            return f"{base}(on:{'/'.join(armed)})"
    return existing or None


def _format_joker_inline_compact(
    card: dict[str, Any],
    *,
    show_sell: bool = False,
    show_copyable: bool = False,
    poker_hands: Sequence[dict[str, Any]] | None = None,
    in_selecting: bool = False,
) -> str:
    idx = card.get("index", "?")
    title = _display_name(card, compact=True)
    tags: list[str] = []
    cstats = _fallback_joker_hand_stats(card, poker_hands, in_selecting=in_selecting)
    if cstats:
        tags.append(cstats)
    elif card.get("blueprint_compat") == "compatible":
        tags.append("compat")
    elif card.get("blueprint_compat") == "incompatible":
        tags.append("INCOMPAT")
    if show_copyable and card.get("copyable") is False:
        tags.append("no-copy")
    if card.get("edition"):
        tags.append(str(card["edition"]))
    if card.get("debuff"):
        tags.append("DEBUFF")
    if card.get("eternal"):
        tags.append("Eternal")
    if card.get("perishable"):
        tally = card.get("perish_tally")
        tags.append(f"Perish:{tally}" if tally is not None else "Perish")
    if card.get("rental"):
        tags.append("Rental")
    if show_sell:
        sell_cost = card.get("sell_cost", 0)
        if not card.get("can_sell", True):
            tags.append(f"sell:${sell_cost}/locked")
        else:
            tags.append(f"sell:${sell_cost}")
    suffix = f"({','.join(tags)})" if tags else ""
    return f"[{idx}]{title}{suffix}"


def _format_consumable_inline_compact(
    card: dict[str, Any],
    *,
    show_sell: bool = False,
) -> str:
    """Format an owned Tarot/Planet/Spectral consumable onto a concise inline token."""
    idx = card.get("index", "?")
    title = _display_name(card, compact=True)
    tags: list[str] = []
    cstats = card.get("compact_stats")
    if not cstats and card.get("hand_type"):
        ht = str(card["hand_type"])
        cstats = HAND_SHORT.get(ht, ht)
    if cstats:
        tags.append(str(cstats))
    if card.get("edition"):
        tags.append(str(card["edition"]))
    if card.get("can_use") is not None:
        max_h = card.get("max_highlighted")
        min_h = card.get("min_highlighted") or 1
        if card.get("can_use"):
            tags.append("usable")
        elif card.get("can_use_with_targets") and max_h:
            tags.append(f"use:{max_h}" if min_h == max_h else f"use:{min_h}..{max_h}")
        else:
            tags.append("no-use")
    if show_sell:
        sell_cost = card.get("sell_cost", 0)
        if not card.get("can_sell", True):
            tags.append(f"sell:${sell_cost}/locked")
        else:
            tags.append(f"sell:${sell_cost}")
    suffix = f"({','.join(tags)})" if tags else ""
    return f"[{idx}]{title}{suffix}"


def _format_shop_price_tag(card: dict[str, Any]) -> str:
    cost = card.get("cost", 0)
    affordable = card.get("affordable")
    has_space = card.get("has_space")
    can_buy_and_use = bool(card.get("can_buy_and_use"))

    if affordable is not None or has_space is not None:
        aff = True if affordable is None else bool(affordable)
        spc = True if has_space is None else bool(has_space)
        if not aff and not spc:
            return f"${cost} [no $, slots full]"
        if not aff:
            return f"${cost} [no $]"
        if not spc:
            if can_buy_and_use:
                return f"${cost} [slots full; --use OK]"
            return f"${cost} [slots full]"
        return f"${cost}"

    # Fallback for older Mod responses without separate affordable/has_space flags
    if card.get("can_buy", True):
        return f"${cost}"
    if can_buy_and_use:
        return f"${cost} [slots full; --use OK]"
    return f"${cost} [no $/slots full]"


def _format_item_card(
    card: dict[str, Any],
    *,
    show_price: bool = False,
    show_sell: bool = False,
    compact: bool = False,
    show_copyable: bool = False,
) -> str:
    idx = card.get("index", "?")
    if card.get("kind") == "PlayingCard":
        base = _format_playing_card(card)
        if show_price:
            affordable = card.get("affordable")
            if affordable is None:
                affordable = card.get("can_buy", True)
            afford = "" if affordable else " [no $]"
            return f"{base} - ${card.get('cost', 0)}{afford}"
        return base

    title = _display_name(card, compact=compact)
    tags: list[str] = []
    if card.get("kind") and card.get("kind") not in ("Joker", "Voucher", "Booster"):
        tags.append(str(card["kind"]))
    if card.get("blueprint_compat") == "compatible":
        tags.append("compat")
    elif card.get("blueprint_compat") == "incompatible":
        tags.append("INCOMPAT")
    if show_copyable and card.get("copyable") is False:
        tags.append("no-copy")
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
        tags.append(_format_shop_price_tag(card))
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
                use_str = f"usable (select {max_h})" if compact else f"usable (select {max_h} hand card{'s' if max_h > 1 else ''})"
            else:
                use_str = f"usable (select {min_h}..{max_h})" if compact else f"usable (select {min_h}..{max_h} hand cards)"
        else:
            use_str = "not-usable"
            if max_h:
                if min_h == max_h:
                    use_str += f" (needs {max_h})" if compact else f" (needs {max_h} hand card{'s' if max_h > 1 else ''})"
                else:
                    use_str += f" (needs {min_h}..{max_h})" if compact else f" (needs {min_h}..{max_h} hand cards)"
        tags.append(use_str)

    tag_str = f" [{', '.join(tags)}]" if tags else ""
    desc = card.get("description")
    desc_str = f" — {desc}" if desc else ""
    return f"[{idx}] {title}{tag_str}{desc_str}"


def format_auto_steps(auto_steps: Sequence[dict[str, Any]]) -> str:
    parts: list[str] = []
    for st in auto_steps:
        act = st.get("action")
        if act == "cash_out":
            parts.append(f"cash-out (+${st.get('dollars', 0)})")
        elif act == "select_blind":
            parts.append(f"select-blind ({st.get('slot', 'Boss')})")
        elif act == "skip_blind":
            parts.append(f"skip-blind ({st.get('slot', '?')})")
        else:
            parts.append(str(act))
    return "[auto] " + " -> ".join(parts)


def compute_legal_actions(state: dict[str, Any], *, compact: bool = False) -> list[str]:
    """Infer high-level legal CLI/MCP actions from a state snapshot."""
    stage_name = state.get("stage_name")
    state_name = state.get("state_name")
    ready = state.get("ready") or {}
    eq = ready.get("event_queues") or {}
    actions: list[str] = []

    if ready.get("in_tutorial"):
        actions.append("dismiss-overlay" if compact else "wait / advance tutorial overlay (tutorial active)")
    if stage_name == "MAIN_MENU":
        menu = state.get("menu") or {}
        if menu.get("has_saved_run"):
            actions.append("continue" if compact else "continue (resume saved run)")
        actions.append("start" if compact else "start [--deck <key>] [--stake <1-8>] [--seed <seed>]")
        return actions

    if stage_name != "RUN":
        return ["wait"] if compact else ["wait (non-interactive stage)"]

    if state_name == "GAME_OVER":
        return ["start", "main-menu"] if compact else ["start [--deck <key>] [--stake <1-8>] (new run)", "main-menu"]

    if is_win_screen(state):
        if compact:
            return ["endless", "start", "main-menu"]
        return [
            "endless (continue into Endless Mode)",
            "start [--deck <key>] [--stake <1-8>] (new run)",
            "main-menu",
        ]

    if ready.get("has_overlay_menu"):
        return ["dismiss-overlay", "start", "main-menu"] if compact else ["dismiss-overlay (close popup)", "start (new run)", "main-menu"]

    if eq.get("base_blocking", 0) > 0 or ready.get("controller_locked"):
        return [
            f"wait (animating: base_blocking={eq.get('base_blocking', 0)}, "
            f"locked={ready.get('controller_locked')})"
        ]

    if state_name == "BLIND_SELECT":
        blind = state.get("blind") or {}
        on_deck = _resolve_next_blind_slot(blind)
        actions.append(f"select-blind({on_deck or 'current'})" if compact else f"select-blind ({on_deck or 'current'})")
        if on_deck in ("Small", "Big"):
            actions.append(f"skip-blind({on_deck})" if compact else f"skip-blind ({on_deck})")
        if blind.get("can_reroll_boss"):
            actions.append("reroll-boss($10)" if compact else "reroll-boss ($10)")
    elif state_name == "SELECTING_HAND":
        run = state.get("run") or {}
        hand_cards = (state.get("hand") or {}).get("cards") or []
        if hand_cards and not ready.get("block_play"):
            actions.append("play" if compact else "play <idx...> (1..5 cards)")
        if hand_cards and (run.get("discards_left") or 0) > 0:
            actions.append("discard" if compact else "discard <idx...> (1..5 cards)")
        actions.append("sort-hand" if compact else "sort-hand <rank|suit>")
        if len(hand_cards) > 1:
            actions.append("move-hand" if compact else "move-hand <from> <to>")
    elif state_name == "ROUND_EVAL":
        if ready.get("round_eval_ready"):
            dollars = (state.get("round_eval") or {}).get("cash_out_dollars", 0)
            actions.append(f"cash-out(+${dollars})" if compact else f"cash-out (+${dollars})")
        else:
            actions.append("wait" if compact else "wait (round evaluation tallying)")
    elif state_name == "SHOP":
        shop = state.get("shop") or {}
        shop_ready = bool(ready.get("shop_ready")) or (
            bool(state.get("state_complete"))
            and eq.get("base_blocking", 0) == 0
            and bool(shop)
        )
        if not shop_ready:
            return ["wait (shop loading)"]
        if any(c.get("can_buy") or c.get("can_buy_and_use") for c in shop.get("jokers") or []):
            actions.append("buy" if compact else "buy <idx> [--use]")
        if any(c.get("can_buy") for c in shop.get("vouchers") or []):
            actions.append("buy-voucher" if compact else "buy-voucher [idx]")
        if any(c.get("can_buy") for c in shop.get("boosters") or []):
            actions.append("buy-pack" if compact else "buy-pack <idx>")
        if shop.get("can_reroll"):
            rc = shop.get("reroll_cost", 0)
            rc_str = "FREE" if rc == 0 else f"${rc}"
            actions.append(f"reroll({rc_str})" if compact else f"reroll ({rc_str})")
        next_slot = _resolve_next_blind_slot(state.get("blind") or {})
        if next_slot in ("Small", "Big"):
            actions.append("next-round [--select|--skip]")
        else:
            actions.append("next-round [--select]")
    elif state_name in PACK_STATES:
        pack = state.get("pack") or {}
        if not ready.get("pack_ready"):
            return ["wait (pack opening)"]
        if any(c.get("can_select", True) for c in pack.get("cards") or []):
            actions.append("pick" if compact else "pick <idx> [target_hand_idx...]")
        if pack.get("can_skip"):
            actions.append("skip-pack")
        hand_cards = (state.get("hand") or {}).get("cards") or []
        if len(hand_cards) > 1:
            actions.append("move-hand" if compact else "move-hand <from> <to>")
    else:
        return [f"wait (transient state: {state_name})"]

    if state_name in ("SELECTING_HAND", "SHOP", "BLIND_SELECT") or state_name in PACK_STATES:
        jokers = (state.get("jokers") or {}).get("cards") or []
        if any(j.get("can_sell") for j in jokers):
            actions.append("sell-joker" if compact else "sell-joker <idx>")
        if len(jokers) > 1:
            actions.append("move-joker" if compact else "move-joker <from> <to>")
        cons = (state.get("consumeables") or {}).get("cards") or []
        if any(c.get("can_use") or c.get("can_use_with_targets") for c in cons):
            actions.append("use" if compact else "use <idx> [target_hand_idx...]")
        if any(c.get("can_sell") for c in cons):
            actions.append("sell-consumable" if compact else "sell-consumable <idx>")

    return actions


def format_state(
    state: dict[str, Any],
    *,
    show_hands: bool = False,
    compact: bool = False,
    auto_steps: Sequence[dict[str, Any]] | None = None,
    batch_steps: Sequence[dict[str, Any]] | None = None,
) -> str:
    """Format a state snapshot into concise, LLM-friendly text (normal or --compact)."""
    lines: list[str] = []
    if batch_steps:
        bnames = [str(s.get("action", "?")) for s in batch_steps]
        lines.append(f"[batch] executed {len(bnames)} steps: {' -> '.join(bnames)}")
    if auto_steps:
        lines.append(format_auto_steps(auto_steps))

    stage_name = state.get("stage_name") or str(state.get("stage"))
    state_name = state.get("state_name") or str(state.get("state"))
    ready = state.get("ready") or {}
    eq = ready.get("event_queues") or {}

    win_screen = is_win_screen(state)
    header = f"=== BALATRO [{stage_name} / {'WIN_SCREEN' if win_screen else state_name}]"
    flags: list[str] = []
    if ready.get("paused") and not win_screen and state_name != "GAME_OVER":
        flags.append("PAUSED")
    if ready.get("has_overlay_menu") and not win_screen and state_name != "GAME_OVER":
        flags.append("OVERLAY")
    if ready.get("in_tutorial"):
        flags.append("TUTORIAL")
    if eq.get("base_blocking", 0) > 0 and not (ready.get("paused") and ready.get("has_overlay_menu")):
        flags.append(f"BUSY:{eq['base_blocking']}")
    if ready.get("active_locks"):
        flags.append(f"LOCKS:{','.join(ready['active_locks'])}")
    if flags:
        header += f" ({' | '.join(flags)})"
    header += " ==="
    lines.append(header)

    if win_screen:
        lines.append("*** YOU WIN! Ante 8 Cleared — Choose: endless | start (new-run) | main-menu ***")
    elif state_name == "GAME_OVER":
        lines.append("*** GAME OVER — Choose: start (new-run) | main-menu ***")

    summary = state.get("run_summary")
    if isinstance(summary, dict):
        lines.append(
            f"Run Summary: Best Hand {_format_num(summary.get('best_hand', 0))} | "
            f"Most Played: {summary.get('most_played_hand') or '?'} | "
            f"Played: {summary.get('cards_played', 0)} | Discarded: {summary.get('cards_discarded', 0)} | "
            f"Bought: {summary.get('cards_purchased', 0)} | Rerolls: {summary.get('times_rerolled', 0)} | "
            f"Seed: {summary.get('seed') or '?'}"
        )

    gamespeed = state.get("gamespeed")
    speed_tag = ""
    if isinstance(gamespeed, (int, float)) and gamespeed != 1:
        speed_tag = f" | Speed:{float(gamespeed):g}x"

    if stage_name == "MAIN_MENU":
        menu = state.get("menu") or {}
        sel = menu.get("selected_deck") or {}
        stakes = menu.get("stakes") or []
        stake_short: dict[int, str] = {}
        for sp in stakes:
            idx_s = int(sp.get("stake") or 0)
            sname = str(sp.get("name") or f"Stake {idx_s}").removesuffix(" Stake")
            stake_short[idx_s] = sname

        def _fmt_stake_range(d: dict[str, Any]) -> str:
            ms = d.get("max_stake")
            if ms is None:
                return ""
            ms_i = int(ms)
            lbl = stake_short.get(ms_i, str(ms_i))
            if ms_i <= 1:
                return f"1:{lbl}"
            return f"1..{ms_i}:{lbl}"

        lines.append(f"Profile: {menu.get('profile')} | Saved Run: {menu.get('has_saved_run')}{speed_tag}")
        sel_sr = _fmt_stake_range(sel)
        sel_sr_str = f" (stakes:{sel_sr})" if sel_sr else ""
        lines.append(f"Selected Deck: {_display_name(sel, compact=compact)} [{sel.get('key')}]{sel_sr_str}")
        if stakes:
            if compact:
                st_str = " | ".join(f"{s['stake']}:{stake_short.get(int(s['stake']), s.get('name'))}" for s in stakes)
                lines.append(f"Stakes: {st_str}")
            else:
                lines.append("Stakes:")
                for s in stakes:
                    sdesc = f" — {s['description']}" if s.get("description") else ""
                    lines.append(f"  [{s.get('stake')}] {_display_name(s, compact=False)}{sdesc}")
        decks = menu.get("unlocked_decks") or []
        if decks:
            deck_parts = []
            for d in decks:
                sr = _fmt_stake_range(d)
                dlabel = _display_name(d, compact=compact)
                deck_parts.append(f"{d.get('key')}({dlabel}, {sr})" if sr else f"{d.get('key')}({dlabel})")
            lines.append(f"Unlocked Decks ({len(decks)}): " + ", ".join(deck_parts))
        lines.append(
            ("Actions: " if compact else "Legal Actions: ")
            + " | ".join(compute_legal_actions(state, compact=compact))
        )
        return "\n".join(lines)

    run = state.get("run") or {}
    blind = state.get("blind") or {}
    deck = state.get("deck") or {}
    poker_hands = run.get("poker_hands") or []

    if run:
        dk = run.get("deck") or {}
        bankrupt_at = run.get("bankrupt_at", 0)
        money_str = f"${run.get('dollars', 0)}"
        if not compact or bankrupt_at != 0:
            money_str += f" (min ${bankrupt_at})"
        prob = run.get("probabilities_normal", 1)
        prob_tag = f" | Prob:{float(prob):g}x" if isinstance(prob, (int, float)) and prob > 1 else ""
        if compact:
            lines.append(
                f"Ante {run.get('ante')}/{run.get('win_ante')} R{run.get('round')} | "
                f"{money_str} | Hands:{run.get('hands_left')} Discards:{run.get('discards_left')} | "
                f"Deck:{deck.get('remaining', 0)}/{deck.get('total', 0)} [{_display_name(dk, compact=True)}]{prob_tag}{speed_tag}"
            )
        else:
            lines.append(
                f"Ante {run.get('ante')}/{run.get('win_ante')} | Round {run.get('round')} | "
                f"{money_str} | Hands: {run.get('hands_left')} | Discards: {run.get('discards_left')} | "
                f"Deck: {deck.get('remaining', 0)}/{deck.get('total', 0)} "
                f"[{_display_name(dk)}, {run.get('stake_name')}]{prob_tag}{speed_tag}"
            )

    active_blind = blind.get("active")
    if active_blind and state_name in ("SELECTING_HAND", "HAND_PLAYED", "DRAW_TO_HAND", "NEW_ROUND", "ROUND_EVAL", "GAME_OVER"):
        bname = _display_name(active_blind, compact=compact)
        status = " [DISABLED]" if active_blind.get("disabled") else ""
        debuff = f" — {active_blind['debuff_text']}" if active_blind.get("debuff_text") else ""
        lines.append(
            f"Blind: {bname}{status} | Score: {_format_num(run.get('chips', 0))} / "
            f"{_format_num(active_blind.get('chips', 0))} (Reward ${active_blind.get('dollars', 0)}){debuff}"
        )
        played_eye = active_blind.get("played_hands") or []
        if played_eye:
            lines.append("  Already Played (The Eye - banned): " + ", ".join(played_eye))

    if state_name == "BLIND_SELECT":
        lines.append(f"\nBlind Select (Next: {blind.get('on_deck')}):")
        for ch in blind.get("choices") or []:
            marker = ">>" if ch.get("status") == "Select" else "  "
            bname = _display_name(ch, compact=compact)
            extra = f" | Effect: {ch['debuff_text']}" if ch.get("debuff_text") else ""
            tag = ch.get("skip_tag")
            tag_str = ""
            if tag:
                tdesc = f" — {tag['description']}" if tag.get("description") else ""
                tag_str = f" | Skip: {_display_name(tag, compact=compact)}{tdesc}"
            lines.append(
                f"  {marker} [{ch.get('slot')}] {bname} ({ch.get('status')}) — "
                f"Target {_format_num(ch.get('chips', 0))}, ${ch.get('dollars', 0)}{extra}{tag_str}"
            )

    if state_name == "ROUND_EVAL":
        reval = state.get("round_eval") or {}
        rstatus = "READY" if reval.get("ready") else "TALLYING"
        lines.append(f"\nRound Eval [{rstatus}]: Cash Out = +${reval.get('cash_out_dollars', 0)}")

    # Jokers
    jokers_obj = state.get("jokers")
    has_copier = False
    joker_names: set[str] = set()
    in_hand_focus = state_name in ("SELECTING_HAND", "TAROT_PACK", "SPECTRAL_PACK")
    if jokers_obj is not None:
        jcards = jokers_obj.get("cards") or []
        joker_names = {str(c.get("name") or "") for c in jcards}
        has_copier = bool(joker_names & {"Blueprint", "Brainstorm"})
        if compact:
            if jcards:
                inline = " | ".join(
                    _format_joker_inline_compact(
                        c,
                        show_sell=not in_hand_focus,
                        show_copyable=has_copier,
                        poker_hands=poker_hands,
                        in_selecting=(state_name == "SELECTING_HAND"),
                    )
                    for c in jcards
                )
                lines.append(f"Jokers ({len(jcards)}/{jokers_obj.get('limit', 0)}): {inline}")
            else:
                lines.append(f"Jokers (0/{jokers_obj.get('limit', 0)}): (none)")
        else:
            lines.append(f"\nJokers ({len(jcards)}/{jokers_obj.get('limit', 0)}):")
            if jcards:
                for c in jcards:
                    lines.append(
                        "  " + _format_item_card(c, show_sell=True, compact=compact, show_copyable=has_copier)
                    )
            else:
                lines.append("  (none)")

    # Consumables
    cons_obj = state.get("consumeables")
    if cons_obj is not None:
        ccards = cons_obj.get("cards") or []
        if compact:
            if ccards:
                inline = " | ".join(
                    _format_consumable_inline_compact(c, show_sell=not in_hand_focus)
                    for c in ccards
                )
                lines.append(f"Consumables ({len(ccards)}/{cons_obj.get('limit', 0)}): {inline}")
            else:
                lines.append(f"Consumables (0/{cons_obj.get('limit', 0)}): (none)")
        else:
            lines.append(f"\nConsumables ({len(ccards)}/{cons_obj.get('limit', 0)}):")
            if ccards:
                for c in ccards:
                    lines.append("  " + _format_item_card(c, show_sell=True, compact=compact))
            else:
                lines.append("  (none)")

    # Hand
    hand_obj = state.get("hand")
    if hand_obj is not None and (hand_obj.get("cards") or state_name == "SELECTING_HAND"):
        hcards = hand_obj.get("cards") or []
        prefix = "" if compact else "\n"
        lines.append(
            f"{prefix}Hand ({len(hcards)}/{hand_obj.get('limit', 0)}, sort={hand_obj.get('sort')}):"
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

    # Deck remaining composition (always shown in RUN states where deck is present)
    deck_line = format_deck_composition(deck)
    if deck_line and state_name in ("SELECTING_HAND", "BLIND_SELECT", "SHOP", "TAROT_PACK", "SPECTRAL_PACK", "STANDARD_PACK"):
        lines.append(deck_line)

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
                lines.append(
                    "    " + _format_item_card(c, show_price=True, compact=compact, show_copyable=has_copier)
                )
        else:
            lines.append("    (empty)")
        lines.append("  Vouchers:")
        if shop.get("vouchers"):
            for c in shop["vouchers"]:
                lines.append("    " + _format_item_card(c, show_price=True, compact=compact))
        else:
            lines.append("    (empty)")
        lines.append("  Booster Packs:")
        if shop.get("boosters"):
            for c in shop["boosters"]:
                lines.append("    " + _format_item_card(c, show_price=True, compact=compact))
        else:
            lines.append("    (empty)")
        preview_lines = _format_shop_blind_preview(blind, compact=compact)
        lines.extend(preview_lines)

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
                lines.append("  " + _format_item_card(c, compact=compact, show_copyable=has_copier))
        else:
            lines.append("  (empty)")

    # Vouchers & Tags (compact)
    vouchers = run.get("vouchers") or []
    tags = run.get("tags") or []
    if vouchers:
        lines.append("Owned Vouchers: " + ", ".join(_display_name(v, compact=compact) for v in vouchers))
    if tags:
        if compact:
            tag_items = []
            for t in tags:
                tname = _display_name(t, compact=True)
                tstats = t.get("compact_stats")
                tag_items.append(f"{tname}({tstats})" if tstats else tname)
            lines.append("Active Tags: " + ", ".join(tag_items))
        else:
            lines.append(
                "Active Tags: "
                + ", ".join(
                    f"{_display_name(t, compact=False)} ({t['description']})" if t.get("description") else _display_name(t, compact=False)
                    for t in tags
                )
            )

    # Poker Hands
    if poker_hands:
        if show_hands:
            lines.append("\nPoker Hands:")
            for h in poker_hands:
                hlabel = h["name"]
                lines.append(
                    f"  {hlabel:16s} Lv.{h['level']:<2d}  "
                    f"{h['chips']:>4} x {h['mult']:<4}  (played: {h['played']})"
                )
        else:
            leveled = [h for h in poker_hands if (h.get("level") or 1) > 1]
            if leveled:
                upgraded_parts = []
                for h in leveled:
                    cnt = int(h.get("played") or 0)
                    cnt_str = f", x{cnt}" if cnt > 0 else ""
                    upgraded_parts.append(f"{h['name']} Lv.{h['level']} ({h['chips']}x{h['mult']}{cnt_str})")
                lines.append("Upgraded Hands: " + ", ".join(upgraded_parts))

            boss_choice = next((ch for ch in (blind.get("choices") or []) if ch.get("slot") == "Boss"), None)
            ox_relevant = (
                (active_blind and active_blind.get("name") == "The Ox")
                or (boss_choice and boss_choice.get("name") == "The Ox")
            )
            if bool(joker_names & {"Supernova", "Obelisk"}) or ox_relevant:
                played_hands = [h for h in poker_hands if int(h.get("played") or 0) > 0]
                if played_hands:
                    played_hands.sort(key=lambda h: -int(h.get("played") or 0))
                    lines.append(
                        "Played Hands: "
                        + ", ".join(f"{h['name']}:{h['played']}" for h in played_hands)
                    )

    if compact:
        lines.append("Actions: " + " | ".join(compute_legal_actions(state, compact=True)))
    else:
        lines.append("\nLegal Actions: " + " | ".join(compute_legal_actions(state, compact=False)))
    return "\n".join(lines)
