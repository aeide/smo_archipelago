# Handoff — P0 spike: cross-kingdom overworld landing (decoupled entrance rando)

**For a fresh session (Sonnet).** Read CLAUDE.md first — especially the
stale-shell warning (use Read/Write/Edit/Grep tools for ALL file work; never
trust shell `cat`/`grep`/`git diff` over file bytes) and the switch-mod
build/deploy block. Then read this doc top to bottom. You do NOT need to read
the full feasibility doc to do this task, but it's at
[v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md](v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md)
if context helps; the plan this task belongs to is
[plan-decoupled-entrances.md](plan-decoupled-entrances.md).

## Goal (one binary question)

If Mario exits a subarea and the transition is rewritten to a **different
kingdom's** existing door-mouth, does he land in that overworld in a **usable
state**? (Sane scenario, no softlock, save+reload survivable.) This gates the
entire decoupled-entrance-randomizer feature — a full any-to-any port shuffle
where subarea exits can chain into foreign kingdoms.

This is **approach A** from the feasibility doc: reuse a door transition SMO
already performs every time you leave that kingdom's subarea (a known-good
load), rather than synthesizing an Odyssey arrival.

## What to build (switch-mod ONLY — no apworld/client/seed changes)

Hardcode **two spike rows** in
[switch-mod/src/hooks/EntranceShuffleHook.cpp](../switch-mod/src/hooks/EntranceShuffleHook.cpp)
`processEntranceRemap`, checked BEFORE the `lookupEntranceRemap` table call
(the table will be empty anyway — no entrance_shuffle seed needed), behind a
single flag:

```cpp
static constexpr bool kP0DecoupledSpike = true;  // REMOVE after the spike
```

**Row 1 — the cross-kingdom exit (the actual test).** When leaving Push Block
Peril (cur == `PushBlockExStage`, Cap Kingdom — reachable at game start; its
exit pipes are PROVEN to fire `:file`, see the Step 3 header comment in the
hook file), rewrite the dest to Luncheon's shop door-mouth:

- match: `cur == "PushBlockExStage"` (and dest != cur — the existing guard
  already returns before the spike would run… note the guard sits ABOVE, so
  place the spike after `cur` is read and the dest==cur guard, before the
  table lookup)
- rewrite: `to_stage = "LavaWorldHomeStage"`, `to_id = "shop"`

(That coordinate is Crazy Cap Store (Luncheon)'s `primary_exit` —
`data/entrance_stages.json` — i.e. exactly where SMO puts Mario when he walks
out of the Luncheon shop. A known-good arrival point.)

**Row 2 — the return edge (makes it a true undirected port edge).** When
entering the Luncheon shop (inbound dest == `LavaWorldShopStage`), rewrite to
Push Block Peril's interior:

- match: `dest == "LavaWorldShopStage"`
- rewrite: `to_stage = "PushBlockExStage"`, `to_id = "PushBlockExStageEnt"`

Result: Push Block's exit pipe ↔ Luncheon's shop door become one symmetric
edge — exit the subarea, appear outside the Luncheon shop; walk into the shop
door, appear back inside Push Block Peril. Retrace works both ways.

**Reuse the existing bounded mutation body** (the `kFixedStringCap` /
both-fit-before-writing-either pattern already in `processEntranceRemap`) —
factor it into a small static helper or duplicate it; do NOT invent a new write
path. Log with a distinct prefix, e.g. `[entrance:p0-spike]`, echoing dest/cur
→ to_stage/to_id and the incoming `mScenarioNo`.

**Do NOT touch** `processDetourExitGate` / `processCascadeOdysseyDivert` /
the reportArrival block. Note: Luncheon IS a detour-exit kingdom, but the
detour gate only acts when the ORIGIN is a detour sibling's HomeStage; origin
here is `PushBlockExStage` (not a HomeStage → `kingdomShortFromHomeStage`
returns null → no-op). Confirm that in the logs rather than assuming.

No new hooks, no new symbols → the READ-THE-DECOMP rule isn't triggered.
Everything rides the existing `GameDataFile::changeNextStage` trampoline.

## Build + deploy

Follow CLAUDE.md's canonical PowerShell block ("Switch-mod build & deploy").
No `sync_capture_table`/`sync_shine_table` needed (no items/locations change);
no `install_apworld.py` (no apworld change). Remember to QUOTE
`"-DBRIDGE_HOST=$LAN_IP"`. Hand the deployed build to Devon for the walk — the
Linux sandbox cannot build this.

## Devon's in-game walk checklist

Back up the save file first (a chain-reached Luncheon at game start may strand
Mario — that's a possible FINDING, not an accident to lose a save to).
Suggested order, on a fresh-ish file that has Cap Kingdom accessible:

1. Enter Push Block Peril from Cap (vanilla door — unchanged, no entry row
   for it).
2. Exit via a pipe. Expect `[entrance:p0-spike]` in the log and a load into
   Luncheon at the shop door. **Record the `[entrance:file]` line's
   `scenario=` value.**
3. In Luncheon: walk around; is the kingdom in a sane layout? Which scenario
   (pre-peace lava state expected)? HUD/moon counter sane? Does `reportArrival`
   fire Luncheon on the tracker? Is the Odyssey absent (expected)? Can moons
   be collected and do checkpoints flag on the map?
4. Walk back into the shop door → expect Push Block Peril (Row 2). Exit again
   → Luncheon again (symmetry). Then retrace: shop door → Push Block →
   ...confirm the loop is stable.
5. **Save + quit + reload while standing in Luncheon.** Where does Mario
   spawn? What scenario? This is the #2 unknown after the landing itself.
6. Try to leave Luncheon by other means (checkpoint-warp within kingdom is
   fine; there's no Odyssey to board). Note anything that softlocks.
7. Watch for KingdomOrderGate / detour-gate log lines interfering (there
   should be none on a door transition — confirm).

## Success / failure criteria

- **PASS:** usable overworld state end-to-end, including step 5. Cosmetic
  oddities (no parked Odyssey, odd map cursor) are acceptable — note them for
  the Phase 5 fidelity pass (approach B).
- **FAIL:** crash, broken/void scenario state, save+reload strands or corrupts.
  A failure kills approach A specifically — record exactly WHICH step failed
  and the log lines, so a follow-up can evaluate approach B
  (demo-world-warp-seam arrival) before the feature is declared dead.

## Wrap-up (whichever way it goes)

1. Write results to `docs/devon-p0-decoupled-spike-results.md` (log excerpts +
   the checklist outcomes — same style as
   [devon-p7-entrance-testing-results.md](devon-p7-entrance-testing-results.md)).
2. Update the **Status** lines in
   [plan-decoupled-entrances.md](plan-decoupled-entrances.md) and the
   feasibility doc (revise the ~65% estimate).
3. Either remove the spike rows (flip/delete `kP0DecoupledSpike`) in the same
   session, or leave them flagged OFF with a comment pointing at the results
   doc — Devon's call. Do not ship a build with the spike ON beyond the test.
4. Nothing here touches Nintendo IP (stage/entry ids are functional
   identifiers), but run the usual `git status` audit before any commit.
