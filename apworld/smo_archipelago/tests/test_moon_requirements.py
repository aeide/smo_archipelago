"""Tests for apworld/smo_archipelago/data/moon_requirements.json and subareas.json.

Run from the tests/ directory (or via the repo-root venv):
    python -m pytest apworld/smo_archipelago/tests/test_moon_requirements.py -v

What is tested:
  1. JSON files are valid and load cleanly.
  2. Every non-Capture, non-special location in locations.json has a matched
     entry in moon_requirements.json (location_name field points back to it).
  3. Vocabulary is closed — no unknown strings appear in any method field.
  4. Structural invariants: method keys are "1"–"5"; every method that is not
     null has the required sub-fields; captures is a list; locked_default_capture
     is a bool.
  5. subareas.json: every subarea has a kingdom assignment; every location_name
     listed there actually exists in locations.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

APWORLD_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APWORLD_ROOT / "data"

# ─── Valid vocabulary sets (mirrors import_moon_requirements.py) ───────────────
VALID_JUMP_HEIGHTS = frozenset({
    "none", "single", "double", "cap_return",
    "backflip", "gpj", "triple", "long_jump",
})

VALID_CAP_THROWS = frozenset({"none", "neutral", "up", "down", "spin"})

VALID_OTHER_REQUIRED = frozenset({
    "capture", "dive", "ground_pound", "roll", "roll_boost", "crouch",
    "wall_jump", "ledge_grab", "climb", "homing_cap", "bonk_roll",
    "damage_boost", "2d_jump", "scooter", "jaxi", "rainbow_spin",
    "outfit", "single", "other_kingdom_trigger",
})

METHOD_KEYS = frozenset({"1", "2", "3", "4", "5"})


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def locations() -> list[dict]:
    return json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def requirements() -> dict[str, dict]:
    return json.loads((DATA_DIR / "moon_requirements.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def subareas() -> dict[str, dict]:
    return json.loads((DATA_DIR / "subareas.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matchable_location_names(locations) -> set[str]:
    """Non-Capture, non-special locations that must have a requirements entry.

    junk_only locations (P3 Mushroom Kingdom / Dark Side / Darker Side checks)
    are excluded: they're filler/trap-only checks with no ability-logic
    requirements (requires == ""), so they have no moon_requirements entry by
    design.
    """
    return {
        loc["name"]
        for loc in locations
        if not loc["name"].startswith("Capture:")
        and ": " in loc["name"]   # excludes "Arrive in the Mushroom Kingdom"
        and not loc.get("junk_only", False)
    }


# ─── 1. Files load ────────────────────────────────────────────────────────────

def test_moon_requirements_loads(requirements):
    assert isinstance(requirements, dict)
    assert len(requirements) > 0, "moon_requirements.json is empty"


def test_subareas_loads(subareas):
    assert isinstance(subareas, dict)
    assert len(subareas) > 0, "subareas.json is empty"


# ─── 2. Every current location is matched ─────────────────────────────────────

def test_all_locations_matched(matchable_location_names, requirements):
    """Every non-Capture locations.json entry must appear as a location_name."""
    covered = {
        entry["location_name"]
        for entry in requirements.values()
        if entry.get("location_name") is not None
    }
    missing = matchable_location_names - covered
    assert not missing, (
        f"{len(missing)} location(s) in locations.json have no requirements entry:\n"
        + "\n".join(f"  {n}" for n in sorted(missing))
    )


# ─── 3. Vocabulary is closed ──────────────────────────────────────────────────

def test_jump_height_vocabulary(requirements):
    bad: list[str] = []
    for csv_name, entry in requirements.items():
        for m_key, method in entry["methods"].items():
            if method is None:
                continue
            jh = method.get("jump_height")
            if jh is not None and jh not in VALID_JUMP_HEIGHTS:
                bad.append(f"{csv_name} method {m_key}: jump_height={jh!r}")
    assert not bad, "Unknown jump_height values:\n" + "\n".join(bad)


def test_cap_throw_vocabulary(requirements):
    bad: list[str] = []
    for csv_name, entry in requirements.items():
        for m_key, method in entry["methods"].items():
            if method is None:
                continue
            for ct in method.get("cap_throws", []):
                if ct not in VALID_CAP_THROWS:
                    bad.append(f"{csv_name} method {m_key}: cap_throw={ct!r}")
    assert not bad, "Unknown cap_throw values:\n" + "\n".join(bad)


def test_other_required_vocabulary(requirements):
    bad: list[str] = []
    for csv_name, entry in requirements.items():
        for m_key, method in entry["methods"].items():
            if method is None:
                continue
            for ot in method.get("other_required", []):
                if ot not in VALID_OTHER_REQUIRED:
                    bad.append(f"{csv_name} method {m_key}: other_required={ot!r}")
    assert not bad, "Unknown other_required values:\n" + "\n".join(bad)


# ─── 4. Structural invariants ─────────────────────────────────────────────────

def test_method_keys(requirements):
    for csv_name, entry in requirements.items():
        assert set(entry["methods"].keys()) == METHOD_KEYS, (
            f"{csv_name}: unexpected method keys {set(entry['methods'].keys())}"
        )


def test_method_fields(requirements):
    required_fields = {"jump_height", "cap_throws", "other_required"}
    bad: list[str] = []
    for csv_name, entry in requirements.items():
        for m_key, method in entry["methods"].items():
            if method is None:
                continue
            missing = required_fields - set(method.keys())
            if missing:
                bad.append(f"{csv_name} method {m_key}: missing {missing}")
    assert not bad, "\n".join(bad)


def test_captures_is_list(requirements):
    bad = [k for k, v in requirements.items() if not isinstance(v["captures"], list)]
    assert not bad, f"Non-list captures in: {bad}"


def test_locked_default_capture_is_bool(requirements):
    bad = [
        k for k, v in requirements.items()
        if not isinstance(v["locked_default_capture"], bool)
    ]
    assert not bad, f"Non-bool locked_default_capture in: {bad}"


# ─── 5. subareas.json invariants ─────────────────────────────────────────────

def test_subareas_have_kingdom(subareas):
    no_kingdom = [k for k, v in subareas.items() if not v.get("kingdom")]
    assert not no_kingdom, (
        f"Subareas without kingdom assignment: {no_kingdom}"
    )


def test_subarea_location_names_exist(subareas, locations):
    all_loc_names = {loc["name"] for loc in locations}
    bad: list[str] = []
    for subarea, data in subareas.items():
        for loc_name in data.get("location_names", []):
            if loc_name not in all_loc_names:
                bad.append(f"{subarea} → {loc_name!r} not in locations.json")
    assert not bad, "\n".join(bad)


def test_subarea_csv_names_in_requirements(subareas, requirements):
    bad: list[str] = []
    for subarea, data in subareas.items():
        for csv_name in data.get("csv_names", []):
            if csv_name not in requirements:
                bad.append(f"{subarea} csv_name {csv_name!r} missing from requirements")
    assert not bad, "\n".join(bad)
