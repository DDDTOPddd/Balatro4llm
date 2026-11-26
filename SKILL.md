---
name: balatro4llm
description: Play Balatro autonomously via the local balatro4llm CLI and in-game Lua Mod (zero screenshots or mouse/keyboard emulation). Use when asked to inspect, play, or continue a run of Balatro.
---

# Playing Balatro via `balatro4llm` CLI

You control a live Balatro game purely through the local CLI (`python -m balatro4llm ...`), which talks to the non-blocking in-game Lua Mod over `127.0.0.1:12345` (NDJSON/TCP).

## Core Operating Rules
1. **Never use screenshots, VLM vision, or GUI mouse/keyboard simulation.** Every piece of game state and every action goes through `python -m balatro4llm`.
2. **Recommended efficiency flags** (pass before the subcommand, or set via env vars):
   - `--compact` (`BALATRO4LLM_COMPACT=1`): removes duplicate bilingual parentheses and condenses Jokers during hand play to single-line `Name(+live_stats)`.
   - `--auto-cash-out` (`BALATRO4LLM_AUTO_CASH_OUT=1`): automatically cashes out when a play beats a blind and enters `ROUND_EVAL`, landing straight in `SHOP`.
   - `--auto-advance` (`BALATRO4LLM_AUTO_ADVANCE=1`): enables `--auto-cash-out` AND automatically enters a mandatory Boss Blind (when it cannot be rerolled).
   ```powershell
   python -m balatro4llm --compact --auto-cash-out state
   ```
3. **Every action command automatically waits for animations/events (`G.E_MANAGER`) to finish** and prints the fresh stable state (including `Deck Left` remaining draw-pile composition) plus `Legal Actions`.
4. **All indices are 1-based** (`[1]`, `[2]`, ...) matching the exact numbers printed in the latest state output. Re-read indices after every action that modifies cards.
5. Use **`batch`** for deterministic multi-step sequences where all indices are already known (e.g. `reorder-jokers` + `play`, buying two known shop cards, or `use` + `sell-consumable`). **Never** batch actions that depend on unseen future draws or unseen shop/pack contents!
6. Pass `--json` before the subcommand if you need structured JSON; pass `state --hands` to inspect all poker hand levels.

---

## CLI Command Reference

| Phase | Command | Purpose |
|---|---|---|
| Health | `python -m balatro4llm ping` | Check Mod connectivity, version, stage/state, FPS |
| Inspect | `python -m balatro4llm state [--hands]` | Print current state, remaining deck composition & legal actions |
| Batch | `python -m balatro4llm batch "<cmd1>" "<cmd2>" ...` | Run deterministic actions in sequence, waiting between steps (fail-fast + prints live state on error) |
| Menu / Run | `python -m balatro4llm start [--deck b_red] [--stake 1] [--seed SEED]` | Start a new run (from Main Menu or Game Over) |
| Menu / Run | `python -m balatro4llm continue` | Resume saved run from Main Menu |
| Menu / Run | `python -m balatro4llm main-menu` | Return to Main Menu |
| Overlay | `python -m balatro4llm dismiss-overlay` | Continue to Endless Mode after Ante 8 win, or close pause/tutorial overlay |
| Blind Select | `python -m balatro4llm select-blind` | Enter the highlighted (`>>`) blind |
| Blind Select | `python -m balatro4llm skip-blind` | Skip Small or Big Blind to claim its Skip Tag |
| Blind Select | `python -m balatro4llm reroll-boss` | Reroll Boss Blind ($10; requires Director's Cut or Retcon voucher) |
| Playing Hand | `python -m balatro4llm play <idx...>` | Play 1–5 hand cards (e.g. `play 1 3 4 6 7`) |
| Playing Hand | `python -m balatro4llm discard <idx...>` | Discard 1–5 hand cards (e.g. `discard 2 5 8`) |
| Playing Hand | `python -m balatro4llm sort-hand <rank\|suit>` | Sort hand descending by rank or suit |
| Playing Hand | `python -m balatro4llm reorder-hand <order...>` | Manually permute hand slots (full 1-based permutation) |
| Round Eval | `python -m balatro4llm cash-out` | Collect blind + hand + interest rewards and open the Shop |
| Shop | `python -m balatro4llm buy <idx> [--use]` | Buy Shop Card #`idx` (`--use` buys and immediately uses a non-targeted consumable) |
| Shop | `python -m balatro4llm buy-voucher [idx]` | Redeem Voucher #`idx` (default `1`) |
| Shop | `python -m balatro4llm buy-pack <idx>` | Buy and open Booster Pack #`idx` |
| Shop | `python -m balatro4llm reroll` | Reroll shop cards |
| Shop | `python -m balatro4llm next-round` | Leave Shop and advance to Blind Select |
| Booster Pack | `python -m balatro4llm pick <idx> [targets...]` | Pick Pack item #`idx`; pass 1-based hand indices for targeted Tarot/Spectral cards |
| Booster Pack | `python -m balatro4llm skip-pack` | Skip remaining choices in the Booster Pack |
| Inventory | `python -m balatro4llm use <idx> [targets...]` | Use owned Consumable #`idx` (pass 1-based hand indices when `usable (select ...)`) |
| Inventory | `python -m balatro4llm sell-joker <idx>` | Sell owned Joker #`idx` (fails safely on Eternal jokers) |
| Inventory | `python -m balatro4llm sell-consumable <idx>` | Sell owned Consumable #`idx` |
| Inventory | `python -m balatro4llm reorder-jokers <order...>` | Reorder Jokers using full 1-based permutation (e.g. `reorder-jokers 1 2 4 3`) |

---

## Safe `batch` Examples
```powershell
# Reorder Jokers so XMult is on the far right, then play immediately
python -m balatro4llm --compact --auto-cash-out batch "reorder-jokers 1 2 3 5 4" "play 1 2 3 4 5"

# Buy two known shop cards (remember: buying #1 shifts old #2 to #1!) and leave shop
python -m balatro4llm --compact --auto-advance batch "buy 1" "buy 1" "next-round"

# Reorder hand for Death Tarot (move copy target to right), then cast Death
python -m balatro4llm --compact batch "reorder-hand 2 1 3 4 5 6 7 8" "pick 2 1 2"
```

---

## Critical Balatro Mechanics & Agent Strategy

### 1. Joker Ordering (Multiply AFTER Adding!)
Jokers trigger **left to right** (`[1]` → `[N]`).
- Place **+Chips** and **+Mult** jokers on the **left** and **XMult** jokers (`X2`, `X3`, `X4`, Polychrome) on the **right**.
- Check `Blueprint` (copies joker immediately to its **right**) and `Brainstorm` (copies joker `[1]` on the far **left**).

### 2. Targeted Consumables & `Death` Ordering
- Targeted consumables show `usable (select N)` when hand is visible. Pass 1-based hand indices directly: `use 1 2 5` or `pick 2 1`.
- **`Death` Tarot**: converts the **lower-index (left)** card into a copy of the **higher-index (right)** card. Use `reorder-hand` first if the desired copy target currently sits to the left.

### 3. Deck Composition (`Deck Left`)
- Always check the `Deck Left (N): S:.. H:.. C:.. D:.. | A:.. K:.. | Special: ...` line before discarding (avoid chasing dead suits/ranks!) and in the Shop (pick Jokers/Planets that match your actual deck composition).

### 4. Economy & Interest
- You earn **+$1 interest per $5 held** at end of round (capped at **$25** = +$5/round unless upgraded by Seed Money / Money Tree).
- Cast `Temperance` / `The Hermit` *before* spending down cash.

### 5. Boss Blind Traps
Read `Blind: ... — <Effect>` before every hand:
- **The Pillar**: Cards played earlier in this Ante are `(DEBUFF)`.
- **Cerulean Bell**: One card is `(FORCED)` and must be included in `play` / `discard`.
- **The Eye / The Mouth / The Psychic**: The Eye bans repeating hand types (listed under `Already Played`); The Mouth locks you to one hand type; The Psychic requires playing **all 5 cards**.
- **Verdant Leaf**: Debuffs all cards until you `sell-joker <idx>`.
- **Face-down cards (`??`)**: Use `sort-hand rank` vs `sort-hand suit` to deduce hidden cards fairly.

### 6. Error & Timeout Recovery
- If a command times out during a long animation, run `python -m balatro4llm state` (or pass `--wait-timeout 60`) before acting again.
- If `batch` fails mid-sequence, read the printed current state (all prior steps already succeeded) and continue from there.
- If `state` shows `(OVERLAY)` on an Ante 8 Win screen, run `dismiss-overlay` to enter Endless Mode or `start` / `main-menu`.
