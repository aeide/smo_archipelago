# Decoupled / chained entrance randomizer (Devon, 2026-06-20)

**Goal.** Evolve the shipped P7 entrance shuffle from a *coupled door→interior
bijection* into a **full any-to-any port randomizer**:

1. **A subarea's exit need not return to the overworld it came from.** Today every
   interior dumps Mario back at its origin door's overworld. Devon wants an exit pipe
   to be its own shufflable endpoint — so leaving subarea B can drop you straight into
   subarea C, forming **chains of subareas**.
2. **Path-symmetric (involution).** "A → B → C should also mean C → B → A if you
   follow the same pipes/doors." Each physical connection is **one undirected edge**:
   retracing your steps walks you back the way you came.
3. **More endpoints → put overworlds in the pool.** Chaining needs more matchable
   endpoints; Devon proposes adding overworld landings ("enter Poison Tides, wind up
   in Luncheon Kingdom, as if you'd flown the Odyssey there").
4. **Purpose:** break the early-game bottleneck by widening the opening options.

**Status: investigated, NOT started. Estimate ~65% feasible, VERY HIGH effort** —
the largest item in this folder. The good news is concentrated and real: the
hard-won Switch apply-mode machinery (the precomputed table + the "lie to the game"
ChangeStageInfo rewrite) **survives almost intact**. The risk is concentrated in two
places: a genuine in-game unknown (landing in an overworld via a door/pipe instead of
the Odyssey flight) and a large *logic* redesign (a connectivity-guaranteed matching
that collides head-on with the kingdom-order model).

---

## The core shift: directed bijection → undirected port matching

### What ships today (coupled, directed)
- Each subarea is a node with **one logical port**: `primary_entry` (door in) /
  `primary_exit` (back out). The bijection σ maps **door D → interior σ(D)**
  ([entrance_logic.py](../../apworld/smo_archipelago/entrance_logic.py)
  `_roll_entrance_bijection`, `compile_stage_remaps`).
- Overworlds are **fixed anchors, never in the pool** — every subarea implicitly
  hangs off its home overworld. The region graph is a **star** (overworld center,
  subareas as leaves) — see `_wire_entrance_shuffle` in
  [hooks/World.py](../../apworld/smo_archipelago/hooks/World.py).
- Returns are a **pure function of the permutation**: the exit row rewrites
  `I.stage → D.primary_exit.dest` (the origin overworld), so there is **no runtime
  origin tracking** on the Switch (this is what let P7 sidestep the save/load origin
  problem the spike called "THE real integration cost",
  [p7-entrance-shuffle-spike.md](../p7-entrance-shuffle-spike.md) §3c).
- Multi-exit subareas **collapse all exits to origin** (validated: both Cascade
  `gragra` + `gragrareturn` pipes → the one origin).

### What Devon is asking for (undirected, chained)
Decompose the world into **ports** — one per physical opening: each overworld
door-mouth, each subarea entrance, each subarea exit pipe. A single-door subarea has
**two ports** (in + out); [entrance_stages.json](../../apworld/smo_archipelago/data/entrance_stages.json)
already records this (`entries[]` / `exits[]` lists, e.g. *Push Block Peril* has two
exits: a `ChangeStageArea` and a `DokanStageChange`). The shuffle becomes a **random
perfect matching (involution) over all ports**: walk into port P → arrive at
`match(P)` facing inward; because the matching is symmetric, walking back out returns
you through P. **This is exactly Devon's requirements 1 + 2 for free** — chaining and
path-symmetry are inherent properties of an involution on ports, not extra mechanism.

This is the standard "coupled two-way door rando" model used by mature AP worlds
(OoT/Metroid door rando). It is **cleaner** than the current directed model, not
hackier — but it is a different data model end to end.

---

## What survives (the encouraging part)

- **The Switch rewrite mechanism is unchanged.** `processEntranceRemap` in
  [EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp) already
  rewrites `mChangeStageName` + `mChangeStageId` in the `ChangeStageInfo` buffer at the
  universal `GameDataFile::changeNextStage` chokepoint, with the moon-rock `dest==cur`
  guard and the buffer-fit guard. An involution is still just a set of directed rewrite
  rows — chaining adds rows, it doesn't change how a row is applied.
- **Returns stay precomputed → save/load stays sidestepped.** Even with chains, each
  exit port maps to exactly one destination (a pure function of the matching). The
  exit table is still static and stateless, so the §3c origin-persistence cost the
  spike feared **stays avoided** — the single biggest "phew."
- **The wire tier already chunks a full-overwrite table.** `EntranceMap` /
  `parseEntranceMap` / `applyEntranceMap` (seqlock, `kEntranceRemapMax = 256` slots,
  64-row chunks — [ApProtocol](../../switch-mod/src/ap/ApProtocol.cpp),
  [ApState](../../switch-mod/src/ap/ApState.cpp)) already carries ~238 rows worst case;
  the involution's row count is the same order of magnitude.
- **`compile_stage_remaps` is the natural seam** — it already turns a bijection into
  directed Switch rows. It generalizes to "emit one rewrite row per port-edge end."

## What has to be rebuilt

### 1. Data: enumerate every port, including overworld door-mouths (medium–high)
- Today only `primary_entry` / `primary_exit` are used. The matching needs **every**
  `entries[]` / `exits[]` port as a distinct node, plus a stable port id (the
  `entry_id` already disambiguates, e.g. `PoisonWaveExEnt` vs `PoisonWaveExExit`).
- **Overworld door-mouths must become pool nodes.** Each overworld has one door-mouth
  per subarea door physically in that kingdom. `extract_entrance_stages.py` must be
  re-run with enrichment to capture the overworld side of every door (and, for the
  literal-Odyssey-arrival variant, the overworld arrival entrances). **IP note:** stage
  + entry-id identifiers are functional (same regime as the existing entrance_stages
  data); no Nintendo strings involved.
- **The deferred conflated-subarea split becomes mandatory** — Costume Room (×3) and
  Sphynx Treasure Vault (×2) currently merge multiple physical doors into one node
  (spike §1b-bis); a port matching needs one node per physical door.

### 2. The matching algorithm with a connectivity guarantee (high — the logic core)
- A naïve random perfect matching can produce **closed loops disconnected from the
  start** (a chain that cycles among subareas and never touches a reachable overworld =
  a dead pocket, or worse, strands required moons). The shuffle must produce a
  **graph where the start kingdom can reach everything the fill needs** — the classic
  entrance-rando solvability constraint. Options: AP assumed-fill + a connected-graph
  repair pass, or a reachability-preserving matching (build the matching so each step
  keeps the frontier growing). This is real algorithm design, not a config flag.
- **Asymmetric edge cost.** A port-edge is *not* freely bidirectional for logic: to go
  A→B you need only A's door; to come back B→A you must physically **reach B's exit
  pipe**, which can require interior abilities. So each undirected edge carries two
  different access rules (forward = door/overworld gate; reverse = interior reqs to
  reach the exit). The current `make_door_access_rule` + `compile_interior_requires`
  split already separates door-gates from interior-reqs — the pieces exist, but they
  must now be attached to **both directions of a general graph**, not a star.

### 3. Reconcile with the kingdom-order model (high — design, not mechanism)
This is the deep collision. Devon's explicit aim — reach overworlds early via subarea
chains — **directly contradicts** the kingdom-order gate. Today kingdoms unlock in
Odyssey-flight order; `KingdomOrderGate.cpp`'s BACKSTOP
(`tryChangeNextStageWithDemoWorldWarp`) actively rejects out-of-order warps, and the
map already exposes premature destinations (memory
`kingdom-order-gate-premature-destinations`). If a Cap subarea exit now lands you in
Luncheon's overworld, you've bypassed the entire progression. That's the *point*, but
it means:
- The order gate must be **relaxed or disabled** when this mode is on (a deliberate
  decision — it changes how kingdom gates, peace gates, and moon-pipe gating compose,
  since all of them assume the flight order).
- The **peace / scenario state** of a chain-reached overworld is the subtle part — see
  §4.

### 4. Landing in an overworld — the #1 in-game unknown (medium risk, mitigable)
Two ways to realize "wind up in Luncheon":
- **(A, recommended) Emerge from one of Luncheon's existing door-mouths.** If a Cap
  subarea's exit port matches a Luncheon *door-mouth* port, Mario exits into Luncheon's
  overworld through a transition **SMO already performs every time you leave a Luncheon
  subarea** — a known-good load. This achieves Devon's outcome ("you wind up in
  Luncheon") while **sidestepping the raw-overworld-arrival unknown entirely**, and it
  needs no new Odyssey-arrival plumbing. The residual question is only whether standing
  in an overworld you haven't "officially flown to" leaves the kingdom in a sane
  scenario state (the Odyssey may not be physically parked) — a smaller question than a
  synthetic arrival.
- **(B, literal "as if you landed the Odyssey") route through the demo-world-warp
  seam.** We *already* hook `tryChangeNextStageWithDemoWorldWarp` (the overworld→
  overworld flight path SMO uses for real arrivals). A landing port could be rewritten
  through *that* path rather than a raw pipe transition, so the kingdom loads via the
  engine's own arrival code (Odyssey parked, correct scenario). Higher fidelity, more
  plumbing, and it must satisfy/relax the order BACKSTOP that lives on the same hook.

Recommend **A** for v1 (lowest risk, reuses known-good transitions), with **B** as a
later fidelity upgrade. Either way `mScenarioNo` correctness for a chain-reached
overworld is the thing to validate in-game first.

### 5. Compound-key Switch lookup — the deferred `from_parent` fix, generalized (medium)
Today exit rows key on `cur` (the interior stage) alone, which works *only* because
each interior has one logical exit to a shared overworld. With multiple exit ports per
stage going to **different** destinations (and with nested interiors whose vanilla exit
dest is a *parent interior*, not an overworld), `cur` alone is ambiguous. The fix is
exactly the one the memory `entrance-from-parent-fix-deferred` already scoped: **add a
second match key** (`mChangeStageId` / the exit's `entry_id`, and/or `from_parent`) so
the lookup disambiguates *which* pipe Mario used. The `ChangeStageInfo` already carries
the id, and `lookupEntranceRemap` already takes two keys — this extends the key, it
doesn't redesign the path. The memory's "how to apply" checklist
(`compile_stage_remaps` + `EntranceMapMsg` passthrough + `EntranceRemapEntry`/`Slot` +
`parseEntranceMap` + `lookupEntranceRemap` entry branch) **is the work order for this
piece.**

---

## Risks / unknowns (why ~65%, not higher)

- **Overworld-via-transition load state (#1).** Whether Mario lands in a chain-reached
  overworld in a sane scenario/Odyssey state is unverified. Mitigated hard by approach
  (A) (reuse existing door-mouth exits) but still needs a first in-game probe.
- **Connectivity-guaranteed matching.** A random involution can strand regions; the
  shuffle must guarantee solvability. Real algorithm work; AP's assumed-fill helps but
  doesn't free you from producing a connected, logic-respecting graph.
- **Kingdom-order reconciliation.** The order gate and the whole peace/moon-pipe gating
  stack assume Odyssey-flight order; chained overworld access breaks that assumption by
  design. Untangling it cleanly (vs. a tangle of special cases) is the main design risk.
- **Asymmetric bidirectional rules.** Modeling each edge's forward (door) vs reverse
  (reach-the-exit interior reqs) cost in a general graph is more error-prone than the
  current star; more places for a one-way logic bug.
- **Data volume + multi-port stages.** Enumerating every port, splitting conflated
  subareas, and handling stages with 2+ exits (the Cascade/Push-Block shapes) is broad,
  finicky extraction work.
- **Row budget.** A full port involution + overworld door-mouths could approach the
  `kEntranceRemapMax = 256` table cap; count it during design (chunked sends already
  exist, but the BSS table is fixed).

## What de-risks it

- The **Switch apply mechanism, the precomputed-return insight, and the chunked
  full-overwrite wire table all carry over** — the most expensive, already-validated
  parts don't change.
- An **involution is a cleaner model** than today's directed bijection; chaining +
  symmetry fall out of it for free rather than being bolted on.
- The **compound-key fix is already scoped** (the `from_parent` memory is a ready work
  order).
- Approach **(A)** lets overworld landings reuse **known-good** existing door
  transitions, turning the scariest unknown into a smaller scenario-state question.

## Recommendation

Strong long-term feature, but it's a **near-total P7 rework**, so stage it:

1. **Spike the #1 unknown first (one cheap build).** Hand-author a single remap row
   that points a subarea exit at a *different kingdom's* existing door-mouth and walk it
   in-game (approach A). Confirm Mario lands in that overworld in a usable state. This
   binary result gates the whole feature — do it before any apworld work.
2. **Generalize the data + Switch key** (port enumeration, conflated-subarea split,
   compound exit key — the `from_parent` work order). Switch-side, this is mostly the
   already-scoped deferred fix.
3. **Build the connectivity-guaranteed matching + general-graph reachability** in the
   apworld, with the kingdom-order gate relaxed under this mode. This is the bulk of the
   new design effort.
4. **Add literal Odyssey-arrival landings (approach B) as an optional fidelity pass**
   if approach A's "no Odyssey parked" feel isn't good enough.

**Why ~65%:** no single piece looks impossible and the costliest machinery is already
built and validated, but it stacks a true in-game unknown (overworld landing) on top of
a substantial logic redesign (solvable matching + order-model reconciliation) — more,
and more interlocking, surface than any other v3 item. The spike in step 1 would move
this number a lot in either direction.

Sources consulted (disk-truth reads this session):
[EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp),
[entrance_logic.py](../../apworld/smo_archipelago/entrance_logic.py),
[hooks/World.py](../../apworld/smo_archipelago/hooks/World.py),
[data/entrance_stages.json](../../apworld/smo_archipelago/data/entrance_stages.json),
[ApState.cpp](../../switch-mod/src/ap/ApState.cpp) / [ApState.hpp](../../switch-mod/src/ap/ApState.hpp),
[ApProtocol.cpp](../../switch-mod/src/ap/ApProtocol.cpp),
[p7-entrance-shuffle-spike.md](../p7-entrance-shuffle-spike.md),
[logic-and-entrance-status.md](../logic-and-entrance-status.md), and memories
`entrance-from-parent-fix-deferred` / `entrance-shuffle-live-validated` /
`kingdom-order-gate-premature-destinations`.
