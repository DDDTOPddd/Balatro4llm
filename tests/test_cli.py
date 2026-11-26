"""CLI adapter tests: UTF-8 stdio, subcommands, batch execution, and zero-dependency isolation."""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import unittest

from balatro4llm.cli import build_parser

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_shop_state(speed: float = 4) -> dict:
    return {
        "stage_name": "RUN",
        "state_name": "SHOP",
        "state_complete": True,
        "gamespeed": speed,
        "ready": {
            "controller_locked": False,
            "active_locks": [],
            "paused": False,
            "has_overlay_menu": False,
            "in_tutorial": False,
            "shop_ready": True,
            "blind_select_ready": True,
            "event_queues": {"base": 1, "base_blocking": 0},
        },
        "run": {
            "ante": 4,
            "win_ante": 8,
            "round": 9,
            "dollars": 25,
            "bankrupt_at": 0,
            "hands_left": 4,
            "discards_left": 3,
            "deck": {"name": "Red Deck", "loc_name": "红色牌组"},
            "stake_name": "Red Stake",
            "poker_hands": [
                {"name": "Pair", "loc_name": "对子", "level": 2, "chips": 25, "mult": 3, "played": 4},
            ],
        },
        "blind": {
            "on_deck": "Big",
            "choices": [
                {"slot": "Small", "name": "Small Blind", "status": "Defeated", "chips": 1200, "dollars": 0},
                {"slot": "Big", "name": "Big Blind", "status": "Upcoming", "chips": 1800, "dollars": 4},
                {"slot": "Boss", "name": "The Club", "status": "Upcoming", "chips": 2400, "dollars": 5, "debuff_text": "所有梅花失效"},
            ],
        },
        "deck": {
            "remaining": 52,
            "total": 52,
            "composition": {"suits": {"S": 13, "H": 13, "C": 13, "D": 13}, "ranks": {"A": 4}, "special": []},
        },
        "jokers": {
            "limit": 5,
            "cards": [
                {"index": 1, "kind": "Joker", "name": "Abstract Joker", "loc_name": "抽象小丑", "compact_stats": "+6M", "sell_cost": 2, "can_sell": True, "description": "每张小丑+3倍率"},
                {"index": 2, "kind": "Joker", "name": "The Trio", "loc_name": "三重奏", "compact_stats": "X3M", "sell_cost": 4, "can_sell": True, "description": "包含三条时X3倍率"},
            ],
        },
        "consumeables": {"limit": 2, "cards": []},
        "shop": {
            "ready": True,
            "reroll_cost": 5,
            "can_reroll": True,
            "jokers": [
                {"index": 1, "kind": "Joker", "name": "Scholar", "loc_name": "学者", "cost": 4, "affordable": True, "has_space": True, "can_buy": True, "description": "打出的A给予+20筹码和+4倍率"},
                {"index": 2, "kind": "Planet", "name": "Mercury", "loc_name": "水星", "cost": 3, "affordable": True, "has_space": False, "can_buy": False, "can_buy_and_use": True, "can_use": True, "description": "升级对子"},
            ],
            "vouchers": [],
            "boosters": [],
        },
    }


def _make_hand_state(speed: float = 4) -> dict:
    st = _make_shop_state(speed=speed)
    st["state_name"] = "SELECTING_HAND"
    st["blind"]["active"] = {"name": "Big Blind", "chips": 1800, "dollars": 4}
    st["hand"] = {
        "limit": 8,
        "sort": "rank",
        "cards": [
            {"index": 1, "kind": "PlayingCard", "short": "AH"},
            {"index": 2, "kind": "PlayingCard", "short": "AS"},
        ],
    }
    return st


class TestCliZeroDependencyAndEndToEnd(unittest.TestCase):
    def test_cli_imports_without_mcp_dependency(self) -> None:
        code = (
            "import sys; sys.modules['mcp'] = None; "
            "import balatro4llm; "
            "from balatro4llm.cli.main import build_parser; "
            "p = build_parser(); "
            "ns = p.parse_args(['next-round', '--select']); "
            "assert ns.select is True and balatro4llm.__version__ == '0.8.0'"
        )
        res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_cli_subprocess_utf8_and_commands(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(8)
        stop_evt = threading.Event()
        state_holder = {"speed": 4, "screen": "shop", "actions": []}
        conns: list[socket.socket] = []

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
                        req = json.loads(line.decode("utf-8"))
                        cmd = req["cmd"]
                        args = req.get("args") or {}
                        if cmd == "ping":
                            data = {
                                "mod_version": "0.7.0",
                                "game_version": "1.0.1o-FULL",
                                "stage": 2,
                                "stage_name": "RUN",
                                "state": 5,
                                "state_name": "SHOP",
                                "state_complete": True,
                                "paused": False,
                                "gamespeed": state_holder["speed"],
                                "fps": 120,
                                "uptime": 10.5,
                            }
                        elif cmd == "state":
                            data = (
                                _make_shop_state(state_holder["speed"])
                                if state_holder["screen"] == "shop"
                                else _make_hand_state(state_holder["speed"])
                            )
                        elif cmd == "action":
                            act = args["name"]
                            state_holder["actions"].append((act, args))
                            if act == "set_speed":
                                prev = state_holder["speed"]
                                state_holder["speed"] = args["speed"]
                                data = {"action": "set_speed", "previous_speed": prev, "speed": state_holder["speed"], "persisted": state_holder["speed"] in (0.5, 1, 2, 4)}
                            elif act == "select_blind":
                                state_holder["screen"] = "hand"
                                data = {"action": "select_blind"}
                            else:
                                data = {"action": act}
                        else:
                            data = {}
                        conn.sendall((json.dumps({"id": req["id"], "ok": True, "data": data}, ensure_ascii=False) + "\n").encode("utf-8"))

        def accept_loop() -> None:
            srv.settimeout(0.1)
            while not stop_evt.is_set():
                try:
                    c, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                conns.append(c)
                threading.Thread(target=handle_conn, args=(c,), daemon=True).start()

        t = threading.Thread(target=accept_loop, daemon=True)
        t.start()

        env_clean = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}

        def run_cli(*args: str) -> str:
            res = subprocess.run(
                [sys.executable, "-m", "balatro4llm", "--port", str(port), *args],
                cwd=str(ROOT),
                env=env_clean,
                capture_output=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
            return res.stdout.decode("utf-8")

        try:
            out_ping = run_cli("ping")
            self.assertIn("Game Speed   : 4x", out_ping)

            out_shop = run_cli("--compact", "state")
            self.assertIn("打出的A给予+20筹码和+4倍率", out_shop)
            self.assertIn("[2] Mercury [Planet, $3 [slots full; --use OK], usable] — 升级对子", out_shop)
            self.assertIn("Abstract Joker(+6M,sell:$2)", out_shop)

            out_json = run_cli("--json", "state")
            parsed_json = json.loads(out_json)
            self.assertIn("legal_actions", parsed_json)

            out_spd = run_cli("--compact", "set-speed", "8")
            self.assertIn("[speed] 4x -> 8x (runtime-only turbo)", out_spd)
            self.assertIn("Speed:8x", out_spd)

            out_nr = run_cli("--compact", "next-round", "--select")
            self.assertIn("[batch] executed 2 steps: next_round -> select_blind", out_nr)
            self.assertIn("=== BALATRO [RUN / SELECTING_HAND] ===", out_nr)

            out_batch = run_cli("--compact", "batch", "move-joker 1 2", "move-hand 2 1")
            self.assertIn("[batch] executed 2 steps: move_joker -> move_hand", out_batch)
        finally:
            stop_evt.set()
            for c in conns:
                try:
                    c.close()
                except OSError:
                    pass
            srv.close()
            t.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
