"""
port_graph.py — P3b: the decoupled entrance randomizer's port-graph data model.

Pure data layer (no AP imports at module top level, mirroring entrance_logic.py)
consumed by:
  * the P3c matching algorithm (rolls a connectivity-guaranteed involution over
    the mouth pool),
  * the P3d region wiring (attaches per-direction rules to a general graph),
  * the P3e slot_data/remap-row compiler.

Design authority: docs/design-decoupled-kingdom-order.md (D1–D9, signed off
2026-07-07) and docs/plan-decoupled-entrances.md. Read those before changing
pool or exclusion semantics here.

The mouth model
---------------
Every physical door/pipe (one P1 `port_id`, i.e. one ChangeStageId shared by
the pair per SMO convention) has up to TWO mouths:

  * its OVERWORLD mouth — the opening in the parent stage. Coordinates come
    from the subarea record's `door_mouths[port_id]` (schema v2).
  * its INTERIOR mouth — the opening inside the subarea. Stage is the
    subarea's `stage`; the spawn/transition marker is the same door
    `entry_id` (P0-validated: spawning at both sides' markers works).

Vanilla behavior is the identity involution: each door's two mouths are
matched to each other. The decoupled shuffle re-matches mouths freely.

Ingest vs. emit
---------------
A mouth is INGEST-capable when Mario can physically walk into it from the
stage it lives in:
  * overworld mouth  → its port_id appears in the record's `entries[]`
  * interior mouth   → its port_id appears in the record's `exits[]`
Every sound mouth is EMIT-capable (usable as a rewrite/spawn target) — both
sides were proven in-game by the P0 spike.

THE POOL IS INGEST MOUTHS ONLY, matched pairwise (an involution). Because
both ends of every matched pair are walkable, path symmetry (Devon's
requirement 2) holds by construction. Emit-only mouths (e.g. the overworld
end of an exit-only pipe) simply become unused spawn markers — nothing can
walk into them, so no player-visible asymmetry exists.

Exclusion propagates DOOR-WISE (D5 erratum)
-------------------------------------------
If a door's overworld mouth is excluded (Moon/Dark/Darker overworlds, or
festival-dropped kingdoms) its interior mouth must be excluded too: leaving
the overworld mouth vanilla while re-matching the interior mouth would give
the player an asymmetric door (walk in vanilla, walk back → somewhere else).
Practically this removes Moon/Dark/Darker subareas from the decoupled
matching entirely (their only doors hang off excluded overworlds) — their
checks stay flight-reachable exactly as today, consistent with D6.

One-way-ENTRY subareas stay vanilla (P3c erratum, 2026-07-07)
-------------------------------------------------------------
The emit-only note above covers the exit-only pipe (interior ingest, overworld
marker unused — nothing strands). The MIRROR shape — a subarea with ingest
entry doors but NO walkable interior exit (`exits[] == []`, scripted return) —
is NOT safe to shuffle: its interior can only ever be entered through its own
entry marker, so re-matching the entry door orphans the whole interior and
every check in it. Real data: the SIX Mushroom boss re-fight painting arenas
(RevengeBoss*Stage — they hold the re-fight Multi-Moons). Rule: a subarea
that would contribute pooled mouths but zero INTERIOR ingest mouths has ALL
its doors dropped from the pool (vanilla passthrough), same door-wise shape
as the D5 exclusions. (One-way *split* doors — Jaxi Driving's `aaa` entry +
`run00return` exit, zone-split doors like `LakeWorldTownZone#CapTrampolineA`
whose two halves carry different port_ids — are fine: each lone half is
independently matchable and the interior stays enterable via its own ingest
mouths.)

Costs (per-direction rules, D-asymmetric edges)
-----------------------------------------------
Each INGEST mouth carries one cost — what it takes to use the opening from
its own side. Traversing a matched edge A→B = reach(region of A) AND
cost(A). This is the generalization the feasibility doc called "asymmetric
edge cost":
  * overworld mouth cost = the door-side gate that make_door_access_rule
    composes today: SUBAREA_ENTRANCE_GATES + kingdom entrance gate +
    (moon-pipe) rock-reach capture + (moon-pipe) peace function.
  * interior mouth cost = the reach-the-exit interior requirement:
    SUBAREA_EXIT_GATES for the subarea, overridable per mouth via
    PORT_EXIT_GATE_OVERRIDES (multi-exit stages whose exits differ).
Door-side SCENARIO gates (the {CascadeDeparture()}-style member fragments)
need multiworld context and stay a P3d wiring concern — P3d must attach them
to overworld mouths the same way _apply_entrance_shuffle_door_rules does for
simple mode. They are intentionally NOT part of PortCost.

Switch/remap note for P3e
-------------------------
Entering mouth A fires GameDataFile::changeNextStage with
cur = A.stage, id = A.entry_id, dest = A's VANILLA partner's stage. Interior
mouths therefore key remap rows on (cur, from_id) — exactly P2's compound
exit key. Overworld mouths key on (dest, id); P2 added `from_id` to every
row/slot but only wired id-matching into the EXIT lookup branch — P3e must
verify the ENTRY branch also consults from_id (needed once multi-door
subareas can point their doors at different partners) and extend it if not.
That is a small, additive switch-mod change on the P2 seam.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

try:  # package import (bundled .apworld / generation)
    from .entrance_logic import (
        SUBAREA_ENTRANCE_GATES,
        SUBAREA_EXIT_GATES,
        MOON_ROCK_REACH_CAPTURE,
        MOON_PIPE_PEACE_FUNCS,
        get_kingdom_entrance_gate,
        kingdom_prefix_from_name,
        build_entrance_pool,
        _and_join,
    )
except ImportError:  # loose import (test suite, sys.path = package dir)
    from entrance_logic import (  # type: ignore
        SUBAREA_ENTRANCE_GATES,
        SUBAREA_EXIT_GATES,
        MOON_ROCK_REACH_CAPTURE,
        MOON_PIPE_PEACE_FUNCS,
        get_kingdom_entrance_gate,
        kingdom_prefix_from_name,
        build_entrance_pool,
        _and_join,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# D5: overworld exclusions (door-wise, see module docstring)
# ---------------------------------------------------------------------------

# Kingdom display names exactly as entrance_stages.json spells them.
DECOUPLED_EXCLUDED_KINGDOMS: frozenset[str] = frozenset({
    "Moon Kingdom",   # endgame overworld — D6: permanently out
    "Dark Side",      # post-game, Moon-coupled
    "Darker Side",    # post-game, Moon-coupled
})

# Under goal=festival the post-Metro regions are emptied
# (SMOWorld.FESTIVAL_REGIONS_TO_EMPTY) — their door-mouths leave the pool
# too (design doc D5, festival note). Mushroom is post-Metro content as well
# (its checks are festival-dropped), so it joins the festival exclusion even
# though it is IN the pool under the mushroom_kingdom goal (D9).
# test_port_graph cross-checks this against __init__.py's tuple.
FESTIVAL_EXCLUDED_KINGDOMS: frozenset[str] = frozenset({
    "Snow Kingdom", "Seaside Kingdom", "Luncheon Kingdom", "Ruined Kingdom",
    "Bowser's Kingdom", "Moon Kingdom", "Mushroom Kingdom",
    "Dark Side", "Darker Side",
})

# Authored per-mouth interior exit-gate overrides for multi-exit stages whose
# exits have DIFFERENT reach costs (none known yet; the P1 data made the
# slots visible). Key: mouth_id (see Mouth.mouth_id). Value: requires string.
PORT_EXIT_GATE_OVERRIDES: dict[str, str] = {}

OVERWORLD = "overworld"
INTERIOR = "interior"


@dataclass(frozen=True)
class Mouth:
    """One walkable/spawnable opening. See module docstring for the model."""
    door_port_id: str        # P1 port id of the physical door (pair-level id)
    side: str                # OVERWORLD | INTERIOR
    stage: str               # stage this mouth physically lives in
    entry_id: str            # spawn/transition marker (ChangeStageId)
    subarea: str             # owning subarea display name (record key)
    kingdom: str             # kingdom display name (record's `kingdom`)
    ingest: bool             # Mario can walk into this opening

    @property
    def mouth_id(self) -> str:
        return f"{self.door_port_id}@{self.side}"

    @property
    def sound(self) -> bool:
        return bool(self.stage and self.entry_id)


@dataclass(frozen=True)
class PortCost:
    """Item/peace cost to use a mouth from its own side (scenario fragments
    are attached in P3d — see module docstring)."""
    requires: str            # full-evaluator requires string; '' = free
    peace_func: str | None   # hooks/Rules peace fn name (moon-pipe doors)


@dataclass
class PortGraph:
    """The enumerated mouth pool + vanilla matching."""
    mouths: dict[str, Mouth]                  # mouth_id -> Mouth (ingest pool)
    vanilla_matching: dict[str, str]          # mouth_id -> mouth_id involution
    dropped_doors: list[str]                  # port_ids dropped w/ reasons logged

    def ingest_mouths(self) -> list[Mouth]:
        return list(self.mouths.values())


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

def _door_ids_in(items: Iterable[dict]) -> set[str]:
    return {it.get("port_id", "") for it in items if it.get("port_id")}


def build_port_graph(
    entrance_stages: dict,
    subareas: dict,
    exclusions: dict,
    *,
    festival: bool = False,
) -> PortGraph:
    """Enumerate the decoupled matching pool from schema-v2 entrance data.

    Base subarea set = build_entrance_pool (same story-critical exclusions +
    round-trippability as simple mode), then D5/festival kingdom exclusions
    applied DOOR-WISE, then per-door soundness (a door with any unsound mouth
    drops whole — the Sand→Bowser one-way-warp rule at door granularity).
    """
    schema = entrance_stages.get("_schema_version", 1) \
        if isinstance(entrance_stages, dict) else 1
    if schema < 2:
        raise ValueError(
            "port_graph requires entrance_stages.json schema v2 (P1 output); "
            f"got schema {schema}. Re-run scripts/extract_entrance_stages.py."
        )

    excluded_kingdoms = set(DECOUPLED_EXCLUDED_KINGDOMS)
    if festival:
        excluded_kingdoms |= FESTIVAL_EXCLUDED_KINGDOMS

    pool = build_entrance_pool(subareas, exclusions, entrance_stages)

    mouths: dict[str, Mouth] = {}
    vanilla: dict[str, str] = {}
    dropped: list[str] = []

    for name in pool:
        rec = entrance_stages.get(name)
        if not rec:
            continue
        kingdom = rec.get("kingdom", "")
        if kingdom in excluded_kingdoms:
            # Door-wise exclusion: the whole subarea's doors stay vanilla.
            dropped.extend(sorted(_door_ids_in(rec.get("entries", []))
                                  | _door_ids_in(rec.get("exits", []))))
            continue
        stage = rec.get("stage", "")
        door_mouths: dict = rec.get("door_mouths", {}) or {}
        entry_ids = _door_ids_in(rec.get("entries", []))
        exit_ids = _door_ids_in(rec.get("exits", []))

        rec_pairs: list[tuple[Mouth, Mouth]] = []
        for port_id, dm in sorted(door_mouths.items()):
            ow = Mouth(
                door_port_id=port_id, side=OVERWORLD,
                stage=dm.get("stage", ""), entry_id=dm.get("entry_id", ""),
                subarea=name, kingdom=kingdom,
                ingest=(port_id in entry_ids),
            )
            # Interior marker id: the shared ChangeStageId of the pair.
            interior_marker = dm.get("entry_id", "")
            inn = Mouth(
                door_port_id=port_id, side=INTERIOR,
                stage=stage, entry_id=interior_marker,
                subarea=name, kingdom=kingdom,
                ingest=(port_id in exit_ids),
            )
            # Door-level soundness: any unsound mouth drops the whole door.
            if not (ow.sound and inn.sound):
                dropped.append(port_id)
                logger.warning(
                    "port_graph: dropping unsound door %s (subarea '%s')",
                    port_id, name)
                continue
            rec_pairs.append((ow, inn))

        # One-way-ENTRY subarea rule (see module docstring): no walkable
        # interior exit => every door stays vanilla or the interior strands.
        if not any(inn.ingest for _, inn in rec_pairs):
            oneway = sorted({ow.door_port_id for ow, inn in rec_pairs
                             if ow.ingest or inn.ingest})
            if oneway:
                dropped.extend(oneway)
                logger.info(
                    "port_graph: subarea '%s' has no walkable interior exit; "
                    "%d entry door(s) stay vanilla", name, len(oneway))
            continue

        for ow, inn in rec_pairs:
            for m in (ow, inn):
                if m.ingest:
                    mouths[m.mouth_id] = m
            # Vanilla involution over the ingest subset of this door.
            if ow.ingest and inn.ingest:
                vanilla[ow.mouth_id] = inn.mouth_id
                vanilla[inn.mouth_id] = ow.mouth_id
            elif ow.ingest or inn.ingest:
                # One walkable end: it maps to the other end's MARKER in
                # vanilla, but the pair is not symmetric — the lone ingest
                # mouth still enters the pool (P0's PBP-pipe shape); vanilla
                # matching just leaves it fixed-point-free-less, recorded as
                # self-mapped for involution bookkeeping.
                lone = ow if ow.ingest else inn
                vanilla[lone.mouth_id] = lone.mouth_id

    return PortGraph(mouths=mouths, vanilla_matching=vanilla,
                     dropped_doors=dropped)


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

def mouth_cost(mouth: Mouth, moonpipe_subareas: frozenset[str]) -> PortCost:
    """Item/peace cost to use `mouth` from its own side (see module doc)."""
    if mouth.side == INTERIOR:
        req = PORT_EXIT_GATE_OVERRIDES.get(
            mouth.mouth_id, SUBAREA_EXIT_GATES.get(mouth.subarea, ""))
        return PortCost(requires=req, peace_func=None)

    parts: list[str] = []
    prefix = kingdom_prefix_from_name(mouth.kingdom)
    kg = get_kingdom_entrance_gate(prefix)
    if kg:
        parts.append(kg)
    sg = SUBAREA_ENTRANCE_GATES.get(mouth.subarea, "")
    if sg:
        parts.append(sg)
    peace_func: str | None = None
    if mouth.subarea in moonpipe_subareas:
        reach = MOON_ROCK_REACH_CAPTURE.get(prefix, "")
        if reach:
            parts.append(reach)
        peace_func = MOON_PIPE_PEACE_FUNCS.get(prefix) or None
    return PortCost(requires=_and_join(parts), peace_func=peace_func)


def make_mouth_access_rule(
    mouth: Mouth,
    moonpipe_subareas: frozenset[str],
    scenario_gates: dict,
    subareas: dict,
    world: "World",          # noqa: F821 — AP types, lazy (see module docstring)
    multiworld: "MultiWorld",  # noqa: F821
    player: int,
):
    """Return lambda(state)->bool for traversing a matched edge FROM `mouth`'s
    side (P3d). Composes mouth_cost's item/peace parts with, for OVERWORLD
    mouths only, the door-side scenario fragments (OR over the door subarea's
    member moons — the same composition _apply_entrance_shuffle_door_rules
    uses in simple mode, e.g. {CascadeDeparture()} on the Mysterious Clouds
    door). INTERIOR mouths carry only their own exit cost: the partner door
    must NOT re-AND it (the double-application trap — simple's
    make_door_access_rule ANDs SUBAREA_EXIT_GATES onto the door because there
    the door rule is the only place to put it; under decoupled the exit gate
    rides this interior mouth's own outgoing edge instead).

    AP objects are only touched lazily inside the returned closure; this
    factory itself is generation-time only (hooks/World.py), never imported
    by the pure test layer."""
    from .entrance_logic import (
        evaluate_full_requires,
        make_door_scenario_gate_rule,
    )
    from .hooks import Rules as HookRules

    cost = mouth_cost(mouth, moonpipe_subareas)
    checks: list = []
    if cost.requires:
        checks.append(
            lambda state, r=cost.requires, w=world, mw=multiworld, p=player:
                evaluate_full_requires(state, r, w, mw, p))
    if cost.peace_func:
        peace_fn = getattr(HookRules, cost.peace_func, None)
        if callable(peace_fn):
            checks.append(
                lambda state, f=peace_fn, w=world, mw=multiworld, p=player:
                    f(w, mw, state, p))
    if mouth.side == OVERWORLD:
        members = subareas.get(mouth.subarea, {}).get("location_names", [])
        fragments = [scenario_gates.get(ln, "") for ln in members]
        if any(fragments):
            checks.append(make_door_scenario_gate_rule(
                fragments, world, multiworld, player))

    if not checks:
        return lambda state: True

    def combined(state, _checks: list = checks) -> bool:
        return all(c(state) for c in _checks)

    return combined


# ---------------------------------------------------------------------------
# Matching helpers (consumed by P3c and the test suite)
# ---------------------------------------------------------------------------

def is_involution(matching: dict[str, str], mouths: dict[str, Mouth]) -> bool:
    """True iff `matching` is a self-inverse total map over `mouths`."""
    if set(matching) != set(mouths):
        return False
    return all(matching.get(matching[m]) == m for m in matching)


def estimate_remap_rows(matching: dict[str, str],
                        vanilla_matching: dict[str, str]) -> int:
    """One rewrite row per mouth whose assignment DEVIATES FROM VANILLA
    (P3e shape). Vanilla is the cross-pairing of each door's own two mouths,
    not the identity map — a mouth matched to its own door's other mouth
    needs no row. Compare the result against the Switch table cap
    (kEntranceRemapMax, 512 as of P2)."""
    return sum(1 for a, b in matching.items()
               if vanilla_matching.get(a) != b)
