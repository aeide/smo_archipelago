# P3 — Mushroom→captures, Dark Side→abilities, junk-only MK/DS checks

Detailed implementation plan for review. Drafted 2026-06-13, after P1 verified in-game.
Supersedes the short P3 sketch in `plan-v2-vision.md` (that section stays as the high-level
index). Read `CLAUDE.md` invariants first; nothing here may reshape committed fixed-buffer
wire contracts.

## Locked decisions (Devon, 2026-06-13)

1. **Starting captures = Frog + Chain Chomp + 1 random ONLY.** Spark Pylon and Bowser are
   shuffled as real pool items this iteration (NOT precollected). `_precollect_starting_captures`
   in `hooks/World.py` already does exactly this — **no change needed** to the precollect logic.
2. **Split the two part-captures into their variants:** `Puzzle Part` → two items, and
   `Picture Match Part` → two items. Exact variant names sourced from the upstream
   manual-apworld lineage / `locations.json` (never the romfs dump).
3. **Plan-first** — this document. No code until approved.

## Scope boundary (what P3 is and is NOT)

- **IS:** add MK + Dark Side moon *locations* as excluded junk-only checks; complete the capture
  roster; add the 20 ability items; add the duplicate→coins "clone" items; wire ability items
  client→Switch and have the Switch **track** them.
- **IS NOT:** ability *enforcement* (gating Mario's moveset). That is **P4** (the hard hooking
  phase). In P3 abilities are received, stored in a bitfield, and announced via a Cappy bubble —
  the game stays fully playable because nothing is locked yet. This keeps P3's Switch side light:
  **no new game symbols are required** (capture grant + `addCoin` already exist; ability tracking
  is a pure bitfield).

---

## Architecture facts this plan relies on

- **Manual-AP framework.** Items/locations/regions/categories are data in
  `data/{items,locations,regions,categories}.json`; custom logic lives in `hooks/*.py`.
- **IDs are positional.** `Game.py` derives a `starting_index`; each item/location gets
  `starting_index + position`. **Appending** new entries to the JSON arrays preserves every
  existing ID (safe for in-flight seeds and the extracted `shine_map.json`/`capture_map.json`
  joins). **Inserting mid-array shifts IDs** — never do it. All P3 additions are appends.
- **`classify_item` (client/datapackage.py)** keys off the item's `category` list:
  `"Capture"` → `ItemKind.CAPTURE`; `"X Kingdom Power/Multi-Moon"` → `ItemKind.MOON`; else
  `OTHER`. Abilities need a new `Ability` category → new `ItemKind.ABILITY`.
- **Excluded junk-only mechanism already exists.** `hooks/World.py::_apply_filler_only_rules`
  reads a `filler_only: true` flag on locations and adds `add_item_rule(loc, not item.advancement)`.
  MK/DS junk checks reuse this exact pattern (a `junk_only`/`filler_only` flag), so no fill-API
  work is needed.
- **Capture item flow today:** AP item → `classify_item` CAPTURE → `ItemMsg(kind="capture",
  cap, hack_name)` → Switch `applyOnFrame` switch-case `Capture`: sets `captures_unlocked[bit]`,
  calls `grantCapture`, and already computes `already_owned = captureAlreadyInDictionary(hack)`
  (currently only used to suppress a duplicate Cappy bubble). The clone→coins feature hooks
  right here.
- **P1 coin path** (`CoinGrant` wire msg → `ApState::applyCoinGrant` → `addCoin`) is the reuse
  target for every duplicate→100-coins conversion.

---

## Item accounting

### Captures (current 44 → target roster)

Append to `items.json` (keep existing names/spellings — `locations.json` rules and the extracted
`capture_map.json` key off them):

- **New unique captures (3):** `Broode's Chain Chomp` (progression — required for Cascade peace →
  moon rock; logic must make it reachable pre-Cascade-peace, lands early-sphere in practice),
  `Letter`, `Yoshi`.
- **Now shuffled (2):** `Spark Pylon`, `Bowser` (per decision #1 — real pool items, not starters).
- **Part-variant splits (+2 net):** replace single `Puzzle Part` with two variant items, and
  single `Picture Match Part` with two. *Exact names TBD from upstream* — placeholder:
  `Puzzle Part (Lake)` / `Puzzle Part (Metro)`, `Picture Match Part (Goomba)` /
  `Picture Match Part (Mario)`. ⚠ This RENAMES the existing single entries; confirm whether the
  extracted `capture_map.json` / `sync_capture_table.py` join tolerates the rename (it keys on
  `cap_name` → `hack_name`; both variants likely share one hack, so the capture_map may need a
  variant→hack mapping, or both variants map to the same hack). **Resolve before editing.**
- **Capture clones (duplicate→coins), +1 copy each (6):** `Bullet Bill`, `Sherm`, `Parabones`,
  `Banzai Bill`, `Bowser`, `Spark Pylon`. A second copy enters the pool; if the Switch already
  owns that capture when the copy arrives, it converts to 100 coins instead of a no-op.

Net captures in pool ≈ 44 + 3 + (splits +2) + 6 clones = **~55 entries**, minus the 3
precollected starters that get pulled out at generation (Frog, Chain Chomp, +1 random).

### Ability items (new — 20)

New category `Ability` in `categories.json`; all appended to `items.json` with
`"category": ["Ability"]`. Per `plan-v2-vision.md` item accounting:

- **Unique (11):** Up Throw, Down Throw, Spin Throw, Backflip, Side Flip, Cap Bounce,
  Ground Pound Jump, Long Jump, Wall Slide, Ledge Grab, Climb.
- **Progressive chains (7 steps, via `count`):** `Progressive Jump` ×2 (Double→Triple),
  `Progressive Crouch` ×3 (Crouch→Roll→Roll Boost), `Progressive Ground Pound` ×2
  (Ground Pound→Dive).
- **Clones (2):** one extra `Wall Slide` (dup→coins) and one extra `Progressive Ground Pound`
  (⚠ chain-clone nuance: a 3rd `Progressive Ground Pound` copy makes Dive easier to find rather
  than duplicating Ground Pound — flagged in plan-v2; keep as-is unless Devon wants GP cloned
  without easing Dive, which needs a different design).

Classification flags (`progression`/`useful`/`filler`) per item set in `items.json`; abilities
that gate logic in P6 should be `progression` (chains especially).

### Cap moons → coins (P1, done) and generic MK moon item

`Cap Kingdom Power Moon` stays `filler` (P1 grants its coins on the Switch). The existing generic
`Mushroom Kingdom Power Moon` (count 1, filler) — keep as filler or drop; it's vestigial now that
MK *locations* become junk checks. Decide during implementation; low impact.

---

## Locations: MK (104) + Dark Side (24) as excluded junk-only checks

- **Source names** from the upstream manual-apworld lineage (same provenance as the existing
  `locations.json`). `data/moon_requirements.json` already holds ~340 unmatched MK/Dark-Side/
  post-game CSV rows — useful cross-reference, but the canonical `"Mushroom: …"` / `"Dark Side: …"`
  location names must come from the community apworld, **never the romfs dump** (CLAUDE.md IP rule;
  no bulk paste >~5 names into commits/docs).
- **Append** to `locations.json` with: `category` (new `"Mushroom Kingdom"` / `"Dark Side"` /
  `"Darker Side"` tags), `region` (new regions below), `requires` (vanilla post-game gating), and
  `filler_only: true` (or a new `junk_only: true` flag wired into `_apply_filler_only_rules`).
  This makes them collectible checks that the fill never fills with progression/useful.
- **Counts** to reconcile against upstream: MK ~104, Dark Side ~24 (Darker Side is a single moon;
  confirm whether it's its own region). Exact counts verified at implementation time.

## Regions: add MK + Dark Side off the post-game chain

`regions.json` currently ends at `Moon Kingdom`. Add:

- `"Mushroom Kingdom"`: `requires` = game-clear gate (reaching Moon Kingdom + its story
  Multi-Moon, i.e. the victory condition). `connects_to`: `["Dark Side"]` (and Darker Side if
  separate).
- `"Dark Side"` (and optionally `"Darker Side"`): `requires` post-game / moon-count gate per
  vanilla.

Because these locations are junk-only, their reachability never constrains the progression fill —
but AP still requires them reachable, so the gating must be satisfiable in every seed. Add a
reachability guard test (mirror `test_randomize_kingdom_gates`'s sweep).

---

## Wire protocol — ability items (additive, fixed-buffer safe)

Two options; recommend **Option A**:

- **Option A (reuse ItemMsg):** add `ItemKind.ABILITY = "ability"` and carry the ability id in
  the existing `ItemMsg` (e.g. reuse `cap`/`name`, or add an `ability` field). Minimal new wire
  surface; the Switch `applyOnFrame` switch gets an `Ability` case.
- **Option B (new `AbilityUnlockMsg`):** dedicated message keyed by ability id. Cleaner
  separation but more wire surface.

Either way:
- **Client:** `classify_item` returns `ABILITY` for `"Ability"`-category items; the receive path
  forwards an ability message (same place captures are forwarded in `context._process_received_items`
  / `switch_server`). Document in `docs/wire-protocol.md`.
- **Idempotent HELLO replay:** abilities, like captures, replay on HELLO. Use a balance/bitfield
  model (the Switch ignores an ability it already has), NOT naive re-apply — clones make naive
  replay wrong (same M6-D rule).
- **Duplicate → coins:** if the ability (or capture clone) is already unlocked when the item
  arrives, convert to +100 coins via the P1 `addCoin` path instead of a no-op.

## Switch-mod (light — no new game symbols)

- `ApState::ability_unlocked` — a bitfield (mirror of `captures_unlocked`), one bit per ability id.
  Worker thread sets the bit on receipt; frame thread reads it (P4 will gate moves on it).
- `ApProtocol` parse + `ApClient` dispatch for the new message (mirror `coin_grant`/capture paths).
- **Duplicate handling:** on receiving an ability/capture already in the bitfield/dictionary,
  call the existing coin-grant path (+100). Capture clones reuse the existing
  `captureAlreadyInDictionary` check in `ApState::applyOnFrame` (today it only suppresses the
  bubble — extend it to grant coins).
- **Display:** Cappy speech bubble on ability unlock (`CappyMessenger`), matching capture unlocks.
- No `HookSymbols.hpp` / `.sym` additions needed in P3 (deferred to P4 enforcement).

---

## Tests (apworld, host-runnable; gate live-AP tests on `SMOAP_LIVE_AP`)

- Item pool: ability items present with correct counts; chains have right `count`; clones present;
  capture roster includes the 5 additions + 2 split variants; existing capture names unchanged.
- `classify_item("<ability>")` → ABILITY; `classify_item("Goomba")` → CAPTURE still.
- Precollect unchanged: exactly 3 captures precollected (Frog, Chain Chomp, +1 random); Spark Pylon
  & Bowser remain in the pool.
- MK/DS locations: present, tagged junk-only, never receive progression/useful (assert the item
  rule); regions reachable.
- ID stability: a snapshot test that existing item/location IDs are unchanged after the appends
  (guards against accidental mid-array insertion).
- Fill succeeds across: goal (standard/festival) × multi_moon_shuffle × randomize_kingdom_gates.
- Switch host-tests (`smo-host-tests`): protocol round-trip for the ability message; bitfield
  set/replay idempotency; duplicate→coin conversion logic where extractable.

---

## Work split & suggested order

**Phase 3a — apworld/Python/data (Sonnet; no Switch needed):**
1. Resolve exact names: capture variant splits, MK/DS location names + counts (from upstream).
2. `categories.json`: add `Ability` (and MK/DS/Darker-Side location categories).
3. `items.json`: append ability items (11 + 7 chain steps + 2 clones), capture additions
   (Broode's Chain Chomp, Letter, Yoshi, Spark Pylon, Bowser), capture clones (6), split the two
   part-captures. **Append-only.**
4. `client/datapackage.py` + `client/protocol.py`: `ItemKind.ABILITY`, classify, forward path.
5. `locations.json` + `regions.json`: MK/DS junk-only locations + regions + post-game gating;
   extend `_apply_filler_only_rules` if using a new `junk_only` flag.
6. `docs/wire-protocol.md`: document the ability message.
7. Tests (all of the above).
8. Re-run `scripts/sync_capture_table.py` after `items.json` edits (captures changed); confirm the
   part-variant split doesn't break the `capture_map.json` join.

**Phase 3b — Switch-mod (Opus + smo-build session; light, no symbol discovery):**
9. `ApProtocol`/`ApClient`: parse + dispatch ability message.
10. `ApState`: `ability_unlocked` bitfield; duplicate-capture/ability → `addCoin(100)`.
11. `CappyMessenger`: ability-unlock bubble.
12. Host-tests; build via `build_switchmod.py` (remember: Python 3.11+ with `lz4 pyelftools mmh3`;
    deploy to the real Ryujinx mods dir — `%APPDATA%\Ryujinx\mods\contents\<tid>\<mod>\exefs\`,
    confirmed via "Open Mods Directory").

---

## Open items to resolve before/at implementation

1. **Capture variant naming + capture_map join.** ✅ RESOLVED 2026-06-14. Each split variant has
   its OWN distinct hack_name (Puzzle Part Lake=`GotogotonLake`/Metro=`GotogotonCity`; Picture
   Match Goomba=`FukuwaraiFacePartsKuribo`/Mario=`FukuwaraiFacePartsMario`) — NOT a shared hack.
   But `capture_map.json` keys both under the OLD names (`Puzzle Part`/`Picture Match Part`), so the
   split item names aren't map keys. Handled by `VARIANT_CAP_HACK_OVERRIDE` in BOTH `client/maps.py`
   (runtime grant) and now `scripts/sync_capture_table.py` (Switch table gen). No aliases needed
   (each variant → exactly one hack). NB: while fixing this we found `sync_capture_table.py` was
   emitting an IDENTITY hack-name table entirely (it couldn't find `capture_map.json` — looked in
   `client/data/`, real map is `%APPDATA%/SMOArchipelago/data/`), which fail-opened the capture gate
   for 46/51 captures. Both bugs fixed; see `plan-v2-vision.md` 2026-06-14. `sync_shine_table.py`
   still has the same path bug (unfixed).
2. **Exact MK/DS/Darker Side counts and names** from upstream (104/24 are approximate).
3. **Generic `Mushroom Kingdom Power Moon` item** — keep as filler or remove.
4. **Progressive Ground Pound clone semantics** (eases Dive vs. true GP clone) — confirm with
   Devon; current plan keeps the chain-advancing behavior.
5. **Ability message shape** — Option A (extend `ItemMsg`) vs B (new msg). Recommend A.
6. **Bound-item display** ("MK moon" framing for captures, "Dark Side moon" for abilities) is a
   display-layer concern; functional items are categorized Capture/Ability. Defer the in-game
   display binding to P5 (per-kingdom colors / labels) unless Devon wants it now.

## Risks

- **ID drift** if anything is inserted rather than appended → breaks in-flight seeds and the
  extracted-map joins. Mitigated by the ID-stability test.
- **capture_map join** for split variants (open item #1).
- **Reachability** of junk-only MK/DS regions must hold every seed (guard test).
- Clone→coins on the Switch must be idempotent across HELLO replay (balance/bitfield model, not
  naive re-apply).
