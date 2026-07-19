"""Detect interior arrival markers that never spawn Mario on a fresh arrival —
the provenance for port_graph.GATED_INTERIOR_ARRIVAL (the decoupled entrance-
shuffle softlock guard).

Background. On arrival SMO places Mario at the placement object in the
destination stage whose ChangeStageId matches the arrival id. If the only such
object is switch-gated (a `SwitchAppear` link — it isn't placed until the in-
stage switch is flipped, i.e. after completing the course) or entirely absent,
the arrival resolves to nothing: the stage loads with no player and no entry
pipe, a hard softlock. Vanilla never hits this because these ids are the EXIT /
goal pipes of multi-exit subareas — walked OUT of, never arrived AT. The
decoupled port shuffle can route an inbound entrance to one, hence the guard.

This scans every entrance_stages.json door_mouth and, for its subarea's INTERIOR
stage, checks whether the mouth's ChangeStageId resolves to an ungated arrival
marker in ANY scenario slot (conservative: safe if safe anywhere). It prints the
`(interior_stage, entry_id)` tuples that are NEVER safe — paste them into
port_graph.GATED_INTERIOR_ARRIVAL.

IP-safe: emits only functional stage names + entrance ids (same identifier class
already in entrance_stages.json). No moon/display names touched.

Requires a romfs dump under .romfs-cache/StageData (see extract_shine_map.py).
Run:  python scripts/detect_gated_arrival_markers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import oead

REPO = Path(__file__).resolve().parent.parent
STAGEDATA = REPO / ".romfs-cache" / "StageData"
ENTR = REPO / "apworld" / "smo_archipelago" / "data" / "entrance_stages.json"

_cache: dict[str, object] = {}


def load_map(stage: str):
    if stage in _cache:
        return _cache[stage]
    p = STAGEDATA / f"{stage}Map.szs"
    root = None
    if p.exists():
        data = p.read_bytes()
        if data[:4] == b"Yaz0":
            data = bytes(oead.yaz0.decompress(data))
        sarc = oead.Sarc(data)
        for f in sarc.get_files():
            if f.name == f"{stage}Map.byml":
                root = oead.byml.from_binary(bytes(f.data))
                break
    _cache[stage] = root
    return root


def markers(stage: str, entry_id: str):
    """Every object across all scenarios whose ChangeStageId == entry_id."""
    root = load_map(stage)
    if root is None:
        return None
    hits: list = []

    def walk(node):
        if isinstance(node, oead.byml.Hash):
            if "ChangeStageId" in node and str(node["ChangeStageId"]) == entry_id \
                    and "UnitConfigName" in node:
                hits.append(node)
            for _, v in node.items():
                if isinstance(v, (oead.byml.Hash, oead.byml.Array)):
                    walk(v)
        elif isinstance(node, oead.byml.Array):
            for v in node:
                walk(v)

    for scen in root:
        walk(scen)
    return hits


def is_switch_gated(o) -> bool:
    if "Links" in o and isinstance(o["Links"], oead.byml.Hash):
        for lk, _ in o["Links"].items():
            if "SwitchAppear" in str(lk):
                return True
    return False


def main() -> None:
    if not STAGEDATA.is_dir():
        sys.exit(f"ERROR: romfs StageData not found at {STAGEDATA}. Run "
                 f"extract_shine_map.py first to populate .romfs-cache/.")
    entr = json.loads(ENTR.read_text(encoding="utf-8"))
    unsafe: dict[tuple[str, str], str] = {}
    for name, rec in entr.items():
        if not isinstance(rec, dict) or "door_mouths" not in rec:
            continue
        interior = rec["stage"]
        for dm in rec["door_mouths"].values():
            entry_id = dm["entry_id"]
            ms = markers(interior, entry_id)
            if ms is None:
                continue  # interior map missing (zone alias etc.) — skip
            if not ms:
                unsafe[(interior, entry_id)] = f"{name}: no interior marker"
            elif all(is_switch_gated(o) for o in ms):
                unsafe[(interior, entry_id)] = f"{name}: switch-gated in all scenarios"

    print(f"# Unspawnable interior arrival markers: {len(unsafe)}")
    print("# Paste into port_graph.GATED_INTERIOR_ARRIVAL:\n")
    for (stage, eid), why in sorted(unsafe.items()):
        print(f'    ("{stage}", "{eid}"),  # {why}')


if __name__ == "__main__":
    main()
