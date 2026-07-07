# Plan — Decoupled / chained entrance randomizer (v3)

**Status: P0 spike PASSED (2026-07-06), Phase 1 (data) DONE (2026-07-07), P2
(compound key + option Choice) CODE COMPLETE awaiting in-game walk
(2026-07-08), P3a signed off, P3b–3d IMPLEMENTED (2026-07-07) — next up: 3e
(slot_data/client/Switch wire path), then 3f.**
Results: see the "Phase 1 results" subsection below. This is the execution plan for
[v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md](v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md)
(read that first — it holds the full design rationale, risk analysis, and source
survey). This doc is the session-by-session work order: phases, concrete tasks,
validation gates, and which Claude model to run each phase on.

**Core shift, one line:** today's coupled door→interior bijection
(`_roll_entrance_bijection` + `compile_stage_remaps`) becomes a **random perfect
matching (involution) over ALL ports** — every overworld door-mouth, subarea
entrance, and subarea exit pipe is a node; walking into port P arrives at
`match(P)`; symmetry gives retrace-your-steps for free; subarea exits can chain
into other subareas or foreign overworlds.

**Phase ordering is load-bearing.** P0 is a go/no-go gate. P2 lands *before* P3
deliberately: the compound-key Switch change is a backward-compatible superset
validated against today's known-good coupled shuffle, so when the new matching
lands in P3, any breakage is isolated to the apworld tier.

---

## Phase 0 — Gate spike: cross-kingdom overworld landing (approach A)

**Status: PASS (2026-07-06).** Results: [devon-p0-decoupled-spike-results.md](devon-p0-decoupled-spike-results.md).
Mario lands in a chain-reached kingdom (Cap → Push Block Peril exit → Luncheon shop
door-mouth) in a sane, usable overworld state — no crash, no corruption. Odyssey
absent (expected cosmetic gap, Phase 5 item). Save+quit+reload reverts to the last
*officially-unlocked* kingdom (Cap) rather than preserving the chain-reached one
(Luncheon) — not a failure, but a confirmed real cost that Phase 3a's design doc must
address explicitly (does a chain-reached kingdom need an explicit "current world"
write on arrival, or is "reload drops you back to your last unlocked kingdom" an
accepted rule?). Row 2 (the return edge, shop door → Push Block Peril) was not
exercised this walk — worth a quick confirmation before Phase 2, but not a blocker
for the go/no-go. `kP0DecoupledSpike` has been flipped back off and the spike rows
left in place, commented, pointing at the results doc. **Feasibility revised up from
~65%** — see the feasibility doc's updated estimate.

Hand-author hardcoded remap rows in the Switch mod that point a Cap subarea's
exit pipe at a Luncheon door-mouth, build, and have Devon walk it in-game.
Full work order: [handoff-decoupled-p0-spike.md](handoff-decoupled-p0-spike.md).

- **Deliverable:** one switch-mod build + Devon's in-game walk results recorded in
  `docs/devon-p0-decoupled-spike-results.md`; feasibility doc's ~65% estimate
  updated up or down.
- **Pass:** Mario lands in the chain-reached overworld in a usable state
  (sane `mScenarioNo`, no softlock, save+reload survivable).
- **Fail modes to distinguish:** crash / broken scenario state (feature likely
  dead as approach A → evaluate approach B before abandoning) vs. cosmetic
  weirdness like no parked Odyssey (acceptable, note for the Phase 5 fidelity pass).
- **Model: Sonnet 5.** One hardcoded row pair at an existing, documented seam;
  no new hooks, no decomp reads needed. The handoff pre-specifies the rows.

## Phase 1 — Data: full port enumeration

- Extend `scripts/extract_entrance_stages.py` (run on the machine WITH romfs
  data) to emit **every** `entries[]`/`exits[]` port as a distinct node with a
  stable port id, **plus overworld door-mouth ports** (the overworld side of
  every subarea door). Version the `entrance_stages.json` schema; the current
  `primary_entry`/`primary_exit` shape must stay readable so coupled mode keeps
  working.
- **Split the conflated subareas** — Costume Room (×3) and Sphynx Treasure Vault
  (×2) merge multiple physical doors into one node; a port matching needs one
  node per physical door. (Spike §1b-bis; this stops being deferrable.)
- Generalize `is_round_trippable` to per-port soundness. The Sand→Bowser
  one-way-warp lesson generalizes: **a port missing its key data must drop BOTH
  ends of its edge from the pool, never one** (see the `is_round_trippable`
  docstring in `entrance_logic.py`).
- **Count the worst-case row budget** against `kEntranceRemapMax = 256`
  (`ApState.hpp`) before any Switch code. One rewrite row per port-edge end;
  overworld door-mouths grow the count. Bumping the cap is cheap (fixed BSS,
  ~200 B/slot) but must be a deliberate, counted decision.
- **IP note:** stage + entry-id identifiers are functional (same regime as the
  existing entrance_stages data). No Nintendo strings anywhere in this phase.
- **Model: Sonnet 5.** Mechanical, finicky, test-coverable extraction work.

### Phase 1 results (2026-07-07)

`scripts/extract_entrance_stages.py` was extended (re-run on the machine with
romfs data + `%APPDATA%/SMOArchipelago/data/shine_map.json`, via
`scripts/.extract-venv`) and `data/entrance_stages.json` regenerated. Shape,
back-compat, and findings:

- **Schema v2, additive only.** Root now carries `"_schema_version": 2`
  alongside the existing subarea keys (consumers all do `.get(name)` lookups
  — `entrance_logic.py`, `hooks/World.py`, `client/switch_server.py` — so an
  extra top-level key is safe; verified no caller iterates/counts all keys
  except `import_moon_requirements.py`'s diagnostic `len()` print, cosmetic
  only). `primary_entry`/`primary_exit`/`entries`/`exits` keep their exact old
  fields; coupled-mode (`compile_stage_remaps`, `build_entrance_pool`) is
  untouched and all 41 pre-existing tests still pass unmodified.
- **`port_id` on every entries[]/exits[] item.** Stable id
  `f"{overworld_stage}#{entry_id}"` — see `port_id()`'s docstring in the
  extractor. Reciprocated two-way doors (the common case) naturally collapse
  to ONE port_id shared between their entries[] and exits[] record (SMO
  convention: both placements in a matched door pair reuse one ChangeStageId,
  already relied upon by `pick_primary_exit`'s reciprocation check); a
  one-way pipe gets its own distinct id. Confirmed on the concrete test case
  named in this phase's brief: **Push Block Peril's two exits** — the main
  door (`PushBlockExStageEnt`, reciprocated, shared with `primary_entry`) and
  the pipe (`PushBlockExStageEntDokan`, exit-only) now resolve to two
  different port_ids instead of both falling out of one `cur`-keyed
  `primary_exit`. This is exactly the ambiguity the P0 spike write-up flagged
  as Phase 2's job to fix on the Switch side — Phase 1 supplies the data half.
- **`door_mouths` per subarea** — a dict keyed by port_id, `{stage, entry_id,
  roles: ["entry"|"exit", ...]}`, materializing the overworld-side coordinate
  of every door as a first-class, deduplicated object instead of leaving it
  implicit in entries[]/exits[] list items.
- **Conflated-subarea split (Costume Room ×3, Sphynx Treasure Vault ×2):
  already done** (an earlier P6.5/P7 session split these into per-kingdom
  subarea keys — `test_costume_room_split_into_three` /
  `test_sphynx_vault_split_into_two` already guarded it). Verified each of
  the 5 variants resolves to its own distinct stage + door_mouths under the
  new port model (regression-guarded by
  `test_previously_conflated_subareas_are_one_physical_door_each`); no further
  splitting was needed at the port level. Sphynx Treasure Vault (Seaside) is
  notable as a *non-reciprocated* door — its entry is physically in
  `SeaWorldSphinxQuizZone`, its exit lands in `SeaWorldHomeStage` — so it
  correctly produces 2 distinct door_mouths, not 1.
- **`is_round_trippable` generalized to per-port soundness.** New primitives
  in `entrance_logic.py`: `is_port_sound(port)` (stage + entry_id both
  resolvable) and `is_edge_sound(a, b)` (both ends sound — the "drop both
  ends, never just one" rule from the Sand→Bowser one-way-warp lesson,
  generalized from subarea to port granularity). `is_round_trippable` now
  requires primary_entry AND every listed exit to be individually sound
  (previously only checked primary_entry); behavior-identical against real
  data (all exits are always fully populated from `collect_doors()`) but now
  guards against a future partially-formed port poisoning the pool. Phase 3's
  port-graph builder should call `is_edge_sound` when constructing the full
  matching so an unsound endpoint drops its whole edge, symmetrically.
- **Row-budget sizing decision — the cap will need to grow.** Counted against
  `kEntranceRemapMax = 256` (`switch-mod/src/ap/ApState.hpp`) before any
  Switch code, per this phase's brief:

  | Scope | Raw entries+exits | Distinct door_mouth ports (dedup'd) |
  |---|---|---|
  | Current 119-subarea pool | 331 | 197 |
  | All 134 extracted subareas (pool ceiling) | 390 | 238 |

  Today's coupled model needs ≤2 rows per shuffled *subarea* pair (≤238 for
  119 pairs), which is why 256 was chosen and still holds for Phase 2's
  compound-key work (Phase 2 changes the KEY, not the ROW COUNT). But Phase
  3's full port-level involution — matching every individual entries[]/exits[]
  port, not just one primary pair per subarea — has a worst case of 331
  raw port-halves (390 if the pool ever grows to all 134). **Both exceed 256.**
  Decision for whoever starts Phase 2/3's Switch-side work: bump
  `kEntranceRemapMax` to **512** (headroom over the 390 ceiling, cheap per the
  existing ~200 B/slot note — ~100 KB of fixed BSS, trivial on Switch). This
  is flagged here as the deliberate call the brief asked for; the actual
  `ApState.hpp` edit belongs to Phase 2, not this phase (data-only, no Switch
  code touched).
- **Tests:** 14 new pytest cases in `test_entrance_shuffle.py` cover schema
  version, universal port_id presence, the Push Block Peril two-exit proof,
  reciprocated-door role tagging, the 5 previously-conflated subarea variants,
  the Jaxi Driving override's port_id, `is_port_sound`/`is_edge_sound`
  directly, the generalized `is_round_trippable` exit check, and a sanity
  bound on the pool-scoped port total (250–450) so a future data regression
  that silently re-merges ports is caught immediately. Full suite: 55 passed.

## Phase 2 — Switch: compound-key exit lookup (the `from_parent` work order)

Memory `entrance-from-parent-fix-deferred` is the ready-made checklist. Today
exit rows key on `cur` alone, which is ambiguous once a stage has multiple exit
ports going to different destinations (or nested interiors whose vanilla exit
dest is a parent interior).

- Extend `EntranceRemapSlot` (`ApState.hpp`) with the second match key (the
  exit's `mChangeStageId`/`entry_id`, and/or `from_parent`); update
  `applyEntranceMap` merge keying, `lookupEntranceRemap`'s exit branch,
  `parseEntranceMap` (`ApProtocol.cpp`), the `EntranceMapMsg` passthrough, and
  `compile_stage_remaps` to emit one row per port-edge end.
- **Wire-format shapes are committed contracts** — extend the fixed-buffer
  structs, don't rewrite them. Chunked full-overwrite send (64-row chunks)
  already exists and carries over.
- **Option model (Devon, 2026-07-08), lands in this phase:** `entrance_shuffle`
  converts from Toggle to a three-value Choice — `off` / `simple` (today's
  coupled bijection) / `decoupled` (the P3 port involution; raises at
  generation until P3 ships). YAML back-compat via `alias_true = simple`,
  `alias_false = off` — which is also why the new mode can't be named "true"
  (bare YAML `true` parses as a boolean and must keep meaning simple). Full
  detail in the P2 handoff §3.5.
- **Validate against the CURRENT coupled shuffle before P3:** host C++ tests
  (`switch-mod/tests/`, smo-host-tests skill) + pytest for
  `compile_stage_remaps`, then an in-game regression walk of the existing
  coupled shuffle, plus the new capability proof: a multi-exit stage
  (Push Block Peril's two exit pipes) with its exits mapped to DIFFERENT
  destinations.
- **Model: Opus 4.8.** Scoped work order, but it touches committed wire
  contracts and the frame-thread lookup path; a regression here costs full
  build+deploy+in-game cycles to find.

### Phase 2 status (2026-07-08) — code complete, awaiting Devon's in-game walk

All 5 work-order sections done: `EntranceRemapSlot`/`EntranceRemapEntry` gained
`from_id` (empty = wildcard), `kEntranceRemapMax` 256→512,
`applyEntranceMap`/`lookupEntranceRemap` merge/match on
`(from, from_id, is_exit)` with the documented 3-tier precedence,
`parseEntranceMap` accepts the optional field, `processEntranceRemap` passes
`mChangeStageId` through, `compile_stage_remaps` emits one exit row per
physical exit port (falling back to the old single wildcard row when a
subarea's `exits[]` can't be enumerated), and the `entrance_shuffle`
Toggle→Choice conversion (§3.5) landed with the `is_option_enabled` truthiness
sweep in `hooks/World.py` (2 call sites) replaced by an explicit
`option_simple`/`option_decoupled` check, plus the generation-time raise.

Full detail + test results: [devon-p2-compound-key-results.md](devon-p2-compound-key-results.md).
Host C++ + pytest suites green (56 entrance-shuffle unit tests + 5 new
Choice-option tests, both host and SMOAP_LIVE_AP=1 runs). Not yet done: the
in-game walk (regression + Push Block Peril two-exits capability proof) —
needs a switch-mod build/deploy, tracked for Devon.

## Phase 3 — Apworld: involution matching + general-graph logic (the bulk)

### 3a. Design doc FIRST — kingdom-order reconciliation

**Status: COMPLETE — SIGNED OFF 2026-07-07 —
[design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md).**
Key reframe: the strict order-rule table is already empty (free-detour work),
so the design keeps ALL existing order/economy machinery untouched and models
chains as a second access channel. Decisions: accept reload-eviction (D3);
door-mouth pool excludes Moon/Dark/Darker only — Ruined + Mushroom IN, data
verified (D5); endgame-via-chain permanently out (D6); chains never discount
flight costs (D1). P3b may start.
The deep collision: chained overworld access breaks the Odyssey-flight-order
assumption that the kingdom-order gate, peace gates, moon-pipe gating,
detour-exit gates, and the Cascade Odyssey divert all share. Before any code,
write `docs/design-decoupled-kingdom-order.md` deciding:
- The option already exists after P2: `entrance_shuffle = decoupled` (the
  three-value Choice, see Phase 2). This doc decides what the mode IMPLIES:
  order gate relaxed or disabled? What happens to `randomize_kingdom_gates`
  totals, `kingdom_gates` wire msg, `UnlockShineNumHook` costs?
- How peace/scenario state composes for a chain-reached kingdom (P0's findings
  feed directly in here).
- What the detour gates and `processCascadeOdysseyDivert` do under this mode.
- **Devon signs off on this doc before 3b starts.**

### 3b. Port-graph data model (`entrance_logic.py`)
Ports, undirected edges, **per-direction access rules**: forward = door-side
gate (`SUBAREA_ENTRANCE_GATES` + kingdom gates + moon-pipe peace/reach — i.e.
what `make_door_access_rule` composes today); reverse = interior requirements
to physically reach that exit pipe (`SUBAREA_EXIT_GATES` generalizes from a
per-subarea escape gate to a per-port reverse cost).

**Status: IMPLEMENTED (2026-07-07) — `apworld/smo_archipelago/port_graph.py`
+ `tests/test_port_graph.py` (pytest run on Windows pending).** Model notes
(full rationale in the module docstring):

- **Nodes are door MOUTHS** (each P1 `port_id` door = overworld mouth +
  interior mouth; vanilla = the identity involution pairing each door's two
  mouths). Pool = **ingest-capable** mouths only (walkable from their own
  side, derived from `entries[]`/`exits[]`); emit-only mouths (e.g. PBP's
  pipe overworld end) become unused markers — path symmetry holds by
  construction for every matched pair.
- **D5 exclusions propagate door-wise** (design-doc erratum, recorded there):
  Moon/Dark/Darker subareas drop entirely (their only doors hang off excluded
  overworlds), else the player would see asymmetric doors. Festival adds the
  post-Metro set + Mushroom (cross-checked against `FESTIVAL_REGIONS_TO_EMPTY`
  by test).
- **Per-mouth cost** (`mouth_cost`): overworld = door gate + kingdom gate +
  moon-pipe reach/peace; interior = `SUBAREA_EXIT_GATES` +
  `PORT_EXIT_GATE_OVERRIDES` (empty, authored later). Door-side SCENARIO
  fragments stay a 3d wiring concern (need multiworld context).
- **Two flagged follow-ups:** (a) P3e must verify the Switch ENTRY lookup
  branch consults `from_id` (P2 added the field everywhere but only wired the
  EXIT branch) — needed once multi-door subareas diverge; (b) emission-marker
  validity for NON-reciprocated exit ids (spawning inside a stage at an
  exit-only marker) is P0-proven only for reciprocated ids — P4 walk item,
  with "fall back to default spawn" as the expected failure shape. Also note
  nested subareas: an "overworld" mouth may live in a parent INTERIOR stage —
  region attachment in 3d must use the mouth's stage, not assume a kingdom
  HomeStage.

### 3c. Connectivity-guaranteed random involution
A naïve random matching can strand closed loops. Frontier-growing construction
(each edge placement keeps the reachable-port frontier able to grow) or random
match + repair pass; seeded from `world.random`. Heavy unit tests: adversarial
seeds, no dead pockets, one-way strand shapes (mini-rocket interiors),
determinism per seed, row-count ceiling.

**Step 0 baseline (2026-07-07, recorded before any P3c code).** Devon's
"151 failed / 813 passed / 84 skipped" run was on the bare Python 3.13
interpreter (`C:\Users\devon\AppData\Local\Programs\Python\Python313`), which
has pytest but NONE of the dev deps — in particular no `pytest-asyncio`, so
all 140 `@pytest.mark.asyncio` tests fail "async functions not natively
supported". Not regressions. The canonical interpreter is the repo venv
(`e:\smo_archipelago\.venv`, Python 3.12.10, pytest 9.0.3 — what `python`
resolves to in a fresh shell). On the venv the suite is **964 passed /
84 skipped / 0 failed** (33s) — fully green, no P2/P3b regressions — but ONLY
with `--basetemp` redirected: two directories have broken ACLs (created
2026-07-07 ~11:58 by the sandboxed Cowork run; even `icacls`/`takeown` are
denied without elevation):

- `C:\Users\devon\AppData\Local\Temp\pytest-of-devon` — pytest's `tmp_path`
  root; while it exists, every `tmp_path`-using test (236 of them) ERRORS
  with `PermissionError`. Workaround: `pytest --basetemp=<fresh dir>`.
- `E:\smo_archipelago\apworld\smo_archipelago\tests\.pytest_cache\v\cache` —
  harmless (cache-write warnings only).

**Devon action:** delete both from an elevated prompt; then plain `pytest`
works again.

**Status: IMPLEMENTED (2026-07-07) — `apworld/smo_archipelago/port_matching.py`
+ `tests/test_port_matching.py` (19 tests; full suite 983 passed / 84 skipped).**
`roll_port_matching(graph, rng) -> dict[str, str]`: frontier-growing phase 1
(every pairing lands one new stage on the root-connected frontier; provably
terminating), uniform phase 2, loud RuntimeError postconditions (involution,
connectivity, row budget) so a bad roll can never escape into fill. Checker is
`unconnected_stages(matching, graph)`; roots via `root_stages`. Deterministic
in the caller's `rng` (sorted candidate lists before every `rng.choice`).
Real-pool stats (100 seeds): standard 289 mouths / 125 stages (22 roots),
282–288 rewrite rows vs the 480 budget (`kEntranceRemapMax` 512 − 32
headroom); festival 166 mouths / 68 stages, ≤166 rows. Pool 289 is odd ⇒
exactly one fixed point per roll, always a lone (vanilla self-mapped) mouth
⇒ zero-row vanilla passthrough.

Three real-data discoveries (load-bearing for 3d/3e — the naive model in this
section's original sketch was wrong about all three):

1. **One-way-ENTRY subareas must stay vanilla — P3b pool rule added
   (`port_graph.py`).** The 6 Mushroom boss re-fight painting arenas have
   `exits: []` (scripted return); re-matching a painting would orphan the
   arena and its re-fight Multi-Moon. `build_port_graph` now drops ALL doors
   of any subarea that would contribute pooled mouths but zero interior
   ingest mouths (mirror image of the emit-only-pipe case; docstring
   erratum). Blast radius verified = exactly those 6 subareas.
2. **Roots are NOT just `*HomeStage`.** Overworld door mouths also live in
   placement zones of the kingdom map (`SkyWorldCastleZone`,
   `LakeWorldTownZone`, `SeaWorldLava/Lighthouse/SphinxQuiz/WallCaveWestZone`,
   `ForestWorldWoodsStage` = Deep Woods, `SnowWorldTownStage`) — no suffix
   convention holds ('…Zone' and '…Stage' both occur, and `LavaBonus1Zone` is
   Luncheon Slots' INTERIOR). Rule shipped: root = any stage hosting a pooled
   overworld mouth that is not itself a pooled interior stage (+ HomeStages
   unconditionally). Self-consistent for vanilla-kept parent interiors too.
3. **Zone-split doors: one physical door can be TWO lone one-way mouths with
   different port_ids** (`LakeWorldTownZone#CapTrampolineA` overworld half vs
   `LakeWorldHomeStage#CapTrampolineA` interior half — the door actor sits in
   the zone, the interior exit records the parent stage). Both are
   independently matchable and sound. Consequence for the checker: a lone
   OVERWORLD mouth left vanilla-fixed still walks INTO its subarea, credited
   as a directed entry edge — without that credit vanilla itself reads
   "stranded" for those subareas. ⚠ 3e note: these halves produce entry-side
   and exit-side rows whose stage keys are the ZONE name on one side and the
   HomeStage on the other — verify the Switch-side lookup keys against
   `getCurrentStageName` semantics for zones (does a zone-hosted door report
   the zone or the parent stage as `cur`?) before compiling rows.

### 3d. Region graph rebuild (`hooks/World.py::_wire_entrance_shuffle`)
Star → general graph, both direction rules attached per edge, scenario gates
still riding member locations (`_apply_subarea_scenario_gates` pattern).
⚠ Remember the Manual-derived engine quirk: a region's `requires` gates its
**outgoing** entrances ([handoff-region-gating-egress.md](handoff-region-gating-egress.md)).

**Status: IMPLEMENTED (2026-07-07) — `hooks/World.py`
(`_prepare_decoupled_entrance_shuffle` / `_wire_decoupled_entrances` /
`after_set_rules` decoupled branch), `port_graph.make_mouth_access_rule`,
`tests/test_decoupled_region_wiring.py` (7 SMOAP_LIVE_AP probes in the
test_cascade_reachability style) + a readiness-flag source guard in
test_entrance_shuffle.py. Suite: 984 passed / 91 skipped (the 983/84 baseline
held exactly — the +1/+7 are the new tests); live: all 7 new probes green
plus the cascade-reachability and option-modes files re-run green against the
reinstalled zip. A one-off `distribute_items_restrictive` probe also passed
(below).** The mode stays player-BLOCKED: the P2 OptionError now short-circuits
on a module flag `PORT_SHUFFLE_SHIPPABLE = False` (hooks/World.py) that tests
flip to exercise the wiring; flipping it for real is P3e's last step.

How the wiring resolves the egress-quirk × two-channel collision (the load-
bearing design decision of this phase):

- **Synthetic "{K} Arrival" region per kingdom hosting pooled overworld
  mouths** (14 standard / 8 festival). Region-reachability of a kingdom is
  one-kingdom-early under the Manual engine (its `requires` gates EGRESS);
  simple mode compensates by keeping the clobbered regionCheck ANDed onto
  every door, but under decoupled that would demand *flight* arrival for
  *chain* traversal through K — defeating the mode. Instead: `K -> K Arrival`
  is deliberately left rule-less at wiring time so the Manual core set_rules
  clobber OVERWRITES it with K's own fullRegionCheck — the honest
  flight-arrival predicate, applied by the engine itself. Every matched edge
  targeting an overworld mouth in K lands in `K Arrival` (the chain channel —
  ingress-authored rules, no off-by-one), every overworld-mouth edge SOURCES
  from `K Arrival`, and a free `K Arrival -> K` presence edge hands the
  kingdom region (its overworld locations) to whichever channel arrived
  first. Flight edges between kingdoms are untouched and asserted
  clobber-owned by the tests (D1: chains never discount flight costs).
- **Every port entrance is sourced from a region set_rules has never heard
  of** (interior / Arrival regions aren't in regions.json), so rules are set
  once at wiring time and survive — no simple-style after_set_rules door pass
  exists in this mode. after_set_rules runs only the two location helpers
  (interior-requires replacement + D3 scenario-gate re-apply), shared with
  simple.
- **Per-direction rules:** `make_mouth_access_rule` (port_graph.py) = mouth
  cost (item/peace via evaluate_full_requires + peace fn) + door-side
  scenario fragments for OVERWORLD mouths only (OR over the door subarea's
  members, same composition as simple). The interior exit gate rides the
  interior mouth's own outgoing edge ONLY — never re-ANDed onto the partner
  door the way simple's make_door_access_rule does (the handoff's
  double-application trap).
- **Fixed points wire NO entrance** (vanilla passthrough) except the
  lone-overworld credit shape, which gets its vanilla directed
  `region(ow) -> subarea Interior` edge (P3c discovery 3's zone-split
  subareas would otherwise logic-strand when a roll fixes their overworld
  half).
- **Mouth → region resolution is side+stage** with a loud RuntimeError if two
  pooled subareas ever claim one interior stage (P1 data guarantees
  uniqueness today), and a nested-door branch (overworld mouth in a pooled
  parent's interior stage → parent's interior region).

Real-data findings (probe-verified 2026-07-07, load-bearing for 3e):

1. **All 14 mouth kingdoms map 1:1 to regions.json region names** (incl.
   Cloud + Mushroom; no "Night Metro" complication — metro subarea records
   all say "Metro Kingdom"). No name-translation layer needed anywhere.
2. **Zero nested doors and zero interior-stage collisions in current data** —
   every pooled overworld mouth lives in a HomeStage or one of the 8 known
   placement-zone stages. The nested-door branch and the collision
   RuntimeError are future-proofing for re-extractions, not live paths.
3. **Decoupled seeds FILL today**: a one-off `distribute_items_restrictive`
   probe over seeds 1/11/22 (capturesanity + abilitysanity +
   randomize_kingdom_gates + multi_moon_shuffle) placed every item, 0
   unfilled locations, no FillError — the general graph does not reproduce
   the full+shuffle "No more spots" tightness, and 3f's Mushroom promotion is
   not load-bearing for fill health.
4. **Deliberately absent until 3e:** `world._entrance_map` is never set under
   decoupled, so no `entrance_map` slot_data key ships (wrong-mode data) and
   the spoiler-log entrance block is silent for decoupled seeds — 3e's new
   slot_data key should bring a port-matching spoiler block with it.

### 3e. slot_data + client plumbing
Ship the port matching under a NEW slot_data key (keep `entrance_map` for
coupled mode back-compat); generalize the client's `compile_stage_remaps`
call path (`switch_server.py` / `push_entrance_map`).

### 3f. Mushroom check promotion (design D9)
`_apply_junk_only_rules` exempts Mushroom-category locations iff decoupled;
Devon re-runs `compile_moon_logic.py` (romfs machine, shine_map present) to
fill the 43 Mushroom `requires` from the xlsx-derived requirements data.
In-game moon-spawn probe rides P4; scenario-floor contingency (PeachWorld
arrival, `capArrivalScenarioOverride` pattern) only if the probe fails.

- **Model: Fable 5 for 3a–3d** (highest-interlock design + algorithm work in
  the repo; a subtle one-way logic bug is the top failure mode). Opus 4.8 is
  the budget fallback. **Sonnet 5 for 3e** (follows existing `entrance_map` /
  `mm_bonus_*` patterns).

## Phase 4 — Validation

- pytest additions → `python scripts/install_apworld.py` → `Generate.py`
  (BOTH on Windows — the regen-loop and stale-shell rules in CLAUDE.md apply).
- Row-count assertion vs table cap at generate time.
- Devon's in-game walk matrix: chains of 2–3 subareas, forward + full retrace,
  save/load mid-chain, moon pipes, multi-exit stages, a chain-reached overworld
  each for an early and a late kingdom. Reuse the `kEntranceRemapApply=false`
  preview mode for a log-only dry run before the applied walk.
- **Model: Sonnet 5** for test writing; Devon in-game.

## Phase 5 (optional) — Approach B: literal Odyssey-arrival landings

Route overworld landings through the `tryChangeNextStageWithDemoWorldWarp` seam
so the kingdom loads via the engine's own arrival code (Odyssey parked, correct
scenario). Only if approach A's landing feel isn't good enough after Phase 4.
- **Model: Opus 4.8.** Hooks adjacent to the KingdomOrderGate BACKSTOP; needs
  decomp reads (READ THE DECOMP BEFORE PICKING A CHOKEPOINT).

---

## Model assignment summary

| Phase | Model | Rationale |
|---|---|---|
| P0 spike | Sonnet 5 | Pre-specified rows at a documented seam; no new hooks |
| P1 port enumeration | Sonnet 5 | Mechanical extraction, test-coverable |
| P2 compound key | Opus 4.8 | Committed wire contracts + frame-thread lookup; regressions are expensive |
| P3a design doc | Fable 5 | Highest-interlock design decision in the repo |
| P3b–3d matching + graph | Fable 5 (Opus 4.8 fallback) | Real algorithm design + Manual-engine quirks |
| P3e slot_data/client | Sonnet 5 | Pattern-following plumbing |
| P4 tests | Sonnet 5 | Pattern-following against the existing suite |
| P5 approach B | Opus 4.8 | New hook near the order-gate BACKSTOP; decomp reads |

## Standing reminders for every session on this feature

- CLAUDE.md's dev-environment rules apply in full: **disk-truth via
  Read/Write/Edit/Grep tools only** (the Linux shell serves stale/truncated
  files), builds + Generate on Windows, `install_apworld.py` after every
  apworld source change before Generate.
- Switch-mod changes need the full build_switchmod.py → Ryujinx deploy loop
  (CLAUDE.md has the canonical PowerShell block; QUOTE the `-DBRIDGE_HOST` arg).
- Never commit Nintendo IP; everything in this plan is functional identifiers.
- Keep this doc updated at the end of each session (status per phase), the way
  plan-p4-detail.md is maintained.
