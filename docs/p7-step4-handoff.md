# P7 Step 4 — next-session handoff prompt

> **STATUS UPDATE 2026-06-19 — read this first; the body below is now historical.**
>
> The #1 problem this doc agonized over (subarea-name → stage/entrance translation,
> approaches A/B/C) is **RESOLVED**: translation lives in the **apworld at push time**
> (Design B+C). `data/entrance_stages.json` maps each subarea → `{stage, primary_entry,
> primary_exit}`; the client resolves the slot_data subarea bijection into stage-level
> **quads** `{from, to_stage, to_id}` (`entrance_logic.compile_stage_remaps`) and ships
> them chunked (`ENTRANCE_MAP_CHUNK=48`, first chunk `reset=True`) over `EntranceMapMsg`.
> The Switch only does a flat `from_stage → (to_stage, to_id)` lookup — never sees subarea
> names. All 119 pool doors resolve; a 48-entry chunk = 4145 B (< 8 KiB line cap). 50 tests
> green.
>
> **Plumbing DONE (Step 4 step 2):** `ApProtocol` parse (`parseEntranceMap`) → `ApState`
> seqlock table (`entrance_remap[160]`, `applyEntranceMap`/`lookupEntranceRemap`/
> `clearEntranceMap`) → `ApClient` dispatch → preview log in `EntranceShuffleHook`.
>
> **Forward-remap SEAM DONE (Step 4 step 3), COMPILE-TIME GATED OFF:**
> `EntranceShuffleHook.cpp::processEntranceRemap` rewrites `mChangeStageName` +
> `mChangeStageId` in place (bounded, both-fit-or-neither). Gate
> `kEntranceRemapApply=false` → ships as pure `[entrance:remap-preview]` log, **zero
> behavior change on deploy**. Flip to `true` + rebuild to enable the redirect.
>
> **THE LIVE GATE (unchanged, still needs an in-game answer):** the EXIT path. Devon's
> earlier walk showed `[entrance:return]` (`returnPrevStage`) **never fired** → exits are
> forward `:file` transitions to the interior's *vanilla* parent. So FORWARD-only remap
> sends you INTO the shuffled interior correctly but its exit dumps you in the WRONG
> overworld. Coupled return-to-origin (origin tracking + exit rewrite + SaveLoadHook
> persistence) is the next chunk — see §"Step 4 plan" steps 4 & 6 below. Enabling
> `kEntranceRemapApply` alone is valid only for a single-door "did I arrive?" smoke test.
>
> **Next decision for Devon:** (a) rebuild+deploy to confirm `[entrance:remap-preview]`
> lines match expected doors in-game, then (b) design the return/origin model before
> flipping the gate. Recommend (a) first — cheap confidence the table is correct end-to-end.

---

Paste this as the opening prompt next session. Step 3 (logger) is built + deployed;
Devon is collecting in-game logs in the interim.

---

## Read first, in order
1. `docs/p7-session-log.md` — running status. Step 3 ✅ built+deployed; the "Step 4
   decomp facts" block + the GATE checkbox are the live edges.
2. This file.
3. CLAUDE.md: "READ THE DECOMP BEFORE PICKING A HOOK CHOKEPOINT", switch-mod build &
   deploy loop, "Never commit Nintendo IP".

## What's already wired (don't re-derive)
- `hooks/EntranceShuffleHook.cpp` — LOGGER on `GameDataFunction::tryChangeNextStage
  (GameDataHolderWriter, const ChangeStageInfo*)`. Prints per call:
  `[entrance] tryChangeNextStage: stage='<mChangeStageName>' id='<mChangeStageId>'
  isReturn=N scenario=N cur='<getCurrentStageName>'`.
- Symbol HIT-verified in main.nso, in `SmoApSymbols.sym` + `HookSymbols.hpp`
  (`kGameDataFunctionTryChangeNextStage`). Field offsets in ChangeStageInfo: id@0x00,
  name@0x98, isReturn@0x1C8, scenario@0x1CC (FixedSafeString<0x80>=0x98 bytes, cstr@+0x08).
- apworld already emits `slot_data["entrance_map"] = {door_subarea: interior_subarea}`
  (DISPLAY NAMES). Client ships it as EntranceMapMsg, pushed on Connect + replayed on
  HELLO. Switch currently ignores it. ApState plumbing for it is NOT yet written.

## ⚠️ The #1 Step 4 problem: subarea-name → (stage, entrance) translation
`subareas.json` keys are display names ("Poison Tides") with only kingdom + csv_names +
location_names — **NO stage names**. The wire ships those display names. But the Switch's
remap must rewrite `ChangeStageInfo.mChangeStageName` (an SMO stage like
`WaterfallWorldHomeStage`) and probably `mChangeStageId` (the entrance/spawn id inside it).
So there is a missing translation layer. Before writing ANY remap code, decide where it
lives. Candidate approaches (evaluate next session):

- **(C) Auto-derive subarea→stage from existing moon data (preferred to investigate first).**
  Each subarea has `location_names` → locations.json/shine_table maps each moon to its
  (stage, obj_id). A subarea's moons live in the interior stage, so subarea→interior-stage
  falls out of data we already have on the Switch (`shine_table.h`) or can bake in the
  apworld. This kills most manual log collection. GAP: it gives the interior *stage* but not
  the *entrance/spawn id* (`mChangeStageId`) — and not the DOOR side's stage/entrance (the
  door is a transition object, not a moon). Those still need logs.
- **(B) Change the wire format** so the apworld emits stage names / entrance ids instead of
  display names. Only viable if the apworld can source them — it currently can't (no stage
  data in subareas.json). Could combine with (C): apworld derives stages from moon data and
  ships {door_stage: interior_stage(+entrance)}.
- **(A) Hand-built subarea→(stage,entrance) table on the Switch from logs.** ~119 subareas →
  a lot of walking. Last resort; use only for the door/entrance bits (C) can't supply.

Recommendation: spend the first part of next session correlating Devon's logs (below) with
`subareas.json` location_names + `shine_table.h` stages to see whether (C)/(B) can supply the
table cheaply. Don't write remap code until the translation source is decided.

## What I need from Devon's testing (the GATE)
For EACH transition, note **which door** (kingdom + plain description, e.g. "Cap Kingdom,
the door into the Underground Power Plant") next to the captured log line(s). The label↔log
correlation is what builds the translation table.

Walk and capture full `[entrance] ...` lines for:
1. **Normal door** — ENTER a building, then EXIT it. (a couple of different ones if easy)
2. **Moon pipe** — enter + exit.
3. **Painting warp** — the cross-kingdom paintings.
4. **Moon-rock reload** — does the line show `stage == cur`? (confirms the same-stage guard)
5. If convenient: a **kingdom-to-kingdom** Odyssey trip (to see what those look like vs. doors).

### The single most important answer — the EXIT path
When you EXIT an interior, one of these happens; tell me which:
- **(i)** An `[entrance]` line appears with `isReturn=1`, and `stage=` is the interior's
  HOME overworld (the kingdom the interior belongs to) — then Step 4 must override exits.
- **(ii)** NO `[entrance]` line appears on exit — exit uses the separate `returnPrevStage`
  path. In that case SMO's own prev-stage stack likely returns Mario to wherever he entered
  from (probably CORRECT for free, since we only rewrote the forward target), but we must
  verify it doesn't dump him in the interior's home kingdom.
This determines whether Step 4 needs a second hook on `returnPrevStage` /
`GameDataFile::returnPrevStage`, or no exit hook at all.

Also note: on a NORMAL entry, what `id=` (entrance name) does the game use? That's the
canonical spawn id we must set when remapping into that interior.

## Step 4 plan (after the gate clears)
Sequence, with the dependencies called out:

1. **Decide the translation source** (see #1 above). Blocks everything else.
2. **Plumb EntranceMapMsg → ApState** (mirror kingdom_gates): parse in `ApProtocol`, store
   under a seqlock in `ApState`, accessor on the frame side. This is independent of the
   gate answer and safe to write first. Store as whatever key the translation decision needs
   (stage names if we move translation to the apworld; display names + an on-Switch table if
   not).
3. **Entry remap** — on `!mIsReturn` (and NOT the moon-rock same-stage case), map the door's
   target → σ(door)'s interior; rewrite `mChangeStageName` (and `mChangeStageId` to the
   interior's canonical entrance) IN PLACE in the FixedSafeString buffer (copy bytes, don't
   swap the pointer — it points into the fixed buffer).
4. **Exit handling** — per the gate answer: (i) override in this hook / a returnPrevStage
   hook to send Mario to the ORIGIN door's kingdom; (ii) likely nothing, but verify. Origin
   tracking: persist origin-door per active subarea if (i).
5. **Moon-rock guard** — skip remap when `mChangeStageName == getCurrentStageName()` (the
   logger already prints `cur` so the guard condition is observable).
6. **SaveLoadHook** — persist origin-door across save+quit if (i) requires it.
7. Build + deploy + in-game verify. (`'-DBRIDGE_HOST=192.168.4.100'` — QUOTE it; PowerShell
   splits at the dots. Post-link python needs pyelftools/lz4/mmh3 — already installed.)

## Environment reminders
- File work via Read/Write/Edit/Grep (disk truth). Linux shell serves STALE/TRUNCATED bytes.
- Builds/Generate/pytest on Windows (PowerShell tool).
- switch-mod change → build_switchmod.py + copy subsdk9/main.npdm to Ryujinx; run
  sync_capture_table.py + sync_shine_table.py first. NOT install_apworld.py (unless apworld
  changed — and option (B)/(C) WOULD change the apworld, so rebuild the zip then).
- Never commit: shine_map.json, capture_map.json, *_review.json, capture_table.h,
  shine_table.h, .romfs-cache/, raw Nintendo binaries, keys, or any >~5-entry name list.
