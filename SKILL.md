---
name: balatro4llm
description: Play Balatro autonomously via the local balatro4llm CLI and in-game Lua Mod (zero screenshots or mouse/keyboard emulation). Use when asked to inspect, play, or continue a run of Balatro.
---

# Playing Balatro via `balatro4llm` CLI

You control a live Balatro game purely through the local CLI (`python -m balatro4llm ...`), which talks to the non-blocking in-game Lua Mod over `127.0.0.1:12345` (NDJSON/TCP).

## Core Operating Rules
1. **Never use screenshots, VLM vision, or GUI mouse/keyboard simulation.** Every piece of game state and every action goes through `python -m balatro4llm`.
2. **UTF-8 is enforced natively by the CLI** — run `python -m balatro4llm ...` directly without any PowerShell encoding boilerplate (`PYTHONIOENCODING` / `[Console]::OutputEncoding` is no longer needed).
3. **Recommended efficiency flags** (pass before the subcommand, or set via env vars):
   - `--compact` (`BALATRO4LLM_COMPACT=1`): uses canonical English names (cards, blinds, vouchers, hands), condenses **owned** Jokers, Consumables, Active Tags, and `Actions:` to single lines (`Name(live_stats,sell:$N)`), shows live hand played counts (`xN`) & Shop Next Blind/Boss previews, while preserving full descriptions for new Shop/Pack/Skip Tag items.
   - `--auto-cash-out` (`BALATRO4LLM_AUTO_CASH_OUT=1`): automatically cashes out when a play beats a blind and enters `ROUND_EVAL`, landing straight in `SHOP`.
   - `--auto-advance` (`BALATRO4LLM_AUTO_ADVANCE=1`): enables `--auto-cash-out` AND automatically enters a mandatory Boss Blind (when it cannot be rerolled).
   ```powershell
   python -m balatro4llm --compact --auto-advance state
   ```
4. **Speed up animations once at run start**: call `python -m balatro4llm set-speed 8` (or `16` for runtime-only turbo; `0.5/1/2/4` saved to settings; Options menu stays safe at all speeds). At `>=4x`, `ROUND_EVAL` cash-out tallying also auto-accelerates so plays finish well within sync wait time.
5. **Every action command automatically waits for animations/events (`G.E_MANAGER`) to finish** and prints the fresh stable state (including `Deck Left` remaining draw-pile composition, `Next:`/`Boss:` preview in `SHOP`, and `Actions:`).
6. **All indices are 1-based** (`[1]`, `[2]`, ...) matching the exact numbers printed in the latest state output. Re-read indices after every action that modifies cards.
7. Prefer **`move-joker <from> <to>`** and **`move-hand <from> <to>`** when moving a single Joker or hand card (instead of computing a full permutation for `reorder-jokers`/`reorder-hand`).
8. Use **`batch`** for deterministic multi-step sequences where all indices are already known (e.g. `move-joker` + `play`, `sell-joker` + `buy`, or `move-hand` + `use`/`pick`). **Never** batch actions that depend on unseen future draws or unseen shop/pack contents!
9. Pass `--json` before the subcommand if you need structured JSON; pass `state --hands` to inspect all poker hand levels.

---

## CLI Command Reference

| Phase | Command | Purpose |
|---|---|---|
| Health | `python -m balatro4llm ping` | Check Mod connectivity, version, stage/state, game speed, FPS |
| Inspect | `python -m balatro4llm state [--hands]` | Print current state, remaining deck composition & legal actions |
| Speed | `python -m balatro4llm set-speed <0.5\|1\|2\|4\|8\|16>` | Set animation speed (`0.5/1/2/4` saved; `8/16` runtime-only turbo; `>=4x` fast cash-out) |
| Batch | `python -m balatro4llm batch "<cmd1>" "<cmd2>" ...` | Run deterministic actions in sequence, waiting between steps (fail-fast + prints live state on error) |
| Menu / Run | `python -m balatro4llm start [--deck b_red] [--stake <1-8\|max\|name>] [--seed SEED]` | Start a new run (`new-run` alias; `--deck` accepts key or English/localized name; `--stake` accepts `1..8`, `max`, or stake name like `green`/`绿注`; enforced against unlocked stakes shown in Main Menu `state`) |
| Menu / Run | `python -m balatro4llm continue` | Resume saved run from Main Menu |
| Win / End | `python -m balatro4llm endless` | Enter Endless Mode from the Ante 8 Win screen |
| Win / End | `python -m balatro4llm main-menu` | Return to Main Menu (from Win screen, Game Over, or mid-run) |
| Overlay | `python -m balatro4llm dismiss-overlay` | Close pause / tutorial / unlock overlay |
| Blind Select | `python -m balatro4llm select-blind` | Enter the highlighted (`>>`) blind |
| Blind Select | `python -m balatro4llm skip-blind` | Skip Small or Big Blind to claim its Skip Tag |
| Blind Select | `python -m balatro4llm reroll-boss` | Reroll Boss Blind ($10; requires Director's Cut or Retcon voucher) |
| Playing Hand | `python -m balatro4llm play <idx...>` | Play 1–5 hand cards (e.g. `play 1 3 4 6 7`) |
| Playing Hand | `python -m balatro4llm discard <idx...>` | Discard 1–5 hand cards (e.g. `discard 2 5 8`) |
| Playing Hand | `python -m balatro4llm sort-hand <rank\|suit>` | Sort hand descending by rank or suit |
| Playing Hand | `python -m balatro4llm move-hand <from> <to>` | Move one hand card from 1-based slot `from` to slot `to` |
| Playing Hand | `python -m balatro4llm reorder-hand <order...>` | Permute all hand slots using a full 1-based permutation |
| Round Eval | `python -m balatro4llm cash-out` | Collect blind + hand + interest rewards and open the Shop |
| Shop | `python -m balatro4llm buy <idx> [--use]` | Buy Shop Card #`idx` (`--use` works even when consumable slots are `[slots full; --use OK]`) |
| Shop | `python -m balatro4llm buy-voucher [idx]` | Redeem Voucher #`idx` (default `1`) |
| Shop | `python -m balatro4llm buy-pack <idx>` | Buy and open Booster Pack #`idx` |
| Shop | `python -m balatro4llm reroll` | Reroll shop cards |
| Shop | `python -m balatro4llm next-round [--select\|--skip]` | Leave Shop to Blind Select, or immediately enter (`--select`) / skip (`--skip`) the previewed next blind |
| Booster Pack | `python -m balatro4llm pick <idx> [targets...]` | Pick Pack item #`idx`; pass 1-based hand indices for targeted Tarot/Spectral cards |
| Booster Pack | `python -m balatro4llm skip-pack` | Skip remaining choices in the Booster Pack |
| Inventory | `python -m balatro4llm use <idx> [targets...]` | Use owned Consumable #`idx` (pass 1-based hand indices when `usable (select ...)`) |
| Inventory | `python -m balatro4llm sell-joker <idx>` | Sell owned Joker #`idx` (fails safely on Eternal jokers) |
| Inventory | `python -m balatro4llm sell-consumable <idx>` | Sell owned Consumable #`idx` |
| Inventory | `python -m balatro4llm move-joker <from> <to>` | Move one owned Joker from 1-based slot `from` to slot `to` |
| Inventory | `python -m balatro4llm reorder-jokers <order...>` | Reorder all Jokers using a full 1-based permutation |

---

## Safe `batch` Examples
```powershell
# Move XMult Joker #2 to far right (#5), then play immediately
python -m balatro4llm --compact --auto-advance batch "move-joker 2 5" "play 1 2 3 4 5"

# Free a Joker slot when shop shows [slots full], buy Shop Card #1, and move it to slot #2
python -m balatro4llm --compact batch "sell-joker 3" "buy 1" "move-joker 5 2"

# Buy a Planet card immediately and enter the next blind straight from Shop (skips BLIND_SELECT round-trip!)
python -m balatro4llm --compact --auto-advance batch "buy 2 --use" "next-round --select"

# Move Death copy-target card from slot #1 to right of sacrifice card (#2), then cast Death
python -m balatro4llm --compact batch "move-hand 1 2" "pick 2 1 2"
```

---

## Critical Balatro Mechanics & Agent Strategy

### 1. Joker Ordering (Multiply AFTER Adding!)
Jokers trigger **left to right** (`[1]` → `[N]`).
- Place **+Chips** and **+Mult** jokers on the **left** and **XMult** jokers (`X2`, `X3`, `X4`, Polychrome) on the **right**.
- Check `Blueprint` (copies joker immediately to its **right**) and `Brainstorm` (copies joker `[1]` on the far **left**). Live compatibility is shown as `compat` / `INCOMPAT` (and uncopyable jokers show `no-copy` when you own Blueprint/Brainstorm).

### 2. Shop Availability Tags
Shop prices explicitly distinguish why an item cannot be bought as-is:
- **`[no $]`**: Not enough money (even after considering Credit Card bankruptcy floor).
- **`[slots full]`**: Affordable! Sell an owned Joker/Consumable first (e.g. `batch "sell-joker 2" "buy 1"`).
- **`[slots full; --use OK]`**: Affordable non-targeted Planet/Tarot consumable — buy and use immediately with `buy <idx> --use` without freeing a consumable slot!

### 3. Targeted Consumables & `Death` Ordering
- Targeted consumables show `use:N` / `use:min..max` in `--compact` mode (or `usable (select N)` in normal mode) when hand is visible. Pass 1-based hand indices directly: `use 1 2 5` or `pick 2 1`.
- **`Death` Tarot**: converts the **lower-index (left)** card into a copy of the **higher-index (right)** card. Use `move-hand <target_idx> <dest_idx>` first if the desired copy target currently sits to the left.

### 4. Deck Composition (`Deck Left`)
- Always check the `Deck Left (N): S:.. H:.. C:.. D:.. | A:.. K:.. | Special: ...` line before discarding (avoid chasing dead suits/ranks!) and in the Shop (pick Jokers/Planets that match your actual deck composition).

### 5. Economy & Interest
- You earn **+$1 interest per $5 held** at end of round (capped at **$25** = +$5/round unless upgraded by Seed Money / Money Tree).
- Cast `Temperance` / `The Hermit` *before* spending down cash.

### 6. Boss Blind Traps
Read `Blind: ... — <Effect>` before every hand:
- **The Pillar**: Cards played earlier in this Ante are `(DEBUFF)`.
- **Cerulean Bell**: One card is `(FORCED)` and must be included in `play` / `discard`.
- **The Eye / The Mouth / The Psychic**: The Eye bans repeating hand types (listed under `Already Played`); The Mouth locks you to one hand type; The Psychic requires playing **all 5 cards**.
- **Verdant Leaf**: Debuffs all cards until you `sell-joker <idx>`.
- **Face-down cards (`??`)**: Use `sort-hand rank` vs `sort-hand suit` to deduce hidden cards fairly.

### 7. Error & Timeout Recovery
- If a command times out during a long animation, run `python -m balatro4llm state` (or pass `--wait-timeout 60`) before acting again.
- If `batch` fails mid-sequence, read the printed current state (all prior steps already succeeded) and continue from there.
- If `state` shows `[RUN / WIN_SCREEN]` (Ante 8 cleared), use `endless` to continue into Endless Mode, `start` / `new-run` to start a new run, or `main-menu` to return to the Main Menu.
