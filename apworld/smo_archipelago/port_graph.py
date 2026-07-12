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

# Row-table budget (P2/P3c/P3e). Owned here (not port_matching.py) because
# compile_port_remaps (P3e) needs it and port_matching already imports FROM
# this module — defining it there and importing it back would be a circular
# import. port_matching.py re-exports these two names for its own callers/
# tests, unchanged. Keep in sync with kEntranceRemapMax in
# switch-mod/src/ap/ApState.hpp.
ROW_TABLE_CAP = 512
ROW_HEADROOM = 32

# P3c discovery 3 / P3e §4: a handful of overworld door mouths physically sit
# in a kingdom's placement ZONE (e.g. `LakeWorldTownZone`) rather than its
# HomeStage. `entrance_stages.json` records the zone as that mouth's own
# `stage` (correct for placing Mario there as a spawn TARGET), but it is
# UNVERIFIED whether `GameDataFunction::getCurrentStageName()` ever reports
# the zone name as `cur`/`dest` at transition-fire time, or always reports
# the parent HomeStage (compound same-scene load) — see
# CostumeDoorHook.cpp's confirmed finding that the Lake town-zone trampoline
# door (`DoorWarp`) is a SAME-STAGE warp (no real changeNextStage fires for
# it at all), which is suggestive but not conclusive for OTHER zone-hosted
# doors. Entries are added one confirmed walk at a time (docs/
# plan-decoupled-entrances.md §3e + P4 findings item 8): if a walk shows a
# zone name reaching the wire (a remap-APPLIED `to_stage`, or `cur`/`dest`
# reporting a zone), add `{"ZoneName": "ParentHomeStage"}` here — a pure data
# change, no code change — and compile_port_remaps will alias rewrite targets
# that land on that zone (the ENTRY row's `from`, via the subarea's own
# interior stage, is never a per-door zone value, so match keys need no
# aliasing in practice).
#
# CONFIRMED 2026-07-08 (Devon's walk, log Ryujinx_..._00-25-03): a rewrite
# target of `SkyWorldCastleZone` (Bowser's `jizo02` door mouth) loaded the
# ZONE as a standalone stage — castle geometry, no skybox/graphics preset,
# world id stuck on the origin kingdom (map showed Sand). Shipping the parent
# HomeStage instead is the fix; the entrance marker id resolves within the
# composite stage load. The remaining extracted zone roots (SkyWorldCastleZone
# was one of ~6; see plan doc §3e item 4) stay out until a walk lands on them.
#
# CONFIRMED 2026-07-08 (Devon's A3 walk, log jizo-check.txt): the match-key
# side needs NO aliasing. Standing inside SkyWorldCastleZone and firing the
# jizo01 door, `getCurrentStageName` reported `cur='SkyWorldHomeStage'` — the
# engine reports the parent HomeStage for zone-hosted transitions, never the
# zone name. So `cur`-keyed exit rows and `dest`-keyed entry rows both match
# on HomeStage names as shipped; ZONE_STAGE_ALIAS remains rewrite-target-only.
ZONE_STAGE_ALIAS: dict[str, str] = {
    "SkyWorldCastleZone": "SkyWorldHomeStage",
}


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
# One-way courses (Devon ruling 2026-07-08)
# ---------------------------------------------------------------------------
# "Subareas with a separate entrance and exit are often intended to move from
# the entrance to the exit and not the other way around — for logic purposes,
# assume you CANNOT reach the entrance door to a subarea from its exit door."
#
# Encoding. An INTERIOR mouth is ENTRY-CAPABLE when the same physical door is
# also a walkable entrance from the overworld — i.e. a pooled OVERWORLD mouth
# of the same subarea shares its `entry_id` (the pair-shared ChangeStageId).
# Matching on entry_id, not door_port_id, deliberately covers the zone-split
# doors (P3c discovery 3): their two halves carry different port_ids but the
# SAME ChangeStageId because they are one physical door recorded twice — a
# two-way room, not a course. Genuinely separate exits (Jaxi Driving's
# `run00return`/`arijigoku2` vs its `aaa` entry) share nothing and stay
# exit-only.
#
# Arriving INSIDE a subarea at an exit-only mouth therefore reaches (a) that
# subarea's exit-only mouths (the far end of the course — where multi-exit
# stages cluster their exit pipes) and (b) nothing else: not the entrance
# door, and NOT the member moons (the course flows entrance -> exit; granting
# moons from a far-end arrival would over-promise reachability the player
# does not have — under-promising only tightens fill, over-promising strands
# required checks in the real world). The P3d wiring realizes this as a
# second "<name> Interior (far side)" region per affected subarea with a free
# one-way edge full-interior -> far-side (completing the course reaches the
# far end) — see hooks/World.py.
#
# A subarea whose pooled interior mouths are ALL exit-only (a "one-way
# course") can then never feed its full interior through the matching — the
# only way in is its own vanilla entrance. roll_port_matching PINS such a
# subarea's pooled overworld mouths as fixed points (vanilla passthrough, the
# same credit shape the zone-split lone mouths use), keeping the member moons
# in logic; the exit mouths keep shuffling.

def entry_capable_interior_mouths(graph: PortGraph) -> frozenset[str]:
    """mouth_ids of pooled INTERIOR mouths whose door is also a walkable
    entrance (see the one-way-course note above)."""
    ow_ids_by_sub: dict[str, set[str]] = {}
    for m in graph.mouths.values():
        if m.side == OVERWORLD:
            ow_ids_by_sub.setdefault(m.subarea, set()).add(m.entry_id)
    return frozenset(
        m.mouth_id for m in graph.mouths.values()
        if m.side == INTERIOR
        and m.entry_id in ow_ids_by_sub.get(m.subarea, ()))


def one_way_course_subareas(graph: PortGraph) -> frozenset[str]:
    """Subareas with pooled interior mouths, NONE of them entry-capable —
    their full interior is unreachable through any shuffled matching and
    depends on the vanilla entrance staying pinned."""
    capable = entry_capable_interior_mouths(graph)
    has_interior: set[str] = set()
    has_capable: set[str] = set()
    for m in graph.mouths.values():
        if m.side != INTERIOR:
            continue
        has_interior.add(m.subarea)
        if m.mouth_id in capable:
            has_capable.add(m.subarea)
    return frozenset(has_interior - has_capable)


def pinned_one_way_entry_mouths(graph: PortGraph) -> frozenset[str]:
    """The overworld mouths roll_port_matching must fix vanilla: every pooled
    OVERWORLD mouth of a one-way-course subarea. By shape these are all lone
    (their door's interior side is not ingest — an ingest sibling would make
    the subarea entry-capable), so the fixed point is the true vanilla
    passthrough / zero-row shape."""
    courses = one_way_course_subareas(graph)
    return frozenset(
        m.mouth_id for m in graph.mouths.values()
        if m.side == OVERWORLD and m.subarea in courses)


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


# ---------------------------------------------------------------------------
# P3e — row compiler (matching -> Switch-bound remap rows)
# ---------------------------------------------------------------------------

def _subarea_interior_stage_map(graph: PortGraph) -> dict[str, str]:
    """subarea display name -> its interior stage, derived from any ingest
    INTERIOR mouth of that subarea (every door of one subarea shares the same
    interior `.stage`, so any one suffices). Every subarea contributing a
    pooled OVERWORLD mouth is guaranteed at least one ingest INTERIOR mouth
    too (the one-way-ENTRY subarea rule in build_port_graph), so this always
    resolves for a mouth's own subarea."""
    return {m.subarea: m.stage for m in graph.mouths.values()
            if m.side == INTERIOR}


def compile_port_remaps(matching: dict[str, str], graph: PortGraph) -> list[dict]:
    """Resolve a P3c port matching into Switch-bound remap rows (P3e), the
    per-mouth sibling of entrance_logic.compile_stage_remaps (coupled mode).

    One row per mouth whose assignment deviates from `graph.vanilla_matching`
    — same semantics as estimate_remap_rows, so
    `len(compile_port_remaps(m, g)) == estimate_remap_rows(m, g.vanilla_matching)`
    always holds. Vanilla-assigned mouths (including the roll's designated
    fixed point) emit nothing.

    For mouth A matched to B (matching[A] == B, arrival target = B's own
    stage + entry_id marker):

      * A is INTERIOR (an exit): `{"kind": "exit", "from": A.stage,
        "from_id": A.entry_id, "to_stage": B.stage, "to_id": B.entry_id}` —
        P2's compound exit key, exact-match tier.
      * A is OVERWORLD (a door): `{"kind": "entry", "from": <A's own
        subarea's interior stage — the vanilla dest when walking through A
        unmodified>, "from_id": A.entry_id, "to_stage": B.stage,
        "to_id": B.entry_id}`. `from_id` on an entry row is new for P3e —
        needed because two doors of the SAME subarea can now point at
        DIFFERENT partners, so `lookupEntranceRemap`'s entry tier must
        disambiguate by the transition's own id (see ApState.cpp).

    `to_stage`/`to_id` come straight from B's own Mouth fields regardless of
    B's side — walking into either mouth of a matched pair lands you at the
    OTHER mouth's own marker, symmetric by construction (the mouth model).
    `ZONE_STAGE_ALIAS` (data-driven, one confirmed walk at a time — see that
    constant's docstring; first entry landed 2026-07-08) is applied to any
    stage that comes from an OVERWORLD mouth's own per-door `.stage` field
    (i.e. `to_stage`/`to_id` when the target is an OVERWORLD mouth) — the one
    schema-v2 field never exercised by the already-validated coupled shuffle.

    A mouth id in `matching` that doesn't resolve against `graph.mouths`
    (client-side data drift between the slot_data matching and the local
    bundled entrance_stages.json) drops that row AND its reciprocal — never
    one end alone — logged loudly.

    Deterministically sorted. Raises RuntimeError if the row count exceeds
    the table budget (ROW_TABLE_CAP - ROW_HEADROOM) — the roller already
    asserts this at generation time (port_matching.roll_port_matching); this
    re-assert catches a client-side data drift (stale bundled
    entrance_stages.json) that could inflate/shrink the row set independent
    of the roll.
    """
    subarea_stage = _subarea_interior_stage_map(graph)
    rows: list[dict] = []
    dropped = 0
    for mouth_id, target_id in matching.items():
        if graph.vanilla_matching.get(mouth_id) == target_id:
            continue
        mouth = graph.mouths.get(mouth_id)
        target = graph.mouths.get(target_id)
        if mouth is None or target is None:
            dropped += 1
            continue

        to_stage = target.stage
        to_id = target.entry_id
        if target.side == OVERWORLD:
            to_stage = ZONE_STAGE_ALIAS.get(to_stage, to_stage)

        if mouth.side == INTERIOR:
            rows.append({
                "kind": "exit",
                "from": mouth.stage,
                "from_id": mouth.entry_id,
                "to_stage": to_stage,
                "to_id": to_id,
            })
        else:
            from_stage = subarea_stage.get(mouth.subarea)
            if not from_stage:
                logger.warning(
                    "compile_port_remaps: mouth %s's subarea '%s' has no "
                    "resolvable interior stage — dropping row (and its "
                    "reciprocal)", mouth_id, mouth.subarea)
                dropped += 1
                continue
            rows.append({
                "kind": "entry",
                "from": from_stage,
                "from_id": mouth.entry_id,
                "to_stage": to_stage,
                "to_id": to_id,
            })

    if dropped:
        logger.warning(
            "compile_port_remaps: dropped %d unresolvable mouth row(s) — "
            "client/server entrance_stages.json data drift?", dropped)

    rows.sort(key=lambda r: (
        r["kind"], r["from"], r.get("from_id", ""), r["to_stage"], r["to_id"]))

    budget = ROW_TABLE_CAP - ROW_HEADROOM
    if len(rows) > budget:
        raise RuntimeError(
            f"compile_port_remaps: {len(rows)} rewrite rows exceeds the "
            f"{budget} budget (kEntranceRemapMax {ROW_TABLE_CAP} - "
            f"{ROW_HEADROOM} headroom)")
    return rows
