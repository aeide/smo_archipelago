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


def test_vanilla_matching_is_fully_connected(graph):
    # The physical layout must satisfy our own checker — validates both the
    # checker and the HomeStage root convention against real extracted data.
    assert unconnected_stages(graph.vanilla_matching, graph) == set()


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


def test_refight_painting_arenas_stay_vanilla(graph):
    # The 6 Mushroom boss re-fight arenas have NO walkable interior exit
    # (scripted return) — shuffling their painting entry would orphan the
    # arena and its Multi-Moon. port_graph must keep them out of the pool
    # entirely (one-way-ENTRY rule, P3c erratum in its docstring).
    refight = {m.subarea for m in graph.mouths.values()
               if "Re-fight" in m.subarea}
    assert refight == set(), f"re-fight arenas leaked into pool: {refight}"
    assert any("PictureBoss" in d for d in graph.dropped_doors), (
        "re-fight painting doors should be recorded in dropped_doors")


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
