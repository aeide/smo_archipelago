# Handoff — YAML option: start at Cap-Kingdom peace (Cap peace in sphere-0 logic)

**Created 2026-06-28.** Opened up by the now-complete *save-relocate* work:
we have a real save that loads into **post-peace Cap Kingdom, Odyssey landed, 0 moons**
(see [v3-feasibility/future-feasibility-save-relocate-to-peace-kingdom.md](v3-feasibility/future-feasibility-save-relocate-to-peace-kingdom.md)
§"How it was actually done"). This handoff is the **next task**: expose a YAML option
so a seed can be generated whose **sphere-0 logic assumes the player starts at Cap
peace** (Cap's peace/re-arrival moons reachable immediately), for players who launch
from that save.

It **must** be an option (default OFF) because **not every player has the save** — a
normal player still starts the vanilla way (prologue → Cascade), where Cap peace is
genuinely *not* sphere-0.

---

## The one fact that makes this small

`CapPeace()` already exists and is already the single gate for all Cap peace/re-arrival
content. In [hooks/Rules.py:52-60](../apworld/smo_archipelago/hooks/Rules.py#L52):

```python
def CapPeace(world, multiworld, state, player):
    # Re-arrival in Cap: reachable once you've left Cascade (its leave-gate of moons).
    return KingdomMoons(world, multiworld, state, player, "Cascade", 5)
```

It is consumed as a `{CapPeace()}` token in requires strings (confirmed referenced from
[data/locations.json](../apworld/smo_archipelago/data/locations.json),
[data/scenario_gates.json](../apworld/smo_archipelago/data/scenario_gates.json),
[data/subarea_scenario_gates.json](../apworld/smo_archipelago/data/subarea_scenario_gates.json)),
**not** as a region edge — so changing what the function returns changes every Cap-peace
gate at once, with no regions.json surgery.

**On the Cap-peace save, Cap is at peace and the Odyssey is launched from frame zero**,
so Cap-peace moons are physically collectable immediately — i.e. `CapPeace()` is
*true in sphere 0*. The whole task is: **make `CapPeace()` return `True` early when the
new option is on.** It strictly *loosens* reachability (more sphere-0 room → never less
generable), and nothing else keys off Cap, so there's no circular-gate or fill-safety
risk (Cap content gates no other kingdom — audit Rules.py: `CapPeace` appears only in
its own definition).

---

## Recommended implementation (apworld-only; no switch-mod / wire / re-seed-of-others)

### 1. New option — `hooks/Options.py`

Add a plain `Toggle` (default **OFF**), registered in `before_options_defined`:

```python
class StartAtCapPeace(Toggle):
    """Generate logic assuming the run STARTS at Cap-Kingdom peace with the Odyssey
    landed (the special save produced by the save-relocate bootstrap). When ON, Cap
    Kingdom's peace / re-arrival moons are reachable from sphere 0 instead of requiring
    the Cascade leave-gate first.

    Leave OFF (default) for a normal playthrough that starts with the Cap prologue and
    flies to Cascade — there, Cap peace is genuinely not reachable until you've left
    Cascade, so a sphere-0 placement would be unwinnable.

    Requires the matching Cap-peace save to actually play; this only changes seed logic.
    No effect unless `include_cap_peace_moons` is also on (that option decides whether the
    Cap-peace moons are in the pool at all)."""
    display_name = "Start at Cap Kingdom Peace"
```
```python
    options["start_at_cap_peace"] = StartAtCapPeace   # in before_options_defined
```

> Name `start_at_cap_peace` is a proposal — confirm with Devon. Don't reuse
> `include_cap_peace_moons` (that's the orthogonal "are these moons in the pool" toggle;
> the new one is "*when* are they reachable").

### 2. Short-circuit the rule — `hooks/Rules.py`

```python
def CapPeace(world, multiworld, state, player):
    # Start-at-Cap-peace save: Cap is at peace + Odyssey launched from frame zero,
    # so Cap peace/re-arrival moons are reachable in sphere 0.
    if is_option_enabled(multiworld, player, "start_at_cap_peace"):
        return True
    return KingdomMoons(world, multiworld, state, player, "Cascade", 5)
```

`is_option_enabled` is already imported at the top of Rules.py
([Rules.py:3](../apworld/smo_archipelago/hooks/Rules.py#L3)). Rule functions receive
`multiworld` + `player`, so reading the option here is the established pattern (mirrors
how the other peace rules are written).

That is the **entire functional change.** Everything downstream (the `{CapPeace()}`
tokens in locations.json / the two scenario-gate JSONs) picks it up automatically.

### 3. Test — `tests/test_scenario_gating.py` (already exercises `CapPeace`)

Add a case: generate (or build a CollectionState) with `start_at_cap_peace` ON and
assert a Cap-peace-gated location is reachable with **zero** Cascade moons collected;
and with it OFF, assert the existing `KingdomMoons("Cascade",5)` behavior is unchanged.
Pattern off the existing `CapPeace` references in that file
([tests/test_scenario_gating.py](../apworld/smo_archipelago/tests/test_scenario_gating.py)).

### 4. Regen loop (Windows — see CLAUDE.md)

`pytest apworld/smo_archipelago/tests/` → `python scripts/install_apworld.py` →
`python vendor/Archipelago/Generate.py` with a YAML that sets `start_at_cap_peace: true`.
**No `compile_moon_logic.py` needed** — this changes a Python rule, not the compiled
`requires` data (and per CLAUDE.md never run it without the romfs maps present).
**No switch-mod rebuild** — the in-game Cap-peace state comes from the *save*, not the mod.

---

## Open questions to resolve with Devon before/while building

1. **Scope = Cap only?** The save also lands with Cascade pre-Broode (Multi-Moon
   collectable) and the Odyssey launched, but Cascade still requires its own moons
   normally and Cascade access is *already* sphere-0 (it's the free start region). So
   the only honest sphere-0 *gain* is Cap-peace-without-Cascade-moons. Confirm we don't
   also want to pull any other kingdom's peace forward (recommendation: **no** — keep it
   Cap-only; broader "start later in the game" is a separate, bigger feature).

2. **Starting region / kingdom-order.** Cap is still the first kingdom in flight order on
   this save, so the switch-mod kingdom-order gate and the region graph head (Cascade as
   free start) are unaffected. Verify nothing in `KingdomOrderGate` or
   `before_create_regions` needs the option (expected: nothing — it's generation logic
   only). If a future run wants to *physically* start in a different kingdom, that's the
   separate save-relocate-to-other-kingdom problem, not this option.

3. **Interaction with `include_cap_peace_moons` OFF.** If a player sets the new option ON
   but `include_cap_peace_moons` OFF, the Cap-peace moons aren't in the pool, so the
   ungate has nothing to act on — harmless. Decide whether to surface a warning or just
   let it no-op (recommendation: no-op; it's a legal combination).

4. **Does any non-Cap gate transitively assume the vanilla Cap timing?** Audited this
   session: `CapPeace` is referenced only in its own definition in Rules.py — no other
   peace rule or region edge composes it. Re-confirm after editing (grep `CapPeace`).

5. **AP-consistency on the save.** The save was produced by genuine flight (not editing),
   so its peace/deposit/outstanding accounting is self-consistent. The option only tells
   the *generator* Cap is sphere-0; the *Switch* still reports/receives normally. No
   wire/accounting change expected — verify a loopback connect from the Cap-peace save
   doesn't trip the M6 deposit/outstanding replay (it shouldn't: 0 moons collected).

---

## Why this is the whole job (and what it is NOT)

- **IS:** one option + one early-return in `CapPeace()` + a test + a regen. Pure
  generation-logic tier. Strictly loosens sphere-0, so it can't make a seed *less*
  generable.
- **IS NOT:** a switch-mod change (the save provides in-game state), a wire-protocol
  change, or a regions.json rewrite (CapPeace is a `{Func()}` token, not an edge).
- **IS NOT:** a way to *create* the Cap-peace save — that's the completed bootstrap. This
  option only makes seeds *assume* it.

Cross-refs: [[world-traveling-peach-auto-start]] (peace-state precedent),
[[region-gating-egress-off-by-one]] (why `CapPeace` keys off `KingdomMoons`, not
`canReachRegion`), [[scenario-gating-spreadsheet-authoritative]] (scenario_gates.json
is where the `{CapPeace()}` tokens live for the gated moons).
