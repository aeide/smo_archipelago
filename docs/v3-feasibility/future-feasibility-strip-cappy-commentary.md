# Future feasibility notes

Scratchpad for "could we do X?" investigations that haven't been started — so a
future session doesn't re-do the legwork. Each entry records what was found, the
estimated odds/effort, the cleanest approach identified, and the open unknowns.
These are NOT committed plans; they're pre-flight reconnaissance.

---

## Strip Cappy's inter-kingdom flight commentary (Devon, 2026-06-20)

**Goal.** Remove the Cappy "discussion" sections during Odyssey flights between
kingdoms — the commentary where Cappy talks about where you're going / game tips
that you have to spam to skip. Skippable cutscenes are fine to leave; only the
forced talk should stop firing. Note: these already auto-disable in post-game,
which hints a gate exists.

**Status: investigated, NOT started. Estimate ~70% feasible, medium effort.**

### What the system is

The flight commentary lives in **`StageSceneStateWorldMap`** (the world-map /
airship-travel state machine). Header `src/Scene/StageSceneStateWorldMap.h` in
OdysseyDecomp shows a sequence of separate demo states:

```
exeDemoPrep() -> exeDemoStart() -> exeDemoWorldOpen()
   -> exeDemoWorldUnlock() -> exeDemoWorldSelect() -> exeDemoWorldComment()
```

- **`exeDemoWorldComment()`** is the target — "Cappy comments on the world you're
  traveling to."
- Driven by member **`TalkMessage* mWorldMsg`** (other members of note:
  `ShineTowerRocket* mShineTowerRocket`, `al::SimpleLayoutAppearWaitEnd*
  mWorldSelectMovieLyt`, `al::KeyRepeatCtrl* mKeyRepeatCtrl`).

### The caveat that sets the difficulty

**Only the header is decompiled — there is NO `StageSceneStateWorldMap.cpp` in
OdysseyDecomp** (confirmed 2026-06-20: the `.cpp` 404s on GitHub; the `.h` is
3,009 bytes). So the body of `exeDemoWorldComment` and the exact post-game gate
live only in the raw binary. Reading the gate needs a **Ghidra/objdump pass on
`main.nso`**, not a decomp read. This is what makes it more work than the Peach
flag (a one-symbol write verified in minutes).

### Why it's promising

1. **State `exe*` functions are out-of-line nerve functions**, registered into a
   nerve table by address — so `exeDemoWorldComment` should be a real, hookable
   exported symbol (the reliable kind, not an inlined predicate). Verify the
   mangled symbol exists in `main.nso` dynsym before anything else.
2. **Comment is its own isolated state**, separate from
   `WorldOpen`/`WorldUnlock`/`WorldSelect` — strongly suggests it can be skipped
   without breaking the world-unlock reveal or the arrival.
3. **It's spam-skippable in-game** -> the game already has a sanctioned "end this
   message now" exit path. Cleanest implementation: hook `exeDemoWorldComment`
   and on entry invoke that same skip/finish path the button press uses, so the
   state self-exits through its NORMAL route. Follows our "trigger the existing
   exit, don't invent a new nerve transition" rule — avoids the guess-the-wrong-
   chokepoint cycle CLAUDE.md warns about.

### Open unknowns (why it's not a slam-dunk)

- **The post-game auto-disable may not be a single flippable flag.** Post-game
  might route world-map travel through a DIFFERENT code path (free flight vs.
  story flight) rather than a granular "skip comment" boolean. If so there's
  nothing to copy — suppress at the state instead. Don't bank on mimicking the
  post-game gate.
- **Confirm Comment carries nothing required** — that it doesn't advance a
  scenario or gate arrival timing — via the disasm read before committing.

### Concrete first step (when pursued)

Disasm read of `exeDemoWorldComment` + its caller/transition in `main.nso`:
1. Confirm `exeDemoWorldComment` is a clean out-of-line nerve symbol (dynsym).
2. Find how the existing spam-skip ends the state / `mWorldMsg`.
3. Confirm Comment is isolable (no scenario advance / arrival coupling).

No build/test cycle until the disasm confirms the chokepoint. The thing that
could sink it: Comment turning out entangled with the world-unlock reveal, or
post-game routing through entirely different code.

Sources consulted: OdysseyDecomp `src/Scene/StageSceneStateWorldMap.h`;
community confirmation of the post-game auto-disable behavior.
