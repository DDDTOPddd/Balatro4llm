"""End-to-end MCP stdio client-server tests + persistent TCP socket reuse benchmark."""

from __future__ import annotations

import asyncio
import json
import pathlib
import socket
import sys
import threading
import time
import unittest
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_shop_state(speed: float = 4) -> dict[str, Any]:
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
                {"index": 1, "kind": "Joker", "name": "Abstract Joker", "compact_stats": "+6M", "sell_cost": 2, "can_sell": True},
                {"index": 2, "kind": "Joker", "name": "The Trio", "compact_stats": "X3M", "sell_cost": 4, "can_sell": True},
            ],
        },
        "consumeables": {"limit": 2, "cards": []},
        "shop": {
            "ready": True,
            "reroll_cost": 5,
            "can_reroll": True,
            "jokers": [
                {"index": 1, "kind": "Joker", "name": "Scholar", "cost": 4, "affordable": True, "has_space": True, "can_buy": True, "description": "打出的A给予+20筹码和+4倍率"},
            ],
            "vouchers": [],
            "boosters": [],
        },
    }


def _make_hand_state(speed: float = 4) -> dict[str, Any]:
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


def _extract_text(result: Any) -> str:
    return "\n".join(getattr(c, "text", str(c)) for c in (result.content or []))


class _MockModServer:
    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind(("127.0.0.1", 0))
        self.port = self._srv.getsockname()[1]
        self._srv.listen(8)
        self._stop = threading.Event()
        self._conns: list[socket.socket] = []
        self.accepts = 0
        self.speed = 4
        self.screen = "shop"
        self.fail_buy = False
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)

    def start(self) -> "_MockModServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        for c in self._conns:
            try:
                c.close()
            except OSError:
                pass
        try:
            self._srv.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)

    def _accept_loop(self) -> None:
        self._srv.settimeout(0.1)
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.accepts += 1
            self._conns.append(c)
            threading.Thread(target=self._handle_conn, args=(c,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            while not self._stop.is_set():
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
                    ok = True
                    err = None
                    data: dict[str, Any] = {}
                    if cmd == "ping":
                        data = {
                            "mod_version": "0.7.0",
                            "game_version": "1.0.1o-FULL",
                            "stage": 2,
                            "stage_name": "RUN",
                            "state": 5 if self.screen == "shop" else 1,
                            "state_name": "SHOP" if self.screen == "shop" else "SELECTING_HAND",
                            "state_complete": True,
                            "paused": False,
                            "gamespeed": self.speed,
                            "fps": 120,
                            "uptime": 12.3,
                        }
                    elif cmd == "state":
                        data = _make_shop_state(self.speed) if self.screen == "shop" else _make_hand_state(self.speed)
                    elif cmd == "action":
                        act = args.get("name")
                        if act == "set_speed":
                            prev = self.speed
                            self.speed = args["speed"]
                            data = {"action": "set_speed", "previous_speed": prev, "speed": self.speed, "persisted": self.speed in (0.5, 1, 2, 4)}
                        elif act == "select_blind":
                            self.screen = "hand"
                            data = {"action": "select_blind"}
                        elif act == "buy" and self.fail_buy:
                            ok = False
                            err = "insufficient funds"
                        else:
                            data = {"action": act}
                    else:
                        ok = False
                        err = f"unknown cmd: {cmd}"
                    resp = {"id": req["id"], "ok": ok, "data": data} if ok else {"id": req["id"], "ok": False, "error": err}
                    conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))


class TestMcpStdioEndToEnd(unittest.TestCase):
    def test_mcp_stdio_tools_resources_errors_and_keepalive_latency(self) -> None:
        mock = _MockModServer().start()
        try:
            async def _run() -> float:
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "balatro4llm.mcp", "--port", str(mock.port)],
                    cwd=str(ROOT),
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()

                        # 1. Lean tool schema check
                        tools_res = await session.list_tools()
                        tool_names = {t.name for t in tools_res.tools}
                        self.assertEqual(
                            tool_names,
                            {"balatro_ping", "balatro_state", "balatro_act", "balatro_batch"},
                        )
                        schema_chars = sum(
                            len(json.dumps(t.input_schema, ensure_ascii=False)) + len(t.description or "")
                            for t in tools_res.tools
                        )
                        print(f"\n[MCP SCHEMA] 4 tools (input_schema + description) = {schema_chars} chars")
                        self.assertLess(schema_chars, 4000)

                        # 2. Resources check
                        res_list = await session.list_resources()
                        uris = {str(r.uri) for r in res_list.resources}
                        self.assertIn("balatro://state", uris)
                        self.assertIn("balatro://guide", uris)

                        r_state = await session.read_resource("balatro://state")
                        r_state_txt = "\n".join(getattr(c, "text", str(c)) for c in r_state.contents)
                        self.assertIn("=== BALATRO [RUN / SHOP] ===", r_state_txt)

                        r_guide = await session.read_resource("balatro://guide")
                        r_guide_txt = "\n".join(getattr(c, "text", str(c)) for c in r_guide.contents)
                        self.assertIn("Playing Balatro", r_guide_txt)

                        # 3. Core tool execution
                        ping_res = await session.call_tool("balatro_ping", {})
                        self.assertFalse(ping_res.is_error)
                        self.assertIn("PONG from balatro4llm v0.7.0", _extract_text(ping_res))

                        st_res = await session.call_tool("balatro_state", {"compact": True})
                        self.assertFalse(st_res.is_error)
                        st_txt = _extract_text(st_res)
                        self.assertIn("打出的A给予+20筹码和+4倍率", st_txt)
                        self.assertIn("Abstract Joker(+6M,sell:$2)", st_txt)

                        mj_res = await session.call_tool("balatro_act", {"command": "move-joker 1 2"})
                        self.assertFalse(mj_res.is_error)

                        sp_res = await session.call_tool("balatro_act", {"command": "set-speed 4"})
                        self.assertFalse(sp_res.is_error)
                        self.assertIn("[speed] 4x -> 4x (saved)", _extract_text(sp_res))

                        nr_res = await session.call_tool("balatro_act", {"command": "next-round --select"})
                        self.assertFalse(nr_res.is_error)
                        nr_txt = _extract_text(nr_res)
                        self.assertIn("[batch] executed 2 steps: next_round -> select_blind", nr_txt)
                        self.assertIn("=== BALATRO [RUN / SELECTING_HAND] ===", nr_txt)

                        bt_res = await session.call_tool(
                            "balatro_batch",
                            {"steps": ["move-joker 1 2", "move-hand 2 1"]},
                        )
                        self.assertFalse(bt_res.is_error)
                        self.assertIn("move_joker -> move_hand", _extract_text(bt_res))

                        # 4. Invalid command returns ToolError cleanly without breaking stdio stream
                        bad_res = await session.call_tool("balatro_act", {"command": "nonexistent-cmd"})
                        self.assertTrue(bad_res.is_error)

                        ping_after = await session.call_tool("balatro_ping", {})
                        self.assertFalse(ping_after.is_error)

                        # 5. Batch failure preserves completed steps + live state
                        mock.fail_buy = True
                        fail_batch = await session.call_tool(
                            "balatro_batch",
                            {"steps": ["reroll", "buy 1"]},
                        )
                        self.assertTrue(fail_batch.is_error)
                        fail_txt = _extract_text(fail_batch)
                        self.assertIn("Completed before failure: reroll", fail_txt)
                        self.assertIn("=== BALATRO", fail_txt)

                        # 6. 20-call persistent keep-alive benchmark (must reuse the 1 TCP socket!)
                        accepts_before = mock.accepts
                        t0 = time.perf_counter()
                        for _ in range(20):
                            res = await session.call_tool("balatro_state", {"compact": True})
                            self.assertFalse(res.is_error)
                        avg_ms = ((time.perf_counter() - t0) * 1000.0) / 20.0
                        self.assertEqual(mock.accepts, accepts_before)
                        self.assertEqual(mock.accepts, 1)
                        return avg_ms

            avg_ms = asyncio.run(_run())
            print(f"\n[MCP BENCHMARK] 20 consecutive balatro_state calls over stdio (1 reused TCP socket): {avg_ms:.2f} ms/call")
        finally:
            mock.stop()


if __name__ == "__main__":
    unittest.main()
