"""Core unit tests for balatro4llm (formatting, action parsing, persistent TCP & auto-reconnect, batch)."""

from __future__ import annotations

import contextlib
import io
import json
import socket
import threading
import unittest
from typing import Any

from balatro4llm.cli import build_parser, namespace_to_action_spec, parse_batch_steps
from balatro4llm.core import (
    BalatroBatchError,
    BalatroClient,
    BalatroCommandError,
    BalatroError,
    compute_legal_actions,
    format_batch_error,
    format_state,
    parse_action_command,
)


def _sample_shop_state(
    *,
    small_status: str = "Defeated",
    big_status: str = "Upcoming",
    boss_name: str = "The Ox",
    boss_debuff: str = "打出三条牌型时 资金归$0",
    on_deck: str = "Small",  # deliberately stale like vanilla SHOP before BLIND_SELECT
    include_supernova: bool = True,
    supernova_compact_stats: str | None = None,
) -> dict[str, Any]:
    jokers = [
        {
            "index": 1,
            "kind": "Joker",
            "name": "Supernova" if include_supernova else "Mail-In Rebate",
            "loc_name": "超新星" if include_supernova else "邮寄返利",
            "compact_stats": supernova_compact_stats if include_supernova else "Q:+$5",
            "sell_cost": 2,
            "can_sell": True,
        },
        {
            "index": 2,
            "kind": "Joker",
            "name": "The Trio",
            "loc_name": "三重奏",
            "compact_stats": "X3M",
            "edition": "foil",
            "sell_cost": 5,
            "can_sell": True,
        },
    ]
    return {
        "stage_name": "RUN",
        "state_name": "SHOP",
        "state_complete": True,
        "gamespeed": 8,
        "ready": {
            "shop_ready": True,
            "event_queues": {"base_blocking": 0},
        },
        "run": {
            "ante": 7,
            "win_ante": 8,
            "round": 16,
            "dollars": 69,
            "bankrupt_at": 0,
            "hands_left": 4,
            "discards_left": 4,
            "probabilities_normal": 2,
            "deck": {"key": "b_red", "name": "Red Deck", "loc_name": "红色牌组"},
            "stake_name": "Red Stake",
            "vouchers": [{"key": "v_tarot_merchant", "name": "Tarot Merchant", "loc_name": "塔罗商人"}],
            "tags": [
                {
                    "key": "tag_investment",
                    "name": "Investment Tag",
                    "loc_name": "投资标签",
                    "description": "击败 Boss盲注后 获得$25",
                    "compact_stats": "+$25",
                },
                {
                    "key": "tag_coupon",
                    "name": "Coupon Tag",
                    "loc_name": "优惠券标签",
                    "description": "下一家店内的 初始卡牌和补充包 均为免费",
                },
            ],
            "poker_hands": [
                {"name": "Four of a Kind", "level": 6, "chips": 210, "mult": 22, "played": 0, "played_this_round": 0},
                {"name": "Full House", "level": 4, "chips": 115, "mult": 10, "played": 2, "played_this_round": 0},
                {"name": "Three of a Kind", "level": 5, "chips": 110, "mult": 11, "played": 9, "played_this_round": 0},
                {"name": "Pair", "level": 1, "chips": 10, "mult": 2, "played": 3, "played_this_round": 0},
            ],
        },
        "blind": {
            "on_deck": on_deck,
            "can_reroll_boss": False,
            "choices": [
                {
                    "slot": "Small",
                    "name": "Small Blind",
                    "loc_name": "小盲注",
                    "status": small_status,
                    "chips": 35000,
                    "dollars": 0,
                    "skip_tag": {"name": "Handy Tag", "description": "每出牌+$1"},
                },
                {
                    "slot": "Big",
                    "name": "Big Blind",
                    "loc_name": "大盲注",
                    "status": big_status,
                    "chips": 52500,
                    "dollars": 4,
                    "skip_tag": {"name": "Coupon Tag", "description": "下一家店免费"},
                },
                {
                    "slot": "Boss",
                    "name": boss_name,
                    "loc_name": boss_name,
                    "status": "Upcoming",
                    "chips": 70000,
                    "dollars": 5,
                    "boss": True,
                    "debuff_text": boss_debuff,
                },
            ],
        },
        "jokers": {"limit": 5, "cards": jokers},
        "consumeables": {
            "limit": 2,
            "cards": [
                {
                    "index": 1,
                    "kind": "Tarot",
                    "name": "Strength",
                    "loc_name": "力量",
                    "description": "将最多2张 选定卡牌 点数提高1",
                    "can_use": False,
                    "can_use_with_targets": False,
                    "max_highlighted": 2,
                    "min_highlighted": 1,
                    "sell_cost": 1,
                    "can_sell": True,
                },
                {
                    "index": 2,
                    "kind": "Planet",
                    "name": "Venus",
                    "loc_name": "金星",
                    "hand_type": "Three of a Kind",
                    "compact_stats": "3oaK",
                    "description": "（等级5） 升级三条 +2倍率并且 +20筹码",
                    "can_use": True,
                    "can_use_with_targets": True,
                    "sell_cost": 1,
                    "can_sell": True,
                },
            ],
        },
        "deck": {
            "remaining": 49,
            "total": 49,
            "composition": {"suits": {"S": 12, "H": 10, "C": 13, "D": 14}, "ranks": {"A": 7}, "special": []},
        },
        "shop": {
            "ready": True,
            "reroll_cost": 5,
            "can_reroll": True,
            "jokers": [
                {
                    "index": 1,
                    "kind": "Tarot",
                    "name": "Death",
                    "cost": 3,
                    "affordable": True,
                    "has_space": False,
                    "can_buy": False,
                    "can_buy_and_use": False,
                    "can_use": False,
                    "max_highlighted": 2,
                    "min_highlighted": 2,
                    "description": "将靠左牌变成靠右牌",
                }
            ],
            "vouchers": [],
            "boosters": [],
        },
    }


class TestCoreFormatting(unittest.TestCase):
    def test_compact_shop_compresses_owned_consumables_tags_and_actions(self) -> None:
        st = _sample_shop_state()
        out = format_state(st, compact=True)

        self.assertIn("Consumables (2/2): [1]Strength(no-use,sell:$1) | [2]Venus(3oaK,usable,sell:$1)", out)
        self.assertNotIn("将最多2张 选定卡牌 点数提高1", out)
        self.assertIn("将靠左牌变成靠右牌", out)

        self.assertIn("Active Tags: Investment Tag(+$25), Coupon Tag", out)
        self.assertNotIn("击败 Boss盲注后 获得$25", out)

        self.assertIn("Next: [Big] Big Blind (52,500, $4 | Skip: Coupon Tag — 下一家店免费)", out)
        self.assertIn("Boss: The Ox (70,000, $5) — 打出三条牌型时 资金归$0", out)

        self.assertIn("[1]Supernova(3oaK:+9M/Pair:+3M,sell:$2)", out)
        self.assertIn("Three of a Kind Lv.5 (110x11, x9)", out)
        self.assertIn("Four of a Kind Lv.6 (210x22)", out)
        self.assertIn("Played Hands: Three of a Kind:9, Pair:3, Full House:2", out)

        self.assertIn("Prob:2x", out)
        self.assertIn("Actions: reroll($5) | next-round [--select|--skip] | sell-joker | move-joker | use | sell-consumable", out)
        self.assertNotIn("Legal Actions:", out)

    def test_compact_shop_before_boss_shows_single_next_boss_line(self) -> None:
        st = _sample_shop_state(small_status="Defeated", big_status="Defeated", on_deck="Big")
        out = format_state(st, compact=True)
        self.assertIn("Next: [Boss] The Ox (70,000, $5) — 打出三条牌型时 资金归$0", out)
        self.assertNotIn("\nBoss:", out)
        self.assertIn("next-round [--select]", out)
        self.assertNotIn("--skip", out)

    def test_compact_selecting_hand_consumables_use_targets(self) -> None:
        st = _sample_shop_state()
        st["state_name"] = "SELECTING_HAND"
        st["consumeables"]["cards"][0]["can_use_with_targets"] = True
        st["hand"] = {"limit": 8, "sort": "desc", "cards": [{"index": 1, "short": "AS"}, {"index": 2, "short": "KS"}]}
        out = format_state(st, compact=True)
        self.assertIn("Consumables (2/2): [1]Strength(use:1..2) | [2]Venus(3oaK,usable)", out)
        self.assertIn("Actions: play | discard | sort-hand | move-hand | sell-joker | move-joker | use | sell-consumable", out)

    def test_non_compact_mode_preserves_full_format(self) -> None:
        st = _sample_shop_state()
        out = format_state(st, compact=False)
        self.assertIn("将最多2张 选定卡牌 点数提高1", out)
        self.assertIn("Legal Actions:", out)
        self.assertIn("sell-joker <idx>", out)
        actions = compute_legal_actions(st)
        self.assertIn("sell-joker <idx>", actions)

    def test_main_menu_shows_all_stakes_and_per_deck_unlocked_ranges(self) -> None:
        menu_state = {
            "stage_name": "MAIN_MENU",
            "state_name": "MENU",
            "gamespeed": 4,
            "ready": {"event_queues": {"base_blocking": 0}},
            "menu": {
                "profile": 1,
                "has_saved_run": True,
                "stakes": [
                    {"stake": 1, "key": "stake_white", "name": "White Stake", "loc_name": "白注", "description": "基础难度"},
                    {"stake": 2, "key": "stake_red", "name": "Red Stake", "loc_name": "红注", "description": "小盲注无奖励"},
                    {"stake": 3, "key": "stake_green", "name": "Green Stake", "loc_name": "绿注", "description": "所需分数增速加快"},
                ],
                "selected_deck": {"key": "b_red", "name": "Red Deck", "loc_name": "红色牌组", "win_stake": 2, "max_stake": 3},
                "unlocked_decks": [
                    {"key": "b_red", "name": "Red Deck", "loc_name": "红色牌组", "win_stake": 2, "max_stake": 3},
                    {"key": "b_blue", "name": "Blue Deck", "loc_name": "蓝色牌组", "win_stake": 0, "max_stake": 1},
                ],
            },
        }
        compact_out = format_state(menu_state, compact=True)
        self.assertIn("Selected Deck: Red Deck [b_red] (stakes:1..3:Green)", compact_out)
        self.assertIn("Stakes: 1:White | 2:Red | 3:Green", compact_out)
        self.assertIn("b_red(Red Deck, 1..3:Green), b_blue(Blue Deck, 1:White)", compact_out)

        full_out = format_state(menu_state, compact=False)
        self.assertIn("[3] 绿注 (Green Stake) — 所需分数增速加快", full_out)
        self.assertIn("b_red(红色牌组 (Red Deck), 1..3:Green)", full_out)


class TestCoreActionParsers(unittest.TestCase):
    def test_parse_action_command_all_variants(self) -> None:
        self.assertEqual(
            parse_action_command('start --deck "Red Deck" --stake max --seed ABCD'),
            ("start", {"deck": "Red Deck", "stake": "max", "seed": "ABCD"}),
        )
        self.assertEqual(parse_action_command("new-run --stake 3"), ("start", {"stake": 3}))
        self.assertEqual(parse_action_command("set-speed 16"), ("set_speed", {"speed": 16}))
        self.assertEqual(parse_action_command("set-speed 0.5"), ("set_speed", {"speed": 0.5}))
        self.assertEqual(parse_action_command("move-joker 1 5"), ("move_joker", {"from": 1, "to": 5}))
        self.assertEqual(parse_action_command("move-hand 4 2"), ("move_hand", {"from": 4, "to": 2}))
        self.assertEqual(parse_action_command("buy 2 --use"), ("buy", {"index": 2, "use": True}))
        self.assertEqual(parse_action_command("next-round --select"), ("next_round", {"select": True}))
        self.assertEqual(parse_action_command("next-round --skip"), ("next_round", {"skip": True}))
        self.assertEqual(parse_action_command("pick 2 1 3"), ("pick", {"index": 2, "targets": [1, 3]}))

    def test_invalid_command_raises_silently_without_stderr_leak(self) -> None:
        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf), contextlib.redirect_stdout(stdout_buf):
            for bad in ("", "   ", "nonexistent-cmd", "play", 'unterminated "quote', "next-round --select --skip"):
                with self.assertRaises(BalatroError):
                    parse_action_command(bad)
        self.assertEqual(stderr_buf.getvalue(), "")
        self.assertEqual(stdout_buf.getvalue(), "")

    def test_cli_parsers_and_expand_steps(self) -> None:
        parser = build_parser()
        ns16 = parser.parse_args(["set-speed", "16"])
        self.assertEqual(namespace_to_action_spec(ns16), ("set_speed", {"speed": 16}))

        steps = parse_batch_steps(["buy 2 --use", "next-round --select"])
        self.assertEqual(steps, [("buy", {"index": 2, "use": True}), ("next_round", {"select": True})])

        expanded = BalatroClient._expand_action_steps(steps)
        self.assertEqual(
            expanded,
            [("buy", {"index": 2, "use": True}), ("next_round", {}), ("select_blind", {})],
        )

        expanded_skip = BalatroClient._expand_action_steps([("next_round", {"skip": True})])
        self.assertEqual(expanded_skip, [("next_round", {}), ("skip_blind", {})])

        with self.assertRaises(BalatroError):
            BalatroClient._expand_action_steps([("next_round", {"select": True, "skip": True})])


class _FakeClient(BalatroClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._states = [
            {
                "stage_name": "RUN",
                "state_name": "BLIND_SELECT",
                "state_complete": True,
                "ready": {"blind_select_ready": True, "event_queues": {"base_blocking": 0}},
                "blind": {"on_deck": "Big", "can_reroll_boss": False},
            },
            {
                "stage_name": "RUN",
                "state_name": "SELECTING_HAND",
                "state_complete": True,
                "ready": {"event_queues": {"base_blocking": 0}},
                "hand": {"cards": [{"index": 1, "short": "AS"}]},
            },
        ]

    def execute_action(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(params or {})))
        return {"action": name}

    def _wait_after_action(self, name: str, wait_timeout: float) -> dict[str, Any]:
        return self._states.pop(0)


class TestCompositeAndPersistentTcp(unittest.TestCase):
    def test_next_round_select_executes_two_steps(self) -> None:
        client = _FakeClient()
        receipt, state = client.next_round(select=True, auto_cash_out=True, auto_select_boss=True)
        self.assertEqual(client.calls, [("next_round", {}), ("select_blind", {})])
        self.assertEqual(state["state_name"], "SELECTING_HAND")
        self.assertEqual(len(receipt["batch_steps"]), 2)

    def test_next_round_select_rejects_no_wait(self) -> None:
        client = _FakeClient()
        with self.assertRaises(BalatroError):
            client.next_round(select=True, wait=False)

    def test_persistent_connection_reuse_reconnect_and_batch_fail_fast(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(8)
        stop_evt = threading.Event()
        metrics = {"accepts": 0, "requests": 0}
        force_drop_next = {"flag": False}
        fail_buy = {"flag": False}
        active_conns: list[socket.socket] = []

        def handle_conn(conn: socket.socket) -> None:
            buf = b""
            with conn:
                while not stop_evt.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        if force_drop_next["flag"]:
                            force_drop_next["flag"] = False
                            return  # abrupt EOF before response to simulate game restart
                        req = json.loads(line.decode("utf-8"))
                        metrics["requests"] += 1
                        cmd = req["cmd"]
                        args = req.get("args") or {}
                        if cmd == "ping":
                            resp = {"id": req["id"], "ok": True, "data": {"mod_version": "0.7.0", "gamespeed": 4}}
                        elif cmd == "state":
                            resp = {"id": req["id"], "ok": True, "data": _sample_shop_state()}
                        elif cmd == "action":
                            act = args.get("name")
                            if act == "buy" and fail_buy["flag"]:
                                resp = {"id": req["id"], "ok": False, "error": "insufficient funds"}
                            else:
                                resp = {"id": req["id"], "ok": True, "data": {"action": act}}
                        else:
                            resp = {"id": req["id"], "ok": False, "error": "unknown"}
                        conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))

        def accept_loop() -> None:
            srv.settimeout(0.1)
            while not stop_evt.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                metrics["accepts"] += 1
                active_conns.append(conn)
                threading.Thread(target=handle_conn, args=(conn,), daemon=True).start()

        t = threading.Thread(target=accept_loop, daemon=True)
        t.start()
        try:
            with BalatroClient(port=port, timeout=2.0, persistent=True) as client:
                p = client.ping()
                self.assertEqual(p["mod_version"], "0.7.0")
                st1 = client.get_state()
                self.assertEqual(st1["state_name"], "SHOP")
                st2 = client.get_state()
                self.assertEqual(st2["state_name"], "SHOP")
                # All 3 calls shared 1 single keep-alive socket!
                self.assertEqual(metrics["accepts"], 1)
                self.assertEqual(metrics["requests"], 3)

                # Simulate Balatro closing the idle socket; persistent client must reconnect transparently
                force_drop_next["flag"] = True
                st3 = client.get_state()
                self.assertEqual(st3["state_name"], "SHOP")
                self.assertEqual(metrics["accepts"], 2)

                # Test batch fail-fast preserves completed steps and live state
                fail_buy["flag"] = True
                with self.assertRaises(BalatroBatchError) as ctx:
                    client.run_batch([("reroll", {}), ("buy", {"index": 1})], wait_timeout=2.0)
                self.assertEqual(ctx.exception.failed_index, 2)
                self.assertEqual(ctx.exception.action_name, "buy")
                self.assertEqual(len(ctx.exception.completed), 1)
                self.assertEqual(ctx.exception.completed[0]["action"], "reroll")
                self.assertIsNotNone(ctx.exception.last_state)
                err_txt = format_batch_error(ctx.exception, compact=True)
                self.assertIn("Completed before failure: reroll", err_txt)
                self.assertIn("=== BALATRO [RUN / SHOP] ===", err_txt)
        finally:
            stop_evt.set()
            for c in active_conns:
                try:
                    c.close()
                except OSError:
                    pass
            srv.close()
            t.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
