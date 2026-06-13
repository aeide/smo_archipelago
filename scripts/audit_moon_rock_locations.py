"""Classify moon-rock CHECK candidates against the local romfs IsMoonRock flag.

Usage (run under the extract venv so oead is available; falls back to plain
python if the venv hasn't been created):

    scripts\\.extract-venv\\Scripts\\python scripts\\audit_moon_rock_locations.py
    # or explicitly:
    ... audit_moon_rock_locations.py --romfs <path-to-extracted-romfs>

Inputs:
  * scripts/moon_rock_candidates.json — community-sourced candidate names
    (Kgamer77/SuperMarioOdysseyArchipelago postgame tables, MIT), converted
    to this apworld's "<Kingdom>: <Name>" convention. COMMITTED.
  * The locally extracted RomFS (gitignored) — walked exactly like
    extract_shine_map.py, but keeping each shine's IsMoonRock flag.

Output: a per-kingdom console summary classifying every candidate as
  ROCK            flagged IsMoonRock, exact-name match -> promote to a check
  ROCK-CASEFIX    flagged IsMoonRock, but the candidate's casing/punctuation
                  differs from MSBT; the MSBT-exact form is printed for
                  one-at-a-time approval (the committed name must match MSBT
                  or sync_shine_table can't bind it)
  NOT-ROCK        exists in the game but not rock-gated (post-game-only:
                  Koopa Freerunning, Peach visits, hint-art, ...) -> skip
  ALREADY-LISTED  already a location in data/locations.json -> skip
  NOT-FOUND       no MSBT match at all (typo upstream?) -> investigate

plus counts of rock-flagged shines NOT covered by any candidate (printed to
console only — those names come from the romfs, so they stay out of the repo
until individually approved).

A detailed JSON report is written to scripts/.moon_rock_audit.json
(GITIGNORED — it contains romfs-derived strings).

IP note (CLAUDE.md): the candidates file carries only community-curated
names; everything derived from the romfs walk stays local.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(HERE))
import extract_shine_map as esm  # noqa: E402


def norm(s: str) -> str:
    """Casing/punctuation-insensitive key. Curly vs straight quotes, hyphen
    variants, and ellipsis characters all collapse so community names match
    MSBT text despite typographic drift."""
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("…", "...").replace("–", "-").replace("—", "-"))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def find_romfs(arg: Path | None) -> Path:
    """Locate an extracted RomFS: --romfs arg, repo .romfs-cache, or the
    wizard's bundled-scripts cache under %APPDATA%."""
    candidates: list[Path] = []
    if arg:
        candidates.append(arg)
    candidates.append(REPO / ".romfs-cache")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "SMOArchipelago" / "bundled" / "scripts" / ".romfs-cache")
    for base in candidates:
        if not base.is_dir():
            continue
        # The romfs root is wherever SystemData/ lives (possibly nested).
        if (base / "SystemData").is_dir():
            return base
        for child in base.rglob("SystemData"):
            return child.parent
    raise SystemExit(
        "FAIL: no extracted RomFS found. Pass --romfs <dir> (the directory "
        "containing SystemData/), or run the wizard's extraction first.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--romfs", type=Path, default=None)
    p.add_argument("--candidates", type=Path,
                   default=HERE / "moon_rock_candidates.json")
    p.add_argument("--report", type=Path,
                   default=HERE / ".moon_rock_audit.json")
    args = p.parse_args(argv)

    romfs = find_romfs(args.romfs)
    print(f"romfs: {romfs}")

    raw = esm.walk_shine_lists(romfs)
    msbts = esm.load_all_stage_msbts(romfs)
    apworld_names = esm.load_apworld_moon_names()

    # Resolve every shine to "<Kingdom>: <Name>" exactly like extract(),
    # but keep the IsMoonRock flag.
    rock: dict[str, str] = {}      # norm -> exact resolved name
    nonrock: dict[str, str] = {}
    for r in raw:
        kingdom = esm.KINGDOM_FOR_HOMESTAGE.get(r.home_stage)
        if kingdom is None:
            continue
        text = msbts.get(r.stage_name, {}).get(f"ScenarioName_{r.object_id}")
        if not text:
            continue
        full = f"{kingdom}: {text}"
        (rock if r.is_moon_rock else nonrock)[norm(full)] = full

    cand_data = json.loads(args.candidates.read_text(encoding="utf-8"))
    report: dict[str, dict[str, list]] = {}
    totals = {"ROCK": 0, "ROCK-CASEFIX": 0, "NOT-ROCK": 0,
              "ALREADY-LISTED": 0, "NOT-FOUND": 0}
    covered: set[str] = set()

    for kingdom, names in cand_data.items():
        if kingdom.startswith("_"):
            continue
        rows: dict[str, list] = {k: [] for k in totals}
        for name in names:
            key = norm(name)
            if name in apworld_names:
                rows["ALREADY-LISTED"].append(name)
            elif key in rock:
                covered.add(key)
                exact = rock[key]
                if exact == name:
                    rows["ROCK"].append(name)
                else:
                    rows["ROCK-CASEFIX"].append({"candidate": name, "msbt": exact})
            elif key in nonrock:
                rows["NOT-ROCK"].append(name)
            else:
                rows["NOT-FOUND"].append(name)
        report[kingdom] = rows
        for k in totals:
            totals[k] += len(rows[k])
        print(f"\n== {kingdom} ==")
        for k in ("ROCK", "ROCK-CASEFIX", "NOT-ROCK", "ALREADY-LISTED", "NOT-FOUND"):
            if rows[k]:
                print(f"  {k} ({len(rows[k])}):")
                for entry in rows[k]:
                    print(f"    {entry}")

    # Rock-flagged shines no candidate covered: console-only (romfs strings).
    uncovered = [v for k, v in sorted(rock.items()) if k not in covered]
    print(f"\n== totals == {totals}")
    print(f"rock-flagged shines not covered by any candidate: {len(uncovered)}")
    for name in uncovered:
        print(f"    (local-only) {name}")

    args.report.write_text(
        json.dumps({"totals": totals, "kingdoms": report,
                    "uncovered_rock": uncovered},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"\ndetailed report -> {args.report} (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
