# Prompt — paste into a fresh Claude Code session (VS Code) at E:\smo_archipelago

---

Read CLAUDE.md first, then read
`docs/handoff-decoupled-flight-economy-fix.md` in full — it contains a
completed audit and the exact fix plan. Your job is to implement that plan;
do not re-derive the diagnosis or redesign the approach.

Context in one paragraph: `entrance_shuffle: decoupled` seeds generate with
~8-sphere playthroughs and mass-stranded progression because the decoupled
wiring's free "K Arrival → K" presence edge lets on-foot chain arrival grant
kingdom regions, and under the Manual egress quirk each inter-kingdom flight
edge carries only a single kingdom's `{KingdomMoons}` gate — so
reach(Moon Kingdom) collapses from the cumulative 124-moon economy to ~one
kingdom's gate. The fix is decoupled-only: AND a recursive
`flight_reach(source kingdom)` predicate (computed over regions.json
`connects_to` only, OR over parents, exempting `Pokino` and all "K Arrival"
destinations) onto every inter-kingdom flight entrance, via `add_rule`, at the
end of the decoupled branch of `after_set_rules` in
`apworld/smo_archipelago/hooks/World.py`.

Execute steps 1–5 of the handoff's "Step-by-step plan" exactly:

1. Implement `_apply_decoupled_flight_economy` in `hooks/World.py` (reuse the
   region table + requires-evaluation helpers that `Rules.py::set_rules`'s
   region loop already uses; `add_rule`, never `set_rule`).
2. Call it last in the `option_decoupled` branch of `after_set_rules`; update
   that branch's now-wrong comment.
3. Rework `test_kingdom_arrival_channel_and_flight_gates_unchanged` in
   `tests/test_decoupled_region_wiring.py` (the `unclobbered == 0` assertion
   is invalidated by design).
4. Add the invariant tests described in the handoff (empty-state Moon
   unreachable even with all non-moon progression; collection walk opens Moon
   only at the full rolled gate total; simple/off modes untouched).
5. Add the D1 erratum to `docs/design-decoupled-kingdom-order.md` and the
   one-line CLAUDE.md status pointer.

Constraints (all load-bearing, from CLAUDE.md and the handoff):

- Touch ONLY the decoupled path — `off`/`simple` behavior must stay
  byte-identical (guard test exists).
- Do NOT attempt the systemic egress→ingress engine fix
  (handoff-region-gating-egress.md deferred item 2).
- Do NOT modify regions.json requires, KINGDOM_MOON_GATES,
  `randomize_kingdom_gates`, the switch mod, the client, or slot_data.
- Never express "player has left kingdom K" as `canReachRegion` — item
  predicates only (repo rule).
- Run the test files listed in handoff step 6 with pytest. Then STOP and hand
  back to Devon for the zip rebuild + Generate validation
  (`python scripts\install_apworld.py` then `python vendor\Archipelago\Generate.py`)
  — remind him Generate loads the installed zip, not the source tree, and
  that the acceptance check is the spoiler shape described in handoff step 6.
- Nothing in this task touches gitignored IP files; do not stage any (see
  CLAUDE.md "Never commit Nintendo IP").

---
