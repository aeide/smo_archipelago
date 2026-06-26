"""
entrance_logic.py — P7 entrance shuffle helpers.

Provides gate constants and compile helpers for the entrance shuffle option.
Imported by hooks/World.py; has no AP imports so it's usable by the test suite
directly.

Design notes
------------
* SUBAREA_ENTRANCE_GATES / KINGDOM_ENTRANCE_GATES mirror
  compile_moon_logic.SUBAREA_GATES / KINGDOM_GATES — they describe item
  requirements for the DOOR to a subarea, not its interior.
* compile_interior_requires(record) mirrors compile_moon() from
  compile_moon_logic.py, producing a requires string with NO gates — only the
  move-set methods.  Gates go on the Entrance access-rule lambda.
* evaluate_interior_requires() is a simplified requires-string evaluator for
  |item:count| tokens and AND/OR/parens.  Interior-only requires strings never
  contain {FunctionName()} calls (added by gates_for() in the compile script,
  not by compile_moon()), so the simplified evaluator suffices.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from BaseClasses import CollectionState, MultiWorld
    from worlds.AutoWorld import World

_DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# Boolean expression helpers (defined first — used by gate constants below)
# ---------------------------------------------------------------------------

def _and_join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " and ".join(parts) + ")"


def _or_join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " or ".join(parts) + ")"


# ---------------------------------------------------------------------------
# Item fragment tables (mirror compile_moon_logic.py)
# ---------------------------------------------------------------------------

JUMP_FRAG: dict[str, str] = {
    "PJ1":        "|Progressive Jump:1|",
    "PJ2":        "|Progressive Jump:2|",
    "CAP_BOUNCE": "|Cap Bounce|",
    "BACKFLIP":   "(|Backflip| and |Progressive Crouch:1|)",
    "SIDE_FLIP":  "|Side Flip|",
    "GPJ":        "(|Ground Pound Jump| and |Progressive Ground Pound:1|)",
    "LONG_JUMP":  "(|Long Jump| and |Progressive Crouch:1|)",
}

HEIGHT_SATISFIERS: dict[str, list[str]] = {
    "double":     ["PJ1", "CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
    "cap_return": ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
    "backflip":   ["CAP_BOUNCE", "BACKFLIP", "SIDE_FLIP", "GPJ", "PJ2"],
    "gpj":        ["GPJ", "PJ2"],
    "triple":     ["PJ2"],
}

THROW_FRAG: dict[str, str] = {
    "up": "|Up Throw|", "down": "|Down Throw|", "spin": "|Spin Throw|",
}

OTHER_FRAG: dict[str, str | None] = {
    "ground_pound": "|Progressive Ground Pound:1|",
    "dive":         "|Progressive Ground Pound:2|",
    "crouch":       "|Progressive Crouch:1|",
    "roll":         "|Progressive Crouch:2|",
    "roll_boost":   "|Progressive Crouch:3|",
    "wall_slide":   "|Wall Slide|",
    "climb":        "|Climb|",
    "cap_bounce":   "|Cap Bounce|",
    "bonk_roll":    "|Progressive Crouch:2|",
    "single":       None,
}

FREE_CAPTURES = frozenset({"Frog", "Chain Chomp"})

# ---------------------------------------------------------------------------
# Gate constants (depend on helpers — defined after them)
# ---------------------------------------------------------------------------

_HIGH_JUMP = _or_join([
    JUMP_FRAG["BACKFLIP"], JUMP_FRAG["SIDE_FLIP"],
    JUMP_FRAG["PJ2"], JUMP_FRAG["GPJ"],
])

_LAKE_GATE = _or_join([
    "|Zipper|",
    _and_join([_HIGH_JUMP, "|Cap Bounce|",
               _or_join(["|Progressive Ground Pound:2|", "|Wall Slide|"])]),
])

_NARROW_VALLEY_GATE = _or_join([
    "|Gushen|",
    _and_join([JUMP_FRAG["PJ2"], "|Wall Slide|", "|Cap Bounce|"]),
])

# Kingdom prefix → entry-gate requires string (overworld traversal prereq).
# Matches compile_moon_logic.KINGDOM_GATES.  Lake is included here by name.
KINGDOM_ENTRANCE_GATES: dict[str, str] = {
    "Metro":    "|Spark pylon|",
    "Bowser's": "|Spark pylon|",
    "Lake":     _LAKE_GATE,
}

# Subarea name → entry-gate requires string.
# Mirrors compile_moon_logic.SUBAREA_GATES.  Sewers is included (it's excluded
# from the pool via entrance_exclusions.json, but listed here for completeness).
SUBAREA_ENTRANCE_GATES: dict[str, str] = {
    "Unzipping the Chasm":              "|Zipper|",
    "Sewers":                           "|Manhole|",
    "Rotating Maze Shards":             "|Manhole|",
    "Swinging Along the High-Rises":    "|Mini Rocket|",
    "A Sea of Clouds":                  "|Mini Rocket|",
    "Strange Neighborhood":             "|Mini Rocket|",
    "Shards in the Fog":                "|Mini Rocket|",
    "Picture Match (Mario)":            "|Mini Rocket|",
    "Roulette Tower":                   "|Mini Rocket|",
    "Shards Under Siege":               "|Taxi|",
    "Flying Through the Narrow Valley": _NARROW_VALLEY_GATE,
    "Fork-Flickin to the Summit":       "|Lava Bubble|",
    "Shards in the Cheese Rocks":       "|Hammer Bro|",
    "Spinning Athletics":               "|Lava Bubble|",
}

# Subarea name → EXIT-gate requires string: the item(s) needed to LEAVE the
# interior, independent of which door you came in through. Most subareas exit
# for free (a return pipe/door drops you back), so they're absent here. The
# mini-rocket sky subareas are the exception Devon flagged: the ONLY way out is
# to re-board the Mini Rocket inside, so reaching one of these interiors via a
# DIFFERENT (shuffled) door still strands Mario without |Mini Rocket|.
#
# Only consulted on the entrance-shuffle ON path (make_door_access_rule ANDs it
# onto the door→interior rule). Shuffle OFF needs no exit table: there the door
# is the identity (interior == its own door), whose ENTRY gate already equals the
# exit gate, so the baked moon `requires` (= entry gate) covers leaving for free.
# Keys MUST stay a subset of SUBAREA_ENTRANCE_GATES (an exit-gated subarea is by
# definition also entry-gated by the same capture); guarded by the test suite.
SUBAREA_EXIT_GATES: dict[str, str] = {
    "Swinging Along the High-Rises":    "|Mini Rocket|",
    "A Sea of Clouds":                  "|Mini Rocket|",
    "Strange Neighborhood":             "|Mini Rocket|",
    "Shards in the Fog":                "|Mini Rocket|",
    "Picture Match (Mario)":            "|Mini Rocket|",
    "Roulette Tower":                   "|Mini Rocket|",
}

# Subarea name → INTERIOR-INTRINSIC FULL entry gate. Unlike SUBAREA_ENTRANCE_GATES
# (item-only) and the {Func()}-only interior scenario gates, this is a complete
# requires string that may MIX {Func(args)} predicate calls with |item| tokens under
# AND/OR — the only place such a gate can live. It's the subarea's own "what it takes
# to enter/do this subarea" condition, intrinsic to the INTERIOR, so it's keyed on the
# interior you land in (like SUBAREA_EXIT_GATES) and applies no matter which shuffled
# door now leads in. The interior moons themselves stay free (no move-set). Mirrors
# compile_moon_logic.SUBAREA_INTERIOR_FULL_GATES, which bakes the identical string into
# each member moon's locations.json `requires` for the entrance-shuffle OFF path.
SUBAREA_INTERIOR_FULL_GATES: dict[str, str] = {
    # Jaxi Driving: Sand world peace OR the move-set to reach it the hard way.
    "Jaxi Driving":
        "({SandPeace()} or (|Bullet Bill| and |Progressive Ground Pound:2| and |Wall Slide|))",
}

# Kingdom prefix → peace-function name (from hooks/Rules.py).
# Cap, Cloud, Lost omitted — their peace = kingdom reachability; no extra gate.
MOON_PIPE_PEACE_FUNCS: dict[str, str] = {
    "Cascade":  "CascadePeace",
    "Sand":     "SandPeace",
    "Lake":     "LakePeace",
    "Wooded":   "WoodedPeace",
    "Metro":    "MetroPeace",
    "Snow":     "SnowPeace",
    "Seaside":  "SeasidePeace",
    "Luncheon": "LuncheonPeace",
    "Ruined":   "RuinedPeace",
    "Bowser's": "BowserPeace",
}


def get_kingdom_entrance_gate(kingdom_prefix: str) -> str:
    """Return the kingdom entrance gate requires string, or '' if none."""
    return KINGDOM_ENTRANCE_GATES.get(kingdom_prefix, "")


def kingdom_prefix_from_name(kingdom_name: str) -> str:
    """Convert a full kingdom name to the prefix used in KINGDOM_ENTRANCE_GATES."""
    if kingdom_name == "Bowser's Kingdom":
        return "Bowser's"
    # Night Metro counts as Metro for gate purposes.
    if kingdom_name == "Night Metro":
        return "Metro"
    return kingdom_name.removesuffix(" Kingdom").strip()


# ---------------------------------------------------------------------------
# Interior-only requires compiler (mirrors compile_moon() from
# compile_moon_logic.py, WITHOUT the gates_for() additions)
# ---------------------------------------------------------------------------

def _capture_term(groups: list[list[str]]) -> str | None:
    if not groups:
        return None
    or_parts: list[str] = []
    for g in groups:
        items = [c for c in g if c not in FREE_CAPTURES]
        if not items:
            return None  # whole group is free
        or_parts.append(_and_join([f"|{c}|" for c in items]))
    return _or_join(or_parts)


def _compile_method(m: dict, groups: list[list[str]]) -> str:
    terms: list[str] = []
    jh = m.get("jump_height")
    if jh == "long_jump":
        terms.append(JUMP_FRAG["LONG_JUMP"])
    elif jh in HEIGHT_SATISFIERS:
        terms.append(_or_join([JUMP_FRAG[k] for k in HEIGHT_SATISFIERS[jh]]))
    throws = m.get("cap_throws", [])
    if throws and not ({"neutral", "none"} & set(throws)):
        terms.append(_or_join([THROW_FRAG[t] for t in throws if t in THROW_FRAG]))
    for o in m.get("other_required", []):
        if o == "capture":
            ct = _capture_term(groups)
            if ct is not None:
                terms.append(ct)
        else:
            frag = OTHER_FRAG.get(o)
            if frag is not None:
                terms.append(frag)
    return _and_join(terms)


def compile_interior_requires(record: dict) -> str:
    """Compile a moon record to its interior-only requires string (no gates).

    Mirrors compile_moon_logic.compile_moon() exactly; returns only the
    move-set requirement without any kingdom gate, subarea gate, or peace gate.
    """
    methods = [v for v in record["methods"].values() if v is not None]
    groups = record["capture_groups"]
    method_exprs: list[str] = []
    for m in methods:
        e = _compile_method(m, groups)
        if e not in method_exprs:
            method_exprs.append(e)
    if any(e == "" for e in method_exprs):
        return ""  # at least one fully-baseline method → free
    return _or_join(method_exprs)


def load_data_json(filename: str) -> dict:
    """Load data/<filename> as JSON, zip-safe (bundled .apworld OR loose source).

    pathlib cannot traverse into an .apworld zip — the inner path
    (``…/meatballs.apworld/meatballs/data/<file>``) looks like a real FS path and
    raises FileNotFoundError. So generation-time data loads must go through
    importlib.resources. Falls back to the source-tree filesystem for the test
    suite (where ``__package__`` may be empty). Mirrors load_entrance_stages but
    re-raises FileNotFoundError so a genuinely-missing required file is loud.
    """
    try:
        from importlib.resources import files
        text = (
            files(__package__).joinpath("data", filename).read_text(encoding="utf-8")
        )
        return json.loads(text)
    except FileNotFoundError:
        raise
    except Exception:
        pass
    return json.loads((_DATA_DIR / filename).read_text(encoding="utf-8"))


def build_interior_requires_map(
    location_table: list[dict],
    requirements_path: Path | None = None,
) -> dict[str, str]:
    """Build {location_name: interior_req_str} for every location that has a
    record in moon_requirements.json.  Locations absent from requirements get
    "" (free).
    """
    try:
        if requirements_path is not None:
            requirements: dict = json.loads(
                requirements_path.read_text(encoding="utf-8"))
        else:
            requirements = load_data_json("moon_requirements.json")
    except FileNotFoundError:
        return {}

    loc_to_record: dict[str, dict] = {}
    for rec in requirements.values():
        ln = rec.get("location_name")
        if ln:
            loc_to_record[ln] = rec

    result: dict[str, str] = {}
    for loc in location_table:
        name = loc["name"]
        rec = loc_to_record.get(name)
        result[name] = compile_interior_requires(rec) if rec is not None else ""
    return result


# ---------------------------------------------------------------------------
# Pool helpers
# ---------------------------------------------------------------------------

def is_round_trippable(name: str, entrance_stages: dict) -> bool:
    """True if `name` can be a sound shuffle endpoint: it must be present in
    entrance_stages.json with a `stage` and a `primary_entry.entry_id`.

    Rationale (load-bearing — see the Sand→Bowser one-way-warp bug): the bijection
    is a permutation over the pool, so EVERY pooled subarea is both some door's
    interior and some interior's door. compile_stage_remaps drops BOTH rows of a
    pair when a subarea is missing from entrance_stages (`if not …_rec: continue`),
    but the partner pairs that map TO/FROM it via resolvable data still install
    one-way couplings — Mario reaches the unresolved subarea's stage the vanilla
    way (its own door reverted to vanilla) yet exits via a foreign door's coupling,
    stranding him in the wrong kingdom. The fix is to never let such a subarea into
    the pool in the first place. `primary_entry.entry_id` is the inbound key
    compile_stage_remaps needs to redirect INTO the subarea; without it the entry
    row drops and the same asymmetry appears. (`primary_exit` is intentionally NOT
    required: pipe-less interiors — e.g. boss re-fight arenas — exit via the
    game's return stack (returnPrevStage / :return), which is correct for free and
    needs no exit row.)
    """
    rec = entrance_stages.get(name)
    if not rec:
        return False
    if not rec.get("stage"):
        return False
    return bool((rec.get("primary_entry") or {}).get("entry_id"))


def build_entrance_pool(
    subareas: dict,
    exclusions: dict,
    entrance_stages: dict | None = None,
) -> list[str]:
    """Return the sorted list of in-pool subarea names.

    `subareas`        — parsed subareas.json (keys = subarea names).
    `exclusions`      — parsed entrance_exclusions.json (nested kingdom→{name→…}).
    `entrance_stages` — parsed entrance_stages.json. When provided, subareas that
                        are NOT round-trippable (see is_round_trippable) are
                        dropped from the pool and logged, so a stale/renamed/merged
                        entrance_stages can never poison the bijection with a
                        one-way warp. When None, no stage filter is applied
                        (back-compat for pure data-shape tests).
    """
    excluded: set[str] = set()
    for kingdom_exc in exclusions.values():
        for name in kingdom_exc:
            excluded.add(name)
    candidates = [name for name in subareas if name not in excluded]
    if entrance_stages is None:
        return sorted(candidates)

    pool = [n for n in candidates if is_round_trippable(n, entrance_stages)]
    dropped = sorted(set(candidates) - set(pool))
    if dropped:
        import logging
        logging.getLogger(__name__).warning(
            "entrance_shuffle: dropping %d non-round-trippable subarea(s) from the "
            "pool (absent from entrance_stages.json or missing primary_entry): %s",
            len(dropped), ", ".join(dropped),
        )
    return sorted(pool)


# ---------------------------------------------------------------------------
# P7 Step 4 — stage-level remap resolution (apworld -> Switch)
# ---------------------------------------------------------------------------
# The Switch hook (EntranceShuffleHook) operates on raw SMO stage names, not AP
# subarea display names. The bridge therefore resolves the slot_data bijection
# {door_subarea: interior_subarea} into stage-level quads via
# data/entrance_stages.json before shipping them in EntranceMapMsg. Keeping the
# resolution here (a pure dict transform, no AP imports) lets switch_server call
# it and lets the test suite exercise it directly.

def load_entrance_stages() -> dict:
    """Load data/entrance_stages.json, zip-safe (bundled apworld OR loose source).

    Tries importlib.resources against this module's own package first (works
    inside the .apworld zip where Path() can't reach virtual entries), then
    falls back to the filesystem for dev / test runs from the source tree.
    Returns {} if the table is unavailable.
    """
    try:
        from importlib.resources import files
        text = (
            files(__package__).joinpath("data", "entrance_stages.json")
            .read_text(encoding="utf-8")
        )
        return json.loads(text)
    except Exception:
        pass
    try:
        return json.loads(
            (_DATA_DIR / "entrance_stages.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return {}


def compile_stage_remaps(
    bijection: dict[str, str],
    entrance_stages: dict,
) -> list[dict]:
    """Resolve a {door_subarea: interior_subarea} bijection into Switch-bound
    stage-level remap rows, BOTH directions.

    For a coupled bijection the return target is a pure function of the
    permutation, so exits are precomputed here exactly like entries — no
    runtime origin tracking on the Switch (see docs/p7-step4-return-design.md).
    Each shuffled pair (door D, interior I = σ(D)) emits TWO rows, tagged with
    a `kind` discriminator so the Switch knows which key to match on:

        # ENTRY — fires when you walk through the door that vanilla leads to D;
        #         matched against the inbound dest stage (D.stage is unique).
        {"kind": "entry", "from": D.stage,
         "to_stage": I.stage,            "to_id": I.primary_entry.entry_id}

        # EXIT  — fires when you LEAVE interior I; matched against the CURRENT
        #         stage (I.stage), NOT the dest, because the vanilla exit dest
        #         is the shared kingdom overworld and can't disambiguate which
        #         interior you're in. Rewrites to door D's exterior coordinate.
        {"kind": "exit",  "from": I.stage,
         "to_stage": D.primary_exit.dest, "to_id": D.primary_exit.entry_id}

    Identity pairs (σ(D) == D) are skipped — both rows would rewrite a vanilla
    transition to itself. `entrance_stages` is parsed data/entrance_stages.json,
    keyed by subarea display name. A pair is skipped (stays vanilla) when either
    subarea is missing from the table, or the needed primary_entry / primary_exit
    fields are absent; the entry row can land even if the exit row can't (a
    missing primary_exit drops only the exit half). Callers can diff the
    entry-row count against the non-identity pair count to surface drift.
    """
    rows: list[dict] = []
    for door, interior in bijection.items():
        if door == interior:
            continue  # identity — both rows would be vanilla no-ops
        door_rec = entrance_stages.get(door)
        int_rec = entrance_stages.get(interior)
        if not door_rec or not int_rec:
            continue
        door_stage = door_rec.get("stage")
        int_stage = int_rec.get("stage")
        primary_entry = int_rec.get("primary_entry") or {}
        entry_id = primary_entry.get("entry_id")
        # ENTRY row — needs the door's stage (match key) + the interior's stage
        # and arrival id (rewrite target).
        if door_stage and int_stage and entry_id:
            rows.append({"kind": "entry", "from": door_stage,
                         "to_stage": int_stage, "to_id": entry_id})
        # EXIT row — keyed on the interior's stage (cur at exit time); rewrites
        # to the ORIGIN door's exterior. Independent of the entry row landing.
        door_exit = door_rec.get("primary_exit") or {}
        exit_dest = door_exit.get("dest")
        exit_id = door_exit.get("entry_id")
        if int_stage and exit_dest and exit_id:
            rows.append({"kind": "exit", "from": int_stage,
                         "to_stage": exit_dest, "to_id": exit_id})
    return rows


# ---------------------------------------------------------------------------
# Moon-pipe detection
# ---------------------------------------------------------------------------

def build_moonpipe_subarea_set(
    subareas: dict,
    location_table: list[dict],
) -> frozenset[str]:
    """Return the set of subarea names where ALL locations are Moon Rock checks.

    A Moon Rock location has "Moon Rock" in its category list.
    """
    moon_rock_names: frozenset[str] = frozenset(
        loc["name"]
        for loc in location_table
        if "Moon Rock" in loc.get("category", [])
    )
    result: set[str] = set()
    for sub_name, info in subareas.items():
        locs = info.get("location_names", [])
        if locs and all(ln in moon_rock_names for ln in locs):
            result.add(sub_name)
    return frozenset(result)


# ---------------------------------------------------------------------------
# Interior requires evaluator
# ---------------------------------------------------------------------------
# Interior-only requires strings contain only |item:count| tokens and boolean
# operators (AND/OR/parens).  No {FunctionName()} calls needed.

_ITEM_RE = re.compile(r'\|([^|]+)\|')


def evaluate_interior_requires(
    state: "CollectionState",
    req_str: str,
    world: "World",
    player: int,
) -> bool:
    """Evaluate a move-set requires string against the current collection state.

    Handles |item:count| and boolean AND/OR/parens.  Does NOT handle
    {FunctionName()} — interior-only strings never contain those.
    """
    from .Rules import infix_to_postfix, evaluate_postfix  # module-level fns

    if not req_str:
        return True

    result = req_str
    # Replace each |item:count| token with 1/0 based on collection state.
    # Iterate over all non-overlapping matches and replace left-to-right.
    offset = 0
    tokens = list(_ITEM_RE.finditer(req_str))
    parts: list[str] = []
    prev_end = 0
    for m in tokens:
        parts.append(result[prev_end:m.start()])
        item_str = m.group(1)
        segments = item_str.split(":")
        item_name = segments[0].strip()
        count = int(segments[1].strip()) if len(segments) > 1 else 1
        has = state.count(item_name, player) >= count
        parts.append("1" if has else "0")
        prev_end = m.end()
    parts.append(result[prev_end:])
    result = "".join(parts)

    result = re.sub(r'\s+and\s+', '&', result, flags=re.IGNORECASE)
    result = re.sub(r'\s+or\s+', '|', result, flags=re.IGNORECASE)
    result = result.strip()
    if not result:
        return True
    try:
        postfix = infix_to_postfix(result, "entrance_logic")
        return evaluate_postfix(postfix, "entrance_logic")
    except Exception:
        return True  # fail-open on malformed string


# ---------------------------------------------------------------------------
# Full requires evaluator ({Func()} + |item| + and/or)
# ---------------------------------------------------------------------------
# Used only for SUBAREA_INTERIOR_FULL_GATES, the one gate class that mixes
# {Func(args)} predicate calls with |item| tokens (e.g. "Sand peace OR the
# move-set"). evaluate_interior_requires is item-only and make_scenario_gate_rule
# is {Func}-only; neither can express the OR-of-mixed-types, so this composes both.

def evaluate_full_requires(
    state: "CollectionState",
    req_str: str,
    world: "World",
    multiworld: "MultiWorld",
    player: int,
) -> bool:
    """Evaluate a requires string that may mix {Func(args)} calls, |item:count|
    tokens, and AND/OR/parens. {Func()} calls resolve against hooks/Rules.py: a
    bool/None result substitutes 1/0; a string result (a requires sub-expression,
    e.g. KingdomMoons) is spliced in and re-parsed. Fail-open on any error."""
    if not req_str:
        return True
    from .hooks import Rules as HookRules

    expr = req_str
    # Resolve {Func(args)} left-to-right, iteratively: a spliced string result may
    # introduce further |item| tokens (handled below); our gates don't nest {Func()}.
    for _ in range(16):
        m = _FUNC_RE.search(expr)
        if not m:
            break
        name = m.group(1)
        arg = m.group(2).strip()
        args = [a.strip() for a in arg.split(",")] if arg else []
        fn = getattr(HookRules, name, None)
        if callable(fn):
            try:
                res = fn(world, multiworld, state, player, *args)
            except Exception:
                res = True  # fail-open
        else:
            res = True
        if isinstance(res, str):
            sub = f"({res})" if res else "1"
        else:
            sub = "1" if res else "0"
        expr = expr[:m.start()] + sub + expr[m.end():]
    # Remaining string: |item| tokens + 1/0 literals + and/or/parens.
    return evaluate_interior_requires(state, expr, world, player)


# ---------------------------------------------------------------------------
# Door access rule factory
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# D3 — subarea scenario gate rule factory (entrance-shuffle ON path)
# ---------------------------------------------------------------------------
# compile_moon_logic.py exports data/subarea_scenario_gates.json
# ({location_name: fragment}) for pooled-subarea moons. Under shuffle ON,
# _apply_entrance_shuffle_location_rules strips each moon's baked scenario gate
# (its rule is replaced by move-set-only interior requires), so World.py re-applies
# the exported fragment to the interior member location. Fragments are AND-joined
# {Func(args)} predicate calls only (e.g. "{SandPeace()}",
# "{canReachLocation(Sand: The Hole in the Desert)}"); they never contain |item|
# tokens (item gates ride the door entrance via make_door_access_rule) — so a tiny
# {Func()} dispatcher suffices, no need for the full Manual requires parser.

_FUNC_RE = re.compile(r'\{(\w+)\(([^)]*)\)\}')


def parse_scenario_fragment(fragment: str) -> list[tuple[str, list[str]]]:
    """Parse an AND-joined {Func(args)} scenario fragment into (func_name, args)
    pairs. Pure (no AP imports) so the test suite can exercise it directly. Args are
    comma-split and stripped; a no-arg call yields []."""
    out: list[tuple[str, list[str]]] = []
    for m in _FUNC_RE.finditer(fragment or ""):
        arg = m.group(2).strip()
        args = [a.strip() for a in arg.split(",")] if arg else []
        out.append((m.group(1), args))
    return out


def make_scenario_gate_rule(
    fragment: str,
    world: "World",
    multiworld: "MultiWorld",
    player: int,
) -> "Callable[[CollectionState], bool]":
    """Return lambda(state) -> bool for a scenario gate fragment. Functions resolve
    against hooks/Rules.py and are ANDed (scenario gates only ever AND). An empty or
    unresolvable fragment yields an always-True rule (fail-open).

    CRITICAL: a gate {Func()} may return EITHER a bool (peace gates, e.g.
    CascadePeace -> canReachLocation) OR a requires-EXPRESSION STRING (the
    KingdomMoons-based departure / re-arrival gates, e.g.
    CascadeDeparture() -> "|Cascade Kingdom Power Moon:6|"). A naive
    `all(fn(...))` treats that non-empty string as truthy, so a {CascadeDeparture()}
    gate silently becomes a no-op — the entrance-shuffle leak that let moons behind a
    post-departure door (and the Cascade Power Moons placed inside) be reached from
    sphere 0, making a 6-moon Cascade leave-gate satisfiable with moons that actually
    require leaving and returning. Route the whole fragment through
    evaluate_full_requires, which splices a string result back into the expression and
    evaluates its |item| tokens — so bool- and string-returning gates both work."""
    if not (fragment or "").strip():
        return lambda state: True
    return (lambda state, frag=fragment, w=world, mw=multiworld, p=player:
            evaluate_full_requires(state, frag, w, mw, p))


def make_door_scenario_gate_rule(
    member_fragments: list[str],
    world: "World",
    multiworld: "MultiWorld",
    player: int,
) -> "Callable[[CollectionState], bool]":
    """Return lambda(state)->bool gating a DOOR by its own subarea's intrinsic
    scenario reachability under entrance shuffle.

    Under shuffle a moon's interior scenario gate rides the moon (it moves with the
    interior region — see World._apply_subarea_scenario_gates). But the physical DOOR
    that moon now sits behind has its OWN overworld reachability: in vanilla a door
    only exists once that DOOR-subarea's quest state is met (e.g. Cascade's
    "Mysterious Clouds" door appears only post-departure, {CascadeDeparture()}). That
    door-side gate is NOT the interior's gate and was previously dropped under shuffle,
    letting a moon behind a late door be reached as early as its (unrelated) interior
    gate allowed — e.g. the Chain Chomp moons (interior {CascadePeace()}, satisfiable
    sphere 1) landing in sphere 1 behind the {CascadeDeparture()} Mysterious Clouds
    door (8 Cascade moons).

    `member_fragments` is the door subarea's per-member scenario fragments (one per
    door member moon; '' = that member is ungated). The door is reachable iff ANY
    member was reachable in vanilla — i.e. OR over members — so an ungated member
    collapses the whole rule to always-True (the door is gate-free). Each member
    fragment is itself an AND of {Func()} calls (delegated to make_scenario_gate_rule).
    An empty member list yields an always-True rule (no-op)."""
    member_rules = [
        make_scenario_gate_rule(f, world, multiworld, player)
        for f in member_fragments
    ]
    if not member_rules:
        return lambda state: True

    def rule(state: "CollectionState", _rules=member_rules) -> bool:
        return any(r(state) for r in _rules)

    return rule


def make_door_access_rule(
    door_subarea: str,
    door_kingdom_name: str,
    is_moon_pipe: bool,
    world: "World",
    multiworld: "MultiWorld",
    player: int,
    interior_subarea: str | None = None,
) -> "Callable[[CollectionState], bool]":
    """Return a lambda(state) -> bool for a door's entrance access rule.

    Combines kingdom gate + subarea entrance gate + interior EXIT gate + (if
    moon-pipe) peace gate. All checks are evaluated lazily at fill/play time; no
    AP state is read here.

    `interior_subarea` is the subarea this door actually leads to under the
    entrance-shuffle bijection (may differ from `door_subarea`). When it has an
    entry in SUBAREA_EXIT_GATES — i.e. a mini-rocket sky subarea you can only
    leave by re-boarding the rocket — that exit requirement is ANDed in, so AP
    never treats the interior's moons as reachable when Mario couldn't escape.
    Defaults to `door_subarea` (the shuffle-OFF identity) when not supplied.
    """
    from .hooks import Rules as HookRules  # lazy to avoid circular at import

    if interior_subarea is None:
        interior_subarea = door_subarea

    checks: list[Callable] = []

    # Kingdom gate
    door_prefix = kingdom_prefix_from_name(door_kingdom_name)
    kg = get_kingdom_entrance_gate(door_prefix)
    if kg:
        checks.append(lambda state, r=kg, w=world, p=player:
                       evaluate_interior_requires(state, r, w, p))

    # Subarea entrance gate (the door you walk through)
    sg = SUBAREA_ENTRANCE_GATES.get(door_subarea, "")
    if sg:
        checks.append(lambda state, r=sg, w=world, p=player:
                       evaluate_interior_requires(state, r, w, p))

    # Interior exit gate (the subarea you land in). Independent of how you
    # entered — covers mini-rocket interiors reached via a non-rocket door.
    xg = SUBAREA_EXIT_GATES.get(interior_subarea, "")
    if xg:
        checks.append(lambda state, r=xg, w=world, p=player:
                       evaluate_interior_requires(state, r, w, p))

    # Interior-intrinsic FULL entry gate (the subarea you land in). A complete
    # {Func} OR |item| requires string — the subarea's own entry condition, keyed
    # on the interior so it rides the interior under shuffle regardless of which
    # door leads in. Member moons stay free; this is the only gate they get.
    fg = SUBAREA_INTERIOR_FULL_GATES.get(interior_subarea, "")
    if fg:
        checks.append(lambda state, r=fg, w=world, mw=multiworld, p=player:
                       evaluate_full_requires(state, r, w, mw, p))

    # Peace gate (moon-pipe door)
    if is_moon_pipe:
        peace_fn_name = MOON_PIPE_PEACE_FUNCS.get(door_prefix, "")
        if peace_fn_name:
            peace_fn = getattr(HookRules, peace_fn_name, None)
            if callable(peace_fn):
                checks.append(lambda state, f=peace_fn, w=world, mw=multiworld, p=player:
                               f(w, mw, state, p))

    if not checks:
        return lambda state: True

    def combined(state: "CollectionState", _checks: list = checks) -> bool:
        return all(c(state) for c in _checks)

    return combined
