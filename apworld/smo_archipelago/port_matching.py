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

Mushroom erratum (2026-07-17, Devon ruling — exit-portals are the MK route)
---------------------------------------------------------------------------
The "every kingdom overworld is flight-reachable" premise is FALSE for the
Mushroom Kingdom — it is post-game, fly-in only after the credits, i.e. after
the AP goal under goal=mushroom_kingdom. Its D9-promoted overworld checks can
hold progression, so a decoupled seed needs a real pre-goal route into
PeachWorldHomeStage: some matched pair whose overworld mouth is an MK door
and whose partner sits in root-connected territory (walk in elsewhere, exit
through the partner mouth, portal-land at the MK door — the exit-portal
semantics compile_port_remaps ships and the switch-mod applies). Kingdoms in
NON_ROOT_KINGDOMS therefore contribute NO roots: their stages are ordinary
nodes phase 1 must connect, and unconnected_stages fails a matching that
leaves the MK cluster rooted only through itself (e.g. every MK door paired
with a sole-mouth interior — under the involution that interior's only way in
is FROM Mushroom, a dead end). Note the VANILLA matching genuinely strands the
MK cluster under this model (vanilla MK access IS the credits warp) — that is
correct, asserted by the baseline test, and why the roller never leaves all
MK doors on their vanilla partners. Evidence seed 91455467025183402260 +
docs/handoff-decoupled-mushroom-overworld-reachability.md.

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
        Mouth,
        PortGraph,
        ROW_HEADROOM,
        ROW_TABLE_CAP,
        entry_capable_interior_mouths,
        estimate_remap_rows,
        is_involution,
        pinned_one_way_entry_mouths,
    )
except ImportError:  # loose import (test suite, sys.path = package dir)
    from port_graph import (  # type: ignore
        INTERIOR,
        OVERWORLD,
        Mouth,
        PortGraph,
        ROW_HEADROOM,
        ROW_TABLE_CAP,
        entry_capable_interior_mouths,
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


# Kingdoms whose overworld is NOT flight-reachable before the AP goal, so
# their stages must never anchor connectivity (module docstring, Mushroom
# erratum). Matched against Mouth.kingdom (the subarea record's display name)
# so placement zones and any future MK-hosted door stage are caught without a
# stage-name list. Moon/Dark/Darker never pool (DECOUPLED_EXCLUDED_KINGDOMS),
# so Mushroom is the only pooled post-game overworld.
NON_ROOT_KINGDOMS: frozenset[str] = frozenset({"Mushroom Kingdom"})


def root_stages(graph: PortGraph) -> frozenset[str]:
    """Always-reachable connectivity anchors (D1): every stage hosting a
    pooled OVERWORLD mouth that is not itself a pooled interior — kingdom
    HomeStages, their placement zones, and vanilla-kept parent interiors
    (see module docstring). HomeStages root unconditionally — EXCEPT stages
    of NON_ROOT_KINGDOMS (post-game overworlds, not flight-reachable
    pre-goal), which are never roots and must earn their connectivity
    through the matching like any interior."""
    inner = interior_stages(graph)
    non_root = frozenset(
        m.stage for m in graph.mouths.values()
        if m.side == OVERWORLD and m.kingdom in NON_ROOT_KINGDOMS)
    return frozenset(
        m.stage for m in graph.mouths.values()
        if m.side == OVERWORLD
        and m.stage not in non_root
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


_ROOT = "<root>"


def _directed_model(graph: PortGraph):
    """Shared directed-reachability vocabulary (checker + roller phase 1).

    Returns (node_fn, capable, interior_stage_to_sub, subs):
      * node_fn(Mouth) -> the node an arrival AT that mouth grants:
        _ROOT (flight-reachable overworld territory), ("ow", K) for a
        NON_ROOT kingdom's overworld, ("full", sub) for an entry-capable
        interior mouth or a nested door inside a pooled interior stage,
        ("far", sub) for an exit-only interior mouth;
      * capable — entry_capable_interior_mouths(graph);
      * interior_stage_to_sub — pooled interior stage -> owning subarea;
      * subs — every pooled subarea with interior mouths."""
    capable = entry_capable_interior_mouths(graph)
    interior_stage_to_sub = {m.stage: m.subarea
                             for m in graph.mouths.values()
                             if m.side == INTERIOR}
    subs = {m.subarea for m in graph.mouths.values() if m.side == INTERIOR}

    def node(m: Mouth):
        if m.side == INTERIOR:
            return (("full" if m.mouth_id in capable else "far"), m.subarea)
        parent = interior_stage_to_sub.get(m.stage)
        if parent is not None:
            return ("full", parent)  # nested door: lives in a pooled interior
        if m.kingdom in NON_ROOT_KINGDOMS:
            return ("ow", m.kingdom)
        return _ROOT

    return node, capable, interior_stage_to_sub, subs


def directed_full_interior_strands(matching: dict[str, str],
                                   graph: PortGraph) -> set[str]:
    """Directed reachability holes the undirected checker cannot see
    (2026-07-17, found by the Mushroom-erratum roll perturbation).

    unconnected_stages treats every matched pair as an undirected edge, but
    the P3d wiring is DIRECTED at two points: (a) an edge into an exit-only
    interior mouth lands in the subarea's far-side region, which never flows
    back to the full interior (one-way course rule), and (b) a NON_ROOT
    kingdom's overworld (Mushroom) is only enterable through a portal, not by
    flight. So two subareas whose ONLY entry-capable mouths are paired with
    EACH OTHER read "connected" undirected (via their exit mouths' pairs) yet
    both full interiors — and every moon in them — deadlock: each is
    enterable only from the other. Seen live: seed-11 pairs
    (bike02@interior <-> ClashWorldMoonEX2@interior) and
    (EX_SkyBonus@interior <-> CostumeEventWorldLava@interior).

    Model (the abstract mirror of _wire_decoupled_entrances._mouth_region):
    nodes are <root> (all flight-reachable overworld territory, god-state
    view), ("ow", K) for each NON_ROOT kingdom's overworld, ("full", sub) and
    ("far", sub) per pooled subarea. A mouth maps to the node an arrival AT
    it grants (entry-capable interior -> full, exit-only -> far, nested door
    -> parent's full, overworld -> <root> or its NON_ROOT kingdom). Each pair
    contributes both directed edges, full -> far is free (course completion),
    and a lone vanilla-fixed overworld mouth credits its own subarea's full
    interior (vanilla passthrough). Returns the display names of stranded
    targets: subareas whose FULL interior is unreachable from <root>, plus
    any NON_ROOT kingdom whose overworld never gets a portal route. Empty ==
    the matching is directionally sound; roll_port_matching re-rolls until
    it is."""
    node, capable, interior_stage_to_sub, subs = _directed_model(graph)
    ROOT = _ROOT

    adj: dict[object, set] = defaultdict(set)
    for sub in subs:
        adj[("full", sub)].add(("far", sub))
    for a, b in matching.items():
        ma, mb = graph.mouths.get(a), graph.mouths.get(b)
        if ma is None or mb is None:
            continue
        if a == b:
            if (ma.side == OVERWORLD
                    and graph.vanilla_matching.get(a) == a
                    and ma.subarea in subs):
                adj[node(ma)].add(("full", ma.subarea))  # vanilla credit
            continue
        adj[node(ma)].add(node(mb))
        adj[node(mb)].add(node(ma))

    seen: set = {ROOT}
    stack: list = [ROOT]
    while stack:
        for nxt in adj[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)

    strands = {sub for sub in subs if ("full", sub) not in seen}
    non_root_kingdoms_pooled = {
        m.kingdom for m in graph.mouths.values()
        if m.side == OVERWORLD and m.kingdom in NON_ROOT_KINGDOMS
        and interior_stage_to_sub.get(m.stage) is None}
    strands |= {k for k in non_root_kingdoms_pooled if ("ow", k) not in seen}
    return strands


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
    # Directed-model guard (2026-07-17): never reserve an INTERIOR lone mouth
    # that is its subarea's only full-interior grant channel — the directed
    # phase 1 needs that mouth as a connection target (an interior fixed
    # point earns no vanilla credit, so reserving it would strand the
    # subarea's moons). Overworld lone mouths always stay eligible: their
    # vanilla credit still walks into their own subarea.
    node, _capable, _ists, _subs = _directed_model(graph)
    grant_channels: dict[str, int] = defaultdict(int)
    for m in graph.mouths.values():
        n = node(m)
        if n != _ROOT and n[0] == "full":
            grant_channels[n[1]] += 1

    def _grant_safe(mid: str) -> bool:
        m = graph.mouths[mid]
        if m.side == OVERWORLD:
            return True
        n = node(m)
        if n != _ROOT and n[0] == "full":
            return grant_channels[n[1]] > 1
        return True

    safe = [m for m in lone
            if (graph.mouths[m].stage in roots
                or by_stage[graph.mouths[m].stage] > 1)
            and _grant_safe(m)]
    fallback = [m for m in lone if _grant_safe(m)]
    return rng.choice(safe or fallback or lone)


def _interior_slack(graph: PortGraph, unmatched: set[str]) -> int:
    """#interior − #overworld over the unmatched pool — the topology
    constraint's feasibility margin (module docstring)."""
    slack = 0
    for m in unmatched:
        slack += 1 if graph.mouths[m].side == INTERIOR else -1
    return slack


def roll_port_matching(graph: PortGraph, rng: Random,
                       max_attempts: int = 25) -> dict[str, str]:
    """Roll a random total involution over `graph.mouths` such that every
    pooled stage is root-connected (see module docstring), no pair is
    OVERWORLD↔OVERWORLD (matching-topology constraint, Devon ruling
    2026-07-08), and the matching is DIRECTIONALLY sound — no full-interior
    deadlock and a real portal route into every NON_ROOT kingdom
    (directed_full_interior_strands). The frontier construction only
    guarantees undirected connectivity, so a completed roll is validated
    against the directed model and re-rolled from the still-advancing `rng`
    until clean (observed ~1-in-2 rolls need a retry on real data).
    Deterministic in `rng`; raises RuntimeError (loudly, at generation time)
    rather than ever returning an unsolvable or over-budget matching."""
    last_strands: set[str] = set()
    for attempt in range(1, max_attempts + 1):
        matching = _roll_port_matching_once(graph, rng)
        last_strands = directed_full_interior_strands(matching, graph)
        if not last_strands:
            if attempt > 1:
                logger.info(
                    "port_matching: directionally sound roll on attempt %d",
                    attempt)
            return matching
        logger.info(
            "port_matching: attempt %d directionally strands %s — re-rolling",
            attempt, sorted(last_strands))
    raise RuntimeError(
        f"port_matching: {max_attempts} rolls all directionally stranded "
        f"content (last: {sorted(last_strands)}) — pool shape changed under "
        "us; see directed_full_interior_strands")


def _roll_port_matching_once(graph: PortGraph, rng: Random) -> dict[str, str]:
    """One roll attempt: the undirected frontier construction + loud
    structural postconditions. Directed validation lives in the public
    wrapper above."""
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

    # Phase 1 — DIRECTED frontier growing (2026-07-17 rewrite; the earlier
    # undirected stage-frontier let phase 2 pair two subareas' only
    # entry-capable mouths with each other, a full-interior deadlock the
    # undirected checker can't see — directed_full_interior_strands has the
    # full story). Track the directed-model nodes actually REACHED and only
    # pair a frontier mouth usable FROM reached territory with a target
    # mouth whose ARRIVAL grant closes a need (a needed subarea's
    # entry-capable interior mouth / nested door, or a NON_ROOT kingdom's own
    # door). Each pairing full-connects one new subarea (or kingdom), so the
    # certificate is monotone and phase 2 can pair the remainder freely.
    node, capable, interior_stage_to_sub, all_subs = _directed_model(graph)

    reached: set = {_ROOT}

    def _mark_full(sub: str) -> None:
        reached.add(("full", sub))
        reached.add(("far", sub))  # course completion is free (full -> far)

    # Vanilla-credit closure: pins and the reserved parity fixed point are
    # vanilla passthroughs whose overworld mouth still walks into its own
    # subarea. Closure form because a pin can itself sit in a not-yet-reached
    # nested stage (nested course entrance).
    fixed_vanilla = list(pinned)
    if fixed_point is not None:
        fixed_vanilla.append(fixed_point)

    def _apply_fixed_credit() -> None:
        changed = True
        while changed:
            changed = False
            for mid in fixed_vanilla:
                m = graph.mouths[mid]
                if (m.side == OVERWORLD
                        and graph.vanilla_matching.get(mid) == mid
                        and m.subarea in all_subs
                        and ("full", m.subarea) not in reached
                        and node(m) in reached):
                    _mark_full(m.subarea)
                    changed = True

    _apply_fixed_credit()

    def _grant(mid: str):
        """The need a pairing ARRIVING at `mid` would close, else None."""
        n = node(graph.mouths[mid])
        if n == _ROOT or n[0] == "far":
            return None
        return n  # ("full", sub) or ("ow", kingdom)

    non_root_kingdom_nodes = {
        ("ow", m.kingdom) for m in graph.mouths.values()
        if m.side == OVERWORLD and m.kingdom in NON_ROOT_KINGDOMS
        and interior_stage_to_sub.get(m.stage) is None}

    while True:
        need = {("full", s) for s in all_subs} | non_root_kingdom_nodes
        need -= reached
        if not need:
            break
        targets = sorted(mid for mid in unmatched if _grant(mid) in need)
        if not targets:
            raise RuntimeError(
                "port_matching: needs "
                f"{sorted(need)} have no unmatched granting mouths left "
                "— cannot be root-connected by any completion of this roll")
        frontier = sorted(mid for mid in unmatched
                          if node(graph.mouths[mid]) in reached)
        if not frontier:
            raise RuntimeError(
                "port_matching: no unmatched mouths left in reached "
                f"territory while {sorted(need)} cannot be root-connected "
                "(root-side mouth supply exhausted)")
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
                "the no-overworld↔overworld constraint while "
                f"{sorted(need)} remain unconnected")
        matching[a] = b
        matching[b] = a
        unmatched.discard(a)
        unmatched.discard(b)
        got = _grant(b)
        if got[0] == "full":
            _mark_full(got[1])
        else:
            reached.add(got)
        _apply_fixed_credit()

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
