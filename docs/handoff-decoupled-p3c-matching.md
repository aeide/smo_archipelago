# Handoff — P3c: connectivity-guaranteed involution (decoupled entrance rando)

**For a Claude Code session on Devon's Windows machine.** Read CLAUDE.md
first — but note: its "stale/truncated Linux shell" warnings are Cowork-mode
specific. In Claude Code your shell IS the real machine: run pytest, Generate,
and scripts directly (interpreter: `python` = Python 3.13.13; pytest 9.1.1
freshly installed). The other CLAUDE.md rules (IP hygiene, regen loop, zip vs
source) apply unchanged.

Context chain, in order:
1. [plan-decoupled-entrances.md](plan-decoupled-entrances.md) — phase plan;
   P0/P1/P2/P3a/P3b complete. You are P3c.
2. [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md) —
   SIGNED OFF; D1–D9 are fixed constraints, not open questions.
3. `apworld/smo_archipelago/port_graph.py` — P3b's data model (your input).
   Its module docstring is the model spec; read it fully.
4. `apworld/smo_archipelago/tests/test_port_graph.py` — 22/22 green.

## Step 0 — triage the full-suite baseline (BEFORE any P3c code)

Devon's full-suite run on the fresh Python 3.13 interpreter:
**151 failed, 813 passed, 84 skipped.** `test_port_graph.py` alone is 22/22
green. The 151 are UNDIAGNOSED — most likely environment, not regressions:
this interpreter got pytest installed today and has none of the AP dev deps,
and many tests import Archipelago core (probable mass
ModuleNotFoundError). Check the failure signatures; if it's missing deps, try
`python -m pip install -r vendor/Archipelago/requirements.txt` (or the
interpreter previous sessions used). **Establish and record a green (or
explained) baseline in the plan doc before touching P3c** — otherwise you
can't attribute your own breakage. If any failures turn out to be REAL
regressions from P2/P3b, fix or escalate to Devon before proceeding.

## The task — random involution over the mouth pool with a solvability guarantee

Roll, per seed (`world.random`-driven, deterministic), an involution over
`build_port_graph(...).mouths` that the P3d region wiring can trust.

**The key structural insight (from the D1 two-channel model):** every kingdom
overworld is ALWAYS flight-reachable, so overworld mouths sitting in kingdom
HomeStages are never strandable. The classic entrance-rando dead-pocket risk
reduces to: **no subarea (or nested-subarea cluster) may be matched ONLY
within itself/its cluster** — i.e. build the stage-connectivity graph
(nodes = stages; a matched pair (A,B) connects A.stage↔B.stage; kingdom
HomeStages are the roots) and require every pooled subarea's stage to be
connected to some root. Nested subareas ("overworld" mouths living in parent
INTERIOR stages — see the P3b plan notes) must resolve through their parent's
connectivity, not be assumed rooted.

Suggested construction (design freedom is yours if tests hold):
frontier-growing — maintain the set of root-connected stages; repeatedly pick
a random unmatched mouth in a connected stage and match it to a random
unmatched mouth, preferring one in a NOT-yet-connected stage while any
remain; fall back to uniform matching once all stages are connected. Odd
leftover mouth ⇒ leave it vanilla-identity (allowed; involutions may have
fixed points — a fixed point means "no rewrite row" per
`estimate_remap_rows`'s vanilla-baseline semantics).

Hard requirements:
- Total involution over the pool (`is_involution` passes).
- Stage-connectivity guarantee as above (write the checker; it's also a test).
- Deterministic per seed; different across seeds.
- `estimate_remap_rows(matching, vanilla) <= 512 - headroom` (assert at roll
  time too, loudly).
- Excluded kingdoms/doors never appear (they're already absent from the pool;
  don't re-add).
- Festival pool variant works (`festival=True`).

Where it lives: new `apworld/smo_archipelago/port_matching.py` (pure, no AP
imports, same try/except import idiom as port_graph) — keeps port_graph as
the data layer. `roll_port_matching(graph, rng) -> dict[str, str]`.

Tests (`tests/test_port_matching.py`): involution validity + connectivity
checker across MANY seeds (e.g. 200 rng seeds — it's pure and fast);
determinism (same seed twice ⇒ identical); distinct seeds differ; row budget;
festival variant; a hand-built adversarial mini entrance_stages fixture
(e.g. 3 subareas, one door each, forcing the frontier logic to reach all);
lone-mouth handling; empty-pool degenerate case.

## Scope guard

P3c is the MATCHING ONLY. Do not start 3d (region wiring), 3e (slot_data /
compile rows / Switch entry-branch from_id verification), or 3f (Mushroom
junk exemption) — those are separate sessions. Do update the plan doc's 3c
section with results, and CLAUDE.md-style notes for anything load-bearing you
discover. Nothing in this task touches Nintendo IP; audit `git status`
before any commit as usual.
