"""Probe: scenario-number -> meaning mapping (WorldList + ScenarioInfo).

IP-safe: structural field names + scenario COUNTS + functional stage ids only.
"""
from __future__ import annotations
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="backslashreplace")
import oead

REPO = Path(__file__).resolve().parent.parent
ROMFS = REPO / ".romfs-cache"


def load_sarc(p):
    s = oead.Sarc(oead.yaz0.decompress(p.read_bytes()))
    return {f.name: bytes(f.data) for f in s.get_files()}


def keys_of(d):
    try:
        return list(d.keys())
    except Exception:
        return []


print("=" * 70)
print("WorldList.szs structure")
print("=" * 70)
wl = load_sarc(ROMFS / "SystemData" / "WorldList.szs")
print("inner files:", list(wl.keys()))
for nm, data in wl.items():
    doc = oead.byml.from_binary(data)
    print(f"\n--- {nm}: top type = {type(doc).__name__}")
    if keys_of(doc):
        print("    keys:", keys_of(doc))
    else:
        try:
            print(f"    array len={len(doc)}")
            if len(doc):
                e0 = doc[0]
                print("    elem0 keys:", keys_of(e0))
                # dump one world entry's scenario-ish shape, functional only
                for k in keys_of(e0):
                    v = e0[k]
                    if keys_of(v):
                        print(f"      {k}: <dict {keys_of(v)}>")
                    else:
                        try:
                            print(f"      {k}: <list len={len(v)}>")
                        except Exception:
                            print(f"      {k}: {v!r}")
        except Exception as e:
            print("    introspect failed:", e)

print()
print("=" * 70)
print("ScenarioInfo.byml inside WaterfallWorldHomeStageMap.szs")
print("=" * 70)
mapf = load_sarc(ROMFS / "StageData" / "WaterfallWorldHomeStageMap.szs")
if "ScenarioInfo.byml" in mapf:
    doc = oead.byml.from_binary(mapf["ScenarioInfo.byml"])
    print("top type:", type(doc).__name__, "keys:", keys_of(doc))
    try:
        print("len:", len(doc))
        for i, e in enumerate(doc):
            if keys_of(e):
                print(f"  [{i}] keys={keys_of(e)} ->",
                      {k: str(e[k]) for k in keys_of(e)
                       if not keys_of(e[k])})
    except Exception as ex:
        print("introspect failed:", ex)
else:
    print("no ScenarioInfo.byml")
