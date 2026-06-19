"""Validate locally-extracted shine_map.json + capture_map.json (gitignored).

These tests are skipped when the file hasn't been generated yet (fresh clone,
CI without a SMO dump). After running `python scripts/extract_shine_map.py`
they confirm schema, count, anchor entries, and apworld coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from client.maps import CaptureMap, MoonResolution, ShineMap

DATA_DIR = Path(__file__).resolve().parent.parent / "client" / "data"
SHINE_MAP_PATH = DATA_DIR / "shine_map.json"
CAPTURE_MAP_PATH = DATA_DIR / "capture_map.json"
WORLD_SCENARIOS_PATH = DATA_DIR / "world_scenarios.json"


def _entries() -> list[dict]:
    if not SHINE_MAP_PATH.exists():
        pytest.skip(f"{SHINE_MAP_PATH} not generated; run scripts/extract_shine_map.py")
    return json.loads(SHINE_MAP_PATH.read_text(encoding="utf-8"))


REQUIRED_KEYS = {"stage_name", "object_id", "kingdom", "shine_id", "shine_uid"}


def test_extracted_count_is_complete() -> None:
    entries = _entries()
    # SMO 1.0.0 has 775 raw shines across 17 HomeStage BYMLs. Allow some
    # latitude in case Nintendo data layout shifts slightly between regions.
    assert len(entries) >= 500, f"too few entries: {len(entries)}"


def test_extracted_schema() -> None:
    for i, e in enumerate(_entries()):
        missing = REQUIRED_KEYS - set(e)
        assert not missing, f"entry {i} missing keys {missing}: {e}"
        assert isinstance(e["stage_name"], str) and e["stage_name"]
        assert isinstance(e["object_id"], str) and e["object_id"]
        assert isinstance(e["kingdom"], str) and e["kingdom"]
        assert isinstance(e["shine_id"], str) and e["shine_id"]
        assert isinstance(e["shine_uid"], int)


def test_extracted_no_duplicate_pair_keys() -> None:
    pairs = [(e["stage_name"], e["object_id"]) for e in _entries()]
    dups = {p for p in pairs if pairs.count(p) > 1}
    assert not dups, f"duplicate (stage_name, object_id) keys: {sorted(dups)[:5]}"


def test_extracted_anchor_resolves() -> None:
    """The M5.7 ground-truth entry must resolve identically.

    Confirmed live: Mario collects 'Our First Power Moon' in Ryujinx ->
    MoonGetHook fires with stage=WaterfallWorldHomeStage, obj=obj214.
    """
    if not SHINE_MAP_PATH.exists():
        pytest.skip(f"{SHINE_MAP_PATH} not generated; run scripts/extract_shine_map.py")
    m = ShineMap(SHINE_MAP_PATH)
    res = m.resolve("WaterfallWorldHomeStage", "obj214")
    assert res == MoonResolution(kingdom="Cascade", shine_id="Our First Power Moon")


def test_extracted_kingdom_set_known() -> None:
    """All extracted kingdom labels must be ones the apworld knows about."""
    known = {
        "Cap", "Cascade", "Sand", "Lake", "Wooded", "Cloud", "Lost",
        "Metro", "Snow", "Seaside", "Luncheon", "Ruined", "Bowser's",
        "Moon", "Mushroom", "Dark Side", "Darker Side",
    }
    actual = {e["kingdom"] for e in _entries()}
    extra = actual - known
    assert not extra, f"unexpected kingdoms in extraction: {extra}"


# -- scenario-gating fields (docs/scenario-gating-logic-design.md) --

SCENARIO_GATING_KEYS = {
    "progress_bit_flag", "main_scenario_no", "is_moon_rock", "is_grand",
}


def test_scenario_gating_fields_present_and_typed() -> None:
    for i, e in enumerate(_entries()):
        missing = SCENARIO_GATING_KEYS - set(e)
        assert not missing, f"entry {i} missing gating keys {missing}"
        assert isinstance(e["progress_bit_flag"], int)
        assert isinstance(e["main_scenario_no"], int)
        assert isinstance(e["is_moon_rock"], bool)
        assert isinstance(e["is_grand"], bool)


def test_progress_bit_flag_is_nonzero() -> None:
    """Every moon is placed in at least one scenario, so the mask is never 0."""
    zero = [e for e in _entries() if e["progress_bit_flag"] == 0]
    assert not zero, f"{len(zero)} moons with empty ProgressBitFlag mask"


def test_some_story_anchors_present() -> None:
    """main_scenario_no == -1 for ordinary moons; story/grand moons anchor a
    scenario. The set must be non-empty (40 in SMO 1.0.0) and a strict subset."""
    entries = _entries()
    anchors = [e for e in entries if e["main_scenario_no"] != -1]
    assert anchors, "no story-anchor moons found (main_scenario_no all -1)"
    assert len(anchors) < len(entries), "every moon flagged as an anchor (wrong)"


# -- world_scenarios.json (per-kingdom scenario semantics) --

WORLD_SCENARIO_KEYS = {
    "home_stage", "world_name", "scenario_num", "clear_main_scenario",
    "moon_rock_scenario", "after_ending_scenario",
}


def _world_scenarios() -> dict:
    if not WORLD_SCENARIOS_PATH.exists():
        pytest.skip(f"{WORLD_SCENARIOS_PATH} not generated; run scripts/extract_shine_map.py")
    return json.loads(WORLD_SCENARIOS_PATH.read_text(encoding="utf-8"))


def test_world_scenarios_schema_and_kingdoms() -> None:
    known = {
        "Cap", "Cascade", "Sand", "Lake", "Wooded", "Cloud", "Lost",
        "Metro", "Snow", "Seaside", "Luncheon", "Ruined", "Bowser's",
        "Moon", "Mushroom", "Dark Side", "Darker Side",
    }
    ws = _world_scenarios()
    extra = set(ws) - known
    assert not extra, f"unexpected kingdoms in world_scenarios: {extra}"
    # All 17 playable kingdoms should be present.
    assert known - set(ws) == set(), f"missing kingdoms: {known - set(ws)}"
    for kingdom, rec in ws.items():
        missing = WORLD_SCENARIO_KEYS - set(rec)
        assert not missing, f"{kingdom} missing keys {missing}"
        assert isinstance(rec["scenario_num"], int) and rec["scenario_num"] > 0
        for k in ("clear_main_scenario", "moon_rock_scenario",
                  "after_ending_scenario"):
            assert isinstance(rec[k], int)


# -- capture_map.json --


def _capture_entries() -> list[dict]:
    if not CAPTURE_MAP_PATH.exists():
        pytest.skip(f"{CAPTURE_MAP_PATH} not generated; run scripts/extract_shine_map.py")
    return json.loads(CAPTURE_MAP_PATH.read_text(encoding="utf-8"))


CAPTURE_REQUIRED_KEYS = {"hack_name", "cap"}


def test_capture_map_schema() -> None:
    for i, e in enumerate(_capture_entries()):
        missing = CAPTURE_REQUIRED_KEYS - set(e)
        assert not missing, f"capture entry {i} missing keys {missing}: {e}"
        assert isinstance(e["hack_name"], str) and e["hack_name"]
        assert isinstance(e["cap"], str) and e["cap"]


def test_capture_map_alias_table_semantics() -> None:
    """Spot-check one example per alias-table case so the extractor's
    CAPTURE_NAME_ALIASES semantics stay tested. Kept intentionally small to
    avoid bulk transcription of the Nintendo internal-name -> English table.
    """
    if not CAPTURE_MAP_PATH.exists():
        pytest.skip(f"{CAPTURE_MAP_PATH} not generated; run scripts/extract_shine_map.py")
    m = CaptureMap(CAPTURE_MAP_PATH)
    # canonical Japanese internal -> apworld English (most-known anchor)
    assert m.resolve("Kuribo") == "Goomba"
    # alias case: variant collapse (multiple Nintendo entries -> one apworld)
    assert m.resolve("FukuwaraiFacePartsKuribo") == "Picture Match Part"
    # alias case: casing override
    assert m.resolve("StatueKoopa") == "Bowser Statue"


def test_capture_map_every_entry_resolves_to_a_string() -> None:
    """Structural — no Nintendo strings asserted, just shape."""
    m = CaptureMap(CAPTURE_MAP_PATH)
    for e in _capture_entries():
        assert m.resolve(e["hack_name"]) == e["cap"]


def test_capture_map_no_duplicate_hack_keys() -> None:
    keys = [e["hack_name"] for e in _capture_entries()]
    dups = {k for k in keys if keys.count(k) > 1}
    assert not dups, f"duplicate hack_name keys: {dups}"


# -- bootstrap re-launch must not regress to os.execv (Windows quoting + rc bug) --


def test_bootstrap_does_not_use_os_execv() -> None:
    """`scripts/extract_shine_map.py` must NOT use `os.execv` to re-launch
    under the venv'd Python on Windows. Two reasons:

      1. `os.execv` on Windows is implemented via Microsoft's `_wspawnv`,
         which does NOT quote argv entries containing spaces. A path like
         `C:\\...\\super mario odyssey.nsp` arrives at the relaunched
         Python as 3 separate argv tokens; argparse then complains about
         `unrecognized arguments: mario odyssey.nsp`.
      2. `os.execv` on Windows is NOT a true process replacement — it
         spawns the new process and the caller exits with code 0
         immediately. The parent subprocess.Popen sees rc=0 regardless
         of the child's real exit code, masking failures from any
         wrapper (such as the setup wizard).

    Use `subprocess.run([...])` + `sys.exit(proc.returncode)` instead —
    `list2cmdline` quotes args with spaces correctly, and the exit code
    propagates honestly."""
    script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "extract_shine_map.py"
    if not script.exists():
        pytest.skip(f"{script} not present (running from installed apworld)")
    src = script.read_text(encoding="utf-8")
    # Strip the comment block that explains WHY we avoid os.execv — that
    # mention is intentional, not a regression. Anywhere outside a
    # comment is forbidden.
    code_only = "\n".join(
        line for line in src.splitlines()
        if "os.execv" not in line or line.lstrip().startswith("#")
    )
    assert "os.execv" not in code_only, (
        "scripts/extract_shine_map.py reintroduced os.execv outside a "
        "comment. Use subprocess.run + sys.exit(returncode) instead — "
        "see the docstring of _bootstrap_and_reexec for the full "
        "Windows-specific rationale."
    )
