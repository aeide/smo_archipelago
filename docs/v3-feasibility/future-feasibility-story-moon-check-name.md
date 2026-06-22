# Show the AP check name (+ owning player) in the story-moon cutscene (Devon, 2026-06-22)

**Goal.** Story moons play a little cutscene that shows where the moon is and its
name (the big underlined banner, e.g. *"Atop the Highest Tower (Sand)"* in the
attached screenshot). Devon wants the **AP check identity** added to that banner:

- If the check holds an item for **this** world → show **exactly what the check is**.
- If it holds an item for **another player's** world → show **what the check is *and*
  whose world it belongs to**.

Layout is flexible: on the same line as the moon name, **or** on a second line below
the underline in a smaller font if that fits the available width better.

> **Scope (Devon, 2026-06-22): this is the REVEAL cutscene, not COLLECTION.** The
> banner fires when a story moon *appears / is revealed* (the camera pan showing where
> it is) — **before** Mario touches it — not the get jingle when you collect it. That
> distinction is the whole difficulty: the at-collection banner is already AP-aware
> (see "Precedent" below), but the reveal banner is a different, **un-hooked** cutscene
> whose text must be delivered **pre-collection**.

**Status: investigated, NOT started. Estimate ~65% feasible, Medium effort.** The
*text rendering* is a solved problem in this codebase (the get-cutscene precedent
proves every rendering primitive), but the reveal path adds two genuinely new pieces:
finding/hooking the un-decompiled reveal scene state, and delivering the label
**before** collection (the existing text-delivery path is collection-triggered).

---

## Precedent — what we can reuse (the rendering is solved)

We do **not** start from zero: the project already substitutes a story-moon cutscene
banner with an AP-aware label at *collection* time — the **Channel A** pipeline, live
since M6. The reveal feature reuses its rendering + formatting primitives; only the
*trigger* and the *text delivery timing* are new.

- **The banner pane is already driven by us.** [MoonLabelHook.cpp](../../switch-mod/src/hooks/MoonLabelHook.cpp)
  trampolines the three moon-get demo states and writes the `TxtScenario` pane via
  `al::setPaneStringFormat(layout, "TxtScenario", "%s", text)`:
  - `StageSceneStateGetShine::exeDemoGet` (normal moon)
  - `StageSceneStateGetShineMain::exeDemoGetStart`
  - **`StageSceneStateGetShineGrand::exeDemoGetStart`** — the **grand / multi-moon
    get**, i.e. *the story-moon cutscene the request is about*.
- **The AP label is already composed, including the owning player.**
  [client/display.py](../../apworld/smo_archipelago/client/display.py)::`format_moon_label`
  produces `"Got <name>!"` when the item routes to me and `"Sent <name> to <slot>"`
  when it routes to another player — so "what the check is" + "whose world" is
  *already* the string the bridge ships.
- **The delivery path is already wired.** The Switch stamps an outbound `Check` with
  a `seq` ([ApFrameBridge.cpp:43](../../switch-mod/src/ap/ApFrameBridge.cpp#L37)),
  the bridge replies with a `MoonLabel` (text + seq + TTL), and the hook reads it
  during the cutscene via `tryTakePendingMoonLabel`.

So every **rendering primitive** the reveal banner needs is proven: substitute a
cutscene pane with `al::setPaneStringFormat`, compose "<item>" / "<item> for <player>"
text on the client, sanitize it for the stage-clear font. What the reveal path does
**not** inherit is the *trigger* (a different, un-hooked cutscene) and the *delivery
timing* (the text must exist before collection). Those are the two real gaps.

---

## The two real gaps (the reveal-specific work)

### Gap 1 — hook the REVEAL cutscene (an un-decompiled scene state)

The reveal banner is **not** one of the three hooked get states
(`StageSceneStateGetShine{,Main,Grand}`); those fire on collection. The reveal is a
separate cutscene played when the story moon spawns/appears (post-boss, post-objective
camera pan). **No hook for it exists yet**, and its scene state isn't in OdysseyDecomp
(the `StageScene*` demo-state family is in the undecompiled tree), so the target must
be located with a **symbol/decomp pass on `main.nso`** — the same "find the
undecompiled seam" caveat that holds the costume-door and Cappy docs below their
ceilings. Per CLAUDE.md's "read the decomp before picking a chokepoint" rule, the
state's structure must be confirmed before hooking.

Encouraging priors: (a) the parallel get states are simple `exeDemo*` nerve methods
that hook cleanly, so the reveal demo is very likely the same shape; (b) the reveal
already renders a name banner in vanilla, so it **already uses a layout + pane** we
can target with the proven `setPaneStringFormat` call — we're adding/replacing text on
an existing pane, not building UI from scratch.

### Gap 2 — deliver the label BEFORE collection (scout-text, not the collection reply)

This is the sharper gap. The existing `MoonLabel` text is delivered by a **collection**
round-trip: the Switch sends a `Check` stamped with `seq`
([ApFrameBridge.cpp:43](../../switch-mod/src/ap/ApFrameBridge.cpp#L37)) and the bridge
replies with the `MoonLabel`. That text **does not exist until you grab the moon** — so
it can't feed a banner that fires *before* collection.

The pre-collection source that *does* already enumerate every moon is the **scout
cache** — but it currently ships **color only**: `ShineScoutsMsg` entries are
`{shine_uid, palette}`
([switch_server.py:846](../../apworld/smo_archipelago/client/switch_server.py#L846),
[protocol.py:354](../../apworld/smo_archipelago/client/protocol.py#L354)), no text.
So the reveal path needs the scout push **extended to carry a per-uid label string**.
The bridge already knows each location's scouted item + recipient (it formats exactly
that for the get path), so it can emit the same "<item>" / "<item> for <player>" text
per `shine_uid`. On the Switch side, add a **by-uid label store** (resolve the
revealing Shine's `unique_id` the same way [ShineAppearanceHook.cpp](../../switch-mod/src/hooks/ShineAppearanceHook.cpp)
already does for recolor — it maps `Shine* → unique_id → per-uid fact` today) and look
the label up when the reveal cutscene fires. Mechanical and well-precedented (recolor
is the exact same "per-uid fact resolved at a Shine event" shape), but it's a real wire
extension: ~30 bytes × moon count, chunked like the existing scout send.

### Layout sub-point — augment vs. replace, and the byte budget

The screenshot keeps the vanilla moon name ("Atop the Highest Tower (Sand)") and adds
the AP info — same line, or smaller second line under the underline. So we **augment**,
not overwrite: write the AP caption to a **second pane** rather than clobbering the
name pane. Whether the reveal layout has a usable subtitle pane is part of the Gap-1
layout inspection (strong prior that name banners carry a sub/caption pane). If none
exists, fallbacks are a two-line single pane (cheap, possibly cramped — we don't
control its font scale) or, last resort, a layout-asset edit (avoided — ships modified
Nintendo content). The **30-byte budget**
([display.py:23](../../apworld/smo_archipelago/client/display.py#L23),
`char text[32]` in `PendingMoonLabel`) means "<item> for <LongPlayerName>" may need a
wider per-uid cap than the get path's 30 bytes — a one-line constant bump on both
sides, but a wire-contract touch (keep lock-step).

---

## What the change requires

1. **Symbol/layout spike** (the gating unknown): locate the reveal scene state on
   `main.nso`, confirm it's an `exeDemo*`-style hookable method, and inspect its
   layout for a second text pane. *Decides Gap 1 + the augment-vs-two-line question.*
2. **Client**: extend `ShineScoutsMsg` to carry a per-uid label; add a caption
   formatter (a `format_moon_label` variant that drops the "Got/Sent" verb → bare
   "<item>" / "<item> for <player>"); possibly raise the byte cap for this line.
3. **Switch**: add a by-uid pending-label store (mirror the recolor path's
   `Shine → unique_id → per-uid fact` resolve); hook the reveal scene state and write
   the AP caption to the second pane (leaving the vanilla name intact). Reuses
   `applyPendingLabel` + `sanitizeForMsgFont` wholesale. **Switch-mod + client +
   wire-struct change → needs an apworld rebuild; no re-seed** (cosmetic, no
   logic/fill impact).

---

## Risks / why ~65%

- **Un-decompiled reveal state (the main gap).** The trigger isn't in the decomp, so a
  `main.nso` pass is needed to find and confirm the hook point; residual chance the
  demo's text write is inlined or the state is awkward to hook. Mitigated by the get
  states being clean `exeDemo*` siblings and by the reveal already owning a name-banner
  layout.
- **Wire extension for pre-collection text.** Shipping per-uid label strings is more
  than a flag — a new/expanded scout field plus a by-uid store. Low *risk* (the recolor
  scout path is the exact precedent) but real *effort*.
- **Second-pane availability + byte budget.** If the reveal layout has no sub-pane, the
  fallback is a cramped two-line pane (we don't control font scale) or an avoided asset
  edit. A wider per-uid cap is a lock-step wire touch.
- **Font glyph coverage** — already solved: `sanitizeForMsgFont` + the hyphen
  truncation marker handle AP player names (the reconcile-label path already feeds
  player names through the same sanitizer).

---

## Recommendation / first step (when pursued)

1. **One-build symbol/layout spike, no behavior change:** find the reveal scene state
   via the `smo-symbol-discovery` pipeline, install a *logger-only* trampoline, and
   walk up to a story-moon reveal in-game to confirm it fires there (and is distinct
   from the get states); simultaneously dump its layout to find a sub-pane. That binary
   result — "clean reveal hook + usable pane: yes/no" — gates the whole feature.
2. If clean: extend the scout push with per-uid text + by-uid store, add the caption
   formatter, hook the reveal state, write the caption to the sub-pane. Verify:
   own-world reveal shows "<moon name>" + "<item>"; foreign shows "<moon name>" +
   "<item> for <player>"; long names truncate; non-ASCII player names sanitize.

**Why ~65%:** every *rendering* piece is proven (the get-cutscene precedent gives us
pane substitution, label composition incl. the owning player, and font sanitization
for free), and the pre-collection text source has an exact structural precedent in the
recolor scout path. The points off are two real unknowns rather than a wall: the reveal
cutscene is **un-decompiled** (needs a `main.nso` seam-finding pass, with a residual
inlining risk), and delivering the label **before** collection requires a scout-text
wire extension + a by-uid store rather than reusing the collection round-trip.

---

Sources consulted (disk-truth reads + decomp this session):
[MoonLabelHook.cpp](../../switch-mod/src/hooks/MoonLabelHook.cpp) (the `TxtScenario`
substitution + the 3 get states, incl. `GetShineGrand` = story/multi-moon),
[client/display.py](../../apworld/smo_archipelago/client/display.py)
(`format_moon_label` "Got X!" / "Sent X to Y", 30-byte cap),
[ApFrameBridge.cpp](../../switch-mod/src/ap/ApFrameBridge.cpp) (Check `seq` stamping),
[ApProtocol.hpp](../../switch-mod/src/ap/ApProtocol.hpp) (`MoonLabel` struct, 30-byte
note), [ApState.cpp](../../switch-mod/src/ap/ApState.cpp) /
[ApState.hpp](../../switch-mod/src/ap/ApState.hpp) (`PendingMoonLabel`, 32-byte cap),
[switch_server.py](../../apworld/smo_archipelago/client/switch_server.py) /
[protocol.py](../../apworld/smo_archipelago/client/protocol.py) (`ShineScoutsMsg` =
`{shine_uid, palette}`, color-only — the pre-collection text gap);
OdysseyDecomp tree (the `StageSceneStateGetShine*` family is in the undecompiled
`StageScene` tree — no appear/reveal scene state available to read).
