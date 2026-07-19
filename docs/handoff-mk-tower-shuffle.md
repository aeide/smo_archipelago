# Handoff: pool the 6 Mushroom Kingdom boss-refight towers into the entrance shuffle

> **✅ RESOLVED 2026-07-18 — implemented, apworld-only, needs `install_apworld.py` + RESEED (no switch-mod rebuild).**
>
> **Ground truth corrected two ways by romfs verification** (probe scripts in the
> session scratchpad; re-derivable from `.romfs-cache/StageData`):
> 1. **The towers ARE real standalone stages** (`PeachWorldPictureBoss{Knuckle,Forest,Magma}Stage`,
>    `PeachWorldPictureMofumofuStage`, `PeachWorldPictureGiantWanderBossStage`,
>    `PeachWorldPictureBossRaidStage`) — two-way MK doors (`ChangeStageArea` pairs
>    `BossKnuckleA`/`BossForestA`/`MofumofuA`/`BossMagmaA`; `DokanStageChange` pipe pairs
>    `GiantWanderBossA/B`, `BossRaidA/B`), `PlayerStartObj` + painting in all 15 scenario
>    slots, WorldList members of world 14. The `port_graph.ZONE_STAGE_ALIAS` entries
>    calling them zones were WRONG and are removed (erratum note at the constant).
> 2. **The vanilla post-boss return target is the TOWER ROOM**, not MK overworld and not
>    the door origin: the Multi-Moon's own `ShineGrand` actor (and the arena's
>    `MissRestartArea`) carries `ChangeStageName=PeachWorldPicture*Stage,
>    ChangeStageId=PictureBoss*`. The (a)/(b) question below dissolved — Devon chose
>    (AskUserQuestion, 2026-07-18): **pool the TOWERS as ordinary two-way subareas**; the
>    painting → `RevengeBoss*Stage` arena → MM-return-to-tower loop stays fully vanilla;
>    leaving the tower follows the shuffle like any pooled subarea. MK-side tower mouths
>    join the pool as extra (non-root) MK-overworld portal landings — consistent with D10.
>
> **Implementation (all landed):** the 6 `entrance_stages.json` "… Boss Re-fight" records
> re-pointed at the tower stages (extractor parity via
> `extract_entrance_stages.py::SUBAREA_STAGE_OVERRIDE` + a tower-scoped
> `PictureStageChange` exit filter so the painting can never pool);
> `ZONE_STAGE_ALIAS` tower entries removed; `entrance_logic.compile_stage_remaps` now
> emits **per-port `from_id` entry rows** (the Switch's compound entry tier already
> matched them — this is what keeps the id-`PictureBoss*` MM return un-hijacked in simple
> mode; decoupled rows always carried `from_id`). No switch-mod change: `lookupEntranceRemap`'s
> entry tier already prefers `(dest, from_id)` exact matches and decoupled emits no
> wildcards. Rematch checks' interior requires resolve to the boss capture
> (`|Knucklotec's Fist|`, `|Uproot|`, `|Sherm|`, `|Gushen|`, `|Lava Bubble|`,
> `|Progressive Ground Pound:1|`) keyed on shuffled tower access; the directed roller
> certifies every tower's full interior each roll (~302 rows, budget 480; 200-seed
> strand-free). Guard tests: `test_port_matching.py::test_refight_towers_pooled_arena_loop_vanilla`
> / `::test_refight_towers_drop_under_festival` / `::test_zone_alias_never_covers_a_pooled_interior_stage`,
> `test_entrance_shuffle.py::test_refight_records_point_at_towers_not_arenas` /
> `::test_refight_tower_rows_never_touch_the_arena_loop`. Festival: Mushroom is
> festival-excluded → feature inert there (locations don't exist either).
> Old seeds keep working (matching lacks tower mouths → towers stay vanilla).
> Devon's in-game list: bottom of this file.

**Recommended model: Opus 4.8.** Cross-tier feature (apworld pool/data + logic re-keying
+ switch-mod remap rows + slot_data) following an established pattern (the existing
subarea pool), but with two genuinely novel wrinkles — nested boss stages behind the
towers and the post-boss return path — that need decomp verification, not guessing.
Fable if a session's worth of budget allows; Sonnet would likely mishandle the nesting.

## Goal (Devon, 2026-07-17)

The 6 boss refights live behind towers in the MK overworld. Vanilla flow:
**MK overworld → tower interior (loading zone) → painting → boss fight (loading zone)**.
Wanted: the TOWERS join the entrance-shuffle pool so any shuffled door can lead into a
tower interior. The painting warp stays VANILLA — whichever tower you land in, the
painting ahead of you leads to that tower's boss. (Refight MM checks:
"Mushroom: Tussle in Tostarena: Rematch" etc. — the 6 Mushroom-side entries of the
21-MM multi_moon set, see [handoff-refight-multi-moons.md](handoff-refight-multi-moons.md).)

## Why this matters beyond flavor

In the evidence seed
([logs/decoupled-seed-91455467025183402260-mushroom-evidence.md](logs/decoupled-seed-91455467025183402260-mushroom-evidence.md))
MK overworld had no in-game route, so all 6 refight checks were dead. Pooled towers make
the refights reachable WITHOUT MK overworld access — and possibly make MK overworld
itself reachable via the post-boss return (see Open design decision). Coordinate with
[handoff-decoupled-mushroom-overworld-reachability.md](handoff-decoupled-mushroom-overworld-reachability.md).

## Implementation shape

1. **Discover the functional identifiers** (tower interior stage names, their MK-side
   door markers on the PeachWorld home stage, the painting's ChangeStageInfo dest =
   boss stage, and the boss stage's post-victory return target). Sources: the
   entrance-stages data the pool already uses (`entrance_logic.load_entrance_stages`,
   `data/subareas.json` build pipeline), Devon's extracted data in
   `%APPDATA%/SMOArchipelago/data/`, OdysseyDecomp/lunakit for stage naming. Do NOT
   guess stage names; do NOT bulk-paste content beyond functional IDs (IP rule).
2. **apworld**: add the 6 towers to the shuffle pool (subareas.json entry or a new
   tower class in `entrance_logic.build_entrance_pool` — match however exclusions
   are modeled). Attribute each boss stage's MM location to its tower for
   `build_interior_requires_map`, so the check's logic keys on the shuffled door
   origin (nested stage = the novel part; plain subareas are one stage deep).
3. **switch-mod** (`EntranceShuffleHook.cpp`): entry rows keyed on dest should handle
   tower interiors generically — verify. Add NO rows for the painting's dest (keeps
   the warp vanilla). Decide + implement the post-boss return (below). Slot_data
   already carries the bijection; growing it is apworld-side.
4. **Vanilla MK-side tower doors**: with the towers' interiors claimed by the
   shuffle, the MK overworld doors to them become shuffled doors like any other
   (they lead elsewhere). Fine — but confirm the pool round-trip filter
   (`load_entrance_stages` restriction) accepts them.

> **Coordination update 2026-07-17 (sibling handoff resolved):** Devon chose
> **exit-portals** as the guaranteed MK-overworld route (design doc §D10), so
> this feature no longer carries the burden of providing MK arrival — the
> post-boss-return decision below is now purely about THIS feature's own
> semantics (option (b), pop-to-origin-consistency, no longer conflicts with
> the sibling handoff's needs). Note also `port_matching.NON_ROOT_KINGDOMS`:
> if tower pooling ever adds MK-hosted door mouths, they are automatically
> non-root and the directed roller will demand a real route to them.

## Open design decision — post-boss return (AskUserQuestion with Devon)

After beating a refight boss, vanilla returns Mario to… (verify: tower? MK
overworld?). P7 leaves boss/cutscene warps untouched, so today the return would be
vanilla. Options:
- **(a) Vanilla return lands MK overworld** → this chain becomes the organic MK
  arrival route the sibling handoff needs. Leak-by-design; logic must then model
  door→tower→boss→MK-overworld.
- **(b) Return pops to the tower's shuffled door origin** (consistent with every
  other pooled subarea) → no MK arrival; the sibling handoff needs another route.
Verify the vanilla behavior FIRST (decomp/stage data, or a cheap instrumented log),
then put the choice to Devon — it decides both handoffs' logic models.

## Risks / guardrails

- **CapAppear-class lesson**: an untested stage class as a shuffle destination
  produced a no-Mario softlock
  ([handoff-entrance-subarea-no-mario.md](handoff-entrance-subarea-no-mario.md)).
  Before shipping, desk-verify tower entry markers/scenario validity the same way
  that handoff prescribes (decomp read, start-point diagnostics), and give Devon an
  explicit in-game test list covering all 6 towers, both directions, plus one full
  boss round-trip.
- Refight MM side-grants (`mm_bonus_captures` 3-per-MM) ride these checks — the
  grant path is item-name-keyed, so shuffling ACCESS shouldn't touch it; confirm
  no assumption about Mushroom reachability lurks in the bonus-grant tests.
- Festival goal drops the 6 MK refight MMs from the pool — tower pooling must
  degrade cleanly under festival (towers may still be pooled as moonless subareas
  or be excluded; pick the simpler invariant and test it).
- No new locations → no `sync_shine_table` churn expected; flag if that turns out
  wrong. Tiers touched: apworld (install_apworld + re-seed) AND switch-mod
  (build_switchmod + Ryujinx deploy) — both loops, per CLAUDE.md.
- File work via Read/Grep/Edit only (stale shell mount); pytest via repo `.venv`.

## Acceptance

- Decoupled + coupled seeds generate with towers in the pool; refight checks'
  spheres reflect shuffled tower access, not MK overworld access.
- In-game (Devon): a shuffled door leads into a tower; painting shows/leads to that
  tower's vanilla boss; boss completes; return behaves per the decided option;
  the MM check sends and its bonus captures grant.
- Guard/regression tests: pool contains the 6 towers, boss MM locations key on the
  tower's shuffled origin, festival degradation pinned.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (stale shell mount, both build loops,
> decomp-before-chokepoint invariant, IP rules), then docs/handoff-mk-tower-shuffle.md,
> docs/handoff-refight-multi-moons.md, and the entrance-pool code
> (hooks/World.py + entrance_logic.py + EntranceShuffleHook.cpp). Step 1: discover
> the tower/boss stage identifiers and the vanilla post-boss return target from
> data + decomp — no guessing. Step 2: AskUserQuestion to settle the post-boss
> return design with Devon (it also decides the Mushroom-arrival route in
> docs/handoff-decoupled-mushroom-overworld-reachability.md — coordinate). Step 3:
> implement per the handoff's shape with the CapAppear softlock lesson applied
> (verify entry markers before shipping), add the guard tests, and hand Devon the
> two-tier rebuild + in-game test list (all 6 towers, one full boss round-trip).

---

## Devon's deploy + in-game verification (2026-07-18 build)

Deploy is **apworld-only**: `python scripts/install_apworld.py` then regenerate a
fresh decoupled seed (old seeds stay valid but keep the towers vanilla — the new
pool members only enter a NEW roll). **No switch-mod rebuild, no `sync_shine_table`.**

In-game checklist (fresh decoupled seed, spoiler in hand):

1. **All 6 towers as destinations** (`[entrance:remap-APPLIED]` with
   `to_stage=PeachWorldPicture*Stage`): walk each shuffled mouth the spoiler says
   leads to a tower; confirm Mario spawns INSIDE the tower room at the door/pipe
   marker (ids `BossKnuckleA`, `BossForestA`, `MofumofuA`, `BossMagmaA`,
   `GiantWanderBossA/B`, `BossRaidA/B`) — Mario + geometry present, no
   no-Mario softlock, no MK-overworld skybox glitch (the old zone-alias failure
   signature `[p5-reswatch] resident=… engineCurWorld=…` mismatch with missing
   graphics preset would indicate a regression).
2. **One full boss round-trip** (per tower ideally; minimum one): from a shuffled
   arrival inside a tower, jump into the painting (must load `RevengeBoss*Stage`
   vanilla — NO `[entrance:remap-APPLIED]` line for the painting commit), beat the
   boss, collect the Multi-Moon. Confirm: the check sends, the 3 bonus captures
   grant (Cappy bubble), and the post-MM warp returns you INTO THE SAME TOWER
   (again no remap-APPLIED on that commit — dest `PeachWorldPicture*Stage`
   id `PictureBoss*` must stay vanilla).
3. **Tower exit portal**: walk out the tower's door/pipe — it should portal to the
   matched partner (remap-APPLIED with `cur=PeachWorldPicture*Stage`), and walking
   back re-enters the tower (two-way).
4. **MK-side tower mouth as a landing**: if the spoiler routes any portal to a
   `PeachWorldHomeStage#Boss*`/`#GiantWanderBoss*`/`#MofumofuA` mouth, walk it —
   Mario should land in MK overworld beside that tower (this doubles as the still-owed
   D9 pre-credits `PeachWorldHomeStage` portal probe: check moons spawn + Odyssey
   normalization on that arrival).
5. **Death-in-arena**: die (or fall out) during one refight — the MissRestartArea /
   miss path must also stay vanilla (respawn in arena or return to the tower, no
   warp to a foreign kingdom).
