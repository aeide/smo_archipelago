#!/usr/bin/env python3
"""Scratch probe: design-check the mid_story anchor gating before implementing it.

IP-safe: prints functional ids, bit masks, scenario numbers, counts, and
name-presence booleans only. (shine_id IS the English moon-name suffix that
already lives in committed locations.json, so echoing it to MY console is not a
new commit — but nothing here is written to a tracked file.) Re-runnable.

Confirms, per kingdom:
  * grand-anchor-by-min-bit  (the moon whose collection advances b -> b+1)
  * mid_story moon count + min_scenario histogram
  * for each mid_story min_scenario M, the resolved anchor (grand at smallest
    min-bit >= M-1) and whether that anchor name EXISTS in locations.json.
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
    if flag <= 0:
        return 0
    return (flag & -flag).bit_length() - 1


def main():
    smp, shine = find("shine_map.json", need_field="progress_bit_flag")
    wsp, ws = find("world_scenarios.json")
    if not shine or not ws:
        print("MISSING scenario data")
        return
    loc_names = {l["name"] for l in json.loads(LOC.read_text(encoding="utf-8"))}

    by_k = {}
    for e in shine:
        by_k.setdefault(e["kingdom"], []).append(e)

    total_mid = 0
    for k in sorted(by_k):
        w = ws.get(k)
        if not w:
            continue
        moons = by_k[k]
        snum = w["scenario_num"]; clear = w["clear_main_scenario"]
        peace_bit = clear - 1
        fp = min(lsb(e["progress_bit_flag"]) for e in moons)
        sentinel = clear >= snum

        # grand anchors by min-bit
        grand_by_bit = {}
        for e in moons:
            if e.get("is_grand"):
                b = lsb(e["progress_bit_flag"])
                grand_by_bit.setdefault(b, f"{k}: {e['shine_id']}")
        grand_bits = sorted(grand_by_bit)

        # mid_story residual: non-rock, fp < M < peace_bit, excluding sentinel/Cascade-peace-trap
        hist = {}
        unresolved = 0
        for e in moons:
            if e.get("is_moon_rock"):
                continue
            M = lsb(e["progress_bit_flag"])
            # post_peace (coarse) test mirror:
            is_pp = (k != "Cascade" and not sentinel and peace_bit > fp
                     and M >= peace_bit)
            if is_pp:
                continue
            if M <= fp:
                continue  # first_visit
            if k != "Cascade" and (sentinel or peace_bit <= fp):
                continue  # no meaningful mid band
            # mid_story
            hist[M] = hist.get(M, 0) + 1
        n_mid = sum(hist.values())
        total_mid += n_mid
        if n_mid == 0 and not grand_bits:
            continue
        print(f"\n=== {k}  peace_bit={peace_bit} fp={fp} grand_bits={grand_bits} "
              f"mid={n_mid} hist={dict(sorted(hist.items()))}")
        for b in grand_bits:
            present = "OK" if grand_by_bit[b] in loc_names else "** MISSING **"
            print(f"     grand@bit{b}: {grand_by_bit[b]!r}  [{present}]")
        for M in sorted(hist):
            needed = M - 1
            cands = [b for b in grand_bits if b >= needed]
            if cands and k != "Cascade":
                anchor = grand_by_bit[cands[0]]
                tag = "canReach " + ("OK" if anchor in loc_names else "MISSING")
                print(f"     M={M} (n={hist[M]}) -> anchor@bit{cands[0]} {anchor!r} [{tag}]")
            else:
                print(f"     M={M} (n={hist[M]}) -> FALLBACK to peace fragment")
    print(f"\nTOTAL mid_story moons: {total_mid}")


if __name__ == "__main__":
    main()
