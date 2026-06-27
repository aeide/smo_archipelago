"""Unit tests for scenario-reachability gating in scripts/compile_moon_logic.py.

Per-kingdom scenario gating is now SPREADSHEET-AUTHORITATIVE (data/scenario_gates.json,
compiled by parse_scenario_spreadsheet.py) because the romfs progress_bit_flag measures
object presence, not collectability — bit-0 story moons leaked to FREE. The bit-driven
helpers (build_post_peace_names / build_mid_story_anchors / scenario_fragments_for) are
DEPRECATED and no longer wired into gating; their tests remain as historical coverage.
The live carve-outs that stay bit-driven are Cascade (build_cascade_anchors departure
pass) and Moon (build_rearrival_names + build_moon_postwin_names).

Pure-helper tests run with no romfs / shine_map dependency; the file-integrity tests
read the committed (IP-safe) scenario_gates.json + locations.json.
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
# Cascade: clear==num (SENTINEL for the coarse peace rule); after_ending=3 -> ae_bit=2
# drives the dedicated pass's CascadePeace/CascadeDeparture split.
CASCADE = {"scenario_num": 7, "clear_main_scenario": 7, "after_ending_scenario": 3}
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
    def test_degrades_to_empty_without_scenario_data(self):
        # D2: post_peace is bit-classified only; with no scenario data there is no
        # category seed to fall back to -> empty.
        assert cml.build_post_peace_names(None, None) == set()

    def test_classifies_by_bit_no_category_seed(self):
        shine = [
            # first-visit (bit 0) -> not added
            {"kingdom": "Sand", "shine_id": "Early", "progress_bit_flag": 0b001,
             "is_moon_rock": False},
            # post-peace (bit 2 == peace_bit) -> added
            {"kingdom": "Sand", "shine_id": "Late", "progress_bit_flag": 0b100,
             "is_moon_rock": False},
            # §4b regression guard: an is_moon_rock moon with NO "Moon Rock" category is
            # now gated by its BIT (bit 4 >= peace_bit 2), not skipped/free.
            {"kingdom": "Sand", "shine_id": "RockByFlag", "progress_bit_flag": 0b10000,
             "is_moon_rock": True},
        ]
        world = {"Sand": SAND}
        out = cml.build_post_peace_names(shine, world)
        assert "Sand: Late" in out            # post-peace by bit
        assert "Sand: RockByFlag" in out      # disjoint rock now bit-gated (the §4b fix)
        assert "Sand: Early" not in out       # first-visit stays free
        # No category seed: a "Moon Rock" category name not present in shine is NOT
        # injected by this function anymore.
        assert "Sand: A Category Rock" not in out


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

    def test_rock_moon_in_mid_band_now_gated_by_bit(self):
        # D2: is_moon_rock is no longer a skip. A rock sitting in the mid band
        # (first_visit < bit < peace_bit) is classified by its bit like any other moon
        # and gets the story-anchor gate.
        shine = [
            {"kingdom": "Sand", "shine_id": "Showdown", "progress_bit_flag": 0b001,
             "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Sand", "shine_id": "RockMoon", "progress_bit_flag": 0b010,
             "is_moon_rock": True, "is_grand": False},
        ]
        locs = {"Sand: Showdown", "Sand: RockMoon"}
        anchors, _ = cml.build_mid_story_anchors(shine, self.WS, set(), locs)
        assert anchors["Sand: RockMoon"] == "{canReachLocation(Sand: Showdown)}"


class TestBuildCascadeAnchors:
    # after_ending=3 -> ae_bit=2: bit 1 -> CascadePeace, bits >=2 -> CascadeDeparture.
    WS = {"Cascade": {"scenario_num": 7, "clear_main_scenario": 7,
                      "after_ending_scenario": 3}}

    def test_degrades_without_data(self):
        assert cml.build_cascade_anchors(None, None, set()) == ({}, 0)
        assert cml.build_cascade_anchors([], self.WS, set()) == ({}, 0)

    def test_departure_emitted_even_without_peace_anchor(self):
        # No "Cascade: Multi Moon Atop the Falls" location -> the pre-leave CascadePeace
        # branch can't fire, but the post-leave (>= ae_bit) layers still gate on
        # CascadeDeparture (which has no location dependency).
        shine = [
            {"kingdom": "Cascade", "shine_id": "ChainArea",   # bit1 (pre-leave)
             "progress_bit_flag": 0b0010, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "Revisit2",    # bit2 (>= ae_bit)
             "progress_bit_flag": 0b0100, "is_moon_rock": False, "is_grand": False},
        ]
        anchors, n = cml.build_cascade_anchors(
            shine, self.WS, {"Cascade: ChainArea", "Cascade: Revisit2"})
        assert anchors == {"Cascade: Revisit2": "{CascadeDeparture()}"}
        assert n == 1
        assert "Cascade: ChainArea" not in anchors  # no peace anchor -> left free

    def test_splits_pre_leave_peace_from_post_leave_departure(self):
        # bit 0 (anchor) free; bit 1 -> CascadePeace; bits 2,3 -> CascadeDeparture.
        # Rocks are classified by their bit, not skipped (D2): the bit-3 rock gets
        # CascadeDeparture like any other after-ending moon.
        shine = [
            {"kingdom": "Cascade", "shine_id": "Multi Moon Atop the Falls",
             "progress_bit_flag": 0b0001, "is_moon_rock": False, "is_grand": True},
            {"kingdom": "Cascade", "shine_id": "ChainArea",   # bit1 -> peace
             "progress_bit_flag": 0b0010, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "Revisit2",    # bit2 -> departure
             "progress_bit_flag": 0b0100, "is_moon_rock": False, "is_grand": False},
            {"kingdom": "Cascade", "shine_id": "RockMoon",    # bit3 rock -> departure
             "progress_bit_flag": 0b1000, "is_moon_rock": True, "is_grand": False},
        ]
        locs = {"Cascade: Multi Moon Atop the Falls", "Cascade: ChainArea",
                "Cascade: Revisit2", "Cascade: RockMoon"}
        anchors, n = cml.build_cascade_anchors(shine, self.WS, locs)
        assert anchors == {
            "Cascade: ChainArea": "{CascadePeace()}",
            "Cascade: Revisit2": "{CascadeDeparture()}",
            "Cascade: RockMoon": "{CascadeDeparture()}",
        }
        assert n == 3
        assert "Cascade: Multi Moon Atop the Falls" not in anchors  # anchor / bit0 free


class TestBuildRearrivalNames:
    def test_degrades_without_data(self):
        assert cml.build_rearrival_names(None) == set()
        assert cml.build_rearrival_names([]) == set()

    def test_classifies_layer_excludes_first_visit_includes_rocks(self):
        shine = [
            # Cap starts at bit 1 (first-visit) -> excluded
            {"kingdom": "Cap", "shine_id": "Start", "progress_bit_flag": 0b0010,
             "is_moon_rock": False},
            # Cap bit 2 (> first_playable 1) -> re-arrival
            {"kingdom": "Cap", "shine_id": "Revisit", "progress_bit_flag": 0b0100,
             "is_moon_rock": False},
            # Cap bit 3 rock -> NOW included (D2: rocks classified by bit, gate via
            # CapPeace == canReachRegion(Sand), i.e. "you have left and can return").
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
        assert out == {"Cap: Revisit", "Cap: RockMoon", "Lost: Late"}
        assert "Cap: Start" not in out         # first-visit wave stays free
        assert "Sand: Mid" not in out          # non-re-arrival kingdom


class TestScenarioGateGatesFor:
    """gates_for appends the per-location scenario fragment from the merged
    scenario_gate_by_name dict (spreadsheet gates + Cascade/Moon carve-out gates)."""

    def test_gates_for_appends_scenario_gate(self):
        sg = {
            "Lost: Late": "{LostPeace()}",
            "Sand: Mid": "{canReachLocation(Sand: The Hole in the Desert)}",
            "Cascade: X": "{CascadeDeparture()}",
        }
        assert "{LostPeace()}" in cml.gates_for("Lost: Late", {}, sg, set())
        assert ("{canReachLocation(Sand: The Hole in the Desert)}"
                in cml.gates_for("Sand: Mid", {}, sg, set()))
        assert "{CascadeDeparture()}" in cml.gates_for("Cascade: X", {}, sg, set())

    def test_location_absent_from_table_gets_no_scenario_gate(self):
        assert cml.gates_for("Lost: Early", {}, {"Lost: Late": "{LostPeace()}"},
                             set()) == []


class TestMoonRockReachCapture:
    def test_constants(self):
        assert cml.MOON_ROCK_REACH_CAPTURE["Cap"] == "|Paragoomba|"
        assert cml.MOON_ROCK_REACH_CAPTURE["Luncheon"] == "|Lava Bubble|"

    def test_gates_for_appends_capture_to_rock_only(self):
        rock = "Cap: Roll On and On"
        gates = cml.gates_for(rock, {}, {}, {rock})
        assert "|Paragoomba|" in gates
        # A non-rock Cap location (not in moon_rock_names) gets no reach capture.
        non_rock = cml.gates_for("Cap: Some Overworld Moon", {}, {}, set())
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
        gates = cml.gates_for(loc, {}, {}, set(), {loc})
        assert cml.MOON_CAVE_TRAVERSAL in gates
        # A Moon location NOT in the cave set gets no traversal gate.
        free = cml.gates_for("Moon: Some Overworld Moon", {}, {}, set())
        assert cml.MOON_CAVE_TRAVERSAL not in free

    def test_default_cave_arg_is_noop(self):
        # Back-compat: gates_for without the moon_cave arg behaves as before.
        assert cml.gates_for("Moon: In a Hole in the Magma", {}, {}, set()) == []


class TestBuildMoonPostwinNames:
    def test_degrades_without_data(self):
        assert cml.build_moon_postwin_names(None) == set()
        assert cml.build_moon_postwin_names([]) == set()

    def test_classifies_postwin_purely_by_bit(self):
        # D2: tagged purely by the scenario bit (min_scenario > first_playable). In real
        # data every Moon rock already sits at a later scenario, so the bit rule catches
        # them without an is_moon_rock read. A synthetic rock sharing the arrival bit is
        # therefore treated as arrival (collectable) — the bit is authoritative.
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
            # A real moon-rock layer moon sits at a later scenario -> tagged by bit.
            {"kingdom": "Moon", "shine_id": "Rock", "progress_bit_flag": 0b0100,
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


class TestScenarioFragmentsFor:
    """scenario_fragments_for isolates the post_peace / mid_story / re-arrival gate
    fragment(s) — exactly what gates_for appends — for the D3 subarea export."""

    def test_post_peace_fragment(self):
        assert cml.scenario_fragments_for(
            "Sand: Late", {"Sand: Late"}, {}, set()) == ["{SandPeace()}"]

    def test_mid_story_fragment(self):
        anchors = {"Sand: Mid": "{canReachLocation(Sand: The Hole in the Desert)}"}
        assert cml.scenario_fragments_for(
            "Sand: Mid", set(), anchors, set()) == [
                "{canReachLocation(Sand: The Hole in the Desert)}"]

    def test_rearrival_fragment(self):
        # Cap is in REARRIVAL_PEACE_GATES but not MOON_ROCK_PEACE_GATES, so it gets
        # only the re-arrival gate.
        assert cml.scenario_fragments_for(
            "Cap: Revisit", set(), {}, {"Cap: Revisit"}) == ["{CapPeace()}"]

    def test_post_peace_xor_mid(self):
        # post_peace wins over mid (mirrors gates_for's if/elif).
        anchors = {"Sand: X": "{canReachLocation(Sand: The Hole in the Desert)}"}
        assert cml.scenario_fragments_for(
            "Sand: X", {"Sand: X"}, anchors, set()) == ["{SandPeace()}"]

    def test_first_visit_no_fragment(self):
        assert cml.scenario_fragments_for("Sand: Early", set(), {}, set()) == []


class TestBuildSubareaScenarioGates:
    """build_subarea_scenario_gates groups pooled-subarea moons -> {loc: fragment}."""

    SUBAREAS = {
        # pooled subarea, two members at different layers
        "Deep Cave": {
            "kingdom": "Sand Kingdom",
            "location_names": ["Sand: Late", "Sand: Mid", "Sand: Early"],
        },
        # excluded subarea — must be omitted entirely
        "Sewers": {
            "kingdom": "Metro Kingdom",
            "location_names": ["Metro: Festival"],
        },
    }
    EXCLUDED = {"Sewers"}
    LOC_NAMES = {"Sand: Late", "Sand: Mid", "Sand: Early", "Metro: Festival",
                 "Sand: Overworld"}
    # Merged scenario gate table (spreadsheet + carve-out gates) — the single source
    # build_subarea_scenario_gates now reads. "Sand: Early" deliberately absent (free).
    SCEN = {
        "Sand: Late": "{SandPeace()}",
        "Metro: Festival": "{MetroPeace()}",
        "Sand: Mid": "{canReachLocation(Sand: The Hole in the Desert)}",
    }

    def _build(self, junk=frozenset()):
        return cml.build_subarea_scenario_gates(
            self.SUBAREAS, self.EXCLUDED, junk, self.LOC_NAMES, self.SCEN)

    def test_pooled_members_exported_with_their_own_fragment(self):
        gates = self._build()
        assert gates["Sand: Late"] == "{SandPeace()}"
        assert gates["Sand: Mid"] == "{canReachLocation(Sand: The Hole in the Desert)}"

    def test_first_visit_member_not_exported(self):
        # Sand: Early has no scenario gate -> absent from the export.
        assert "Sand: Early" not in self._build()

    def test_excluded_subarea_member_not_exported(self):
        # Metro: Festival is post_peace but lives in the EXCLUDED Sewers -> omitted.
        assert "Metro: Festival" not in self._build()

    def test_overworld_nonsubarea_moon_not_exported(self):
        assert "Sand: Overworld" not in self._build()

    def test_junk_member_skipped(self):
        gates = self._build(junk={"Sand: Late"})
        assert "Sand: Late" not in gates
        assert "Sand: Mid" in gates  # other members still exported


class TestSubareaScenarioGatesFileIntegrity:
    """The committed subarea_scenario_gates.json must agree with locations.json:
    every exported fragment's predicate(s) appear in the baked requires (they share
    a compile pass, so any drift means a stale regen). Runs without shine_map — both
    files are committed."""

    _DATA = Path(__file__).resolve().parents[1] / "data"

    def _load(self, name):
        import json
        return json.loads((self._DATA / name).read_text(encoding="utf-8"))

    def test_export_consistent_with_baked_requires(self):
        import json
        import re
        gates_path = self._DATA / "subarea_scenario_gates.json"
        if not gates_path.exists():
            pytest.skip("subarea_scenario_gates.json not generated")
        gates = json.loads(gates_path.read_text(encoding="utf-8"))
        baked = {l["name"]: l.get("requires", "") for l in self._load("locations.json")}
        func_re = re.compile(r"\{(\w+\([^)]*\))\}")
        for loc, frag in gates.items():
            assert loc in baked, f"{loc} exported but absent from locations.json"
            for call in func_re.findall(frag):
                assert call in baked[loc], (
                    f"{loc}: exported {call} missing from baked requires "
                    f"{baked[loc]!r} — stale regen?")


class TestSpreadsheetScenarioGates:
    """The committed scenario_gates.json (authored ground truth, compiled by
    parse_scenario_spreadsheet.py) and its application into locations.json. These
    run without shine_map — both files are committed and IP-safe."""

    _DATA = Path(__file__).resolve().parents[1] / "data"

    def _json(self, name):
        import json
        return json.loads((self._DATA / name).read_text(encoding="utf-8"))

    def _gates(self):
        p = self._DATA / "scenario_gates.json"
        if not p.exists():
            pytest.skip("scenario_gates.json not generated")
        return self._json("scenario_gates.json")

    def test_all_canreach_targets_exist(self):
        import re
        gates = self._gates()
        loc_names = {l["name"] for l in self._json("locations.json")}
        for name, frag in gates.items():
            for tgt in re.findall(r"canReachLocation\(([^)]+)\)", frag):
                assert tgt in loc_names, f"{name}: canReachLocation({tgt}) is not a location"

    def test_no_self_reference(self):
        gates = self._gates()
        for name, frag in gates.items():
            assert f"canReachLocation({name})" not in frag, f"{name} gates on itself"

    def test_no_cycles_including_peace_expansion(self):
        # Each {<K>Peace()} predicate expands to canReachLocation(<clear moon>); a cycle
        # across that boundary would make a kingdom permanently incompletable.
        import re
        gates = self._gates()
        peace_loc = {
            "CascadePeace": "Cascade: Multi Moon Atop the Falls",
            "SandPeace": "Sand: The Hole in the Desert",
            "LakePeace": "Lake: Broodals Over the Lake",
            "WoodedPeace": "Wooded: Defend the Secret Flower Field!",
            "MetroPeace": "Metro: A Traditional Festival!",
            "SnowPeace": "Snow: The Bound Bowl Grand Prix",
            "SeasidePeace": "Seaside: The Glass Is Half Full!",
            "LuncheonPeace": "Luncheon: Cookatiel Showdown!",
            "RuinedPeace": "Ruined: Battle with the Lord of Lightning!",
            "BowserPeace": "Bowser's: Showdown at Bowser's Castle",
        }

        def edges(name):
            frag = gates.get(name, "")
            e = set(re.findall(r"canReachLocation\(([^)]+)\)", frag))
            for fn in re.findall(r"\{(\w+)\(\)\}", frag):
                if fn in peace_loc:
                    e.add(peace_loc[fn])
            return {x for x in e if x in gates}

        color = {}
        bad = []

        def dfs(u, stack):
            color[u] = 1
            stack.append(u)
            for v in edges(u):
                if color.get(v, 0) == 1:
                    bad.append(stack[stack.index(v):] + [v])
                elif color.get(v, 0) == 0:
                    dfs(v, stack)
            color[u] = 2
            stack.pop()

        for n in gates:
            if color.get(n, 0) == 0:
                dfs(n, [])
        assert not bad, f"cycle(s) in scenario gating: {bad[:3]}"

    def test_carveouts_only_emit_fork_painting(self):
        # Cascade/Moon are owned by the dedicated departure / postwin passes; the only
        # carve-out-kingdom entry the spreadsheet contributes is the fork painting.
        gates = self._gates()
        cascade = [k for k in gates if k.startswith("Cascade: ")]
        moon = [k for k in gates if k.startswith("Moon: ")]
        assert cascade == ["Cascade: Secret Path to Fossil Falls!"]
        assert moon == []

    def test_known_leaks_now_gated_in_locations(self):
        # Regression guard for the §2 bit-0 free-leaks: each must now carry its
        # spreadsheet scenario predicate in the baked locations.json requires.
        baked = {l["name"]: l.get("requires", "") for l in self._json("locations.json")}
        expect = {
            "Luncheon: Surrounded by Tall Mountains":
                "canReachLocation(Luncheon: Under the Cheese Rocks)",
            "Snow: Dashing Over Cold Water!":
                "canReachLocation(Snow: The Bound Bowl Grand Prix)",
            "Wooded: Behind the Rock Wall":
                "canReachLocation(Wooded: Flower Thieves of Sky Garden)",
            "Metro: Pushing Through the Crowd":
                "canReachLocation(Metro: New Donk City's Pest Problem)",
            "Bowser's: Smart Bombing":
                "canReachLocation(Bowser's: Infiltrate Bowser's Castle!)",
        }
        for name, needle in expect.items():
            if name in baked:
                assert needle in baked[name], (
                    f"{name} should be gated on {needle} but requires={baked[name]!r} "
                    f"— stale compile? re-run compile_moon_logic.py")

    def test_fork_moons_carry_order_independent_gate(self):
        gates = self._gates()
        assert gates.get("Cascade: Secret Path to Fossil Falls!") == \
            "({SnowPeace()} or {SeasidePeace()})"
        assert gates.get("Sand: Secret Path to Tostarena!") == \
            "{canReachLocation(Wooded: Flower Thieves of Sky Garden)}"
        assert gates.get("Snow: Secret Path to Shiveria!") == "{MoonPeace()}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
