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
    Mouth,
    build_port_graph,
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
