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


def _entrance_stages() -> dict:
    return json.loads((DATA_DIR / "entrance_stages.json").read_text(encoding="utf-8"))


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

def test_entrance_pool_size_is_119():
    """After data fixes the pool must contain exactly 119 subareas."""
    from entrance_logic import build_entrance_pool
    subareas = _subareas()
    exclusions = _exclusions()
    pool = build_entrance_pool(subareas, exclusions)
    assert len(pool) == 119, f"Expected 119 in pool, got {len(pool)}: {sorted(pool)}"


def test_pool_is_fully_round_trippable():
    """Every pooled subarea MUST resolve in entrance_stages.json with a stage and
    a primary_entry — otherwise the bijection can install a one-way cross-kingdom
    warp (Mario enters an unresolved subarea's stage vanilla but exits via a
    partner door's coupling). Regression guard for the Sand->Bowser warp caused by
    the merged Costume Room / Sphynx Treasure Vault subareas (absent from
    entrance_stages.json). See entrance_logic.is_round_trippable."""
    from entrance_logic import build_entrance_pool, is_round_trippable
    st = _entrance_stages()
    pool = build_entrance_pool(_subareas(), _exclusions())
    bad = [n for n in pool if not is_round_trippable(n, st)]
    assert not bad, f"Non-round-trippable subareas in pool (would warp Mario): {bad}"


def test_build_entrance_pool_drops_non_round_trippable():
    """When entrance_stages is passed, build_entrance_pool drops any subarea that
    is absent / missing primary_entry, so a stale entrance_stages can never poison
    the bijection."""
    from entrance_logic import build_entrance_pool
    subareas = dict(_subareas())
    subareas["Bogus Phantom Subarea"] = {
        "kingdom": "Sand Kingdom", "csv_names": [], "location_names": [],
    }
    st = _entrance_stages()
    unfiltered = build_entrance_pool(subareas, _exclusions())
    filtered = build_entrance_pool(subareas, _exclusions(), st)
    assert "Bogus Phantom Subarea" in unfiltered
    assert "Bogus Phantom Subarea" not in filtered


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


def test_door_scenario_gate_rule_ors_over_members(monkeypatch):
    """A door's intrinsic scenario gate ORs over its member moons: an ungated
    member collapses the rule to always-True (door gate-free); all-gated members
    require the (weakest) member gate. Regression for the entrance-shuffle bug where
    a moon behind a late door (e.g. Mysterious Clouds = {CascadeDeparture()}) was
    reachable as early as its unrelated interior gate allowed."""
    import entrance_logic as el

    # Stub the per-fragment factory: '' -> always True; anything else -> reads a flag.
    def fake_frag_rule(frag, world, mw, player):
        if not frag:
            return lambda state: True
        return lambda state: bool(getattr(state, "ok", False))
    monkeypatch.setattr(el, "make_scenario_gate_rule", fake_frag_rule)

    class S:
        ok = False
    s = S()

    # All members gated -> door blocked until the flag flips.
    r = el.make_door_scenario_gate_rule(["NEED", "NEED"], None, None, 1)
    assert r(s) is False
    s.ok = True
    assert r(s) is True

    # One ungated member -> door reachable even with the flag down (OR collapses).
    assert el.make_door_scenario_gate_rule(["", "NEED"], None, None, 1)(S()) is True

    # No members -> no-op always-True.
    assert el.make_door_scenario_gate_rule([], None, None, 1)(S()) is True


def test_mysterious_clouds_door_gate_is_cascade_departure():
    """Regression (door-side scenario gate): the Cascade 'Mysterious Clouds' door is
    physically reachable only post-departure ({CascadeDeparture()}). Under entrance
    shuffle that gate must ride the DOOR entrance, else moons mapped behind it (e.g.
    the Nice Shots with Chain Chomps moons, interior gate {CascadePeace()} = sphere 1)
    fill far too early. Guards the door-gate source data World.py reads."""
    from entrance_logic import load_data_json
    subareas = load_data_json("subareas.json")
    gates = load_data_json("subarea_scenario_gates.json")
    members = subareas["Mysterious Clouds"]["location_names"]
    frags = [gates.get(m, "") for m in members]
    assert frags and all(f == "{CascadeDeparture()}" for f in frags), frags


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


# ---------------------------------------------------------------------------
# SUBAREA_EXIT_GATES — mini-rocket interiors must require Mini Rocket to leave
# even when reached via a shuffled (non-rocket) door.
# ---------------------------------------------------------------------------

_MINI_ROCKET_SUBAREAS = frozenset({
    "Swinging Along the High-Rises",
    "A Sea of Clouds",
    "Strange Neighborhood",
    "Shards in the Fog",
    "Picture Match (Mario)",
    "Roulette Tower",
})


def test_exit_gates_cover_every_mini_rocket_subarea():
    """Every subarea whose ENTRY gate is Mini Rocket must also be EXIT-gated by
    Mini Rocket — the only way out is to re-board the rocket inside."""
    from entrance_logic import SUBAREA_ENTRANCE_GATES, SUBAREA_EXIT_GATES

    entry_rocket = {
        name for name, gate in SUBAREA_ENTRANCE_GATES.items()
        if gate == "|Mini Rocket|"
    }
    assert entry_rocket == _MINI_ROCKET_SUBAREAS, (
        "mini-rocket entry-gated set drifted; update the test + exit table")
    for name in entry_rocket:
        assert SUBAREA_EXIT_GATES.get(name) == "|Mini Rocket|", (
            f"{name!r} is entered by Mini Rocket but has no Mini Rocket exit gate")


def test_exit_gates_are_subset_of_entrance_gates():
    """An exit-gated subarea is by definition also entry-gated by the same
    capture (you needed it to get to the launch point in the first place)."""
    from entrance_logic import SUBAREA_ENTRANCE_GATES, SUBAREA_EXIT_GATES

    for name, exit_gate in SUBAREA_EXIT_GATES.items():
        assert name in SUBAREA_ENTRANCE_GATES, (
            f"{name!r} has an exit gate but no entrance gate")
        assert SUBAREA_ENTRANCE_GATES[name] == exit_gate, (
            f"{name!r} entry/exit gate mismatch — mini-rocket subareas use the "
            f"same capture both ways")


def test_exit_gated_subareas_are_in_the_shuffle_pool():
    """The fix only matters if these interiors can actually be reached via a
    foreign door. Confirm they're pool members (not excluded) — otherwise the
    interior == its own door (identity) and the entry gate already covers exit."""
    from entrance_logic import SUBAREA_EXIT_GATES, build_entrance_pool

    pool = set(build_entrance_pool(_subareas(), _exclusions(), _entrance_stages()))
    for name in SUBAREA_EXIT_GATES:
        assert name in pool, (
            f"{name!r} is exit-gated but absent from the entrance pool")


# ---------------------------------------------------------------------------
# MIXED door gates — {Func} OR |item| entries in SUBAREA_ENTRANCE_GATES (e.g. Jaxi
# Driving). These are DOOR-keyed (the gate is what it takes to reach the door in the
# overworld), so they ride the door under shuffle, not the interior. Regression
# coverage for (a) the c42c933 char-split bug where a malformed flat-string
# capture_group made the interior require nonexistent single-character "items", and
# (b) the Cascade-departure leak where the Jaxi gate was interior-keyed (left the Jaxi
# exterior door ungated) AND evaluated item-only (fail-OPEN on {SandPeace()}).
# ---------------------------------------------------------------------------

def _moon_requirements() -> dict:
    return json.loads((DATA_DIR / "moon_requirements.json").read_text(encoding="utf-8"))


def test_capture_groups_are_never_flat_strings():
    """Every capture_group must be a LIST of capture names ([["Bullet Bill"]]), never
    a bare string (["Bullet Bill"]) — the latter makes _capture_term iterate over the
    string's CHARACTERS, producing |B| and |u| and ... (nonexistent items) and an
    unsatisfiable interior rule. This guards the whole table, not just Jaxi."""
    bad = []
    for csv_name, rec in _moon_requirements().items():
        for g in rec.get("capture_groups", []):
            if not isinstance(g, list):
                bad.append((rec.get("location_name", csv_name), rec["capture_groups"]))
                break
    assert not bad, f"malformed (flat-string) capture_groups: {bad}"


def _mixed_door_gates() -> dict:
    """The DOOR-keyed {Func} OR |item| gates (Jaxi Driving) — the only entries in
    SUBAREA_ENTRANCE_GATES whose value contains a {Func()} call."""
    from entrance_logic import SUBAREA_ENTRANCE_GATES
    return {n: g for n, g in SUBAREA_ENTRANCE_GATES.items() if "{" in g}


def test_full_gated_subareas_are_pooled_and_free_inside():
    """For each MIXED door gate ({Func} OR |item|, e.g. Jaxi Driving): the door
    subarea must be in the shuffle pool (else the door gate never applies) and every
    member moon must compile to a FREE interior (no move-set) — the door gate is the
    moon's only requirement."""
    from entrance_logic import build_entrance_pool, compile_interior_requires
    subareas = _subareas()
    pool = set(build_entrance_pool(subareas, _exclusions(), _entrance_stages()))
    reqs = {r.get("location_name"): r for r in _moon_requirements().values()}
    mixed = _mixed_door_gates()
    assert mixed, "expected at least one mixed {Func} OR |item| door gate (Jaxi Driving)"
    for sub in mixed:
        assert sub in pool, f"{sub!r} has a mixed door gate but is not pooled"
        for ln in subareas.get(sub, {}).get("location_names", []):
            rec = reqs.get(ln)
            if rec is not None:
                assert compile_interior_requires(rec) == "", (
                    f"{ln!r} should be free inside (gate rides the door), got "
                    f"{compile_interior_requires(rec)!r}")


def test_full_gate_matches_baked_locations_requires():
    """The shuffle-OFF baked requires (locations.json) for a mixed-gated door
    subarea's members must equal the SUBAREA_ENTRANCE_GATES string, so OFF and ON
    agree."""
    subareas = _subareas()
    by_name = {l["name"]: l for l in _locations()}
    for sub, gate in _mixed_door_gates().items():
        for ln in subareas.get(sub, {}).get("location_names", []):
            loc = by_name.get(ln)
            if loc is not None and not loc.get("junk_only"):
                assert loc.get("requires") == gate, (
                    f"{ln!r} baked requires {loc.get('requires')!r} != door gate {gate!r}")


def test_full_gate_mirror_compile_moon_logic():
    """The shuffle-ON mixed door gate (entrance_logic.SUBAREA_ENTRANCE_GATES) must
    mirror the shuffle-OFF bake source (compile_moon_logic.SUBAREA_INTERIOR_FULL_GATES)
    string-for-string — same Jaxi gate whether or not entrance shuffle is on."""
    import importlib.util
    script = APWORLD_ROOT.parents[1] / "scripts" / "compile_moon_logic.py"
    if not script.exists():
        pytest.skip("compile_moon_logic.py not present")
    spec = importlib.util.spec_from_file_location("_cml", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert _mixed_door_gates() == mod.SUBAREA_INTERIOR_FULL_GATES
