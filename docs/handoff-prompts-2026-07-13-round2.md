# Handoff prompts — 2026-07-13 round 2 (post-fix playtest)

Three more issues from Devon's continued playtest, in Devon's priority order. Round-1
prompts live in `docs/handoff-prompts-2026-07-13.md`; those five fixes are implemented
and under test — do not regress them.

⚠ The log for Session 8 (`cap-purples-found-in-metro-subarea.txt`) did not upload —
Devon: drop it at `docs/testing-logs/2026-07-13/cap-purples-found-in-metro-subarea.txt`
before dispatching Session 8, or attach it to that session.

All three sessions are independent and can run in parallel.

---

## Session 6 (priority 1) — Odyssey gauge shows "full on moons" / hides the required moon count in chain-reached kingdoms

**Model: Fable 5** (the file itself documents two failed lever experiments; the crux is
discriminating a UI read from a gate read of the SAME out-of-line function — wrong
guesses cost full build+deploy+in-game cycles). Opus 4.8 fallback.

```
Read CLAUDE.md fully first (stale-shell-mount warning — Read/Grep tools only for file
contents; "READ THE DECOMP BEFORE PICKING A HOOK CHOKEPOINT" invariant; switch-mod
build loop).

REQUEST (playtest 2026-07-13): In every kingdom except Cascade, the in-Odyssey takeoff
gauge shows "full on moons" and never shows the required moon count — the true
threshold is only visible in the SMO Client tracker. Devon wants the Odyssey UI to show
the real required count (like vanilla does, and like Cascade already does) WITHOUT
undoing the chain-arrival takeoff/backtracking behavior.

This is a KNOWN, DOCUMENTED cosmetic trade-off — read
switch-mod/src/hooks/UnlockShineNumHook.cpp top-to-bottom before anything else. The
relevant design facts encoded there:
- The takeoff gate is `getPayShineNum(cur) >= findUnlockShineNum(cur)`. To open takeoff
  in free-detour kingdoms (Lake/Wooded/Snow/Seaside) and chain-reached-only kingdoms
  (chainAllowanceActive), the current-world findUnlockShineNum hook RETURNS 0 — the
  proven lever. Side effect: the in-kingdom takeoff gauge reads the SAME current-world
  value, so it renders 0/"full on moons". The world-map GLOBE label reads the by-world
  variant (findUnlockShineNumByWorldId, left at the rolled value) and is already
  correct.
- Two levers already tried and REJECTED (do not retry): forcing isUnlockedNextWorld
  true (never consulted at the takeoff seam — no log line ever fired), and zeroing
  Cascade's member worker (hid the gauge count — reverted; Cascade's escape now lives
  in EntranceShuffleHook::processCascadeOdysseyDivert, which is why Cascade displays
  correctly today).
- The member worker GameDataHolder::findUnlockShineNum is also hooked ([chain-launch],
  ~line 206+) with the same allowance-zero; the free wrappers are inlined into some
  callers — HookSymbols.hpp ~735-761 documents which symbol serves which seam.

Task: make the takeoff GAUGE (and any "full on moons" text seam) show the true
rolled gate while the takeoff GATE keeps reading 0 under an active allowance. Candidate
approaches, in the order I'd evaluate them:
1. Find where the gauge/"full on moons" UI actually gets its numbers. Read the decomp
   (https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/...) for
   the takeoff/globe layout code (MapLayout / StageMapSelect / the ShineTowerRocket
   launch UI) — if the UI reads through a DIFFERENT function or reads
   getPayShineNum/required separately for display, hook the display read and substitute
   the rolled value there. This is the clean fix.
2. If gauge and gate provably share the single out-of-line
   GameDataHolder::findUnlockShineNum read, discriminate by caller: capture the return
   address (LR) in the hook and zero ONLY the gate-side caller(s). Verify caller PCs
   are stable against the 1.0.0 build-id pin and document each PC the way
   ShopItemMessageHook documents its BL offsets.
3. If neither is tractable, fallback UX: leave the gauge honest (return the rolled
   value everywhere) and open the takeoff by patching the comparison/consumer seam
   itself — but ONLY with decomp evidence of where the comparison lives.

MUST NOT break (regression checklist to include for Devon's in-game pass):
- Free-detour crossings still open at 0 moons (Lake<->Wooded post-Sand, Snow<->Seaside
  post-Metro), and evaluateDetourExitGate still gates the combined exit.
- Chain-reached-only kingdoms still allow flying back out with the gate unpaid, and
  chain_allowance_bit stays coherent with WorldMapSelectHook's chain-return bounce
  (the hook comment says the launch check and the bounce consume the SAME read — if
  you split reads, keep them from disagreeing).
- Paying the gate still reverts everything to honest behavior.
- Cascade behavior unchanged (processCascadeOdysseyDivert untouched).
- Globe labels keep showing rolled values (findUnlockShineNumByWorldId untouched).

Switch-mod only. Deliverable: patch + causal explanation + exact build/deploy commands
(CLAUDE.md switch-mod section) + the regression checklist above as an in-game test
script.
```

---

## Session 7 (priority 2) — Show the 3 bonus captures on the Multi-Moon get screen

**Model: Sonnet 5** (client-side label composition with one wire-format constraint to
respect; small, well-mapped change).

```
Read CLAUDE.md fully first (stale-shell-mount warning — Read/Grep tools only;
wire-format fixed-buffer shapes are committed contracts — do NOT widen or rewrite
protocol structs).

REQUEST (playtest 2026-07-13): Collecting the Mushroom Kingdom Multi-Moon grants 3
bonus captures (this run: Paragoomba, Spark pylon, Volbonan). That works — the grants
land and the SMO Client tracker logs them — but Devon wants the capture names shown
in-game on the "Got Mushroom Kingdom Multi-Moon!" screen too. Same treatment for the
Dark Side Multi-Moon's 3 bonus abilities.

How the pieces work today (read in this order):
- docs/handoff-refight-multi-moons.md — the bundle feature design.
- apworld/smo_archipelago/client/context.py ~293-300 + ~1091-1096: mm_bonus_captures
  (18 ordered names, consumed in chunks of 3 per Nth Mushroom MM) and
  mm_bonus_abilities (3 names) arrive via slot_data.
- context.py ~664-695 (_process_received_items): where the Nth chunk is consumed and
  granted — this code KNOWS the 3 names at exactly the right moment.
- The moon-get screen text is the moon_label channel: client composes the label
  (client/display.py), pushes it over the wire, and
  switch-mod/src/hooks/MoonLabelHook.cpp applies it to the 'TxtScenario' pane (see
  docs/testing-logs/2026-07-13/lake-loaded.txt for live examples, e.g. "Got Seaside
  Power Moon!").
- There is also the Cappy speech-bubble channel (ui/CappyMessenger.cpp) already used
  for connect/status notifications — a candidate secondary surface.

Task:
1. When composing the moon label for a location whose scouted/received item is the
   Mushroom Kingdom Multi-Moon (or Dark Side MM), append the 3 bonus names, e.g.
   "Got Mushroom Kingdom Multi-Moon! +Paragoomba, Spark pylon, Volbonan".
   CONSTRAINTS: (a) the moon_label wire message has a fixed char[N] payload — find the
   actual size in client/protocol.py + switch-mod/src/ap/ApProtocol.hpp and TRUNCATE
   SAFELY (never widen the struct); (b) run the composed text through the same
   sanitize path as existing labels (MsgFontSafe / sanitizeForMsgFont parity — see
   ShopItemMessageHook's font note); (c) the label must still be correct when the MM
   is collected by ANOTHER player's world or when it's a repeat MM (chunk indexing by
   Nth arrival — reuse the exact indexing _process_received_items uses, do not
   re-derive it).
2. If the fixed buffer is too small for 3 names + base label, fall back to pushing the
   bonus names as a Cappy speech bubble immediately after the moon label (the bubble
   already queues text safely). State which surface you chose and why.
3. Timing check: the label is pushed on the check round-trip while the get-demo is on
   screen (see the [pump]/[moon_label] sequence in the logs — label arrives ~50ms
   after the check send). Confirm the bonus names are already known client-side at
   compose time (they are in slot_data from Connected — no extra round-trip needed).

Client/apworld only if the label fits the existing buffer — then the loop is: pytest
on Windows, `python scripts/install_apworld.py` (plain), no switch-mod rebuild. If you
end up touching MoonLabelHook/CappyMessenger, say so explicitly — that adds the
build_switchmod.py deploy loop. Add a unit test for the label composition (including
the truncation edge) in apworld/smo_archipelago/tests/.
```

---

## Session 8 (priority 3) — Purple coins in shuffled subareas credit the wrong kingdom

**Model: Opus 4.8** (switch-mod attribution fix requiring decomp reading of the
collect-coin path; contained once the seam is found).

```
Read CLAUDE.md fully first (stale-shell-mount warning — Read/Grep tools only; "READ THE
DECOMP BEFORE PICKING A HOOK CHOKEPOINT" invariant; switch-mod build loop).

BUG (playtest 2026-07-13): With entrance shuffle live, purple (regional) coins
collected in a subarea credit the kingdom the player ARRIVED FROM, not the kingdom the
subarea belongs to. Observed: entered a Metro Kingdom subarea via a shuffled entrance
from Cap Kingdom; the purples collected there were counted as CAP purples. Required:
purple coins always credit the subarea's HOME kingdom (Metro in this repro), regardless
of arrival path.

Log: docs/testing-logs/2026-07-13/cap-purples-found-in-metro-subarea.txt — if this
file is absent, ask Devon for it before theorizing.

Background you need:
- Vanilla never has this problem: a subarea is only ever entered from its own kingdom,
  so keying collect-coin counts off the "current world" is safe there. Our P7 entrance
  shuffle (switch-mod/src/hooks/EntranceShuffleHook.cpp) breaks that assumption —
  cross-kingdom subarea entry is routine.
- The P5 cross-world-load layer (switch-mod/src/game/CrossWorldLoad.{cpp,hpp}) swaps
  world RESOURCES to the destination kingdom, but the engine's notion of current world
  can lag/differ (see the resident vs engineCurWorld distinction in the p5-reswatch
  logging — and note round-1 Session 2 touched exactly this machinery; read
  docs/handoff-prompts-2026-07-13.md Session 2 and any fix it landed FIRST so you
  build on, not against, it).
- Kingdom name↔bit↔worldId tables live in switch-mod/src/game/KingdomUnlock.*.

Task:
1. Read the decomp for the purple-coin collect path
   (https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/... —
   start from the CollectCoin/CoinCollect actor and follow to the GameDataFunction/
   GameDataHolder call that increments the per-kingdom count; also find how the count
   is KEYED: by current worldId at collect time, or by something stage-derived).
   Confirm against the log which kingdom's counter actually moved.
2. Decide the correct attribution source: the subarea STAGE's home kingdom (derivable
   from the stage name via the same stage→world mapping the entrance/p5 code already
   uses — e.g. the stage_world used in '[p5-worldreq] request(plain) REDIRECTED'
   logging). Hook the increment seam (or its keying input) to credit that kingdom.
   Prefer a function called from many sites (stays out-of-line) per the CLAUDE.md
   inlining lesson.
3. Audit the READ side too: the shop purchase UI and the coin counter HUD read
   per-kingdom purple counts — make sure a Metro-credited purple collected while the
   engine thinks it's in Cap doesn't render as a phantom in Cap's HUD counter or break
   the shop's affordability check. State explicitly what the HUD shows mid-subarea
   after the fix.
4. Edge cases: subareas shared/reused across kingdoms (if any), moon-rock same-stage
   reloads (dest==cur guard), and purples collected BEFORE this fix on Devon's
   existing save (counts already banked wrong — is any migration needed or do we
   accept the historical drift? Ask Devon).

Switch-mod only. Deliverable: patch + decomp citations for the chosen seam + build/
deploy commands (CLAUDE.md switch-mod section) + in-game repro checklist (Cap →
shuffled entrance → Metro subarea → collect purples → confirm Metro counter increments
and Cap's does not, in both the HUD and a Metro shop).
```

---

## Model summary (round 2)

| Session | Issue | Model | Why |
|---|---|---|---|
| 6 | Odyssey gauge "full on moons" / hidden gate count | **Fable 5** | Must split a UI read from a gate read of the same function; two levers already failed |
| 7 | Bonus captures on MM get screen | **Sonnet 5** | Client-side label composition; one wire-buffer constraint |
| 8 | Subarea purples credit arrival kingdom | **Opus 4.8** | Decomp-driven attribution fix in the collect-coin seam |
