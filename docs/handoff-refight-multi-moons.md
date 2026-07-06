# Handoff — Re-fight & Dark Side multi-moons → shuffle + capture/ability bundles

**Status: ✅ IMPLEMENTED 2026-07-05** (this doc kept as the design record). Both open flags
confirmed with Devon: Dark Side location = `Dark Side: Arrival at Rabbit Ridge!`; bonus
grants are slot_data side-grants (Devon's "one MM item = +3 of a thing" framing — same as
the +3-moon weight), with the 3 captures/abilities rolled **random-from-locked per seed**.
All four tiers built (data, festival drop + gen roll, slot_data + client grant, tests+docs).
Full apworld test suite green. **Still TODO (Windows):** `python scripts/install_apworld.py`
+ regenerate — old seeds must be re-rolled. See memory [[refight-multimoon-bundles]].
**Tier:** apworld generation + slot_data + Python client. **No switch-mod rebuild**, **no
`sync_shine_table`** (location names are unchanged — the 7 locations already exist).
Deploy = `install_apworld.py` + regenerate a seed.

---

## The request (Devon, 2026-07-01)

In-game testing showed the **6 Mushroom Kingdom boss re-fights** award only a single
power moon, while in **vanilla they give a Multi-Moon**. Devon wants them corrected, and
extended:

1. **Add the 6 Mushroom re-fight multi-moons to the `multi_moon_shuffle`** (they become
   real shuffle slots like the story bosses).
2. **When you collect one of these multi-moons, also unlock 3 new captures** — "bonus on
   top" of the existing capturesanity capture items, the 3 chosen **randomly at
   generation time** ("random from locked").
3. **Ditto the Dark Side multi-moon awarding 3 different abilities** — add **1 Dark Side
   multi-moon** to the shuffle; receiving it unlocks **3 abilities** (bonus, random).

Answers captured from the AskUserQuestion rounds:
- Shuffle: **add to the shuffle** (not a fixed reward).
- Capture source: **bonus on top** (in addition to the pool's capture items; duplicates
  fall through to the existing coin path).
- Which unlocks: **random from locked** (rolled at generation from the pool).
- Dark Side scope: **add 1 DS multi-moon to the shuffle** → matching grows to **21↔21**.

---

## Why the re-fights "only give a single moon" — the real mechanism (verified this session)

- **In-game moon count is AP-item-driven, NOT local-collection-driven.** `MoonGetHook`
  ([switch-mod/src/hooks/MoonGetHook.cpp](../switch-mod/src/hooks/MoonGetHook.cpp)) just
  reports the check and calls `orig`; it never grants moon *count*. The AP-credit HUD only
  moves on **received items** (see CLAUDE.md deferred-work note "AP-credit-only counts").
- The physical Multi-Moon actor the game spawns is **vanilla-preserved** — the mod does
  not downgrade multi→single. So "gives a single power moon" is **not** a switch-mod bug;
  it's that these 6 locations are tagged **`junk_only: true`**, so they can only hold
  filler. Collecting one nets a single filler moon instead of a Multi-Moon item.
- Therefore the whole fix lives in the **apworld + client**, not the switch mod.

---

## Ground-truth data (all line numbers as of 2026-07-01)

### The 7 locations to tag (`apworld/smo_archipelago/data/locations.json`)
All currently `"junk_only": true` — **remove that** and add `"multi_moon": true`.

Mushroom re-fights (~lines 4557-4610, region `"Mushroom Kingdom"`):
- `Mushroom: Tussle in Tostarena: Rematch`   (Knucklotec re-fight)
- `Mushroom: Struggle in Steam Gardens: Rematch` (Torkdrift)
- `Mushroom: Dust-Up in New Donk City: Rematch`  (Mechawiggler)
- `Mushroom: Battle in Bubblaine: Rematch`    (Mollusque-Lanceur)
- `Mushroom: Blowup at Mount Volbono: Rematch`  (Cookatiel)
- `Mushroom: Rumble in Crumbleden: Rematch`    (Lord of Lightning)

Dark Side (line 4648, region `"Dark Side"`):
- `Dark Side: Arrival at Rabbit Ridge!`  ← **FLAG 1** (see Open decisions). This is the
  boss-rush culmination and a Multi-Moon in vanilla. Devon's "A Long Journey's End" does
  **not** exist; `Darker Side: Long Journey's End` (line 4864) is the *Darker Side* single
  moon and is the wrong one.

### The 14 existing `multi_moon: true` locations
locations.json lines 104, 290, 300, 806, 1052, 1071, 1662, 1723, 2152, 2474, 2904, 2945,
3373, 3446. (Cascade Atop Falls, Sand ×2, Lake, Wooded ×2, Metro, Snow, Seaside, Luncheon
×2, Bowser's, Ruined, etc.)

### The 14 existing Multi-Moon items (`apworld/smo_archipelago/data/items.json`)
`<Kingdom> Kingdom Multi-Moon` for Cascade(1) Sand(2) Lake(1) Wooded(2) Metro(2) Snow(1)
Seaside(1) Luncheon(2) Ruined(1) Bowser's(1) = **14**. There is already a
`Mushroom Kingdom Power Moon` item (line 206) but **no** Mushroom or Dark Side *Multi*-Moon.

### Items to add
- `Mushroom Kingdom Multi-Moon`, `count: 6`, same category/classification block as the
  other `*-Moon` MM items.
- `Dark Side Multi-Moon`, `count: 1`, same shape.

---

## Implementation plan (4 tiers)

### Tier 1 — data
- locations.json: 7 edits (drop `junk_only`, add `multi_moon`).
- items.json: 2 new item entries (see above). `_apply_multi_moon_rules` picks both up
  automatically (it keys on the `multi_moon` flag and `item.name.endswith(" Multi-Moon")`).
- Matching becomes a closed **21↔21** on non-festival goals. `adjust_filler_items`
  (`__init__.py`) trims 7 filler to keep item-count == location-count (the 7 locations
  already existed as junk_only, so no net location change; +7 MM items displaces 7 filler).

### Tier 2 — generation balancing (`apworld/smo_archipelago/hooks/World.py`)
- **Festival goal (`goal == 1`)**: `create_regions` removes post-Metro locations, so
  Mushroom + Dark Side locations **don't exist** under festival. Extend the existing
  festival Multi-Moon drop in `before_create_items_filler` (World.py:584, currently drops
  1 Metro MM) to **also drop all 7 new MM items** — otherwise 7 orphan items with no
  locations. Net: feature is **inert under festival**, active only on moon-hunt goals.
- **`_demote_surplus_kingdom_moons`** (World.py:~392) keys demotion on `KINGDOM_MOON_GATES`
  kingdoms. Mushroom/Dark Side aren't gate kingdoms, so their MMs are never demoted and
  stay at their default classification. **Watch point:** decide classification of the 7 new
  MM items. Recommended: default (progression) is fine — nothing gates on Mushroom/DS
  moons and those locations carry proper region/`requires` gating, so AP fill won't strand
  an early-needed progression MM on a post-game location (it places it elsewhere and fills
  the late slot with filler). If a `remaining_fill` "No more spots" appears, fall back to
  making the 7 new MM items **filler**.
- **Roll the bonus grants** from `world.random` (deterministic per seed): a flat ordered
  list of **18 capture names** (sample from the 42 captures) + **3 ability names** (from
  the ability set). Stash on the `world` object (mirror how kingdom-gate rolls are stashed)
  for slot_data.

### Tier 3 — slot_data + client grant
- **slot_data** — add `mm_bonus_captures` (ordered list of 18) + `mm_bonus_abilities` (3).
  Follow the existing `kingdom_gates` path: rolled in World.py → stashed on `world` →
  emitted wherever `fill_slot_data`/slot_data is assembled (grep `kingdom_gates` across the
  apworld to find the exact emit site — `__init__.py` and/or a hook).
- **client** (`apworld/smo_archipelago/client/context.py`):
  - Read the two fields in the `Connected` handler (~line 887, alongside `capturesanity`
    / `abilitysanity` / `goal`).
  - In the ReceivedItems handler (`on_received_items`, line 577): the 6 Mushroom MM items
    **share one name** (`Mushroom Kingdom Multi-Moon`) so they can't be mapped per-item.
    **Consume the ordered capture list in chunks of 3** each time a `Mushroom Kingdom
    Multi-Moon` arrives (order-agnostic; all 6 collectively unlock the 18). For each chunk,
    fire 3 capture `ItemMsg`s via the existing `switch.send_item(ItemMsg(kind="capture",
    cap=…, hack_name=capture_map.cap_to_hack(cap), …))` path (dupes → coins automatically).
  - For `Dark Side Multi-Moon`, fold its 3 abilities into the **ability snapshot** —
    `push_ability_state` ships a full per-ability count table. **Sub-task:** find where the
    ability counts are sourced (grep `push_ability_state` / `ability` in `state.py` +
    `switch_server.py`) and add the bonus abilities to that count so the snapshot includes
    them. (Abilities don't flow through `send_item` — see the `ItemKind.ABILITY` branch at
    context.py:625-630.)
  - **Idempotency:** the handler already skips `pos < initial_mirror_len` on reconnect
    replays. Make bonus consumption key on the received-item index (not a running counter
    that would re-fire on replay). Capture unlock is idempotent (dupe→coins high-water);
    ability snapshot is a full overwrite (idempotent). Verify no double coin-grant on
    reconnect.
  - The MM items **still grant their 3 moons** via the existing moon path — the
    captures/abilities are **bonus side-grants**, not real pool items.

### Tier 4 — tests + docs
- `apworld/smo_archipelago/tests/test_multi_moon_shuffle.py`: update to **21↔21**; assert
  the 7 new items are dropped under the festival goal (parallels the Metro-MM drop test).
- Add a client test: receiving 2× `Mushroom Kingdom Multi-Moon` fires captures[0:3] then
  [3:6]; receiving `Dark Side Multi-Moon` adds 3 abilities to the snapshot; reconnect
  replay does not double-grant.
- Update the `_apply_multi_moon_rules` docstring (World.py:730) "14↔14" → "21↔21".
- CLAUDE.md: update the `multi_moon_shuffle` Devon-fork note (13 MM ↔ 13 locations → 20/21).
- Write a memory file (`refight-multimoon-bundles.md`) + MEMORY.md index line.

---

## Open decisions to confirm at session start

- **FLAG 1 — Dark Side location.** Use `Dark Side: Arrival at Rabbit Ridge!` as the DS
  multi-moon? (Recommended — it's the vanilla Multi-Moon there. `A Long Journey's End`
  doesn't exist.)
- **FLAG 2 — bonus grants are slot_data side-grants, not extra AP items.** They don't
  affect logic/fill; they just unlock in-game (dupes → coins). This is what "bonus on top"
  implies. Confirm before building — if Devon instead wants them to be *real AP items*
  (affecting logic), the design changes materially (pool sizing, reachability).

---

## Gotchas / invariants that bit or would bite

- **junk_only ⨯ multi_moon conflict.** `_apply_junk_only_rules` (World.py:759) forbids
  advancement AND useful; `_apply_multi_moon_rules` requires an MM item (progression-
  capable). Must remove `junk_only` from all 7 tagged locations.
- **Festival goal removes post-Metro content** — Mushroom + Dark Side locations vanish, so
  the 7 items must be dropped there too (Tier 2).
- **6 identical Mushroom MM item names** — no per-item mapping; use ordered consumption.
- **Deploy is apworld-only.** No switch-mod rebuild (client emits existing capture/ability
  wire msgs the mod already handles). No `sync_shine_table` (names unchanged). Just
  `python scripts/install_apworld.py` + regenerate. Old seeds must be re-rolled.
- **Generate loads the installed zip, not source** — rebuild the zip before Generate
  (CLAUDE.md "Generate runs the INSTALLED apworld zip").

---

## Kick-off prompt for the new session

> Implement the re-fight & Dark Side multi-moon feature per
> `docs/handoff-refight-multi-moons.md`. First confirm the two open FLAGs with me
> (Dark Side location = `Dark Side: Arrival at Rabbit Ridge!`; bonus captures/abilities as
> slot_data side-grants, not real AP items). Then build all four tiers: tag the 7 locations
> `multi_moon` (drop `junk_only`), add the `Mushroom Kingdom Multi-Moon` (×6) +
> `Dark Side Multi-Moon` (×1) items, handle the festival-goal drop of the 7 new items, roll
> 18 bonus captures + 3 bonus abilities from `world.random` into new slot_data fields
> (`mm_bonus_captures` / `mm_bonus_abilities`), and grant them in the client's ReceivedItems
> handler (ordered-chunk consumption for the shared-name Mushroom MMs; fold the 3 abilities
> into the ability snapshot). Update `test_multi_moon_shuffle.py` (21↔21 + festival drop),
> add a client bonus-grant test, fix the `_apply_multi_moon_rules` docstring, and update
> CLAUDE.md + a memory file. Do NOT rebuild the switch-mod or run `sync_shine_table` — this
> is apworld-only; the deploy is `install_apworld.py` + regenerate.
