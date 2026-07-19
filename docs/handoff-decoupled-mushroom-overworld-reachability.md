# Handoff: decoupled — Mushroom overworld falsely reachable in sphere 1; no real route exists

> **RESOLVED 2026-07-17 — the diagnosis below was WRONG in one load-bearing way.**
> Decoupled matched pairs are TWO-WAY portals (walking into either mouth lands at
> the other's marker — `compile_port_remaps`, validated in-game by the P0 spike,
> the 2026-07-11 GabuzouClockEx walk, and Devon's own chain report), so this
> doc's "decoupled subarea exits pop back to the door of origin" ground-truth
> claim conflated COUPLED P7 behavior; origin-pop only happens when you exit
> through the mouth you entered by (whose partner IS your origin). The sphere-1
> MK moons were logic faithfully following real portal routes (Wintery Flower
> Road / Push Block Peril exits → MK doors). What WAS broken, and is now fixed
> (Devon rulings via AskUserQuestion — exit-portals are the route, early MK
> moons fine): (1) `port_matching.py` rooted PeachWorldHomeStage as
> flight-reachable, so no roll-time guarantee of a real MK route existed —
> `NON_ROOT_KINGDOMS` + the directed phase-1 rewrite now certify one every
> roll; (2) the undirected connectivity model missed full-interior deadlock
> pairs (real strands in probe seeds) — `directed_full_interior_strands` +
> directed frontier fix those; (3) the decoupled spoiler read as
> one-directional — it now carries a two-way-portal legend. Guard tests:
> `test_port_matching.py` (Mushroom erratum block) +
> `test_decoupled_region_wiring.py::test_mushroom_route_exists_without_game_clear`
> / `::test_arrival_inbound_edges_are_portal_or_flight_only`. Design record:
> [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md) §D10.
> STILL OWED: Devon's in-game walk of a portal into PeachWorldHomeStage
> pre-credits (D9's moon-spawn probe) — the one unvalidated link in the route.

**Recommended model: Fable 5 (Opus 4.8 acceptable).** This is region-graph correctness in
the Manual-derived generation layer, sitting directly on two prior subtle fixes (the
egress-gating quirk and the decoupled flight-economy fix) — the class of bug where a
shallow patch relocates the leak instead of closing it, and every bad seed costs Devon a
full playthrough to notice. Same reasoning tier as the flight-economy audit.

## Symptom + evidence

Devon completed his first decoupled seed (91455467025183402260) and **never arrived in
the Mushroom Kingdom overworld** — no shuffled entrance leads there. Yet the spoiler
placed ~16 MK OVERWORLD moons (several holding progression) in **sphere 1**. Victory
("Arrive in the Mushroom Kingdom" — the seed's goal) was correctly last (sphere 21).
Full extract with the entrance rows and sphere listings:
[logs/decoupled-seed-91455467025183402260-mushroom-evidence.md](logs/decoupled-seed-91455467025183402260-mushroom-evidence.md).

Ground truth in-game: the only shuffled connections into MK are five subarea
INTERIORS; decoupled subarea exits pop back to the door of origin (P7), so subarea
access never grants overworld access. Without a route, MK overworld requires beating
the game — "definitely shouldn't be in sphere 1" (Devon).

## Two deliverables

1. **Close the false-reachability leak**: MK overworld (and by extension ANY kingdom's
   overworld region) must not become logically reachable merely because one of its
   subarea interiors was reached via a shuffled door.
2. **Guarantee a real route** (Devon: "make sure it is reachable with our current
   system"): goal=Mushroom Kingdom under decoupled needs an actual in-game path to MK
   overworld, enforced at generation. Decide the mechanism WITH Devon (see below).

## Suspects for the leak (rank with evidence before fixing)

1. **Subarea → home-kingdom return edges surviving the decoupled rewrite.** Vanilla
   regions.json models a subarea as connected to its home kingdom; if the decoupled
   prep (hooks/World.py `_prepare_decoupled_entrance_shuffle`, `entrance_logic.py`
   `build_interior_requires_map` etc.) re-keys subarea INGRESS to the shuffled origin
   but leaves the vanilla EGRESS edge subarea→home-overworld intact, then reaching
   "8-Bit Bullet Bills" from Sand grants Mushroom overworld. Remember the engine
   quirk: `Rules.py::set_rules` applies a region's `requires` to its OUTGOING
   entrances ([handoff-region-gating-egress.md](handoff-region-gating-egress.md)) —
   an ungated subarea region gives its egress edges away for free.
2. **The flight-economy fix's exemptions.** `hooks/World.py::_apply_decoupled_flight_economy`
   ANDs `flight_reach` onto inter-kingdom flight edges but exempts Pokino + "K
   Arrival" edges ([handoff-decoupled-flight-economy-fix.md](handoff-decoupled-flight-economy-fix.md)).
   Check whether a "Mushroom Arrival → Mushroom" chain-presence edge (or the
   exemption) leaks the overworld independently of suspect 1. Note the victory
   location IS gated correctly (sphere 21) — find why the region's moons aren't
   behind the same wall; that asymmetry is diagnostic.
3. **Post-game kingdom modeling.** Mushroom is vanilla-post-game (fly-in only after
   credits). Whatever edge represents "beat the game → Mushroom" may be free or
   mispriced under decoupled. Also audit Dark/Darker, which share post-game status
   (and see [p7-entrance-shuffle-spike.md](p7-entrance-shuffle-spike.md) §6 on
   Moon's leave=win coupling before touching anything near it).

## The route question (AskUserQuestion with Devon before implementing #2)

Options, not mutually exclusive:
- **(a) MK tower shuffle provides the route.** Sibling feature
  ([handoff-mk-tower-shuffle.md](handoff-mk-tower-shuffle.md)) pools the 6 MK
  refight towers as shuffle destinations. If the boss-fight EXIT (post-victory
  return) vanilla-lands in MK overworld and stays un-remapped (P7 leaves
  boss/cutscene warps untouched), door→tower→painting→boss→MK-overworld becomes a
  real arrival route. Logic would then gate MK overworld on tower-chain
  reachability. Verify the vanilla return target before betting on this.
- **(b) Pool MK overworld arrival as an explicit shuffle destination** (a door that
  deposits Mario at a MK overworld spawn). Bigger switch-mod surface: overworld
  home stages as remap dest + spawn-marker validity (cf. the CapAppear softlock,
  [handoff-entrance-subarea-no-mario.md](handoff-entrance-subarea-no-mario.md)).
- **(c) Gate MK overworld moons + victory on game-clear** — logically sound but
  makes goal=Mushroom ≈ "beat the game," which likely defeats Devon's intent.

Whichever route is chosen, generation must ENFORCE it exists (a guard test in the
spirit of `test_randomize_kingdom_gates.py`'s reachability-sweep guard), and the
false-reachability fix must not strand the 5 MK subarea checks (they're correctly
reachable via their shuffled doors — keep them keyed on shuffled origin).

## Guardrails

- Generation layer only (expected). `Rules.py` `add_rule` not `set_rule` when
  stacking predicates (flight-economy precedent). Kill switch + slot_data shape:
  don't change wire contracts without flagging.
- Regen loop: edits do nothing until `install_apworld.py` (Windows) → `Generate.py`.
  The tell for a stale zip: unchanged generation output + old zip mtime (CLAUDE.md).
- File work via Read/Grep/Edit only (stale shell mount). pytest via repo `.venv`
  ([[pytest-must-use-repo-venv]]).
- Accessibility was Minimal in the evidence seed — 4 progression items were
  legitimately unreachable. Don't "fix" that; it's a settings choice. The bug is
  the opposite polarity (falsely reachable).

## Acceptance

- Regenerated decoupled seed (same options): NO MK overworld moon appears in any
  sphere before an actual in-game route exists; victory route is real and the
  playthrough's MK arrival is traceable through the entrance map.
- Guard test: decoupled generation fails (or re-rolls) if the goal kingdom's
  overworld has no in-game route; regression test pinning that subarea interiors
  don't grant home-overworld reachability in decoupled mode.
- Written note in docs/design-decoupled-kingdom-order.md (or successor) recording
  the chosen route mechanism and why.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (region-engine egress quirk, decoupled
> flight-economy fix, stale shell mount, install_apworld regen loop), then
> docs/handoff-decoupled-mushroom-overworld-reachability.md and its evidence
> extract, plus docs/handoff-decoupled-flight-economy-fix.md and
> docs/handoff-region-gating-egress.md. First reproduce the diagnosis in code:
> trace exactly which edge chain makes the Mushroom overworld region reachable in
> sphere 1 under decoupled, and explain why the victory location is gated but the
> region's moons aren't. Rank the handoff's three suspects with evidence. Then use
> AskUserQuestion to settle the route mechanism with Devon (tower-chain vs.
> explicit overworld destination vs. game-clear gate — coordinate with
> docs/handoff-mk-tower-shuffle.md), implement the leak fix + route guarantee +
> guard tests, and hand Devon the regen/verification steps. add_rule not set_rule;
> don't strand the five MK subarea checks.
