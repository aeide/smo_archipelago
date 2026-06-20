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


class TestBuildMidStoryAnchors:
    # Minimal world_scenarios with the fields the classifier reads.
    WS = {
        "Sand":  {"scenario_num": 7, "clear_main_scenario": 3},   # peace_bit 2
        "Metro": {"scenario_num": 11, "clear_main_scenario": 4},  # peace_bit 3
        "Cascade": {"scenario_num": 7, "clear_main_scenario": 7}, # peace trap
        "Cap":   {"scenario_num": 6, "clear_main_scenario": 2},   # peace_bit 1, floor 1
    }

    def test_degrades_without_data(self):
        anchors, stats = cml.build_mid_story_anchors(None, None, set(), set())
        assert anchors == {} and stats == {}

    def test_sand_mid_story_uses_first_grand(self):
        shine = [
            # grand advancer at bit 0 (collecting it enters scenario 1)
            {"kingdom": "Sand", "shine_id": "Showdown", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            # the peace grand at bit 1 (NOT the mid anchor)
            {"kingdom": "Sand", "shine_id": "Hole", "progress_bit_flag": 0b010,
             "is_moon_rock": False, "is_grand": True},
            # a mid_story moon: earliest scenario 1 (< peace_bit 2)
            {"kingdom": "Sand", "shine_id": "MidMoon", "progress_bit_flag": 0b010,
             "is_moon_rock": False, "is_grand": False},
            # a first_visit moon (bit 0) — stays free
            {"kingdom": "Sand", "shine_id": "EarlyMoon", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": False},
        ]
        locs = {"Sand: Showdown", "Sand: Hole", "Sand: MidMoon", "Sand: EarlyMoon"}
        anchors, stats = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        # Both the ordinary mid moon AND the peace grand "Hole" (itself at bit 1, < the
        # peace_bit 2) chain onto the earlier bit-0 advancer "Showdown". The chain is
        # transitive and never self-references (Showdown != Hole). The first-visit
        # "EarlyMoon" stays free.
        assert anchors == {
            "Sand: MidMoon": "{canReachLocation(Sand: Showdown)}",
            "Sand: Hole": "{canReachLocation(Sand: Showdown)}",
        }
        assert stats == {"Sand": 2}

    def test_metro_missing_bit1_grand_and_festival_self_ref(self):
        # Metro has grands at bit 0 and bit 2 but none at bit 1.
        #  * Mid1 (bit 1) -> its bit-0 advancer "Pest".
        #  * Mid2 (bit 2) -> no bit-1 advancer, so it over-gates to {MetroPeace()}.
        #  * Festival (bit 2, the peace anchor itself) must be SKIPPED — gating it on
        #    the peace predicate would self-reference (MetroPeace == canReach(Festival))
        #    and make Metro permanently incompletable.
        shine = [
            {"kingdom": "Metro", "shine_id": "Pest", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Metro", "shine_id": "Festival", "progress_bit_flag": 0b100,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Metro", "shine_id": "Mid1", "progress_bit_flag": 0b010,   # bit1
             "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Metro", "shine_id": "Mid2", "progress_bit_flag": 0b100,   # bit2
             "is_moon_rock": False, "is_grand": False},
        ]
        locs = {"Metro: Pest", "Metro: Festival", "Metro: Mid1", "Metro: Mid2"}
        anchors, _ = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        assert anchors["Metro: Mid1"] == "{canReachLocation(Metro: Pest)}"   # bit0
        assert anchors["Metro: Mid2"] == cml.MOON_ROCK_PEACE_GATES["Metro"]  # over-gate
        assert "Metro: Festival" not in anchors                              # self-ref skip

    def test_cascade_excluded_from_mid_story(self):
        # Cascade is handled by the dedicated build_cascade_anchors pass (see
        # TestBuildCascadeAnchors), NOT by the generic mid_story chain: its clear
        # scenario is its LAST (after_ending earlier), so the bit band has no clean
        # advancer chain. build_mid_story_anchors must therefore emit nothing for
        # Cascade — the dedicated pass owns those gates.
        shine = [
            {"kingdom": "Cascade", "shine_id": "Multi", "progress_bit_flag": 0b0000001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Cascade", "shine_id": "ChainArea", "progress_bit_flag": 0b0000010,
             "is_moon_rock": False, "is_grand": False},  # bit1, no bit0
        ]
        locs = {"Cascade: Multi", "Cascade: ChainArea"}
        anchors, stats = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        assert anchors == {}
        assert "Cascade" not in stats

    def test_post_peace_moon_excluded(self):
        # A moon already in post_peace_names is not also mid-gated.
        shine = [
            {"kingdom": "Sand", "shine_id": "Showdown", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Sand", "shine_id": "MidMoon", "progress_bit_flag": 0b010,
             "is_moon_rock": False, "is_grand": False},
        ]
        locs = {"Sand: Showdown", "Sand: MidMoon"}
        anchors, _ = cml.build_mid_story_anchors(
            shine, self.WS, {"Sand: MidMoon"}, locs)
        assert "Sand: MidMoon" not in anchors

    def test_anchor_missing_from_locations_drops_to_no_gate(self):
        # If the resolved anchor isn't a real location and there's no peace fallback,
        # the moon is left free rather than referencing a phantom location.
        shine = [
            {"kingdom": "Sand", "shine_id": "Showdown", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Sand", "shine_id": "MidMoon", "progress_bit_flag": 0b010,
             "is_moon_rock": False, "is_grand": False},
        ]
        # "Sand: Showdown" intentionally absent from the location set.
        locs = {"Sand: MidMoon"}
        anchors, _ = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        # Sand has a peace fragment, so it falls back to that rather than free.
        assert anchors["Sand: MidMoon"] == cml.MOON_ROCK_PEACE_GATES["Sand"]

    def test_rock_moon_excluded(self):
        shine = [
            {"kingdom": "Sand", "shine_id": "Showdown", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Sand", "shine_id": "RockMoon", "progress_bit_flag": 0b010,
             "is_moon_rock": True, "is_grand": False},
        ]
        locs = {"Sand: Showdown", "Sand: RockMoon"}
        anchors, _ = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        assert "Sand: RockMoon" not in anchors


class TestBuildCascadeAnchors:
    WS = {"Cascade": {"scenario_num": 7, "clear_main_scenario": 7}}  # peace trap

    def test_degrades_without_data(self):
        assert cml.build_cascade_anchors(None, None, set()) == ({}, 0)
        assert cml.build_cascade_anchors([], self.WS, set()) == ({}, 0)

    def test_missing_anchor_location_disables(self):
        # No "Cascade: Multi Moon Atop the Falls" location -> can't gate (the gate
        # is canReachLocation on that name), so emit nothing rather than a phantom.
        shine = [{"kingdom": "Cascade", "shine_id": "ChainArea",
                  "progress_bit_flag": 0b10, "is_moon_rock": False, "is_grand": False}]
        assert cml.build_cascade_anchors(shine, self.WS, {"Cascade: ChainArea"}) == ({}, 0)

    def test_gates_post_first_visit_layers(self, monkeypatch):
        # With the full-gating policy (MAX=3) every non-rock Cascade moon at
        # min_scenario 1..3 ANDs in {CascadePeace()}; bit-0 first-visit (the Multi
        # Moon anchor itself) and rock moons are excluded.
        monkeypatch.setattr(cml, "CASCADE_GATE_MIN_LAYER", 1)
        monkeypatch.setattr(cml, "CASCADE_GATE_MAX_LAYER", 3)
        shine = [
            {"kingdom": "Cascade", "shine_id": "Multi Moon Atop the Falls",
             "progress_bit_flag": 0b0001, "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Cascade", "shine_id": "ChainArea",   # bit1
             "progress_bit_flag": 0b0010, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "Revisit2",    # bit2
             "progress_bit_flag": 0b0100, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "Revisit3",    # bit3
             "progress_bit_flag": 0b1000, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "RockMoon",    # rock -> category-gated
             "progress_bit_flag": 0b0010, "is_moon_rock": True, "is_grand": False},
        ]
        locs = {"Cascade: Multi Moon Atop the Falls", "Cascade: ChainArea",
                "Cascade: Revisit2", "Cascade: Revisit3", "Cascade: RockMoon"}
        anchors, n = cml.build_cascade_anchors(shine, self.WS, locs)
        assert anchors == {
            "Cascade: ChainArea": "{CascadePeace()}",
            "Cascade: Revisit2": "{CascadePeace()}",
            "Cascade: Revisit3": "{CascadePeace()}",
        }
        assert n == 3
        assert "Cascade: Multi Moon Atop the Falls" not in anchors  # anchor / bit0
        assert "Cascade: RockMoon" not in anchors                   # rock excluded

    def test_layer_cap_leaves_revisit_free(self, monkeypatch):
        # The fill-capacity cap (CASCADE_GATE_MAX_LAYER) bounds the top layer gated;
        # at MAX=1 only the layer-1 moons gate, deeper revisit layers stay free.
        monkeypatch.setattr(cml, "CASCADE_GATE_MIN_LAYER", 1)
        monkeypatch.setattr(cml, "CASCADE_GATE_MAX_LAYER", 1)
        shine = [
            {"kingdom": "Cascade", "shine_id": "ChainArea",
             "progress_bit_flag": 0b0010, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "Revisit2",
             "progress_bit_flag": 0b0100, "is_moon_rock": False, "is_grand": False},
        ]
        locs = {"Cascade: Multi Moon Atop the Falls", "Cascade: ChainArea",
                "Cascade: Revisit2"}
        anchors, n = cml.build_cascade_anchors(shine, self.WS, locs)
        assert anchors == {"Cascade: ChainArea": "{CascadePeace()}"}
        assert n == 1


class TestBuildRearrivalNames:
    def test_degrades_without_data(self):
        assert cml.build_rearrival_names(None) == set()
        assert cml.build_rearrival_names([]) == set()

    def test_classifies_layer_excludes_first_visit_and_rocks(self):
        shine = [
            # Cap starts at bit 1 (first-visit) -> excluded
            {"kingdom": "Cap", "shine_id": "Start", "progress_bit_flag": 0b0010,
             "is_moon_rock": False},
            # Cap bit 2 (> first_playable 1) -> re-arrival
            {"kingdom": "Cap", "shine_id": "Revisit", "progress_bit_flag": 0b0100,
             "is_moon_rock": False},
            # Cap bit 3 rock -> excluded (rocks gated elsewhere)
            {"kingdom": "Cap", "shine_id": "RockMoon", "progress_bit_flag": 0b1000,
             "is_moon_rock": True},
            # Lost starts at bit 0 -> bit 1 is re-arrival
            {"kingdom": "Lost", "shine_id": "Early", "progress_bit_flag": 0b0001,
             "is_moon_rock": False},
            {"kingdom": "Lost", "shine_id": "Late", "progress_bit_flag": 0b0010,
             "is_moon_rock": False},
            # Sand is NOT a re-arrival kingdom -> never added even past first-visit
            {"kingdom": "Sand", "shine_id": "Mid", "progress_bit_flag": 0b0100,
             "is_moon_rock": False},
        ]
        out = cml.build_rearrival_names(shine)
        assert out == {"Cap: Revisit", "Lost: Late"}
        assert "Cap: Start" not in out         # first-visit wave stays free
        assert "Cap: RockMoon" not in out      # rocks excluded
        assert "Sand: Mid" not in out          # non-re-arrival kingdom


class TestRearrivalGatesFor:
    def test_gates_for_appends_rearrival_predicate(self):
        loc = "Lost: Late"
        gates = cml.gates_for(loc, {}, set(), {}, set(), {loc})
        assert "{LostPeace()}" in gates
        # A re-arrival kingdom location NOT in the rearrival set gets no gate.
        free = cml.gates_for("Lost: Early", {}, set(), {}, set(), set())
        assert "{LostPeace()}" not in free
        # Each re-arrival kingdom maps to its own predicate.
        assert "{CapPeace()}" in cml.gates_for(
            "Cap: Revisit", {}, set(), {}, set(), {"Cap: Revisit"})
        assert "{MoonPeace()}" in cml.gates_for(
            "Moon: Pipe", {}, set(), {}, set(), {"Moon: Pipe"})

    def test_default_rearrival_arg_is_noop(self):
        # Back-compat: gates_for without the rearrival arg behaves as before.
        assert cml.gates_for("Lost: Late", {}, set(), {}, set()) == []


class TestMoonRockReachCapture:
    def test_constants(self):
        assert cml.MOON_ROCK_REACH_CAPTURE["Cap"] == "|Paragoomba|"
        assert cml.MOON_ROCK_REACH_CAPTURE["Luncheon"] == "|Lava Bubble|"

    def test_gates_for_appends_capture_to_rock_only(self):
        rock = "Cap: Roll On and On"
        gates = cml.gates_for(rock, {}, set(), {}, {rock})
        assert "|Paragoomba|" in gates
        # A non-rock Cap location (not in moon_rock_names) gets no reach capture.
        non_rock = cml.gates_for("Cap: Some Overworld Moon", {}, set(), {}, set())
        assert "|Paragoomba|" not in non_rock


class TestMoonCaveTraversal:
    def test_fragment_has_both_sets(self):
        frag = cml.MOON_CAVE_TRAVERSAL
        # Capture set A.
        assert "|Parabones|" in frag
        assert "|Banzai Bill|" in frag
        assert "|Spark pylon|" in frag
        # Ability set B (GPJ folds in its Progressive Ground Pound prerequisite).
        assert "|Ground Pound Jump|" in frag
        assert "|Progressive Ground Pound:1|" in frag
        assert "|Cap Bounce|" in frag
        assert "|Wall Slide|" in frag
        # The two sets are OR-combined (either path clears the cave).
        assert " or " in frag

    def test_rafters_is_an_extra_cave_location(self):
        assert "Moon: Up in the Rafters" in cml.MOON_CAVE_EXTRA_LOCATIONS

    def test_gates_for_appends_traversal_to_cave_moon(self):
        loc = "Moon: In a Hole in the Magma"
        gates = cml.gates_for(loc, {}, set(), {}, set(), frozenset(), {loc})
        assert cml.MOON_CAVE_TRAVERSAL in gates
        # A Moon location NOT in the cave set gets no traversal gate.
        free = cml.gates_for("Moon: Some Overworld Moon", {}, set(), {}, set())
        assert cml.MOON_CAVE_TRAVERSAL not in free

    def test_default_cave_arg_is_noop(self):
        # Back-compat: gates_for without the moon_cave arg behaves as before.
        assert cml.gates_for("Moon: In a Hole in the Magma", {}, set(), {}, set()) == []


class TestBuildMoonPostwinNames:
    def test_degrades_without_data(self):
        assert cml.build_moon_postwin_names(None) == set()
        assert cml.build_moon_postwin_names([]) == set()

    def test_classifies_rearrival_and_rock_excludes_arrival(self):
        shine = [
            # Moon first-visit layer (min_scenario == first_playable 0) -> arrival, kept
            {"kingdom": "Moon", "shine_id": "Boss", "progress_bit_flag": 0b0001,
             "is_moon_rock": False},
            {"kingdom": "Moon", "shine_id": "Cave", "progress_bit_flag": 0b0001,
             "is_moon_rock": False},
            # Re-arrival layer (min_scenario > 0) -> post-win
            {"kingdom": "Moon", "shine_id": "Revisit1", "progress_bit_flag": 0b0010,
             "is_moon_rock": False},
            {"kingdom": "Moon", "shine_id": "Revisit2", "progress_bit_flag": 0b0100,
             "is_moon_rock": False},
            # Moon-rock layer -> post-win even though it shares a bit with arrival
            {"kingdom": "Moon", "shine_id": "Rock", "progress_bit_flag": 0b0001,
             "is_moon_rock": True},
            # A different kingdom is never tagged
            {"kingdom": "Cap", "shine_id": "Whatever", "progress_bit_flag": 0b0100,
             "is_moon_rock": True},
        ]
        out = cml.build_moon_postwin_names(shine)
        assert out == {"Moon: Revisit1", "Moon: Revisit2", "Moon: Rock"}
        assert "Moon: Boss" not in out      # first-visit stays collectable/in-logic
        assert "Moon: Cave" not in out
        assert "Cap: Whatever" not in out   # only Moon Kingdom


class TestFreeCapturesAndJoin:
    def test_broodes_chain_chomp_is_free(self):
        # Granted as a fixed starter in hooks/World.py, so it never gates.
        assert "Broode's Chain Chomp" in cml.FREE_CAPTURES

    def test_and_join_dedupes_idempotent_terms(self):
        assert cml.and_join(["|A|", "|A|"]) == "|A|"
        assert cml.and_join(["|A|", "|B|", "|A|"]) == "(|A| and |B|)"
        assert cml.and_join(["", "|A|", ""]) == "|A|"
        assert cml.and_join([]) == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
