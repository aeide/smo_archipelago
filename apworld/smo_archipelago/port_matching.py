"""
port_matching.py — P3c: connectivity-guaranteed random involution over the
decoupled entrance randomizer's mouth pool.

Pure algorithm layer (no AP imports, same import idiom as port_graph.py).
Input is P3b's `PortGraph` (port_graph.build_port_graph); output is a total
involution `mouth_id -> mouth_id` that the P3d region wiring and the P3e
row compiler can trust. Design authority: docs/design-decoupled-kingdom-order.md
(D1-D9) and docs/plan-decoupled-entrances.md §3c.

The solvability model (D1 two-channel insight)
----------------------------------------------
Every kingdom overworld is ALWAYS flight-reachable, so kingdom HomeStages are
the connectivity ROOTS. The classic entrance-rando dead-pocket risk reduces
to: no subarea stage (or nested-subarea cluster) may be matched ONLY within
itself/its cluster. Formally, build the stage-connectivity graph — nodes are
the stages the pooled mouths physically live in; a matched pair (A, B) is an
undirected edge A.stage <-> B.stage (both ends are ingest, hence walkable
both ways); fixed points contribute no edge — and require every node to be
connected to some root.

Nested subareas resolve naturally: an "overworld" mouth living in a parent
INTERIOR stage puts that parent stage in the node set, and the BFS demands
the whole chain be linked to a root.

ROOTS are every stage that hosts a pooled OVERWORLD mouth and is NOT some
pooled subarea's interior stage. Real data (2026-07-07) makes this rule, not
a "HomeStage"-suffix test, necessary: overworld door mouths also live in
placement ZONES of the kingdom map (SkyWorldCastleZone, LakeWorldTownZone,
SeaWorld*Zone, ForestWorldWoodsStage [Deep Woods], SnowWorldTownStage...) —
all walkably part of the always-flight-reachable overworld. The rule is
self-consistent for the residual cases too: a non-pooled parent's interior
stage hosting a pooled child door keeps its vanilla entry door, so it IS
always vanilla-reachable — root is physically correct. Only stages that are
themselves pooled interiors genuinely depend on the matching. Kingdom
HomeStages are additionally always roots (belt and braces).

One real-data quirk the checker must honor: zone-hosted doors are SPLIT into
two lone one-way halves with DIFFERENT port_ids (the door actor sits in the
zone, e.g. `LakeWorldTownZone#CapTrampolineA`, while the interior's exit
records the parent stage, `LakeWorldHomeStage#CapTrampolineA`), each vanilla
self-mapped. A lone OVERWORLD mouth left as a fixed point behaves exactly
vanilla (no rewrite row) and therefore still walks INTO its subarea — the
checker credits that as a directed entry edge (overworld stage -> subarea
interior stage). Without the credit, vanilla itself would read "stranded"
for those subareas.

Construction (frontier-growing, provably terminating)
-----------------------------------------------------
Phase 1: while any stage is unconnected, pair a random unmatched mouth in
connected territory with a random unmatched mouth in a NOT-yet-connected
stage; that stage joins the frontier. Each step strictly grows the connected
set, and an unconnected stage's mouths are only ever consumed by the pairing
that connects it, so phase 1 cannot starve a stage of its own mouths. It can
only fail if connected territory runs out of unmatched mouths first — loud
RuntimeError (cannot happen at real pool sizes: ~150+ rooted overworld
mouths vs ~120 stages to connect).

Phase 2: all stages connected — uniform random pairing of the remainder
(no pairing can UN-connect anything).

Matching-topology constraint (Devon ruling 2026-07-08, plan doc P4 item 9)
--------------------------------------------------------------------------
An OVERWORLD mouth must always pair with an INTERIOR mouth; an
OVERWORLD↔OVERWORLD pair is never rolled. (Interior↔interior stays legal.)
This REPLACES the earlier "free matching" ruling 3(a) — no option knob.
Feasibility holds on real data by construction: every overworld mouth has a
vanilla interior partner and multi-exit subareas contribute surplus interior
mouths, so #interior ≥ #overworld. To keep phase 2 completable the roller
maintains the invariant "unmatched #interior − #overworld ≥ 0" at every
step: O–I pairs leave the slack unchanged, and I–I pairs (slack −2) are
only taken while slack ≥ 2. A pool where the slack starts negative cannot
satisfy the constraint at all — loud RuntimeError at roll time.

Odd pool ⇒ one fixed point. Parity guarantee: the pool is odd iff an odd
number of doors contributed exactly ONE ingest mouth (lone mouths, vanilla
self-mapped per port_graph), so a lone mouth always exists to take the fixed
point. We reserve one UP FRONT and give it `matching[x] = x`, which equals
its vanilla assignment ⇒ ZERO rewrite rows (estimate_remap_rows semantics) ⇒
true vanilla passthrough in-game. Fixed-pointing a TWO-WAY mouth instead
would compile a self-loop row (door dumps you back at itself) — legal but
weird, so the roller never does it.

Determinism: driven entirely by the caller's `rng` (`world.random` at
generation time) with every candidate list sorted before `rng.choice` /
`rng.shuffle` — same seed ⇒ identical matching, byte for byte.

Row budget: asserted loudly at roll time against kEntranceRemapMax (512, P2,
switch-mod/src/hooks/EntranceShuffleHook.cpp) minus headroom.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from random import Random

try:  # package import (bundled .apworld / generation)
    from .port_graph import (
        INTERIOR,
        OVERWORLD,
        PortGraph,
        ROW_HEADROOM,
        ROW_TABLE_CAP,
        estimate_remap_rows,
        is_involution,
        pinned_one_way_entry_mouths,
    )
except ImportError:  # loose import (test suite, sys.path = package dir)
    from port_graph import (  # type: ignore
        INTERIOR,
        OVERWORLD,
        PortGraph,
        ROW_HEADROOM,
        ROW_TABLE_CAP,
        estimate_remap_rows,
        is_involution,
        pinned_one_way_entry_mouths,
    )

logger = logging.getLogger(__name__)

# ROW_TABLE_CAP / ROW_HEADROOM now live in port_graph.py (P3e: compile_port_remaps
# needs them too, and port_graph is the module port_matching already imports
# FROM, so defining them there avoids a circular import). Re-exported here
# unchanged so existing imports of `port_matching.ROW_TABLE_CAP` keep working.


# ---------------------------------------------------------------------------
# Connectivity model
# ---------------------------------------------------------------------------

def interior_stages(graph: PortGraph) -> frozenset[str]:
    """Stages that are some pooled subarea's interior — the only stages whose
    reachability genuinely depends on the matching."""
    return frozenset(m.stage for m in graph.mouths.values()
                     if m.side == INTERIOR)


def root_stages(graph: PortGraph) -> frozenset[str]:
    """Always-reachable connectivity anchors (D1): every stage hosting a
    pooled OVERWORLD mouth that is not itself a pooled interior — kingdom
    HomeStages, their placement zones, and vanilla-kept parent interiors
    (see module docstring). HomeStages root unconditionally."""
    inner = interior_stages(graph)
    return frozenset(
        m.stage for m in graph.mouths.values()
        if m.side == OVERWORLD
        and (m.stage.endswith("HomeStage") or m.stage not in inner))


def stage_nodes(graph: PortGraph) -> frozenset[str]:
    """Every stage a pooled mouth physically lives in."""
    return frozenset(m.stage for m in graph.mouths.values())


def _subarea_interior_stage(graph: PortGraph) -> dict[str, str]:
    return {m.subarea: m.stage for m in graph.mouths.values()
            if m.side == INTERIOR}


def unconnected_stages(matching: dict[str, str],
                       graph: PortGraph) -> set[str]:
    """Stages not linked to any root under `matching`. Empty set == the
    matching satisfies the P3c solvability guarantee.

    Edges: a matched pair is bidirectional (both ends ingest => walkable both
    ways). A fixed point contributes nothing EXCEPT the vanilla-passthrough
    credit: a lone OVERWORLD mouth fixed at its vanilla self-map still walks
    into its own subarea, a directed entry edge (module docstring). A lone
    INTERIOR fixed point is one-way OUT of its stage — no credit."""
    nodes = stage_nodes(graph)
    sub_stage = _subarea_interior_stage(graph)
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in matching.items():
        ma, mb = graph.mouths.get(a), graph.mouths.get(b)
        if ma is None or mb is None:
            continue
        if a == b:
            if (ma.side == OVERWORLD
                    and graph.vanilla_matching.get(a) == a
                    and ma.subarea in sub_stage):
                adj[ma.stage].add(sub_stage[ma.subarea])
            continue
        adj[ma.stage].add(mb.stage)
        adj[mb.stage].add(ma.stage)
    seen = set(root_stages(graph))
    stack = list(seen)
    while stack:
        for nxt in adj[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return set(nodes) - seen


# ---------------------------------------------------------------------------
# The roll
# ---------------------------------------------------------------------------

def _reserve_fixed_point(graph: PortGraph, unmatched: set[str],
                         rng: Random) -> str:
    """Pick the odd pool's designated fixed point: a lone (vanilla
    self-mapped) mouth, preferring one whose stage doesn't depend on it for
    connectivity (rooted stage, or stage with other pooled mouths)."""
    lone = sorted(m for m in unmatched
                  if graph.vanilla_matching.get(m) == m)
    if not lone:
        # Parity argument says this is impossible: pool size is odd iff the
        # lone-mouth count is odd. A hit here means port_graph's vanilla
        # bookkeeping changed under us.
        raise RuntimeError(
            "port_matching: odd mouth pool but no vanilla self-mapped lone "
            "mouth to take the fixed point — port_graph invariant broken")
    roots = root_stages(graph)
    by_stage: dict[str, int] = defaultdict(int)
    for m in graph.mouths.values():
        by_stage[m.stage] += 1
    safe = [m for m in lone
            if graph.mouths[m].stage in roots
            or by_stage[graph.mouths[m].stage] > 1]
    return rng.choice(safe or lone)


def _interior_slack(graph: PortGraph, unmatched: set[str]) -> int:
    """#interior − #overworld over the unmatched pool — the topology
    constraint's feasibility margin (module docstring)."""
    slack = 0
    for m in unmatched:
        slack += 1 if graph.mouths[m].side == INTERIOR else -1
    return slack


def roll_port_matching(graph: PortGraph, rng: Random) -> dict[str, str]:
    """Roll a random total involution over `graph.mouths` such that every
    pooled stage is root-connected (see module docstring) and no pair is
    OVERWORLD↔OVERWORLD (matching-topology constraint, Devon ruling
    2026-07-08). Deterministic in `rng`; raises RuntimeError (loudly, at
    generation time) rather than ever returning an unsolvable or over-budget
    matching."""
    matching: dict[str, str] = {}
    if not graph.mouths:
        return matching

    unmatched = set(graph.mouths)

    # One-way-course pinning (Devon ruling 2026-07-08, see port_graph's
    # one-way-course note): a subarea whose pooled interior mouths are all
    # exit-only can never feed its FULL interior (member moons) through the
    # matching — arriving at an exit mouth cannot traverse the course
    # backwards. Pin its entrance doors vanilla (fixed points = zero rewrite
    # rows) so the moons stay reachable; the exit mouths keep shuffling. All
    # pins are lone overworld mouths (shape argument in port_graph), so each
    # is the true vanilla-credit fixed point and only INCREASES the interior
    # slack the topology constraint needs.
    pinned = sorted(pinned_one_way_entry_mouths(graph) & unmatched)
    for m in pinned:
        matching[m] = m
        unmatched.discard(m)
    if pinned:
        logger.info(
            "port_matching: pinned %d one-way-course entrance mouth(s) "
            "vanilla: %s", len(pinned), pinned)

    fixed_point: str | None = None
    if len(unmatched) % 2 == 1:
        fixed_point = _reserve_fixed_point(graph, unmatched, rng)
        unmatched.discard(fixed_point)

    if _interior_slack(graph, unmatched) < 0:
        raise RuntimeError(
            "port_matching: overworld mouths outnumber interior mouths in "
            "the pool — the no-overworld↔overworld constraint cannot be "
            "satisfied (pool shape changed under us; see module docstring)")

    nodes = stage_nodes(graph)
    connected = set(root_stages(graph))

    # Pin vanilla-credit: a pinned entrance walks into its course's interior
    # stage (the same directed overworld→interior edge unconnected_stages
    # credits), so phase 1 must count that stage connected once the pin's own
    # stage is — otherwise the course's exit-only mouth looks like the stage's
    # last hope and e.g. reserving it as the parity fixed point strands the
    # stage spuriously. Closure form because a pin can itself sit in a
    # not-yet-connected stage (nested course entrance).
    sub_stage = _subarea_interior_stage(graph)
    pin_credit = [(graph.mouths[m].stage, sub_stage[graph.mouths[m].subarea])
                  for m in pinned if graph.mouths[m].subarea in sub_stage]

    def _apply_pin_credit() -> None:
        changed = True
        while changed:
            changed = False
            for src, dst in pin_credit:
                if src in connected and dst not in connected:
                    connected.add(dst)
                    changed = True

    _apply_pin_credit()

    # Phase 1 — frontier growing: every pairing lands one new stage. The
    # connecting mouth `b` (in a not-yet-connected stage) is picked first;
    # its frontier partner is then drawn from the side-compatible subset:
    # an OVERWORLD b needs an INTERIOR a, and an INTERIOR b may take any a
    # only while the slack invariant survives an I–I pair.
    while nodes - connected:
        frontier = sorted(m for m in unmatched
                          if graph.mouths[m].stage in connected)
        targets = sorted(m for m in unmatched
                         if graph.mouths[m].stage not in connected)
        if not targets:
            raise RuntimeError(
                "port_matching: stages "
                f"{sorted(nodes - connected)} have no unmatched mouths left "
                "— cannot be root-connected by any completion of this roll")
        if not frontier:
            raise RuntimeError(
                "port_matching: no unmatched mouths left in root-connected "
                f"territory while {sorted(nodes - connected)} remain "
                "unconnected (root-side mouth supply exhausted)")
        slack = _interior_slack(graph, unmatched)
        rng.shuffle(targets)
        a = b = None
        for cand in targets:
            if graph.mouths[cand].side == OVERWORLD or slack < 2:
                # b overworld → a must be interior; slack-tight interior b
                # must also take an overworld a (an I–I pair would strand an
                # overworld mouth later).
                want = INTERIOR if graph.mouths[cand].side == OVERWORLD \
                    else OVERWORLD
                compat = [m for m in frontier
                          if graph.mouths[m].side == want]
            else:
                compat = frontier
            if compat:
                b = cand
                a = rng.choice(compat)
                break
        if a is None or b is None:
            raise RuntimeError(
                "port_matching: no side-compatible frontier pairing under "
                "the no-overworld↔overworld constraint while stages "
                f"{sorted(nodes - connected)} remain unconnected")
        matching[a] = b
        matching[b] = a
        unmatched.discard(a)
        unmatched.discard(b)
        connected.add(graph.mouths[b].stage)
        _apply_pin_credit()

    # Phase 2 — everything is connected; pair the rest uniformly under the
    # constraint: every remaining overworld mouth takes an interior partner
    # first, then the surplus interiors pair among themselves.
    rest_o = sorted(m for m in unmatched
                    if graph.mouths[m].side == OVERWORLD)
    rest_i = sorted(m for m in unmatched
                    if graph.mouths[m].side == INTERIOR)
    rng.shuffle(rest_o)
    rng.shuffle(rest_i)
    if len(rest_o) > len(rest_i):
        # Unreachable while the slack invariant holds; defensive.
        raise RuntimeError(
            "port_matching: phase-2 overworld surplus despite the slack "
            "invariant — roller bug")
    for a in rest_o:
        b = rest_i.pop()
        matching[a] = b
        matching[b] = a
    while len(rest_i) >= 2:
        a, b = rest_i.pop(), rest_i.pop()
        matching[a] = b
        matching[b] = a
    if rest_i:
        # Only possible when the pool was even but phase 1 + shuffle left one
        # (cannot happen — pairs consume two at a time); defensive.
        leftover = rest_i.pop()
        matching[leftover] = leftover
        logger.warning("port_matching: unexpected even-pool leftover %s "
                       "left as fixed point", leftover)
    if fixed_point is not None:
        matching[fixed_point] = fixed_point

    # Loud postconditions — a bad roll must never escape into fill.
    if not is_involution(matching, graph.mouths):
        raise RuntimeError("port_matching: rolled matching is not a total "
                           "involution over the mouth pool")
    oo = sorted(a for a, b in matching.items()
                if a != b
                and graph.mouths[a].side == OVERWORLD
                and graph.mouths[b].side == OVERWORLD)
    if oo:
        raise RuntimeError(
            "port_matching: rolled matching contains overworld↔overworld "
            f"pairs (topology constraint violated): {oo}")
    missing = unconnected_stages(matching, graph)
    if missing:
        raise RuntimeError(
            f"port_matching: rolled matching strands stages {sorted(missing)}")
    rows = estimate_remap_rows(matching, graph.vanilla_matching)
    budget = ROW_TABLE_CAP - ROW_HEADROOM
    if rows > budget:
        raise RuntimeError(
            f"port_matching: matching needs {rows} rewrite rows, over the "
            f"{budget} budget (kEntranceRemapMax {ROW_TABLE_CAP} - "
            f"{ROW_HEADROOM} headroom)")
    logger.info("port_matching: rolled %d pairs, %d rewrite rows (budget %d)",
                len(matching) // 2, rows, budget)
    return matching
