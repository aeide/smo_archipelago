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
  * Vault == Cap Bounce, so the 496 tier = Backflip OR Side Flip OR Cap Bounce.
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
REVIEW_DOC = REPO_ROOT / "docs" / "logic-compile-review.md"

# ─────────────────────────────────────────────────────────────────────────────
# Boolean-expression helpers — always fully parenthesised for the manual parser.
# ─────────────────────────────────────────────────────────────────────────────

def and_join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
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
FREE_CAPTURES = frozenset({"Frog", "Chain Chomp"})

JUMP_FRAG: dict[str, str] = {
    "PJ1":       "|Progressive Jump:1|",                                  # Double
    "PJ2":       "|Progressive Jump:2|",                                  # Triple
    "CAP_BOUNCE": "|Cap Bounce|",                                         # = vault
    "BACKFLIP":  "(|Backflip| and |Progressive Crouch:1|)",
    "SIDE_FLIP": "|Side Flip|",
    "GPJ":       "(|Ground Pound Jump| and |Progressive Ground Pound:1|)",
    "LONG_JUMP": "(|Long Jump| and |Progressive Crouch:1|)",
}

# Min-height enum -> the jump-item keys that reach >= that height.
# Reach: Double 312 < CapReturn/Vault 400-496 == Backflip/SideFlip/CapBounce 496
#        < GPJ 514 < Triple 550.  (Long Jump is a separate horizontal axis.)
HEIGHT_SATISFIERS: dict[str, list[str]] = {
    "double":     ["PJ1", "CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
    "cap_return": ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
    "backflip":   ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
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
    "wall_slide":   "|Wall Slide|",
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
                      JUMP_FRAG["PJ2"], JUMP_FRAG["GPJ"]])

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

# ─────────────────────────────────────────────────────────────────────────────
# Scenario reachability (COARSE tier) — see docs/scenario-reachability-design.md.
#
# Generalizes the rock-only {<Kingdom>Peace()} rule to ALL post-peace moons.
# A moon is post_peace iff:  is_moon_rock  OR  min_scenario >= peace_bit
#   min_scenario = lowest set bit of progress_bit_flag (earliest scenario the
#                  moon is ever present in).
#   peace_bit    = clear_main_scenario - 1   (from world_scenarios.json).
# post_peace moons AND in {<Kingdom>Peace()} (folded with MOON_ROCK_PEACE_GATES so
# a rock moon is gated once, not twice). Cap/Cloud/Lost/Moon have no *Peace()
# predicate, so post_peace moons there receive NO new gate (their leave-to-access
# gating is a deferred mid_story concern).
#
# mid_story (a moon needing partial story progress but not peace) is COLLAPSED into
# the free tier for this pass — anchor gating is the documented follow-up.
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
    moon_rock_names: frozenset[str],
    shine_map: list | None,
    world_scen: dict | None,
) -> set[str]:
    """Union of (a) existing Moon Rock category locations and (b) non-rock moons
    classified post_peace by their progress_bit_flag. Keyed by AP location name
    (`<kingdom>: <shine_id>`). When scenario data is absent, falls back to (a)."""
    names: set[str] = set(moon_rock_names)
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
        if e.get("is_moon_rock"):
            continue                        # already covered by moon_rock_names
        ws = world_scen.get(kingdom)
        if ws is None:
            continue
        if classify_scenario_post_peace(
            e["progress_bit_flag"], ws, first_playable.get(kingdom, 0), kingdom
        ):
            names.add(f"{kingdom}: {e['shine_id']}")
    return names


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


def gates_for(location_name: str, loc_subarea_gate: dict[str, str],
              post_peace_names: set[str] | frozenset[str]) -> list[str]:
    out: list[str] = []
    prefix = location_name.split(": ", 1)[0]
    if prefix in KINGDOM_GATES:
        out.append(KINGDOM_GATES[prefix])
    # post_peace_names folds rock moons (locations.json category) with non-rock
    # post-peace moons (scenario classification) so the {<Kingdom>Peace()} gate is
    # appended exactly once. Cap/Cloud/Lost/Moon have no predicate -> no gate.
    if location_name in post_peace_names:
        peace = MOON_ROCK_PEACE_GATES.get(prefix, "")
        if peace:
            out.append(peace)
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

    moon_rock_names = frozenset(
        l["name"] for l in locations if "Moon Rock" in l.get("category", [])
    )

    # Scenario reachability (coarse): fold rock moons with non-rock post-peace
    # moons into a single name set that gets {<Kingdom>Peace()}. Build-time read of
    # the gitignored scenario tables; degrades to rock-only when absent.
    shine_map = _load_scenario_table("shine_map.json", require_field="progress_bit_flag")
    world_scen = _load_scenario_table("world_scenarios.json")
    post_peace_names = build_post_peace_names(moon_rock_names, shine_map, world_scen)
    scenario_data_present = bool(shine_map and world_scen)
    new_post_peace = len(post_peace_names) - len(moon_rock_names)

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
        gated = and_join([base] + gates_for(ln, loc_subarea_gate, post_peace_names))
        compiled[ln] = gated
        if gated == "":
            free_moons.append(ln)
        if len(rec["capture_groups"]) > 1:
            or_capture_moons.append(csv_name)

    # Write requires back into locations.json for compiled moons.
    written = 0
    kingdom_gated = 0
    for loc in locations:
        nm = loc["name"]
        if nm not in compiled:
            continue
        loc["requires"] = compiled[nm]
        written += 1
        if nm.split(": ", 1)[0] in KINGDOM_GATES:
            kingdom_gated += 1
    LOCATIONS.write_text(
        json.dumps(locations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    _write_review(compiled, free_moons, or_capture_moons, kingdom_gated,
                  loc_subarea_gate, missing_subareas, scenario_data_present)

    peace_gated = sum(1 for v in compiled.values() if "Peace()" in v)
    print(f"Compiled requires for {written} moon locations -> {LOCATIONS.name}")
    print(f"  skipped junk_only:     {skipped_junk}")
    print(f"  free (no requirement): {len(free_moons)}")
    print(f"  kingdom-gated:         {kingdom_gated}")
    print(f"  subarea-gated:         {len(loc_subarea_gate)}")
    if scenario_data_present:
        print(f"  scenario data:         loaded ({len(shine_map)} moons, "
              f"{len(world_scen)} kingdoms)")
        print(f"  peace-gated (compiled): {peace_gated}  "
              f"(+{new_post_peace} non-rock post-peace names folded in)")
    else:
        print("  scenario data:         ABSENT — peace gating is rock-only "
              "(set up bridge/%APPDATA% shine_map+world_scenarios to enable)")
    if missing_subareas:
        print(f"  WARNING missing subarea keys: {missing_subareas}")
    print(f"  review -> {REVIEW_DOC}")


def _write_review(compiled, free_moons, or_capture_moons, kingdom_gated,
                  loc_subarea_gate, missing_subareas,
                  scenario_data_present=False) -> None:
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

    # Scenario reachability (coarse tier) — per-kingdom peace-gate counts, IP-safe
    # (counts only, no moon names). Lets Devon eyeball that post_peace gating
    # landed on the expected predicate kingdoms. See
    # docs/scenario-reachability-design.md.
    peace_by_kingdom: dict[str, int] = {}
    for nm, req in compiled.items():
        if "Peace()" in req:
            k = nm.split(": ", 1)[0]
            peace_by_kingdom[k] = peace_by_kingdom.get(k, 0) + 1
    total_peace = sum(peace_by_kingdom.values())
    lines.append("## Scenario reachability (coarse post_peace gating)\n")
    if scenario_data_present:
        lines.append("Each `post_peace` moon (rock, OR earliest scenario >= the "
                     "kingdom's peace scenario) ANDs in `{<Kingdom>Peace()}`. "
                     "`mid_story` is collapsed to free this pass (anchor gating is "
                     "the documented follow-up). Cap/Cloud/Lost/Moon and Cascade "
                     "non-rock moons get NO new gate by design.\n")
        lines.append(f"- Total peace-gated moons (rock + scenario): **{total_peace}**")
        for k in sorted(peace_by_kingdom):
            lines.append(f"  - {k}: {peace_by_kingdom[k]}")
        lines.append("")
    else:
        lines.append("Scenario tables (`shine_map.json` / `world_scenarios.json`) "
                     "were ABSENT — peace gating degraded to rock-only. Set up the "
                     "bridge / %APPDATA% data dir and re-run to enable.\n")

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
