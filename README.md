# Balatro4llm

A zero-vision, zero-GUI-click bridge that lets AI Agents (DeepSeek Harness, Codex, Antigravity, or future MCP clients) play **Balatro** natively via an in-game **Lua Mod (Lovely)** + decoupled **Python Core / CLI**.

## Architecture

```text
Balatro (LÖVE2D + Lovely 0.10+)
  └── mod/ (balatro4llm Lua Mod)
        ├── lovely.toml    # Patches main.lua (love.load / love.update / love.quit)
        ├── server.lua     # Non-blocking LuaSocket NDJSON/TCP server on 127.0.0.1:12345
        ├── state.lua      # Read-only memory state, remaining deck composition & compact stats
        ├── actions.lua    # Atomic internal G.FUNCS.* executor
        └── json.lua       # Pure-Lua 5.1/LuaJIT JSON encoder/decoder
                ▲
                │  NDJSON over TCP (127.0.0.1:12345)
                ▼
Python Layer (balatro4llm/)
  ├── client.py            # Transport, stability wait loop, auto-advance, batching, state formatting
  ├── cli.py               # Thin CLI entrypoint (`python -m balatro4llm ...`)
  └── (future) mcp_server.py  # Drop-in wrapper over client.py with zero rework
```

## Key Principles

- **No vision / screenshots / simulated clicks**: Reads Balatro's live Lua state (`G.*`) and calls verified internal game callbacks (`G.FUNCS.*`).
- **Source-verified**: All state fields and callbacks are verified against Lua source extracted from `Balatro.exe` into `reference/balatro_src/` (gitignored).
- **Non-blocking**: Uses LÖVE2D's bundled `socket` with `settimeout(0)` polled inside `love.update(dt)`, keeping full FPS with ~10 ms RTT.
- **Stable post-action wait**: `BalatroClient.wait_until_stable()` polls until blocking events (`G.E_MANAGER.queues.base`), controller locks (`G.CONTROLLER.locks`), and screen-specific readiness checks settle before returning the updated state.
- **Token- & turn-efficient without cheating**: Includes View-Deck remaining composition (`Deck Left`), `--compact` single-language formatting, `--auto-cash-out` / `--auto-advance` for mandatory zero-choice steps, and deterministic `batch` execution — while leaving all tactical & scoring decisions 100% to the LLM.

## Quick Start (Windows)

### 1. Install Lovely Injector (v0.10+)
1. Download `lovely-x86_64-pc-windows-msvc.zip` from [ethangreen-dev/lovely-injector Releases](https://github.com/ethangreen-dev/lovely-injector/releases).
2. Extract **`winmm.dll`** (or `version.dll` on older Lovely <0.10) into your Steam Balatro folder (e.g. `E:\SteamLibrary\steamapps\common\Balatro\`).

### 2. (Optional) Extract Balatro Lua Source for Reference
```powershell
python scripts\extract_source.py
```
Extracts all `.lua` files from `Balatro.exe` into `reference/balatro_src/` (gitignored).

### 3. Deploy the Lua Mod
```powershell
python scripts\install_mod.py
```
Copies `mod/` cleanly into `%AppData%\Balatro\Mods\balatro4llm`.

### 4. Launch Balatro & Verify
Launch Balatro via Steam. Confirm Lovely's console logs:
```text
[balatro4llm] Listening on 127.0.0.1:12345 (NDJSON/TCP)
```
Then test from your terminal:
```powershell
python -m balatro4llm ping
python -m balatro4llm --compact state
```

## CLI Usage Examples

```powershell
# Recommended global flags for AI agents (or set BALATRO4LLM_COMPACT=1, BALATRO4LLM_AUTO_CASH_OUT=1, BALATRO4LLM_AUTO_ADVANCE=1)
python -m balatro4llm --compact --auto-cash-out state

# Start or continue a run
python -m balatro4llm start --deck b_red --stake 1
python -m balatro4llm continue

# Blind select
python -m balatro4llm select-blind
python -m balatro4llm skip-blind
python -m balatro4llm reroll-boss

# Playing a round (1-based hand indices)
python -m balatro4llm sort-hand suit
python -m balatro4llm discard 2 4 7
python -m balatro4llm --compact --auto-cash-out play 1 3 5 6 8
python -m balatro4llm cash-out

# Shop & Booster Packs
python -m balatro4llm buy 1
python -m balatro4llm buy 2 --use
python -m balatro4llm buy-voucher 1
python -m balatro4llm buy-pack 1
python -m balatro4llm pick 2 1 3
python -m balatro4llm skip-pack
python -m balatro4llm reroll
python -m balatro4llm next-round

# Inventory, Reordering & Deterministic Batching
python -m balatro4llm use 1 2 5
python -m balatro4llm sell-joker 2
python -m balatro4llm sell-consumable 1
python -m balatro4llm reorder-jokers 1 2 4 3
python -m balatro4llm reorder-hand 2 1 3 4 5 6 7 8
python -m balatro4llm --compact --auto-cash-out batch "reorder-jokers 1 2 3 5 4" "play 1 2 3 4 5"

# Raw JSON output for scripts / MCP
python -m balatro4llm --json state
```

See [SKILL.md](SKILL.md) for the complete AI Agent operating guide.
