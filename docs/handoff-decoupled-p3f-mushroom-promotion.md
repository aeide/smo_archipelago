# Handoff — P3f: Mushroom check promotion under decoupled (design D9)

**STATUS: IMPLEMENTED (2026-07-08).** Step 0's "11-location gap" was a false
alarm — see the "Step 0 resolution" section inserted below, right after the
original Step 0 write-up (kept verbatim for the record). `_apply_junk_only_rules`
now has the decoupled exemption; `test_p3f_mushroom_promotion.py` covers it
(2 always-run + 3 `SMOAP_LIVE_AP`-gated). Full suite: 1001 passed / 97 skipped
(999/94 P3e baseline + 5 new), zero regressions, live probes green. Requires
backfill (`compile_moon_logic.py`) is still Devon's dependency — unblocked,
not started. See plan doc §3f for the full summary.

**For a Claude Code session on Devon's Windows machine.** CLAUDE.md's
stale-shell warnings are Cowork-specific; you run pytest/Generate yourself.
Canonical interpreter: the repo venv `e:\smo_archipelago\.venv` (Python
3.12.10). If `tmp_path` tests ERROR with PermissionError, use
`--basetemp=<fresh dir>` (broken-ACL dirs, see plan doc §3c Step-0).

Context chain, in order:

1. [plan-decoupled-entrances.md](plan-decoupled-entrances.md) §3f — the
   one-paragraph pointer to this doc, and §3e just above it (COMPLETE,
   2026-07-08) for the wire-path context this phase builds on.
2. [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md) D9
   — the signed-off design decision this phase implements. Read it in full;
   the summary below is not a substitute.
3. `hooks/World.py::_apply_junk_only_rules` — the function you are adding a
   decoupled exemption branch to.
4. `docs/handoff-decoupled-p3e-slot-data.md` — P3e's own STATUS section,
   specifically Devon's checklist at the top: **P3e's `PORT_SHUFFLE_SHIPPABLE`
   flip has NOT happened yet** (gated on Devon's zone preview-walk). D9 says
   Mushroom promotion applies "iff `entrance_shuffle == decoupled`" — that
   mode is still player-BLOCKED, so this phase's code lands and is
   test-exercised the same way P3d/P3e's was (flip the module flag inside
   tests only), not something a live seed can reach yet either.

## Step 0 — resolve a data discrepancy before writing any code

The design doc says "43 Mushroom checks" get promoted. **As of 2026-07-08
that number doesn't match current data** — verify current counts before
trusting anything below, the design doc may be stale:

- `data/locations.json` has **36** locations tagged both `junk_only: true`
  and `category: ["Mushroom Kingdom"]` (all currently `requires: ""`).
- `data/moon_requirements.json` has only **25** keys starting with
  `"Mushroom Kingdom:"` (all currently `requires: null`/unfilled — Devon's
  `compile_moon_logic.py` re-run mentioned in D9 has not happened yet).

That's an **11-location gap**: at least 11 of the 36 junk_only Mushroom
locations in `locations.json` have no corresponding entry in
`moon_requirements.json` at all, so `compile_moon_logic.py` (which fills
`requires` FROM that file) cannot backfill them no matter how many times
Devon re-runs it on the romfs machine. Before implementing the
`_apply_junk_only_rules` exemption:

1. Recompute both counts yourself (`locations.json` filter above,
   `moon_requirements.json` key-prefix filter above) — don't trust this
   doc's numbers either; more data-import work may have landed by the time
   you read this.
2. Diff the two sets by location name (`location_table` name vs
   `moon_requirements.json`'s `location_name` field) to find exactly which
   junk_only Mushroom locations are missing a requirements record.
3. Report the gap to Devon before proceeding — closing it is either (a) a
   CSV/xlsx import gap (`scripts/import_moon_requirements.py` — check if
   these 11ish are simply absent from Devon's source spreadsheet, in which
   case they need `requires: ""` treated as "no gate, free" rather than
   "not yet compiled" and D9's promotion is still safe for them), or (b) a
   genuine missing-data bug worth fixing at the source. **Do not silently
   promote a location with an unfilled `requires` to a full (non-junk-only)
   check** — an unfilled `requires` reads as "free" to the evaluator, which
   for a real gated moon would place progression items behind nothing.

## Step 0 resolution (2026-07-08 session)

The gap was **not real** — it was an artifact of diffing by key prefix
instead of the `location_name` field, exactly as this doc's own instructions
warned might be the case. Recomputed:

- `locations.json`: **36** locations tagged both `junk_only: true` and
  `category: ["Mushroom Kingdom"]` (unchanged from the original write-up).
- `moon_requirements.json`: diffing by the **`location_name` field** (not the
  dict key) against those 36 names — **36/36 matched, 0 missing**.
- The original doc's "25 keys starting with `Mushroom Kingdom:`" underc­ounted
  because 18 of the 43 total records whose `location_name` starts with
  `"Mushroom:"` use a **subarea-prefixed** CSV key instead (e.g. `"Peach's
  Castle: Light from the Ceiling"`, `"Castle Courtyard 64: Totally Classic!"`,
  `"Crazy Cap Store (Mushroom): Shopping Near Peach's Castle"`, the 6
  boss-refight keys like `"Knucklotec Boss Re-fight: ...: Rematch"`). Their
  `location_name` field correctly reads `"Mushroom: ..."` regardless of the
  key's own prefix.
- The 43-vs-36 delta is exactly **7 non-junk_only** Mushroom-category
  records: the 6 re-fight Multi-Moons (`multi_moon: true`, already full AP
  checks, never junk_only) plus 1 already-gated post-metro location
  (`"Mushroom: Secret Path to Peach's Castle!"`, already ships a real
  `requires` string). Both groups are correctly excluded from the junk_only
  set on their own terms — nothing to promote, nothing missing.
- Conclusion: **no CSV/xlsx import gap, no genuine missing data.** All 36
  junk_only Mushroom locations already have complete `moon_requirements.json`
  records (`capture_groups`/`methods` populated) — Devon's
  `compile_moon_logic.py` re-run can backfill every one of them with no
  further data-import work. Proceeded to implementation without a stop.
  Encoded as a regression guard:
  `test_mushroom_junk_only_locations_have_moon_requirements_record` in
  `test_p3f_mushroom_promotion.py` (always-run, no AP import needed).

## The task

Under `entrance_shuffle == decoupled` (module flag `PORT_SHUFFLE_SHIPPABLE`
flipped, same test-only technique P3d/P3e used), promote Mushroom Kingdom's
junk-only locations to full AP checks — eligible for progression/useful
items, not just filler/traps.

1. **Exemption in `_apply_junk_only_rules`** (`hooks/World.py`). Currently:

   ```python
   junk_only_names = {
       loc["name"] for loc in world.location_table
       if loc.get("junk_only", False)
   }
   ```

   Add a decoupled-mode filter that drops Mushroom-Kingdom-category names
   from `junk_only_names` (so `add_item_rule`'s filler/traps-only
   restriction never applies to them) when
   `_entrance_shuffle_mode(multiworld, player) ==
   EntranceShuffle.option_decoupled` (reuse the existing helper — see P2's
   note in `hooks/World.py` about why this must be the raw Choice value, not
   `is_option_enabled`'s truthiness check). Dark Side and Darker Side
   junk_only locations are **NOT** exempted (D5: their overworlds are
   excluded from the port pool, so decoupled chains never make them any
   more reachable than vanilla flight does — exempting them would place
   progression behind checks the player still can't freely reach).
   `locations.json`'s `junk_only: true` tag itself stays static — this is a
   generation-time rule override, not a data edit, so off/simple stay
   byte-identical (test this explicitly, mirroring P3d's "simple mode grows
   NO decoupled machinery" byte-identical guard).

2. **Requires backfill is Devon's dependency, not yours.** Once Step 0's gap
   is understood, Devon runs `compile_moon_logic.py` on his romfs-equipped
   machine (**NEVER without `shine_map.json`/`world_scenarios.json`
   present** — see CLAUDE.md's warning; an accidental run without them
   degrades to rock-only and wipes already-compiled gates on the other 562+
   moons). Compiled requires ship **unconditionally** (not gated on
   decoupled) — under off/simple those same requires just describe a
   post-goal junk location where a movement/ability gate is also
   semantically correct, so there's no harm shipping them everywhere. No
   `shine_table.h` resync needed (names don't change, only `requires`
   strings). You cannot do this step yourself without the romfs data; don't
   attempt to hand-author `requires` strings as a substitute — flag it as
   blocked-on-Devon in your session summary instead.

3. **Do NOT touch the pre-clear moon-spawn question.** D9 flags an in-game
   unknown: vanilla's painting-warp precedent proves pre-clear Mushroom
   LOADS safely, but vanilla never has moons placed there pre-clear (they
   spawn in the post-clear scenario). Whether a chain-reached pre-clear
   Mushroom actually spawns its moons/NPCs is a P4 walk-matrix question, not
   this phase's. The contingency IF the probe fails is the established
   scenario-floor pattern (`capArrivalScenarioOverride` /
   `CapReturnScenarioHook`-style: floor commits into `PeachWorldHomeStage`
   to the post-clear placement scenario, never lowering a higher one) — a
   switch-mod change that stays OUT of scope until Devon's probe demands it.
   Do not speculatively build it.

## Tests

Mirror the existing `_apply_junk_only_rules` / entrance-shuffle test style
(`test_entrance_shuffle.py`, `test_p3e_port_matching_wire.py`'s
`PORT_SHUFFLE_SHIPPABLE` flip technique where a live probe is needed):

- Pure/non-live: a Mushroom junk_only location's item rule under decoupled
  (flag flipped) accepts an advancement item; under simple/off it still
  rejects one (regression). Dark Side junk_only locations reject advancement
  items under ALL three modes (the D5 non-exemption).
- Live (SMOAP_LIVE_AP-gated, subprocess, same prelude as
  `test_p3e_port_matching_wire.py`): a decoupled multiworld generates
  without a FillError with the promoted Mushroom checks in play; simple/off
  multiworlds are byte-identical to before this phase (full-suite regression
  is the real gate, but a targeted determinism/no-machinery-growth check is
  cheap insurance, same shape as P3d's).
- Full suite must hold at **999 passed / 94 skipped** (the P3e baseline)
  plus your new tests, zero regressions.

## Scope guard

3f only: no P4 in-game walk matrix, no scenario-floor switch-mod change (D9
explicitly defers it), no `PORT_SHUFFLE_SHIPPABLE` flip (still Devon-gated,
still pending the P3e zone preview-walk — see the P3e handoff's checklist).
If Step 0's data gap turns out to need a source-data fix beyond a simple
`import_moon_requirements.py` re-run, stop and report to Devon rather than
improvising a workaround. Update plan doc §3f with results in the §3c/§3d/§3e
style, and update THIS handoff's status as you complete items. IP: none
involved (functional identifiers + Devon's own xlsx-derived requirements
data only); audit `git status` before commit — note P3b–3e are also likely
still uncommitted, so agree with Devon on the commit slicing before touching
git.
