"""P3c — port_matching.py unit tests (connectivity-guaranteed involution).

No Archipelago imports; runs directly against the source tree, same style as
test_port_graph.py. Design authority: docs/design-decoupled-kingdom-order.md
and docs/plan-decoupled-entrances.md §3c.
"""

from __future__ import annotations

import json
from pathlib import Path
from random import Random

import pytest

from port_graph import (
    INTERIOR,
    OVERWORLD,
    Mouth,
    PortGraph,
    build_port_graph,
    estimate_remap_rows,
    is_involution,
)
from port_matching import (
    ROW_HEADROOM,
    ROW_TABLE_CAP,
    roll_port_matching,
    root_stages,
    stage_nodes,
    unconnected_stages,
)

APWORLD_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APWORLD_ROOT / "data"

MANY_SEEDS = 200


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def graph():
    return build_port_graph(
        _load("entrance_stages.json"), _load("subareas.json"),
        _load("entrance_exclusions.json"))


@pytest.fixture(scope="module")
def festival_graph():
    return build_port_graph(
        _load("entrance_stages.json"), _load("subareas.json"),
        _load("entrance_exclusions.json"), festival=True)


# ---------------------------------------------------------------------------
# Mini-fixture builders (hand-built PortGraphs — the matching layer's input
# contract is PortGraph, so adversarial shapes are constructed directly)
# ---------------------------------------------------------------------------

def _mouth(door: str, side: str, stage: str, sub: str,
           kingdom: str = "Test Kingdom") -> Mouth:
    return Mouth(door_port_id=door, side=side, stage=stage,
                 entry_id=door.split("#")[-1], subarea=sub,
                 kingdom=kingdom, ingest=True)


def _add_two_way(mouths, vanilla, door, ow_stage, in_stage, sub):
    ow = _mouth(door, OVERWORLD, ow_stage, sub)
    inn = _mouth(door, INTERIOR, in_stage, sub)
    mouths[ow.mouth_id] = ow
    mouths[inn.mouth_id] = inn
    vanilla[ow.mouth_id] = inn.mouth_id
    vanilla[inn.mouth_id] = ow.mouth_id


def _add_lone_interior(mouths, vanilla, door, in_stage, sub):
    inn = _mouth(door, INTERIOR, in_stage, sub)
    mouths[inn.mouth_id] = inn
    vanilla[inn.mouth_id] = inn.mouth_id  # lone ingest = vanilla self-map


def adversarial_graph() -> PortGraph:
    """The strandable nested-cluster shape from the plan doc: subarea A (two
    doors off the kingdom home), subarea B nested INSIDE A's stage, subarea C
    off the home. A naive uniform matching frequently pairs A's mouths among
    themselves + B within the cluster, stranding A+B; the frontier roller
    must never emit that."""
    mouths: dict[str, Mouth] = {}
    vanilla: dict[str, str] = {}
    _add_two_way(mouths, vanilla, "TestWorldHomeStage#AEnt1",
                 "TestWorldHomeStage", "AExStage", "Sub A")
    _add_two_way(mouths, vanilla, "TestWorldHomeStage#AEnt2",
                 "TestWorldHomeStage", "AExStage", "Sub A")
    _add_two_way(mouths, vanilla, "AExStage#BEnt",
                 "AExStage", "BExStage", "Sub B")   # nested in A
    _add_two_way(mouths, vanilla, "TestWorldHomeStage#CEnt",
                 "TestWorldHomeStage", "CExStage", "Sub C")
    return PortGraph(mouths=mouths, vanilla_matching=vanilla,
                     dropped_doors=[])


def odd_pool_graph() -> PortGraph:
    """Adversarial graph + one lone exit-pipe mouth (Dokan shape) => odd
    pool, so the roller must produce exactly one fixed point and put it on
    the lone (vanilla self-mapped) mouth."""
    g = adversarial_graph()
    _add_lone_interior(g.mouths, g.vanilla_matching,
                       "TestWorldHomeStage#ADokan", "AExStage", "Sub A")
    return g


def rootless_graph() -> PortGraph:
    """Mutually-nested cluster: each subarea's overworld mouth lives in the
    OTHER's interior stage, so every stage is a pooled interior and no root
    exists => nothing can ever be root-connected."""
    mouths: dict[str, Mouth] = {}
    vanilla: dict[str, str] = {}
    _add_two_way(mouths, vanilla, "YExStage#XEnt",
                 "YExStage", "XExStage", "Sub X")
    _add_two_way(mouths, vanilla, "XExStage#YEnt",
                 "XExStage", "YExStage", "Sub Y")
    return PortGraph(mouths=mouths, vanilla_matching=vanilla,
                     dropped_doors=[])


def zone_split_graph() -> PortGraph:
    """The zone-split shape from real data: Sub E's door is bisected into a
    lone overworld half (door actor in a town ZONE) and a lone interior half
    (exit records the parent HomeStage), both vanilla self-mapped. Sub F is
    an exit-only pipe interior. Reaching FExStage requires crediting E's
    vanilla-fixed overworld half as an entry edge into EExStage."""
    mouths: dict[str, Mouth] = {}
    vanilla: dict[str, str] = {}
    ow = _mouth("ZWorldTownZone#EDoor", OVERWORLD, "ZWorldTownZone", "Sub E")
    mouths[ow.mouth_id] = ow
    vanilla[ow.mouth_id] = ow.mouth_id
    _add_lone_interior(mouths, vanilla, "ZWorldHomeStage#EDoor",
                       "EExStage", "Sub E")
    _add_lone_interior(mouths, vanilla, "ZWorldHomeStage#FDokan",
                       "FExStage", "Sub F")
    return PortGraph(mouths=mouths, vanilla_matching=vanilla,
                     dropped_doors=[])


# ---------------------------------------------------------------------------
# The connectivity model itself (roots + checker) against real data
# ---------------------------------------------------------------------------

def test_roots_include_homestages_and_zones(graph):
    roots = root_stages(graph)
    home = {s for s in roots if s.endswith("HomeStage")}
    assert len(home) >= 10, f"suspiciously few HomeStage roots: {sorted(home)}"
    # Real-data zone shapes must root (walkable parts of the overworld map).
    assert "SkyWorldCastleZone" in roots
    assert "LakeWorldTownZone" in roots


def test_mushroom_stages_never_root(graph):
    # Mushroom erratum (module docstring): the MK overworld is post-game and
    # NOT flight-reachable pre-goal, so no stage hosting a Mushroom mouth may
    # anchor connectivity — the matching must earn MK a real route.
    roots = root_stages(graph)
    assert "PeachWorldHomeStage" not in roots
    mk_stages = {m.stage for m in graph.mouths.values()
                 if m.kingdom == "Mushroom Kingdom"}
    assert mk_stages, "Mushroom mouths vanished from the pool (D9 regression?)"
    assert not (roots & mk_stages), sorted(roots & mk_stages)


def test_no_root_is_a_pooled_interior(graph):
    interiors = {m.stage for m in graph.mouths.values()
                 if m.side == INTERIOR}
    bad = {s for s in root_stages(graph)
           if s in interiors and not s.endswith("HomeStage")}
    assert not bad, f"pooled interior stages claimed as roots: {sorted(bad)}"


def test_no_interior_stage_is_a_homestage(graph):
    # Belt-and-braces clause in root_stages: HomeStages root unconditionally,
    # which is only safe while no subarea interior IS a HomeStage.
    for m in graph.mouths.values():
        if m.side == INTERIOR:
            assert not m.stage.endswith("HomeStage"), m.mouth_id


def test_vanilla_matching_strands_exactly_the_mushroom_cluster(graph):
    # The physical layout must satisfy our own checker — validates both the
    # checker and the HomeStage root convention against real extracted data.
    # EXCEPT the Mushroom cluster: vanilla MK access is the credits warp, not
    # a walkable route, so under the Mushroom erratum the vanilla matching
    # genuinely strands PeachWorldHomeStage + its subarea interiors — and
    # nothing else. (The roller never leaves MK on vanilla: phase 1 wires it
    # to rooted territory, asserted by the roll tests below.)
    mk_stages = {m.stage for m in graph.mouths.values()
                 if m.kingdom == "Mushroom Kingdom"}
    assert unconnected_stages(graph.vanilla_matching, graph) == mk_stages


def test_checker_flags_hand_built_strand():
    g = adversarial_graph()
    m = {}
    # A's interiors pair with each other, A's overworld mouths pair with each
    # other, B pairs vanilla within the cluster, C pairs vanilla: A+B strand.
    a1o, a1i = "TestWorldHomeStage#AEnt1@overworld", "TestWorldHomeStage#AEnt1@interior"
    a2o, a2i = "TestWorldHomeStage#AEnt2@overworld", "TestWorldHomeStage#AEnt2@interior"
    bo, bi = "AExStage#BEnt@overworld", "AExStage#BEnt@interior"
    co, ci = "TestWorldHomeStage#CEnt@overworld", "TestWorldHomeStage#CEnt@interior"
    m[a1i], m[a2i] = a2i, a1i
    m[a1o], m[a2o] = a2o, a1o
    m[bo], m[bi] = bi, bo
    m[co], m[ci] = ci, co
    assert is_involution(m, g.mouths)
    assert unconnected_stages(m, g) == {"AExStage", "BExStage"}


def test_stage_nodes_cover_nested_parent():
    g = adversarial_graph()
    assert "AExStage" in stage_nodes(g)          # nested parent is a node
    assert "TestWorldHomeStage" in root_stages(g)
    assert "AExStage" not in root_stages(g)      # and NOT a root


def test_checker_credits_vanilla_fixed_overworld_lone():
    g = zone_split_graph()
    ow = "ZWorldTownZone#EDoor@overworld"
    e_int = "ZWorldHomeStage#EDoor@interior"
    f_int = "ZWorldHomeStage#FDokan@interior"
    # E's overworld half stays vanilla-fixed => credited entry into EExStage;
    # E's interior half matched to F's pipe links FExStage through it.
    good = {ow: ow, e_int: f_int, f_int: e_int}
    assert is_involution(good, g.mouths)
    assert unconnected_stages(good, g) == set()
    # Interior fixed points earn NO credit (one-way OUT): fixing F's pipe and
    # pairing E's two halves leaves FExStage stranded.
    bad = {ow: e_int, e_int: ow, f_int: f_int}
    assert is_involution(bad, g.mouths)
    assert unconnected_stages(bad, g) == {"FExStage"}


def mushroom_graph() -> PortGraph:
    """Adversarial graph + a Mushroom door to a sole-mouth shop interior —
    the dead-end shape from evidence seed 91455467025183402260 (an MK door
    paired with a sole-mouth partner gives that interior no way in except
    FROM Mushroom, so it can't be Mushroom's route)."""
    g = adversarial_graph()
    ow = _mouth("PeachWorldHomeStage#MkShopDoor", OVERWORLD,
                "PeachWorldHomeStage", "MK Shop", kingdom="Mushroom Kingdom")
    inn = _mouth("PeachWorldHomeStage#MkShopDoor", INTERIOR,
                 "MkShopStage", "MK Shop", kingdom="Mushroom Kingdom")
    g.mouths[ow.mouth_id] = ow
    g.mouths[inn.mouth_id] = inn
    g.vanilla_matching[ow.mouth_id] = inn.mouth_id
    g.vanilla_matching[inn.mouth_id] = ow.mouth_id
    return g


def test_checker_flags_mushroom_dead_end():
    # All-vanilla completion: the MK door <-> its own shop is a closed loop
    # with no root, so exactly the MK cluster must read unconnected.
    g = mushroom_graph()
    m = dict(g.vanilla_matching)
    assert is_involution(m, g.mouths)
    assert unconnected_stages(m, g) == {"PeachWorldHomeStage", "MkShopStage"}


def test_roller_always_routes_mushroom(graph):
    # Real pool: every roll must give Mushroom a route witness — at least one
    # MK door whose partner mouth lives in territory that is root-connected
    # WITHOUT any MK-door pair (i.e. the route into PeachWorldHomeStage never
    # bootstraps through Mushroom itself). Walk that partner's stage, use the
    # partner mouth, portal-land at the MK door: the pre-goal MK arrival.
    mk_doors = {m.mouth_id for m in graph.mouths.values()
                if m.side == OVERWORLD and m.kingdom == "Mushroom Kingdom"}
    assert mk_doors, "no pooled MK doors (D9 regression?)"
    nodes = stage_nodes(graph)
    for seed in range(50):
        m = roll_port_matching(graph, Random(seed))
        assert unconnected_stages(m, graph) == set(), f"seed {seed}"
        reduced = {a: b for a, b in m.items()
                   if a not in mk_doors and b not in mk_doors}
        connected_sans_mk = nodes - unconnected_stages(reduced, graph)
        witnesses = [
            a for a in mk_doors
            if m.get(a) is not None and m[a] != a
            and graph.mouths[m[a]].stage in connected_sans_mk]
        assert witnesses, (
            f"seed {seed}: no MK door partnered into rooted territory — "
            "Mushroom has no pre-goal route")


# ---------------------------------------------------------------------------
# roll_port_matching — hard requirements, real pool
# ---------------------------------------------------------------------------

def test_many_seeds_valid_involution_and_connected(graph):
    for seed in range(MANY_SEEDS):
        m = roll_port_matching(graph, Random(seed))
        assert is_involution(m, graph.mouths), f"seed {seed}"
        assert unconnected_stages(m, graph) == set(), f"seed {seed}"


def test_row_budget_many_seeds(graph):
    budget = ROW_TABLE_CAP - ROW_HEADROOM
    for seed in range(0, MANY_SEEDS, 10):
        m = roll_port_matching(graph, Random(seed))
        rows = estimate_remap_rows(m, graph.vanilla_matching)
        assert rows <= budget, f"seed {seed}: {rows} > {budget}"


def test_deterministic_per_seed(graph):
    assert roll_port_matching(graph, Random(12345)) == \
        roll_port_matching(graph, Random(12345))


def test_distinct_seeds_differ(graph):
    assert roll_port_matching(graph, Random(1)) != \
        roll_port_matching(graph, Random(2))


def test_festival_pool_variant(festival_graph):
    for seed in range(20):
        m = roll_port_matching(festival_graph, Random(seed))
        assert is_involution(m, festival_graph.mouths), f"seed {seed}"
        assert unconnected_stages(m, festival_graph) == set(), f"seed {seed}"


# ---------------------------------------------------------------------------
# Matching-topology constraint (Devon ruling 2026-07-08, plan doc P4 item 9):
# no OVERWORLD↔OVERWORLD pair, ever. Replaces the "free matching" ruling 3(a).
# ---------------------------------------------------------------------------

def _overworld_overworld_pairs(m: dict[str, str], mouths) -> list[str]:
    return sorted(a for a, b in m.items()
                  if a != b
                  and mouths[a].side == OVERWORLD
                  and mouths[b].side == OVERWORLD)


def test_no_overworld_overworld_pairs_many_seeds(graph):
    for seed in range(MANY_SEEDS):
        m = roll_port_matching(graph, Random(seed))
        oo = _overworld_overworld_pairs(m, graph.mouths)
        assert oo == [], f"seed {seed}: O↔O pairs {oo}"


def test_no_overworld_overworld_pairs_festival(festival_graph):
    for seed in range(20):
        m = roll_port_matching(festival_graph, Random(seed))
        oo = _overworld_overworld_pairs(m, festival_graph.mouths)
        assert oo == [], f"seed {seed}: O↔O pairs {oo}"


def test_real_pool_interior_slack_nonnegative(graph):
    # Feasibility-by-construction guard (plan doc item 9): every overworld
    # mouth has a vanilla interior partner and multi-exit subareas add
    # surplus interiors, so #interior >= #overworld. If a data change ever
    # breaks this, the constraint becomes unsatisfiable — fail here, in the
    # data-shape test, not inside a generation.
    n_i = sum(1 for m in graph.mouths.values() if m.side == INTERIOR)
    n_o = sum(1 for m in graph.mouths.values() if m.side == OVERWORLD)
    assert n_i >= n_o, f"interior {n_i} < overworld {n_o}"


def test_zero_slack_pool_completes_with_all_o_i_pairs():
    # adversarial_graph is 4 two-way doors = 4 overworld + 4 interior mouths
    # (slack 0): the roller must emit ONLY O–I pairs — a single I–I pair
    # would strand two overworld mouths with no legal partner.
    g = adversarial_graph()
    n_i = sum(1 for m in g.mouths.values() if m.side == INTERIOR)
    n_o = sum(1 for m in g.mouths.values() if m.side == OVERWORLD)
    assert n_i == n_o, "fixture drifted: expected a zero-slack pool"
    for seed in range(MANY_SEEDS):
        m = roll_port_matching(g, Random(seed))
        assert is_involution(m, g.mouths), f"seed {seed}"
        assert unconnected_stages(m, g) == set(), f"seed {seed}"
        for a, b in m.items():
            if a == b:
                continue
            assert {g.mouths[a].side, g.mouths[b].side} == \
                {OVERWORLD, INTERIOR}, f"seed {seed}: {a} <-> {b}"


# ---------------------------------------------------------------------------
# roll_port_matching — adversarial / degenerate shapes
# ---------------------------------------------------------------------------

def test_adversarial_cluster_never_strands():
    g = adversarial_graph()
    for seed in range(MANY_SEEDS):
        m = roll_port_matching(g, Random(seed))
        assert is_involution(m, g.mouths), f"seed {seed}"
        assert unconnected_stages(m, g) == set(), f"seed {seed}"


def test_odd_pool_fixed_point_is_lone_mouth():
    g = odd_pool_graph()
    lone = "TestWorldHomeStage#ADokan@interior"
    for seed in range(MANY_SEEDS):
        m = roll_port_matching(g, Random(seed))
        assert is_involution(m, g.mouths), f"seed {seed}"
        assert unconnected_stages(m, g) == set(), f"seed {seed}"
        fixed = [k for k, v in m.items() if k == v]
        assert fixed == [lone], f"seed {seed}: fixed points {fixed}"


def test_odd_pool_fixed_point_costs_no_row():
    g = odd_pool_graph()
    m = roll_port_matching(g, Random(7))
    lone = "TestWorldHomeStage#ADokan@interior"
    # vanilla self-map == rolled self-map => no deviation => no rewrite row.
    deviating = {a for a, b in m.items()
                 if g.vanilla_matching.get(a) != b}
    assert lone not in deviating


def test_empty_pool_returns_empty():
    g = PortGraph(mouths={}, vanilla_matching={}, dropped_doors=[])
    assert roll_port_matching(g, Random(0)) == {}


def test_rootless_pool_raises_loudly():
    g = rootless_graph()
    with pytest.raises(RuntimeError, match="root-connected"):
        roll_port_matching(g, Random(0))


REFIGHT_SUBAREAS = {
    "Knucklotec Boss Re-fight", "Torkdrift Boss Re-fight",
    "Mechawiggler Boss Re-fight", "Mollusque-Lanceur Boss Re-fight",
    "Cookatiel Boss Re-fight", "Lord of Lightning Boss Re-fight",
}


def test_refight_towers_pooled_arena_loop_vanilla(graph):
    # MK tower pooling (Devon ruling 2026-07-18): the 6 "… Boss Re-fight"
    # records are re-pointed at the TOWER rooms (PeachWorldPicture*Stage) —
    # real two-way subareas — so the re-fight Multi-Moon checks key on
    # shuffled tower access. The painting -> RevengeBoss*Stage arena ->
    # Multi-Moon return-to-tower loop INSIDE the tower stays fully vanilla:
    # no mouth may ever reference an arena stage or a PictureBoss* painting
    # id, else the shuffle could remap the painting or the post-boss return.
    pooled = {m.subarea for m in graph.mouths.values()
              if m.subarea in REFIGHT_SUBAREAS}
    assert pooled == REFIGHT_SUBAREAS, (
        f"re-fight towers missing from pool: {REFIGHT_SUBAREAS - pooled}")
    for m in graph.mouths.values():
        assert "Revenge" not in m.stage, f"arena stage pooled: {m}"
        assert not m.entry_id.startswith("Picture"), f"painting id pooled: {m}"
    # Every tower is two-way: interior ingest mouths exist (the one-way-ENTRY
    # rule must NOT fire for them anymore).
    for sub in REFIGHT_SUBAREAS:
        assert any(m.side == INTERIOR for m in graph.mouths.values()
                   if m.subarea == sub), f"{sub}: no interior ingest mouth"


def test_refight_towers_drop_under_festival(festival_graph):
    # Mushroom is festival-excluded (FESTIVAL_EXCLUDED_KINGDOMS), so tower
    # pooling must be inert under goal=festival — the Rematch locations do
    # not even exist there.
    pooled = {m.subarea for m in festival_graph.mouths.values()
              if m.subarea in REFIGHT_SUBAREAS}
    assert pooled == set(), f"towers pooled under festival: {pooled}"


def test_zone_alias_never_covers_a_pooled_interior_stage(graph):
    # ZONE_STAGE_ALIAS rewrites OVERWORLD-mouth targets to a parent
    # HomeStage. If an alias key were also a pooled subarea's INTERIOR
    # stage, a portal targeting that interior could be rewritten to the
    # overworld instead — exactly the bug the 2026-07-18 tower erratum
    # removed (the six PeachWorldPicture*Stage entries were mis-classified
    # as zones; they are real pooled tower interiors).
    from port_graph import ZONE_STAGE_ALIAS
    interior_stages = {m.stage for m in graph.mouths.values()
                       if m.side == INTERIOR}
    overlap = interior_stages & set(ZONE_STAGE_ALIAS)
    assert overlap == set(), f"alias shadows pooled interior stage(s): {overlap}"


def test_every_pooled_subarea_has_interior_ingest(graph):
    # Orphan-proofing invariant (enforced by port_graph's one-way-ENTRY
    # rule): every subarea contributing mouths owns >=1 interior ingest
    # mouth, so its interior can always be a shuffle destination.
    subareas_with_interior = {m.subarea for m in graph.mouths.values()
                              if m.side == INTERIOR}
    for m in graph.mouths.values():
        assert m.subarea in subareas_with_interior, (
            f"subarea '{m.subarea}' has pooled mouths but no interior "
            f"ingest mouth (via {m.mouth_id})")


# ---------------------------------------------------------------------------
# One-way-course pinning (Devon ruling 2026-07-08)
# ---------------------------------------------------------------------------

def one_way_course_graph() -> PortGraph:
    """Adversarial-style pool + a one-way course: entry door (lone overworld,
    'aaa' shape) + exit pipe (lone interior, different entry_id). The roller
    must pin the entry vanilla and keep the exit shuffleable."""
    g = adversarial_graph()
    ow = _mouth("TestWorldHomeStage#courseIn", OVERWORLD,
                "TestWorldHomeStage", "Course")
    inn = _mouth("TestWorldHomeStage#courseOut", INTERIOR,
                 "CourseExStage", "Course")
    g.mouths[ow.mouth_id] = ow
    g.mouths[inn.mouth_id] = inn
    g.vanilla_matching[ow.mouth_id] = ow.mouth_id    # lone halves
    g.vanilla_matching[inn.mouth_id] = inn.mouth_id
    return g


def test_one_way_entry_pinned_and_exit_shuffles():
    from port_graph import pinned_one_way_entry_mouths
    g = one_way_course_graph()
    pins = pinned_one_way_entry_mouths(g)
    assert pins == {"TestWorldHomeStage#courseIn@overworld"}
    for seed in range(40):
        m = roll_port_matching(g, Random(seed))
        for pin in pins:
            assert m[pin] == pin, f"seed {seed}: pinned entry was re-matched"
        # The course's exit mouth stays in the involution (self or partner —
        # never dropped), and the roll's own postconditions (involution,
        # no O-O, connectivity, budget) all passed by construction.
        assert "TestWorldHomeStage#courseOut@interior" in m


def test_real_pool_pins_stay_fixed(graph):
    from port_graph import pinned_one_way_entry_mouths
    pins = pinned_one_way_entry_mouths(graph)
    for seed in (1, 11, 22, 33):
        m = roll_port_matching(graph, Random(seed))
        for pin in pins:
            assert m[pin] == pin
