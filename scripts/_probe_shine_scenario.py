"""Probe: what gating fields does SMO expose per-moon?

Reads the local romfs cache to discover whether moon availability
(scenario >= N, moon-rock, world-peace) is machine-extractable.

IP-safe: prints FIELD NAMES and structural shape, plus a tiny number of
sample entries using only functional identifiers (stage names, obj ids,
scenario numbers). No bulk moon-name dumps.
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="backslashreplace")

import oead

REPO = Path(__file__).resolve().parent.parent
ROMFS = REPO / ".romfs-cache"


def load_sarc(p: Path) -> dict[str, bytes]:
    sarc = oead.Sarc(oead.yaz0.decompress(p.read_bytes()))
    return {f.name: bytes(f.data) for f in sarc.get_files()}


def keys_of(d) -> list[str]:
    try:
        return list(d.keys())
    except Exception:
        return []


print("=" * 70)
print("PART 1 — ShineList entry fields (ShineInfo.szs)")
print("=" * 70)
files = load_sarc(ROMFS / "SystemData" / "ShineInfo.szs")
print("ShineList files:", sorted(files.keys())[:6], "...")
casc = oead.byml.from_binary(files["ShineList_WaterfallWorldHomeStage.byml"])
shines = casc["ShineList"] if "ShineList" in keys_of(casc) else casc
allkeys: Counter = Counter()
for s in shines:
    for k in keys_of(s):
        allkeys[k] += 1
print(f"\nCascade has {len(shines)} shine entries")
print("UNION of all field keys across Cascade entries (key -> count):")
for k, c in allkeys.most_common():
    print(f"   {k:24} {c}")
print("\nFirst 5 entries — gating fields only (functional, no JP names):")
gating = ["ObjId", "MainScenarioNo", "ProgressBitFlag", "IsMoonRock",
          "IsGrand", "IsAchievement", "OptionalId", "HintIdx"]
for s in shines[:5]:
    print("  ", {k: str(s[k]) for k in gating if k in keys_of(s)})

# Distribution of MainScenarioNo / ProgressBitFlag across ALL kingdoms
print("\nMainScenarioNo distribution across ALL kingdoms:")
scen_dist: Counter = Counter()
prog_dist: Counter = Counter()
rock_n = 0
for name, data in files.items():
    if not name.startswith("ShineList_"):
        continue
    doc = oead.byml.from_binary(data)
    arr = doc["ShineList"] if "ShineList" in keys_of(doc) else doc
    for s in arr:
        if "MainScenarioNo" in keys_of(s):
            scen_dist[int(s["MainScenarioNo"])] += 1
        if "ProgressBitFlag" in keys_of(s):
            prog_dist[int(s["ProgressBitFlag"])] += 1
        if "IsMoonRock" in keys_of(s) and bool(s["IsMoonRock"]):
            rock_n += 1
print("   MainScenarioNo:", dict(sorted(scen_dist.items())))
print("   ProgressBitFlag:", dict(sorted(prog_dist.items())))
print("   IsMoonRock=true count:", rock_n)

# Scan ALL kingdoms for any field that looks scenario/progress related
print("\nScanning ALL ShineList_*.byml for scenario-ish field names:")
scen_fields: Counter = Counter()
for name, data in files.items():
    if not name.startswith("ShineList_"):
        continue
    doc = oead.byml.from_binary(data)
    arr = doc["ShineList"] if "ShineList" in keys_of(doc) else doc
    for s in arr:
        for k in keys_of(s):
            lk = k.lower()
            if any(t in lk for t in ("scenario", "progress", "peace", "rock",
                                     "flag", "cond", "appear", "lock", "open",
                                     "clear", "story", "phase")):
                scen_fields[k] += 1
print("   ", dict(scen_fields) or "(none found)")

print()
print("=" * 70)
print("PART 2 — StageData placement structure (is it scenario-layered?)")
print("=" * 70)
mapf = load_sarc(ROMFS / "StageData" / "WaterfallWorldHomeStageMap.szs")
print("Map SARC inner files:", list(mapf.keys()))
# the map byml is usually the single inner file
inner_name = next(iter(mapf))
top = oead.byml.from_binary(mapf[inner_name])
print(f"\nTop-level type of {inner_name}: {type(top).__name__}")
if isinstance(top, list) or hasattr(top, "__len__") and not keys_of(top):
    try:
        print(f"  -> ARRAY of length {len(top)}  (likely scenario layers, 0-based)")
        for i, layer in enumerate(top):
            lk = keys_of(layer)
            print(f"     scenario[{i}]: categories = {lk}")
    except Exception as e:
        print("  array introspection failed:", e)
else:
    print("  -> MAP with keys:", keys_of(top))

print()
print("=" * 70)
print("PART 3 — find a Shine/PowerStar placement & dump its gating fields")
print("=" * 70)


def iter_placements(top):
    """Yield (scenario_idx, category, placement_dict)."""
    if keys_of(top):  # map at top
        layers = [(-1, top)]
    else:
        layers = list(enumerate(top))
    for sidx, layer in layers:
        for cat in keys_of(layer):
            val = layer[cat]
            try:
                for pl in val:
                    if keys_of(pl):
                        yield sidx, cat, pl
            except Exception:
                pass


shine_unitconfigs: Counter = Counter()
sample_shine = None
sample_scen = None
for sidx, cat, pl in iter_placements(top):
    ucn = ""
    if "UnitConfigName" in keys_of(pl):
        ucn = str(pl["UnitConfigName"])
    if "Shine" in ucn or "PowerStar" in cat or "Shine" in cat:
        shine_unitconfigs[ucn] += 1
        if sample_shine is None:
            sample_shine = pl
            sample_scen = sidx
print("Shine-ish UnitConfigNames seen:", dict(shine_unitconfigs) or "(none)")
if sample_shine is not None:
    print(f"\nSample shine placement (scenario layer index = {sample_scen}):")
    for k in keys_of(sample_shine):
        v = sample_shine[k]
        if keys_of(v):
            print(f"   {k:22} <dict keys={keys_of(v)}>")
        else:
            try:
                ln = len(v)
                # list-like
                print(f"   {k:22} <list len={ln}>")
            except Exception:
                print(f"   {k:22} {v!r}")
else:
    print("No shine placement found in this stage's Map byml.")

# Also: union of ALL placement field keys in this stage, flag gating-ish
print("\nAll placement field names in this stage (gating-ish flagged *):")
allpl: Counter = Counter()
for sidx, cat, pl in iter_placements(top):
    for k in keys_of(pl):
        allpl[k] += 1
for k, c in allpl.most_common():
    lk = k.lower()
    flag = "*" if any(t in lk for t in
                      ("scenario", "progress", "peace", "rock", "flag",
                       "cond", "appear", "lock", "open", "clear", "story",
                       "phase", "switch", "link")) else " "
    print(f"  {flag} {k:26} {c}")
