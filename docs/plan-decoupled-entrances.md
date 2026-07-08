# Plan — Decoupled / chained entrance randomizer (v3)

**Status: P0 spike PASSED (2026-07-06), Phase 1 (data) DONE (2026-07-07), P2
(compound key + option Choice) CODE COMPLETE awaiting in-game walk
(2026-07-08), P3a signed off, P3b–3e IMPLEMENTED (2026-07-08), 3f
(Mushroom promotion) IMPLEMENTED (2026-07-08) — all still gated behind
`PORT_SHUFFLE_SHIPPABLE=False` pending Devon's zone preview-walk.**
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

**Work order written (2026-07-07):
[handoff-decoupled-p3e-slot-data.md](handoff-decoupled-p3e-slot-data.md)** —
row compiler (`compile_port_remaps`, one row per vanilla-deviating mouth,
reusing the existing `entrance_map` WIRE msg with a new `port_matching`
slot_data key), client mirror/push generalization, the Switch ENTRY-branch
`from_id` extension (P2 seam), the §3c zone-split stage-key verification,
decoupled spoiler block, and the Devon-gated PORT_SHUFFLE_SHIPPABLE flip as
the last step.

**Status: IMPLEMENTED (2026-07-08) — `port_graph.compile_port_remaps`,
`hooks/World.py` slot_data/spoiler wiring, `client/state.py` +
`client/switch_server.py` + `client/context.py` mode-generic push path,
`ApState.cpp` entry-tier `from_id`, host + pytest + SMOAP_LIVE_AP suites all
green. `PORT_SHUFFLE_SHIPPABLE` deliberately left `False` — Devon's call, see
"Not done" below.** Full non-live suite **999 passed / 94 skipped** (the
984/91 P3d baseline +15 new non-live tests +3 new live-gated tests, zero
regressions); live re-run of `test_entrance_shuffle_option_modes.py`,
`test_decoupled_region_wiring.py`, `test_cascade_reachability.py`,
`test_rearrival_reachability.py`, and the new
`test_p3e_port_matching_wire.py` all green against the reinstalled zip.

1. **Row compiler (`port_graph.compile_port_remaps`).** One row per mouth in
   `matching` whose assignment deviates from `graph.vanilla_matching` —
   `len(rows) == estimate_remap_rows(...)` always (test-asserted, incl. a
   100-seed-style real-pool round trip). An INTERIOR mouth emits a `kind:
   "exit"` row keyed on its own `(stage, entry_id)`; an OVERWORLD mouth emits
   a `kind: "entry"` row keyed on `(subarea's own interior stage, entry_id)`
   — the "from" here is deliberately the mouth's OWN subarea's interior
   stage (the vanilla dest walking through that door unmodified), resolved
   via any ingest INTERIOR mouth of the same subarea (guaranteed to exist by
   the P3b one-way-ENTRY pool rule), NOT the door's own per-mouth `.stage`
   field. `to_stage`/`to_id` come straight from the matched target mouth's
   own fields regardless of its side — the mouth model's walk-in-either-end
   symmetry. A mouth id absent from the local graph (client/server
   `entrance_stages.json` drift) drops BOTH ends of that pair, logged loudly,
   never a one-sided row. `ROW_TABLE_CAP`/`ROW_HEADROOM` moved from
   `port_matching.py` into `port_graph.py` (compile_port_remaps needs them
   too, and port_matching already imports FROM port_graph — defining them
   there and importing back would deadlock the module load); port_matching.py
   re-exports both names unchanged so existing imports don't break.
2. **slot_data + client plumbing.** `before_fill_slot_data` ships
   `slot_data["port_matching"] = world._port_matching` (verbatim
   `{mouth_id: mouth_id}`) whenever set — mutually exclusive with
   `entrance_map` by construction (the two `before_create_regions` branches
   never both set their world attribute). `client/state.py` gained a twin
   mirror (`port_matching` / `_port_matching_configured` / three accessor
   methods, same shape as `entrance_map`'s). `SwitchServer.push_entrance_map`
   now picks a compiler based on whichever mirror is configured
   (`is_entrance_map_configured()` first, `is_port_matching_configured()`
   second, no-op if neither) and ships the SAME chunked `entrance_map` wire
   message either way — the Switch never needs to know which mode produced a
   table. The decoupled compiler path (`_compile_decoupled_rows`) rebuilds a
   `PortGraph` from the client's own bundled `entrance_stages.json`/
   `subareas.json` via `build_port_graph(..., festival=False)` — deliberately
   ALWAYS non-festival, since festival only ever *removes* mouths from the
   pool (never renames/adds), so the non-festival graph is a strict superset
   that resolves every mouth id a festival-rolled matching could ship,
   without threading the `goal` option through the client for a distinction
   that can't change resolvability. `context.py`'s Connected handler reads
   `slot_data["port_matching"]` alongside `entrance_map` and calls
   `switch.set_port_matching(...)` before the single shared
   `push_entrance_map()` call.
3. **Switch ENTRY branch now consults `from_id`.** `ApState::lookupEntranceRemap`
   gained a 4th tier (entry-exact `(dest, id)` → entry-wildcard → exit-exact
   `(cur, id)` → exit-wildcard), mirroring the P2 exit tiers exactly.
   `EntranceRemapEntry`/`applyEntranceMap`'s merge key and `ApProtocol.cpp`'s
   parser needed ZERO changes — P2 already made `from_id` a fully generic
   field on every row regardless of `kind`, and the merge key was already
   `(from, from_id, is_exit)`; only the read-side lookup tiers were missing
   the entry-side id check. Coupled-mode entry rows keep shipping an empty
   `from_id` and hit the wildcard tier unchanged (verified: the existing
   coupled-shuffle live walk pattern is untouched). Host-tested
   (`test_protocol.cpp`, 2 new cases: entry row with `from_id` present, two
   entry rows sharing `from` with different `from_id` — the exact port-matching
   disambiguation shape) since `ApState.cpp` itself has no host test (P2's
   documented gap — Switch-only headers, in-game walk is the verification
   path for the table/lookup logic specifically).
4. **Zone-split stage-key verification — PARTIALLY SETTLED, needs Devon's
   confirmation before shipping for real.** Re-read
   `CostumeDoorHook.cpp`'s header (confirmed from a main.nso symbol dump,
   2026-06-24): the Lake town-zone trampoline door is a `DoorWarp`
   **SAME-STAGE** door — i.e. no real `changeNextStage` fires for it at all,
   which is strong evidence `LakeWorldTownZone` and its parent
   `LakeWorldHomeStage` are ONE compound-loaded scene from
   `getCurrentStageName()`'s perspective, not two independently-targetable
   stages. That's suggestive but was confirmed for exactly one door, not the
   ~6 other placement-zone roots (`SkyWorldCastleZone`,
   `SeaWorldLava/Lighthouse/SphinxQuiz/WallCaveWestZone`). Rather than guess,
   `compile_port_remaps` ships the raw extracted per-door stage verbatim
   (matching every already-in-game-validated coupled-mode field it reuses —
   the ENTRY row's `from` is always a subarea's own singular interior
   `.stage`, the SAME field coupled mode has used since the 2026-06-19 walk,
   never a per-door zone value) and a new `ZONE_STAGE_ALIAS: dict[str, str]`
   seam in `port_graph.py`, authored EMPTY, applied only to a REWRITE
   TARGET's stage when that target is an OVERWORLD mouth (the one schema-v2
   field the coupled shuffle never exercised). If Devon's preview-mode
   (`kEntranceRemapApply=false`) log walk past a zone-hosted door shows
   `cur`/`dest` reporting the parent stage instead of the zone, add
   `{"ZoneName": "ParentHomeStage"}` to that table — a pure data change, no
   code change. Test-covered (`test_compile_port_remaps_zone_alias_applied_to_overworld_target`).
5. **Spoiler block.** `before_write_spoiler` now branches: falls through to a
   new `_write_decoupled_spoiler` when `_entrance_map` is unset (covers both
   "off" and "decoupled" — the function itself no-ops when `_port_matching`
   is also unset). Keyed by MOUTH pair (not subarea), since a subarea can now
   have independently-shuffled doors (Push Block Peril's two exits can lead
   to two different places) — each deviating pair printed once with both
   mouths' kingdom/subarea/side/marker, moons listed under whichever side(s)
   are an interior, plus a trailing vanilla-fixed-mouth count. Live-tested
   (header presence/absence both directions + a `moon inside` line).
6. **Readiness flag — NOT flipped, by design.** `PORT_SHUFFLE_SHIPPABLE`
   stays `False`; `test_port_shuffle_readiness_flag_defaults_off` untouched.
   This is Devon's explicit call per the P3e work order, gated on the zone
   preview-walk (item 4) at minimum. See the handoff doc's updated status for
   the full checklist.
7. **Bug found in Devon's first live walk (2026-07-07, FIXED same day): the
   empty coupled mirror shadowed the decoupled push.** Devon's first
   decoupled seed produced `[entrance] applied 0 remap entries (reset=1)` on
   HELLO and every door walked vanilla. Root cause: `context.py`'s Connected
   handler reassigns BOTH state mirrors every connect (absent slot_data key →
   `set_entrance_map({})`, which still marks the mirror *configured* — that
   reassign-both behavior is deliberate, it's what clears stale tables on a
   reconnect across seeds), but `push_entrance_map` selected a compiler on
   `is_*_configured()` alone, coupled first — so the always-configured empty
   coupled mirror won, compiled 0 rows, and sent a bare reset; the decoupled
   branch was unreachable through the real Connected path. The P3e
   mode-selection tests missed it because they set one mirror at a time
   directly, never the Connected handler's set-both shape. Fix
   (`switch_server.py`): prefer the mirror that is configured AND non-empty
   (coupled still wins the defensive both-non-empty case); both-empty sends
   the vanilla-reverting reset unchanged; neither stays a no-op. Two new
   regression tests in `test_switch_server.py` (the exact decoupled Connected
   shape `set_entrance_map({})` + non-empty `set_port_matching`, and the
   both-empty off-seed clear). Client-only fix: re-run `install_apworld.py` +
   restart SMOClient; no Switch rebuild, no re-generation (the seed's
   slot_data was always correct — the matching just never left the client).

### 3f. Mushroom check promotion (design D9)
`_apply_junk_only_rules` exempts Mushroom-category locations iff decoupled;
Devon re-runs `compile_moon_logic.py` (romfs machine, shine_map present) to
fill the 43 Mushroom `requires` from the xlsx-derived requirements data.
In-game moon-spawn probe rides P4; scenario-floor contingency (PeachWorld
arrival, `capArrivalScenarioOverride` pattern) only if the probe fails.

**Work order written (2026-07-08):
[handoff-decoupled-p3f-mushroom-promotion.md](handoff-decoupled-p3f-mushroom-promotion.md)**
— `_apply_junk_only_rules` decoupled exemption (Dark/Darker Side stay
non-exempt per D5), Devon's `compile_moon_logic.py` re-run as an explicit
external dependency (not something the session can do itself), the
scenario-floor contingency explicitly deferred to P4.

**Status: IMPLEMENTED (2026-07-08).** Step 0's "11-location gap" turned out
to be a false alarm: the handoff's own recompute compared 36 junk_only
Mushroom locations against only 25 `moon_requirements.json` keys
**prefixed** `"Mushroom Kingdom:"`, but many records use subarea-prefixed CSV
keys (`"Peach's Castle: ..."`, `"Castle Courtyard 64: ..."`, `"Crazy Cap
Store (Mushroom): ..."`, the 6 boss-refight keys, etc.) whose
`location_name` **field** correctly reads `"Mushroom: ..."`. Diffing by that
field instead (not the key) — 36 junk_only Mushroom locations, 43 total
records whose `location_name` starts `"Mushroom:"`, matched set = 36,
missing = 0. The 43-vs-36 delta is exactly 7 non-junk_only Mushroom-category
records (6 re-fight Multi-Moons + 1 already-gated post-metro location, both
already excluded from the junk_only set on their own terms) — no CSV/xlsx
import gap, nothing to report to Devon, Step 0 cleared without a stop.

`_apply_junk_only_rules` (`hooks/World.py`) now drops Mushroom-Kingdom-tagged
junk_only names from the exclusion set when `_entrance_shuffle_mode(...) ==
EntranceShuffle.option_decoupled` (raw Choice value, not `is_option_enabled`
— same reasoning as every other mode-branch in this file); Dark Side/Darker
Side junk_only locations are untouched in all three modes, matching D5.
Requires backfill stays Devon's dependency (romfs-equipped
`compile_moon_logic.py` re-run) — all 36 locations already have complete
`moon_requirements.json` records (capture_groups/methods present) ready to
compile, they're just not run through it yet. Scenario-floor contingency and
the P4 in-game moon-spawn probe are untouched, per scope guard.

New tests: `test_p3f_mushroom_promotion.py` — 2 always-run data-shape checks
(the Step 0 diff-by-`location_name` result, encoded as a regression guard)
plus 3 `SMOAP_LIVE_AP`-gated subprocess probes (item-rule acceptance
decoupled-only for Mushroom, Dark Side non-exemption in all 3 modes, and a
real `Generate.main()` → `Main.main()` full-Fill run confirming the promoted
Mushroom checks don't raise `FillError`). Full suite: **1001 passed / 97
skipped** (the 999/94 P3e baseline + 2 new non-live + 3 new live-gated),
zero regressions; live re-run of the 3 new probes green against the
reinstalled zip. `PORT_SHUFFLE_SHIPPABLE` untouched (still `False`).

- **Model: Fable 5 for 3a–3d** (highest-interlock design + algorithm work in
  the repo; a subtle one-way logic bug is the top failure mode). Opus 4.8 is
  the budget fallback. **Sonnet 5 for 3e/3f** (follows existing `entrance_map`
  / `mm_bonus_*` / `_apply_junk_only_rules` patterns).

## Phase 4 — Validation

### P4 findings (2026-07-07, Devon's first live decoupled walk)

After the §3e item-7 client fix, the first real decoupled walk (seed
11314520684955636324) produced:

1. **PASS — interior-target chains + involution symmetry + entry `from_id`
   exact tier.** Cap "Frog Pond" door → Rumbling Floor Cave (a SEASIDE
   subarea — cross-kingdom into an interior) landed correctly, and walking
   back out returned Mario to the Cap door. First live validation of the
   entry-exact lookup tier.
2. **FINDING — chain into a NEXT-STORY-KINGDOM overworld triggers the
   engine's arrival flow, marker ignored.** Cap "Push Block Peril" door →
   "Gusty Bridges" door mouth (`WaterfallWorldHomeStage`/`WindBlowExStart`):
   the remap row applied byte-correct, but Devon had just cleared Cap Tower,
   so Cascade was the game's next story destination, unvisited — the engine
   flagged the commit `isForwardWorldWarpDemo=1` and ran the kingdom-arrival
   flow (splash + arrival spawn, "as if completed Cap via the wire"; the
   cascade-arrival hook suppressed the cutscene, not the framing). Control
   case: the P0 spike's Cap→Luncheon landing (NOT the next kingdom) had
   `fwdWarpDemo=0` and honored the `'shop'` marker exactly. Two suspects,
   not yet separated: (a) the first-visit/next-world warp-demo
   classification (one-time per kingdom), and (b) door-ENTRY ChangeStageInfos
   carry explicit `scenario=1` (pipe EXITS carry `-1` — the spike's clean
   landing was an exit), and broode-respawn forces scenario 1 into
   pre-Broode Cascade regardless. Retest below distinguishes them.
   **Related risk to test in the matrix:** a scenario=1 entry-mouth commit
   into a kingdom with real story progress could drag its scenario DOWN
   (the cap-return hook exists because low-scenario commits were a real
   problem) — walk a chain into a progressed kingdom and verify scenario.
3. **Devon design rulings (2026-07-07, supersede open questions above):**
   (a) **Free matching stays** — any mouth ↔ any mouth. The PBP-door →
   Gusty-Bridges-door overworld hop is working as designed; doors are NOT
   constrained to land in interiors. No `roll_port_matching` change.
   (b) **Chain-return flight is REQUIRED scope (new)** — from a
   chain-reached kingdom, the Odyssey/world map MUST allow flying back to
   any kingdom Mario has ALREADY VISITED (officially or via chain), and
   ONLY those (e.g. Cap → chain → Cascade → chain → Luncheon: may fly to
   Cap or Cascade, nothing forward). First live data: chain-reached
   pre-Broode Cascade (forced scenario 1) has the ship present
   (freeship-lifted, `exist=1 activate=1 launch=1`) but boarding-to-warp
   did not function — suspected vanilla story gating (Odyssey inactive
   until the arrival Multi-Moon). Two distinct halves to solve:
   (i) ship EXISTS but local story state blocks boarding (Cascade case) —
   needs a decomp read of the world-map/boarding gate before picking a
   hook; (ii) ship DOESN'T SPAWN at all in a chain-reached kingdom (P0
   Luncheon case, `exist=0`) — heavier, P5-approach-B-adjacent territory.
   Must also verify chain arrivals set the M7 visited bit (the
   only-visited-kingdoms restriction rides the existing kingdom-order-gate
   machinery + BACKSTOP). Devon's in-progress test (AP-granting Cascade
   moons) will tell us whether the Cascade block is moon-count or
   story-MM gated.
4. **FINDING — scenario-gated target markers fall back to default spawn
   (P3b prediction confirmed in-game).** Devon's second PBP-door entry
   (Cascade already visited) landed at Cascade's DEFAULT spawn (the
   Odyssey), not `WindBlowExStart`: Gusty Bridges is
   `{CascadeDeparture()}`-gated (`subarea_scenario_gates.json`), so in
   pre-departure scenario 1 the door actor and its placement marker don't
   exist — the engine's missing-marker fallback is the default spawn.
   NOT a logic bug (the 3d wiring already gates the mouth's outgoing edge
   on the same scenario fragments, and arrival-credit only claims "reached
   the kingdom", which physically holds). Two real costs: (a) cosmetic —
   chain arrivals at scenario-gated mouths land at the kingdom default
   spawn until the story advances there; (b) the RETRACE guarantee fails
   while the arrival door doesn't exist — the ruling-3(b) chain-return
   flight scope is therefore load-bearing (it's the guaranteed exit from
   a chain-reached kingdom whose doors are scenario-gated), not a
   fidelity nicety. Open sub-questions: whether the 2nd entry skipped the
   arrival framing (would confirm the warp-demo flow is one-time per
   unvisited next kingdom), and whether the Odyssey launched after Devon
   AP-granted Cascade moons (would pin the boarding block to the
   moon-count launch gate, making chain-return-flight half (i) cheap).
5. **BLOCKER (RESOLVED 2026-07-08 — see the banner in
   [handoff-p4-cascade-reentry-crash.md](handoff-p4-cascade-reentry-crash.md)
   for the full diagnosis; fix awaiting Devon's rebuild+retest) —
   FrameHeap abort re-entering Cascade post-moon-rock.** After
   opening Cascade's moon rock, re-entering the remapped PBP door (the same
   commit that had loaded cleanly three times pre-moon-rock) aborted in
   `sead::FrameHeap::tryAlloc` on `FileLoadThread` mid
   `ParallelSZSDecompressor`/`ResourceMgr::tryLoad`/`ArchiveEntry::load` —
   a frame-heap allocation failure loading stage resources. Full stack,
   ranked hypotheses (door-path HomeStage load heap headroom / forced
   scenario-1 × moon-rock actor set / session heap fragmentation), Devon's
   repro matrix, and the next-session work order:
   [handoff-p4-cascade-reentry-crash.md](handoff-p4-cascade-reentry-crash.md).
   Note the retrace edge (Gusty Bridges → PBP door mouth in Cap) validated
   clean immediately before the crash.
6. **(SUPERSEDED 2026-07-08 — Devon's repro matrix + the crash-log
   symbolization answered this: the arrival flow is one-time per unvisited
   next kingdom — the second PBP entry skipped the splash — and the
   persistent cost WAS the explicit `scenario=1`, now neutralized to `-1` on
   remapped overworld commits. Kept for the record.)**
   **Retest that separates the suspects (Devon):** with Cascade now visited,
   (i) walk Gusty Bridges door → should land at the PBP door mouth in Cap
   (retrace edge, both kingdoms visited — expect clean); (ii) re-enter the
   PBP door → if it now lands cleanly AT `WindBlowExStart` (no arrival
   flow), the cost is a one-time first-chain-arrival-per-unvisited-next-
   kingdom quirk (document, likely acceptable); if it STILL runs the
   arrival flow, the cause is persistent (scenario=1 explicit is the prime
   suspect) and needs a Switch-side fix (candidate: force scenario -1 on
   remapped commits targeting overworld mouths — decomp read of
   `isForwardWorldWarpDemo`/arrival-spawn selection first, per CLAUDE.md).

- pytest additions → `python scripts/install_apworld.py` → `Generate.py`
  (BOTH on Windows — the regen-loop and stale-shell rules in CLAUDE.md apply).
- Row-count assertion vs table cap at generate time.
- Devon's in-game walk matrix: chains of 2–3 subareas, forward + full retrace,
  save/load mid-chain, moon pipes, multi-exit stages, a chain-reached overworld
  each for an early and a late kingdom. Reuse the `kEntranceRemapApply=false`
  preview mode for a log-only dry run before the applied walk.
- **Model: Sonnet 5** for test writing; Devon in-game.

### P4 session 2026-07-08 — crash resolved, chain-return flight shipped, flag flipped

**Crash:** root-caused (stale explicit `scenario=1` on remapped overworld
commits → mixed oversized placement load → memory blowout; two victims: game
FrameHeap 07-07, mod heap 07-08) and fixed — scenario neutralization in
`EntranceShuffleHook` + allocation-free fixed-buffer `Status` in the pump.
Full write-up: the banner in
[handoff-p4-cascade-reentry-crash.md](handoff-p4-cascade-reentry-crash.md).

**Chain-return flight (finding 3b) IMPLEMENTED — switch-mod, awaiting the
same rebuild.** Devon's answers pinned the boarding block to the moon-count
launch gate (Odyssey flew after AP-granting moons), making half (i) the
proven free-detour lever. Design (Devon picked "open globe + bounce forward
picks"):

- `ApState`: `chain_reached_kingdoms` bitmask + per-kingdom
  `chain_origin_bit[]` + `chain_allowance_bit` (the takeoff read publishes
  which kingdom's allowance is live, so launch and bounce can't disagree).
- `EntranceShuffleHook::processChainArrival` (remapped overworld commits
  only, pre-orig, BEFORE reportArrival so `last_arrival_kingdom` still holds
  the origin): marks dest chain-reached + dest/origin session-visited,
  records the origin, and — generalizing the validated Cascade treatment,
  half (ii) — `setAlreadyGoWorld` (parked landing, no first-visit flow) +
  `forceAcquireOdyssey` (P0 Luncheon `exist=0` case) + `unlockWorld` (world
  map lists it as a return destination later). Lost/Ruined exempt from the
  normalization (story-managed ship states), bookkeeping still applies.
- `UnlockShineNumHook` (current-world read): chain-reached AND rolled gate
  unpaid (`depositedEffectiveMoons < gate`, exported from KingdomOrderGate)
  → return 0 (proven free-detour lever) + publish the allowance bit. Reverts
  to honest values once paid. Accepted cosmetic: gauge reads 0/"full" while
  active.
- `WorldMapSelectHook` (Layer-2 flight commit): while the allowance is
  active, an un-visited pick (session bit OR save `isAlreadyGoWorld`) is
  SUBSTITUTED to the chain origin (fallback Cap) with a Cappy bubble —
  substitution is the proven primitive at this seam (decomp:
  `tryChangeNextStageWithDemoWorldWarp` commits unconditionally).

**Watch items for Devon's build+walk (one build covers everything):**

1. R1-Broode-defeated retest → expect `[entrance:remap-scenario] … 1 -> -1`
   + clean load at `WindBlowExStart`. Still crashing ⇒ P5 approach B.
2. Chain into an unvisited kingdom → `[chain-arrival]` log, parked ship,
   no splash; board → globe opens at 0; pick an unvisited kingdom → bounce
   + bubble; pick a visited one → normal flight.
3. **unlockWorld-on-chain-arrival autopilot check** (adjacent to the old
   mUnlockWorldNum-overshoot bug): after chaining into a LATE kingdom,
   verify the post-boss autopilot still routes normally.
4. Free-detour kingdoms chain-reached: allowance intentionally does NOT
   stack (their gate is already 0; detour-exit gate still enforces the
   sibling rule). Special1/2 unlock reads `findUnlockShineNum` too — a
   game-cleared save with an active allowance could prematurely satisfy
   `checkEnableUnlockWorldSpecial1/2`; post-game edge, log-watch only.
5. Still open from the P3e checklist (unchanged): Lake town-zone
   `cur=`/`dest=` log check (`ZONE_STAGE_ALIAS` stays empty until a walk
   shows a zone name), walk 3 (coupled `simple`-seed regression), Mysterious
   Clouds → PBP interior → both exits diverging (P2 multi-exit proof).
6. Rest of the P4 matrix: save/load mid-chain, moon pipes, early+late
   chain-reached kingdoms, scenario-drag-down check on a progressed kingdom
   (should now be moot per the neutralization — verify).

**PORT_SHUFFLE_SHIPPABLE flipped for real** (kill-switch comment, OptionError
text, `EntranceShuffle` docstring, and the readiness test — now
`test_port_shuffle_readiness_flag_shipped` — all updated; targeted pytest
green, full suite on Windows pending).

### P4 findings (2026-07-08, Devon's pre-fix walk — two notes + a topology theme)

Both walks predate this session's fixes; diagnoses against the attached log
(`Ryujinx_1.3.3_2026-07-08_00-25-03.log`).

7. **NOTE 1 — stranded in chain-reached Metro (no Odyssey, no way back).**
   Sand shop door → Metro overworld (day), Odyssey's parking spot EMPTY —
   the P0-Luncheon `exist=0` case (chain arrivals never ran the engine's
   ship-placement bookkeeping). No return path; save+quit recovered (S&Q
   respawns via the save's own kingdom — worth remembering as the universal
   escape hatch). **Addressed by this session's chain-arrival normalization
   + chain-return flight** (forceAcquireOdyssey + setAlreadyGoWorld +
   unlockWorld on remapped overworld commits; takeoff allowance + visited-
   only bounce): post-rebuild, that arrival should land with a parked ship
   and Sand selectable on the globe. Also note: post-fix, chain arrivals
   load the kingdom's TRUE story scenario (scenario neutralization) — a
   never-visited Metro chain arrival will be scenario-1 NIGHT, not the day
   layout Devon saw; that's the coherent behavior, not a regression.

8. **NOTE 2 — Sand ice cavern → broken Bowser's (no skybox, wrong colors,
   map still Sand). CONFIRMED: the ZONE_STAGE_ALIAS case, live.** Log:
   `[entrance:file] stage='SandWorldPressExStage' id='arijigoku'` →
   `[entrance:remap-APPLIED] … -> stage='SkyWorldCastleZone' id='jizo02'`.
   The matched Bowser's door-mouth's extracted per-door `.stage` is the
   placement-zone root `SkyWorldCastleZone`; shipped verbatim as a rewrite
   target it loads the ZONE as a standalone stage: castle geometry, no
   skybox/graphics preset (the wrong colors), no world-list entry → world id
   stays Sand (hence the map, and Devon's checkpoint-warp escape working).
   This is precisely what §3e item 4's empty data seam anticipated. **Fix is
   the designed one-liner** — `ZONE_STAGE_ALIAS = {"SkyWorldCastleZone":
   "SkyWorldHomeStage"}` in `port_graph.py` → `install_apworld.py` →
   reconnect (rows compile client-side at Connected; NO re-seed, NO Switch
   rebuild). Held back per Devon's "no solutions right now" — apply on his
   word. The other ~5 extracted zone roots (`SeaWorldLava/Lighthouse/
   SphinxQuiz/WallCaveWestZone`, …) will almost certainly need the same
   entry when a walk lands on them; per the seam's one-confirmation-at-a-
   time protocol they stay out until observed. Side interaction worth
   noting: a zone-named target also BYPASSES the new scenario
   neutralization + chain-arrival bookkeeping (both gate on
   `kingdomShortFromHomeStage`, which doesn't know zone names) — the alias
   restores those too.

9. **THEME (Devon, 2026-07-08) — proposed matching-topology constraint,
   PENDING decision.** Proposal: overworld mouths must always match subarea
   INTERIOR mouths (either end); interior mouths may match interiors or
   overworlds; **an overworld↔overworld pair is never allowed.** If mouth
   counts don't balance, add kingdom overworlds to the pool (spawn at the
   Odyssey). This partially supersedes ruling 3(a) ("free matching stays —
   any mouth ↔ any mouth", 2026-07-07) — final call is Devon's. Discussion
   points logged for that decision:
   - Both motivating incidents trace to now-addressed causes (note 7 → the
     chain-arrival/return fixes; note 8 → the zone alias). The one
     previously validated O↔O hop (PBP → Gusty Bridges) worked. Recommend
     RE-WALKING overworld hops on the fixed build before deciding — the
     constraint may be solving already-solved pain.
   - Independent merits regardless: preserves the vanilla "doors go inside
     something" feel, and shrinks the overworld-arrival edge-case surface
     (arrival flow, ship state, scenario, zone stages) to chain EXITS only.
   - Feasibility: no pool compensation should be needed. Every overworld
     mouth has a vanilla interior partner, and multi-exit subareas add
     surplus interior mouths, so #interior ≥ #overworld holds by
     construction — "no O–O pairs" is satisfiable without adding kingdom
     overworlds. (If kingdom-overworld pool entries are ever wanted for
     flavor, note they'd be landing-only pseudo-mouths, which breaks the
     validated involution symmetry — that's a directed-matching redesign,
     not a constraint tweak.)
   - Cost/locus: `roll_port_matching` constraint + the 3d logic wiring —
     apworld-only, needs a RE-SEED, no client/Switch changes. Cleanest as a
     third topology knob (e.g. keep free matching available) rather than a
     hard replacement, given 3(a) was an explicit ruling.
   - **RESOLVED (2026-07-08, Devon's ruling after sleeping on it): ADOPT
     "no overworld↔overworld pairs" — REPLACING free matching, no option
     knob.** Implemented same session in `port_matching.py`
     (`roll_port_matching`): O↔O pairs are never rolled; I↔I pairs are
     deferred while the unmatched pool's interior surplus ("slack" =
     #interior − #overworld) is < 2, so phase 2 can always give every
     overworld mouth an interior partner; loud RuntimeError postcondition
     sweeps the rolled matching for O↔O. The 3d logic wiring needed NO
     change (it consumes the matching generically). New tests: real-pool +
     festival no-O↔O sweeps, a real-pool `#interior ≥ #overworld`
     data-shape guard, and a zero-slack adversarial pool that forces
     all-O–I pairing. Suite 1007/97 green; zip reinstalled. **Needs a
     RE-SEED to take effect** (rolled at generation).

### P4 session 2026-07-08 (second) — retest results, triage, topology shipped

Devon rebuilt (install_apworld + build_switchmod + deploy) and ran the watch
matrix. First: his full-pytest "157 failed" was **environmental, not a
regression** — every failure was `async def functions are not natively
supported`, i.e. the run used a Python without `pytest-asyncio`. The repo
`.venv` (which has it) runs the identical set **1003 passed / 97 skipped,
zero failures** (re-confirmed this session; 1007 after the item-9 tests).
Run tests via `.venv\Scripts\python -m pytest apworld\smo_archipelago\tests`.
(Separately: under the sandboxed agent shell, `tmp_path` tests need
`--basetemp` pointed somewhere writable — the `pytest-of-devon` ACL issue
from the P3c session.)

**Validated this walk (fixed build, seed unchanged):**

- **R1 Broode-defeated → PBP door: CLEAN.** `[entrance:remap-scenario]
  stale explicit scenario 1 -> -1` fired, clean load at `WindBlowExStart`.
  The Cascade re-entry crash fix (handoff banner) is CONFIRMED IN-GAME —
  no P5 escalation needed for THAT class.
- **Chain into unvisited Metro (Sand shop door): the finding-7 case now
  lands right.** `[chain-arrival]` bookkeeping ran (setAlreadyGoWorld +
  unlockWorld + parked-flight arrival, scenario-1 night as predicted),
  Odyssey parked and boardable, globe opens at gate 0
  (`findUnlockShineNum[chain-return]` log present), un-visited pick bounced
  with the Cappy bubble, visited pick flew normally. Chain-return flight's
  core loop works.
- **Sand ice cavern → Bowser's: the ZONE_STAGE_ALIAS one-liner is
  CONFIRMED IN-GAME** (proper `SkyWorldHomeStage` arrival, Odyssey present,
  world id correct). First alias entry stays; the ~5 other zone roots wait
  for walks per protocol.
- **Odyssey flight → Lake marked visited correctly**
  (`[wmap.tryChange.Demo] visited[Lake] = true`).
- **Mysterious Clouds moon pipe → PBP interior landed correctly** (moon-pipe
  row + interior-target chain both fine; the EXIT from PBP is finding 10).

**New findings (10–13):**

10. **BLOCKER — FrameHeap abort leaving PBP (subarea) into remapped Metro
    overworld; scenario neutralization is NOT sufficient for this class.**
    `cur='PushBlockExStage'` exit → `CityWorldHomeStage`/`donsuke`: the
    ChangeStageInfo already carried `scenario=-1` (no stale-scenario input
    at all), `[chain-arrival]` ran (Metro already chain-reached), then the
    same `sead::FrameHeap::tryAlloc` abort on FileLoadThread mid
    `ParallelSZSDecompressor`/`ResourceMgr::tryLoad` as 07-07. Control
    contrast: the SAME session's Sand-overworld shop door → Metro
    (`bikereturn`) loaded CLEAN at 00:08; the crash at 00:40 differs by (a)
    origin being a pooled SUBAREA stage, (b) 30 more minutes of session
    (Bowser/Moon/Lake flights, moon grants), (c) Metro re-load vs first
    load. Residual suspect from the handoff stands: the door/exit-path
    scene-heap shape when the destination is a big overworld. Repro matrix
    for Devon: fresh boot → Mysterious Clouds pipe → PBP → main-entrance
    exit (does it crash cold?); same exit remapped to a SMALL overworld;
    overworld-door → Metro again late-session (fragmentation control). If
    it repros cold, escalate overworld-TARGET commits to **P5 approach B**
    (route through `tryChangeNextStageWithDemoWorldWarp` — flights into
    Metro are consistently clean, and it would also solve findings 11–13's
    arrival-state edge cases at the root). Decomp read of the stage-load
    heap sizing REQUIRED before any fix (CLAUDE.md rule).

11. **Chain-reached Bowser's: takeoff allowance does NOT open the
    post-peace story launch.** Pre-boss AND post-boss (RoboBrood beaten),
    Cappy-on-Odyssey gives the story line ("let's hurry after those two");
    the gauge reads full (allowance zeroed `findUnlockShineNum(current)`)
    but launch is refused until 8 Bowser moons were AP-granted and
    deposited (`addPayShine count=8`). So the "chase Bowser" story state's
    launch predicate consults something OTHER than the current-world
    `findUnlockShineNum` — candidates: the by-world-id variant
    (deliberately left honest), the un-hooked `GameDataHolder::
    findUnlockShineNum` member inlined at the site, or a shine-count
    compare via `getCurrentShineNum`. Same family as Lost/Ruined
    story-managed ship states (already exempted from normalization).
    **Decomp read of the boarding/launch flow required before picking a
    seam.** Until fixed, a chain into a post-peace-story kingdom can
    strand (S&Q is the escape hatch).

12. **`unlockWorld` on chain arrival OVERSHOOTS — decomp-confirmed.**
    OdysseyDecomp `GameProgressData`: `unlockWorld(idx)` loops
    `unlockNormalWorld()` (`mUnlockWorldNum++`) until `isUnlockWorld(idx)`
    — a **monotonic counter written to the save**. Chain-arriving in
    Bowser's (worldId 12) permanently unlocked EVERY kingdom up to Bowser
    on the globe. This is the old mUnlockWorldNum-overshoot fear realized
    (watch item 3). Consequences observed: globe lists everything (Devon
    wants visited-only — [[kingdom-order-gate-premature-destinations]] now
    load-bearing, not cosmetic), and once no bounce is active the unlocked
    worlds are freely flyable from ANY kingdom.

13. **Post-payment forward leak — visited-only enforcement dies with the
    allowance.** Paying the chain-reached kingdom's rolled gate clears
    `chain_allowance_bit` (by design, "revert to honest"), which turns the
    Layer-2 bounce OFF entirely; nothing else enforces order
    (`KingdomOrderGate::kRules` is an empty sentinel — the strict-order
    table has no active entries). Result: after granting+depositing 8
    Bowser moons, the story `firstNext` flight to MOON committed through
    `tryChange.Demo` unbounced (Moon reached with only Cascade+Bowser
    progressed — out of AP logic), and thereafter free travel anywhere
    (finding 12's unlocked worlds + no bounce). **Fix sketch (next
    switch-mod session, with Devon):** decouple the visited-only rule from
    the allowance bit — bounce any un-visited/not-alreadyGo pick whenever
    the DEPARTING kingdom is still chain-reached-only (persist the chain
    bit; clear it only if the kingdom is later reached legitimately), and
    decide what to do about finding 12's already-unlocked earlier kingdoms
    (options: stop calling unlockWorld and find a listing-only seam via
    decomp; or extend the bounce to cover mod-unlocked-but-unvisited picks
    from ALL kingdoms — needs care not to break vanilla forward
    progression, where flying to an unvisited next kingdom is the normal
    move). Devon's design ruling needed on whether paying a chain
    kingdom's gate should EVER legitimize story-forward travel (this walk
    says no).

**Still open from the watch list:** Lake town-zone `cur=`/`dest=` log check,
walk 3 (coupled `simple` regression), PBP both-exits-diverge (half done —
entry validated, exit is finding 10), save/load mid-chain, scenario
drag-down verify on a progressed kingdom.

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
