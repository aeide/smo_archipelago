"""Probe: for stages that had no entry door under the {ChangeStageArea,
DokanStageChange} filter, find EVERY placement (any UnitConfigName) whose
ChangeStageName points at them, so we learn what door actor types to add."""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path
import oead

REPO = Path(__file__).resolve().parent.parent
STAGEDATA = REPO / ".romfs-cache" / "StageData"

MISSING = {
    "SandWorldSlotStage", "SandWorldCostumeStage", "ForestWorldWoodsCostumeStage",
    "SeaWorldCostumeStage", "SandWorldRotateExStage", "FogMountainExStage",
    "LakeWorldShopStage", "PoleGrabCeilExStage", "CloudExStage",
    "SnowWorldShopStage", "SnowWorldCostumeStage", "LavaWorldShopStage",
    "LavaBonus1Zone", "LavaWorldCostumeStage", "LavaWorldTreasureStage",
    "DotTowerExStage", "SkyWorldCostumeStage", "FukuwaraiMarioStage",
    "PeachWorldCostumeStage", "RevengeBossKnuckleStage", "RevengeForestBossStage",
    "RevengeMofumofuStage", "RevengeGiantWanderBossStage", "RevengeBossMagmaStage",
    "RevengeBossRaidStage", "KillerRoadNoCapExStage",
}


def iter_dicts(node):
    if isinstance(node, (dict, oead.byml.Hash)):
        yield node
        for v in node.values():
            yield from iter_dicts(v)
    elif isinstance(node, (list, oead.byml.Array)):
        for v in node:
            yield from iter_dicts(v)


def main():
    # dest -> set of (unit, source, entry_id)
    found: dict[str, set] = defaultdict(set)
    for szs in sorted(STAGEDATA.glob("*Map.szs")) + sorted(STAGEDATA.glob("*Design.szs")):
        stem = szs.name[:-4]
        source = stem[:-3] if stem.endswith("Map") else stem[:-6] if stem.endswith("Design") else stem
        try:
            sarc = oead.Sarc(oead.yaz0.decompress(szs.read_bytes()))
        except Exception:
            continue
        for f in sarc.get_files():
            if not f.name.endswith(".byml"):
                continue
            try:
                doc = oead.byml.from_binary(bytes(f.data))
            except Exception:
                continue
            for d in iter_dicts(doc):
                try:
                    keys = set(d.keys())
                except Exception:
                    continue
                if "ChangeStageName" not in keys:
                    continue
                dest = str(d["ChangeStageName"])
                if dest not in MISSING:
                    continue
                unit = str(d["UnitConfigName"]) if "UnitConfigName" in keys else "?"
                eid = str(d["ChangeStageId"]) if "ChangeStageId" in keys else "?"
                found[dest].add((unit, source, eid))
    for dest in sorted(MISSING):
        recs = found.get(dest)
        if not recs:
            print(f"{dest}: *** NO placement anywhere points here ***")
        else:
            print(f"{dest}:")
            for unit, source, eid in sorted(recs):
                print(f"    unit={unit:20s} source={source:30s} entry_id={eid}")


if __name__ == "__main__":
    main()
