# Handoff: on-screen ability list for the Dark Side multi-moon

## ✅ RESOLVED 2026-07-17 — the Cappy toast already existed; the fix was translation

**Correction to this doc's framing:** the Dark Side MM Cappy toast was NOT missing — it
already existed in `context.py` (built alongside the capture toast in the same prior
session, per `docs/handoff-refight-multi-moons.md`), gated identically to the Mushroom
branch (`if self.switch is not None: ... send_cappy(...)`). What it did wrong: it announced
the raw AP pool item names verbatim (e.g. `"Bonus abilities: Progressive Crouch, Wall
Slide, Climb"`), not the concrete moves those items unlock.

**Fix:** the Dark Side branch (`context.py::_process_received_items`, `elif ref.name ==
"Dark Side Multi-Moon"`) now builds a `granted_moves` list before sending the Cappy bubble:
for each bonus ability name, read `prior = state.abilities_received.get(ab, 0)` **before**
calling `grant_bonus_ability` (which mutates that dict in place), then
`newly_unlocked_move(ab, prior + 1)`. This is the exact same idiom the real ability
receipt's moon-label rewrite already uses (`context.py` ~line 1681) — not a new pattern.
A grant past the end of a chain (item already fully owned) returns `None` and falls back
to the raw item name, same as that existing call site.

Edge cases (offline / duplicate / festival) needed **no new code** — they already matched
the Mushroom capture branch's behavior because both branches share the same
`pos < initial_mirror_len` skip (duplicates), the same `if self.switch is not None` guard
(offline = silent state accrual, no toast), and festival drops the Dark Side MM item from
the pool entirely so the `elif` never matches. Documented explicitly in a new code comment
rather than left implicit.

Tests added to `tests/test_multi_moon_bonus.py`: three behavioral (translate a single-grant
item, translate mid-chain, fall back past chain-end) that replicate the context.py math
directly against `BridgeState` + `abilities.py` (no Archipelago dependency, matching the
suite's existing convention for this file), plus a source-parse test pinning the
prior-before-grant ordering and that the translated `granted_moves` (not the raw
`self.mm_bonus_abilities`) is what reaches `format_bonus_grant_cappy`.

**Devon, to verify:**
1. `.venv\Scripts\python -m pytest apworld\smo_archipelago\tests\test_multi_moon_bonus.py`
2. `python scripts\install_apworld.py` — client-only, no switch-mod rebuild, no
   `sync_shine_table`, no re-seed.
3. Restart SMOClient. In-game: collect the Dark Side multi-moon (or, if already collected
   this session, disconnect/reconnect SMOClient to re-trigger delivery against an unclaimed
   receipt) and watch for a Cappy bubble reading `Bonus abilities: <move>, <move>, <move>` —
   concrete move names (e.g. "Roll Boost", "Wall Slide"), not pool item names like
   "Progressive Crouch". If a rolled bonus ability happens to be one you'd already fully
   unlocked via the real pool, that entry falls back to the item name by design (no new
   move to report) — not a bug.

---

**Recommended model: Sonnet 5.** Pattern-clone task: the Mushroom-MM capture toast
already exists; this mirrors it for abilities. Haiku 4.5 is viable if budget matters
(the template is recent and clean), but Sonnet is the safe default because the ability
display-naming layer (`abilities.py` move translation) adds one judgment call.

## Goal (Devon, 2026-07-17)

When a Mushroom Kingdom multi-moon is collected, the game shows on-screen which 3
bonus captures were granted (built in a recent session). Apply the same treatment to
the **Dark Side multi-moon**: show which 3 bonus abilities were granted.

## Where to look

- Find the existing MK toast: grep `client/context.py` (and `switch_server.py` /
  the Cappy-message push path) for where the mm_bonus capture chunk grant triggers
  the on-screen message. The display surface is the Cappy speech bubble
  (`CappyMessenger` on the Switch side — already wire-supported; NO switch-mod
  changes needed).
- `mm_bonus_abilities` (3, from slot_data) are folded into the ability snapshot by
  `context._process_received_items` when the Dark Side MM arrives
  ([handoff-refight-multi-moons.md](handoff-refight-multi-moons.md), memory
  [[refight-multimoon-bundles]]). Hook the toast at that same point, mirroring the
  capture version's structure.

## Judgment call: naming

Bonus abilities are AP pool item names (e.g. progressive chains). The tracker
translates items→concrete moves via `client/abilities.py::moves_owned` ("Progressive
Crouch ×3" reads as "Crouch, Roll, Roll Boost"). For the toast, show what the player
actually gained: prefer the newly-unlocked MOVE name(s) given the player's
before/after ability counts, falling back to the item name if translation is
ambiguous. Match whatever convention the MK capture toast uses for tone/format.
Keep the message within Cappy-bubble-safe text (see `util/MsgFontSafe` expectations
client-side if any filtering exists — check how the capture toast sanitizes).

## Guardrails

- Client-only change; ships via `install_apworld.py` (plain, Windows). NO
  switch-mod rebuild, NO sync_shine_table.
- The abilities also land in the `ability_state` full-overwrite snapshot — the
  toast is presentation only; don't touch the snapshot logic. (If the sibling
  handoff-mm-bonus-capture-enforcement session found snapshot bugs, coordinate —
  don't fix them here.)
- Edge cases the MK version presumably handles — mirror them: Switch offline at
  MM arrival (toast on next connect? or skip — match MK behavior), duplicate MM
  arrivals, festival-goal seeds where the Dark Side MM may not exist.
- File work via Read/Grep/Edit only (stale shell mount); pytest on Windows.

## Acceptance

- Collecting the Dark Side MM shows the 3 granted abilities on screen, same look/
  path as the MK capture toast.
- Behavior on reconnect/duplicate matches the MK version's (documented in a
  comment either way).
- Test mirroring whatever coverage the MK toast has.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md (stale shell mount, install_apworld loop),
> then docs/handoff-darkside-mm-ability-toast.md and
> docs/handoff-refight-multi-moons.md. Locate the existing Mushroom-MM bonus
> capture toast in client/context.py (and its push path) and mirror it for the
> Dark Side MM's mm_bonus_abilities, translating item names to newly-unlocked
> move names via abilities.py where unambiguous. Client-only — no switch-mod
> changes. Match the MK toast's offline/duplicate edge-case behavior, add the
> mirrored test, and tell Devon the verification steps (install_apworld.py, then
> in-game: collect/re-receive the Dark Side MM and expect the 3-ability bubble).
