"""Generate switch-mod/src/ap/shine_table.h from the apworld + shine_map.

Produces a per-moon table the Switch uses for two things:
  1. Phase 2 pre-marking: walk the table on save load and call
     GameDataFile::setGotShine(unique_id) for every moon NOT in the AP
     pool. Result: only AP-pool moons spawn — the world physically
     contains only your locations.
  2. Future Talkatoo speech enrichment: when Phase 3 lands the actor
     hook, the speech bubble can resolve a moon's display name back to
     its shine_uid so the in-game state can drive picks (e.g. filter
     out moons whose isGotShine() returned true).

Inputs:
  apworld/smo_archipelago/data/locations.json  (AP location names)
  apworld/smo_archipelago/client/data/shine_map.json (extracted SMO data)

The intersection is what "in the AP pool" means at compile time. At
runtime the bridge ships a per-slot TalkatooPool that further narrows
this to the moons the user's slot owns (other slots, or filtered-out
moons, vanish from the AP pool). The table here is the SUPERSET — every
moon in the apworld that has a known shine_uid + stage + obj_id mapping.

Usage:
    python scripts/sync_shine_table.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Mirrors the regex in apworld/smo_archipelago/client/datapackage.py — keep
# in sync. "Cap: Frog-Jumping Above the Fog" -> kingdom="Cap",
# shine_id="Frog-Jumping Above the Fog".
_LOC_PREFIX_RE = re.compile(r"^([A-Za-z' ]+):\s*(.+)$")


def parse_location_name(name: str) -> tuple[str, str] | None:
    """Decompose an AP location name into (kingdom, shine_id) or None."""
    if name.startswith("Capture:"):
        return None
    m = _LOC_PREFIX_RE.match(name)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent
    default_locations = here / "apworld" / "smo_archipelago" / "data" / "locations.json"
    default_shine_map = (
        here / "apworld" / "smo_archipelago" / "client" / "data" / "shine_map.json"
    )
    default_out = here / "switch-mod" / "src" / "ap" / "shine_table.h"

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--locations", type=Path, default=default_locations,
                    help=f"apworld locations.json (default: {default_locations})")
    ap.add_argument("--shine-map", type=Path, default=default_shine_map,
                    help=f"shine_map.json from extract_shine_map.py "
                         f"(default: {default_shine_map})")
    ap.add_argument("--out", type=Path, default=default_out,
                    help=f"output shine_table.h (default: {default_out})")
    args = ap.parse_args(argv)

    if not args.locations.exists():
        print(f"locations.json not found at {args.locations}", file=sys.stderr)
        return 1
    if not args.shine_map.exists():
        print(
            f"shine_map.json not found at {args.shine_map}\n"
            f"  Run scripts/extract_shine_map.py first (Nintendo-IP, "
            f"per-machine; gitignored).",
            file=sys.stderr,
        )
        return 1

    locations = json.loads(args.locations.read_text(encoding="utf-8"))
    shine_map = json.loads(args.shine_map.read_text(encoding="utf-8"))

    # Index shine_map by (kingdom, shine_id) so we can look up by AP name.
    by_name: dict[tuple[str, str], dict] = {}
    for entry in shine_map:
        key = (entry.get("kingdom", ""), entry.get("shine_id", ""))
        if key[0] and key[1]:
            by_name[key] = entry

    rows: list[dict] = []
    missing: list[str] = []
    for loc in locations:
        name = loc.get("name", "")
        parsed = parse_location_name(name)
        if parsed is None:
            continue  # Captures / non-moon locations skip the table.
        kingdom, shine_id = parsed
        entry = by_name.get((kingdom, shine_id))
        if entry is None:
            missing.append(name)
            continue
        rows.append({
            "stage_name": entry["stage_name"],
            "object_id": entry["object_id"],
            "shine_uid": int(entry["shine_uid"]),
            "kingdom": kingdom,
            "shine_id": shine_id,
            # Phase 4: moons flagged in locations.json as scenario-advancing
            # (Multi Moons, boss-fight clears, Seaside seals). The Talkatoo%
            # block in MoonGetHook bypasses these so the player can always
            # progress the scenario. The bridge ALSO uses this to filter the
            # talkatoo_pool — there's no point Talkatoo hinting at a moon the
            # player can grab for free.
            "progression": bool(loc.get("progression", False)),
        })

    # Sort for deterministic output (the table is consumed by enumerate-and-
    # check loops; order only matters for diff hygiene). Sort by stage then
    # obj_id matches how SMO walks mShineHintList.
    rows.sort(key=lambda r: (r["stage_name"], r["object_id"]))

    # shine_id may contain double quotes? Defensive escape just in case
    # (none observed in current data; future apworld renames could).
    def esc(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"')

    body = "\n".join(
        f'    {{ "{esc(r["stage_name"])}", "{esc(r["object_id"])}", '
        f'{r["shine_uid"]}, "{esc(r["kingdom"])}", "{esc(r["shine_id"])}", '
        f'{"true" if r["progression"] else "false"} }},'
        for r in rows
    )
    n_progression = sum(1 for r in rows if r["progression"])
    content = (
        "// AUTO-GENERATED by scripts/sync_shine_table.py — DO NOT EDIT.\n"
        "// Source: apworld/smo_archipelago/data/locations.json (moon locations)\n"
        "//   joined with apworld/smo_archipelago/client/data/shine_map.json\n"
        f"// Count: {len(rows)} moons "
        f"({n_progression} flagged progression; "
        f"apworld locations missing a shine_map entry: {len(missing)})\n"
        "\n"
        "#pragma once\n"
        "\n"
        "#include <array>\n"
        "#include <string_view>\n"
        "\n"
        "namespace smoap::game {\n"
        "\n"
        "// One row per AP moon location. The Phase 2 SaveLoadHook walks this\n"
        "// table and pre-marks every moon NOT in the per-slot AP-pool as\n"
        "// collected so the world physically contains only the player's\n"
        "// locations. The kingdom field matches kKingdoms[] (apworld form,\n"
        "// e.g. \"Bowser's\" not \"Bowser\") — translate before kingdomBitFor()\n"
        "// if needed.\n"
        "//\n"
        "// `progression` flags scenario-advancing moons (Multi Moons, boss\n"
        "// fights, Seaside seals). Phase 4's Talkatoo% block exempts these so\n"
        "// the player can always advance the kingdom's scenario_no — blocking\n"
        "// a Multi Moon would gate every downstream moon that requires\n"
        "// scenario_no >= N. Source of truth: \"progression\": true entries in\n"
        "// locations.json.\n"
        "struct ShineTableRow {\n"
        "    std::string_view stage_name;\n"
        "    std::string_view object_id;\n"
        "    int shine_uid;\n"
        "    std::string_view kingdom;     // AP-form\n"
        "    std::string_view shine_id;    // matches TalkatooPool.moons entries\n"
        "    bool progression;             // scenario-advancing; exempt from Talkatoo% block\n"
        "};\n"
        "\n"
        f"inline constexpr std::array<ShineTableRow, {len(rows)}> kShineTable = {{{{\n"
        f"{body}\n"
        "}};\n"
        "\n"
        "}  // namespace smoap::game\n"
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, encoding="utf-8")

    print(f"Wrote {len(rows)} shine rows to {args.out}")
    if missing:
        print(f"  {len(missing)} apworld locations had no shine_map entry "
              f"(first 5: {missing[:5]})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
