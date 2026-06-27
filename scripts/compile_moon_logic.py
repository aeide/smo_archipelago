#!/usr/bin/env python3
"""
compile_moon_logic.py  (Stage 2 of the P6 "update logic" pipeline)

Reads the faithful structured requirements produced by
import_moon_requirements.py and compiles each moon into a manual-AP `requires`
string, written back into apworld/smo_archipelago/data/locations.json.

Compilation model (locked with Devon 2026-06-17):
  moon.requires = OR(methods)  AND  kingdom-gate  AND  subarea-gate  AND  per-moon-gate
  each method   = AND(height-term, throw-term, other-terms, capture-term)

Decisions baked in:
  * Height is a FLOOR: a min-height requirement is satisfied by ANY jump item
    reaching >= that height (the "ladder").  Long Jump is its own axis.
  * Vault == Cap Bounce, so the 496 tier = Backflip OR Side Flip OR Cap Bounce
    OR Spin (the spin jump's 490 apex is treated as the same vault tier).
  * Movement prerequisites (real-SMO mechanics): Backflip & Long Jump each also
    need Progressive Crouch:1; Ground Pound Jump also needs Progressive Ground
    Pound:1.  Side Flip has no prerequisite.
  * Free captures (always available, never gating): Frog, Chain Chomp.
  * "assume MORE": where uncertain, pick the stricter rule and flag it in
    docs/logic-compile-review.md.

Run AFTER import_moon_requirements.py, on Windows:
    python scripts/compile_moon_logic.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "apworld" / "smo_archipelago" / "data"
LOCATIONS = DATA_DIR / "locations.json"
REQUIREMENTS = DATA_DIR / "moon_requirements.json"
SUBAREAS = DATA_DIR / "subareas.json"
ENTRANCE_EXCLUSIONS = DATA_DIR / "entrance_exclusions.json"
# D3: per-member scenario gate export for the entrance-shuffle ON path. See
# build_subarea_scenario_gates + hooks/World.py::_apply_subarea_scenario_gates.
SUBAREA_SCENARIO_GATES = DATA_DIR / "subarea_scenario_gates.json"
# Spreadsheet-driven scenario gates (authoritative source of truth — see
# scripts/parse_scenario_spreadsheet.py). Replaces the romfs bit-driven scenario
# tiers for every kingdom EXCEPT the Cascade-departure + Moon-postwin carve-outs,
# because the romfs progress_bit_flag measures object presence, not collectability
# (bit-0 moons that are actually story-gated leaked to FREE). Keyed by location
# name; values are functional {Func()} fragments (IP-safe, committed).
SCENARIO_GATES = DATA_DIR / "scenario_gates.json"
REVIEW_DOC = REPO_ROOT / "docs" / "logic-compile-review.md"

# ─────────────────────────────────────────────────────────────────────────────
# Boolean-expression helpers — always fully parenthesised for the manual parser.
# ─────────────────────────────────────────────────────────────────────────────

def and_join(parts: list[str]) -> str:
    # AND is idempotent: drop empties and exact-duplicate fragments (preserving
    # order) so e.g. a moon-rock capture gate doesn't repeat a term the moon's own
    # method already requires (Luncheon: Treasure of the Lava Islands -> Lava Bubble).
    seen: set[str] = set()
    parts = [p for p in parts if p and not (p in seen or seen.add(p))]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " and ".join(parts) + ")"


def or_join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " or ".join(parts) + ")"


# ─────────────────────────────────────────────────────────────────────────────
# Item fragments (with movement prerequisites folded in)
# ─────────────────────────────────────────────────────────────────────────────
# Always-available captures — precollected as fixed starters in hooks/World.py
# (FIXED_STARTER_CAPTURES), so they never gate. Broode's Chain Chomp is granted up
# front because Cascade's story moon (Multi Moon Atop the Falls) needs it and the
# Cascade scenario gating relies on Multi Moon being collectable from arrival.
FREE_CAPTURES = frozenset({"Frog", "Chain Chomp", "Broode's Chain Chomp"})

JUMP_FRAG: dict[str, str] = {
    "PJ1":       "|Progressive Jump:1|",                                  # Double
    "PJ2":       "|Progressive Jump:2|",                                  # Triple
    "CAP_BOUNCE": "|Cap Bounce|",                                         # = vault
    "BACKFLIP":  "(|Backflip| and |Progressive Crouch:1|)",
    "SIDE_FLIP": "|Side Flip|",
    "SPIN_JUMP": "|Spin|",                                                # spin jump, 490 ≈ vault (no crouch prereq)
    "GPJ":       "(|Ground Pound Jump| and |Progressive Ground Pound:1|)",
    "LONG_JUMP": "(|Long Jump| and |Progressive Crouch:1|)",
}

# Min-height enum -> the jump-item keys that reach >= that height.
# Reach: Double 312 < CapReturn/Vault 400-496 == Backflip/SideFlip/CapBounce/Spin
#        (Spin 490 ≈ 496) < GPJ 514 < Triple 550.  (Long Jump is a separate horizontal axis.)
HEIGHT_SATISFIERS: dict[str, list[str]] = {
    "double":     ["PJ1", "CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "SPIN_JUMP", "GPJ", "PJ2"],
    "cap_return": ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "SPIN_JUMP", "GPJ", "PJ2"],
    "backflip":   ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "SPIN_JUMP", "GPJ", "PJ2"],
    "gpj":        ["GPJ", "PJ2"],
    "triple":     ["PJ2"],
    # "none"/"single" -> baseline (free); "long_jump" handled separately
}

THROW_FRAG: dict[str, str] = {
    "up": "|Up Throw|", "down": "|Down Throw|", "spin": "|Spin Throw|",
}  # neutral / none -> baseline (free)

OTHER_FRAG: dict[str, str | None] = {
    "ground_pound": "|Progressive Ground Pound:1|",
    "dive":         "|Progressive Ground Pound:2|",
    "crouch":       "|Progressive Crouch:1|",
    "roll":         "|Progressive Crouch:2|",
    "roll_boost":   "|Progressive Crouch:3|",
    "wall_slide":   "|Wall Slide|",  # also covers ceiling swing pole (PoleGrabCeil) /
                                      # ledge grab — Ledge Grab is auto-granted with Wall
                                      # Slide, so pole moons require wall_slide in logic
    "climb":        "|Climb|",
    "cap_bounce":   "|Cap Bounce|",
    "bonk_roll":    "|Progressive Crouch:2|",  # FLAG: Bonk(Roll) assumed to need Roll
    "single":       None,                      # baseline (free)
    # "capture" handled separately via capture_groups
}

# ─────────────────────────────────────────────────────────────────────────────
# Kingdom-overworld + subarea entrance gates (docs/capture-requirement-notes.md
# lines 1-16).  ANDed onto every moon in the kingdom / subarea.
# ─────────────────────────────────────────────────────────────────────────────
_HIGH_JUMP = or_join([JUMP_FRAG["BACKFLIP"], JUMP_FRAG["SIDE_FLIP"],
                      JUMP_FRAG["SPIN_JUMP"], JUMP_FRAG["PJ2"], JUMP_FRAG["GPJ"]])

# Lake overworld: Zipper OR (high jump + Cap Bounce + (Dive OR Wall Slide)).
# notes "Wall Jump" -> AP item Wall Slide; "Dive" -> Progressive Ground Pound:2.
_LAKE_GATE = or_join([
    "|Zipper|",
    and_join([_HIGH_JUMP, "|Cap Bounce|",
              or_join(["|Progressive Ground Pound:2|", "|Wall Slide|"])]),
])

# Keyed by the short kingdom prefix used in location names.
KINGDOM_GATES: dict[str, str] = {
    "Metro":    "|Spark pylon|",
    "Bowser's": "|Spark pylon|",
    "Lake":     _LAKE_GATE,
}

# Re-arrival ("leave and come back") gates — the four kingdoms with no boss-style
# world-peace cutscene (Cap/Cloud/Lost/Moon). Their post-first-visit moon layers only
# open on RE-ARRIVAL, which the AP graph models as "the kingdom's revisit hub / next
# kingdom is reachable". A moon here is in the re-arrival layer iff its earliest
# scenario is past the first-visit wave (min_scenario > first_playable_bit) — a broader
# rule than the coarse post_peace `>= peace_bit` test, which the floor guard (Cap/Cloud
# start at bit 1) would otherwise skip entirely. Predicates live in hooks/Rules.py
# (canReachRegion-based). Cap/Cloud are redundant-but-harmless (their region already
# sits behind the hub); Lost is load-bearing (Night Metro needs enough Lost moons);
# Moon is currently a no-op (Moon -> Mushroom ungated) kept for uniformity.
REARRIVAL_PEACE_GATES: dict[str, str] = {
    "Cap":   "{CapPeace()}",
    "Cloud": "{CloudPeace()}",
    "Lost":  "{LostPeace()}",
    "Moon":  "{MoonPeace()}",
}

# Peace gates for Moon Rock (post-peace moon-pipe) locations.
# Cap/Cloud/Lost omitted — peace = kingdom reachability, requires stays "".
MOON_ROCK_PEACE_GATES: dict[str, str] = {
    "Cascade":  "{CascadePeace()}",
    "Sand":     "{SandPeace()}",
    "Lake":     "{LakePeace()}",
    "Wooded":   "{WoodedPeace()}",
    "Metro":    "{MetroPeace()}",
    "Snow":     "{SnowPeace()}",
    "Seaside":  "{SeasidePeace()}",
    "Luncheon": "{LuncheonPeace()}",
    "Ruined":   "{RuinedPeace()}",
    "Bowser's": "{BowserPeace()}",
}

# Cascade's "you have left and come back" gate (Rules.CascadeDeparture ==
# canReachRegion("Sand Kingdom")). Cascade has no boss-peace cutscene and its
# clear_main_scenario is its LAST scenario, so its after-ending + moon-rock layers
# (bit >= after_ending_scenario-1) gate on departure, not peace. See
# docs/scenario-logic-revisit-june-20.md §5a.
CASCADE_DEPARTURE_GATE = "{CascadeDeparture()}"

# ─────────────────────────────────────────────────────────────────────────────
# Scenario reachability (COARSE tier) — see docs/scenario-reachability-design.md.
#
# Generalizes the rock-only {<Kingdom>Peace()} rule to ALL post-peace moons.
# A moon is post_peace iff:  is_moon_rock  OR  min_scenario >= peace_bit
#   min_scenario = lowest set bit of progress_bit_flag (earliest scenario the
#                  moon is ever present in).
#   peace_bit    = clear_main_scenario - 1   (from world_scenarios.json).
# post_peace moons AND in {<Kingdom>Peace()} (folded with MOON_ROCK_PEACE_GATES so
# a rock moon is gated once, not twice). Cap/Cloud/Lost/Moon have no boss-style
# *Peace() predicate in this coarse tier; their post-first-visit ("re-arrival") layer
# is instead handled by build_rearrival_names + REARRIVAL_PEACE_GATES (see below).
#
# mid_story (a moon needing partial story progress but not peace) is gated by
# build_mid_story_anchors() below — see its block comment for the model.
#
# The inputs (shine_map.json / world_scenarios.json) are read at BUILD TIME ONLY and
# are gitignored Nintendo-IP. The compiler emits only boolean {Peace()} fragments;
# no names ship. When the data is absent the scenario layer degrades to a no-op
# (rock moons still gated via the locations.json "Moon Rock" category).
# ─────────────────────────────────────────────────────────────────────────────


def _scenario_data_dirs() -> list[Path]:
    """Search order for the gitignored scenario tables, freshest first.

    The romfs extractor writes the scenario-bearing maps to the bridge data dir;
    the wizard/client copy under %APPDATA% may predate the scenario fields, so it
    is only a fallback. The in-repo client/data is a last-resort dev location.
    """
    dirs = [REPO_ROOT / "bridge" / "smo_ap_bridge" / "data"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "SMOArchipelago" / "data")
    else:
        dirs.append(Path.home() / ".local" / "share" / "SMOArchipelago" / "data")
    dirs.append(REPO_ROOT / "apworld" / "smo_archipelago" / "client" / "data")
    return dirs


def _load_scenario_table(filename: str, require_field: str | None = None):
    """First existing `filename` across _scenario_data_dirs whose first record
    carries `require_field` (so a pre-scenario shine_map.json copy is skipped).
    Returns the parsed JSON or None."""
    for d in _scenario_data_dirs():
        p = d / filename
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if require_field is not None:
            seq = data if isinstance(data, list) else []
            if not seq or require_field not in seq[0]:
                continue
        return data
    return None


def lowest_set_bit(flag: int) -> int:
    """Index of the least-significant set bit (== min_scenario for a moon's mask)."""
    if flag <= 0:
        return 0
    return (flag & -flag).bit_length() - 1


def classify_scenario_post_peace(
    progress_bit_flag: int, world_scen: dict, first_playable_bit: int, kingdom: str
) -> bool:
    """COARSE post_peace test for a NON-rock moon (rocks are gated via category).

    Returns True iff the moon's earliest scenario is at/after the kingdom's peace
    scenario, with the design's special-cases honored:
      * Cascade — never (clear_main_scenario=7 is its LAST scenario, not peace).
      * Sentinel kingdoms (clear_main_scenario >= scenario_num) — peace "never",
        no gate (Dark/Darker; their moons are junk_only anyway).
      * peace_bit <= first_playable_bit — degenerate floor (e.g. Cap's bit-1
        start); the bit rule would mis-gate first-visit moons, so no gate.
    """
    if kingdom == "Cascade":
        return False
    clear = world_scen["clear_main_scenario"]
    scenario_num = world_scen["scenario_num"]
    if clear >= scenario_num:               # sentinel — peace unreachable / N/A
        return False
    peace_bit = clear - 1
    if peace_bit <= first_playable_bit:     # floor guard (Cap bit-1 case)
        return False
    return lowest_set_bit(progress_bit_flag) >= peace_bit


def build_post_peace_names(
    shine_map: list | None,
    world_scen: dict | None,
) -> set[str]:
    """DEPRECATED / NO LONGER WIRED INTO GATING. Superseded by the spreadsheet-driven
    scenario_gates.json (see SCENARIO_GATES + parse_scenario_spreadsheet.py): the romfs
    progress_bit_flag measures object presence, not collectability, so bit-0 story moons
    leaked to FREE. Retained only for the unit tests / historical reference — do NOT
    re-wire this into main(); per-kingdom scenario gating is authored, not bit-derived.

    Non-junk moons classified post_peace purely by their progress_bit_flag
    (min_scenario >= kingdom peace_bit). Keyed by AP location name
    (`<kingdom>: <shine_id>`). Degrades to empty when scenario data is absent.

    D2 (docs/scenario-logic-revisit-june-20.md §9): gating is driven SOLELY by the
    game-provided scenario bit — no `is_moon_rock` read, no `"Moon Rock"` category
    seed. Boss-kingdom rocks satisfy `min_scenario >= peace_bit` on their own bit, so
    they land here naturally (this recovers the 39 previously logic-free rock moons).
    Cascade is handled by build_cascade_anchors (classify returns False for it); the
    Cap/Cloud/Lost/Moon floor-guard kingdoms are handled by build_rearrival_names."""
    names: set[str] = set()
    if not shine_map or not world_scen:
        return names
    # Per-kingdom first_playable_bit = min set bit across all of the kingdom's
    # moons (so Cap's bit-1 floor isn't read as mid-story / post-peace).
    first_playable: dict[str, int] = {}
    for e in shine_map:
        k = e["kingdom"]
        b = lowest_set_bit(e["progress_bit_flag"])
        first_playable[k] = min(first_playable.get(k, b), b)
    for e in shine_map:
        kingdom = e["kingdom"]
        ws = world_scen.get(kingdom)
        if ws is None:
            continue
        if classify_scenario_post_peace(
            e["progress_bit_flag"], ws, first_playable.get(kingdom, 0), kingdom
        ):
            names.add(f"{kingdom}: {e['shine_id']}")
    return names


def build_rearrival_names(shine_map: list | None) -> set[str]:
    """Non-rock moons in the REARRIVAL_PEACE_GATES kingdoms (Cap/Cloud/Lost/Moon)
    whose earliest scenario is past the first-visit wave (min_scenario >
    first_playable_bit) — the "leave and come back" re-arrival layer. Keyed by AP
    location name. Degrades to empty when scenario data is absent. Only shine_map is
    needed (the rule is purely the per-kingdom bit floor, not world_scenarios).

    D2: classification is bit-driven only — rocks are NOT excluded. A rock in one of
    these kingdoms whose earliest scenario is past first-visit is a genuine re-arrival
    moon and gets the kingdom's {*Peace()} (canReachRegion) gate like any other moon."""
    names: set[str] = set()
    if not shine_map:
        return names
    first_playable: dict[str, int] = {}
    for e in shine_map:
        k = e["kingdom"]
        b = lowest_set_bit(e["progress_bit_flag"])
        first_playable[k] = min(first_playable.get(k, b), b)
    for e in shine_map:
        k = e["kingdom"]
        if k not in REARRIVAL_PEACE_GATES:
            continue
        if lowest_set_bit(e["progress_bit_flag"]) > first_playable.get(k, 0):
            names.add(f"{k}: {e['shine_id']}")
    return names


def build_moon_postwin_names(shine_map: list | None) -> set[str]:
    """Moon Kingdom moons that CANNOT be collected before the game-clear goal.

    Under the current goal (mushroom_kingdom — leaving Moon ends the game) only the
    first-visit layer (min_scenario == first_playable_bit) is collectable. Everything
    at a later scenario (min_scenario > first_playable_bit) is post-win — the re-arrival
    AND moon-rock layers both sit there, only reachable by leaving and returning, so
    they must hold only filler (no progression item may be stranded behind an
    uncollectable check). D2: tagged purely by the scenario bit — no `is_moon_rock`
    read (verified redundant: all of Moon's rock moons already have min_scenario > the
    arrival bit, so the bit rule alone catches them).

    Returned names are tagged `moon_postwin: true` in locations.json; the runtime hook
    (_apply_moon_postwin_rules) enforces the filler restriction, gated on the goal so a
    future Dark/Darker-Side goal can lift it. Keyed by AP location name; degrades to
    empty without shine_map. (A moon present in scenario 0 is collectable on the first
    visit even if it sits behind the boss, so min_scenario==fp is a safe arrival floor.)"""
    names: set[str] = set()
    if not shine_map:
        return names
    moon = [e for e in shine_map if e["kingdom"] == "Moon"]
    if not moon:
        return names
    fp = min(lowest_set_bit(e["progress_bit_flag"]) for e in moon)
    for e in moon:
        if lowest_set_bit(e["progress_bit_flag"]) > fp:
            names.add(f"Moon: {e['shine_id']}")
    return names


# ─────────────────────────────────────────────────────────────────────────────
# Scenario reachability (MID_STORY tier) — see docs/scenario-reachability-design.md §2.3.
#
# A non-rock moon whose earliest scenario sits BETWEEN first-visit and peace
# (first_playable_bit < min_scenario < peace_bit) is only collectable after the
# kingdom advances PAST scenario (min_scenario - 1). The advance is driven by
# collecting that kingdom's story moons, which are themselves AP locations — so the
# faithful gate is `canReachLocation(<the grand story moon that advances the kingdom
# INTO min_scenario>)`.
#
# The advancer into scenario S is the GRAND moon present at min-bit (S-1) (collecting
# a grand at min-bit b moves the kingdom b -> b+1; validated: Sand "Hole in the
# Desert" bit1 -> peace_bit2, Wooded "Defend..." bit1 -> 2, Metro "Festival" bit2 ->
# 3 all line up with the Rules.py peace anchors). So for a moon at min_scenario M we
# pick the grand with the smallest min-bit >= (M-1). When no grand anchor is
# available at/after that bit (Metro's missing bit-1 grand -> falls through to the
# bit-2 Festival, a safe over-gate), or for Cascade (whose clear_main_scenario is its
# LAST scenario, not peace — the peace-bit band is meaningless there), we fall back to
# the kingdom's existing {<Kingdom>Peace()} fragment.
#
# Same IP posture as the coarse tier: the gitignored scenario tables are read at BUILD
# TIME ONLY; the emitted fragments are functional ({canReachLocation(<name>)} where
# <name> is already a committed locations.json entry, or {<Kingdom>Peace()}). No new
# Nintendo strings ship.
# ─────────────────────────────────────────────────────────────────────────────


def build_mid_story_anchors(
    shine_map: list | None,
    world_scen: dict | None,
    post_peace_names: set[str] | frozenset[str],
    location_names: set[str] | frozenset[str],
) -> tuple[dict[str, str], dict[str, int]]:
    """DEPRECATED / NO LONGER WIRED INTO GATING — see build_post_peace_names' note.
    Per-kingdom mid-story gating is now authored in scenario_gates.json (bit-banding
    could not gate the bit-0 story moons). Retained only for the unit tests.

    Map each mid_story location name -> the {gate} fragment to AND in.

    Returns (anchors, stats); stats counts emitted fragments per kingdom. Degrades to
    ({}, {}) when scenario data is absent. post_peace_names is consulted so a moon is
    never both peace-gated (coarse) and mid-gated."""
    anchors: dict[str, str] = {}
    stats: dict[str, int] = {}
    if not shine_map or not world_scen:
        return anchors, stats

    first_playable: dict[str, int] = {}
    grand_by_bit: dict[str, dict[int, str]] = {}
    for e in shine_map:
        k = e["kingdom"]
        b = lowest_set_bit(e["progress_bit_flag"])
        first_playable[k] = min(first_playable.get(k, b), b)
        if e.get("is_grand"):
            grand_by_bit.setdefault(k, {}).setdefault(b, f"{k}: {e['shine_id']}")

    for e in shine_map:
        # D2: no is_moon_rock skip — a rock in the mid band (first_visit < min_scenario
        # < peace_bit) is classified by its bit like any other moon. Most rocks sit at
        # min_scenario >= peace_bit and are dropped below by the post_peace guard.
        k = e["kingdom"]
        ws = world_scen.get(k)
        if ws is None:
            continue
        loc = f"{k}: {e['shine_id']}"
        if loc in post_peace_names:
            continue                        # already coarse peace-gated
        # Cascade is DEFERRED from mid_story (as in the coarse pass): its
        # clear_main_scenario is its LAST scenario (after_ending sits earlier), so the
        # bit band doesn't form a clean advancer chain, and routing its ~19
        # post-first-visit moons to {CascadePeace()} starves the early fill spheres
        # enough to make generation fail on some seeds. Cascade's first advance (Multi
        # Moon Atop the Falls) is mandatory-early and player-controlled, so leaving
        # these moons free is safe. A dedicated Cascade pass is the follow-up.
        if k == "Cascade":
            continue
        fp = first_playable.get(k, 0)
        m = lowest_set_bit(e["progress_bit_flag"])
        if m <= fp:
            continue                        # first_visit — stays free

        clear = ws["clear_main_scenario"]
        scenario_num = ws["scenario_num"]
        if clear >= scenario_num:           # sentinel — no peace, no mid band
            continue
        peace_bit = clear - 1
        if peace_bit <= fp:                 # degenerate floor (Cap-style)
            continue
        if m >= peace_bit:                  # post_peace — handled by coarse tier
            continue

        gb = grand_by_bit.get(k, {})
        # The advancer INTO scenario m is the grand at bit (m-1) — strictly below m, so
        # it is never this moon itself. Use it when present (the tight, faithful gate).
        advancer = gb.get(m - 1)
        if advancer and advancer != loc and advancer in location_names:
            frag = f"{{canReachLocation({advancer})}}"
        else:
            # No exact advancer (e.g. Metro has no bit-1 grand): safe over-gate to the
            # kingdom peace predicate. BUT never gate the peace-anchor moon itself (the
            # grand at bit peace_bit-1) on peace — that would self-reference and make
            # {<Kingdom>Peace()} permanently false (e.g. Metro's Festival).
            peace_anchor = gb.get(peace_bit - 1)
            if loc == peace_anchor:
                continue
            frag = MOON_ROCK_PEACE_GATES.get(k, "")
        if not frag:
            continue                        # no usable gate -> leave free
        anchors[loc] = frag
        stats[k] = stats.get(k, 0) + 1
    return anchors, stats


# ─────────────────────────────────────────────────────────────────────────────
# Scenario reachability (CASCADE dedicated pass) — docs/scenario-logic-revisit-june-20.md §5a.
#
# Cascade has no boss-style world-peace cutscene, and its clear_main_scenario is its
# LAST scenario (after_ending_scenario sits earlier), so the generic peace-bit rule
# doesn't apply. Gate every non-first-visit Cascade moon purely on its scenario bit
# relative to ae_bit = after_ending_scenario - 1 (== 2 for Cascade):
#   min_scenario 0          = first_visit (present from arrival) — stays free.
#   1 .. ae_bit-1           = post-first-advance, pre-leave (after Madame Broode but
#                             before leaving) — {CascadePeace()}. Vacuous-but-correct
#                             today (Broode's Chain Chomp is a fixed starter, so Multi
#                             Moon Atop the Falls is reachable from arrival); documents
#                             intent and survives a future starter change.
#   >= ae_bit               = after-ending + moon-rock layers — only re-entered after
#                             LEAVING and returning, so {CascadeDeparture()} (==
#                             canReachRegion("Sand Kingdom")). THIS is the real gate
#                             that fixes the leave-deadlock: it forces fill to place the
#                             kingdom-gate moons among Cascade's 19 pre-leave locations.
#
# This REPLACES the old vacuous "everything -> {CascadePeace()}" pass (which gated bits
# 1..3 all on an always-true predicate, so the leave-critical bit-2/3 moons looked
# reachable in sphere 1 and fill stranded them behind the leave-wall — see §4a/§4d of
# the diagnosis). Rocks are classified by their bit like any other moon (D2: no
# is_moon_rock read). No CASCADE_GATE_MAX_LAYER cap: with Broode's Chain Chomp a fixed
# starter the pre-leave layer is free, so the fill-starvation the old cap guarded
# against no longer exists (§5c).
#
# Same IP posture as the other tiers: gitignored scenario tables read at BUILD TIME
# ONLY; emitted fragments are functional {CascadePeace()} / {CascadeDeparture()}
# predicates (committed Rules.py over committed names). No new strings ship.
# ─────────────────────────────────────────────────────────────────────────────
CASCADE_GATE_MIN_LAYER = 1   # bit 0 (first_visit) is never gated


def build_cascade_anchors(
    shine_map: list | None,
    world_scen: dict | None,
    location_names: set[str] | frozenset[str],
) -> tuple[dict[str, str], int]:
    """Map each gated Cascade location name -> its scenario fragment; returns
    (anchors, count). Degrades to ({}, 0) when scenario data is absent. Non-first-visit
    Cascade moons (min_scenario >= CASCADE_GATE_MIN_LAYER) are split at ae_bit
    (after_ending_scenario - 1): below ae_bit -> {CascadePeace()} (only if the Multi
    Moon anchor location exists), at/above ae_bit -> {CascadeDeparture()}. The anchor
    moon itself (Multi Moon Atop the Falls, bit 0) is always excluded."""
    anchors: dict[str, str] = {}
    if not shine_map or not world_scen or "Cascade" not in world_scen:
        return anchors, 0
    ws = world_scen["Cascade"]
    ae_bit = ws.get("after_ending_scenario", 1) - 1
    peace = MOON_ROCK_PEACE_GATES.get("Cascade", "")
    have_peace = bool(peace) and "Cascade: Multi Moon Atop the Falls" in location_names
    for e in shine_map:
        if e["kingdom"] != "Cascade":
            continue
        m = lowest_set_bit(e["progress_bit_flag"])
        if m < CASCADE_GATE_MIN_LAYER:
            continue                        # bit 0 first-visit -> free
        loc = f"Cascade: {e['shine_id']}"
        if loc == "Cascade: Multi Moon Atop the Falls" or loc not in location_names:
            continue
        if m >= ae_bit:
            anchors[loc] = CASCADE_DEPARTURE_GATE
        elif have_peace:
            anchors[loc] = peace
        # else: pre-leave layer but no usable peace anchor -> leave free
    return anchors, len(anchors)


# Keyed by subarea name (matches subareas.json keys).
SUBAREA_GATES: dict[str, str] = {
    "Unzipping the Chasm":            "|Zipper|",
    "Sewers":                         "|Manhole|",
    "Rotating Maze Shards":           "|Manhole|",
    "Swinging Along the High-Rises":  "|Mini Rocket|",
    "A Sea of Clouds":                "|Mini Rocket|",
    "Strange Neighborhood":           "|Mini Rocket|",
    "Shards in the Fog":              "|Mini Rocket|",
    "Picture Match (Mario)":          "|Mini Rocket|",
    "Roulette Tower":                 "|Mini Rocket|",
    "Shards Under Siege":             "|Taxi|",
    # Narrow Valley: Gushen OR (max-height jump + Wall Slide + Cap Bounce).
    # FLAG: "max-height jump" read as Triple (the literal max, 550).
    "Flying Through the Narrow Valley": or_join(
        ["|Gushen|", and_join([JUMP_FRAG["PJ2"], "|Wall Slide|", "|Cap Bounce|"])]),
    "Fork-Flickin to the Summit":     "|Lava Bubble|",
    "Shards in the Cheese Rocks":     "|Hammer Bro|",
    "Spinning Athletics":             "|Lava Bubble|",
}

# Per-moon gates that are not subarea-wide (notes line 12).
LOCATION_EXTRA_GATES: dict[str, str] = {
    "Sand: Employees Only": "|Progressive Crouch:1|",   # Crazy Cap back room
}

# Subarea name → INTERIOR-INTRINSIC FULL gate: a complete requires string that may
# MIX {Func()} predicate calls with |item| tokens under AND/OR (which SUBAREA_GATES,
# being a plain item fragment AND-joined onto the move-set, cannot express). For these
# subareas the member moons are free INSIDE — the move-set is dropped — and the whole
# requires becomes just this gate (the subarea's own entry condition). This is the
# shuffle-OFF bake (door == interior, so keying is moot). Under entrance_shuffle ON the
# IDENTICAL string is applied DOOR-keyed via entrance_logic.SUBAREA_ENTRANCE_GATES (the
# gate is a door-exterior requirement — what it takes to reach the door in the overworld
# — so it must travel with the door, not the interior). Keep the two strings in sync;
# guarded by tests/test_entrance_shuffle.py::test_full_gate_mirror_compile_moon_logic.
SUBAREA_INTERIOR_FULL_GATES: dict[str, str] = {
    # Jaxi Driving: Sand world peace OR the move-set to reach it the hard way.
    "Jaxi Driving":
        "({SandPeace()} or (|Bullet Bill| and |Progressive Ground Pound:2| and |Wall Slide|))",
}

# Captures required to physically REACH a kingdom's moon rock (and therefore every
# moon-pipe moon behind it). Only two rocks in the game are capture-gated to reach:
# Cap's (a Paragoomba glide up to the ledge) and Luncheon's (Lava Bubble to cross the
# lava). Devon-sourced 2026-06-19. ANDed onto every Moon Rock-category location in the
# kingdom, on top of any {<Kingdom>Peace()}.
MOON_ROCK_REACH_CAPTURE: dict[str, str] = {
    "Cap":      "|Paragoomba|",
    "Luncheon": "|Lava Bubble|",
}

# Moon Cave traversal gate (Devon-sourced 2026-06-20). To clear Moon Cave (the
# "Underground Caverns" subarea) and beat the game the player needs EITHER the
# capture set (Parabones + Banzai Bill + Spark pylon) OR the ability set (Ground
# Pound Jump + Cap Bounce + Wall Slide). GPJ folds in its Progressive Ground Pound
# prerequisite exactly as everywhere else in this file (you cannot ground-pound-jump
# without ground pound) — a correctness tightening over Devon's literal 3-item set B;
# flip JUMP_FRAG["GPJ"] back to a bare "|Ground Pound Jump|" here if undesired.
#
# ANDed onto (a) every "Underground Caverns" moon, (b) "Moon: Up in the Rafters"
# (also reached only after clearing the cave), and (c) the game-clear goal location
# (so at least one set is guaranteed reachable before the end). Because each cave
# location's `requires` then contains all six items, AP fill can never place any of
# them in a cave location (it would be unreachable) — that satisfies "the items may
# hide in Moon Kingdom but not in Moon Cave moons" for free. The ability set is
# capture-independent, so the goal stays reachable even with capturesanity off.
MOON_CAVE_TRAVERSAL = or_join([
    and_join(["|Parabones|", "|Banzai Bill|", "|Spark pylon|"]),
    and_join([JUMP_FRAG["GPJ"], "|Cap Bounce|", "|Wall Slide|"]),
])

# Cave-reachable moons NOT in the "Underground Caverns" subarea list. "Up in the
# Rafters" lives in the Wedding Room subarea (whose other moons are NOT cave-gated),
# so it is added by name rather than by subarea.
MOON_CAVE_EXTRA_LOCATIONS = frozenset({"Moon: Up in the Rafters"})

# Game-clear goal location (victory). Gated on MOON_CAVE_TRAVERSAL so the six cave
# items are guaranteed placed-and-reachable before the end of the game.
GOAL_LOCATION = "Arrive in the Mushroom Kingdom"

# ─────────────────────────────────────────────────────────────────────────────
# Compilation
# ─────────────────────────────────────────────────────────────────────────────

def capture_term(groups: list[list[str]]) -> str | None:
    """OR over capture groups (AND within each), free captures stripped.
    Returns None when the requirement is free (some group is all-free / empty)."""
    if not groups:
        return None
    or_parts: list[str] = []
    for g in groups:
        items = [c for c in g if c not in FREE_CAPTURES]
        if not items:
            return None  # this whole group is free -> capture satisfied for free
        or_parts.append(and_join([f"|{c}|" for c in items]))
    return or_join(or_parts)


def compile_method(m: dict, groups: list[list[str]]) -> str:
    terms: list[str] = []

    jh = m.get("jump_height")
    if jh == "long_jump":
        terms.append(JUMP_FRAG["LONG_JUMP"])
    elif jh in HEIGHT_SATISFIERS:
        terms.append(or_join([JUMP_FRAG[k] for k in HEIGHT_SATISFIERS[jh]]))
    # none / single -> baseline, no term

    throws = m.get("cap_throws", [])
    if throws and not ({"neutral", "none"} & set(throws)):
        terms.append(or_join([THROW_FRAG[t] for t in throws]))

    for o in m.get("other_required", []):
        if o == "capture":
            ct = capture_term(groups)
            if ct is not None:
                terms.append(ct)
        else:
            frag = OTHER_FRAG[o]
            if frag is not None:
                terms.append(frag)

    return and_join(terms)


def compile_moon(rec: dict) -> str:
    methods = [v for v in rec["methods"].values() if v is not None]
    groups = rec["capture_groups"]
    method_exprs: list[str] = []
    for m in methods:
        e = compile_method(m, groups)
        if e not in method_exprs:           # dedupe identical alternatives
            method_exprs.append(e)
    if any(e == "" for e in method_exprs):
        return ""  # a fully-baseline method exists -> moon is free
    return or_join(method_exprs)


# ─────────────────────────────────────────────────────────────────────────────
# D3 — subarea scenario gate export (entrance-shuffle ON path)
#
# Subarea moons get their scenario gate baked into locations.json `requires` like
# every other moon (so entrance-shuffle OFF is byte-identical to today). But when
# entrance shuffle is ON, hooks/World.py moves each pooled-subarea moon into a
# dynamically-created "<sub> Interior" Region and REPLACES its access rule with the
# move-set-only interior requires (entrance_logic.build_interior_requires_map) —
# dropping the baked scenario gate entirely. The scenario classification is driven
# by the gitignored shine_map (BUILD TIME ONLY), so the apworld can't recompute it
# at gen time; it must be precompiled into a committed file.
#
# scenario_fragments_for() isolates the SCENARIO-tier fragments (post_peace / mid_story
# / re-arrival) — the same ones gates_for appends — so they can be re-applied to the
# interior member location under shuffle. Kingdom, subarea-item, moon-rock-capture and
# moon-cave gates are deliberately NOT exported: under shuffle the kingdom + subarea-
# item gates ride the DOOR entrance (entrance_logic.make_door_access_rule), and the
# excluded cave/moonpipe subareas are never pooled. The gate is interior-INTRINSIC
# (keyed on the moon's own kingdom quest state, not the door), so re-applying it to the
# member location is correct regardless of which door now leads in — the location moves
# with the interior region. IP-safe: keyed by committed location names, values are the
# same functional {Func()} fragments already in locations.json.
# ─────────────────────────────────────────────────────────────────────────────


def scenario_fragments_for(
    location_name: str,
    post_peace_names: set[str] | frozenset[str],
    mid_story_anchors: dict[str, str],
    rearrival_names: set[str] | frozenset[str],
) -> list[str]:
    """DEPRECATED / NO LONGER WIRED IN — build_subarea_scenario_gates now reads the
    merged scenario_gate_by_name dict directly. Retained only for the unit tests.

    The scenario-tier gate fragment(s) for a location — exactly the post_peace /
    mid_story / re-arrival fragments gates_for appends, isolated. Mirrors the branch
    structure in gates_for (post_peace XOR mid_story, then re-arrival appended)."""
    out: list[str] = []
    prefix = location_name.split(": ", 1)[0]
    if location_name in post_peace_names:
        peace = MOON_ROCK_PEACE_GATES.get(prefix, "")
        if peace:
            out.append(peace)
    elif location_name in mid_story_anchors:
        out.append(mid_story_anchors[location_name])
    if location_name in rearrival_names and prefix in REARRIVAL_PEACE_GATES:
        out.append(REARRIVAL_PEACE_GATES[prefix])
    return out


def build_subarea_scenario_gates(
    subareas: dict,
    excluded: set[str] | frozenset[str],
    junk_names: set[str] | frozenset[str],
    location_names: set[str] | frozenset[str],
    scenario_gate_by_name: dict[str, str],
) -> dict[str, str]:
    """Map {location_name: scenario_fragment} for every POOLED-subarea moon that
    carries a scenario gate. Pooled = subareas NOT in the entrance-shuffle exclusion
    set (those are the ones World.py shuffles + strips). Excluded subareas, overworld
    (non-subarea) moons, and junk_only checks are omitted — their baked gate is never
    stripped, so they need no re-application. The fragment is exactly the scenario
    gate baked into locations.json (both read scenario_gate_by_name), so the file can
    never drift from it. The gate is interior-INTRINSIC (the moon's own kingdom quest
    state, not the door), so re-applying it under shuffle is correct regardless of
    which door now leads in."""
    gates: dict[str, str] = {}
    for sub_name, info in subareas.items():
        if sub_name in excluded:
            continue
        for ln in info.get("location_names", []):
            if ln in junk_names or ln not in location_names:
                continue
            frag = scenario_gate_by_name.get(ln)
            if frag:
                gates[ln] = frag
    return gates


def gates_for(location_name: str, loc_subarea_gate: dict[str, str],
              scenario_gate_by_name: dict[str, str],
              moon_rock_names: set[str] | frozenset[str],
              moon_cave_names: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Physical + scenario gates ANDed onto a moon's move-set/capture base.

    The scenario tier is a single lookup in scenario_gate_by_name (spreadsheet
    gates for normal kingdoms; the dedicated Cascade-departure pass and the Moon
    re-arrival fragment are merged into that dict in main()). Kingdom-overworld,
    moon-rock-reach-capture, Moon-Cave, subarea and per-location item gates are
    orthogonal physical requirements and are always ANDed on regardless."""
    out: list[str] = []
    prefix = location_name.split(": ", 1)[0]
    if prefix in KINGDOM_GATES:
        out.append(KINGDOM_GATES[prefix])
    # Capture needed to reach the kingdom's moon rock (Cap=Goomba, Luncheon=Lava
    # Bubble) — applies to every moon-pipe moon behind that rock.
    if location_name in moon_rock_names and prefix in MOON_ROCK_REACH_CAPTURE:
        out.append(MOON_ROCK_REACH_CAPTURE[prefix])
    # Scenario reachability (spreadsheet-authoritative + Cascade/Moon carve-outs).
    frag = scenario_gate_by_name.get(location_name)
    if frag:
        out.append(frag)
    # Moon Cave traversal: every "Underground Caverns" moon + "Up in the Rafters" is
    # reachable only after clearing the cave, so AND in one of the two traversal sets.
    if location_name in moon_cave_names:
        out.append(MOON_CAVE_TRAVERSAL)
    if location_name in loc_subarea_gate:
        out.append(loc_subarea_gate[location_name])
    if location_name in LOCATION_EXTRA_GATES:
        out.append(LOCATION_EXTRA_GATES[location_name])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    requirements = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
    subareas = json.loads(SUBAREAS.read_text(encoding="utf-8"))
    locations = json.loads(LOCATIONS.read_text(encoding="utf-8"))

    # junk_only locations (MK / Dark / Darker-Side filler checks) stay
    # requirement-free so fill can place junk regardless of moveset reachability.
    junk_names = {l["name"] for l in locations if l.get("junk_only")}

    # The "Moon Rock" category is NO LONGER a scenario-reachability input (D2). It is
    # retained ONLY for the MOON_ROCK_REACH_CAPTURE capture gates (Cap/Luncheon) in
    # gates_for, and remains wired to the moon_rock_checks location-enable toggle in
    # categories.json. Scenario gating is driven purely by the progress_bit_flag below.
    moon_rock_names = frozenset(
        l["name"] for l in locations if "Moon Rock" in l.get("category", [])
    )

    location_names = {l["name"] for l in locations}

    # Romfs scenario tables — still read for the Cascade-departure + Moon carve-outs
    # (build_cascade_anchors / build_rearrival_names / build_moon_postwin_names). The
    # general per-kingdom scenario gating no longer derives from these bits; it comes
    # from the authored spreadsheet (SCENARIO_GATES) because the bit measures object
    # presence, not collectability (bit-0 story moons leaked to FREE).
    shine_map = _load_scenario_table("shine_map.json", require_field="progress_bit_flag")
    world_scen = _load_scenario_table("world_scenarios.json")
    rearrival_names = build_rearrival_names(shine_map)          # used for Moon only
    # Moon Kingdom post-win layer (re-arrival + moon-rock) — uncollectable before the
    # mushroom_kingdom goal, so tagged for the runtime filler restriction.
    moon_postwin_names = build_moon_postwin_names(shine_map)
    scenario_data_present = bool(shine_map and world_scen)

    # Moon Cave traversal: the "Underground Caverns" subarea moons + "Up in the
    # Rafters" all require clearing the cave (one of the two MOON_CAVE_TRAVERSAL sets).
    moon_cave_names = set(
        subareas.get("Underground Caverns", {}).get("location_names", [])
    ) | set(MOON_CAVE_EXTRA_LOCATIONS)

    # Cascade dedicated pass: Cascade's clear scenario is its LAST, so it gates on
    # {CascadeDeparture()} / {CascadePeace()} (the leave-deadlock fix), which the flat
    # spreadsheet text cannot express. Built from the romfs bit and kept as a carve-out.
    cascade_anchors, cascade_count = build_cascade_anchors(
        shine_map, world_scen, location_names)

    # ── Spreadsheet-driven scenario gates (the authority for every other kingdom) ──
    # parse_scenario_spreadsheet.py compiled the authored ground-truth xlsx into
    # SCENARIO_GATES. Merge: spreadsheet for normal kingdoms, the dedicated Cascade
    # pass for Cascade, the bit-driven re-arrival fragment for Moon. The Cascade fork
    # painting (order-independent gate) overrides the departure pass for that one warp.
    try:
        spreadsheet_gates = json.loads(SCENARIO_GATES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        spreadsheet_gates = {}
    scenario_gate_by_name: dict[str, str] = {
        k: v for k, v in spreadsheet_gates.items()
        if not (k.startswith("Cascade: ") or k.startswith("Moon: "))
    }
    scenario_gate_by_name.update(cascade_anchors)
    for nm in rearrival_names:
        if nm.startswith("Moon: "):
            scenario_gate_by_name[nm] = REARRIVAL_PEACE_GATES["Moon"]
    _fork = spreadsheet_gates.get("Cascade: Secret Path to Fossil Falls!")
    if _fork:
        scenario_gate_by_name["Cascade: Secret Path to Fossil Falls!"] = _fork

    # D3: per-member scenario gate export for the entrance-shuffle ON path (pooled
    # subareas only). Computed from the SAME scenario map gates_for uses, so it can
    # never drift from the gate baked into locations.json. Written below.
    try:
        exclusions = json.loads(
            ENTRANCE_EXCLUSIONS.read_text(encoding="utf-8"))
        excluded = {n for kexc in exclusions.values() for n in kexc}
    except FileNotFoundError:
        excluded = set()
    subarea_scenario_gates = build_subarea_scenario_gates(
        subareas, excluded, junk_names, location_names, scenario_gate_by_name)

    # location_name -> subarea gate
    loc_subarea_gate: dict[str, str] = {}
    missing_subareas: list[str] = []
    for sub_name, gate in SUBAREA_GATES.items():
        info = subareas.get(sub_name)
        if info is None:
            missing_subareas.append(sub_name)
            continue
        for ln in info.get("location_names", []):
            loc_subarea_gate[ln] = gate

    # Compile per (non-junk) location_name
    compiled: dict[str, str] = {}
    free_moons: list[str] = []
    or_capture_moons: list[str] = []
    skipped_junk = 0
    for csv_name, rec in requirements.items():
        ln = rec.get("location_name")
        if not ln:
            continue
        if ln in junk_names:
            skipped_junk += 1
            continue
        base = compile_moon(rec)
        gated = and_join([base] + gates_for(
            ln, loc_subarea_gate, scenario_gate_by_name,
            moon_rock_names, moon_cave_names))
        compiled[ln] = gated
        if gated == "":
            free_moons.append(ln)
        if len(rec["capture_groups"]) > 1:
            or_capture_moons.append(csv_name)

    # Interior-intrinsic FULL gates: REPLACE the compiled requires for every member
    # of these subareas with the subarea's own {Func} OR |item| entry gate (the move-
    # set is dropped — members are free inside). entrance_shuffle ON applies the same
    # string on the door via entrance_logic.SUBAREA_INTERIOR_FULL_GATES; this keeps the
    # OFF-path locations.json requires identical so the two never drift.
    for sub_name, gate in SUBAREA_INTERIOR_FULL_GATES.items():
        info = subareas.get(sub_name)
        if not info:
            continue
        for ln in info.get("location_names", []):
            if ln in junk_names:
                continue
            compiled[ln] = gate

    # Write requires back into locations.json for compiled moons.
    written = 0
    kingdom_gated = 0
    goal_gated = False
    for loc in locations:
        nm = loc["name"]
        # The game-clear goal isn't a moon (not in moon_requirements), so set its
        # traversal gate directly: one of the two Moon Cave sets must be reachable
        # before the end of the game. This replaces the older {ParabonesSkip()} stub.
        if nm == GOAL_LOCATION:
            loc["requires"] = MOON_CAVE_TRAVERSAL
            goal_gated = True
            continue
        # Moon post-win tag: only adjust when shine_map is present (authoritative);
        # never wipe the flags on a no-data run.
        if shine_map and loc.get("region") == "Moon Kingdom":
            if nm in moon_postwin_names:
                loc["moon_postwin"] = True
            elif "moon_postwin" in loc:
                del loc["moon_postwin"]
        if nm not in compiled:
            continue
        loc["requires"] = compiled[nm]
        written += 1
        if nm.split(": ", 1)[0] in KINGDOM_GATES:
            kingdom_gated += 1
    LOCATIONS.write_text(
        json.dumps(locations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # D3: write the pooled-subarea scenario gate export (consumed by World.py only
    # under entrance_shuffle ON; OFF uses the baked locations.json requires above).
    SUBAREA_SCENARIO_GATES.write_text(
        json.dumps(dict(sorted(subarea_scenario_gates.items())),
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

    _write_review(compiled, free_moons, or_capture_moons, kingdom_gated,
                  loc_subarea_gate, missing_subareas, scenario_data_present,
                  scenario_gate_by_name)

    peace_gated = sum(1 for v in compiled.values() if "Peace()" in v)
    cascade_departure_gated = sum(
        1 for v in compiled.values() if CASCADE_DEPARTURE_GATE in v)
    mid_gated = sum(1 for v in compiled.values() if "canReachLocation(" in v)
    spreadsheet_applied = sum(
        1 for nm in scenario_gate_by_name if nm in compiled)
    cave_gated = sum(1 for nm in moon_cave_names if nm in compiled)
    print(f"Compiled requires for {written} moon locations -> {LOCATIONS.name}")
    print(f"  skipped junk_only:     {skipped_junk}")
    print(f"  free (no requirement): {len(free_moons)}")
    print(f"  kingdom-gated:         {kingdom_gated}")
    print(f"  subarea-gated:         {len(loc_subarea_gate)}")
    print(f"  subarea-scenario-export: {len(subarea_scenario_gates)} pooled-subarea "
          f"moons -> {SUBAREA_SCENARIO_GATES.name} (entrance-shuffle ON re-apply)")
    print(f"  moon-cave-gated:       {cave_gated}/{len(moon_cave_names)} cave moons"
          f"{' + goal' if goal_gated else ' (GOAL LOCATION NOT FOUND)'}")
    if shine_map:
        print(f"  moon-postwin-tagged:   {len(moon_postwin_names)} "
              f"(re-arrival + moon-rock layers; runtime forces filler under "
              f"mushroom_kingdom goal)")
    print(f"  scenario gates:        {len(scenario_gate_by_name)} in table, "
          f"{spreadsheet_applied} applied to compiled moons")
    print(f"    peace-gated (compiled):   {peace_gated}")
    print(f"    canReachLocation-gated:   {mid_gated}")
    print(f"    cascade-departure:        {cascade_departure_gated} "
          f"(Cascade after-ending + rock layers)")
    if not spreadsheet_gates:
        print("    ⚠ scenario_gates.json ABSENT — run parse_scenario_spreadsheet.py "
              "(only Cascade/Moon carve-out gates applied)")
    if missing_subareas:
        print(f"  WARNING missing subarea keys: {missing_subareas}")
    print(f"  review -> {REVIEW_DOC}")


def _write_review(compiled, free_moons, or_capture_moons, kingdom_gated,
                  loc_subarea_gate, missing_subareas,
                  scenario_data_present=False, scenario_gate_by_name=None) -> None:
    scenario_gate_by_name = scenario_gate_by_name or {}
    lines: list[str] = []
    lines.append("# Logic-compile review (auto-generated by compile_moon_logic.py)\n")
    lines.append("Generated from the corrected `SMO Requirements.xlsx`. Devon: spot-check")
    lines.append("the flagged assumptions below; everything follows the locked 2026-06-17")
    lines.append("decisions (height ladder, vault=Cap Bounce, Frog/Chain Chomp free,")
    lines.append("Backflip/Long Jump need Crouch, GPJ needs Ground Pound).\n")

    lines.append("## Summary\n")
    lines.append(f"- Moon locations compiled: **{len(compiled)}**")
    lines.append(f"- Free (no requirement): **{len(free_moons)}**")
    lines.append(f"- Kingdom-gated (Metro/Bowser=Spark pylon, Lake=Zipper/jump): **{kingdom_gated}**")
    lines.append(f"- Subarea-gated moons: **{len(loc_subarea_gate)}**\n")

    # Scenario gating — per-kingdom counts of the spreadsheet-driven gates that
    # actually landed on a compiled moon. IP-safe (counts only, no moon names).
    peace_by_kingdom: dict[str, int] = {}
    canreach_by_kingdom: dict[str, int] = {}
    for nm, req in compiled.items():
        k = nm.split(": ", 1)[0]
        if "Peace()" in req:
            peace_by_kingdom[k] = peace_by_kingdom.get(k, 0) + 1
        if "canReachLocation(" in req:
            canreach_by_kingdom[k] = canreach_by_kingdom.get(k, 0) + 1
    applied = sum(1 for nm in scenario_gate_by_name if nm in compiled)
    lines.append("## Scenario gating (spreadsheet-authoritative)\n")
    lines.append("Per-kingdom scenario gating now comes from the authored "
                 "`Odyssey Scenario_Gating Logic.xlsx` (compiled by "
                 "`parse_scenario_spreadsheet.py` into `data/scenario_gates.json`). The "
                 "romfs `progress_bit_flag` is NO LONGER the per-kingdom scenario "
                 "source — it measures object presence, not collectability, so bit-0 "
                 "story moons leaked to FREE. Carve-outs that remain bit-driven: "
                 "**Cascade** ({CascadeDeparture()}/{CascadePeace()} leave-deadlock "
                 "pass) and **Moon** (postwin filler restriction). Each gate is ANDed "
                 "onto the moon's move-set/capture base.\n")
    lines.append(f"- Scenario gates in table: **{len(scenario_gate_by_name)}**; "
                 f"applied to compiled moons: **{applied}**")
    lines.append(f"- Peace-gated (compiled): **{sum(peace_by_kingdom.values())}**")
    for k in sorted(peace_by_kingdom):
        lines.append(f"  - {k}: {peace_by_kingdom[k]}")
    lines.append(f"- canReachLocation-gated (compiled): "
                 f"**{sum(canreach_by_kingdom.values())}**")
    for k in sorted(canreach_by_kingdom):
        lines.append(f"  - {k}: {canreach_by_kingdom[k]}")
    if not scenario_data_present:
        lines.append("\n⚠ romfs scenario tables ABSENT — Cascade/Moon carve-out gates "
                     "skipped this run (spreadsheet gates still applied).")
    lines.append("")

    lines.append("## Assumptions to verify (\"assume MORE\")\n")
    lines.append("- **Bonk (Roll)** mapped to `Progressive Crouch:2` (needs Roll).")
    lines.append("- **Narrow Valley** entrance \"max-height jump\" read as Triple (`Progressive Jump:2`).")
    lines.append("- **Kingdom gates apply to ALL moons in the kingdom** (overworld + subareas),")
    lines.append("  including subarea moons reached by crossing the gated overworld.")
    lines.append("- **Cross-kingdom subareas** keyed by the moon's physical-kingdom prefix")
    lines.append("  (e.g. a Wooded moon inside Sand's Costume Room gets no Sand gate).\n")

    if missing_subareas:
        lines.append("## ⚠ Subarea gate keys NOT found in subareas.json\n")
        for s in missing_subareas:
            lines.append(f"- {s!r}")
        lines.append("")

    lines.append(f"## Capture OR / AND moons ({len(or_capture_moons)}) — verify the split\n")
    for n in or_capture_moons:
        lines.append(f"- {n}")
    lines.append("")

    lines.append("## Sample compiled output (spot-check)\n")
    sample_keys = [
        "Cap: Frog-Jumping Above the Fog",
        "Cascade: Multi Moon Atop the Falls",
        "Sand: Employees Only",
        "Metro: Powering Up the Power Plant",
        "Seaside: Fly Through the Narrow Valley",
        "Luncheon: Fork Flickin' to the Summit",
    ]
    for k in sample_keys:
        if k in compiled:
            lines.append(f"- `{k}`")
            lines.append(f"  - `{compiled[k] or '(free)'}`")
    lines.append("")

    REVIEW_DOC.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
