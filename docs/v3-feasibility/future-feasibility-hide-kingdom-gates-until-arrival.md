# Hide "needed to exit" thresholds as "?" until the kingdom is reached (Devon, 2026-06-20)

**Goal.** In the SMO Client's **Odyssey** tab, the "Moons by kingdom —
*earned / needed to exit*" panel currently prints a concrete exit threshold for
every kingdom. When the player's YAML sets `randomize_kingdom_gates: true`, those
thresholds are rolled per-seed and are meant to be a surprise. Devon wants to
preserve that surprise: show the "needed to exit" value as **"?"** until the player
has actually reached that kingdom's overworld, then reveal the number.

**Status: SHIPPED + CONFIRMED IN-GAME (Option B, 2026-06-21).** Both the wrong-number
fix and the faithful overworld-arrival reveal shipped, and Devon verified all three
behaviors in-game after the second-pass fixes below: (a) the current kingdom reveals
its rolled gate within ~0.5s of connecting (even before collecting a moon there),
(b) received-item kingdoms no longer falsely reveal, (c) the reveal survives a client
reconnect. Feature closed. Note the investigation's assumption that
`StatusMsg` was "already received, just thrown away" was wrong — `reportStatus` was a
no-op TODO stub, so the Switch never actually sent one. Option B therefore required a
real Switch emit (the medium path), built on the already-hooked
`EntranceShuffleHook::changeNextStage` commit:

- **Switch:** `ApFrameBridge::reportArrival(stage, kingdom_short)` pushes an
  `ApState::ArrivalEvent` (deduped per kingdom change via `last_arrival_kingdom`);
  `ApClient::pumpOnce` drains it into a real `StatusMsg`. The emit fires from
  `EntranceShuffleHook` after `processEntranceRemap` (so the dest read is the FINAL,
  post-shuffle stage), gated on `kingdomShortFromHomeStage(dest)` returning non-null.
- **Client:** the `t=="status"` branch now translates the kingdom (Switch→AP) and
  calls `BridgeState.mark_kingdom_reached`; `reached_kingdoms` rides the snapshot.
- **GUI:** `_format_odyssey` switches the threshold source to the rolled gates
  (`ctx.switch.get_kingdom_gates()`) when randomize is on, showing `?` until a kingdom
  is reached — where "reached" also backstops on any collected moon (Option A) so a
  mid-game reconnect still reveals visited kingdoms before the next stage change.

Requires a switch-mod rebuild + redeploy (the build_switchmod → Ryujinx loop). The
client/apworld side is pure Python (no apworld rebuild / re-seed needed). Original
investigation below.

**Post-ship bug fixes (2026-06-21, second pass).** Devon reported the panel still
showed the vanilla numbers, always. Three distinct causes were found and fixed:

1. **Stale installed zip.** SMOClient runs from the installed
   `vendor/Archipelago/custom_worlds/meatballs.apworld`, NOT the source tree — the
   zip predated the feature edits, so the running client lacked it entirely. Fix:
   `install_apworld.py` (the usual gotcha; the client tier needs the rebuild too).

2. **Backstop keyed on the wrong dict (client).** `_format_odyssey`'s reveal
   fallback OR-ed in `moons_received_by_kingdom`, which is keyed by the *received AP
   item's* kingdom (its identity), so receiving a Lake/Bowser moon item while
   standing in Cascade falsely revealed Lake/Bowser. Fixed to use only
   `moons_checked_by_kingdom` (keyed by the *physical location* collected). See
   [gui.py](../../apworld/smo_archipelago/client/gui.py) `reached` computation.

3. **Arrival `StatusMsg` never re-fired after a client reconnect (Switch).** The
   frame-thread dedup `last_arrival_kingdom` survives a client disconnect, but the
   PC client RESETS `reached_kingdoms` on every (re)connect — so a reconnect (or a
   client started after the in-game arrival) left the current kingdom hidden, since
   the next `changeNextStage` was deduped. Confirmed in Devon's log: one
   `[entrance:file]` (dest=Cascade) but zero `[pump] arrival status`. Fix: a
   per-frame `tickArrivalPoll()` ([EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp),
   driven by `drawMain`) re-derives the current kingdom and routes it through
   `reportArrival` (self-deduping); a new `ApState::arrival_resync` atomic, set by
   the socket worker on `hello_ack`, clears the dedup once per connect so the current
   kingdom re-emits without needing a stage change. Built + deployed 2026-06-21.

**Status (original): investigated, NOT started. Estimate ~90% feasible.** Low effort
for a "good-enough" version (reveal on first moon in the kingdom, zero Switch work);
low-to-medium for the faithful "reveal on overworld arrival" signal.

---

## Two things this investigation surfaced up front

### 1. The displayed number is currently WRONG when gates are randomized

The panel's thresholds come from `ctx.dp.kingdom_exit_thresholds()`
([gui.py:561](../../apworld/smo_archipelago/client/gui.py)), which is
`_parse_kingdom_exit_thresholds(regions_text)`
([datapackage.py:41](../../apworld/smo_archipelago/client/datapackage.py)) — it
regex-scrapes the **static `KingdomMoons(X, N)` literals out of regions.json**, i.e.
the *vanilla* thresholds (Cascade 5, Sand 16, Lake 8, Wooded 16, …). It does **not**
read the per-seed rolled values. So today, with `randomize_kingdom_gates: true`, the
tracker confidently shows the vanilla numbers, which are simply incorrect. This
feature therefore fixes a latent inaccuracy as well as adding the surprise — and it
means we should decide what to show *after* reveal (see "Reveal the real value" below).

### 2. The client already has the real rolled values

On AP Connected, `slot_data["kingdom_gates"]` (AP-form kingdom → rolled N) is read
and stashed: `SMOContext` calls `self.switch.set_kingdom_gates(...)`
([context.py:977-985](../../apworld/smo_archipelago/client/context.py)), which stores
them on the SwitchServer as `_kingdom_gates` + `_kingdom_gates_configured`
([switch_server.py:720-732](../../apworld/smo_archipelago/client/switch_server.py)).
So the client **knows whether randomize is on** (non-empty `kingdom_gates` /
`_kingdom_gates_configured`) and **knows the true per-kingdom values**. Both are
available to the GUI via `ctx`. No new wire data is needed for either.

---

## The one missing ingredient: a "reached this kingdom's overworld" signal

The GUI builds its rows in `_format_odyssey`
([gui.py:546-591](../../apworld/smo_archipelago/client/gui.py)) from a state snapshot.
The state mirror ([state.py](../../apworld/smo_archipelago/client/state.py)) tracks
per-kingdom **moons received / checked** and PayShineNum, plus the entrance map — but
it does **not** track the player's current stage/scene or a "visited kingdoms" set.

What the Switch sends about location:
- **`StatusMsg`** ([protocol.py:122](../../apworld/smo_archipelago/client/protocol.py))
  carries `kingdom` + `stage_name` — but it's sent "at the flag flip" (a scenario
  flag change), and the client currently **discards it**: the dispatcher's
  `t == "status"` branch only `log.debug`s it
  ([switch_server.py:1307-1308](../../apworld/smo_archipelago/client/switch_server.py)).
- **`HelloMsg`** carries no current-stage field.
- The "[entrance:file] stage='CapWorldHomeStage'" and "[cappy] scene changed" lines
  visible in the Odyssey log are **`log` messages** (forwarded free-text), surfaced
  for display only — not structured signals to act on.

So there is no clean structured "Mario is now standing in Lake's overworld" event in
client state today. That gap is the whole question; everything else is already wired.

### Option A — derive "reached" from existing per-kingdom moon data (low effort)

Treat a kingdom as "reached" once `moons_received_by_kingdom[k] > 0` **or**
`moons_checked_by_kingdom[k] > 0` (the latter is set by `_dispatch_check` on any
in-kingdom moon collect, and the HELLO snapshot back-fills owned shines per stage).
Reveal the threshold then; show "?" before.

- **Pros:** zero Switch-side work, no wire change, pure GUI + a tiny state read.
  Guaranteed to work with what's already there.
- **Con:** reveal fires on the player's **first moon in the kingdom**, which is
  slightly *after* setting foot in the overworld. A player who lands in Lake and
  stares at the gate count before grabbing a moon would still see "?" for a beat.
  Arguably fine (you've clearly "reached" Lake the moment you collect there), but it
  doesn't literally match "when you reach the overworld."

### Option B — a true overworld-arrival signal (low-to-medium effort)

Capture a structured arrival event and store a `reached_kingdoms` set in state.

- **Cheapest faithful path:** the `StatusMsg` already exists with `kingdom` +
  `stage_name` and is already received — it's just thrown away. If the Switch already
  emits a status (or a scene-change message) on overworld entry, the client change is
  small: in the `t == "status"` branch, map `stage_name`→kingdom and mark it reached;
  add `reached_kingdoms` to the snapshot; gate the GUI on it. **Verify when StatusMsg
  actually fires** — its comment says "flag flip," which may not coincide with plain
  overworld arrival.
- **If no arrival event fires today:** add a tiny Switch-side emit on overworld scene
  entry (a one-line `StatusMsg`/scene message from the scene-change point that already
  logs "[cappy] scene changed" / "stage='…HomeStage'"). That's a switch-mod change
  (rebuild + redeploy), bumping this to medium effort. Parsing the existing free-text
  log line client-side is possible but fragile — not recommended.

---

## Reveal the real value, not the vanilla one

Because the rolled values are already on the client (`_kingdom_gates`), the reveal
should show the **actual rolled threshold** for that kingdom, not the static
regions.json number. Recommended display logic per kingdom row, when
`randomize_kingdom_gates` is on:

- not reached → `?`
- reached → the rolled `_kingdom_gates[kingdom]` value

When randomize is **off**, keep today's behavior (static vanilla number, always
shown — it's correct and there's no surprise to protect).

Minor GUI detail: the column-width calc (`need_w`,
[gui.py:576-580](../../apworld/smo_archipelago/client/gui.py)) must count `"?"` as a
1-char value so the table stays aligned.

---

## Recommendation / first step

1. **Plumb the randomize flag + rolled values to the GUI** (already on `ctx` via the
   SwitchServer) and switch the threshold source from the static parse to the rolled
   table when randomize is on. This alone fixes the wrong-number bug.
2. **Ship Option A** for the reveal gate (first-moon-in-kingdom) — it's a few lines,
   no Switch rebuild, and is the safe baseline.
3. **Optionally upgrade to Option B** if Devon wants reveal exactly on overworld
   arrival: first check whether `StatusMsg` already fires on arrival (free); if not,
   add the small Switch-side emit (medium). Per CLAUDE.md, any Switch-side change
   needs the build_switchmod → Ryujinx redeploy loop.

**Why ~90%:** every prerequisite except the arrival signal is already in the client
(randomize flag, rolled values, per-kingdom moon counts), the GUI change is small and
localized, and there's a guaranteed zero-Switch-work fallback (Option A). The only
real variable is how faithfully we detect "reached the overworld," and even the
worst case is a small, well-understood Switch emit.

Sources consulted (disk-truth reads this session):
[gui.py](../../apworld/smo_archipelago/client/gui.py),
[datapackage.py](../../apworld/smo_archipelago/client/datapackage.py),
[state.py](../../apworld/smo_archipelago/client/state.py),
[protocol.py](../../apworld/smo_archipelago/client/protocol.py),
[switch_server.py](../../apworld/smo_archipelago/client/switch_server.py),
[context.py](../../apworld/smo_archipelago/client/context.py).
