"""Throwaway probe: find ChangeStage door objects in SMO stage byml.

Goal: confirm where the (ChangeStageName -> destination subarea stage,
ChangeStageId -> entrance id) mapping lives so we can build the P7 entrance
table from romfs StageData instead of a 134-subarea manual log walk.

Walks one parent HomeStage's Design + Map SARC, decodes every byml, and
prints any placement dict that carries a 'ChangeStageName' (or related)
key, plus the keys we see alongside it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import oead

REPO = Path(__file__).resolve().parent.parent
STAGEDATA = REPO / ".romfs-cache" / "StageData"

# Probe targets: parents we have ground-truth log lines for.
#   CapWorldHomeStage      -> PushBlockExStage   (id PushBlockExStageEnt)
#                          -> PoisonWaveExStage  (id PoisonWaveExEnt)
#   WaterfallWorldHomeStage-> TrexPoppunExStage  (id RexPoppunEx)
TARGETS = ["CapWorldHomeStage", "WaterfallWorldHomeStage"]

CHANGE_KEYS = ("ChangeStageName", "ChangeStageId", "ChangeStageIdInNextStage",
               "StageName", "ChangeStageBackName")


def iter_dicts(node):
    """Yield every dict in an arbitrarily nested byml document."""
    if isinstance(node, dict) or isinstance(node, oead.byml.Hash):
        yield node
        for v in node.values():
            yield from iter_dicts(v)
    elif isinstance(node, (list, oead.byml.Array)):
        for v in node:
            yield from iter_dicts(v)


def probe_sarc(path: Path) -> None:
    print(f"\n===== {path.name} =====")
    if not path.exists():
        print("  (missing)")
        return
    sarc = oead.Sarc(oead.yaz0.decompress(path.read_bytes()))
    for f in sarc.get_files():
        if not f.name.endswith(".byml"):
            continue
        try:
            doc = oead.byml.from_binary(bytes(f.data))
        except Exception as e:
            print(f"  [byml fail] {f.name}: {e}")
            continue
        hits = []
        for d in iter_dicts(doc):
            try:
                keys = set(d.keys())
            except Exception:
                continue
            if "ChangeStageName" in keys:
                rec = {k: str(d[k]) for k in CHANGE_KEYS if k in keys}
                if "UnitConfigName" in keys:
                    rec["UnitConfigName"] = str(d["UnitConfigName"])
                if "Id" in keys:
                    rec["Id"] = str(d["Id"])
                hits.append(rec)
        if hits:
            print(f"  --- {f.name}: {len(hits)} ChangeStage object(s) ---")
            for h in hits:
                print("    ", h)


def main() -> None:
    for stage in TARGETS:
        for suffix in ("Design", "Map"):
            probe_sarc(STAGEDATA / f"{stage}{suffix}.szs")


if __name__ == "__main__":
    main()
