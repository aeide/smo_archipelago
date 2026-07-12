"""P3b — port_graph.py unit tests (decoupled entrance rando data model).

No Archipelago imports; runs directly against the source tree, same style as
test_entrance_shuffle.py. Design authority: docs/design-decoupled-kingdom-order.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from entrance_logic import build_moonpipe_subarea_set
from port_graph import (
    DECOUPLED_EXCLUDED_KINGDOMS,
    FESTIVAL_EXCLUDED_KINGDOMS,
    INTERIOR,
    OVERWORLD,
    ROW_HEADROOM,
    ROW_TABLE_CAP,
    Mouth,
    PortGraph,
    build_port_graph,
    compile_port_remaps,
    estimate_remap_rows,
    is_involution,
    mouth_cost,
)

APWORLD_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APWORLD_ROOT / "data"


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


@pytest.fixture(scope="module")
def moonpipes():
    return build_moonpipe_subarea_set(_load("subareas.json"), _load("locations.json"))


# ---------------------------------------------------------------------------
# Schema + enumeration
# ---------------------------------------------------------------------------

def test_schema_v1_rejected():
    with pytest.raises(ValueError, match="schema v2"):
        build_port_graph({"Some Subarea": {}}, {}, {})


def test_pool_size_sane(graph):
    # P1 counted 331 raw entries+exits halves over the 119-subarea pool;
    # the ingest-mouth pool must be the same order of magnitude. A collapse
    # (mass-merge or mass-drop) or explosion fails loudly here.
    n = len(graph.mouths)
    assert 150 <= n <= 450, f"ingest mouth pool badly sized: {n}"


def test_every_mouth_sound_and_ingest(graph):
    for m in graph.mouths.values():
        assert m.sound, f"unsound mouth in pool: {m.mouth_id}"
        assert m.ingest, f"non-ingest mouth in pool: {m.mouth_id}"


def test_mouth_ids_unique_per_side(graph):
    # dict keys enforce uniqueness; check the id embeds the side so the two
    # mouths of one door never collide.
    for mid, m in graph.mouths.items():
        assert mid.endswith(f"@{m.side}")


# ---------------------------------------------------------------------------
# Push Block Peril — the P0-validated shapes
# ---------------------------------------------------------------------------

def test_pbp_main_door_both_mouths_in_pool(graph):
    ow = "CapWorldHomeStage#PushBlockExStageEnt@overworld"
    inn = "CapWorldHomeStage#PushBlockExStageEnt@interior"
    assert ow in graph.mouths and inn in graph.mouths
    assert graph.mouths[inn].stage == "PushBlockExStage"
    assert graph.mouths[ow].stage == "CapWorldHomeStage"


def test_pbp_pipe_interior_ingest_overworld_not(graph):
    # The Dokan pipe is exit-only: its interior mouth is walkable (you leave
    # through it — P0 walked it), its overworld mouth is a marker only.
    inn = "CapWorldHomeStage#PushBlockExStageEntDokan@interior"
    ow = "CapWorldHomeStage#PushBlockExStageEntDokan@overworld"
    assert inn in graph.mouths, "pipe interior mouth must be matchable"
    assert ow not in graph.mouths, "pipe overworld mouth is emit-only"


def test_pbp_two_interior_mouths_distinct(graph):
    # The P0 retrace bug shape: the stage's two exits are two distinct nodes.
    a = graph.mouths.get("CapWorldHomeStage#PushBlockExStageEnt@interior")
    b = graph.mouths.get("CapWorldHomeStage#PushBlockExStageEntDokan@interior")
    assert a and b and a.entry_id != b.entry_id


# ---------------------------------------------------------------------------
# D5 exclusions (door-wise) + festival
# ---------------------------------------------------------------------------

def test_excluded_kingdoms_have_no_mouths(graph):
    for m in graph.mouths.values():
        assert m.kingdom not in DECOUPLED_EXCLUDED_KINGDOMS, (
            f"D5 leak: {m.mouth_id} from excluded kingdom {m.kingdom} — "
            "exclusion must propagate door-wise (interior mouths too)")


def test_mushroom_and_ruined_present(graph):
    # Devon's D5 modification: Mushroom + Ruined ARE in the pool.
    kingdoms = {m.kingdom for m in graph.mouths.values()}
    assert "Mushroom Kingdom" in kingdoms
    assert "Ruined Kingdom" in kingdoms


def test_festival_drops_post_metro(festival_graph):
    kingdoms = {m.kingdom for m in festival_graph.mouths.values()}
    assert not (kingdoms & FESTIVAL_EXCLUDED_KINGDOMS)
    # Pre-Metro kingdoms survive.
    assert "Cap Kingdom" in kingdoms and "Metro Kingdom" in kingdoms


def test_festival_exclusions_cover_init_tuple():
    # FESTIVAL_EXCLUDED_KINGDOMS must contain every REAL kingdom named in
    # SMOWorld.FESTIVAL_REGIONS_TO_EMPTY (helper regions like 'Pokino' and
    # 'Very Early Luncheon' aren't entrance_stages kingdoms and are exempt).
    src = (APWORLD_ROOT / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"FESTIVAL_REGIONS_TO_EMPTY = \((.*?)\)", src, re.DOTALL)
    assert m, "FESTIVAL_REGIONS_TO_EMPTY not found in __init__.py"
    names = set(re.findall(r'"([^"]+)"', m.group(1)))
    real = {n for n in names if n.endswith("Kingdom")}
    missing = real - FESTIVAL_EXCLUDED_KINGDOMS
    assert not missing, f"festival exclusion drift vs __init__.py: {missing}"


# ---------------------------------------------------------------------------
# Vanilla matching is a valid involution
# ---------------------------------------------------------------------------

def test_vanilla_matching_is_involution(graph):
    assert is_involution(graph.vanilla_matching, graph.mouths)


def test_vanilla_two_way_doors_cross_matched(graph):
    ow = "CapWorldHomeStage#PushBlockExStageEnt@overworld"
    inn = "CapWorldHomeStage#PushBlockExStageEnt@interior"
    assert graph.vanilla_matching[ow] == inn
    assert graph.vanilla_matching[inn] == ow


def test_vanilla_lone_ingest_is_identity(graph):
    inn = "CapWorldHomeStage#PushBlockExStageEntDokan@interior"
    # identity = "no rewrite row" = vanilla passthrough
    assert graph.vanilla_matching[inn] == inn


def test_vanilla_rows_zero(graph):
    # The vanilla involution must compile to ZERO rewrite rows (vanilla is
    # the baseline, so nothing deviates from it).
    assert estimate_remap_rows(graph.vanilla_matching,
                               graph.vanilla_matching) == 0


def test_one_swapped_pair_costs_four_rows(graph):
    # Swapping the partners of two vanilla two-way doors deviates FOUR mouths
    # from vanilla (both mouths of both doors) — the estimator must count
    # per-mouth rows, not per-edge.
    m = dict(graph.vanilla_matching)
    two_way = [a for a, b in m.items() if a != b]
    a = two_way[0]
    b = next(x for x in two_way
             if x not in (a, m[a]) and m[x] not in (a, m[a]))
    a2, b2 = m[a], m[b]
    m[a], m[b2] = b2, a
    m[b], m[a2] = a2, b
    assert is_involution(m, graph.mouths)
    assert estimate_remap_rows(m, graph.vanilla_matching) == 4


def test_full_shuffle_row_budget_fits(graph):
    # Worst case: every ingest mouth non-identity — one row each. Must fit
    # the P2 table cap (kEntranceRemapMax = 512) with headroom.
    assert len(graph.mouths) <= 512 - 32, (
        "mouth pool approaching the Switch remap table cap")


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

def test_interior_cost_mini_rocket(graph, moonpipes):
    # 'A Sea of Clouds' is a mini-rocket sky subarea: leaving needs the rocket.
    for m in graph.mouths.values():
        if m.subarea == "A Sea of Clouds" and m.side == INTERIOR:
            assert "|Mini Rocket|" in mouth_cost(m, moonpipes).requires
            break
    else:
        pytest.skip("A Sea of Clouds has no interior ingest mouth in pool")


def test_overworld_cost_jaxi_mixed_gate(graph, moonpipes):
    # Jaxi Driving's door gate mixes {SandPeace()} with items — must ride the
    # overworld mouth cost verbatim.
    for m in graph.mouths.values():
        if m.subarea == "Jaxi Driving" and m.side == OVERWORLD:
            c = mouth_cost(m, moonpipes)
            assert "{SandPeace()}" in c.requires
            break
    else:
        pytest.skip("Jaxi Driving not in pool")


def test_overworld_cost_metro_kingdom_gate(graph, moonpipes):
    # Every Metro overworld mouth carries the Spark pylon kingdom gate.
    checked = 0
    for m in graph.mouths.values():
        if m.kingdom == "Metro Kingdom" and m.side == OVERWORLD:
            assert "|Spark pylon|" in mouth_cost(m, moonpipes).requires
            checked += 1
    assert checked > 0


def test_moonpipe_overworld_mouths_carry_peace_func(graph, moonpipes):
    found = 0
    for m in graph.mouths.values():
        if m.subarea in moonpipes and m.side == OVERWORLD:
            c = mouth_cost(m, moonpipes)
            prefix_has_peace = c.peace_func is not None
            # Cap/Cloud/Lost pipes have no peace func (peace == reachability).
            if m.kingdom not in ("Cap Kingdom", "Cloud Kingdom", "Lost Kingdom"):
                assert prefix_has_peace, f"missing peace func on {m.mouth_id}"
            found += 1
    if not found:
        pytest.skip("no moon-pipe overworld mouths in pool")


def test_interior_cost_never_carries_peace(graph, moonpipes):
    for m in graph.mouths.values():
        if m.side == INTERIOR:
            assert mouth_cost(m, moonpipes).peace_func is None


# ---------------------------------------------------------------------------
# P3e — compile_port_remaps (row compiler)
# ---------------------------------------------------------------------------
# A small hand-built two-door graph (no data file dependency) so row-shape
# assertions are exact and don't depend on which real subarea happens to have
# which gates today. `estimate_remap_rows` correctness against the REAL pool
# is covered separately below via a real roll.

def _mouth(door, side, stage, entry_id, subarea, kingdom="Kingdom X"):
    return Mouth(door_port_id=door, side=side, stage=stage, entry_id=entry_id,
                subarea=subarea, kingdom=kingdom, ingest=True)


@pytest.fixture
def tiny_graph():
    ow1 = _mouth("doorA", OVERWORLD, "KingdomHomeA", "entA", "SubareaA")
    in1 = _mouth("doorA", INTERIOR, "InteriorA", "entA", "SubareaA")
    ow2 = _mouth("doorB", OVERWORLD, "KingdomHomeB", "entB", "SubareaB")
    in2 = _mouth("doorB", INTERIOR, "InteriorB", "entB", "SubareaB")
    mouths = {m.mouth_id: m for m in (ow1, in1, ow2, in2)}
    vanilla = {
        ow1.mouth_id: in1.mouth_id, in1.mouth_id: ow1.mouth_id,
        ow2.mouth_id: in2.mouth_id, in2.mouth_id: ow2.mouth_id,
    }
    return PortGraph(mouths=mouths, vanilla_matching=vanilla, dropped_doors=[]), \
        ow1, in1, ow2, in2


def test_compile_port_remaps_vanilla_emits_nothing(tiny_graph):
    graph, *_ = tiny_graph
    assert compile_port_remaps(graph.vanilla_matching, graph) == []


def test_compile_port_remaps_row_count_matches_estimate(tiny_graph):
    graph, ow1, in1, ow2, in2 = tiny_graph
    # Cross-swap both doors' partners.
    matching = {
        ow1.mouth_id: in2.mouth_id, in2.mouth_id: ow1.mouth_id,
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
    }
    rows = compile_port_remaps(matching, graph)
    assert len(rows) == estimate_remap_rows(matching, graph.vanilla_matching) == 4


def test_compile_port_remaps_overworld_entry_row_shape(tiny_graph):
    graph, ow1, in1, ow2, in2 = tiny_graph
    matching = {
        ow1.mouth_id: in2.mouth_id, in2.mouth_id: ow1.mouth_id,
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
    }
    rows = compile_port_remaps(matching, graph)
    # ow1's row: kind=entry, "from" = ow1's OWN subarea's interior stage
    # (in1.stage), NOT ow1's own physical stage (KingdomHomeA) — that's the
    # vanilla dest when walking through ow1 unmodified. from_id = ow1's own
    # marker (disambiguates it from any OTHER door of SubareaA).
    row = next(r for r in rows
              if r["kind"] == "entry" and r["from_id"] == "entA")
    assert row["from"] == "InteriorA"
    assert row["to_stage"] == "InteriorB" and row["to_id"] == "entB"


def test_compile_port_remaps_interior_exit_row_shape(tiny_graph):
    graph, ow1, in1, ow2, in2 = tiny_graph
    matching = {
        ow1.mouth_id: in2.mouth_id, in2.mouth_id: ow1.mouth_id,
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
    }
    rows = compile_port_remaps(matching, graph)
    row = next(r for r in rows
              if r["kind"] == "exit" and r["from"] == "InteriorA")
    # in1's row: "from"/"from_id" = in1's OWN stage/marker (cur at exit
    # time); target is ow2 (an OVERWORLD mouth) -> lands at its own marker.
    assert row["from_id"] == "entA"
    assert row["to_stage"] == "KingdomHomeB" and row["to_id"] == "entB"


def test_compile_port_remaps_two_exits_can_diverge(tiny_graph):
    """The capability P2 built the substrate for and P3e finally exercises:
    two exit mouths sharing no `from` here (different subareas) still show
    each rewrites independently to a DIFFERENT target — unlike coupled mode,
    which always routes every physical port of one interior to one origin."""
    graph, ow1, in1, ow2, in2 = tiny_graph
    matching = {
        in1.mouth_id: ow1.mouth_id, ow1.mouth_id: in1.mouth_id,  # fixed (vanilla)
        in2.mouth_id: ow2.mouth_id, ow2.mouth_id: in2.mouth_id,  # fixed (vanilla)
    }
    # Both fixed (vanilla) -> no rows.
    assert compile_port_remaps(matching, graph) == []
    # Now cross them: in1 -> ow2, in2 -> ow1 (both interiors now exit to the
    # OTHER door instead of their own).
    matching = {
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
        in2.mouth_id: ow1.mouth_id, ow1.mouth_id: in2.mouth_id,
    }
    rows = compile_port_remaps(matching, graph)
    exits = {r["from"]: (r["to_stage"], r["to_id"])
             for r in rows if r["kind"] == "exit"}
    assert exits["InteriorA"] == ("KingdomHomeB", "entB")
    assert exits["InteriorB"] == ("KingdomHomeA", "entA")
    assert exits["InteriorA"] != exits["InteriorB"]


def test_compile_port_remaps_drops_unresolvable_both_ends(tiny_graph, caplog):
    """A mouth id absent from the local graph (client/server data drift)
    drops BOTH ends of that pair — never a one-sided row."""
    graph, ow1, *_ = tiny_graph
    ghost = "ghostDoor@overworld"
    matching = {ow1.mouth_id: ghost, ghost: ow1.mouth_id}
    rows = compile_port_remaps(matching, graph)
    assert rows == []


def test_compile_port_remaps_sorted_deterministic(tiny_graph):
    graph, ow1, in1, ow2, in2 = tiny_graph
    matching = {
        ow1.mouth_id: in2.mouth_id, in2.mouth_id: ow1.mouth_id,
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
    }
    rows1 = compile_port_remaps(matching, graph)
    rows2 = compile_port_remaps(dict(matching), graph)
    assert rows1 == rows2
    keys = [(r["kind"], r["from"], r.get("from_id", ""), r["to_stage"], r["to_id"])
            for r in rows1]
    assert keys == sorted(keys)


def test_compile_port_remaps_budget_enforced(tiny_graph, monkeypatch):
    import port_graph
    graph, ow1, in1, ow2, in2 = tiny_graph
    matching = {
        ow1.mouth_id: in2.mouth_id, in2.mouth_id: ow1.mouth_id,
        in1.mouth_id: ow2.mouth_id, ow2.mouth_id: in1.mouth_id,
    }
    # 4 rows fine at the real budget; shrink it below 4 to force the raise.
    monkeypatch.setattr(port_graph, "ROW_TABLE_CAP", 3)
    monkeypatch.setattr(port_graph, "ROW_HEADROOM", 0)
    with pytest.raises(RuntimeError, match="budget"):
        compile_port_remaps(matching, graph)


def test_compile_port_remaps_zone_alias_applied_to_overworld_target(
    tiny_graph, monkeypatch,
):
    """ZONE_STAGE_ALIAS (empty by default — see its docstring) only ever
    substitutes a TARGET's stage when the target is an OVERWORLD mouth (the
    schema-v2 per-door field never exercised by the already-validated
    coupled shuffle) — never a subarea's own interior stage (already
    validated, used verbatim by both compile_stage_remaps and the ENTRY row's
    `from` here)."""
    import port_graph
    graph, ow1, in1, ow2, in2 = tiny_graph
    monkeypatch.setattr(port_graph, "ZONE_STAGE_ALIAS",
                        {"KingdomHomeA": "AliasedZoneStage"})
    matching = {in2.mouth_id: ow1.mouth_id, ow1.mouth_id: in2.mouth_id}
    rows = compile_port_remaps(matching, graph)
    exit_row = next(r for r in rows if r["kind"] == "exit")
    assert exit_row["to_stage"] == "AliasedZoneStage"  # target ow1 aliased
    entry_row = next(r for r in rows if r["kind"] == "entry")
    # ow1's ENTRY row "from" is its subarea's interior stage (in1.stage),
    # never aliased — only OVERWORLD-side "to" targets go through the table.
    assert entry_row["from"] == "InteriorA"


def test_real_pool_row_compiler_matches_estimate_across_seeds():
    """Real-data round trip: a real roll's row count and the estimator agree,
    same invariant the roller itself asserts at generation time (P3c)."""
    import random
    from port_matching import roll_port_matching
    graph = build_port_graph(
        _load("entrance_stages.json"), _load("subareas.json"),
        _load("entrance_exclusions.json"))
    for seed in (1, 11, 22):
        matching = roll_port_matching(graph, random.Random(seed))
        rows = compile_port_remaps(matching, graph)
        assert len(rows) == estimate_remap_rows(matching, graph.vanilla_matching)
        assert len(rows) <= ROW_TABLE_CAP - ROW_HEADROOM


# ---------------------------------------------------------------------------
# One-way courses (Devon ruling 2026-07-08 — see port_graph's one-way note)
# ---------------------------------------------------------------------------

def _one_way_imports():
    from port_graph import (
        entry_capable_interior_mouths,
        one_way_course_subareas,
        pinned_one_way_entry_mouths,
    )
    return (entry_capable_interior_mouths, one_way_course_subareas,
            pinned_one_way_entry_mouths)


def test_entry_capability_real_pool_spot_checks(graph):
    """Ice Cave's arijigoku1/arijigoku2 pipes carry both roles => their
    interior mouths are entry-capable; Jaxi Driving's run00return is
    exit-only => not entry-capable (arriving at the finish mesa cannot
    retrace the course)."""
    entry_capable, _, _ = _one_way_imports()
    capable = entry_capable(graph)
    by_id = graph.mouths

    def interior_of(port_suffix):
        hits = [m for m in by_id.values()
                if m.side == INTERIOR and m.door_port_id.endswith(port_suffix)]
        return hits[0] if hits else None

    two_way = interior_of("#arijigoku1")
    if two_way is not None:
        assert two_way.mouth_id in capable
    far = interior_of("#run00return")
    if far is not None:
        assert far.mouth_id not in capable
    dual = interior_of("#run00")
    if dual is not None:
        assert dual.mouth_id in capable


def test_zone_split_doors_count_as_entry_capable():
    """A zone-split door (two port_ids, SAME entry_id — one physical door
    recorded twice) must read entry-capable: it is a two-way room, not a
    course. A genuinely separate exit (different entry_id) must not."""
    entry_capable, one_way, pinned = _one_way_imports()
    mouths: dict[str, Mouth] = {}
    vanilla: dict[str, str] = {}
    # Zone-split room: overworld half lives in the zone, interior half's
    # port records the parent stage — different port_ids, same entry_id.
    ow = Mouth(door_port_id="TestZone#RoomDoor", side=OVERWORLD,
               stage="TestZone", entry_id="RoomDoor",
               subarea="Split Room", kingdom="Test Kingdom", ingest=True)
    inn = Mouth(door_port_id="TestWorldHomeStage#RoomDoor", side=INTERIOR,
                stage="RoomExStage", entry_id="RoomDoor",
                subarea="Split Room", kingdom="Test Kingdom", ingest=True)
    # One-way course: entry door and exit pipe share nothing.
    c_ow = Mouth(door_port_id="TestWorldHomeStage#courseIn", side=OVERWORLD,
                 stage="TestWorldHomeStage", entry_id="courseIn",
                 subarea="Course", kingdom="Test Kingdom", ingest=True)
    c_in = Mouth(door_port_id="TestWorldHomeStage#courseOut", side=INTERIOR,
                 stage="CourseExStage", entry_id="courseOut",
                 subarea="Course", kingdom="Test Kingdom", ingest=True)
    for m in (ow, inn, c_ow, c_in):
        mouths[m.mouth_id] = m
        vanilla[m.mouth_id] = m.mouth_id
    g = PortGraph(mouths=mouths, vanilla_matching=vanilla, dropped_doors=[])

    capable = entry_capable(g)
    assert inn.mouth_id in capable          # zone-split room: two-way
    assert c_in.mouth_id not in capable     # course exit: far side

    courses = one_way(g)
    assert courses == frozenset({"Course"})
    assert pinned(g) == frozenset({c_ow.mouth_id})


def test_one_way_courses_have_no_capable_interior(graph, festival_graph):
    """Definitional invariant on the real pool, both goal shapes: every
    detected course has >=1 pooled interior mouth and ZERO entry-capable
    ones, and every pinned mouth is a lone overworld entrance of a course."""
    entry_capable, one_way, pinned = _one_way_imports()
    for g in (graph, festival_graph):
        capable = entry_capable(g)
        courses = one_way(g)
        for sub in courses:
            interiors = [m for m in g.mouths.values()
                         if m.side == INTERIOR and m.subarea == sub]
            assert interiors, f"course '{sub}' has no pooled interior mouths"
            assert not any(m.mouth_id in capable for m in interiors)
        for mid in pinned(g):
            m = g.mouths[mid]
            assert m.side == OVERWORLD and m.subarea in courses
            assert g.vanilla_matching.get(mid) == mid, (
                f"pinned mouth {mid} is not the lone vanilla self-map shape")
