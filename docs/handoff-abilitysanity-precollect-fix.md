# Handoff — abilitysanity=false breaks real-logic generation (precollect fix)

**For a fresh session (Sonnet).** Read CLAUDE.md first (disk-truth file tools
only; pytest/Generate on Windows; `install_apworld.py` before any Generate).
Small, standalone fix — no Switch-mod work, no wire changes.

## The bug (diagnosed 2026-07-07, Generate seed 81285200019472365252)

`abilitysanity: false` + `no_logic: false` reliably kills generation with
`FillError: No more spots to place 37 items` (goal unbeatable). Root cause:

- `_drop_ability_items_if_disabled` (`hooks/World.py`, called from the
  before-create-items path) removes every `Ability`-category item from the
  pool when abilitysanity is off, and the client opens the Switch gate
  (`ability_state` `enforce=False`). **But nothing compensates logic-side.**
- The compiled moon/door/victory `requires` strings still demand ability
  items (`|Progressive Ground Pound:1|`, `|Wall Slide|`, `|Cap Bounce|`, …).
  With zero such items in existence, every location whose every method needs
  an ability is permanently unreachable — including progression anchors
  (e.g. `Bowser's: Showdown at Bowser's Castle` needs
  `|Progressive Ground Pound:1|` in every disjunct) and one victory branch.
- Under the world's minimal accessibility, AP's fill skips reachability
  checks while the god-state is beatable, scatters gate-currency moons into
  the (huge) dead zone, and the endgame collapses: unplaced progression,
  `can_beat_game()` false, FillError.
- Masked until now because test YAMLs ran `no_logic: true`. NOT a P2
  regression — P2 never touched this path.
- Contrast: `capturesanity: false` is fine (capture items stay in the pool;
  region-level capture gates use the `{YamlDisabled(capturesanity)}` escape —
  see `Pokino` in `data/regions.json`).

## The fix

When abilitysanity is OFF, **precollect every Ability item at its full copy
count** (Progressive Crouch ×3, Progressive Ground Pound ×3, Progressive
Jump ×2, singles ×1 — counts come from `data/items.json`, don't hardcode) in
addition to the existing pool drop. Precollected items satisfy the `|ability|`
tokens in `CollectionState`, so logic stays sound; the pool drop keeps the
item/location counts as today.

- Pattern to copy: `_precollect_starting_captures()` in `hooks/World.py`
  (`multiworld.push_precollected(world.create_item(name))`). Enumerate names
  via the existing `_names_in_item_category(world, "Ability")` helper; copy
  counts from each item's `count` in `world.item_name_to_item`.
- Keep `_drop_ability_items_if_disabled` unchanged; add the precollect beside
  it (same option guard, inverted: only when abilitysanity is OFF).
- Client side needs NO change: precollected items arrive as starting
  inventory and fold into the ability snapshot, which is harmless — the gate
  is already open (`enforce=False`). Just eyeball `context.py`'s
  `_process_received_items` to confirm nothing logs/warns weirdly on ability
  items when abilitysanity is off.

## Tests

1. Unit: with abilitysanity off, precollected state satisfies the deepest
   progressive tokens (`|Progressive Crouch:3|`, `|Progressive Ground
   Pound:3|`, `|Progressive Jump:2|`) and the pool contains zero
   Ability-category items (existing drop assertion stays).
2. Generation probe (real logic, abilitysanity off) — copy the
   SMOAP_LIVE_AP-gated probe pattern from
   `tests/test_entrance_shuffle_option_modes.py`: seed must generate, no
   FillError.
3. Existing suite stays green.

## Verify

pytest (Windows) → `python scripts/install_apworld.py` → `Generate.py` with a
YAML using `no_logic: false`, `abilitysanity: false`, `capturesanity: false`,
`entrance_shuffle: simple`, goal mushroom_kingdom (Devon's Aeide.yaml combo —
the exact shape that failed). A few different seeds, since the failure mode is
fill-probabilistic. No IP concerns; audit `git status` before commit as usual.
