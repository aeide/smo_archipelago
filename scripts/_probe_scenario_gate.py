#!/usr/bin/env python3
"""Scratch probe: inspect locations.json baseline + dry-run scenario classification.

IP-safe: prints counts and kingdom-level stats only; no English moon-name lists.
Re-runnable. Not committed-data-producing.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOC = REPO / "apworld" / "smo_archipelago" / "data" / "locations.json"


def data_dirs():
    dirs = [REPO / "bridge" / "smo_ap_bridge" / "data"]
    ad = os.environ.get("APPDATA")
    if ad:
        dirs.append(Path(ad) / "SMOArchipelago" / "data")
    dirs.append(REPO / "apworld" / "smo_archipelago" / "client" / "data")
    return dirs


def find(name, need_field=None):
    for d in data_dirs():
        p = d / name
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if need_field:
                seq = data if isinstance(data, list) else []
                if seq and need_field not in seq[0]:
                    continue
            return p, data
    return None, None


def lsb(flag: int) -> int:
    return (flag & -flag).bit_length() - 1


def main():
    locs = json.loads(LOC.read_text(encoding="utf-8"))
    has_req = [l for l in locs if "requires" in l]
    free = [l for l in has_req if l["requires"] == ""]
    print(f"total locations: {len(locs)}")
    print(f"junk_only: {sum(1 for l in locs if l.get('junk_only'))}")
    print(f"Moon Rock category: {sum(1 for l in locs if 'Moon Rock' in l.get('category', []))}")
    print(f"with requires key: {len(has_req)}")
    print(f"free (requires==''): {len(free)}")
    print(f"requires mentioning Peace(): {sum(1 for l in has_req if 'Peace()' in (l['requires'] or ''))}")

    smp, shine = find("shine_map.json", need_field="progress_bit_flag")
    wsp, ws = find("world_scenarios.json")
    print(f"\nshine_map: {smp}")
    print(f"world_scenarios: {wsp}")
    if not shine or not ws:
        print("MISSING scenario data — cannot dry-run classification")
        return

    fp = {}
    for e in shine:
        k = e["kingdom"]; b = lsb(e["progress_bit_flag"])
        fp[k] = min(fp.get(k, b), b)
    print("\nper-kingdom: first_playable_bit, peace_bit(clear-1), scenario_num, n_moons, post_peace(non-rock)")
    by_k = {}
    for e in shine:
        by_k.setdefault(e["kingdom"], []).append(e)
    PEACE_KINGDOMS = {"Cascade","Sand","Lake","Wooded","Metro","Snow","Seaside","Luncheon","Ruined","Bowser's"}
    for k in sorted(by_k):
        w = ws.get(k)
        if not w:
            print(f"  {k:12s} (no world_scenarios entry)")
            continue
        clear = w["clear_main_scenario"]; snum = w["scenario_num"]
        peace_bit = clear - 1
        sentinel = clear >= snum
        floor = fp.get(k, 0)
        pp = 0
        if k != "Cascade" and not sentinel and peace_bit > floor:
            for e in by_k[k]:
                if e["is_moon_rock"]:
                    continue
                if lsb(e["progress_bit_flag"]) >= peace_bit:
                    pp += 1
        haspred = "pred" if k in PEACE_KINGDOMS else "NOpred"
        rocks = sum(1 for e in by_k[k] if e["is_moon_rock"])
        flag = " SENTINEL" if sentinel else ""
        print(f"  {k:12s} fp={floor} peace_bit={peace_bit} snum={snum} n={len(by_k[k])} rocks={rocks} newpp={pp} {haspred}{flag}")


if __name__ == "__main__":
    main()
