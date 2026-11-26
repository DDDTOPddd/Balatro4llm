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
  ├── core/                # Zero-dependency shared core (errors, action registry, persistent TCP client, formatter)
  ├── cli/                 # Thin CLI entrypoint (`balatro-cli` / `python -m balatro4llm ...`, zero extra deps)
  └── mcp/                 # Optional MCPServer (`balatro-mcp` / `python -m balatro4llm.mcp`, via `.[mcp]`)
```

## Key Principles

- **No vision / screenshots / simulated clicks**: Reads Balatro's live Lua state (`G.*`) and calls verified internal game callbacks (`G.FUNCS.*`).
- **Source-verified**: All state fields and callbacks are verified against Lua source extracted from `Balatro.exe` into `reference/balatro_src/` (gitignored).
- **Non-blocking**: Uses LÖVE2D's bundled `socket` with `settimeout(0)` polled inside `love.update(dt)`, keeping full FPS with ~10 ms RTT.
- **Stable post-action wait**: `BalatroClient.wait_until_stable()` polls until blocking events (`G.E_MANAGER.queues.base`), controller locks (`G.CONTROLLER.locks`), and screen-specific readiness checks settle before returning the updated state.
- **Token-, speed- & turn-efficient without cheating**: Includes View-Deck remaining composition (`Deck Left`), `--compact` single-line owned Jokers / Consumables / Active Tags / terse `Actions:`, live Joker & poker-hand play counts (`Supernova`, `Obelisk`, `Card Sharp`, `Upgraded Hands` `xN`), Shop Next Blind & Boss previews, `next-round --select|--skip`, exact shop availability tags (`[no $]` / `[slots full]` / `[slots full; --use OK]`), `set-speed 0.5..16` with fast `ROUND_EVAL` cash-out, `move-joker`/`move-hand` single-card moves, `--auto-cash-out` / `--auto-advance`, native UTF-8 CLI output, and deterministic `batch` execution — while leaving all tactical & scoring decisions 100% to the LLM.

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
Then test from your terminal (CLI requires zero third-party dependencies):
```powershell
python -m balatro4llm ping
python -m balatro4llm --compact state
```

### 5. (Optional) Start as a Persistent MCP Server
Install the optional `mcp` SDK extra once, then expose 4 lean tools (`balatro_ping`, `balatro_state`, `balatro_act`, `balatro_batch`) over `stdio` (or `streamable-http`) with persistent TCP keep-alive:
```powershell
pip install -e ".[mcp]"
balatro-mcp --help
```
See [docs/mcp-setup.md](docs/mcp-setup.md) for DeepSeek Harness, Antigravity, Cursor, and Claude Desktop MCP configs.

## CLI Usage Examples

```powershell
# Recommended global flags for AI agents (or set BALATRO4LLM_COMPACT=1, BALATRO4LLM_AUTO_CASH_OUT=1, BALATRO4LLM_AUTO_ADVANCE=1)
python -m balatro4llm --compact --auto-advance state

# Speed up in-game animations (0.5/1/2/4 saved to settings; 8/16 = runtime-only turbo; >=4x fast cash-out)
python -m balatro4llm set-speed 8

# Start, continue, win screen / post-run navigation (`--stake` accepts 1..8, `max`, or stake name like `green`)
python -m balatro4llm start --deck b_red --stake max # alias: new-run
python -m balatro4llm continue
python -m balatro4llm endless                        # enter Endless Mode from Ante 8 win screen
python -m balatro4llm main-menu                      # return to Main Menu

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
python -m balatro4llm next-round --select   # leave shop & enter next blind directly
python -m balatro4llm next-round --skip     # leave shop & skip next Small/Big blind

# Inventory, Reordering & Deterministic Batching
python -m balatro4llm use 1 2 5
python -m balatro4llm sell-joker 2
python -m balatro4llm sell-consumable 1
python -m balatro4llm move-joker 1 5
python -m balatro4llm move-hand 1 2
python -m balatro4llm reorder-jokers 1 2 4 3
python -m balatro4llm --compact --auto-advance batch "move-joker 2 5" "play 1 2 3 4 5"

# Raw JSON output for scripts / MCP
python -m balatro4llm --json state
```

See [SKILL.md](SKILL.md) for the complete AI Agent operating guide.
