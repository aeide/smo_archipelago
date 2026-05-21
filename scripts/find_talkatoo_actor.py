"""Scan kingdom-stage actor lists for Talkatoo's actor class name.

Talkatoo appears in CapWorldHomeStage (Cap Kingdom) early in the game,
plus every other pre-Bowser kingdom's home stage. His actor class is
unknown — we know only that he's referenced by `Hint_Bird` in
CharacterName.msbt. This script dumps every actor class+name in the Cap
home stage so we can spot him by elimination.

Run via the extract venv:
    scripts/.extract-venv/Scripts/python.exe scripts/find_talkatoo_actor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import oead

REPO_ROOT = Path(__file__).resolve().parent.parent
ROMFS = REPO_ROOT / ".romfs-cache"
STAGE_FILES = [
    "CapWorldHomeStageMap.szs",
    "CapWorldHomeStageDesign.szs",
    "WaterfallWorldHomeStageMap.szs",
    "SandWorldHomeStageMap.szs",
    "ForestWorldHomeStageMap.szs",
    "LakeWorldHomeStageMap.szs",
]


def walk(node, path="", out=None):
    """Walk an oead.byml tree, emit (path, value) for every node where the
    path ends in a key containing 'Bird' or where the leaf has the word
    'Talkatoo' or 'Hint_Bird' or similar. Also flag every node where the
    UnitConfigName/ClassName ends in 'Npc' or contains 'Bird'."""
    if out is None: out = []
    if isinstance(node, dict):
        # Dict items.
        for k, v in node.items():
            walk(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]", out)
    else:
        # Leaf scalar. Stringify.
        if isinstance(node, (bytes, str)):
            s = node if isinstance(node, str) else node.decode("utf-8", "replace")
            low = s.lower()
            if any(t in low for t in ("hint_bird", "talkatoo", "moonhint", "shinehint", "hintnpc")):
                out.append((path, s))
            # Also dump every UnitConfigName / ClassName / ModelName so we
            # can scan by eye for Talkatoo-shaped names.
            tail = path.split(".")[-1] if path else ""
            tail = tail.split("[")[0]
            if tail in ("UnitConfigName", "ClassName", "ParameterConfigName"):
                out.append((tail, s))
    return out


def main() -> int:
    for fname in STAGE_FILES:
        path = ROMFS / "StageData" / fname
        if not path.exists():
            print(f"[skip] {fname} not present", file=sys.stderr)
            continue
        print(f"==> {fname}")
        try:
            data = path.read_bytes()
            if data[:4] == b"Yaz0":
                data = oead.yaz0.decompress(data)
            sarc = oead.Sarc(data)
            # SMO stage szs holds <stage>.byml as the only file.
            byml_files = [f for f in sarc.get_files() if f.name.endswith(".byml")]
            for f in byml_files:
                doc = oead.byml.from_binary(bytes(f.data))
                py = oead.byml.to_text(doc)  # serialize then re-parse — easier than oead's PyObject tree
                # Pull out the unique class names from py text by simple grep.
                names = set()
                for line in py.splitlines():
                    if "UnitConfigName" in line or "ClassName" in line or "ParameterConfigName" in line:
                        # YAML "key: value"
                        try:
                            _, val = line.split(":", 1)
                            v = val.strip().strip('"')
                            if v:
                                names.add(v)
                        except ValueError:
                            pass
                # Show only candidates that look NPC-ish (avoid 1000 generic
                # actor names per stage).
                interesting = sorted(n for n in names if any(t in n.lower() for t in
                    ("hint", "bird", "talkatoo", "npc", "char")))
                for n in interesting:
                    print(f"   {n}")
        except Exception as e:
            print(f"   ERROR {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
