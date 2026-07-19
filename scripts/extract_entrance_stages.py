"""Generate data/entrance_stages.json — the P7 entrance-shuffle stage table.

Bridges the apworld's subarea DISPLAY names (subareas.json keys, e.g.
"Poison Tides") to the SMO-internal STAGE names + door entrance ids the
Switch mod sees at runtime in GameDataFile::changeNextStage's ChangeStageInfo
(e.g. dest stage "PoisonWaveExStage", arrival id "PoisonWaveExEnt").

Why this exists: the entry_id is NOT derivable from moon data. It lives in the
parent stage's placement byml as a ChangeStageArea / DokanStageChange object
carrying {ChangeStageName -> dest stage, ChangeStageId -> arrival id}. This
script walks every StageData/<Stage>{Map,Design}.szs, collects the global door
graph, then joins it to each subarea via the moon ShineList (shine_map.json).

OUTPUT IS IP-SAFE TO COMMIT: it contains only functional identifiers (stage
names, entrance ids) keyed by subarea display names that already live in
subareas.json. No moon names are emitted — shine_map.json is used transiently
only to map (kingdom, shine_id) -> stage_name and never copied into the output.

Inputs:
  .romfs-cache/StageData/*.szs                       (gitignored romfs dump)
  %APPDATA%/SMOArchipelago/data/shine_map.json       (gitignored extracted map)
  apworld/smo_archipelago/data/subareas.json         (committed)

Run after extract_shine_map.py has populated shine_map.json:
  python scripts/extract_entrance_stages.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import oead

REPO = Path(__file__).resolve().parent.parent
STAGEDATA = REPO / ".romfs-cache" / "StageData"
SUBAREAS = REPO / "apworld" / "smo_archipelago" / "data" / "subareas.json"
OUT = REPO / "apworld" / "smo_archipelago" / "data" / "entrance_stages.json"

_APPDATA = os.environ.get("APPDATA")
if _APPDATA:
    SHINE_MAP = Path(_APPDATA) / "SMOArchipelago" / "data" / "shine_map.json"
else:
    SHINE_MAP = Path.home() / ".local" / "share" / "SMOArchipelago" / "data" / "shine_map.json"

# Door placements use one of these UnitConfigNames; everything else carrying a
# ChangeStageName (Shine, ShineAddHeight, ...) is a collectible, not a door.
# The full set was confirmed by probing every placement that points at a known
# subarea-interior stage (see scripts/_probe_missing.py results, 2026-06-18):
DOOR_UNITS = {
    "ChangeStageArea",      # standard trigger-area door / pipe mouth
    "DokanStageChange",     # warp pipe
    "DoorWarpStageChange",  # building door: shops, costume rooms, slots, treasure vaults
    "DoorAreaChangeCap",    # capless-door variant (e.g. Breakdown Road Capless)
    "PictureStageChange",   # boss re-fight painting warp (Peach's Castle Revenge* rooms)
    "BazookaElectric",      # Spark-Pylon launch transition into an Ex sub-stage
}

# Kingdom full name (subareas.json) -> short kingdom (shine_map.json / location
# prefix). Mirrors extract_shine_map.KINGDOM_FOR_HOMESTAGE value space.
KINGDOM_SHORT = {
    "Cap Kingdom": "Cap", "Cascade Kingdom": "Cascade", "Sand Kingdom": "Sand",
    "Lake Kingdom": "Lake", "Wooded Kingdom": "Wooded", "Cloud Kingdom": "Cloud",
    "Lost Kingdom": "Lost", "Metro Kingdom": "Metro", "Night Metro": "Metro",
    "Snow Kingdom": "Snow", "Seaside Kingdom": "Seaside",
    "Luncheon Kingdom": "Luncheon", "Ruined Kingdom": "Ruined",
    "Bowser's Kingdom": "Bowser's", "Moon Kingdom": "Moon",
    "Mushroom Kingdom": "Mushroom", "Dark Side": "Dark Side",
    "Darker Side": "Darker Side",
}


# Primary entry/exit selection (Devon's rule, 2026-06-19):
#   ENTER a subarea -> arrive at the NON-suffixed front door. The _Exit/return/
#     dokan pipe is only visible during the exit animation, so never arrive there.
#   LEAVE a subarea -> return to the overworld via the _Exit/return/dokan-suffixed
#     door when one exists.
# When the suffix rule can't decide an entry (genuine twin entrances like
# dot00/dot01), real doors are preferred over pipes, then the lexicographically
# first id is taken as a deterministic default and the subarea is flagged
# entry_ambiguous in the report for optional manual review.
EXIT_SUFFIX_RE = re.compile(r"(_?[Ee]xit|[Rr]eturn|[Dd]okan)$")

# Lower = more "front-door" for entry selection; pipes deprioritized.
DOOR_ENTRY_PRIORITY = {
    "ChangeStageArea": 0, "DoorWarpStageChange": 0, "DoorAreaChangeCap": 0,
    "BazookaElectric": 0, "PictureStageChange": 0, "DokanStageChange": 1,
}


def _is_exit_like(entry_id: str) -> bool:
    return bool(EXIT_SUFFIX_RE.search(entry_id))


def port_id(other_stage: str | None, entry_id: str | None) -> str | None:
    """Stable id for the overworld-side coordinate of a physical door/pipe.

    Every door is placed at one stage carrying a ChangeStageId that is reused
    on BOTH ends of the pair by SMO convention: the trigger placed in the
    overworld (an "entries" record's `parent`+`entry_id`) is the exact object a
    reciprocal "exits" record targets to land Mario back outside (its
    `dest`+`entry_id`) — see pick_primary_exit's reciprocation check, which
    already relies on this mechanic. So `(other_stage, entry_id)` — the
    overworld stage plus the shared id — uniquely names one physical door
    instance, independent of whether it was discovered via an entry or an exit
    scan. A reciprocated pair (e.g. Costume Room's "abc" door) yields the SAME
    port_id from both its entries[] and exits[] record; a one-way pipe (e.g.
    Push Block Peril's `PushBlockExStageEntDokan` exit, which has no matching
    entries[] record) gets its own distinct port_id — this is the concrete
    mechanism that gives Push Block Peril's two exits (main door vs. pipe)
    different ids instead of collapsing to one node keyed on `cur` alone.
    """
    if not other_stage or not entry_id:
        return None
    return f"{other_stage}#{entry_id}"


def pick_primary_entry(entries: list[dict]) -> tuple[dict | None, bool]:
    """Return (primary_entry_or_None, ambiguous?)."""
    if not entries:
        return None, False
    cands = [e for e in entries if not _is_exit_like(e["entry_id"])] or list(entries)
    best = min(DOOR_ENTRY_PRIORITY.get(e["unit"], 2) for e in cands)
    cands = [e for e in cands if DOOR_ENTRY_PRIORITY.get(e["unit"], 2) == best]
    ambiguous = len({e["entry_id"] for e in cands}) > 1
    return sorted(cands, key=lambda e: e["entry_id"])[0], ambiguous


# Subarea interior-stage overrides, keyed by subarea display name. Normally a
# subarea's stage is derived from its moons' stage_name (subarea_stage), but the
# 6 Mushroom boss re-fight subareas are POOLED AT THE TOWER, not the arena
# (Devon ruling 2026-07-18): the shuffleable unit is the tower room
# (PeachWorldPicture*Stage — a REAL standalone stage with a two-way
# ChangeStageArea/Dokan connection to PeachWorldHomeStage, romfs-verified),
# while the painting -> RevengeBoss*Stage arena -> Multi-Moon
# return-to-tower loop inside stays fully vanilla. The moons live in the arena,
# so the derived stage would be the arena — this table re-points the record at
# the tower. (The paintings themselves are kept out of the records by the
# PictureStageChange exit filter below, so they can never be pooled/remapped.)
SUBAREA_STAGE_OVERRIDE: dict[str, str] = {
    "Knucklotec Boss Re-fight": "PeachWorldPictureBossKnuckleStage",
    "Torkdrift Boss Re-fight": "PeachWorldPictureBossForestStage",
    "Mechawiggler Boss Re-fight": "PeachWorldPictureMofumofuStage",
    "Mollusque-Lanceur Boss Re-fight": "PeachWorldPictureGiantWanderBossStage",
    "Cookatiel Boss Re-fight": "PeachWorldPictureBossMagmaStage",
    "Lord of Lightning Boss Re-fight": "PeachWorldPictureBossRaidStage",
}

# Manual primary_exit overrides, keyed by subarea display name. Used when the
# geometrically-correct "exit pipe" the player expects to emerge from is NOT one of
# the interior's own return pipes — so pick_primary_exit (which only ranks the
# interior's exits) can't find it. The classic case is Jaxi Driving
# (SandWorldSphinxExStage): its own returns land OFF the mesa finish spot
# (`run00`=desert pipe below; `run00return`=no Home arrival marker → Odyssey
# fallback), while the pipe ON the mesa top beside the checkpoint/Jaxi/moon —
# obj2160, ChangeStageId `arijigoku2` — belongs to a DIFFERENT subarea
# (SandWorldPressExStage). On ARRIVAL the engine places Mario at the Home object
# whose ChangeStageId matches, regardless of that object's own ChangeStageName, so
# targeting `arijigoku2` emerges Mario on the mesa top. Keep in sync with the
# hand-authored primary_exit in data/entrance_stages.json.
PRIMARY_EXIT_OVERRIDE: dict[str, dict] = {
    "Jaxi Driving": {
        "dest": "SandWorldHomeStage",
        "entry_id": "arijigoku2",
        "unit": "DokanStageChange",
    },
}


def pick_primary_exit(
    exits: list[dict],
    parent: str | None,
    into_set: set[tuple[str, str]] | None = None,
) -> dict | None:
    """Return the door to use when returning to the overworld, or None.

    `into_set` is the set of (source_stage, entry_id) pairs for every door that
    leads INTO this interior. It's used to prefer a RECIPROCATED exit: SMO spawns
    an arriving player at the dest stage's door whose ChangeStageId matches the
    exit's — so a valid forward arrival requires the dest stage to have a door
    back into this interior sharing the exit's entry_id, i.e. (exit.dest,
    exit.entry_id) in into_set. An UNRECIPROCATED exit id is a departure-only pipe
    with no arrival marker in the overworld, so a forward changeNextStage to it
    can't resolve and the engine default-spawns at the Odyssey. This bit the
    entrance shuffle at Jaxi Driving: its "return"-suffixed exit `run00return` is
    such a dead departure-only id (no `run00return` marker exists in
    SandWorldHomeStage — only `aaa` and `run00`), so exiting the shuffled interior
    dumped Mario at the Sand Odyssey instead of the exit-pipe finish spot. The real
    reciprocated exit is the `run00` pipe. We only NARROW to reciprocated
    candidates when at least one exists, so subareas that legitimately leave via a
    returnPrevStage-only path (no forward marker) keep the old behavior.
    """
    if not exits:
        return None
    cands = [e for e in exits if e["dest"] == parent] or list(exits)
    if into_set is not None:
        recip = [e for e in cands if (e["dest"], e["entry_id"]) in into_set]
        if recip:
            cands = recip
    suffixed = [e for e in cands if _is_exit_like(e["entry_id"])]
    return sorted(suffixed or cands, key=lambda e: e["entry_id"])[0]


# --------------------------------------------------------------------------
# Step A: global door graph from romfs StageData
# --------------------------------------------------------------------------

def iter_dicts(node):
    if isinstance(node, (dict, oead.byml.Hash)):
        yield node
        for v in node.values():
            yield from iter_dicts(v)
    elif isinstance(node, (list, oead.byml.Array)):
        for v in node:
            yield from iter_dicts(v)


def collect_doors() -> list[dict]:
    """Return deduped forward doors [{source, dest, entry_id, unit}]."""
    seen: set[tuple[str, str, str, str]] = set()
    doors: list[dict] = []
    szs_files = sorted(STAGEDATA.glob("*Map.szs")) + sorted(STAGEDATA.glob("*Design.szs"))
    for szs in szs_files:
        # Stage name = filename minus the Map/Design suffix and .szs.
        stem = szs.name[:-4]  # drop .szs
        for suf in ("Map", "Design"):
            if stem.endswith(suf):
                source = stem[: -len(suf)]
                break
        else:
            source = stem
        try:
            sarc = oead.Sarc(oead.yaz0.decompress(szs.read_bytes()))
        except Exception as e:
            print(f"WARN: {szs.name}: {e}", file=sys.stderr)
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
                unit = str(d["UnitConfigName"]) if "UnitConfigName" in keys else ""
                if unit not in DOOR_UNITS:
                    continue
                dest = str(d["ChangeStageName"])
                entry_id = str(d["ChangeStageId"]) if "ChangeStageId" in keys else "None"
                if dest == "None":
                    continue  # arrival markers / exits handled from their own stage
                key = (source, dest, entry_id, unit)
                if key in seen:
                    continue
                seen.add(key)
                doors.append({"source": source, "dest": dest,
                              "entry_id": entry_id, "unit": unit})
    return doors


# --------------------------------------------------------------------------
# Step B: subarea display name -> stage name, via shine_map
# --------------------------------------------------------------------------

def build_shine_lookup() -> dict[tuple[str, str], str]:
    """(kingdom_short, shine_id) -> stage_name."""
    data = json.loads(SHINE_MAP.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], str] = {}
    for e in data:
        out[(e["kingdom"], e["shine_id"])] = e["stage_name"]
    return out


def subarea_stage(info: dict, shine_lookup: dict[tuple[str, str], str]) -> tuple[str | None, dict]:
    """Resolve a subarea's interior stage from its location_names.

    Returns (stage_or_None, diag). diag records the per-location resolution so
    ambiguity (multiple stages) or misses are visible in the report.
    """
    short = KINGDOM_SHORT.get(info.get("kingdom", ""), info.get("kingdom", ""))
    stages: dict[str, int] = defaultdict(int)
    misses: list[str] = []
    for loc in info.get("location_names", []):
        # "Cap: Skimming the Poison Tide" -> prefix "Cap", shine_id rest.
        prefix, _, shine_id = loc.partition(": ")
        stage = shine_lookup.get((prefix, shine_id)) or shine_lookup.get((short, shine_id))
        if stage is None:
            misses.append(loc)
        else:
            stages[stage] += 1
    diag = {"stages": dict(stages), "misses": misses}
    if not stages:
        return None, diag
    # Pick the most common stage (subarea interiors are single-stage; ties are
    # flagged via diag for manual review).
    best = max(stages.items(), key=lambda kv: kv[1])[0]
    return best, diag


# --------------------------------------------------------------------------
# Step C: join + emit
# --------------------------------------------------------------------------

def main() -> None:
    if not STAGEDATA.is_dir():
        sys.exit(f"ERROR: romfs StageData not found at {STAGEDATA}. Run "
                 f"extract_shine_map.py first to populate .romfs-cache/.")
    if not SHINE_MAP.is_file():
        sys.exit(f"ERROR: shine_map.json not found at {SHINE_MAP}. Run "
                 f"scripts/extract_shine_map.py first.")

    subareas = json.loads(SUBAREAS.read_text(encoding="utf-8"))
    shine_lookup = build_shine_lookup()
    doors = collect_doors()

    # Index doors by dest (entries INTO a stage) and source (exits OUT of a stage).
    by_dest: dict[str, list[dict]] = defaultdict(list)
    by_source: dict[str, list[dict]] = defaultdict(list)
    for dr in doors:
        by_dest[dr["dest"]].append(dr)
        by_source[dr["source"]].append(dr)

    result: dict[str, dict] = {}
    report = {"resolved": 0, "no_stage": [], "no_entry_door": [],
              "ambiguous_stage": [], "multi_parent": [], "entry_ambiguous": [],
              "no_door_exit": []}

    for name, info in subareas.items():
        stage, diag = subarea_stage(info, shine_lookup)
        override_stage = SUBAREA_STAGE_OVERRIDE.get(name)
        if override_stage is not None:
            stage = override_stage
        if stage is None:
            report["no_stage"].append({"subarea": name, "diag": diag})
            continue
        if override_stage is None and len(diag["stages"]) > 1:
            report["ambiguous_stage"].append({"subarea": name, "stages": diag["stages"]})

        entries = by_dest.get(stage, [])
        exits = by_source.get(stage, [])
        if override_stage is not None:
            # Tower records only: a PictureStageChange OUT of the tower is the
            # PAINTING — it leads DEEPER (into the vanilla-kept boss arena),
            # never back to the overworld. Emitting it as an exit port would
            # pool the painting as an interior ingest mouth and let the shuffle
            # remap the painting warp — breaking the vanilla painting -> boss ->
            # Multi-Moon-return-to-tower loop. Scoped to the override records:
            # elsewhere (Moon's Wedding Room) PictureStageChange exits are real
            # record data.
            exits = [e for e in exits if e["unit"] != "PictureStageChange"]
        parents = sorted({e["source"] for e in entries})
        if not entries:
            report["no_entry_door"].append({"subarea": name, "stage": stage})
        if len(parents) > 1:
            report["multi_parent"].append({"subarea": name, "stage": stage,
                                           "parents": parents})

        # `port_id` (see port_id() docstring) turns each entries[]/exits[] item
        # into its own addressable node instead of an unlabeled list slot —
        # required for a future port-level shuffle where e.g. Push Block
        # Peril's two exits (main door vs. pipe) must resolve to distinct
        # targets, not both fall out of one `cur`-keyed primary_exit.
        entry_recs = [{"parent": e["source"], "entry_id": e["entry_id"],
                       "unit": e["unit"],
                       "port_id": port_id(e["source"], e["entry_id"])}
                      for e in entries]
        exit_recs = [{"dest": e["dest"], "entry_id": e["entry_id"],
                      "unit": e["unit"],
                      "port_id": port_id(e["dest"], e["entry_id"])}
                     for e in exits]
        primary_entry, entry_ambiguous = pick_primary_entry(entry_recs)
        # (source_stage, entry_id) for every door INTO this interior — the arrival
        # markers a returning player can resolve. Used to reject unreciprocated
        # departure-only exit ids (see pick_primary_exit).
        into_set = {(e["source"], e["entry_id"]) for e in entries}
        override = PRIMARY_EXIT_OVERRIDE.get(name)
        if override is not None:
            # Copy (not mutate the module-level constant) and stamp a port_id —
            # the override bypasses exit_recs, so it wouldn't otherwise get one.
            primary_exit = dict(override)
            primary_exit["port_id"] = port_id(
                primary_exit.get("dest"), primary_exit.get("entry_id"))
        else:
            primary_exit = pick_primary_exit(
                exit_recs, parents[0] if parents else None, into_set)
        if entry_ambiguous:
            report["entry_ambiguous"].append({
                "subarea": name, "picked": primary_entry["entry_id"],
                "candidates": sorted({e["entry_id"] for e in entry_recs})})
        if primary_exit is None:
            report["no_door_exit"].append({"subarea": name, "stage": stage})

        # Global-per-subarea catalogue of the overworld-side coordinate of
        # every door (entry + exit), deduped by port_id so a reciprocated pair
        # (entry + exit sharing one physical door) collapses to one entry
        # tagged with both roles, while a one-way pipe keeps its own row.
        door_mouths: dict[str, dict] = {}
        for e in entry_recs:
            pid = e["port_id"]
            if pid is None:
                continue
            dm = door_mouths.setdefault(pid, {
                "stage": e["parent"], "entry_id": e["entry_id"], "roles": []})
            if "entry" not in dm["roles"]:
                dm["roles"].append("entry")
        for e in exit_recs:
            pid = e["port_id"]
            if pid is None:
                continue
            dm = door_mouths.setdefault(pid, {
                "stage": e["dest"], "entry_id": e["entry_id"], "roles": []})
            if "exit" not in dm["roles"]:
                dm["roles"].append("exit")

        result[name] = {
            "kingdom": info.get("kingdom"),
            "stage": stage,
            "parents": parents,
            "primary_entry": primary_entry,
            "primary_exit": primary_exit,
            "entries": entry_recs,
            "exits": exit_recs,
            "door_mouths": door_mouths,
        }
        if entries:
            report["resolved"] += 1

    output = {"_schema_version": 2, **result}
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    # Report to stderr so stdout stays clean JSON if ever piped.
    total_entry_ports = sum(len(v["entries"]) for v in result.values())
    total_exit_ports = sum(len(v["exits"]) for v in result.values())
    print(f"[entrance-stages] subareas={len(subareas)} doors={len(doors)} "
          f"resolved_with_entry={report['resolved']}", file=sys.stderr)
    print(f"[entrance-stages] ports: entries={total_entry_ports} "
          f"exits={total_exit_ports} total={total_entry_ports + total_exit_ports} "
          f"(raw, ALL subareas — see docs/plan-decoupled-entrances.md Phase 1 "
          f"for the pool-scoped budget vs kEntranceRemapMax)", file=sys.stderr)
    print(f"[entrance-stages] wrote {OUT}", file=sys.stderr)
    for cat in ("no_stage", "no_entry_door", "ambiguous_stage", "multi_parent",
                "entry_ambiguous", "no_door_exit"):
        items = report[cat]
        if items:
            print(f"\n[{cat}] {len(items)}:", file=sys.stderr)
            for it in items:
                print("   ", json.dumps(it, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
