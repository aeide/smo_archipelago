"""Validate ProgressBitFlag semantics against KNOWN Cascade availability.

Session-only analysis (Devon's machine, no file written, single kingdom).
Joins Cascade shines to their English ScenarioName for a ground-truth check
against documented availability:
  - before Multi Moon Atop the Falls only 3 moons exist
  - Cascade ClearMainScenario / MoonRockScenario from WorldList
"""
from __future__ import annotations
import sys, io
from pathlib import Path
import oead

REPO = Path(__file__).resolve().parent.parent
ROMFS = REPO / ".romfs-cache"
sys.path.insert(0, str(REPO / "scripts"))
from extract_shine_map import parse_msbt  # reuse the MSBT reader
# extract_shine_map already rewrapped sys.stdout as UTF-8/backslashreplace on
# import; reuse it directly (a second wrapper closes the underlying buffer).


def load_sarc(p):
    s = oead.Sarc(oead.yaz0.decompress(p.read_bytes()))
    return {f.name: bytes(f.data) for f in s.get_files()}


def keys_of(d):
    try:
        return list(d.keys())
    except Exception:
        return []


# Cascade WorldList entry (find by matching StageList containing Waterfall)
wl = load_sarc(ROMFS / "SystemData" / "WorldList.szs")
worlds = oead.byml.from_binary(wl["WorldListFromDb.byml"])
casc_world = None
for w in worlds:
    sl = w["StageList"] if "StageList" in keys_of(w) else []
    names = [str(x["StageName"]) for x in sl if "StageName" in keys_of(x)] if sl else []
    if any("Waterfall" in n for n in names):
        casc_world = w
        break
if casc_world:
    print("Cascade WorldList:",
          {k: str(casc_world[k]) for k in
           ["ScenarioNum", "ClearMainScenario", "MoonRockScenario",
            "AfterEndingScenario"] if k in keys_of(casc_world)})

# Cascade shines + names
shfiles = load_sarc(ROMFS / "SystemData" / "ShineInfo.szs")
shines = oead.byml.from_binary(shfiles["ShineList_WaterfallWorldHomeStage.byml"])
shines = shines["ShineList"] if "ShineList" in keys_of(shines) else shines

msbt = load_sarc(ROMFS / "LocalizedData" / "USen" / "MessageData" / "StageMessage.szs")
names_by_stage = {}
for nm, data in msbt.items():
    if nm.endswith(".msbt"):
        try:
            names_by_stage[nm[:-5]] = parse_msbt(data)
        except Exception:
            names_by_stage[nm[:-5]] = {}

print(f"\n{'name':45} {'MSc':>3} {'bitflag':>8} {'binary':>12} rock grand")
print("-" * 90)
rows = []
for s in shines:
    stage = str(s["StageName"])
    obj = str(s["ObjId"])
    nm = names_by_stage.get(stage, {}).get(f"ScenarioName_{obj}", f"<{obj}>")
    msc = int(s["MainScenarioNo"])
    bf = int(s["ProgressBitFlag"])
    rock = bool(s["IsMoonRock"])
    grand = bool(s["IsGrand"])
    rows.append((msc, bf, nm, rock, grand))
for msc, bf, nm, rock, grand in sorted(rows, key=lambda r: (r[1], r[0])):
    print(f"{nm[:45]:45} {msc:>3} {bf:>8} {bf:>012b} {'R' if rock else ' '}    {'G' if grand else ' '}")
