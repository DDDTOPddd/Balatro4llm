---
name: balatro4llm
description: Play Balatro autonomously via the local balatro4llm MCP Server (preferred) or CLI bridge to the in-game Lua Mod (zero screenshots or mouse/keyboard emulation). Use when asked to inspect, play, or continue a run of Balatro.
---

# Playing Balatro via `balatro4llm` (MCP-First)

You control a live Balatro game with zero vision and zero GUI clicks through the local `balatro4llm` bridge talking to the non-blocking in-game Lua Mod (`127.0.0.1:12345`, NDJSON/TCP).

## Transport Selection (MCP-First)
1. **Use MCP tools whenever available (strongly preferred — ~8 ms/call over persistent TCP)**:
   - `balatro_ping()` — check Mod connectivity, version, stage/state, game speed, and RTT.
   - `balatro_state(compact=True, show_hands=False, as_json=False)` — inspect current state, `Deck Left`, blind previews, and `Actions:`.
   - `balatro_act(command, auto_advance=True, compact=True, wait_timeout=30.0)` — run one action using the command grammar below (e.g. `balatro_act(command="play 1 2 3 4 5")`).
   - `balatro_batch(steps, auto_advance=True, compact=True, wait_timeout=30.0)` — run deterministic multi-step sequences with known indices (e.g. `balatro_batch(steps=["move-joker 2 5", "play 1 2 3 4 5"])`).
   - **Do NOT shell out to `python -m balatro4llm` or `balatro-cli` when these `balatro_*` MCP tools are available.**
2. **CLI Fallback (only when MCP tools are NOT connected)**:
   - Run `python -m balatro4llm --compact --auto-advance <command>` (or `balatro-cli --compact --auto-advance <command>`).
   - UTF-8 is enforced natively by the CLI (no PowerShell encoding boilerplate needed).

## Core Operating Rules
1. **Never use screenshots, VLM vision, or GUI mouse/keyboard simulation.** Every piece of game state and every action goes through `balatro_*` MCP tools (or CLI fallback).
2. **Keep compact & auto-advance enabled** (on by default in MCP: `compact=True, auto_advance=True`):
   - `compact=True`: canonical English names, single-line owned Jokers / Consumables / Active Tags / terse `Actions:`, live hand play counts (`xN`), and Shop `Next:`/`Boss:` previews, while preserving full descriptions for new Shop/Pack/Skip Tag items.
   - `auto_advance=True`: automatically cashes out `ROUND_EVAL` straight into `SHOP` AND automatically enters mandatory Boss Blinds when they cannot be rerolled.
3. **Speed up animations once at run start**: run `set-speed 4` (native max, persisted) or `set-speed 8` / `set-speed 16` (runtime-only turbo; `>=4x` also accelerates `ROUND_EVAL` cash-out tallying).
4. **Every action automatically waits for animations/events (`G.E_MANAGER`) to finish** and returns the fresh stable state.
5. **All indices are 1-based** (`[1]`, `[2]`, ...) matching the exact numbers printed in the latest state output. Re-read indices after every action that modifies cards.
6. Prefer **`move-joker <from> <to>`** and **`move-hand <from> <to>`** when moving a single Joker or hand card (instead of computing a full permutation for `reorder-jokers`/`reorder-hand`).
7. Use **`balatro_batch`** (CLI: `batch`) for deterministic multi-step sequences where all indices are already known. **Never** batch actions that depend on unseen future draws or unseen shop/pack contents.

---

## Action Command Grammar (for `balatro_act` / `balatro_batch` / CLI)

| Phase | Command | Purpose |
|---|---|---|
| Speed | `set-speed <0.5\|1\|2\|4\|8\|16>` | Set animation speed (`0.5/1/2/4` saved; `8/16` runtime-only turbo; `>=4x` fast cash-out) |
| Menu / Run | `start [--deck b_red] [--stake <1-8\|max\|name>] [--seed SEED]` | Start a new run (`new-run` alias; `--deck` accepts key or English/localized name; `--stake` accepts `1..8`, `max`, or stake name like `green`/`绿注`; enforced against unlocked stakes shown in Main Menu) |
| Menu / Run | `continue` | Resume saved run from Main Menu |
| Win / End | `endless` | Enter Endless Mode from the Ante 8 Win screen |
| Win / End | `main-menu` | Return to Main Menu (from Win screen, Game Over, or mid-run) |
| Overlay | `dismiss-overlay` | Close pause / tutorial / unlock overlay |
| Blind Select | `select-blind` | Enter the highlighted (`>>`) blind |
| Blind Select | `skip-blind` | Skip Small or Big Blind to claim its Skip Tag |
| Blind Select | `reroll-boss` | Reroll Boss Blind ($10; requires Director's Cut or Retcon voucher) |
| Playing Hand | `play <idx...>` | Play 1–5 hand cards (e.g. `play 1 3 4 6 7`) |
| Playing Hand | `discard <idx...>` | Discard 1–5 hand cards (e.g. `discard 2 5 8`) |
| Playing Hand | `sort-hand <rank\|suit>` | Sort hand descending by rank or suit |
| Playing Hand | `move-hand <from> <to>` | Move one hand card from 1-based slot `from` to slot `to` |
| Playing Hand | `reorder-hand <order...>` | Permute all hand slots using a full 1-based permutation |
| Round Eval | `cash-out` | Collect blind + hand + interest rewards and open the Shop |
| Shop | `buy <idx> [--use]` | Buy Shop Card #`idx` (`--use` works even when consumable slots are `[slots full; --use OK]`) |
| Shop | `buy-voucher [idx]` | Redeem Voucher #`idx` (default `1`) |
| Shop | `buy-pack <idx>` | Buy and open Booster Pack #`idx` |
| Shop | `reroll` | Reroll shop cards |
| Shop | `next-round [--select\|--skip]` | Leave Shop to Blind Select, or immediately enter (`--select`) / skip (`--skip`) the previewed next blind |
| Booster Pack | `pick <idx> [targets...]` | Pick Pack item #`idx`; pass 1-based hand indices for targeted Tarot/Spectral cards |
| Booster Pack | `skip-pack` | Skip remaining choices in the Booster Pack |
| Inventory | `use <idx> [targets...]` | Use owned Consumable #`idx` (pass 1-based hand indices when `use:N` / `usable (select ...)`) |
| Inventory | `sell-joker <idx>` | Sell owned Joker #`idx` (fails safely on Eternal jokers) |
| Inventory | `sell-consumable <idx>` | Sell owned Consumable #`idx` |
| Inventory | `move-joker <from> <to>` | Move one owned Joker from 1-based slot `from` to slot `to` |
| Inventory | `reorder-jokers <order...>` | Reorder all Jokers using a full 1-based permutation |

---

## Safe `balatro_batch` Examples (MCP)

```json
// Move XMult Joker #2 to far right (#5), then play immediately
balatro_batch(steps=["move-joker 2 5", "play 1 2 3 4 5"])

// Free a Joker slot when shop shows [slots full], buy Shop Card #1, and move it to slot #2
balatro_batch(steps=["sell-joker 3", "buy 1", "move-joker 5 2"])

// Buy & use a Planet card and enter the next blind straight from Shop (skips BLIND_SELECT round-trip!)
balatro_batch(steps=["buy 2 --use", "next-round --select"])

// Move Death copy-target card from slot #1 to right of sacrifice card (#2), then cast Death
balatro_batch(steps=["move-hand 1 2", "pick 2 1 2"])
```

*(CLI fallback equivalent: `python -m balatro4llm --compact --auto-advance batch "<step1>" "<step2>"`)*

---

## Critical Balatro Mechanics & Agent Strategy

### 1. Joker & Hand Ordering (Multiply AFTER Adding!)
Jokers and held-in-hand cards trigger **left to right** (`[1]` → `[N]`).
- Place **+Chips** and **+Mult** jokers on the **left** and **XMult** jokers (`X2`, `X3`, `X4`, Polychrome) on the **right**.
- For held-in-hand triggers, place flat `+Mult` cards (e.g. Queens for `Shoot the Moon`, lowest card for `Raised Fist`) to the **left** of `Steel` (`X1.5`) cards using `move-hand`.
- Check `Blueprint` (copies joker immediately to its **right**) and `Brainstorm` (copies joker `[1]` on the far **left**). Live compatibility is shown as `compat` / `INCOMPAT` (and uncopyable jokers show `no-copy` when you own Blueprint/Brainstorm).

### 2. Shop Availability Tags
Shop prices explicitly distinguish why an item cannot be bought as-is:
- **`[no $]`**: Not enough money (even after considering Credit Card bankruptcy floor).
- **`[slots full]`**: Affordable! Sell an owned Joker/Consumable first (e.g. `balatro_batch(steps=["sell-joker 2", "buy 1"])`).
- **`[slots full; --use OK]`**: Affordable non-targeted Planet/Tarot consumable — buy and use immediately with `buy <idx> --use` without freeing a consumable slot!

### 3. Targeted Consumables & `Death` Ordering
- Targeted consumables show `use:N` / `use:min..max` in compact mode (or `usable (select N)` in normal mode) when hand is visible. Pass 1-based hand indices directly: `use 1 2 5` or `pick 2 1`.
- **`Death` Tarot**: converts the **lower-index (left)** card into a copy of the **higher-index (right)** card. Use `move-hand <target_idx> <dest_idx>` first if the desired copy target currently sits to the left.

### 4. Deck Composition (`Deck Left`)
- Always check the `Deck Left (N): S:.. H:.. C:.. D:.. | A:.. K:.. | Special: ...` line before discarding (avoid chasing dead suits/ranks!) and in the Shop (pick Jokers/Planets that match your actual deck composition).

### 5. Economy, Interest & Survival Spending
- You earn **+$1 interest per $5 held** at end of round (capped at **$25** = +$5/round unless upgraded by Seed Money / Money Tree). Cast `Temperance` / `The Hermit` *before* spending down cash.
- **Break the `$25` floor to survive**: Before leaving Shop (especially Ante 3+), check `Next:` / `Boss:` targets against your conservative 4-hand output. If scoring looks tight or you still lack `XMult`, spend below `$25` (reroll, buy Planets/Tarots/Glass/Steel) rather than dying with unspent cash.

### 6. High-Stake & Mid-Game Build Discipline
- **Slot budget (Ante 3+)**: Converge on **1 Chips + 1 scaling `+Mult` + 2 `XMult`** (at most **1** econ/utility slot). Replace flat early Jokers before the Ante 4–5 scaling cliff.
- **Prefer small hands on Blue+ Stakes**: With `-1` discard, **Pair / High Card** builds (scaling `+Mult` + Chips + `XMult` + **Blue Seal** planet generation) are far more reliable than brittle 5-card Flushes/Straights and do not fight held-in-hand `Steel`/Queen/King cards for hand space.
- **No greedy hand-burning**: Only trigger single-card first-hand utilities (`DNA`, `Sixth Sense`) when remaining hands comfortably clear the blind—never lose a round for a slow copy.
- **Eternal & Skip discipline**: Never buy temporary flat-value `Eternal` Jokers (only Eternals strong enough for Ante 8). Rarely skip blinds on high stakes (each skip costs scaling, Blue Seals, and a shop) unless a Tag like early `Investment Tag (+$25)` clearly outweighs it.

### 7. Boss Blind Traps
Read `Blind: ... — <Effect>` before every hand:
- **The Pillar**: Cards played earlier in this Ante are `(DEBUFF)`.
- **Cerulean Bell**: One card is `(FORCED)` and must be included in `play` / `discard`.
- **The Eye / The Mouth / The Psychic**: The Eye bans repeating hand types (listed under `Already Played`); The Mouth locks you to one hand type; The Psychic requires playing **all 5 cards**.
- **Verdant Leaf**: Debuffs all cards until you `sell-joker <idx>`.
- **Face-down cards (`??`)**: Use `sort-hand rank` vs `sort-hand suit` to deduce hidden cards fairly.

### 8. Error & Timeout Recovery
- If an action times out during a long animation, call `balatro_state()` (or pass `wait_timeout=60`) before acting again.
- If `balatro_batch` fails mid-sequence, read the returned current state (all prior steps already succeeded) and continue from there.
- If state shows `[RUN / WIN_SCREEN]` (Ante 8 cleared), use `endless` to continue into Endless Mode, `start` / `new-run` to start a new run, or `main-menu` to return to the Main Menu.
