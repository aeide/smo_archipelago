#!/usr/bin/env python3
"""
import_moon_requirements.py

Parse the 'Public SMO Randomizer Moon Ability Requirements - Moons.csv'
into two committed JSON files:

  apworld/smo_archipelago/data/moon_requirements.json
      Keyed by CSV name.  Each entry has a ``location_name`` field giving
      the matched locations.json canonical name (null when unmatched).

  apworld/smo_archipelago/data/subareas.json
      Keyed by subarea prefix (e.g. "Frog Pond").  Each entry records the
      parent kingdom and the CSV + location names of its moons.

Usage (from repo root):
    python scripts/import_moon_requirements.py
    python scripts/import_moon_requirements.py path/to/custom.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "apworld" / "smo_archipelago" / "data"
DEFAULT_CSV = REPO_ROOT / "Public SMO Randomizer Moon Ability Requirements - Moons.csv"
OUT_REQUIREMENTS = DATA_DIR / "moon_requirements.json"
OUT_SUBAREAS = DATA_DIR / "subareas.json"

# ─────────────────────────────────────────────────────────────────────────────
# Kingdom prefix normalisation
# Maps the long CSV kingdom prefix to the abbreviated locations.json prefix.
# These are the ONLY prefixes treated as "main kingdom" entries; everything
# else is a subarea.
# ─────────────────────────────────────────────────────────────────────────────
KINGDOM_PREFIX_MAP: dict[str, str] = {
    "Cap Kingdom":      "Cap",
    "Cascade Kingdom":  "Cascade",
    "Sand Kingdom":     "Sand",
    "Wooded Kingdom":   "Wooded",
    "Lake Kingdom":     "Lake",
    "Cloud Kingdom":    "Cloud",
    "Lost Kingdom":     "Lost",
    "Metro Kingdom":    "Metro",
    "Snow Kingdom":     "Snow",
    "Seaside Kingdom":  "Seaside",
    "Luncheon Kingdom": "Luncheon",
    "Ruined Kingdom":   "Ruined",
    "Bowser's Kingdom": "Bowser's",
    "Moon Kingdom":     "Moon",
    "Mushroom Kingdom": "Mushroom",
    "Dark Side":        "Dark Side",
    "Darker Side":      "Darker Side",
}

MAIN_KINGDOM_PREFIXES: frozenset[str] = frozenset(KINGDOM_PREFIX_MAP)

# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary maps
# ─────────────────────────────────────────────────────────────────────────────

# Minimum jump height  (row 0, cols E–I)
JUMP_HEIGHT_MAP: dict[str, str] = {
    "No Jump Needed":                "none",
    "Single Jump (258)":             "single",
    "Double Jump (312)":             "double",
    "Cap Return Jump (400)":         "cap_return",
    "Backflip/Vault/Side Flip (496)": "backflip",
    "Ground Pound Jump (514)":       "gpj",
    "Triple Jump (550)":             "triple",
    "Long Jump":                     "long_jump",
}

# Cap throws (row 1, cols E–I — comma-separated within each cell)
CAP_THROW_MAP: dict[str, str] = {
    "No Cap Throw Needed": "none",
    "Neutral Throw":       "neutral",
    "Up Throw":            "up",
    "Down Throw":          "down",
    "Spin Throw":          "spin",
}

# Other requirements (row 2, cols E–I — comma-separated within each cell).
# None → empty list sentinel; "Capture" → requires one of col-C captures.
OTHER_REQUIRED_MAP: dict[str, str | None] = {
    "None":                  None,
    "Capture":               "capture",
    "Dive":                  "dive",
    "Ground Pound":          "ground_pound",
    "Roll":                  "roll",
    "Roll Boost":            "roll_boost",
    "Crouch":                "crouch",
    "Wall Jump":             "wall_jump",
    "Ledge Grab":            "ledge_grab",
    "Climb":                 "climb",
    "Homing Cap":            "homing_cap",
    "Bonk (Roll)":           "bonk_roll",
    "Damage Boost":          "damage_boost",
    "2D Jump (any jump)":    "2d_jump",
    "2d jump (any jump)":    "2d_jump",   # case variant in sheet
    "Scooter":               "scooter",
    "Jaxi":                  "jaxi",
    "Rainbow Spin":          "rainbow_spin",
    "Outfit":                "outfit",
    "Single Jump (258)":     "single",    # appears in Other Required too
    "Other Kingdom Trigger": "other_kingdom_trigger",
}

# Sentinel value for col C when the stage uses its default capture
LOCKED_SENTINEL = "Locked behind Default Capture"

# One-off CSV name → locations.json canonical name overrides.
# Add an entry here whenever reconciliation finds a naming mismatch that can't
# be resolved by the standard prefix-stripping logic.
CSV_NAME_OVERRIDES: dict[str, str] = {
    # CSV uses a sub-qualifier "Upper Interior:" not present in locations.json
    "Inverted Pyramid: Upper Interior: Hidden Room in the Inverted Pyramid":
        "Sand: Hidden Room in the Inverted Pyramid",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_csv_cell(cell: str) -> list[str]:
    """Split a comma-separated cell, strip whitespace, drop empty strings."""
    return [v.strip() for v in cell.split(",") if v.strip()]


def _norm_jump(raw: str) -> str | None:
    """Return normalised jump-height enum or raise on unknown value."""
    v = raw.strip()
    if not v:
        return None
    if v not in JUMP_HEIGHT_MAP:
        raise ValueError(f"Unknown jump height: {v!r}")
    return JUMP_HEIGHT_MAP[v]


def _norm_cap_throws(raw: str) -> list[str]:
    """Return list of normalised cap-throw enums."""
    result: list[str] = []
    for tok in _split_csv_cell(raw):
        if tok not in CAP_THROW_MAP:
            raise ValueError(f"Unknown cap throw: {tok!r}")
        result.append(CAP_THROW_MAP[tok])
    return result


def _norm_other_required(raw: str) -> list[str]:
    """Return list of normalised other-required enums (empty list for 'None')."""
    result: list[str] = []
    for tok in _split_csv_cell(raw):
        key = tok.lower()
        # Case-insensitive lookup fallback
        matched = None
        for k, v in OTHER_REQUIRED_MAP.items():
            if k.lower() == key:
                matched = v
                break
        if matched is None and key not in {k.lower() for k in OTHER_REQUIRED_MAP}:
            raise ValueError(f"Unknown other-required term: {tok!r}")
        if matched is not None:
            result.append(matched)
        # matched == None means "None" → skip (empty list)
    return result


def _parse_captures(raw: str) -> tuple[list[str], bool]:
    """
    Return (capture_list, locked_default_capture).
    locked_default_capture=True when the stage uses its own default capture.
    """
    v = raw.strip()
    if v == LOCKED_SENTINEL:
        return [], True
    return _split_csv_cell(v), False


# ─────────────────────────────────────────────────────────────────────────────
# Locations.json reverse lookup
# ─────────────────────────────────────────────────────────────────────────────

def _build_location_lookup(data_dir: Path) -> dict[str, str]:
    """
    Return short_name → canonical_location_name for all non-Capture locations.
    short_name = everything after the first ': '.
    """
    locs: list[dict] = json.loads((data_dir / "locations.json").read_text(encoding="utf-8"))
    lookup: dict[str, str] = {}
    for loc in locs:
        name: str = loc["name"]
        if name.startswith("Capture:"):
            continue
        if ": " in name:
            short = name.split(": ", 1)[1]
            lookup[short] = name
    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# Name reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def _reconcile(csv_name: str, short_lookup: dict[str, str]) -> str | None:
    """
    Map a CSV moon name to its locations.json canonical name, or None.

    Strategy:
      0. Check CSV_NAME_OVERRIDES first.
      1. If the CSV prefix is a main kingdom, strip the prefix and search
         short_lookup by the moon's short name.
      2. Otherwise (subarea prefix), same short-name search.
    """
    if csv_name in CSV_NAME_OVERRIDES:
        return CSV_NAME_OVERRIDES[csv_name]

    parts = csv_name.split(": ", 1)
    if len(parts) != 2:
        return None
    _prefix, short = parts[0].strip(), parts[1].strip()
    return short_lookup.get(short)


# ─────────────────────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_csv(csv_path: Path) -> tuple[list[dict], list[str]]:
    """
    Parse all 3-row moon blocks from the CSV.

    Returns:
      (moon_records, parse_errors)

    Each moon_record is a dict:
      {
        "csv_name": str,
        "captures": [str, ...],
        "locked_default_capture": bool,
        "methods": {
          "1": {"jump_height": str|None, "cap_throws": [str,...], "other_required": [str,...]}
                | None,   # None = method not defined for this moon
          "2": ..., "3": ..., "4": ..., "5": ...
        }
      }
    """
    rows: list[list[str]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # Row 0 is header, row 1 is column labels — skip both.
    # Moon blocks start at row 2.  Each block is exactly 3 rows
    # (row A: name/jump, row B: cap throws, row C: other required).
    # The single exception (Darker Side last moon) has trailing empty rows.
    moon_starts: list[int] = [
        i for i in range(2, len(rows))
        if rows[i][1].strip() and rows[i][3].strip() == "Minimum Jump Height:"
    ]

    records: list[dict] = []
    errors: list[str] = []

    for idx in moon_starts:
        if idx + 2 >= len(rows):
            errors.append(f"Row {idx}: truncated block for {rows[idx][1]!r}")
            continue

        row_jump  = rows[idx]      # row A
        row_cap   = rows[idx + 1]  # row B
        row_other = rows[idx + 2]  # row C

        csv_name = row_jump[1].strip()
        raw_captures = row_jump[2].strip()

        try:
            captures, locked = _parse_captures(raw_captures)
        except Exception as e:
            errors.append(f"{csv_name}: captures — {e}")
            continue

        methods: dict[str, dict | None] = {}
        for m_idx, m_key in enumerate(("1", "2", "3", "4", "5")):
            col = 4 + m_idx  # cols E–I are indices 4–8
            jraw  = row_jump[col].strip()  if col < len(row_jump)  else ""
            craw  = row_cap[col].strip()   if col < len(row_cap)   else ""
            oraw  = row_other[col].strip() if col < len(row_other) else ""

            if not jraw and not craw and not oraw:
                methods[m_key] = None
                continue

            try:
                jump    = _norm_jump(jraw)
                cap_thr = _norm_cap_throws(craw)
                other   = _norm_other_required(oraw)
            except ValueError as e:
                errors.append(f"{csv_name} method {m_key}: {e}")
                jump, cap_thr, other = None, [], []

            methods[m_key] = {
                "jump_height":    jump,
                "cap_throws":     cap_thr,
                "other_required": other,
            }

        records.append({
            "csv_name":                csv_name,
            "captures":                captures,
            "locked_default_capture":  locked,
            "methods":                 methods,
        })

    return records, errors


# ─────────────────────────────────────────────────────────────────────────────
# Subarea builder
# ─────────────────────────────────────────────────────────────────────────────

def build_subareas(
    records: list[dict],
    short_lookup: dict[str, str],
    csv_path: Path,
) -> dict[str, dict]:
    """
    Infer subarea → kingdom mapping by scanning moon names in CSV order.
    When a main-kingdom prefix is seen, that becomes the current kingdom.
    Subarea prefixes encountered while a kingdom is current are assigned to it.

    Returns dict keyed by subarea name.
    """
    # Re-scan CSV order to assign subareas to kingdoms
    rows: list[list[str]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    moon_starts = [
        i for i in range(2, len(rows))
        if rows[i][1].strip() and rows[i][3].strip() == "Minimum Jump Height:"
    ]

    current_kingdom: str | None = None
    # subarea_name → kingdom
    subarea_kingdom: dict[str, str] = {}

    for idx in moon_starts:
        csv_name = rows[idx][1].strip()
        parts = csv_name.split(": ", 1)
        if len(parts) != 2:
            continue
        prefix = parts[0].strip()
        if prefix in MAIN_KINGDOM_PREFIXES:
            current_kingdom = prefix
        else:
            if current_kingdom and prefix not in subarea_kingdom:
                subarea_kingdom[prefix] = current_kingdom

    # Build subarea entries
    subareas: dict[str, dict] = {}
    for rec in records:
        csv_name = rec["csv_name"]
        parts = csv_name.split(": ", 1)
        if len(parts) != 2:
            continue
        prefix, short = parts[0].strip(), parts[1].strip()
        if prefix in MAIN_KINGDOM_PREFIXES:
            continue  # not a subarea

        if prefix not in subareas:
            subareas[prefix] = {
                "kingdom":        subarea_kingdom.get(prefix),
                "csv_names":      [],
                "location_names": [],
            }
        subareas[prefix]["csv_names"].append(csv_name)
        loc_name = _reconcile(csv_name, short_lookup)
        if loc_name:
            subareas[prefix]["location_names"].append(loc_name)

    return subareas


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(
    records: list[dict],
    short_lookup: dict[str, str],
    parse_errors: list[str],
) -> None:
    matched = unmatched = 0
    unmatched_names: list[str] = []

    for rec in records:
        csv_name = rec["csv_name"]
        parts = csv_name.split(": ", 1)
        if len(parts) == 2:
            prefix, short = parts[0].strip(), parts[1].strip()
        else:
            prefix, short = "", csv_name

        loc = _reconcile(csv_name, short_lookup)
        if loc:
            matched += 1
        else:
            unmatched += 1
            unmatched_names.append(csv_name)

    print(f"\n{'='*60}")
    print(f"CSV moons parsed : {len(records)}")
    print(f"Matched to locations.json : {matched}")
    print(f"Unmatched (not yet in locations.json) : {unmatched}")

    if unmatched_names:
        print(f"\nUnmatched CSV moon names ({unmatched}):")
        for n in unmatched_names:
            print(f"  {n}")

    if parse_errors:
        print(f"\nParse errors ({len(parse_errors)}):")
        for e in parse_errors:
            print(f"  {e}")

    print("="*60)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not csv_path.exists():
        sys.exit(f"CSV not found: {csv_path}")

    print(f"Parsing: {csv_path}")
    records, parse_errors = parse_csv(csv_path)
    print(f"  {len(records)} moon blocks parsed, {len(parse_errors)} errors")

    short_lookup = _build_location_lookup(DATA_DIR)
    print(f"  {len(short_lookup)} matchable entries in locations.json")

    # Attach location_name to each record
    for rec in records:
        rec["location_name"] = _reconcile(rec["csv_name"], short_lookup)

    # Build moon_requirements dict keyed by csv_name
    requirements: dict[str, dict] = {}
    for rec in records:
        key = rec.pop("csv_name")
        requirements[key] = rec

    # Build subareas
    # Restore csv_name for subarea builder
    for key, val in requirements.items():
        val["csv_name"] = key
    subareas = build_subareas(
        [{"csv_name": k, **v} for k, v in requirements.items()],
        short_lookup,
        csv_path,
    )
    # Remove the temporarily re-added field
    for val in requirements.values():
        val.pop("csv_name", None)

    # Write outputs
    OUT_REQUIREMENTS.write_text(
        json.dumps(requirements, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  → {OUT_REQUIREMENTS}")

    OUT_SUBAREAS.write_text(
        json.dumps(subareas, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  → {OUT_SUBAREAS}")

    _print_report(
        [{"csv_name": k, **v} for k, v in requirements.items()],
        short_lookup,
        parse_errors,
    )


if __name__ == "__main__":
    main()
ent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  → {OUT_SUBAREAS}")

    _print_report(
        [{"csv_name": k, **v} for k, v in requirements.items()],
        short_lookup,
        parse_errors,
    )


if __name__ == "__main__":
    main()
