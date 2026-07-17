# Handoff: Metro Kingdom costume door — gated by an NPC conversation, not a door lock

**Recommended model: Sonnet 5.** Data/logic investigation in the Manual-derived
generation layer plus (maybe) a one-line requirements fix. The main skill needed is
careful reading of `moon_requirements.json` / compile gating and asking Devon the right
clarifying question first — not deep systems reasoning.

## Symptom (Devon, 2026-07-17, verbatim intent)

"Metro Kingdom's costume door isn't open because you have to talk to somebody, rather
than a lock that's on it. Can we make sure that isn't the case."

I.e. the in-game gate on Metro's costume door is an NPC conversation (doorman-style),
not a static lock on the door itself — and our logic/enforcement may be modeling it
wrong. Two distinct failure modes are possible; **ask Devon which he observed before
coding** (AskUserQuestion):

- **(A) Logic wrong:** the seed considers the costume-door check reachable as soon as
  the outfit is affordable/owned, but the gating NPC only exists under certain
  scenario/peace states → check unreachable when logic says reachable (or vice versa:
  we gate it on something unnecessary).
- **(B) Our mod interferes:** the NPC conversation itself is blocked/broken by one of
  our hooks (Cappy messenger routing, Talkatoo% substitution, scenario forcing from
  MoonRockHook), so the door can never open even with the outfit.

## Where to look

- `apworld/smo_archipelago/data/moon_requirements.json` — the Metro costume-door
  moon's `requires` (outfit vocab came from the community CSV via
  `scripts/import_moon_requirements.py`). Check what it currently demands.
- `scripts/compile_moon_logic.py` — how scenario/peace gates get compiled onto
  requires strings; whether NPC-availability windows are representable.
- `docs/logic-and-entrance-status.md` §3 — state of the 213 promoted moons' gating
  (if the costume-door moon is one of the 213, its `requires` may still be the
  known-incomplete compiled output).
- If failure mode B: `hooks/` on the switch-mod side (CappyMessageHook routing,
  Talkatoo substitution) — but only after Devon confirms B.

## Guardrails

- **NEVER run `compile_moon_logic.py` yourself** — it requires `shine_map.json` /
  `world_scenarios.json` (Devon's machine only); running without them degrades to
  rock-only and WIPES existing compiled scenario gates (CLAUDE.md). If the fix is
  "recompile with corrected input," specify the edit and hand the run to Devon.
- IP rule: don't paste moon-name lists >5 into docs/commits; one name as a fixture
  is fine.
- File work via Read/Grep/Edit only (stale shell mount).
- If `requires` data changes: Devon must run compile (if applicable) →
  `install_apworld.py` → `Generate.py`; note that a LIVE seed won't pick up logic
  changes — this fixes future seeds, so if Devon's current seed is affected,
  suggest the `!getitem`-style workaround explicitly.

## Acceptance

- A written determination of what actually gates the Metro costume door in-game
  (scenario window for the NPC, outfit, anything else), citing decomp/data evidence.
- Logic (`requires`/gating) matches that reality, or the interfering hook is fixed.
- If other kingdoms' costume doors share the same NPC-gate pattern, audit them in
  the same pass (there are ≤ a handful; keep the doc list short per IP rule).
- Regression test where feasible (e.g. `tests/` requires-string assertion for the
  affected location(s)).

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (stale shell mount, compile_moon_logic
> warning, IP rules), then docs/handoff-metro-costume-door.md. FIRST use
> AskUserQuestion to determine which failure mode Devon observed (logic thinks the
> check is open when the gating NPC isn't there yet, vs. the NPC interaction being
> broken by our hooks). Then investigate per the handoff: moon_requirements.json →
> compile_moon_logic.py gating → (only if mode B) the switch-mod hooks. Never run
> compile_moon_logic.py yourself. Deliver the determination, the minimal fix,
> which costume doors in other kingdoms need the same treatment, and the exact
> regen steps Devon must run — including whether his current seed can be salvaged
> or needs the !getitem workaround.
