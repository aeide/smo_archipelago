# P7 Step 4 — morning-session handoff (paste as the opening prompt)

> Written 2026-06-18 evening. Devon builds/deploys + walks in-game in the morning,
> then starts a fresh session with the captured `[entrance:remap-preview]` logs.

## TL;DR of where we are

The entrance-shuffle **bidirectional remap table is wired end-to-end, gated OFF**
(`EntranceShuffleHook.cpp::kEntranceRemapApply == false`). A build/deploy in this
state changes ZERO in-game behavior — it only emits `[entrance:remap-preview]`
log lines for BOTH directions (walking into a shuffled interior AND leaving it).
This morning's job: deploy, walk, capture the preview lines, confirm they match
the doors, THEN (separate session, with Devon's go-ahead) flip the gate to `true`.

Read, in order: `docs/p7-step4-return-design.md` (the why + the entry/exit keying
asymmetry — this is the load-bearing design), then this file, then CLAUDE.md's
switch-mod build/deploy loop + "Never commit Nintendo IP".

## What changed this session (all committed to the working tree, not yet git-committed)

PC side (apworld — already rebuilt into the zip via `install_apworld.py`):
- `apworld/smo_archipelago/entrance_logic.py::compile_stage_remaps` now emits paired
  rows tagged `kind:"entry"` / `kind:"exit"`, skipping identity pairs. Entry row keyed
  on the door's stage → interior's primary entrance; exit row keyed on the interior's
  stage → the origin door's `primary_exit` (dest + entry_id).
- `apworld/smo_archipelago/client/switch_server.py::push_entrance_map` ships those rows
  (chunked, reset on first chunk) and recomputes the drift warning on the entry-row count.
- `apworld/smo_archipelago/client/protocol.py` — `EntranceMapMsg` docstring documents `kind`.
- `apworld/smo_archipelago/tests/test_entrance_shuffle.py` — updated the 4 compile tests
  to the entry+exit semantics. **25/25 entrance tests pass.** (Full suite: 592 passed;
  the 236 errors are a pre-existing local `tmp_path` PermissionError in wizard tests,
  unrelated.)

Switch side (needs a build + deploy — Devon does this):
- `switch-mod/src/ap/ApProtocol.hpp` — `EntranceRemapEntry` gained `bool is_exit`.
- `switch-mod/src/ap/ApProtocol.cpp::parseEntranceMap` — parses `"kind"` (exit→is_exit).
- `switch-mod/src/ap/ApState.hpp` — `EntranceRemapSlot` gained `is_exit`; `kEntranceRemapMax`
  160→256; `lookupEntranceRemap` signature is now `(dest_stage, cur_stage, to_stage, to_id)`.
- `switch-mod/src/ap/ApState.cpp` — `applyEntranceMap` merges by (from,is_exit);
  `lookupEntranceRemap` is two-key: entry-by-dest first, then exit-by-cur.
- `switch-mod/src/hooks/EntranceShuffleHook.cpp::processEntranceRemap` — passes both keys,
  skips the moon-rock same-stage case (dest==cur), preview logs `dest=` + `cur=`.

## The build/deploy Devon runs in the morning (switch-mod tier)

```powershell
cd E:\smo_archipelago
python scripts\sync_capture_table.py
python scripts\sync_shine_table.py
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and
    ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual') }).IPAddress
$LAN_IP   # eyeball; pick the /24 matching the Switch if multiple
python scripts\build_switchmod.py -DBRIDGE_HOST=$LAN_IP
$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
New-Item -ItemType Directory -Force "$RYU\exefs" | Out-Null
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\main.npdm "$RYU\exefs\main.npdm"
```

The apworld zip is already rebuilt (this session). Generate a seed with entrance_shuffle
ON (it works now — the FileNotFoundError is fixed). An existing save file is fine for the
preview walk — gate is OFF so nothing is rewritten; we're only reading log lines.

## What to capture in-game (the validation that gates flipping the gate later)

For each transition, note **which door** (kingdom + plain description) next to the line(s).
Expect, on the bridge-connected Switch with the shuffle seed:

1. **Walk INTO a shuffled door** → one `[entrance:remap-preview] dest='<interior stage>'
   cur='<overworld>' -> stage='<shuffled interior>' id='<entrance>'`. Confirm the `dest`
   is the interior the door vanilla-leads-to and `stage`/`id` are the SHUFFLED target.
2. **LEAVE that interior** → a SECOND `[entrance:remap-preview]` with `cur='<the interior
   stage you're in>'`, `dest='<overworld>'`, rewriting to the ORIGIN door's overworld +
   spawn id. **This is the whole point** — it proves the exit row fires and `cur` is the
   interior at exit time (the cur-key the design depends on).
3. **Moon-rock reload** — should print NO remap-preview (the dest==cur guard skips it);
   the plain `[entrance:file]` logger still prints `stage==cur`.

### The questions to answer from the logs
- Does the exit line fire at all? If not, the interior's exit isn't a `:file` forward
  transition (some bosses warp out via cutscene) — those stay vanilla, note which.
- At exit time, is `cur` actually the interior's stage? If it's already the overworld,
  the cur-keying needs a rethink (design §5.2/§5.3).
- For **nested subareas** (a door inside an interior), the design's entry-first lookup
  intends the deeper door to match as an entry. Watch for any exit that unexpectedly
  matched an entry target (design §5 edge cases 2–4 are explicitly UNVERIFIED).

## After validation (DO NOT do tonight; needs Devon's explicit go-ahead)

Flip `kEntranceRemapApply` to `true` in `EntranceShuffleHook.cpp`, rebuild + deploy.
Then the rewrites go live: a shuffled door lands you in σ(door)'s interior and leaving
returns you to the origin door's exterior. Re-walk #1/#2 above and confirm
`[entrance:remap-APPLIED]` + that Mario actually arrives/returns correctly.

## Environment reminders
- File work via Read/Write/Edit/Grep (disk truth). Linux/Bash shell serves STALE/TRUNCATED
  bytes — never trust it for file contents.
- Builds / Generate / pytest on Windows PowerShell.
- A switch-mod change needs build_switchmod.py + copy subsdk9/main.npdm (NO per-mod
  subfolder); run sync_capture_table.py + sync_shine_table.py first. The apworld zip is
  independent and already rebuilt this session.
- Never commit: shine_map.json, capture_map.json, *_review.json, capture_table.h,
  shine_table.h, .romfs-cache/, raw Nintendo binaries, keys, or any >~5-entry name list.
  `entrance_stages.json` is IP-safe.
