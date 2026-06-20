#!/usr/bin/env python3
"""
add_missing_moon_locations.py

Adds the SMO moons that exist in data/moon_requirements.json but have no AP
location yet (the ~213 the curated upstream pool omitted) as new AP checks in
data/locations.json, tagged into include_* toggle cluster categories so players
can opt out.

IP posture: reads ONLY committed data files (moon_requirements.json, subareas.json,
locations.json, items.json). The moon names already live in the committed
moon_requirements.json, so no new Nintendo strings are introduced — this only
promotes already-committed names into locations.json.

What it does (with --apply; default is a dry-run report):
  1. Find every moon_requirements entry whose `location_name` is null.
  2. Derive its AP name `<ShortKingdom>: <moon suffix>` using the same prefix /
     subarea->kingdom maps the importer uses.
  3. Classify it into a cluster category (Cup / Peach / Hint Art / Hat-and-Seek /
     Taking Notes / Caught Hopping / Timer Challenge / Extra) from its name.
  4. Back-fill `location_name` into moon_requirements.json (so compile_moon_logic
     fills its `requires`).
  5. Append a locations.json entry: name, region, category=[<Kingdom> Kingdom,
     <cluster>] (+ "post-metro" where applicable), progression mirrored from an
     existing sibling moon in the same region.
  6. Grow each kingdom's "<Kingdom> Kingdom Power Moon" item count by the number
     of moons added to that kingdom.

After --apply, on the machine WITH the gitignored romfs data, run:
    python scripts/compile_moon_logic.py     # fills requires + peace/scenario gates
    python scripts/sync_shine_table.py        # verifies the shine_map join (Switch award)
    python scripts/install_apworld.py
    python vendor/Archipelago/Generate.py     # fill-test

Usage:
    python scripts/add_missing_moon_locations.py            # dry-run report
    python scripts/add_missing_moon_locations.py --apply    # write the changes
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "apworld" / "smo_archipelago" / "data"

# Long sheet kingdom prefix -> abbreviated locations.json prefix (mirrors
# import_moon_requirements.KINGDOM_PREFIX_MAP).
KINGDOM_PREFIX_MAP = {
    "Cap Kingdom": "Cap", "Cascade Kingdom": "Cascade", "Sand Kingdom": "Sand",
    "Wooded Kingdom": "Wooded", "Lake Kingdom": "Lake", "Cloud Kingdom": "Cloud",
    "Lost Kingdom": "Lost", "Metro Kingdom": "Metro", "Snow Kingdom": "Snow",
    "Seaside Kingdom": "Seaside", "Luncheon Kingdom": "Luncheon",
    "Ruined Kingdom": "Ruined", "Bowser's Kingdom": "Bowser's",
    "Moon Kingdom": "Moon", "Mushroom Kingdom": "Mushroom",
    "Dark Side": "Dark Side", "Darker Side": "Darker Side",
}
SHORT_TO_LONG = {v: k for k, v in KINGDOM_PREFIX_MAP.items()}

# Kingdoms whose moons carry the "post-metro" goal tag (mirrors items.json).
POST_METRO_LONG = {
    "Snow Kingdom", "Seaside Kingdom", "Luncheon Kingdom", "Ruined Kingdom",
    "Bowser's Kingdom", "Moon Kingdom", "Mushroom Kingdom",
}


def classify(suffix: str) -> str:
    """Cluster category for a moon, from its name suffix."""
    s = suffix
    if "Timer Challenge" in s:
        return "Timer Challenge"
    if s.startswith("Peach in the "):
        return "Peach"
    if re.search(r"Found with .* Art$", s):
        return "Hint Art"          # reuse the existing toggle
    if "Hat-and-Seek" in s:
        return "Hat-and-Seek"
    if s.startswith("Taking Notes"):
        return "Taking Notes"
    if "Caught Hopping" in s:
        return "Caught Hopping"
    if re.search(r"(Regular Cup|Master Cup)$", s):
        return "Cup"
    if "Tourist" in s:
        return "Tourist"           # reuse the existing toggle
    return "Extra"


def main() -> None:
    apply = "--apply" in sys.argv

    req = json.loads((DATA / "moon_requirements.json").read_text(encoding="utf-8"))
    subareas = json.loads((DATA / "subareas.json").read_text(encoding="utf-8"))
    locs = json.loads((DATA / "locations.json").read_text(encoding="utf-8"))
    items = json.loads((DATA / "items.json").read_text(encoding="utf-8"))

    existing_names = {l["name"] for l in locs}

    missing = [(csv, rec) for csv, rec in req.items() if not rec.get("location_name")]

    new_entries: list[dict] = []
    backfill: list[tuple[str, str]] = []   # (csv_name, derived ap name)
    per_region = Counter()
    per_cluster = Counter()
    skipped: list[str] = []
    extras: list[str] = []

    for csv_name, rec in missing:
        parts = csv_name.split(": ", 1)
        if len(parts) != 2:
            skipped.append(f"{csv_name}  (no ': ' split)")
            continue
        prefix, suffix = parts[0].strip(), parts[1].strip()

        if prefix in KINGDOM_PREFIX_MAP:
            long_kingdom = prefix
        else:
            info = subareas.get(prefix, {})
            long_kingdom = info.get("kingdom")
            if not long_kingdom:
                skipped.append(f"{csv_name}  (subarea {prefix!r} has no kingdom)")
                continue

        short = KINGDOM_PREFIX_MAP[long_kingdom]
        ap_name = f"{short}: {suffix}"
        if ap_name in existing_names:
            # Already present under this name (importer just didn't link it) —
            # back-fill the link, don't add a duplicate location.
            backfill.append((csv_name, ap_name))
            continue

        cluster = classify(suffix)
        per_cluster[cluster] += 1
        per_region[long_kingdom] += 1
        if cluster == "Extra":
            extras.append(ap_name)

        category = [long_kingdom, cluster]
        if long_kingdom in POST_METRO_LONG:
            category.append("post-metro")

        # NOTE: no `progression` flag. The location-level `progression: true`
        # flag is a hand-audited set of 38 scenario-ADVANCING moons (Talkatoo%
        # exemptions, see tests/test_progression_moons.py) — NOT a "this kingdom
        # is a progression kingdom" marker. None of these promoted moons advance
        # scenario_no, so none get the flag. (Item-pool progression is governed
        # by the kingdom Power Moon item classification in items.json, unchanged.)
        entry = {
            "name": ap_name,
            "category": category,
            "region": long_kingdom,
            "requires": "",            # filled by compile_moon_logic.py
        }
        new_entries.append(entry)
        backfill.append((csv_name, ap_name))
        existing_names.add(ap_name)

    # ---- report ----
    print(f"missing moons (no location_name): {len(missing)}")
    print(f"  -> new locations to add:        {len(new_entries)}")
    print(f"  -> already present, link only:  {len(backfill) - len(new_entries)}")
    print(f"  -> skipped:                     {len(skipped)}")
    print("\nper kingdom (new locations):")
    for k in sorted(per_region):
        print(f"   {per_region[k]:3d}  {k}  (+{per_region[k]} {KINGDOM_PREFIX_MAP[k]} Kingdom Power Moon)")
    print("\nper cluster category:")
    for c, n in per_cluster.most_common():
        print(f"   {n:3d}  {c}")
    if extras:
        print(f"\n'Extra' (no natural cluster) — {len(extras)}:")
        for n in extras:
            print("   ", n)
    if skipped:
        print(f"\nSKIPPED ({len(skipped)}):")
        for s in skipped:
            print("   ", s)

    if not apply:
        print("\n(dry-run — re-run with --apply to write changes)")
        return

    # ---- apply ----
    # 1. back-fill location_name in moon_requirements.json
    for csv_name, ap_name in backfill:
        req[csv_name]["location_name"] = ap_name
    (DATA / "moon_requirements.json").write_text(
        json.dumps(req, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. append new entries to locations.json
    locs.extend(new_entries)
    (DATA / "locations.json").write_text(
        json.dumps(locs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 3. grow kingdom Power Moon item counts
    grow = {f"{KINGDOM_PREFIX_MAP[k]} Kingdom Power Moon": per_region[k] for k in per_region}
    by_name = {it["name"]: it for it in items}
    for name, n in grow.items():
        if name in by_name:
            by_name[name]["count"] = by_name[name].get("count", 0) + n
        else:
            print(f"  WARNING: item {name!r} not found — {n} moons have no item to grow")
    (DATA / "items.json").write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nAPPLIED: +{len(new_entries)} locations, "
          f"backfilled {len(backfill)} location_names, grew {len(grow)} item counts.")
    print("Next (on the machine with romfs data): compile_moon_logic.py -> "
          "sync_shine_table.py -> install_apworld.py -> Generate.py")


if __name__ == "__main__":
    main()
