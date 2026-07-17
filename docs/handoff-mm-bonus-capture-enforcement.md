# Handoff: MM-bonus captures (Volbonan) not enforced on the Switch

## ✅ RESOLVED 2026-07-17 — root cause + fix (rest of this doc is the original brief)

**Root cause — suspect #2 was right, and the mechanism is worse than "a reconnect misses
them": EVERY save load drops them.**

1. `switch-mod/src/hooks/SaveLoadHook.cpp:123` does `st.captures_unlocked.reset()` and then
   `requestRehello()`. The Switch's capture bitset is **not durable state** — it is rebuilt
   from scratch out of the HELLO replay on every single save load.
2. `client/switch_server.py::_run_post_hello_replay` rebuilds it by walking
   `state.received_items` and re-sending one `ItemMsg` per **non-Moon** entry.
3. `client/state.py::grant_bonus_capture` deliberately does **not** append to
   `received_items` (a bonus is a side-effect of a Multi-Moon, not a real item). The
   Multi-Moon that triggered it *is* in the mirror — but it is `kind == "moon"`, so M6
   phase D skips it.

So a bonus capture had **exactly one** delivery to the Switch: the live `send_item` at
grant time (`context.py`). The next save load wiped it and the replay could not restore it,
because no store the replay consults knew it existed. `captures_unlocked` (what the GUI
tracker reads, `gui.py:558`) *did* know — hence Devon's tracker-correct / in-game-wrong
split. `!getitem Volbonan` fixed it permanently because a real AP Capture item lands in
`received_items` and is replayed on every HELLO forever after.

**`mm_bonus_abilities` does NOT share the gap** — confirmed, and it is the same asymmetry
read from the other side. `grant_bonus_ability` bumps `abilities_received`;
`push_ability_state` ships `get_ability_counts()` — a **derived full-overwrite snapshot** —
and `_run_post_hello_replay` calls it. Abilities replay from derived state; captures
replayed from raw item history, and only the latter can lose a synthetic grant. Pinned by
`test_hello_replay_ships_bonus_abilities_via_snapshot`.

**Fix (client/apworld tier only — no switch-mod rebuild):**
- `state.py` — new `bonus_captures: {cap: hack_name}` store, written by
  `grant_bonus_capture(cap, hack_name)`, read via `all_bonus_captures()`; reset in
  `clear_received()` (slot change rolls new picks).
- `switch_server.py` — new `push_bonus_captures()` (mirrors `push_capturesanity_replay`;
  `from_=""` so a save load doesn't re-announce all 18), called from
  `_run_post_hello_replay` right after `push_capturesanity_replay()`.
- `context.py` — passes the resolved `capture_map.cap_to_hack(cap)` into the grant.

**M6 phase D is untouched** — the fix re-derives captures; it never replays a Multi-Moon.
A source-parse test guards that the Moon-skip stays.

**Deterministic recomputation across a client restart** falls out of the existing path
rather than needing new code: a fresh process has `initial_mirror_len == 0`, so AP's
full-history replay marks every MM "new", the ordered chunks re-derive identically from
slot_data, and the store repopulates. AP sends `Connected` (slot_data, context.py:1116)
before `ReceivedItems` (context.py:1173), so the picks are always loaded first.

**No double-counted coins**: the replay only writes the wire — it never re-enters
`grant_bonus_capture` — so `captures_received_count` is untouched and
`compute_total_coin_grant` is stable across reconnects (pinned by a test).

**Devon, to deploy:** `pytest apworld/smo_archipelago/tests/test_multi_moon_bonus.py` (repo
`.venv` — bare pytest lacks pytest-asyncio, see [[pytest-must-use-repo-venv]]) then
`python scripts/install_apworld.py`. **No re-seed** (slot_data shape unchanged) and **no
switch-mod rebuild**. Restart SMOClient; the fix applies to an in-flight seed. Note an
already-granted bonus capture recovers on its own — AP replays the MM history to the fresh
client, which re-derives the store.

**Pre-existing wart noticed, NOT fixed (out of scope):** `clear_received()` resets
`captures_unlocked` but not `captures_received_count` / `abilities_received`, so a
slot change in a live client leaves stale counts that could mint spurious clone-coins.
Only reachable by swapping slots mid-session without restarting SMOClient.

---

**Recommended model: Opus 4.8.** The bug sits at the intersection of three committed
invariants: the post-HELLO replay that deliberately SKIPS Moon items (M6 phase D — and
Mushroom multi-moons ARE Moon-class), the ordered chunks-of-3 consumption of
`mm_bonus_captures`, and the capture-unlock wire/snapshot contract the Switch's
CaptureGate enforces. Getting the fix right without double-granting or breaking replay
ordering needs careful invariant reasoning; Sonnet could find it but is likelier to
patch a symptom.

## Symptom (Devon, 2026-07-17)

Volbonan was granted via a Mushroom Kingdom multi-moon bonus (the re-fight bundle
side-grant feature) and **shows as unlocked in the client's tracker** — but Volbonans
in-game still ejected Mario as if the capture was locked. `!getitem Volbonan` (a real
AP item grant) fixed it immediately.

That split is the key diagnostic: **client-side grant happened; Switch-side
enforcement never learned about it.** The normal capture-item path works; the
mm_bonus side-grant path diverges somewhere before or at the wire.

## Suspects (in likelihood order)

1. **Bonus grants never pushed to the Switch.** `context._process_received_items`
   consumes `mm_bonus_captures` in ordered chunks of 3 per same-named Mushroom MM
   ([handoff-refight-multi-moons.md](handoff-refight-multi-moons.md), memory
   [[refight-multimoon-bundles]]). Check whether that path calls the same
   capture-unlock push the normal item path does, or only mutates client state
   (which would explain tracker-correct/Switch-wrong exactly).
2. **HELLO replay omits them.** MM items are Moon-class → skipped in post-HELLO
   replay by design. If bonus captures are derived transiently at MM-arrival time
   and the HELLO-time captures snapshot is built only from real capture ITEMS,
   a reconnect (or Switch connecting after the MM arrived) never delivers them.
   Devon's session likely hit exactly this (MM collected, then a later HELLO).
3. **Name mapping.** Wire must carry what `capture_table.h` expects; CaptureGate
   matches `PlayerHackKeeper::getCurrentHackName()` against SMO-internal names.
   Less likely (normal path works for the same item name), but verify the bonus
   path feeds the identical string through the identical mapping
   (`maps.py`, `VARIANT_CAP_HACK_OVERRIDE`).

## Where to look

- `apworld/smo_archipelago/client/context.py` — `_process_received_items`, the
  mm_bonus chunk consumption, and whatever the NORMAL capture-item path calls to
  notify the Switch. Diff the two paths line by line.
- `apworld/smo_archipelago/client/switch_server.py` — HELLO replay + the
  captures snapshot construction.
- `apworld/smo_archipelago/client/state.py` — is `captures_unlocked` (the thing
  the GUI reads) also the thing the wire snapshot reads, or two stores?
- Tests: the refight-bundle tests referenced by handoff-refight-multi-moons.md;
  extend rather than duplicate.

## Fix shape (validate, don't assume)

Bonus-granted captures must be **first-class members of whatever store feeds both
the live capture-unlock push AND the HELLO-time snapshot**, and must persist across
reconnects (derive deterministically from received MMs + slot_data
`mm_bonus_captures` on every connection, not just at first arrival — the ordered
chunks are deterministic, so recomputation is safe and idempotent). Keep the M6
"skip Moon items in replay" invariant untouched — the fix belongs in the
captures-snapshot derivation, not in replaying MMs.

## Guardrails

- Client/apworld tier only (expected): fix ships via `install_apworld.py`; NO
  switch-mod rebuild unless investigation proves a CaptureGate-side gap (flag
  loudly — that would also need Devon's build+deploy loop).
- Don't break dupes→coins accounting (`compute_total_coin_grant`) — bonus dupes
  already fold into coins; recomputation must not double-count.
- File work via Read/Grep/Edit only (stale shell mount). pytest runs on Windows
  (source-tree tests are safe to run; note the shell caveat if running anything
  in the sandbox — prefer handing test runs to Devon).
- Check the same bug for the Dark Side MM's `mm_bonus_abilities` while in there —
  abilities ride the `ability_state` full-overwrite snapshot, which MAY already
  make them immune; confirm and note it (relevant to the sibling toast handoff).

## Acceptance

- Bonus-granted captures enforce on the Switch identically to item-granted ones:
  immediately on grant, after client restart, and after Switch reconnect/HELLO.
- Regression test covering the reconnect case (MM received while Switch offline →
  HELLO → snapshot contains bonus captures).
- Written confirmation of whether mm_bonus_abilities has the equivalent gap.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (stale shell mount, M6-phase-D
> Moon-replay-skip invariant, install_apworld loop), then
> docs/handoff-mm-bonus-capture-enforcement.md and
> docs/handoff-refight-multi-moons.md. Diff the normal capture-item unlock path
> against the mm_bonus_captures side-grant path in client/context.py and
> switch_server.py until you can state exactly where the Switch stops hearing
> about bonus grants — confirm the root cause in code before fixing. Implement
> the deterministic-recomputation fix shape from the handoff (or justify a better
> one), keep the Moon-replay-skip invariant intact, add the reconnect regression
> test, and confirm whether mm_bonus_abilities shares the gap. Use Read/Grep/Edit
> only; hand pytest + install_apworld runs to Devon on Windows.
