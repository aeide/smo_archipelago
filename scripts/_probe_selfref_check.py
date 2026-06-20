#!/usr/bin/env python3
"""Scratch: verify the compiled locations.json has no self-referencing canReach gate,
and eyeball the mid_story anchor wiring. IP-safe (echoes existing location names only)."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
locs = json.loads((REPO / "apworld/smo_archipelago/data/locations.json").read_text(encoding="utf-8"))
by = {l["name"]: l.get("requires", "") for l in locs}

selfref = [n for n, r in by.items() if f"canReachLocation({n})" in (r or "")]
print("self-references (must be []):", selfref)

for n in ["Metro: A Traditional Festival!", "Sand: The Hole in the Desert",
          "Sand: Showdown on the Inverted Pyramid", "Luncheon: Cookatiel Showdown!",
          "Wooded: Defend the Secret Flower Field!", "Metro: New Donk City's Pest Problem"]:
    print(f"\n{n!r}\n   -> {by.get(n)!r}")
