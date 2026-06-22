# Costume doors always unlocked (Devon, 2026-06-22)

**Goal.** In vanilla SMO, the special "costume doors" — the locked doors that lead
to each kingdom's `*WorldCostumeStage` fitting-room subarea — only open while Mario
is **wearing the specific required hat + outfit** (e.g. Sand's door wants the
Explorer cap + Explorer outfit). Devon wants these doors to **always be unlocked**,
regardless of what Mario is wearing.

The motivation is the **entrance / shop shuffle**: the regional outfit a costume
door demands is normally bought at that kingdom's Crazy Cap, but once shop entrances
are shuffled the outfit can become awkward or circular to obtain — and, more sharply,
**under entrance shuffle the destination mapped *behind* a costume door is gated by
that outfit**, so an outfit the shuffle made hard to get can strand a shuffled
destination, not just the fitting-room moon. Always-open doors removes that hazard.

**Status: investigated, NOT started. Estimate ~75% feasible, medium effort.**
This is a **switch-mod-only** change (no apworld rebuild, no re-seed). The
uncertainty is entirely the one undecompiled actor seam; everything around it is
favorable.

---

## Scope: which doors

Seven costume doors, one per kingdom that has a fitting room, all sharing the same
mechanism (from [data/entrance_stages.json](../../apworld/smo_archipelago/data/entrance_stages.json),
keyed `Costume Room (...)`, every entry a `DoorWarpStageChange` unit):

| Kingdom | Subarea stage |
|---|---|
| Sand | `SandWorldCostumeStage` |
| Wooded | `ForestWorldWoodsCostumeStage` |
| Seaside | `SeaWorldCostumeStage` |
| Snow | `SnowWorldCostumeStage` |
| Luncheon | `LavaWorldCostumeStage` |
| Bowser's | `SkyWorldCostumeStage` |
| Mushroom | `PeachWorldCostumeStage` |

**Out of scope: the Sphynx vaults** (`SandWorldSecretStage`, `SeaWorldSecretStage`,
`MoonWorldSphinxRoom`, etc.). Those gate on the Sphynx's coin/quiz interaction, not
on a worn costume, so they are a different mechanism and not what "costume doors"
refers to. If Devon later wants those opened too it's a separate seam.

---

## How it works today (two tiers)

As with every gameplay gate in this project there's an apworld-logic tier and a
switch-mod tier — but here **only one of them is even involved.**

### Tier 1 — apworld logic graph: ALREADY CORRECT, no change needed

The costume-room moons do **not** encode an outfit requirement in
[data/moon_requirements.json](../../apworld/smo_archipelago/data/moon_requirements.json).
e.g. `"Costume Room: Dancing with New Friends"` lists only
`jump_height: long_jump` / `cap_throws: [none]` / `other_required: []` — pure
movement, no "own/wear outfit X" term. Costumes are not AP items, and
[hooks/Rules.py](../../apworld/smo_archipelago/hooks/Rules.py) has no costume/cloth/
outfit vocabulary at all.

So the fill **already treats these moons as reachable without the outfit** (it
implicitly assumes you can buy it in-kingdom). That means:

- The logic layer is *already* consistent with "doors are always open" — making them
  physically always-open just makes the game match what the logic already believes.
- **No regions.json / Rules.py / moon_requirements.json edit is required**, and no
  re-generate / re-seed. This is the single biggest reason the feature is cheap
  relative to most entries in this index.
- (Corollary risk, noted for completeness: today the logic's "buy it in-kingdom"
  assumption can be *violated* by shop shuffle — the very problem this feature
  fixes. So shipping always-open doors removes a latent logic-vs-reality gap rather
  than creating one.)

### Tier 2 — switch-mod in-game gate: the actual work

The fitting-room entrance is a `DoorWarpStageChange` actor. When Mario interacts
with it, the actor checks the **currently-worn** cap + cloth and only then requests
the stage change. The worn-outfit getters are known, resolvable symbols in our
headers ([GameDataFunction.h:371-372](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h)):

```cpp
const char* getCurrentCostumeTypeName(GameDataHolderAccessor accessor);
const char* getCurrentCapTypeName(GameDataHolderAccessor accessor);
```

The door compares those against a per-door required outfit (a placement parameter in
the stage's design BYML) before firing the warp. If they don't match, the warp is
never requested.

**Where this intersects the existing entrance shuffle:** our entrance randomizer
rewrites the *destination* of a stage change inside
`GameDataFile::changeNextStage` ([EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp)).
That hook only fires **after** the door decides to warp. So the costume condition
sits strictly *upstream* of everything we already do — we cannot reach it from the
existing chokepoint, and a locked costume door blocks the shuffled destination
behind it just as it blocks the vanilla fitting room. The fix has to act at the
door's own condition.

---

## What the change requires

### The seam problem (this is the whole risk)

The `DoorWarpStageChange` actor is **not in OdysseyDecomp** — the only decompiled
door actors are `DoorCity` / `DoorSnow` (confirmed via the decomp tree), and both of
those gate on a **stage switch**, not a costume, so they're not the template. The
worn-costume comparison also isn't in any decompiled helper (`ClothUtil.cpp`,
`PlayerUtil.cpp` checked — `ClothUtil` only has *ownership* checks like `isHaveCloth`,
no worn-equality helper). So the exact condition seam must be located with a
`main.nso` sail/objdump pass — the same caveat that holds the Cappy-commentary doc to
70%. That pass is the bulk of the effort and the reason this isn't a slam-dunk.

Per CLAUDE.md's "read the decomp before picking a chokepoint" rule, the condition's
shape must be confirmed before hooking — but the priors here are unusually good (see
next section).

### Recommended approach — hook the shared door condition (one hook fixes all seven)

1. **Find the actor + its condition method** via the symbol-discovery pipeline (the
   `smo-symbol-discovery` skill / sail over `main.nso`). The BYML unit name
   `DoorWarpStageChange` is the strong lead for the class name; the target is its
   "may I warp the player" predicate (an `isEnable…` / `tryWarp…` / condition-check
   method).
2. **Trampoline it to force-true** when the door is a costume door — the same
   "force-suppress a game decision" pattern already used by `CaptureGate`,
   `AbilityGateHook`, and `KingdomOrderGate`. Because all seven doors are the same
   actor class driven by a placement parameter, **a single hook covers all of them.**
3. Gate behind a YAML option (e.g. `costume_doors_always_open`, `DefaultOnToggle`)
   plumbed to the Switch the way the other toggles ride slot_data → wire msg →
   `ApState`, so it's opt-out and matches the shuffle's "off by default unless you
   asked for randomization" ergonomics. (Cheap; can be hardcoded for a first spike.)

**Why the predicate is probably hookable (raises confidence above the bare
"undecompiled actor" floor):** `DoorWarpStageChange` is a *generic, reused* actor —
many ordinary (non-costume) doors instantiate it and read their condition from
placement data. Per CLAUDE.md's inlining note, generic code called from many sites
tends to stay **out-of-line**, exactly the property we want in a hook target. The
condition reads a data-driven placement string, so it's far more likely to be a real
method than a constant-folded inline compare (the trap that bit Side Flip).

### Fallback if the predicate is inlined

If the condition turns out inlined into the actor's nerve/`attackSensor` body with
no clean seam, two fallbacks (in preference order):

- **Byte-patch the specific branch** in that actor body to skip the costume compare
  (a fixed, enumerable patch site — acceptable since the actor is one class).
- **Attack the out-of-line inputs**: hook `getCurrentCostumeTypeName` /
  `getCurrentCapTypeName`. This is the *un*preferred route — those getters also feed
  Mario's model selection and the costume-room moon counters, so a blanket spoof is
  too broad; it would need call-site scoping (e.g. a frame-window armed only while
  standing on a costume-door trigger), which adds fragility.

### Rejected approach — ship modified stage BYMLs

Editing each stage's design BYML to delete the door's costume condition would work
but means shipping modified Nintendo stage assets (IP-sensitive, bulky, per-stage) —
against the project's "never ship Nintendo content" line and its code-hook-over-asset
preference. Don't.

---

## Recommendation / first step (when pursued)

1. **One investigation spike, no behavior change:** run the symbol-discovery pass to
   confirm the `DoorWarpStageChange` class name and locate its warp-condition method;
   install a *logger-only* trampoline and walk up to a costume door in-game (wrong
   outfit) to confirm the predicate fires there and returns false. That binary result
   — "clean out-of-line predicate: yes/no" — gates the whole feature and decides
   between the recommended hook and the byte-patch fallback.
2. If clean: add the force-true trampoline + the YAML toggle, rebuild the subsdk
   (switch-mod only — no apworld rebuild), and verify all seven fitting rooms open
   with a default outfit, including with entrance shuffle ON (door open → shuffled
   destination reached).

**Why ~75%:** the logic tier needs zero work and is *already* consistent with the
goal; it's switch-mod-only with no re-seed; the door set is small, fixed, and shares
one actor class so a single chokepoint fixes everything; and the "force a game
decision true" hook pattern is well-trodden here. The points off are the one genuine
unknown — the condition lives in an **undecompiled** actor, so a `main.nso` pass is
needed to find the seam and there's a residual chance it's inlined (mitigated by the
byte-patch fallback and by the actor being generic/reused, which favors out-of-line
code).

---

Sources consulted (disk-truth reads + decomp this session):
[data/entrance_stages.json](../../apworld/smo_archipelago/data/entrance_stages.json),
[data/moon_requirements.json](../../apworld/smo_archipelago/data/moon_requirements.json),
[hooks/Rules.py](../../apworld/smo_archipelago/hooks/Rules.py),
[EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp),
[GameDataFunction.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h),
[ClothUtil.h](../../switch-mod/lib/OdysseyHeaders/game/Util/ClothUtil.h),
[PlayerCostumeInfo.h](../../switch-mod/lib/OdysseyHeaders/game/Player/PlayerCostumeInfo.h);
OdysseyDecomp tree (no `DoorWarpStageChange`; `DoorCity`/`DoorSnow` are switch-gated;
`ClothUtil.cpp`/`PlayerUtil.cpp` have no worn-costume equality helper).
