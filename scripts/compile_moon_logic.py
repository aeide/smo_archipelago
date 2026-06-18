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


def gates_for(location_name: str, loc_subarea_gate: dict[str, str]) -> list[str]:
    out: list[str] = []
    prefix = location_name.split(": ", 1)[0]
    if prefix in KINGDOM_GATES:
        out.append(KINGDOM_GATES[prefix])
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
        gated = and_join([base] + gates_for(ln, loc_subarea_gate))
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
                  loc_subarea_gate, missing_subareas)

    print(f"Compiled requires for {written} moon locations -> {LOCATIONS.name}")
    print(f"  skipped junk_only:     {skipped_junk}")
    print(f"  free (no requirement): {len(free_moons)}")
    print(f"  kingdom-gated:         {kingdom_gated}")
    print(f"  subarea-gated:         {len(loc_subarea_gate)}")
    if missing_subareas:
        print(f"  WARNING missing subarea keys: {missing_subareas}")
    print(f"  review -> {REVIEW_DOC}")


def _write_review(compiled, free_moons, or_capture_moons, kingdom_gated,
                  loc_subarea_gate, missing_subareas) -> None:
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
