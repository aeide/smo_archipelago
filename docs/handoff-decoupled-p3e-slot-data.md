# Handoff — P3e: slot_data + client + Switch wire path for decoupled entrances

## ✅ STATUS: CODE COMPLETE (2026-07-08) — PORT_SHUFFLE_SHIPPABLE still False

All six work-order items below shipped; full results in
[plan-decoupled-entrances.md](plan-decoupled-entrances.md) §3e (§3c/§3d
style). Executive trail:

**Next session → P3f: work order written, see
[handoff-decoupled-p3f-mushroom-promotion.md](handoff-decoupled-p3f-mushroom-promotion.md)**
(Mushroom check promotion under decoupled, design D9). Its Step 0 flags a
data discrepancy in the design doc's "43 Mushroom checks" figure that needs
resolving before any code — see that doc. Devon's zone preview-walk +
`PORT_SHUFFLE_SHIPPABLE` flip checklist below is independent of P3f and can
happen in either order.

1. **Row compiler** — `port_graph.compile_port_remaps(matching, graph)`,
   next to `estimate_remap_rows` as suggested; `ROW_TABLE_CAP`/`ROW_HEADROOM`
   moved from `port_matching.py` into `port_graph.py` to avoid a circular
   import (port_matching re-exports both unchanged).
2. **slot_data + client plumbing** — new `slot_data["port_matching"]` key
   (mutually exclusive with `entrance_map`); `client/state.py` twin mirror;
   `SwitchServer.push_entrance_map` picks a compiler by whichever mirror is
   configured and ships the same chunked `entrance_map` wire message either
   way; `context.py` reads the new key on Connected.
3. **Switch ENTRY branch consults `from_id`** — `ApState::lookupEntranceRemap`
   gained the 4th tier (entry-exact → entry-wildcard → exit-exact →
   exit-wildcard). `ApProtocol.cpp`'s parser and the merge key needed NO
   changes (P2 already made `from_id` fully generic); only the lookup tiers
   were missing the entry-side check. Host-tested.
4. **Zone-split stage-key verification — PARTIALLY SETTLED, not fully
   proven.** `CostumeDoorHook.cpp`'s confirmed main.nso finding (the Lake
   town-zone trampoline is a SAME-STAGE `DoorWarp`, i.e. no real
   `changeNextStage` fires for it) is suggestive that placement zones share
   their parent HomeStage's `getCurrentStageName()` identity, but that's
   confirmed for exactly one door, not the ~6 other zone roots. Shipped a
   `ZONE_STAGE_ALIAS` data seam (empty) in `port_graph.py` instead of
   guessing — see plan doc §3e item 4 and Devon's checklist below.
5. **Spoiler block** — `_write_decoupled_spoiler`, mouth-pair keyed (a
   subarea can have independently-shuffled doors now), live-tested.
6. **Readiness flag — left `PORT_SHUFFLE_SHIPPABLE = False`, as instructed.**
   Devon's call; gated at minimum on the zone preview-walk (item 4).

**Tests:** `test_port_graph.py` +10 (pure `compile_port_remaps` unit tests:
row-count-matches-estimate, entry/exit row shapes, PBP-style divergent
routing, drop-both-ends on unresolvable mouths, sorted/deterministic, budget
RuntimeError, zone-alias seam, a 3-seed real-pool round trip).
`test_switch_server.py` +5 (mode-selection: coupled/decoupled/neither/both,
+ a pure `BridgeState` mirror round trip) — monkeypatch the two
`_compile_*_rows` seams rather than the real compilers, because those do a
lazy cross-package relative import (`from ..entrance_logic import ...`) that
only resolves when `client` is nested under the real `worlds.meatballs`
package (the installed-zip shape), not this suite's loose
`client`-as-top-level sys.path setup — pre-existing limitation, not new (the
coupled compiler was never unit-tested through `push_entrance_map` either).
`test_commands.py`'s `_StubSwitch` gained `set_port_matching`/
`port_matching_calls` (17 pre-existing Connected-handler tests were failing
before this — the stub didn't implement the new method context.py now always
calls). New file `test_p3e_port_matching_wire.py` (3 tests, SMOAP_LIVE_AP=1,
subprocess, `test_entrance_shuffle_option_modes.py`-style): slot_data key
exclusivity both directions, a REAL slot_data → `SwitchServer` →
`compile_port_remaps` round trip (proves entry rows carry real `from_id`,
not just the back-compat wildcard), decoupled spoiler block presence +
coupled block absence. **Full non-live suite: 999 passed / 94 skipped** (the
984/91 P3d baseline + 15 new non-live + 3 new live-gated, zero regressions).
Live re-run: `test_entrance_shuffle_option_modes.py`,
`test_decoupled_region_wiring.py`, `test_cascade_reachability.py`,
`test_rearrival_reachability.py`, `test_p3e_port_matching_wire.py` all green
against the reinstalled zip.

## Devon's checklist (before flipping PORT_SHUFFLE_SHIPPABLE)

**Not done this session (explicitly out of scope per the work order):** the
in-game walk itself, and the flip. Two things need your call:

1. **Zone preview-walk (settles item 4 above).** Rebuild + deploy with
   `kEntranceRemapApply` still `true` (unchanged — this doesn't need a
   preview-only build, just watch the existing `[entrance:remap-preview]` /
   `[entrance:*-APPLIED]` logs) is NOT enough here since no seed can ship a
   port matching yet (the option is still OptionError'd). Instead: flip
   `PORT_SHUFFLE_SHIPPABLE = True` LOCALLY (not committed), generate one
   `entrance_shuffle: decoupled` seed, and watch what `cur=`/`dest=` the
   `[entrance:file]` logger line reports when you walk through/out of a
   placement-zone-hosted door (Lake's town trampoline is the cheapest one to
   reach — Cap start → fly to Lake). If it reports the ZONE name
   (`LakeWorldTownZone`) rather than the parent (`LakeWorldHomeStage`), tell
   me and I'll populate `ZONE_STAGE_ALIAS` in `port_graph.py` — pure data,
   no rebuild needed on the apworld side beyond `install_apworld.py`. If it
   reports the parent, the seam can stay empty and this item is closed.
2. **Full build + deploy** (needed regardless, to exercise item 3's
   switch-mod change for the first time):

```powershell
cd E:\smo_archipelago
python scripts\install_apworld.py
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

3. **In-game walk (P4 territory, NOT done here per the scope guard — this is
   just the minimum smoke check to close out P3e's own switch-mod change):**
   with `PORT_SHUFFLE_SHIPPABLE` flipped locally and a decoupled seed
   generated+connected, confirm at least one shuffled door round-trips (walk
   in, confirm you land somewhere unexpected per the spoiler log; walk back
   out, confirm you return correctly) — this is the first-ever live exercise
   of the ENTRY tier's new `from_id` exact-match path (P2 shipped it
   code-complete but only ever validated the wildcard fallback in-game, per
   `docs/devon-p2-compound-key-results.md`). The full chain/multi-hop walk
   matrix is P4 scope, not this session's.
4. **Then, only after 1-3 look right:** flip `PORT_SHUFFLE_SHIPPABLE = True`
   in `hooks/World.py`, update `test_port_shuffle_readiness_flag_defaults_off`
   (retire or invert), the `EntranceShuffle` option docstring ("NOT YET
   IMPLEMENTED" → describe it), and the `OptionError` text/guard in
   `_raise_if_decoupled_entrance_shuffle`. I left all of these untouched —
   your sign-off, your commit.

---

**For a Claude Code session (Sonnet-tier per the plan doc — this is
pattern-following plumbing on existing seams, EXCEPT §3, a small switch-mod
lookup change that touches the frame-thread path: read the decomp/P2 notes
there, don't improvise) on Devon's Windows machine.** CLAUDE.md's stale-shell
warnings are Cowork-specific; you run pytest yourself. Canonical interpreter:
the repo venv `e:\smo_archipelago\.venv` (Python 3.12.10). If `tmp_path`
tests ERROR with PermissionError, use `--basetemp=<fresh dir>` (broken-ACL
dirs, see plan doc §3c Step-0). Live tests exercise the INSTALLED zip — run
`python scripts/install_apworld.py` after every apworld edit, before every
SMOAP_LIVE_AP run.

Context chain, in order:

1. [plan-decoupled-entrances.md](plan-decoupled-entrances.md) — P0–P3d done.
   §3d's design notes and §3c's three discoveries are load-bearing here,
   especially §3c discovery 3 (zone-split stage keys — YOUR verification item,
   see §4 below).
2. [handoff-decoupled-p3d-region-wiring.md](handoff-decoupled-p3d-region-wiring.md)
   — the ✅ STATUS section is the executive summary of what already exists.
3. [devon-p2-compound-key-results.md](devon-p2-compound-key-results.md) — the
   Switch row/lookup contract you are extending: `EntranceRemapSlot.from_id`,
   merge key `(from, from_id, is_exit)`, 3-tier lookup precedence
   (entry-by-dest → exit-by-(cur,id) exact → exit-by-cur wildcard).
   ⚠ P2's in-game walk is still PENDING — coordinate with Devon on whether it
   lands before or with your build.
4. `port_graph.py` + `port_matching.py` module docstrings (the mouth model +
   "Switch/remap note for P3e") and `entrance_logic.compile_stage_remaps`
   (the coupled row compiler you are writing the sibling of).
5. Client seams: `client/context.py` (~line 1028, slot_data consumption),
   `client/state.py` (`set_entrance_map` mirror), `client/switch_server.py`
   (`push_entrance_map`, plus the HELLO-replay call ~line 1237),
   `client/protocol.py` (`EntranceMapMsg` — a committed wire contract).

## The task

Ship the P3d port matching over the wire so a decoupled seed is physically
shuffled in-game, reusing the existing `entrance_map` WIRE MESSAGE (row shape
is already general enough) while adding a NEW slot_data key (never reuse
`entrance_map` — wrong-mode data for old clients, and coupled mode keeps it
for back-compat).

1. **Row compiler (apworld, pure — unit-testable without AP).**
   `compile_port_remaps(matching, graph) -> list[dict]` (suggested home:
   `port_graph.py` next to `estimate_remap_rows`, whose semantics it must
   match EXACTLY — one row per mouth whose assignment deviates from vanilla;
   assert `len(rows) == estimate_remap_rows(...)` in tests). For mouth A
   matched to B (arrival target = B.stage + B.entry_id, B's own marker):
   - A INTERIOR (an exit): `{"kind": "exit", "from": A.stage,
     "from_id": A.entry_id, "to_stage": B.stage, "to_id": B.entry_id}` —
     P2's compound exit key, exact-match tier.
   - A OVERWORLD (a door): `{"kind": "entry", "from": <A's vanilla
     partner's stage — i.e. A.subarea's interior stage, the inbound DEST the
     Switch matches entry rows on>, "from_id": A.entry_id, "to_stage":
     B.stage, "to_id": B.entry_id}`. The `from_id` on an ENTRY row is new —
     see §3.
   - Vanilla-assigned mouths (incl. the designated fixed point): NO row.
   - Emit deterministically sorted; budget-check `len(rows)` against
     `ROW_TABLE_CAP - ROW_HEADROOM` (the roller already asserted at gen time;
     re-assert at compile time so a client-side data drift is loud too).

2. **slot_data + client plumbing (follow the `entrance_map` /
   `mm_bonus_*` patterns).** `before_fill_slot_data`: ship the mouth-level
   matching under a new key (suggested: `"port_matching"`, a
   {mouth_id: mouth_id} dict) — NOT precompiled rows: the client owns row
   compilation (same division of labor as coupled, and the tracker/spoiler
   can introspect mouth ids). Client: `context.py` reads the new key on
   Connected → new `state.py` mirror fields alongside `entrance_map` →
   `push_entrance_map` compiles rows from WHICHEVER mode is configured
   (exactly one is ever present) and sends the same chunked `entrance_map`
   wire msg (reset=True first chunk, `ENTRANCE_MAP_CHUNK` unchanged — 289
   mouths ⇒ ≤288 rows ⇒ ~6 chunks, fine). HELLO replay path must re-push
   whichever mode is set. Client rebuilds the PortGraph via
   `build_port_graph` on its bundled data (pure, no rng) to resolve mouth ids
   → stages/markers; a mouth id in slot_data that the local graph can't
   resolve = data drift → log loudly, drop BOTH that pair's rows (the
   drop-both-ends rule), never one.

3. **Switch ENTRY branch consults `from_id`** (the flagged P2 seam,
   switch-mod). Today `lookupEntranceRemap`'s entry tier matches by dest
   alone; under a port matching, two doors of the SAME subarea point at
   DIFFERENT partners every seed, so entry rows sharing `from` (the shared
   interior dest stage) must disambiguate by the transition's own
   ChangeStageId. Extend the entry tier to prefer exact `(dest, id)` then
   fall back to empty-`from_id` wildcard — mirror the exit tiers'
   shape exactly (`ApState.cpp` lookup + `processEntranceRemap` already
   passes the id through since P2). Additive; coupled rows keep empty
   entry `from_id` and hit the wildcard tier unchanged. Host C++ tests where
   linkable (P2 note: ApState itself has no host tests — deliberate; cover
   the parser side + pytest the row emit instead).

4. **Zone-split stage-key verification (BLOCKING for correctness, cheap to
   check).** §3c discovery 3: zone-split rows key exit-side on the ZONE name
   (`LakeWorldTownZone`) or HomeStage depending on side. Confirm against
   `getCurrentStageName` semantics (does a zone-hosted door report the zone
   or the parent stage as `cur` at transition time?) BEFORE trusting compiled
   rows — ask Devon for a quick preview-mode log walk past a Lake town-zone
   door if the decomp/headers don't settle it. If cur reports the parent
   stage, zone-keyed EXIT rows need a stage-alias step in the compiler
   (data-side fix, not a Switch fix).

5. **Spoiler block.** `before_write_spoiler` keys off `_entrance_map` and is
   silent for decoupled — add a port-matching block (door-mouth → arrival,
   grouped per kingdom, moons listed per interior like the coupled block) so
   Devon can navigate test seeds.

6. **Readiness flip LAST, Devon-gated.** Everything above lands and tests
   green FIRST. Flipping `PORT_SHUFFLE_SHIPPABLE = True` opens the option to
   YAMLs — that is Devon's call, ideally after a P4-style preview-mode
   (`kEntranceRemapApply=false`) log walk confirms rows fire. When it flips:
   update the source-scan guard in `test_entrance_shuffle.py`
   (`test_port_shuffle_readiness_flag_defaults_off` asserts False — retire or
   invert it), the `EntranceShuffle` option docstring ("NOT YET IMPLEMENTED"),
   and the OptionError text/guard.

## Tests

Pure pytest (no AP): `compile_port_remaps` — row-per-deviating-mouth count ==
`estimate_remap_rows`, fixed points emit nothing, kinds/keys per side,
zone-split halves emit the stage keys decided in §4, determinism, budget
assert, unresolvable-mouth drops both ends. Live (SMOAP_LIVE_AP, subprocess,
flag flipped in-probe — copy `test_decoupled_region_wiring.py`'s prelude):
slot_data carries the new key and NOT `entrance_map` under decoupled (and
vice versa under simple); rows compiled from a generated slot_data round-trip
through the client mirror. Wire: extend the switch smoke/loopback path if
cheap (`scripts/switch_smoke_test.py` pattern) — otherwise host C++ parser
tests + Devon's in-game walk cover the Switch tier. Full suite must hold at
**984 passed / 91 skipped** + your new tests (zero regression in off/simple).

## Scope guard

3e only: no Mushroom junk exemption (3f), no in-game walk matrix (P4 — but
DO hand Devon the build + preview-walk checklist for §3/§4). Switch-mod
changes need the full build_switchmod.py → Ryujinx deploy loop (CLAUDE.md
canonical block; QUOTE the -DBRIDGE_HOST arg). The `entrance_map` wire msg
and `EntranceRemapSlot` are committed contracts — extend additively, never
rewrite. Update plan doc §3e with results + discoveries in the §3c/§3d style,
and update THIS handoff's status as you complete items. IP: none involved
(functional identifiers only); audit `git status` before commit — note P3b–3d
are also still uncommitted, so agree with Devon on the commit slicing.
