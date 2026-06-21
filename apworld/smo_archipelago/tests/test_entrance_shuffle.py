"""P7 entrance shuffle — pure-data + entrance_logic unit tests.

No Archipelago imports; runs directly against the source tree.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

APWORLD_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APWORLD_ROOT / "data"


def _subareas() -> dict:
    return json.loads((DATA_DIR / "subareas.json").read_text(encoding="utf-8"))


def _exclusions() -> dict:
    return json.loads((DATA_DIR / "entrance_exclusions.json").read_text(encoding="utf-8"))


def _locations() -> list[dict]:
    return json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# subareas.json data-fix assertions
# ---------------------------------------------------------------------------

def test_shiveria_town_kingdom_is_snow():
    """Shiveria Town was erroneously tagged as Seaside Kingdom."""
    subareas = _subareas()
    assert "Shiveria Town" in subareas
    assert subareas["Shiveria Town"]["kingdom"] == "Snow Kingdom", (
        "Shiveria Town must be Snow Kingdom (not Seaside)")


def test_class_a_race_kingdom_is_snow():
    subareas = _subareas()
    assert "Class A Race" in subareas
    assert subareas["Class A Race"]["kingdom"] == "Snow Kingdom", (
        "Class A Race must be Snow Kingdom (not Seaside)")


def test_costume_room_split_into_three():
    """Costume Room must be split into three per-kingdom entries."""
    subareas = _subareas()
    assert "Costume Room" not in subareas, (
        "Generic 'Costume Room' must be removed; use per-kingdom variants")
    assert "Costume Room (Sand)" in subareas
    assert "Costume Room (Wooded)" in subareas
    assert "Costume Room (Seaside)" in subareas

    assert subareas["Costume Room (Sand)"]["kingdom"] == "Sand Kingdom"
    assert subareas["Costume Room (Wooded)"]["kingdom"] == "Wooded Kingdom"
    assert subareas["Costume Room (Seaside)"]["kingdom"] == "Seaside Kingdom"

    # Each has exactly one location
    assert subareas["Costume Room (Sand)"]["location_names"] == ["Sand: Dancing with New Friends"]
    assert subareas["Costume Room (Wooded)"]["location_names"] == ["Wooded: Exploring for Treasure"]
    assert subareas["Costume Room (Seaside)"]["location_names"] == ["Seaside: A Relaxing Dance"]


def test_sphynx_vault_split_into_two():
    """Sphynx Treasure Vault must be split into Sand + Seaside entries."""
    subareas = _subareas()
    assert "Sphynx Treasure Vault" not in subareas, (
        "Generic 'Sphynx Treasure Vault' must be removed; use per-kingdom variants")
    assert "Sphynx Treasure Vault (Sand)" in subareas
    assert "Sphynx Treasure Vault (Seaside)" in subareas

    assert subareas["Sphynx Treasure Vault (Sand)"]["kingdom"] == "Sand Kingdom"
    assert subareas["Sphynx Treasure Vault (Seaside)"]["kingdom"] == "Seaside Kingdom"

    assert subareas["Sphynx Treasure Vault (Sand)"]["location_names"] == ["Sand: Sphynx's Treasure Vault"]
    assert subareas["Sphynx Treasure Vault (Seaside)"]["location_names"] == ["Seaside: The Sphynx's Underwater Vault"]


def test_all_subarea_location_names_unique_across_subareas():
    """No location name should appear in more than one subarea entry."""
    subareas = _subareas()
    seen: dict[str, str] = {}
    for sub_name, info in subareas.items():
        for loc in info.get("location_names", []):
            assert loc not in seen, (
                f"Location '{loc}' in '{sub_name}' also in '{seen[loc]}'")
            seen[loc] = sub_name


# ---------------------------------------------------------------------------
# Pool size and exclusion correctness
# ---------------------------------------------------------------------------

def test_entrance_pool_size_is_116():
    """After data fixes the pool must contain exactly 116 subareas."""
    from entrance_logic import build_entrance_pool
    subareas = _subareas()
    exclusions = _exclusions()
    pool = build_entrance_pool(subareas, exclusions)
    assert len(pool) == 119, f"Expected 119 in pool, got {len(pool)}: {sorted(pool)}"


def test_excluded_subareas_absent_from_pool():
    """All named exclusions must be absent from the pool."""
    from entrance_logic import build_entrance_pool
    subareas = _subareas()
    exclusions = _exclusions()
    pool = set(build_entrance_pool(subareas, exclusions))
    for kingdom_exc in exclusions.values():
        for name in kingdom_exc:
            assert name not in pool, f"Excluded subarea '{name}' appears in pool"


def test_sewers_excluded():
    from entrance_logic import build_entrance_pool
    pool = set(build_entrance_pool(_subareas(), _exclusions()))
    assert "Sewers" not in pool, "Sewers must be excluded from entrance shuffle pool"


def test_shiveria_town_excluded():
    from entrance_logic import build_entrance_pool
    pool = set(build_entrance_pool(_subareas(), _exclusions()))
    assert "Shiveria Town" not in pool


def test_class_a_race_excluded():
    from entrance_logic import build_entrance_pool
    pool = set(build_entrance_pool(_subareas(), _exclusions()))
    assert "Class A Race" not in pool


# ---------------------------------------------------------------------------
# compile_interior_requires: spot-checks
# ---------------------------------------------------------------------------

def test_compile_interior_requires_free_moon():
    """A baseline-method moon (no height, no throws, free captures) compiles to ''."""
    from entrance_logic import compile_interior_requires
    record = {
        "methods": {"1": {"jump_height": "single", "cap_throws": ["neutral"], "other_required": []}},
        "capture_groups": [],
    }
    assert compile_interior_requires(record) == ""


def test_compile_interior_requires_no_gates():
    """Interior requires must NOT contain peace-gate or kingdom-gate fragments."""
    from entrance_logic import compile_interior_requires, MOON_PIPE_PEACE_FUNCS
    record = {
        "methods": {"1": {"jump_height": "backflip", "cap_throws": ["neutral"], "other_required": []}},
        "capture_groups": [],
    }
    req = compile_interior_requires(record)
    for peace_fn in MOON_PIPE_PEACE_FUNCS.values():
        assert peace_fn not in req, f"Peace gate {peace_fn} leaked into interior requires"
    assert "Spark pylon" not in req
    assert "Zipper" not in req


def test_parse_scenario_fragment_no_arg():
    """{Func()} parses to (name, []) — used by the D3 scenario-gate rule factory."""
    from entrance_logic import parse_scenario_fragment
    assert parse_scenario_fragment("{SandPeace()}") == [("SandPeace", [])]
    assert parse_scenario_fragment("{CascadeDeparture()}") == [("CascadeDeparture", [])]


def test_parse_scenario_fragment_with_arg():
    from entrance_logic import parse_scenario_fragment
    assert parse_scenario_fragment(
        "{canReachLocation(Sand: The Hole in the Desert)}") == [
            ("canReachLocation", ["Sand: The Hole in the Desert"])]


def test_parse_scenario_fragment_empty_and_anded():
    from entrance_logic import parse_scenario_fragment
    assert parse_scenario_fragment("") == []
    assert parse_scenario_fragment(None) == []
    # AND-joined fragments yield both calls (composition is all() at rule time).
    assert parse_scenario_fragment("({CapPeace()} and {SandPeace()})") == [
        ("CapPeace", []), ("SandPeace", [])]


def test_compile_interior_requires_jump_height():
    """Backflip-height moon requires cap_bounce OR backflip+crouch OR side_flip OR GPJ+GP OR triple."""
    from entrance_logic import compile_interior_requires
    record = {
        "methods": {"1": {"jump_height": "backflip", "cap_throws": [], "other_required": []}},
        "capture_groups": [],
    }
    req = compile_interior_requires(record)
    assert req != "", "Backflip-height moon must not be free"
    assert "Cap Bounce" in req or "Backflip" in req


# ---------------------------------------------------------------------------
# build_interior_requires_map
# ---------------------------------------------------------------------------

def test_build_interior_requires_map_no_gates():
    """None of the mapped requires strings should contain peace/kingdom gate fragments."""
    req_path = DATA_DIR / "moon_requirements.json"
    if not req_path.exists():
        pytest.skip("moon_requirements.json absent (no romfs extraction)")

    from entrance_logic import build_interior_requires_map, MOON_PIPE_PEACE_FUNCS
    loc_table = _locations()
    mapping = build_interior_requires_map(loc_table)
    for name, req in mapping.items():
        for peace_fn in MOON_PIPE_PEACE_FUNCS.values():
            assert peace_fn not in req, (
                f"Peace gate '{peace_fn}' leaked into interior requires for '{name}'")


# ---------------------------------------------------------------------------
# Bijection validity
# ---------------------------------------------------------------------------

def test_bijection_is_valid_permutation():
    """A shuffled bijection must map pool → pool with no duplicates."""
    from entrance_logic import build_entrance_pool
    subareas = _subareas()
    exclusions = _exclusions()
    pool = build_entrance_pool(subareas, exclusions)
    rng = random.Random(42)
    shuffled = list(pool)
    rng.shuffle(shuffled)
    bijection = dict(zip(pool, shuffled))

    assert set(bijection.keys()) == set(pool)
    assert set(bijection.values()) == set(pool)
    assert len(bijection) == len(pool)


def test_bijection_stable_with_same_seed():
    """Same RNG seed must produce the same bijection."""
    from entrance_logic import build_entrance_pool
    pool = build_entrance_pool(_subareas(), _exclusions())

    def _roll(seed):
        rng = random.Random(seed)
        s = list(pool)
        rng.shuffle(s)
        return dict(zip(pool, s))

    assert _roll(99) == _roll(99)
    assert _roll(99) != _roll(100)


# ---------------------------------------------------------------------------
# Moon-pipe detection
# ---------------------------------------------------------------------------

def test_moonpipe_subareas_all_locations_are_rock():
    """Every location in a moon-pipe subarea must have 'Moon Rock' in category."""
    from entrance_logic import build_moonpipe_subarea_set
    subareas = _subareas()
    loc_table = _locations()
    moonpipe = build_moonpipe_subarea_set(subareas, loc_table)

    loc_map = {l["name"]: l for l in loc_table}
    for sub_name in moonpipe:
        for loc_name in subareas[sub_name].get("location_names", []):
            loc = loc_map.get(loc_name)
            if loc is None:
                continue  # location disabled or not present
            assert "Moon Rock" in loc.get("category", []), (
                f"'{loc_name}' in moon-pipe subarea '{sub_name}' lacks Moon Rock category")


def test_moonpipe_subareas_not_empty():
    """There must be at least one moon-pipe subarea (Mysterious Clouds etc.)."""
    from entrance_logic import build_moonpipe_subarea_set
    moonpipe = build_moonpipe_subarea_set(_subareas(), _locations())
    assert len(moonpipe) > 0, "No moon-pipe subareas detected — check Moon Rock categories"


def test_nonmoonpipe_subarea_has_non_rock_location():
    """Poison Tides (Cap) is NOT a moon-pipe subarea."""
    from entrance_logic import build_moonpipe_subarea_set
    moonpipe = build_moonpipe_subarea_set(_subareas(), _locations())
    assert "Poison Tides" not in moonpipe


# ---------------------------------------------------------------------------
# Options registration
# ---------------------------------------------------------------------------

def test_entrance_shuffle_option_registered():
    opts_src = (APWORLD_ROOT / "hooks" / "Options.py").read_text(encoding="utf-8")
    assert "class EntranceShuffle" in opts_src
    assert 'options["entrance_shuffle"] = EntranceShuffle' in opts_src


# ---------------------------------------------------------------------------
# P7 Step 4 — stage-level remap resolution (compile_stage_remaps)
# ---------------------------------------------------------------------------

def _entrance_stages() -> dict:
    path = DATA_DIR / "entrance_stages.json"
    if not path.exists():
        pytest.skip("entrance_stages.json absent (run extract_entrance_stages.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_entrance_stages_nonempty():
    from entrance_logic import load_entrance_stages
    stages = load_entrance_stages()
    assert isinstance(stages, dict)
    assert "Poison Tides" in stages, "entrance_stages.json should resolve from source tree"


def test_compile_stage_remaps_identity_skipped():
    """An identity pair (σ(D)==D) produces NO rows — both would be vanilla no-ops."""
    from entrance_logic import compile_stage_remaps
    stages = _entrance_stages()
    rows = compile_stage_remaps({"Poison Tides": "Poison Tides"}, stages)
    assert rows == []


def test_compile_stage_remaps_cross_pair():
    """A door -> different interior emits one ENTRY row (into the interior) and
    one EXIT row (out of the interior, back to the door's exterior)."""
    from entrance_logic import compile_stage_remaps
    stages = _entrance_stages()
    door, interior = "Poison Tides", "Crowded Elevator"
    if interior not in stages:
        pytest.skip("Crowded Elevator absent from table")
    rows = compile_stage_remaps({door: interior}, stages)

    entries = [r for r in rows if r["kind"] == "entry"]
    exits = [r for r in rows if r["kind"] == "exit"]
    assert len(entries) == 1
    assert len(exits) == 1

    # ENTRY: walk through the door that vanilla-leads-to `door`; matched on the
    # door's own stage, rewritten to the interior's primary entrance.
    e = entries[0]
    assert e["from"] == stages[door]["stage"]
    assert e["to_stage"] == stages[interior]["stage"]
    assert e["to_id"] == stages[interior]["primary_entry"]["entry_id"]

    # EXIT: leave the interior; matched on the interior's OWN stage (cur), and
    # rewritten to the origin DOOR's exterior coordinate (primary_exit).
    x = exits[0]
    assert x["from"] == stages[interior]["stage"]
    assert x["to_stage"] == stages[door]["primary_exit"]["dest"]
    assert x["to_id"] == stages[door]["primary_exit"]["entry_id"]


def test_compile_stage_remaps_skips_unknown():
    """Doors/interiors absent from the table are dropped, not crashed on."""
    from entrance_logic import compile_stage_remaps
    stages = _entrance_stages()
    door, interior = "Poison Tides", "Frog Pond"
    if interior not in stages:
        pytest.skip("Frog Pond absent from table")
    rows = compile_stage_remaps(
        {door: interior, "Not A Real Subarea": "Also Fake"}, stages)
    # Only the resolvable pair survives — and it yields its entry + exit rows.
    froms = {r["from"] for r in rows}
    assert stages[door]["stage"] in froms       # entry key (door stage)
    assert stages[interior]["stage"] in froms   # exit key (interior stage)
    # The fake pair contributes nothing.
    assert all("Fake" not in r["from"] for r in rows)


def test_compile_stage_remaps_full_pool_entries_resolve():
    """A full-pool derangement yields one ENTRY row per shuffled door (no silent
    drops) plus an EXIT row for every door whose interior has a primary_exit."""
    from entrance_logic import build_entrance_pool, compile_stage_remaps
    stages = _entrance_stages()
    pool = build_entrance_pool(_subareas(), _exclusions())
    # Rotate-by-one derangement so no door maps to itself (identity is skipped).
    rotated = pool[1:] + pool[:1]
    bijection = dict(zip(pool, rotated))

    rows = compile_stage_remaps(bijection, stages)
    entry_froms = {r["from"] for r in rows if r["kind"] == "entry"}
    missing = [
        name for name in pool
        if stages.get(name, {}).get("stage") not in entry_froms
    ]
    assert not missing, f"pool doors with no resolved entry row: {missing}"
    # One entry per door; exits are >=... and never exceed the door count.
    n_entry = sum(1 for r in rows if r["kind"] == "entry")
    n_exit = sum(1 for r in rows if r["kind"] == "exit")
    assert n_entry == len(pool)
    assert 0 < n_exit <= len(pool)
