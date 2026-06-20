# Future feasibility — master index

This is the top-level index of "could we add X?" feasibility assessments for the
SMO Archipelago project. Each idea gets a **full detailed write-up in its own
`future-feasibility-<slug>.md`** doc; this file holds the one-paragraph summary
and a feasibility rating so a future session can triage at a glance without
re-reading every detail doc.

These are **reconnaissance, not committed plans**. A high rating means "looks
achievable with the effort noted," not "scheduled."

## Rating legend

- **Feasibility %** — rough odds the feature can be built as described without
  hitting a wall that kills it. Not a confidence interval; a gut estimate from
  the recon.
- **Effort** — relative build cost once started (low / medium / high).

## Summary table

| Idea | Detail doc | Feasibility | Effort |
|---|---|---|---|
| Strip Cappy's inter-kingdom flight commentary | [future-feasibility-strip-cappy-commentary.md](future-feasibility-strip-cappy-commentary.md) | **70%** | Medium |
| Free Lake/Wooded detour with a combined "both" gate | [future-feasibility-lake-wooded-free-detour.md](future-feasibility-lake-wooded-free-detour.md) | **80%** | Medium |
| Hide "needed to exit" thresholds as "?" until kingdom reached | [future-feasibility-hide-kingdom-gates-until-arrival.md](future-feasibility-hide-kingdom-gates-until-arrival.md) | **90%** | Low–Med |
| Moon recolor (by granted kingdom + AP class) + purple-coin model swap | [future-feasibility-moon-colors-and-coin-models.md](future-feasibility-moon-colors-and-coin-models.md) | recolor **95%** / coin models **~55%** | Small / High |
| Shopsanity (golden / purple / full) | [future-feasibility-shopsanity.md](future-feasibility-shopsanity.md) | **75%** | High |
| Decoupled / chained entrance randomizer (full any-to-any) | [future-feasibility-decoupled-entrance-randomizer.md](future-feasibility-decoupled-entrance-randomizer.md) | **65%** | Very High |

---

## Strip Cappy's inter-kingdom flight commentary

**70% · Medium effort.** Suppress the forced Cappy "discussion" sections during
Odyssey flights between kingdoms (the commentary you have to spam to skip);
skippable cutscenes stay. The target is **`exeDemoWorldComment()`**, an isolated
nerve state in `StageSceneStateWorldMap`, separate from the world-open/unlock/
select states — which is what makes it look suppressible without breaking the
arrival or world-reveal. It's spam-skippable in-game, so the clean approach is to
hook the state and invoke the game's own existing skip/finish path on entry
(follows our "trigger the existing exit, don't invent a nerve transition" rule).
The catch: **`StageSceneStateWorldMap.cpp` is NOT in OdysseyDecomp** (only the
header), so the gate and exit path must be read from a Ghidra/objdump pass on
`main.nso` rather than a quick decomp read — that's the bulk of the effort and the
reason it's not a slam-dunk. The post-game auto-disable hints a gate exists but
may route through entirely different code (free vs. story flight), so don't bank
on copying it. Full write-up:
[future-feasibility-strip-cappy-commentary.md](future-feasibility-strip-cappy-commentary.md).

---

## Free Lake/Wooded detour with a combined "both" gate

**80% · Medium effort.** Open up the first main-path detour so that after leaving
Sand you can fly the Odyssey **freely between Lake and Wooded** (either order, like
any earlier kingdom) instead of being forced Lake-first, while requiring the
**minimum moon counts from BOTH** before moving on past the detour (toward Cloud /
Lost). The forced order lives in two tiers and both need touching. The **apworld
logic** side is easy: rewrite the detour edges in `regions.json` so both kingdoms
hang off Sand and the onward edge requires `{KingdomMoons(Lake,8)} and
{KingdomMoons(Wooded,16)}` — `KingdomMoons` already returns composable
requires-strings and honors rolled gate values. The **switch-mod** side has two
parts: (1) free travel is likely a **one-rule deletion** in `KingdomOrderGate`'s
`kRules` (the [[kingdom-order-gate-premature-destinations]] memory shows the map
frontier is already wide open and only the BACKSTOP redirect forces Lake-first),
with the already-resolved `unlockWorld()` primitive as a proven fallback; and (2)
the in-game "both before Cloud" gate, the only genuinely new logic — `UnlockShineNum`
is single-kingdom so it can't natively express "need two other kingdoms," but a
guaranteed **logic-only fallback** works, and a true in-game gate reuses existing
per-kingdom counts (`ShineNumByWorldGetHook`/`ap_moons_kingdom`), existing rolled
thresholds (`kingdom_gate[]`), and the existing `KingdomOrderGate` chokepoint. The
points off are an unverified map-frontier assumption and needing to confirm which
warp path actually enters Cloud (cutscene vs. map pick) before wiring the full gate.
Scoped to Lake/Wooded only; the Snow/Seaside pair is structurally identical if wanted
later. Full write-up:
[future-feasibility-lake-wooded-free-detour.md](future-feasibility-lake-wooded-free-detour.md).

---

## Hide "needed to exit" thresholds as "?" until the kingdom is reached

**90% · Low–Medium effort.** In the SMO Client's Odyssey tab, show each kingdom's
"needed to exit" value as **"?"** until the player reaches that kingdom (preserving
the `randomize_kingdom_gates` surprise), then reveal it. The investigation surfaced
that the panel currently scrapes the **static vanilla** thresholds from regions.json
([datapackage.py](../../apworld/smo_archipelago/client/datapackage.py)), so with
randomized gates on it already shows the *wrong* numbers — this feature fixes that
too. Everything needed is already on the client except one signal: the **rolled
values** and the **randomize-on flag** both arrive via `slot_data["kingdom_gates"]`
and are stashed on the SwitchServer (`_kingdom_gates`), and per-kingdom moon counts
are tracked in state. The only gap is a clean **"reached the overworld of kingdom X"**
event — the client tracks no current stage/scene (the `StatusMsg` carrying
`stage_name` is received but discarded; the scene-change lines are free-text logs).
Two paths: **Option A** (low, zero Switch work) reveals on the first moon collected in
a kingdom — slightly later than literal arrival but guaranteed to work; **Option B**
(low–med) captures a true arrival signal, cheap if `StatusMsg` already fires on
overworld entry, otherwise a small Switch-side emit + rebuild. Recommended: plumb the
rolled values/flag to the GUI (fixes the wrong-number bug), ship Option A, optionally
upgrade to B. Full write-up:
[future-feasibility-hide-kingdom-gates-until-arrival.md](future-feasibility-hide-kingdom-gates-until-arrival.md).

---

## Moon recolor (by granted kingdom + AP classification) + purple-coin model swap

**Recolor ~95% (small) · Coin-model swap ~55% (high).** The updated form of the
original plan's **P5**, with two very different halves. **Recolor** tints each AP-check
moon by meaning: SMO moon items get the **granted moon's kingdom** color (color by the
moon it's *for*, not where it sits), and foreign-game items get green/yellow/grey/red
for progression/useful/junk/trap. This half is nearly done already — the whole
per-check tint pipeline ships (`ShineAppearanceHook.cpp` trampolines `Shine::init` and
tints by a per-location palette index from `ShineScoutsMsg`; the client already
classifies items and knows each item's kingdom via `maps.py`). It only needs the
palette tables extended (16 kingdom colors + yellow/grey added; useful→yellow,
junk→grey remapped) and the client emitting the kingdom index for own moons — exactly
the scoped P5. Keying on the *item's* kingdom even sidesteps the cross-kingdom-subarea
caveat the plan flagged. **Coin-model swap** (replace the moon model with a moon-sized,
recolored per-kingdom purple-coin model) is a different, deferred class of problem:
it's a 3D model/actor swap, the **Shine actor is undecompiled** (no `Shine.cpp` in
OdysseyDecomp — needs a `main.nso` disasm of `init`/`tryChangeCoin`/`exeCoin`), the
per-kingdom regional-coin model archives must be found via an **IP-sensitive romfs
hunt** on Devon's machine (incl. the unused Ruined model), and it carries real
unknowns (cutscene surface, archive memory/availability outside home kingdom). It has
real seams though — `Shine.h` exposes `hideAllModel()`/`getCurrentModel()` and SMO
already renders collected shines as coins internally (`exeCoin`), giving a couple of
candidate routes. Recommend shipping the recolor as P5 and treating the coin models as
a separate later spike, gated on two scope questions (true per-kingdom coin *shapes* vs.
a recolored generic coin; in-world-only vs. also the get-cutscene). Full write-up:
[future-feasibility-moon-colors-and-coin-models.md](future-feasibility-moon-colors-and-coin-models.md).

---

## Shopsanity (golden / purple / full)

**75% · High effort.** A `shopsanity` YAML option turning Crazy Cap shop slots into AP
checks: **golden** shuffles the gold-coin shop's outfits (skipping the Life-Up Heart +
already-shuffled Power Moon) as filler, **purple** shuffles each kingdom's regional
purple-coin outfits/stickers/trophies as filler (except 11 hat+outfit pairs that gate
specific moons — those stay as **useful** items with a logic rule on their moon), and
**full** does both; optional cost randomization. The decisive finding: the Switch-side
purchase detection — usually the make-or-break for shopsanity — is a **solved shape**
in SMO's *decompiled* [ClothUtil.h](../../switch-mod/lib/OdysseyHeaders/game/Util/ClothUtil.h):
`buyItem(ItemInfo*)`/`buyItemInShopItemList` are clean purchase chokepoints,
`isBuyItem`/`isHaveCloth` + the four catalogs (`getClothList`/`getCapList`/`getGiftList`/
`getStickerList`) give snapshot/replay, and `buyCloth` grants outfits on AP receipt;
`ShopLayoutInfo`'s `ItemType { Cloth, Cap, Gift, Sticker, UseItem, Moon }` tags slots.
The apworld already models the shop Power Moon as a location, so "shop slot = check" is
a known shape. What makes it high-effort is **breadth, not depth**: it spans a new
option + locations + items + logic, a new `CheckMsg` shop kind, a new gitignored
`shop_table.h` + extractor (the shine_table/capture_table analogue), a snapshot/replay
extension, and a grant path. Main risks: accurately enumerating shop slots and their
**progressive unlock timing** (the golden shop's catalog opens as you reach kingdoms —
`getWorldNumForNewReleaseShop` keys this; Devon will supply lists), the in-game gating
of the 11 outfit-moons so the useful-item gate isn't bypassed by simply buying the slot,
and the usual verify-`buyItem`-isn't-inlined. Recommend doing **purple first** (bounded,
self-contained, exercises the whole new tier), then golden (adds the unlock-timing
logic), with a `ClothUtil::buyItem` hook + `shop_table` extractor spike up front to
de-risk the identity mapping. Full write-up:
[future-feasibility-shopsanity.md](future-feasibility-shopsanity.md).

---

## Decoupled / chained entrance randomizer (full any-to-any)

**65% · Very High effort.** Evolve the shipped P7 coupled door→interior bijection into
a **full port randomizer**: a subarea's exit need not return to its origin overworld
(so leaving B can drop you into C, forming **chains**), traversal is **path-symmetric**
(A→B→C ⟹ C→B→A), and overworlds join the pool as endpoints (enter Poison Tides, wind up
in Luncheon). This is exactly the "full any-to-any" rework the existing P7 design and the
`entrance-from-parent-fix-deferred` memory both flagged as deferred. The right model is an
**undirected port matching (involution)** — and crucially, chaining + symmetry fall out of
it *for free*, and it's a cleaner model than today's directed bijection. The big
encouragement: the costly, already-validated Switch machinery **survives** — the
ChangeStageInfo "lie to the game" rewrite, the moon-rock guard, the chunked full-overwrite
wire table, and (because each exit port still maps to one destination) the **precomputed
return that sidesteps save/load origin tracking** all carry over; chaining adds rows, not
new mechanism. What must be rebuilt is heavy though: enumerate every port incl. overworld
door-mouths (re-run the extractor, split the conflated Costume Room / Sphynx Vault nodes), a
**connectivity-guaranteed matching** so a random involution doesn't strand regions, a
**general-graph reachability** model with asymmetric per-direction edge rules (forward = door
gate; reverse = reach-the-exit interior reqs), and a **compound exit key** on the Switch
(the already-scoped `from_parent` fix). Two real risks hold it at 65%: the **in-game unknown**
of landing in an overworld via a door/pipe rather than the Odyssey flight (strongly mitigated
by routing overworld arrivals through *existing* door-mouth exits — a known-good transition —
rather than a synthetic arrival), and the **kingdom-order collision** (Devon's "reduce the
early bottleneck" goal deliberately breaks the flight-order progression the order gate, peace
gates, and moon-pipe gating all assume). Recommend a one-build spike first — hand-author a
single exit→foreign-door-mouth row and confirm in-game that Mario lands in another kingdom's
overworld in a usable state; that binary result gates the whole feature. Full write-up:
[future-feasibility-decoupled-entrance-randomizer.md](future-feasibility-decoupled-entrance-randomizer.md).
