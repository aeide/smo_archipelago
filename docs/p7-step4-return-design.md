# P7 Step 4 — return / exit handling design

> Drafted 2026-06-19. Sequel to the forward-remap seam
> (`EntranceShuffleHook.cpp::processEntranceRemap`, `kEntranceRemapApply` gated OFF).
> Current state across both directions: `docs/logic-and-entrance-status.md` §2.

> **SHIPPED + LIVE 2026-06-19. `kEntranceRemapApply` is now `true`** (see
> `EntranceShuffleHook.cpp`); the apply-mode walk passed end-to-end. This design first
> landed as a read-only preview behind `kEntranceRemapApply=false`, then the gate was
> flipped after validation. (Banner corrected — earlier revisions of this doc said
> "still gated OFF".) The bidirectional table is wired end-to-end. What landed, mapped
> to the plan below:
> - **§1 PC** — `entrance_logic.compile_stage_remaps` emits paired `kind:"entry"` /
>   `kind:"exit"` rows, skips identity pairs; `switch_server.push_entrance_map` ships
>   them chunked; drift warning recomputed on entry-row count. (25 entrance tests green.)
> - **§2 wire/ApState** — `EntranceRemapEntry`/`EntranceRemapSlot` gained `is_exit`;
>   `parseEntranceMap` parses `"kind"`; `applyEntranceMap` merges by (from,is_exit);
>   `kEntranceRemapMax` 160→256; `lookupEntranceRemap` is now two-key (dest entry-first,
>   then cur exit).
> - **§3 hook** — `processEntranceRemap` passes both keys + the §5.1 same-stage
>   (dest==cur) moon-rock guard; preview logs `dest=` and `cur=` so the exit match is
>   observable.
> - **§4 validation** — pending Devon's morning in-game walk. **§5 edge cases 2–4 and
>   the nested-subarea entry-first behavior are UNVERIFIED — that's what the preview walk
>   checks before the gate is ever flipped.**
> The body below is the design rationale; it remains accurate.

## TL;DR — the big finding: **no runtime origin tracking is needed**

The handoff doc assumed Step 4 would need to *remember at runtime which door you walked
through* (an origin stack, persisted across save+quit in SaveLoadHook). For a **coupled
bijection** — which is what we ship — that is **unnecessary**. The return target is a pure
function of the shuffle permutation, so it can be **precomputed PC-side** and shipped as a
second set of remap rows, exactly like the entry rows. No per-session state, no SaveLoadHook
persistence, no origin stack.

Why: the shuffle σ is a permutation of subareas. If door-that-leads-to-`D` is rewritten to
land you in interior `I = σ(D)`, then "coupled" means leaving `I` must return you to door
`D`'s exterior. For any interior `I` there is exactly **one** `D = σ⁻¹(I)` (bijection), so the
exit target is deterministic — known at generation time. Runtime tracking only earns its keep
if entrances are **decoupled** (one-way) or an interior is reachable from **multiple shuffled
doors**; see the appendix for that case.

## Data we have (confirmed)

`data/entrance_stages.json` (134 subareas), per record:

```jsonc
"Poison Tides": {
  "kingdom": "Cap Kingdom",
  "stage": "PoisonWaveExStage",                 // the interior stage
  "parents": ["CapWorldHomeStage"],
  "primary_entry": { "parent": "CapWorldHomeStage",
                     "entry_id": "PoisonWaveExEnt",  "unit": "ChangeStageArea" },
  "primary_exit":  { "dest":   "CapWorldHomeStage",
                     "entry_id": "PoisonWaveExExit", "unit": "ChangeStageArea" },
  "entries": [...], "exits": [...]
}
```

- `primary_entry` = how you go **in**: the overworld parent + the entrance-id inside the
  interior. (Already used by the entry rows.)
- `primary_exit` = how you come **out**: `dest` = the overworld you land back in, `entry_id` =
  the spawn point **outside the door** in that overworld. **This is the return coordinate.**
- `unit` distinguishes a walk-through door (`ChangeStageArea`) from a pipe (`DokanStageChange`)
  — informational; we don't need it for the rewrite (we only change name+id, the transition
  animation belongs to the actor that fired it).

## The two transitions, keyed differently

For each shuffled pair `(D, I = σ(D))`, with vanilla `changeNextStage(dest, id)`:

| Direction | Fires when | Vanilla `(dest, id)` | `cur` stage | Rewrite to |
|---|---|---|---|---|
| **Entry** | you walk through the door that vanilla-leads-to `D` | `(D.stage, D.primary_entry.entry_id)` | `D`'s overworld | `(I.stage, I.primary_entry.entry_id)` |
| **Exit** | you leave interior `I` | `(I.primary_exit.dest, I.primary_exit.entry_id)` | **`I.stage`** | `(D.primary_exit.dest, D.primary_exit.entry_id)` |

Key insight on the **match key**:
- **Entry rows match on `dest`** (the inbound stage `D.stage` is a unique interior).
- **Exit rows must match on `cur` (`getCurrentStageName()` = `I.stage`)**, *not* on `dest` —
  because the exit `dest` is an overworld (`CapWorldHomeStage`) shared by every subarea in the
  kingdom, so it can't disambiguate which interior you're leaving. `cur = I.stage` is unique.

This asymmetry is the whole design. It also resolves **nested subareas** (an interior that
contains another door): a deeper door fires with `dest = deeper.stage`, which is an *entry*
key, so it's caught by the entry lookup first; the real exit fires with `dest =` an overworld
(not an entry key) and is caught by the cur-keyed exit lookup. **Lookup order: entry-by-`dest`
first, then exit-by-`cur`.**

## Implementation plan

### 1. PC side — generate exit rows (`entrance_logic.compile_stage_remaps`)

Extend the resolver to emit both directions. Add a `kind` discriminator so the Switch knows
which key to match:

```python
# entry row (unchanged shape + kind):
{"kind": "entry", "from": D.stage,
 "to_stage": I.stage,            "to_id": I.primary_entry.entry_id}
# exit row (new):
{"kind": "exit",  "from": I.stage,                       # matched against cur-stage
 "to_stage": D.primary_exit["dest"], "to_id": D.primary_exit["entry_id"]}
```

- Generate a pair of rows **per non-identity** `(D, I)` (skip `σ(D)==D`: both rows would be
  vanilla no-ops). ≤119 entry + ≤119 exit ≈ ≤238 rows.
- Skip a pair (and warn) if `I.primary_exit` or `D.primary_exit` is missing.
- Keep the existing chunked push (`ENTRANCE_MAP_CHUNK=48`, `reset=True` on the first chunk).
  238 rows → ≤5 chunks, each well under the 8 KiB line cap.

### 2. Wire + ApState — add `kind`/`is_exit` to the row

- `protocol.py EntranceMapMsg`: rows already a `list[dict]`; just include `"kind"`.
- `ApProtocol.{hpp,cpp}`: add `bool is_exit` to `EntranceRemapEntry`; parse `"kind"` ==
  `"exit"`.
- `ApState`: add `bool is_exit` to `EntranceRemapSlot`; **bump `kEntranceRemapMax` 160 → 256**
  (238 rows + headroom). Memory: 256 × ~200 B ≈ 50 KB in the singleton — fine.
- `lookupEntranceRemap` becomes two-key: `lookupEntranceRemap(dest_stage, cur_stage, out…)`.
  Single seqlock read; **prefer an `is_exit==false` row matching `dest`**, else an
  `is_exit==true` row matching `cur`. Fail-safe to "no remap" on torn/contended read
  (unchanged).

### 3. Hook — `processEntranceRemap` passes both keys

```cpp
const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
const char* cur  = currentStageName();
// guards: skip empty dest, skip moon-rock same-stage (dest == cur)
if (std::strcmp(dest, cur) == 0) return;            // (5) below
if (lookupEntranceRemap(dest, cur, to_stage, to_id)) { /* preview or rewrite */ }
```

The mutation body is unchanged (bounded both-fit-or-neither write of `mChangeStageName` +
`mChangeStageId`), still behind `kEntranceRemapApply`.

### 4. Validate read-only FIRST (recommended before flipping the gate)

Because exit rows ship in the same gated-OFF preview path, **one** build/deploy with
`kEntranceRemapApply=false` validates *both* directions:
- Walk through a shuffled door → expect `[entrance:remap-preview]` with the entry target.
- Leave the interior → expect a second `[entrance:remap-preview]` with the **return** target
  (`dest=` the origin door's overworld, `id=` the spawn outside that door).
If the exit line doesn't fire, or `cur` isn't `I.stage` at exit time, the cur-keying needs a
rethink — caught **before** any behavior change. (Consider logging `cur` in the preview line
so the exit match is observable.)

### 5. Edge cases to handle / watch

1. **Moon-rock reload** — same-stage transition (`dest == cur`); skip remap. The logger
   already prints `cur`, so the guard is observable.
2. **The boss re-fight / "no normal exit" subareas** (~6, per prior notes) — eject via a
   cutscene/warp, not a door-exit `:file`. Their exit may not fire a cur-keyed `:file` at all
   (fine — they just stay vanilla), or may fire an unexpected transition. **Validate via the
   read-only preview** before trusting them; do not hand-code assumptions.
3. **Multi-door subareas** — `primary_entry`/`primary_exit` canonicalize to ONE door. A
   subarea with two physical doors in two overworlds (see its `entries`/`exits` lists having
   >1 distinct `entry_id`) returns to the *primary* exit regardless of which door you used.
   For a per-subarea bijection that's correct (only the primary door is a pool slot); audit
   the `entries`/`exits` lists for any subarea with genuinely divergent secondary doors.
4. **Pipe vs door (`unit`)** — we only rewrite name+id, so the exit animation is whatever the
   interior's exit actor plays. Watch for a visual mismatch (walk out of a door but get a pipe
   warp); cosmetic, not blocking.
5. **`reset` ordering** — exit rows ride the same chunked stream; the first chunk's `reset`
   clears the whole table (entries + exits) before the merge. No change to chunking.

## Appendix — when runtime origin tracking WOULD be required

Only if we move off a coupled bijection:
- **Decoupled (one-way) entrances**, or
- **An interior reachable from multiple shuffled doors** (σ not injective on doors).

Then the exit target depends on *how you got in*, which is runtime state. Shape:
- On a successful **entry** rewrite, push the origin door's exit coordinate
  (`D.primary_exit.dest` + `entry_id`) onto a small `ApState` stack (depth ≈ nesting depth,
  e.g. 8). Use a stack, not a scalar, to handle nested subareas.
- On **exit** (cur-keyed `:file` whose `dest` is an overworld), pop the stack and rewrite to
  the popped coordinate instead of a static table row.
- **Persist the stack in SaveLoadHook** (it's live game state) — write on save, restore on
  load, clear on new-game. This is the SaveLoadHook work the coupled design avoids.
We are **not** building this now; it's documented so the static-table choice is a conscious
one, reversible if the shuffle model changes.
```
