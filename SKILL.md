---
name: balatro4llm
description: Play Balatro autonomously via the local balatro4llm CLI and in-game Lua Mod (zero screenshots or mouse/keyboard emulation). Use when asked to inspect, play, or continue a run of Balatro.
---

# Playing Balatro via `balatro4llm` CLI

You control a live Balatro game purely through the local CLI (`python -m balatro4llm ...`), which talks to the non-blocking in-game Lua Mod over `127.0.0.1:12345` (NDJSON/TCP).

## Core Operating Rules
1. **Never use screenshots, VLM vision, or GUI mouse/keyboard simulation.** Every piece of game state and every action goes through `python -m balatro4llm`.
2. **Start every session with `state`** (or `ping` if verifying connectivity):
   ```powershell
   python -m balatro4llm state
   ```
3. **Every action command automatically waits for animations/events (`G.E_MANAGER`) to finish** and prints the fresh stable state plus `Legal Actions`. Do not sleep manually or poll in a loop unless a timeout occurs.
4. **All indices are 1-based** (`[1]`, `[2]`, ...) matching the exact numbers printed in the latest state output. Re-read indices after every action that adds, removes, plays, discards, or reorders cards.
5. Pass `--json` before the subcommand (`python -m balatro4llm --json state`) if you need structured machine-readable JSON; pass `state --hands` to inspect all poker hand levels and base Chips × Mult.

---

## CLI Command Reference

| Phase | Command | Purpose |
|---|---|---|
| Health | `python -m balatro4llm ping` | Check Mod connectivity, version, stage/state, FPS |
| Inspect | `python -m balatro4llm state [--hands]` | Print current state & legal actions (`--hands` shows full hand table) |
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
| Playing Hand | `python -m balatro4llm reorder-hand <order...>` | Manually permute hand slots (full 1-based permutation, e.g. `reorder-hand 2 1 3 4 5 6 7 8`) |
| Round Eval | `python -m balatro4llm cash-out` | Collect blind + hand + interest rewards and open the Shop |
| Shop | `python -m balatro4llm buy <idx> [--use]` | Buy Shop Card #`idx` (`--use` buys and immediately uses a non-targeted consumable) |
| Shop | `python -m balatro4llm buy-voucher [idx]` | Redeem Voucher #`idx` (default `1`) |
| Shop | `python -m balatro4llm buy-pack <idx>` | Buy and open Booster Pack #`idx` |
| Shop | `python -m balatro4llm reroll` | Reroll shop cards |
| Shop | `python -m balatro4llm next-round` | Leave Shop and advance to Blind Select |
| Booster Pack | `python -m balatro4llm pick <idx> [targets...]` | Pick Pack item #`idx`; pass 1-based hand indices for targeted Tarot/Spectral cards |
| Booster Pack | `python -m balatro4llm skip-pack` | Skip remaining choices in the Booster Pack |
| Inventory | `python -m balatro4llm use <idx> [targets...]` | Use owned Consumable #`idx` (pass 1-based hand indices when it says `select ... hand card(s)`) |
| Inventory | `python -m balatro4llm sell-joker <idx>` | Sell owned Joker #`idx` (fails safely on Eternal jokers) |
| Inventory | `python -m balatro4llm sell-consumable <idx>` | Sell owned Consumable #`idx` |
| Inventory | `python -m balatro4llm reorder-jokers <order...>` | Reorder Jokers using full 1-based permutation (e.g. `reorder-jokers 1 2 4 3`) |

---

## Critical Balatro Mechanics & Agent Strategy

### 1. Joker Ordering (Multiply AFTER Adding!)
Jokers trigger **left to right** (`[1]` → `[N]`).
- Place **+Chips** and **+Mult** jokers on the **left** and **XMult** jokers (`X2`, `X3`, `X4`, Polychrome) on the **right**!
- Always check `Blueprint` (copies joker immediately to its **right**) and `Brainstorm` (copies joker `[1]` on the far **left**).
- Whenever you acquire a new XMult or +Mult joker out of order, immediately fix it with `reorder-jokers`.

### 2. Targeted Consumables & `Death` Ordering
- In `SELECTING_HAND`, `TAROT_PACK`, or `SPECTRAL_PACK`, targeted consumables show `usable (select N hand cards)`. Invoke them directly with hand indices:
  - Example: `use 1 2 5` or `pick 2 1`
- **`Death` Tarot ("Convert the left card into the right card")**:
  - Balatro always converts the **lower-index (left)** card into a copy of the **higher-index (right)** card!
  - If the card you want to copy has a *lower* index than the card you want to overwrite, call `reorder-hand` first to move the card to copy to the right, then run `use` / `pick`.

### 3. Economy & Interest
- You earn **+$1 interest per $5 held** at end of round (capped at **$25** = +$5/round unless upgraded by Seed Money / Money Tree).
- Avoid dropping below $25 unnecessarily in mid-game unless buying a run-defining Joker, Voucher, or Pack.
- Use `Temperance` (sum of Joker sell values) and `The Hermit` (doubles money up to +$20) *before* spending down your cash.

### 4. Boss Blind Traps to Watch For
Read the `Blind: ... — <Effect>` line before every hand!
- **The Pillar**: Cards played earlier in this Ante are marked `(DEBUFF)` and score 0 chips/triggers.
- **Cerulean Bell**: One card is marked `(FORCED)`. You **must** include its index in your `play` or `discard` command.
- **The Eye / The Mouth / The Psychic**: The Eye bans repeating poker hands; The Mouth locks you to one hand type; The Psychic requires playing **all 5 cards** (even throwaway cards) or the hand scores 0.
- **Verdant Leaf**: All cards are debuffed until you `sell-joker <idx>` (sell your weakest non-Eternal joker!).
- **Face-down cards (`??`)**: Shown as `?? (face-down)` under The Wheel / The House / The Mark / The Fish / Amber Acorn; use rank/suit sorting (`sort-hand rank` vs `sort-hand suit`) to deduce hidden ranks and suits fairly!

### 5. Error & Timeout Recovery
- If a command times out during a very long retrigger animation, run `python -m balatro4llm state` (or pass `--wait-timeout 60`) before taking the next action.
- If `state` shows `(OVERLAY)` on an Ante 8 Win screen, run `dismiss-overlay` to enter Endless Mode or `main-menu` / `start` for a new run.
- If connection fails, ask the user to confirm Balatro is running with Lovely and the `balatro4llm` mod installed (`python scripts/install_mod.py`).
