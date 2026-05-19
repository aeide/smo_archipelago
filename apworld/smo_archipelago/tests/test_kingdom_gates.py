"""Consistency check: hooks/World.py KINGDOM_MOON_GATES vs regions.json.

The KINGDOM_MOON_GATES table in hooks/World.py drives the demotion of
surplus kingdom moons from progression to useful. It must mirror every
{KingdomMoons(K, N)} clause in data/regions.json -- if a region threshold
changes without updating the table, the demotion either keeps too many
moons as progression (toggle headroom shrinks) or too few (fill might
fail because the rule isn't satisfiable from the progression-classified
subset).

Pure-data: parses both files as text + JSON, no Archipelago imports, so
it runs in the standard test job (not gated on SMOAP_LIVE_AP).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


def _thresholds_from_regions_json() -> dict[str, int]:
    regions = json.loads(
        (APWORLD_ROOT / "data" / "regions.json").read_text(encoding="utf-8"),
    )
    pat = re.compile(r"\{KingdomMoons\(([^,]+),\s*(\d+)\)\}")
    out: dict[str, int] = {}
    for cfg in regions.values():
        for k, n in pat.findall(cfg.get("requires", "") or ""):
            out[k.strip()] = int(n)
    return out


def _thresholds_from_world_py() -> dict[str, int]:
    src = (APWORLD_ROOT / "hooks" / "World.py").read_text(encoding="utf-8")
    m = re.search(r"KINGDOM_MOON_GATES\s*=\s*\{([^}]*)\}", src, re.DOTALL)
    assert m, "KINGDOM_MOON_GATES dict not found in hooks/World.py"
    return {
        k: int(v)
        for k, v in re.findall(r'"([^"]+)":\s*(\d+)', m.group(1))
    }


def test_kingdom_moon_gates_match_regions_json():
    from_regions = _thresholds_from_regions_json()
    from_world_py = _thresholds_from_world_py()
    assert from_world_py == from_regions, (
        f"KINGDOM_MOON_GATES drift detected.\n"
        f"  regions.json: {from_regions}\n"
        f"  World.py:     {from_world_py}"
    )
