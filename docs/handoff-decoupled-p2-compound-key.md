# Handoff — P2: compound-key entrance lookup (decoupled entrance rando)

**For a fresh session (Opus).** Read CLAUDE.md first — especially the
stale-shell warning (ALL file reads/edits/diffs via the Read/Write/Edit/Grep
tools; never trust shell `cat`/`grep`/`git diff` over file bytes) and the
build/deploy blocks. Then this doc. Context chain if needed:
[plan-decoupled-entrances.md](plan-decoupled-entrances.md) (the phase plan +
P0/P1 results) →
[v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md](v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md)
(design rationale) →
[devon-p0-decoupled-spike-results.md](devon-p0-decoupled-spike-results.md)
(the empirical confirmation of the ambiguity you're fixing).

## Where things stand

- **P0 (PASSED 2026-07-06):** cross-kingdom overworld landing via an existing
  door-mouth works. The walk ALSO empirically confirmed the exit-key ambiguity:
  Push Block Peril's TWO physical exits (main door `PushBlockExStageEnt` +
  pipe `PushBlockExStageEntDokan`) both matched the single `cur`-keyed spike
  row — the exit table cannot route different physical exits of one stage to
  different destinations. That is precisely what P2 fixes.
- **P1 (DONE 2026-07-07):** `entrance_stages.json` is schema v2 — every
  `entries[]`/`exits[]` item now carries a stable `port_id`
  (`f"{overworld_stage}#{entry_id}"`), each subarea has a deduplicated
  `door_mouths` dict, and the row-budget decision is made: **bump
  `kEntranceRemapMax` 256 → 512 in this phase** (P3's full port involution
  worst case is 331–390 rows; ~200 B/slot fixed BSS, trivial).
- The P0 spike rows are still in `EntranceShuffleHook.cpp` behind
  `kP0DecoupledSpike = false` — leave them; they're documentation.

## Goal

Exit rows currently key on `cur` (the stage being left) alone. Add a **second
match key — the transition's `entry_id`** — end to end (apworld →
wire → parser → table → frame-thread lookup), so a multi-exit stage can route
each physical exit to a different destination. This is the deferred
`from_parent` fix (memory `entrance-from-parent-fix-deferred`), generalized.
It changes the KEY, not the mechanism: same chokepoint, same rewrite body,
same chunked full-overwrite wire flow.

Key insight making this cheap: at exit time the `ChangeStageInfo` **already
carries the disambiguator** — `mChangeStageId` (read via
`readCstrAt(info, kOffChangeStageIdCstr)` in `processEntranceRemap`) is the
shared ChangeStageId of the door pair Mario used (SMO convention: both
placements of a matched door pair reuse one id — the same convention P1's
`port_id` builds on). So `(cur, id)` at exit time == P1's port coordinate.

## The work order (all files by disk-truth tools)

### 1. Switch: table + lookup — `switch-mod/src/ap/ApState.{hpp,cpp}`
- `EntranceRemapSlot`: add `char from_id[kCheckFieldCap]` (empty = wildcard).
- `kEntranceRemapMax` 256 → 512 (the P1 decision; update the BSS math comment).
- `applyEntranceMap`: merge key `(from, is_exit)` → `(from, from_id, is_exit)`.
- `lookupEntranceRemap`: signature gains the transition id (from the
  ChangeStageInfo). Match precedence, first hit wins:
  1. ENTRY row matching `dest` (unchanged — entry rows stay dest-keyed;
     P3 may later want ids here too, but don't add speculative keys),
  2. EXIT row matching `(cur, id)` exactly,
  3. EXIT row matching `cur` with empty `from_id` (**wildcard — this is the
     back-compat path**: every row today's coupled `compile_stage_remaps`
     emits keeps working unchanged).
  Keep the seqlock read pattern and fail-safe torn-read behavior exactly as-is.

### 2. Switch: parser — `switch-mod/src/ap/ApProtocol.{cpp,hpp}` + hook caller
- `parseEntranceMap`: accept optional `"from_id"` field into
  `EntranceRemapEntry.from_id`. ⚠ The parser **hard-rejects unknown fields**
  (`else { return false; }`) — the parser change and the client change below
  MUST ship in the same build. They always do in this repo (zip + subsdk9 built
  from one tree), but do not split this across sessions. Absent field ⇒ empty
  string (wildcard), so old-shape messages stay valid.
- Note the per-chunk parser cap `kEntranceMapMax = 64` is UNRELATED to the
  512 table cap — chunks merge; don't touch it (client sends 48/chunk).
- `processEntranceRemap` (`EntranceShuffleHook.cpp`): pass the info's
  `mChangeStageId` into `lookupEntranceRemap`. No other hook changes.

### 3. Client/apworld: emit — `entrance_logic.py` + `client/protocol.py`
- `compile_stage_remaps`: exit rows gain `"from_id"` = the exit port's
  `entry_id` (available in schema-v2 `exits[]`; today's coupled model uses
  `primary_exit`, whose id is also present). Emit one exit row per exit port
  where the data supports it; keep behavior identical for coupled mode
  (all of a subarea's exits still target the same origin door → same
  `to_stage`/`to_id`, now with per-port keys instead of one wildcard row).
  If you keep emitting a single wildcard row for coupled mode instead, that's
  also acceptable — decide and document; do NOT mix both for one stage.
- `EntranceMapMsg` docstring + `ENTRANCE_MAP_CHUNK` sizing comment: re-check
  the 8 KiB line-cap math with the extra ~30 B/row field (48/chunk should
  still fit; shrink the chunk if not).
- ⚠ The client ships INSIDE the apworld zip — after client/apworld edits, run
  `python scripts/install_apworld.py` (Windows) before testing SMOClient.

### 4. Tests
- Host C++ (`switch-mod/tests/`, run via the smo-host-tests skill):
  `test_protocol` — from_id present / absent / unknown-field rejection;
  table-level tests for merge keying and the 3-tier lookup precedence if a
  seam exists (add one if cheap).
- pytest (`apworld/smo_archipelago/tests/`, run on Windows):
  `compile_stage_remaps` emits from_id, coupled-mode output otherwise
  unchanged (the existing 55-test suite must stay green **unmodified** unless
  a test literally asserts the old row shape — then update that assertion
  deliberately and say so).

### 5. In-game validation (Devon, one build)
Full loop: `sync` scripts NOT needed (no items/locations change);
`install_apworld.py` + switch-mod build/deploy per CLAUDE.md.
1. **Regression:** a normal coupled entrance_shuffle seed — walk doors, pipes,
   a multi-exit subarea, a moon pipe; everything must behave exactly as the
   2026-06-19 validated walk.
2. **Capability proof:** Push Block Peril's two exits routed to DIFFERENT
   destinations. Recommended vehicle: a small debug path that ships two
   hand-crafted compound-key exit rows through the REAL wire (e.g. a
   `/entrance-test` client command sending an `EntranceMapMsg`) — strictly
   better than hardcoding, since it exercises parse → apply → lookup. Keep it
   behind a debug flag or remove after.
3. **Also close P0's loose end:** the Row-2 return edge (Luncheon shop door →
   Push Block Peril) was never exercised in the P0 walk — fold it into this
   walk's route.

## Success criteria

Coupled shuffle regression-clean; PBP's two exits provably diverge in-game;
host + pytest suites green; `kEntranceRemapMax=512` landed with the comment
math updated. Then P3 (matching algorithm, Fable session) has its Switch
substrate done.

## Wrap-up
- Record the walk in `docs/devon-p2-compound-key-results.md`.
- Update the Phase 2 section of
  [plan-decoupled-entrances.md](plan-decoupled-entrances.md) with status +
  findings (and CLAUDE.md's P7 "Open follow-ups" line if this closes the
  from_parent deferral).
- Wire-format shapes are committed contracts — this phase EXTENDS them
  (additive field); flag anything that felt like more than additive in the
  wrap-up so Devon can review.
- Nothing here touches Nintendo IP (functional identifiers only), but audit
  `git status` before any commit.
