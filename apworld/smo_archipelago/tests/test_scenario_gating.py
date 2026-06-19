"""Unit tests for the coarse scenario-reachability gating in
scripts/compile_moon_logic.py (post_peace classification).

Covers the pure helpers only — no romfs / shine_map dependency — so these run in
CI without the gitignored Nintendo-IP tables. See
docs/scenario-reachability-design.md §2-3 for the model these encode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# compile_moon_logic.py lives in the repo-root scripts/ dir, not on the apworld
# package path the conftest sets up. Load it by file path so the test is
# location-independent and never triggers the (guarded) main().
_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "compile_moon_logic.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("compile_moon_logic", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("compile_moon_logic", mod)
    spec.loader.exec_module(mod)
    return mod


cml = _load_module()


# Real per-kingdom scenario numbers (functional, IP-safe — same as the
# world_scenarios.json the extractor emits; these are scenario counts, not names).
SAND = {"scenario_num": 7, "clear_main_scenario": 3}      # peace_bit = 2
METRO = {"scenario_num": 11, "clear_main_scenario": 4}    # peace_bit = 3
CASCADE = {"scenario_num": 7, "clear_main_scenario": 7}   # SENTINEL (clear==num)
CAP = {"scenario_num": 6, "clear_main_scenario": 2}       # peace_bit = 1, floor = 1
DARK = {"scenario_num": 2, "clear_main_scenario": 2}      # SENTINEL


class TestLowestSetBit:
    @pytest.mark.parametrize("flag, expected", [
        (1, 0),      # bit 0 only
        (14, 1),     # bits {1,2,3}  -> min 1 (Cap-style, no bit 0)
        (79, 0),     # bits {0,1,2,3,6}
        (8, 3),      # bit 3 only (rock-layer style)
        (12, 2),     # bits {2,3}
    ])
    def test_lsb(self, flag, expected):
        assert cml.lowest_set_bit(flag) == expected

    def test_zero_is_safe(self):
        # progress_bit_flag is never 0 in real data, but the helper must not crash.
        assert cml.lowest_set_bit(0) == 0


class TestClassifyPostPeace:
    def test_first_visit_moon_is_free(self):
        # Sand moon present from arrival (bit 0) -> not post_peace.
        assert not cml.classify_scenario_post_peace(0b0000001, SAND, 0, "Sand")

    def test_post_peace_moon_gated(self):
        # Sand moon whose earliest scenario is the peace scenario (bit 2).
        assert cml.classify_scenario_post_peace(0b0000100, SAND, 0, "Sand")

    def test_mid_story_collapses_to_free(self):
        # Sand moon first present at bit 1 (mid-story, < peace_bit 2) -> free in
        # the coarse tier.
        assert not cml.classify_scenario_post_peace(0b0000010, SAND, 0, "Sand")

    def test_metro_deep_peace_bit(self):
        assert cml.classify_scenario_post_peace(0b0001000, METRO, 0, "Metro")  # bit 3
        assert not cml.classify_scenario_post_peace(0b0000100, METRO, 0, "Metro")  # bit 2

    def test_cascade_never_gated_by_bit_rule(self):
        # Even a high-bit Cascade moon stays free — clear=7 is its LAST scenario.
        assert not cml.classify_scenario_post_peace(0b1000000, CASCADE, 0, "Cascade")

    def test_sentinel_kingdom_never_gated(self):
        # Dark Side: clear_main_scenario == scenario_num -> sentinel, no gate.
        assert not cml.classify_scenario_post_peace(0b10, DARK, 0, "Dark Side")

    def test_cap_floor_guard(self):
        # Cap's moons start at bit 1 (floor == peace_bit == 1); the floor guard
        # prevents mis-gating its first-visit moons. (Cap has no *Peace() predicate
        # anyway, but the classifier must not claim post_peace here.)
        assert not cml.classify_scenario_post_peace(0b10, CAP, 1, "Cap")


class TestBuildPostPeaceNames:
    def test_degrades_to_rock_only_without_scenario_data(self):
        rocks = frozenset({"Sand: Some Rock", "Wooded: Another Rock"})
        assert cml.build_post_peace_names(rocks, None, None) == set(rocks)

    def test_folds_rocks_with_scenario_moons(self):
        rocks = frozenset({"Sand: A Rock"})
        shine = [
            # first-visit (bit 0) -> not added
            {"kingdom": "Sand", "shine_id": "Early", "progress_bit_flag": 0b001,
             "is_moon_rock": False},
            # post-peace (bit 2 == peace_bit) -> added
            {"kingdom": "Sand", "shine_id": "Late", "progress_bit_flag": 0b100,
             "is_moon_rock": False},
            # a rock by flag -> skipped here (already covered via rocks set)
            {"kingdom": "Sand", "shine_id": "RockByFlag", "progress_bit_flag": 0b10000,
             "is_moon_rock": True},
        ]
        world = {"Sand": SAND}
        out = cml.build_post_peace_names(rocks, shine, world)
        assert "Sand: A Rock" in out          # rock preserved
        assert "Sand: Late" in out            # post-peace folded in
        assert "Sand: Early" not in out       # first-visit stays free
        assert "Sand: RockByFlag" not in out  # rock-by-flag not double-added here


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
