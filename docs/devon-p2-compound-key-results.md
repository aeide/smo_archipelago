# P2 results — compound-key entrance lookup (decoupled entrance rando)

**Status: CODE COMPLETE, host + pytest suites GREEN. In-game walk PENDING (Devon).**

Full work order: [handoff-decoupled-p2-compound-key.md](handoff-decoupled-p2-compound-key.md).
This doc covers what's been verified without a Switch build (sections 1-4) and
gives Devon the build/deploy/walk checklist for section 5.

## What changed (sections 1-4, all done)

1. **Switch table + lookup** (`switch-mod/src/ap/ApState.{hpp,cpp}`):
   `EntranceRemapSlot` gained `from_id` (exit-only compound key, empty =
   wildcard). `kEntranceRemapMax` 256 → 512 (the P1 decision). Merge key is
   now `(from, from_id, is_exit)`. `lookupEntranceRemap` gained a
   `transition_id` parameter and matches in 3 tiers: entry-by-dest, then
   exit-by-`(cur, id)` exact, then exit-by-`cur`-with-empty-`from_id`
   (wildcard/back-compat). Seqlock read pattern unchanged.
2. **Switch parser** (`switch-mod/src/ap/ApProtocol.{cpp,hpp}` +
   `EntranceShuffleHook.cpp`): `parseEntranceMap` accepts optional `"from_id"`
   (absent → empty/wildcard). `processEntranceRemap` now reads the transition's
   own id (`readCstrAt(info, kOffChangeStageIdCstr)`) and passes it through to
   `lookupEntranceRemap`. No other hook changed.
3. **Client/apworld emit** (`entrance_logic.py` + `client/protocol.py`):
   `compile_stage_remaps` emits **one exit row per physical exit port**
   (`entrance_stages.json` schema-v2 `exits[]`), each carrying that port's own
   `entry_id` as `from_id`, all still targeting the same origin door in
   today's coupled mode (so in-game behavior is unchanged — only the row
   shape gained a key). Falls back to the old single wildcard row when a
   subarea's `exits[]` can't be enumerated (missing data / pipe-less
   interior), never both for one stage. `EntranceMapMsg` docstring +
   `ENTRANCE_MAP_CHUNK` re-checked against the 8 KiB line cap — 48/chunk still
   fits comfortably with the extra field.
4. **§3.5 — `entrance_shuffle` Toggle → Choice** (`hooks/Options.py` +
   `hooks/World.py`): three values — `off`/`simple`/`decoupled` — with
   `alias_true = simple` / `alias_false = off` so existing boolean YAMLs are
   unaffected. `decoupled` raises `Options.OptionError` at
   `before_create_regions` (before any region/pool work) rather than silently
   behaving like `simple`. Both `is_option_enabled(..., "entrance_shuffle")`
   truthiness call sites in `World.py` (the roll site and the
   `after_set_rules` door/location-rule gate) now check
   `option_value == EntranceShuffle.option_simple` explicitly instead of
   `> 0`, since a `decoupled` seed would otherwise read as truthy too.
   `_wire_entrance_shuffle` and slot_data emission were already gated on
   `getattr(world, "_entrance_map", None)` (set only in `simple` mode), so
   they needed no change — audited, not touched.

## Tests

- **Host C++** (`switch-mod/tests/test_protocol.cpp`, smo-host-tests skill):
  5 new tests — entry row has empty `from_id`, exit row carries a present
  `from_id`, exit row without `from_id` parses as wildcard, unknown-field
  rejection, and two exit rows sharing `from` but different `from_id`
  (Push Block Peril's two ports). All pass, plus the 3 other host suites
  (json/cappy_messenger/msg_font_safe) unaffected. `test_shine_lookup`
  fails locally for an unrelated, pre-existing reason (stale/stub
  `shine_table.h` missing romfs-derived data — not touched by this work).
  ApState's table/lookup logic itself has **no host test** (documented,
  deliberate): `ApState.cpp` pulls `hk::` Switch-only headers
  (`CaptureGate.hpp`, `KingdomUnlock.hpp`, `hk::ro::RoUtil.h`, ...) that
  aren't host-linkable without heavy stubbing, and no prior ApState method
  has a host test either (same gap exists for `applyAbilityState` etc.) — the
  in-game walk is the verification path, per existing project convention.
- **pytest** (`apworld/smo_archipelago/tests/`): `test_entrance_shuffle.py`
  — 2 existing tests updated to assert the new per-port row shape (they
  literally asserted the old row count, per the handoff's escape hatch) +
  1 new test proving Push Block Peril's two exits get two distinct
  compound-keyed rows targeting the same origin. New file
  `test_entrance_shuffle_option_modes.py` (5 tests, `SMOAP_LIVE_AP=1`-gated,
  same pattern as `test_cascade_reachability.py`): option text/alias parsing,
  default is `off`, `decoupled` raises `OptionError`, `simple` still rolls a
  bijection. **56 + 5 = 61 tests, all green** (host + non-LIVE pytest + LIVE
  pytest, run against the freshly rebuilt zip).
  - Full non-LIVE suite: 707 passed, 74 skipped (69 pre-existing + 5 new
    LIVE-gated), 236 pre-existing environment errors (sandbox `AppData\Temp`
    permission denial, confirmed unrelated — same count before and after
    this work, isolated files are `test_setup_*`/`test_wizard_*`/
    `test_smoap_file`/`test_sync_capture_table`/`test_smoctx_reload_maps`,
    none of which touch anything this phase changed).
  - LIVE (`SMOAP_LIVE_AP=1`) suite against the rebuilt zip:
    `test_cascade_reachability.py`, `test_rearrival_reachability.py`,
    `test_entrance_shuffle_option_modes.py` all green.
  - `test_cap_peace_sphere0.py` fails (`off_full` reachability count 1/2
    instead of 2/2) — **confirmed pre-existing**, reproduces identically
    against unmodified `hooks/Options.py`/`hooks/World.py` (verified via a
    `git stash` round-trip on just those two files, unrelated to
    `entrance_shuffle` or anything else this phase touched). Not fixed here;
    flagging for a separate session.

## Wire-format note for Devon's review

`from_id` is a **pure additive field** on both `EntranceRemapEntry` (wire) and
`EntranceRemapSlot` (table) — old messages/rows still parse and match exactly
as before (empty `from_id` = wildcard). The one non-additive-feeling change is
the **merge/match key widening** from `(from, is_exit)` to
`(from, from_id, is_exit)`: a HELLO replay or multi-chunk update that used to
overwrite-in-place by `from` now appends a new slot per distinct `from_id`
instead of overwriting. This only matters if two different
`compile_stage_remaps` runs for the *same seed* ever produced a different
`from_id` set for the same `from` stage (they don't — the row set is a pure
function of the bijection + `entrance_stages.json`), so it's inert in
practice, but it's the one seam worth a second pair of eyes.

## Devon's checklist (section 5 of the handoff)

**Build + deploy** (no `sync_capture_table`/`sync_shine_table` needed — no
items/locations changed):

```powershell
cd E:\smo_archipelago
python scripts\install_apworld.py   # already run once this session; rerun if you pull more changes
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and
    ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual')
}).IPAddress
$LAN_IP   # eyeball it
python scripts\build_switchmod.py "-DBRIDGE_HOST=$LAN_IP"

$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
New-Item -ItemType Directory -Force "$RYU\exefs" | Out-Null
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\main.npdm "$RYU\exefs\main.npdm"
```

**Walk (fill results in below as you go):**

1. **Regression** — generate a normal `entrance_shuffle: simple` seed (or
   reuse an existing coupled-shuffle seed/YAML — `simple` is the new name for
   what `entrance_shuffle: true` already meant) and walk doors, pipes, a
   multi-exit subarea, and a moon pipe. Everything should behave exactly like
   the 2026-06-19 validated walk — this is the "did the compound key change
   break anything" check.
2. **Capability proof** — Push Block Peril's two exits routed to DIFFERENT
   destinations. The handoff recommends a debug path (e.g. an
   `/entrance-test` client command sending a hand-crafted `EntranceMapMsg`
   with two exit rows on `PushBlockExStage` — `from_id=PushBlockExStageEnt`
   → one destination, `from_id=PushBlockExStageEntDokan` → another) so the
   real parse→apply→lookup path is exercised, not just a hardcoded shortcut.
   Keep it behind a debug flag or strip it after.
3. **Close P0's loose end** — the Row-2 return edge (Luncheon shop door → Push
   Block Peril) was never exercised in the P0 walk; fold it into this route.

**Results (Devon, 2026-07-08):**

1. **Regression — PASSED.** Walked a normal `entrance_shuffle: simple` seed.
   Push Block Peril now exits Mario at the correct (shuffled) spot instead of
   the old P0-spike hardcoded PBP → Luncheon shop exit. Doors, pipes, and the
   multi-exit subarea all behave as expected; no regression from the
   compound-key change.
2. **Capability proof — DEFERRED to P3.** No seed generable today can produce
   two different destinations for PBP's two exits (coupled mode always
   targets one origin door for all of a subarea's exit ports — see the "Wire-
   format note" above), and no debug vehicle to hand-craft a divergent
   `EntranceMapMsg` was built this session. `(cur, id)`-exact matching remains
   **unverified in-game**; only the wildcard (back-compat) path has been
   walked. Revisit when P3's port involution actually needs divergent
   routing — build the hand-crafted-message debug path then, since it'll be
   exercised for real at that point instead of as a one-off proof.
3. **Row-2 return edge (Luncheon shop door → Push Block Peril) — DEFERRED**
   alongside #2, same reasoning (not exercised this walk).

**Net:** P2's back-compat path (wildcard exit rows, i.e. everything today's
`compile_stage_remaps` actually emits) is in-game validated. The new
`(cur, id)`-exact tier of `lookupEntranceRemap` is code-complete, host+pytest
tested, but **not yet exercised on real Switch hardware**. Fine to ship/build
on top of (P3), but flag this gap if P3 assumes the exact-match tier is
already proven.
