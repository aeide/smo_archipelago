# Object classes from AP core, to represent an entire MultiWorld and this individual World that's part of it
from worlds.AutoWorld import World
from BaseClasses import ItemClassification, MultiWorld, Region, Entrance

# Item/Location subclasses extending AP core, used during generation
from ..Items import SMOItem
from ..Locations import SMOLocation

# Apworld data: game_table is the inlined dict in Data.py; the rest are loaded
# from data/items.json, data/locations.json, data/regions.json.
from ..Data import game_table, item_table, location_table, region_table

# These helper methods allow you to determine if an option has been set, or what its value is, for any player in the multiworld
from ..Helpers import is_location_enabled, is_option_enabled, get_option_value

# entrance_shuffle is a 3-value Choice (off/simple/decoupled) as of P2 — see
# _entrance_shuffle_mode below. OptionError is AP's standard "fail generation
# loudly with a player-facing message" exception (Options.OptionError).
from Options import OptionError
from .Options import EntranceShuffle, Goal

# P3d readiness flag: the decoupled region wiring below is implemented and
# test-exercised, but the mode stays generation-BLOCKED for players until P3e
# ships the slot_data/wire path — a decoupled seed today would be logically
# shuffled but physically vanilla on the Switch. Tests flip this module
# attribute to exercise the full wiring; YAMLs cannot reach it. Flip to True
# (and delete this comment) when P3e lands.
PORT_SHUFFLE_SHIPPABLE = False

# calling logging.info("message") anywhere below in this file will output the message to both console and log file
import logging
import json
from pathlib import Path


# Thresholds from KingdomMoons(K, N) clauses in data/regions.json. These are
# the per-kingdom effective-moon counts needed to leave that kingdom for the
# next, where each Multi-Moon = 3 effective and each Power Moon = 1. Mirrored
# here so after_create_items can demote surplus moons from progression to
# filler, freeing locations for toggle-driven location reductions to trim and
# giving the P3 junk_only locations enough filler to be fillable. The
# test_kingdom_moon_demotion sweep keeps this table in sync with regions.json.
KINGDOM_MOON_GATES = {
    "Cascade":  5,
    "Sand":    16,
    "Lake":     8,
    "Wooded":  16,
    "Lost":    10,
    "Metro":   20,
    "Snow":    10,
    "Seaside": 10,
    "Luncheon": 18,
    "Ruined":   3,
    "Bowser's": 8,
}

# Per-kingdom Moon-item-count cap, one Range option each. Mirrored to
# KINGDOM_MOON_GATES so every gated kingdom has a corresponding cap. The
# option floors (range_start in hooks/Options.py) are sized to leave the
# gate satisfiable under the MM-greedy trim strategy below; the option
# defaults (range_end == default) leave the pool identical to today.
# tests/test_kingdom_moon_count.py keeps the option floors/ends in sync
# with items.json and this table.
KINGDOM_MOON_COUNT_OPTIONS = {
    "Cascade":  "cascade_moon_count",
    "Sand":     "sand_moon_count",
    "Lake":     "lake_moon_count",
    "Wooded":   "wooded_moon_count",
    "Lost":     "lost_moon_count",
    "Metro":    "metro_moon_count",
    "Snow":     "snow_moon_count",
    "Seaside":  "seaside_moon_count",
    "Luncheon": "luncheon_moon_count",
    "Ruined":   "ruined_moon_count",
    "Bowser's": "bowsers_moon_count",
}

# Items dropped from the pool under the festival goal (Goal.option_festival).
# Post-Metro kingdoms are emptied of locations in create_regions, so their
# moon items have nowhere to land — adjust_filler_items would otherwise log
# "more items than locations" and start randomly trimming. The 15 captures
# below are exclusive to post-Metro kingdoms; the moon items cover every
# kingdom past Metro in the regions.json chain.
FESTIVAL_ITEMS_TO_DROP = frozenset({
    "Snow Kingdom Power Moon", "Snow Kingdom Multi-Moon",
    "Seaside Kingdom Power Moon", "Seaside Kingdom Multi-Moon",
    "Luncheon Kingdom Power Moon", "Luncheon Kingdom Multi-Moon",
    "Ruined Kingdom Power Moon", "Ruined Kingdom Multi-Moon",
    "Bowser's Kingdom Power Moon", "Bowser's Kingdom Multi-Moon",
    "Moon Kingdom Power Moon",
    "Ty-foo", "Shiverian Racer", "Snow Cheep Cheep", "Gushen",
    "Lava Bubble", "Volbonan", "Hammer Bro", "Meat", "Fire Piranha Plant",
    "Pokio", "Jizo", "Bowser Statue", "Parabones", "Banzai Bill",
    "Chargin' Chuck",
    # P3 post-game captures (no home once post-Metro regions are removed).
    "Letter", "Yoshi", "Bowser",
})

########################################################################################
## Order of method calls when the world generates:
##    1. create_regions - Creates regions and locations
##    2. create_items - Creates the item pool
##    3. set_rules - Creates rules for accessing regions and locations
##    4. generate_basic - Runs any post item pool options, like place item/category
##    5. pre_fill - Creates the victory location
##
## The create_item method is used by plando and start_inventory settings to create an item from an item name.
## The fill_slot_data method will be used to send data to the SMO client for later use, like deathlink.
########################################################################################



def _load_entrance_data() -> tuple[dict, dict]:
    """Load and return (subareas, exclusions) dicts from data/ (zip-safe).

    Goes through entrance_logic.load_data_json so it works inside the bundled
    .apworld zip — pathlib can't traverse into the zip (see load_data_json).
    """
    from ..entrance_logic import load_data_json
    subareas = load_data_json("subareas.json")
    exclusions = load_data_json("entrance_exclusions.json")
    return subareas, exclusions


def _roll_entrance_bijection(
    world: World,
    pool: list[str],
) -> dict[str, str]:
    """Roll a random bijection (door_subarea → interior_subarea) over pool."""
    shuffled = list(pool)
    world.random.shuffle(shuffled)
    return {door: interior for door, interior in zip(pool, shuffled)}


def _entrance_shuffle_mode(multiworld: MultiWorld, player: int) -> int:
    """Return the raw entrance_shuffle Choice value (EntranceShuffle.option_*).

    Deliberately NOT `is_option_enabled` (a `> 0` truthiness check): since P2,
    entrance_shuffle is a 3-value Choice (off=0/simple=1/decoupled=2) and both
    simple and decoupled are truthy under that check. Every call site needs
    the raw value so it can tell the two apart instead of silently treating
    a future `decoupled` seed as `simple`."""
    return get_option_value(multiworld, player, "entrance_shuffle")


def _raise_if_decoupled_entrance_shuffle(multiworld: MultiWorld, player: int) -> None:
    """Fail generation loudly if entrance_shuffle=decoupled is selected.

    The generation logic for decoupled (P3d) exists below, but the wire path
    (P3e slot_data + client + Switch rows) does not — a decoupled seed would
    be logically shuffled but physically vanilla in-game. Gated on the
    PORT_SHUFFLE_SHIPPABLE module flag (False until P3e) so the test suite
    can exercise the wiring without opening the option to YAMLs. Called from
    the earliest hook that consults the option (before_create_regions) so a
    decoupled seed never silently falls back to the coupled `simple`
    bijection (which would happily roll a bijection and ship a
    working-looking, but wrong-mode, entrance_map)."""
    if PORT_SHUFFLE_SHIPPABLE:
        return
    if _entrance_shuffle_mode(multiworld, player) == EntranceShuffle.option_decoupled:
        raise OptionError(
            "entrance_shuffle: 'decoupled' is reserved for a future release "
            "(P3's full port-graph shuffle) and is not implemented yet. Use "
            "'simple' for the current coupled entrance shuffle, or 'off' to "
            "disable entrance shuffling."
        )


# Called before regions and locations are created. Victory location is included, but Victory event is not placed yet.
def before_create_regions(world: World, multiworld: MultiWorld, player: int):
    _raise_if_decoupled_entrance_shuffle(multiworld, player)
    mode = _entrance_shuffle_mode(multiworld, player)
    if mode == EntranceShuffle.option_decoupled:
        _prepare_decoupled_entrance_shuffle(world, multiworld, player)
        return
    if mode != EntranceShuffle.option_simple:
        return

    from ..entrance_logic import (
        build_entrance_pool, build_interior_requires_map, build_moonpipe_subarea_set,
        load_entrance_stages,
    )

    subareas, exclusions = _load_entrance_data()
    # Pass entrance_stages so the pool is restricted to round-trippable subareas:
    # a member absent from entrance_stages (e.g. a renamed/merged subarea) would
    # otherwise enter the bijection and produce a one-way cross-kingdom warp
    # (see is_round_trippable). The slot_data bijection MUST agree with what
    # push_entrance_map can resolve, so the same filter gates both ends.
    pool = build_entrance_pool(subareas, exclusions, load_entrance_stages())
    bijection = _roll_entrance_bijection(world, pool)

    # Build the set of location names that live in pooled subareas.
    shuffled_locs: set[str] = set()
    for sub_name in pool:
        info = subareas[sub_name]
        shuffled_locs.update(info.get("location_names", []))

    # Compute interior-only requires (no gates) for every shuffled location.
    # Stored per-world so we never mutate the shared location_table dicts.
    interior_requires = build_interior_requires_map(world.location_table)
    filtered_interior_req: dict[str, str] = {
        name: interior_requires.get(name, "") for name in shuffled_locs
    }

    # Identify moon-pipe subareas (all locations in the subarea are Moon Rock).
    moonpipe_subareas = build_moonpipe_subarea_set(subareas, world.location_table)

    # Store on world for use by after_create_regions / after_set_rules / slot_data.
    world._entrance_map: dict[str, str] = bijection
    world._entrance_shuffled_locs: set[str] = shuffled_locs
    world._interior_requires: dict[str, str] = filtered_interior_req
    world._entrance_subareas: dict = subareas
    world._entrance_moonpipe: frozenset[str] = moonpipe_subareas
    world._entrance_pool: list[str] = pool

    logging.info(
        "entrance_shuffle: rolled bijection over %d subareas (player %d)",
        len(pool), player
    )


def _prepare_decoupled_entrance_shuffle(
    world: World, multiworld: MultiWorld, player: int
) -> None:
    """Roll the P3d decoupled port matching and stash everything the wiring
    passes need (the decoupled counterpart of the simple-mode body above).

    Deliberately does NOT set `world._entrance_map`: that attribute drives the
    simple-mode wiring, the `entrance_map` slot_data key, and the spoiler
    block. Decoupled ships its matching under a NEW slot_data key in P3e; a
    coupled-shaped entrance_map for a decoupled seed would be wrong-mode data
    on the wire. The roller's RuntimeErrors (involution/connectivity/row
    budget) are intentionally loud — a bad roll must fail generation, never
    escape into fill.
    """
    from ..entrance_logic import (
        build_interior_requires_map, build_moonpipe_subarea_set,
        load_entrance_stages,
    )
    from ..port_graph import build_port_graph
    from ..port_matching import roll_port_matching

    subareas, exclusions = _load_entrance_data()
    festival = (get_option_value(multiworld, player, "goal")
                == Goal.option_festival)
    graph = build_port_graph(
        load_entrance_stages(), subareas, exclusions, festival=festival)
    matching = roll_port_matching(graph, world.random)

    # Shuffled-location set = every member of a subarea that contributes
    # pooled mouths. Dropped subareas (D5 exclusions, one-way-ENTRY re-fight
    # arenas, unsound doors) keep their locations in their kingdom regions
    # with the baked locations.json rules — flight-reachable exactly as today.
    pooled_subareas = sorted({m.subarea for m in graph.mouths.values()})
    shuffled_locs: set[str] = set()
    for sub_name in pooled_subareas:
        shuffled_locs.update(
            subareas.get(sub_name, {}).get("location_names", []))

    interior_requires = build_interior_requires_map(world.location_table)

    world._port_graph = graph
    world._port_matching = matching
    world._port_subareas = pooled_subareas
    world._entrance_subareas = subareas
    world._entrance_shuffled_locs = shuffled_locs
    world._interior_requires = {
        name: interior_requires.get(name, "") for name in shuffled_locs
    }
    world._entrance_moonpipe = build_moonpipe_subarea_set(
        subareas, world.location_table)

    logging.info(
        "entrance_shuffle: decoupled matching rolled over %d mouths / %d "
        "subareas (player %d)", len(graph.mouths), len(pooled_subareas),
        player)

# Called after regions and locations are created, in case you want to see or modify that information. Victory location is included.
def after_create_regions(world: World, multiworld: MultiWorld, player: int):
    # Every location whose category set resolves "disabled" via the generic
    # category/yaml_option machinery (see Helpers.is_location_enabled and the
    # before_is_category_enabled hook below) is removed here. Adding a new
    # toggle is now a pure data edit: tag the category in categories.json with
    # a yaml_option, tag affected locations, and you're done.
    locationNamesToRemove = [
        location["name"]
        for location in world.location_table
        if not is_location_enabled(multiworld, player, location)
    ]

    for region in multiworld.regions:
        if region.player == player:
            for location in list(region.locations):
                if location.name in locationNamesToRemove:
                    region.locations.remove(location)
    if hasattr(multiworld, "clear_location_cache"):
        multiworld.clear_location_cache()

    _wire_entrance_shuffle(world, multiworld, player)
    _wire_decoupled_entrances(world, multiworld, player)


def _kingdom_region_for_subarea(
    subarea_name: str,
    subareas: dict,
    multiworld: "MultiWorld",
    player: int,
) -> Region | None:
    """Return the AP Region object for the kingdom that contains door_subarea."""
    info = subareas.get(subarea_name, {})
    kingdom_name = info.get("kingdom", "")
    # Map special kingdom names to their AP region names (from regions.json).
    # "Night Metro" is a separate region in regions.json; most metro-subarea
    # doors are in the daytime Metro Kingdom.
    try:
        return multiworld.get_region(kingdom_name, player)
    except Exception:
        return None



def _wire_entrance_shuffle(world: World, multiworld: MultiWorld, player: int) -> None:
    """Create subarea interior Regions + door Entrance objects for entrance shuffle."""
    bijection: dict[str, str] | None = getattr(world, "_entrance_map", None)
    if bijection is None:
        return

    subareas: dict = world._entrance_subareas

    # NOTE: the door access RULES (kingdom/subarea/peace gates + the door's own
    # scenario gate, e.g. {CascadeDeparture()}) are NOT set here — they'd be clobbered
    # by the Manual core set_rules (see Step 3). They're applied post-set_rules in
    # _apply_entrance_shuffle_door_rules. This pass only builds structure.

    # Step 1: Create an interior Region for each pooled subarea.
    # Gather location objects by subarea name first (they're currently in their
    # original kingdom regions).
    interior_regions: dict[str, Region] = {}
    for sub_name in world._entrance_pool:
        interior_reg = Region(f"{sub_name} Interior", player, multiworld)
        interior_regions[sub_name] = interior_reg
        multiworld.regions.append(interior_reg)

    # Step 2: Move SMOLocation objects from their original regions to the
    # appropriate interior regions.
    loc_to_subarea: dict[str, str] = {}
    for sub_name, info in subareas.items():
        if sub_name not in interior_regions:
            continue
        for loc_name in info.get("location_names", []):
            loc_to_subarea[loc_name] = sub_name

    for region in multiworld.regions:
        if region.player != player:
            continue
        for loc_obj in list(region.locations):
            sub_name = loc_to_subarea.get(loc_obj.name)
            if sub_name is not None and sub_name in interior_regions:
                region.locations.remove(loc_obj)
                interior_regions[sub_name].locations.append(loc_obj)
                loc_obj.parent_region = interior_regions[sub_name]

    if hasattr(multiworld, "clear_location_cache"):
        multiworld.clear_location_cache()

    # Step 3: Create one Entrance per door subarea pointing to the shuffled interior.
    # NOTE: only the STRUCTURE (Entrance object + region wiring) is built here. The
    # access RULES are applied later, in after_set_rules via
    # _apply_entrance_shuffle_door_rules — because the Manual core set_rules (which
    # runs AFTER after_create_regions) iterates every original region's exits and
    # set_rule-OVERWRITES each one with that region's own regionCheck. Our door
    # entrances are exits of their home kingdom region, so any rule set here would be
    # clobbered (to the home region's egress check — True for Cascade), silently
    # dropping the door's peace / kingdom / {CascadeDeparture()} scenario gates. The
    # interior LOCATION rules have the same problem and are likewise re-applied in
    # after_set_rules (_apply_entrance_shuffle_location_rules). Confirmed clobber:
    # the door's access_rule became set_rules.<locals>.fullRegionCheck.
    for door_subarea, interior_subarea in bijection.items():
        door_kingdom_region = _kingdom_region_for_subarea(door_subarea, subareas, multiworld, player)
        if door_kingdom_region is None:
            logging.warning("entrance_shuffle: no region found for door '%s'", door_subarea)
            continue

        interior_reg = interior_regions.get(interior_subarea)
        if interior_reg is None:
            logging.warning("entrance_shuffle: no interior region for '%s'", interior_subarea)
            continue

        entrance_name = f"{door_subarea} -> {interior_subarea} Interior"
        entrance = Entrance(player, entrance_name, door_kingdom_region)
        entrance.connect(interior_reg)
        door_kingdom_region.exits.append(entrance)


def _wire_decoupled_entrances(world: World, multiworld: MultiWorld, player: int) -> None:
    """P3d: replace the star region graph with the port graph (decoupled mode).

    Structure AND rules are both built here, unlike simple mode's split
    wiring/after_set_rules dance. The Manual core set_rules only clobbers the
    exits of regions it knows from regions.json (`for region in regionMap.keys():
    ... set_rule(exit, fullRegionCheck)` — Rules.py), and every decoupled port
    entrance is sourced from a region set_rules has never heard of (a subarea
    interior or a kingdom Arrival region), so wiring-time rules survive. The
    ONE decoupled entrance sourced from a regions.json region — each kingdom's
    "{K} -> {K} Arrival" flight-verification edge — is left rule-less here
    precisely BECAUSE the clobber will overwrite it with that kingdom's own
    fullRegionCheck (its `requires` string), which is exactly the honest
    flight-arrival predicate we want (see the Arrival-region note below).

    The two-channel arrival model (design D1 × the Manual egress quirk):
    region-reachability of a kingdom K is one-kingdom-early under the Manual
    engine (K's `requires` gates its OUTGOING entrances, so the flight edge
    INTO K carries the PREDECESSOR's requires — see
    handoff-region-gating-egress.md). Simple mode compensates by keeping the
    clobbered regionCheck ANDed onto every door (the Cascade-departure fix).
    Under decoupled that regionCheck would also demand flight arrival for
    CHAIN traversal through K — defeating the mode. So the compensation is
    structural instead: each kingdom hosting pooled overworld mouths gets a
    synthetic "{K} Arrival" region meaning "Mario is honestly present in K's
    overworld", reachable via EITHER channel:

      * flight:  K -> K Arrival, rule = K's own requires (the set_rules
        clobber applies it for free — eval'd only when regions.json gives K a
        requires; e.g. Sand's {KingdomMoons(Cascade,5)}), with reach(K)
        itself already carrying the requires-chain of every kingdom before K;
      * chain:   every matched edge whose target mouth is an overworld mouth
        in K lands in K Arrival directly (its rule is ingress-authored, so
        no off-by-one exists on this channel).

    All overworld-mouth edges SOURCE from K Arrival too (using a door in K
    means being honestly present in K), and a free "K Arrival -> K" edge
    grants the kingdom region itself on chain arrival so K's overworld
    locations enter logic (D1/D4: peace + scenario gates keep riding the
    locations' own requires, channel-agnostic). Flight edges between kingdoms
    (regions.json connects_to) are untouched — chains never discount flight
    costs (D1), and a chain-reached K only opens K's onward FLIGHT edge if
    K's requires is also genuinely satisfied (the clobbered egress rule).

    Per matched pair (A,B), both directions are wired: region(A) -> region(B)
    gated by cost(A); region(B) -> region(A) gated by cost(B)
    (make_mouth_access_rule: mouth_cost item/peace parts + door-side scenario
    fragments for overworld mouths; the interior exit gate rides the interior
    mouth's own edge ONLY — never re-ANDed onto the partner door the way
    simple's make_door_access_rule does). Fixed points get no entrance
    (vanilla passthrough) EXCEPT the lone-overworld credit shape: a lone
    (vanilla self-mapped) overworld mouth left fixed still physically walks
    into its own subarea, so its vanilla directed entrance
    region(ow) -> region(subarea interior) is preserved — without it the
    zone-split subareas (P3c discovery 3) would be logic-stranded under a
    roll that happens to fix their overworld half.

    Mouth -> region resolution is by mouth SIDE + stage, never stage name
    alone (P3c: zone-split doors put a HomeStage in an interior mouth's
    port_id, and placement zones like LakeWorldTownZone are kingdom-map
    stages with no suffix convention):
      * interior mouth -> its subarea's "<name> Interior" region;
      * overworld mouth in a pooled subarea's interior stage (nested door)
        -> that parent subarea's interior region;
      * any other overworld mouth (HomeStage, placement zone, vanilla-kept
        parent interior) -> its kingdom's Arrival region, kingdom taken from
        the subarea record's `kingdom` field (never suffix-derived).
    """
    matching: dict[str, str] | None = getattr(world, "_port_matching", None)
    if matching is None:
        return

    from ..entrance_logic import load_data_json
    from ..port_graph import INTERIOR, OVERWORLD, make_mouth_access_rule

    graph = world._port_graph
    subareas: dict = world._entrance_subareas
    moonpipe: frozenset[str] = world._entrance_moonpipe
    try:
        scenario_gates: dict = load_data_json("subarea_scenario_gates.json")
    except Exception:
        scenario_gates = {}

    # Step 1: one interior Region per pooled subarea (same shape as simple's
    # Step 1, over the port pool's subarea set instead of the bijection pool).
    interior_regions: dict[str, Region] = {}
    for sub_name in world._port_subareas:
        interior_reg = Region(f"{sub_name} Interior", player, multiworld)
        interior_regions[sub_name] = interior_reg
        multiworld.regions.append(interior_reg)

    # Step 2: move member SMOLocations into their interior regions (identical
    # to simple's Step 2 — kept duplicated so the byte-identical simple path
    # is never touched by decoupled work).
    loc_to_subarea: dict[str, str] = {}
    for sub_name, info in subareas.items():
        if sub_name not in interior_regions:
            continue
        for loc_name in info.get("location_names", []):
            loc_to_subarea[loc_name] = sub_name

    for region in multiworld.regions:
        if region.player != player:
            continue
        for loc_obj in list(region.locations):
            sub_name = loc_to_subarea.get(loc_obj.name)
            if sub_name is not None and sub_name in interior_regions:
                region.locations.remove(loc_obj)
                interior_regions[sub_name].locations.append(loc_obj)
                loc_obj.parent_region = interior_regions[sub_name]

    if hasattr(multiworld, "clear_location_cache"):
        multiworld.clear_location_cache()

    # Step 3: mouth -> region resolution tables. Interior-stage ownership must
    # be unique — two pooled subareas sharing an interior stage would make
    # nested-door attachment ambiguous (P1 data guarantees uniqueness today;
    # loud failure if a future re-extraction regresses it).
    interior_stage_to_sub: dict[str, str] = {}
    for m in graph.mouths.values():
        if m.side != INTERIOR:
            continue
        prev = interior_stage_to_sub.setdefault(m.stage, m.subarea)
        if prev != m.subarea:
            raise RuntimeError(
                f"decoupled entrance shuffle: interior stage '{m.stage}' is "
                f"claimed by two pooled subareas ('{prev}' and "
                f"'{m.subarea}') — nested-door region attachment is ambiguous")

    arrival_regions: dict[str, Region] = {}

    def _arrival_region(kingdom: str) -> Region | None:
        reg = arrival_regions.get(kingdom)
        if reg is not None:
            return reg
        try:
            kingdom_region = multiworld.get_region(kingdom, player)
        except Exception:
            logging.warning(
                "decoupled entrance shuffle: no region for kingdom '%s'",
                kingdom)
            return None
        reg = Region(f"{kingdom} Arrival", player, multiworld)
        multiworld.regions.append(reg)
        # Flight-verification edge — rule-less on purpose: the Manual core
        # set_rules clobber overwrites every regions.json region's exits with
        # that region's own fullRegionCheck, which for this edge IS the honest
        # flight-arrival predicate (see docstring).
        flight = Entrance(player, f"{kingdom} -> {kingdom} Arrival",
                          kingdom_region)
        flight.connect(reg)
        kingdom_region.exits.append(flight)
        # Presence edge: honest arrival by either channel grants the kingdom
        # region itself (overworld locations). Free; never clobbered (its
        # source region is not in regions.json).
        back = Entrance(player, f"{kingdom} Arrival -> {kingdom}", reg)
        back.connect(kingdom_region)
        reg.exits.append(back)
        arrival_regions[kingdom] = reg
        return reg

    def _mouth_region(m) -> Region | None:
        if m.side == INTERIOR:
            return interior_regions.get(m.subarea)
        parent_sub = interior_stage_to_sub.get(m.stage)
        if parent_sub is not None:
            return interior_regions.get(parent_sub)
        return _arrival_region(m.kingdom)

    def _connect(name: str, src: Region, dst: Region, rule) -> None:
        entrance = Entrance(player, name, src)
        entrance.connect(dst)
        src.exits.append(entrance)
        entrance.access_rule = rule

    # Step 4: two directed entrances per matched pair, one per mouth side.
    wired = 0
    credited = 0
    for a_id in sorted(matching):
        b_id = matching[a_id]
        a = graph.mouths[a_id]
        if a_id == b_id:
            # Fixed point = vanilla passthrough (zero rewrite rows). Only the
            # lone-OVERWORLD shape earns a logic edge: it still walks into its
            # own subarea (the checker's vanilla credit). A lone-interior
            # fixed point is one-way OUT into always-reachable territory —
            # no logic value, no entrance.
            if (a.side == OVERWORLD
                    and graph.vanilla_matching.get(a_id) == a_id
                    and a.subarea in interior_regions):
                src = _mouth_region(a)
                if src is not None:
                    _connect(
                        f"{a_id} => {a.subarea} Interior (vanilla credit)",
                        src, interior_regions[a.subarea],
                        make_mouth_access_rule(
                            a, moonpipe, scenario_gates, subareas,
                            world, multiworld, player))
                    credited += 1
            continue
        if a_id > b_id:
            continue  # each pair wires both directions once, from its low id
        b = graph.mouths[b_id]
        reg_a, reg_b = _mouth_region(a), _mouth_region(b)
        if reg_a is None or reg_b is None:
            logging.warning(
                "decoupled entrance shuffle: unresolvable region for pair "
                "(%s, %s) — pair left unwired", a_id, b_id)
            continue
        _connect(f"{a_id} => {b_id}", reg_a, reg_b,
                 make_mouth_access_rule(a, moonpipe, scenario_gates,
                                        subareas, world, multiworld, player))
        _connect(f"{b_id} => {a_id}", reg_b, reg_a,
                 make_mouth_access_rule(b, moonpipe, scenario_gates,
                                        subareas, world, multiworld, player))
        wired += 1

    world._port_arrival_regions = sorted(arrival_regions)
    logging.info(
        "entrance_shuffle: decoupled wiring — %d pair(s) wired both ways, "
        "%d vanilla credit edge(s), %d kingdom Arrival region(s) (player %d)",
        wired, credited, len(arrival_regions), player)


def _apply_entrance_shuffle_door_rules(
    world: World, multiworld: MultiWorld, player: int
) -> None:
    """Apply (and outlive set_rules) the door entrance access rules for entrance
    shuffle.

    Runs in after_set_rules, AFTER the Manual core set_rules has set every door
    entrance's rule to its home region's regionCheck (see the clobber note in
    _wire_entrance_shuffle Step 3). Re-derives the combined door gate the wiring pass
    would have set — kingdom-item gate + subarea entry/exit gate + moon-pipe peace gate
    (make_door_access_rule) AND the door subarea's own scenario gate
    (make_door_scenario_gate_rule, e.g. {CascadeDeparture()} for the Mysterious Clouds
    door) — and ADD-rules it onto the EXISTING entrance objects.

    ⚠ We add_rule (AND), NOT set_rule (replace), so the home region's regionCheck that
    set_rules applied SURVIVES. That regionCheck is the home kingdom's EGRESS gate =
    its ARRIVAL gate under the Manual engine's egress off-by-one (a region's `requires`
    rides its OUTGOING entrances; our door IS one of those exits). For Sand that's
    {KingdomMoons(Cascade,5)} — i.e. "you've left Cascade." Dropping it (the previous
    set_rule) let a Sand door's interior — reachable for FREE because Cascade→Sand is a
    free egress edge — be entered from sphere 0, so a Cascade Power Moon fill-placed
    behind an ungated Sand door (e.g. a shop with no intrinsic gate, like Crazy Cap
    Store) counted toward the Cascade leave-gate without ever leaving Cascade → the
    Cascade-departure deadlock. Region propagation only proves you can REACH the door's
    region (sphere 0); the regionCheck is what proves you ARRIVED there in earnest.
    """
    bijection: dict[str, str] | None = getattr(world, "_entrance_map", None)
    if bijection is None:
        return

    from ..entrance_logic import (
        load_data_json, make_door_access_rule, make_door_scenario_gate_rule,
    )
    from worlds.generic.Rules import add_rule

    subareas: dict = world._entrance_subareas
    moonpipe: frozenset[str] = world._entrance_moonpipe
    try:
        _scenario_gates: dict = load_data_json("subarea_scenario_gates.json")
    except Exception:
        _scenario_gates = {}

    applied = 0
    for door_subarea, interior_subarea in bijection.items():
        entrance_name = f"{door_subarea} -> {interior_subarea} Interior"
        try:
            entrance = multiworld.get_entrance(entrance_name, player)
        except Exception:
            continue

        is_moon_pipe = door_subarea in moonpipe  # door IS a moon-pipe opening
        rule = make_door_access_rule(
            door_subarea, subareas.get(door_subarea, {}).get("kingdom", ""),
            is_moon_pipe, world, multiworld, player,
            interior_subarea=interior_subarea,
        )
        # add_rule (AND), NOT set_rule: keep the home-region egress/arrival gate
        # set_rules already applied (e.g. {KingdomMoons(Cascade,5)} on Sand doors).
        # See the docstring's ⚠ note — set_rule here was the Cascade-departure leak.
        add_rule(entrance, rule)

        # AND the door subarea's own intrinsic scenario gate onto the entrance.
        # This is the door's overworld reachability (e.g. {CascadeDeparture()} for
        # the Mysterious Clouds door) — without it, a moon behind a late door is
        # reachable as early as its unrelated interior gate allows. OR over the
        # door's member moons (an ungated member ⇒ door gate-free); no-op when the
        # door subarea has no gated members.
        door_members = subareas.get(door_subarea, {}).get("location_names", [])
        door_fragments = [_scenario_gates.get(ln, "") for ln in door_members]
        if any(door_fragments):
            add_rule(entrance, make_door_scenario_gate_rule(
                door_fragments, world, multiworld, player))
        applied += 1

    logging.info(
        "entrance_shuffle: applied %d door access rules (post-set_rules, player %d)",
        applied, player)

# Pure roll helpers for randomize_kingdom_gates live in kingdom_gates.py
# (AP-free, directly importable by the test suite — same pattern as
# talkatoo_order.py).
from ..kingdom_gates import pool_gate_capacities, roll_kingdom_gates


def _demote_surplus_kingdom_moons(item_pool: list,
                                  gates: dict[str, int] | None = None,
                                  prefer_demoting_multimoons: bool = False) -> None:
    """Demote surplus per-kingdom progression moons to FILLER in place.

    Items.json marks every kingdom moon as `progression: true`, but each
    gated kingdom's KingdomMoons(K, N) rule only needs N effective moons
    reachable. The surplus contributes nothing to reachability.

    Surplus moons are demoted to `filler` (NOT `useful`) because P3 added 67
    `junk_only` Mushroom/Dark Side locations whose item rule rejects BOTH
    advancement AND useful items — only filler/traps may land there. The pool's
    standalone filler (Coins/traps) is trimmed to a handful by
    adjust_filler_items, so the surplus moons are the only large filler source
    big enough to fill those 67 slots. Demoting them to `useful` instead left
    ~47 non-fillable moons with no legal home (remaining_fill: "No more spots").
    Filler also stays trim-friendly (adjust_filler_items pops filler/trap/useful
    alike), so nothing else regresses.

    `gates` defaults to the static KINGDOM_MOON_GATES table; the
    randomize_kingdom_gates option passes the per-seed rolled table instead
    so the kept-as-progression subset always covers the rolled threshold.
    """
    if gates is None:
        gates = KINGDOM_MOON_GATES
    for kingdom, threshold in gates.items():
        # Ruined exemption: its pool is tiny (1 Multi-Moon + 4 Power Moons)
        # and it gates the entire post-game chain (Bowser's -> Moon ->
        # victory). Demoting any of its moons drops them out of
        # the reachability-guaranteed progression fill, which makes the
        # chain tail fragile (observed as remaining_fill FillErrors at
        # Bowser's/Moon locations). Five always-progression items cost the
        # trim machinery nothing.
        if kingdom == "Ruined":
            continue
        pm_name = f"{kingdom} Kingdom Power Moon"
        mm_name = f"{kingdom} Kingdom Multi-Moon"
        prog_mms = [it for it in item_pool
                    if it.name == mm_name and it.classification == ItemClassification.progression]
        prog_pms = [it for it in item_pool
                    if it.name == pm_name and it.classification == ItemClassification.progression]
        if prefer_demoting_multimoons:
            # multi_moon_shuffle strategy: Power Moons are the progression
            # backbone; Multi-Moons are kept progression only when the PMs
            # alone can't cover the gate. Demoted (filler) MMs are what lets
            # the MM<->MM-location matching fill freely — in particular the
            # filler_only "Cascade: Multi Moon Atop the Falls" can only hold
            # a non-progression Multi-Moon.
            pms_kept = min(len(prog_pms), threshold)
            remainder = threshold - pms_kept
            mms_kept = min(len(prog_mms),
                           (remainder + 2) // 3) if remainder > 0 else 0
        else:
            # Upstream strategy: MMs first since each is worth 3 effective;
            # minimize kept count.
            mms_kept = min(len(prog_mms), threshold // 3)
            pms_kept = min(len(prog_pms), max(0, threshold - 3 * mms_kept))
        for it in prog_mms[mms_kept:]:
            it.classification = ItemClassification.filler
        for it in prog_pms[pms_kept:]:
            it.classification = ItemClassification.filler


# Fixed starters: always precollected, never placed at randomised locations.
# Frog, Chain Chomp, and Broode's Chain Chomp are the three mandatory starting
# captures: Frog (Cap Kingdom opening), Chain Chomp (early Cascade), and Broode's
# Chain Chomp (the capture Cascade's story moon "Multi Moon Atop the Falls" needs —
# granted up front because the Cascade scenario reachability gating leans on Multi
# Moon being collectable from arrival; see scripts/compile_moon_logic.py
# build_cascade_anchors). A further capture is chosen at random from the remaining
# Capture pool each seed.
#
# These are removed from item_pool here so adjust_filler_items doesn't try to
# place them; multiworld.push_precollected makes the AP server hand them to the
# client at game-start (index 0 of the received-items list), so the Switch-mod
# receives them via the normal item-receive path before any HELLO replay.
FIXED_STARTER_CAPTURES: tuple[str, ...] = ("Frog", "Chain Chomp", "Broode's Chain Chomp")


def _precollect_starting_captures(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> None:
    """Remove the starter captures from the pool and push to precollected.

    The FIXED_STARTER_CAPTURES (Frog, Chain Chomp, Broode's Chain Chomp) are
    always precollected. A further capture is chosen uniformly at random from the
    remaining Capture-category items in the pool (excluding the fixed starters).
    The chosen item is stored on the world object as
    `world.random_starter_capture` for test introspection.

    If either fixed starter is missing from the pool (shouldn't happen in
    normal generation), logs a warning and skips it rather than crashing.
    """
    # Collect all Capture items by position so we can remove by index safely.
    # SMOItem carries no per-instance category dict, so resolve the category
    # from the world's canonical name->data table. (An earlier version read a
    # per-item attribute that SMOItem never sets, so it matched nothing and the
    # starters were never precollected — fixed 2026-06-14.)
    item_name_to_item = world.item_name_to_item
    capture_indices = [
        i for i, it in enumerate(item_pool)
        if "Capture" in item_name_to_item.get(it.name, {}).get("category", [])
    ]
    pool_by_name: dict[str, int] = {}  # name -> first index in item_pool
    for i in capture_indices:
        name = item_pool[i].name
        if name not in pool_by_name:
            pool_by_name[name] = i

    to_precollect_indices: list[int] = []

    # Fixed starters
    for name in FIXED_STARTER_CAPTURES:
        idx = pool_by_name.get(name)
        if idx is None:
            logging.warning("_precollect_starting_captures: %r not in pool", name)
            continue
        to_precollect_indices.append(idx)

    # Random extra: pick from captures not already chosen
    chosen_names = {item_pool[i].name for i in to_precollect_indices}
    eligible = [
        i for i in capture_indices
        if item_pool[i].name not in chosen_names
        and i not in to_precollect_indices
    ]
    if eligible:
        extra_idx = world.random.choice(eligible)
        world.random_starter_capture = item_pool[extra_idx].name
        to_precollect_indices.append(extra_idx)
    else:
        world.random_starter_capture = None
        logging.warning("_precollect_starting_captures: no eligible captures for random slot")

    # Push to precollected and remove from pool (descending index order so
    # earlier removals don't shift later indices).
    for i in sorted(to_precollect_indices, reverse=True):
        multiworld.push_precollected(item_pool[i])
        item_pool.pop(i)


# The item pool before starting items are processed, in case you want to see the raw item pool at that stage
def before_create_items_starting(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> list:
    # Precollect the starting captures (Frog, Chain Chomp, Broode's Chain Chomp,
    # +1 random).
    # Must run before the festival-goal trim so the starters are present in
    # the pool when we remove them (festival trim uses item names, not indices,
    # so order doesn't matter, but being explicit avoids edge cases).
    _precollect_starting_captures(item_pool, world, multiworld, player)

    # Under the festival goal, post-Metro locations are removed in
    # create_regions, so post-Metro kingdoms' moons and the 15 captures
    # exclusive to those kingdoms have nowhere to land. Drop them now.
    #
    # Metro Kingdom Power/Multi-Moons also get reclassified to filler:
    # festival is reached from inside Metro, so nothing downstream consumes
    # a `KingdomMoons(Metro, N)` gate, and leaving them as progression
    # forces adjust_filler_items to leave the surplus in the pool (it pops
    # filler/trap/useful, never progression). With them as filler, the
    # pool trims down cleanly to the smaller location count.
    if get_option_value(multiworld, player, "goal") == 1:
        item_pool[:] = [it for it in item_pool if it.name not in FESTIVAL_ITEMS_TO_DROP]
        for it in item_pool:
            if it.name in ("Metro Kingdom Power Moon", "Metro Kingdom Multi-Moon"):
                it.classification = ItemClassification.filler
    return item_pool

def _drop_ability_items_if_disabled(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> None:
    """abilitysanity OFF: remove every `Ability`-category item from the pool.

    When abilitysanity is on (default) the ability items ride in the pool and
    each move is gated in-game until its item arrives (P4 enforcement). When
    off, ability randomization is disabled entirely: the items are dropped here
    (mirroring the festival-goal drop) and adjust_filler_items tops the freed
    slots back up with filler — same check count, no ability items received,
    and the client tells the Switch to open the ability gate (see
    context.py / ability_state `enforce`). Dropping by name keeps item IDs
    stable (IDs are name-keyed in the datapackage, not pool-position).
    """
    if is_option_enabled(multiworld, player, "abilitysanity"):
        return
    name_to_item = world.item_name_to_item
    item_pool[:] = [
        it for it in item_pool
        if "Ability" not in name_to_item.get(it.name, {}).get("category", [])
    ]


def _precollect_ability_items_if_disabled(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> None:
    """abilitysanity OFF: precollect every Ability item at its full copy count.

    _drop_ability_items_if_disabled removes all Ability-category items from
    the pool, but the compiled moon/door/victory `requires` strings still
    demand ability tokens (e.g. `|Progressive Ground Pound:1|`) — with zero
    such items ever existing, every location gated behind one becomes
    permanently unreachable and fill collapses (FillError). Precollecting
    each ability at full count satisfies those tokens in CollectionState
    while the pool drop keeps the item/location counts unchanged; the
    Switch-side gate is separately opened via ability_state `enforce=False`.
    See docs/handoff-abilitysanity-precollect-fix.md.
    """
    if is_option_enabled(multiworld, player, "abilitysanity"):
        return
    name_to_item = world.item_name_to_item
    for name in _names_in_item_category(world, "Ability"):
        count = int(name_to_item.get(name, {}).get("count", 1))
        for _ in range(count):
            multiworld.push_precollected(world.create_item(name))


def _trim_kingdom_moons_to_options(item_pool: list, multiworld: MultiWorld, player: int) -> None:
    """Drop surplus per-kingdom Moon items down to the option-configured cap.

    Power Moons are dropped first so Multi-Moons (worth 3 effective each toward
    the KingdomMoons(K, N) gate) are preserved; this keeps the demotion in
    _demote_surplus_kingdom_moons able to select a gate-satisfying progression
    subset even at the option floor. adjust_filler_items in __init__.py refills
    the freed pool slots with filler — same total check count, just fewer
    kingdom-flavored Moon items received.
    """
    for kingdom, opt_name in KINGDOM_MOON_COUNT_OPTIONS.items():
        target = get_option_value(multiworld, player, opt_name)
        pm_name = f"{kingdom} Kingdom Power Moon"
        mm_name = f"{kingdom} Kingdom Multi-Moon"
        pm_indices = [i for i, it in enumerate(item_pool) if it.name == pm_name]
        mm_indices = [i for i, it in enumerate(item_pool) if it.name == mm_name]
        current = len(pm_indices) + len(mm_indices)
        if current <= target:
            continue
        to_drop = current - target
        # Drop PMs first; only dip into MMs once PMs are exhausted. Pop in
        # descending index order so earlier pops don't shift the later ones.
        pms_to_drop = pm_indices[: min(to_drop, len(pm_indices))]
        mms_to_drop = mm_indices[: max(0, to_drop - len(pm_indices))]
        for i in sorted(pms_to_drop + mms_to_drop, reverse=True):
            item_pool.pop(i)


# The item pool after starting items are processed but before filler is added, in case you want to see the raw item pool at that stage
def _drop_items_by_name(item_pool: list, names: set[str]) -> None:
    """Remove every pool item whose name is in `names` (in place)."""
    item_pool[:] = [it for it in item_pool if it.name not in names]


# Re-fight / Dark Side multi-moon BONUS side-grants (handoff:
# docs/handoff-refight-multi-moons.md). The 6 Mushroom Kingdom Multi-Moon
# items collectively unlock 18 captures (3 apiece); the 1 Dark Side Multi-Moon
# unlocks 3 abilities — "bonus on top" of the capturesanity/abilitysanity pool
# items (duplicates fall through to the existing coin path). The picks are
# rolled here from world.random (deterministic per seed) and shipped in
# slot_data as `mm_bonus_captures` (ordered, 18) + `mm_bonus_abilities` (3);
# the client consumes the capture list in ordered chunks of 3 as each
# (same-named) Mushroom MM arrives, and folds the 3 abilities into the ability
# snapshot when the Dark Side MM arrives. These are NOT real pool items — they
# don't affect logic/fill, only in-game unlocks.
MM_BONUS_CAPTURE_COUNT = 18   # 6 Mushroom Multi-Moons x 3 captures each
MM_BONUS_ABILITY_COUNT = 3    # 1 Dark Side Multi-Moon  x 3 abilities


def _names_in_item_category(world: World, category: str) -> list[str]:
    """Sorted list of item names whose items.json `category` contains `category`.

    Sorted for reproducibility before the seeded sample below — dict order is
    insertion order (deterministic) but sorting removes any doubt.
    """
    return sorted(
        name for name, data in world.item_name_to_item.items()
        if category in data.get("category", [])
    )


def _roll_mm_bonus_grants(world: World) -> None:
    """Roll the multi-moon bonus captures/abilities and stash on `world`.

    Sampled from the FULL capture/ability name sets (not the current item_pool)
    so the bonus is independent of whether capturesanity/abilitysanity put those
    items in the pool — they ship as slot_data side-grants either way. The 3
    always-owned fixed starters are excluded from the capture pick so a bonus is
    more likely to be a real unlock (a dup just becomes coins, so this is only a
    quality nicety). Mirrors how rolled_kingdom_gates is stashed for slot_data.
    """
    captures = [c for c in _names_in_item_category(world, "Capture")
                if c not in FIXED_STARTER_CAPTURES]
    abilities = _names_in_item_category(world, "Ability")
    cap_k = min(MM_BONUS_CAPTURE_COUNT, len(captures))
    abil_k = min(MM_BONUS_ABILITY_COUNT, len(abilities))
    world.mm_bonus_captures = world.random.sample(captures, cap_k) if cap_k else []
    world.mm_bonus_abilities = world.random.sample(abilities, abil_k) if abil_k else []
    logging.info(
        "multi_moon bonus grants rolled: %d captures, %d abilities",
        len(world.mm_bonus_captures), len(world.mm_bonus_abilities))


def before_create_items_filler(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> list:
    goal_is_festival = get_option_value(multiworld, player, "goal") == 1
    # Festival goal: the 6 Mushroom Kingdom + 1 Dark Side Multi-Moon items
    # (added for the re-fight/Dark Side bundle feature) unlock post-game moon
    # locations festival never reaches. Under multi_moon_shuffle they're
    # constrained to the (now-unreachable) Mushroom/Dark Side multi_moon
    # locations — a fill deadlock — and even without the shuffle they only
    # bump post-game moon counts that are meaningless under festival. Drop all
    # 7 in every mode; adjust_filler_items tops any freed slots with filler.
    # See docs/handoff-refight-multi-moons.md (Tier 2).
    if goal_is_festival:
        _drop_items_by_name(
            item_pool,
            {"Mushroom Kingdom Multi-Moon", "Dark Side Multi-Moon"},
        )
    # multi_moon_shuffle: under the FESTIVAL goal, "Metro: A Traditional
    # Festival!" is the victory location and can't hold an item, leaving
    # one more Multi-Moon item than fillable MM location. Drop ONE Metro
    # Multi-Moon (Metro has two) to balance the matching; adjust_filler_items
    # tops the freed slot back up with filler.
    # Under any other goal the festival is a real MM location (it survived
    # __init__.create_regions as a normal check), so items match locations
    # exactly — no drop.
    if (is_option_enabled(multiworld, player, "multi_moon_shuffle")
            and goal_is_festival):
        for i, it in enumerate(item_pool):
            if it.name == "Metro Kingdom Multi-Moon":
                item_pool.pop(i)
                break
    # abilitysanity OFF: strip the Ability-category items from the pool (the
    # freed slots are topped up with filler by adjust_filler_items, same as the
    # moon-count trim below). Runs here so the reduced pool flows into
    # adjust_filler_items / after_create_items unchanged when the option is on.
    # Precollect the same items at full copy count so the compiled `requires`
    # strings' ability tokens stay satisfiable — otherwise every location
    # gated behind an ability becomes unreachable and fill collapses.
    _drop_ability_items_if_disabled(item_pool, world, multiworld, player)
    _precollect_ability_items_if_disabled(item_pool, world, multiworld, player)
    # Apply the per-kingdom moon-count caps before adjust_filler_items runs
    # in create_items: the trim leaves locations > items, which then triggers
    # adjust_filler_items' top-up branch (filler / traps). Runs before
    # after_create_items so _demote_surplus_kingdom_moons sees the trimmed pool.
    _trim_kingdom_moons_to_options(item_pool, multiworld, player)
    return item_pool

# The complete item pool prior to being set for generation is provided here, in case you want to make changes to it
def after_create_items(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> list:
    # randomize_kingdom_gates: roll the per-kingdom leave thresholds with the
    # multiworld's seeded RNG. Rolled AFTER the moon-count trim (which ran in
    # before_create_items_filler) so capacities reflect the final pool, and
    # BEFORE demotion so the kept-progression subset covers the rolled gate.
    # Rules.KingdomMoons reads world.rolled_kingdom_gates to override the
    # static N from regions.json; before_fill_slot_data ships it to the client.
    gates = None
    if is_option_enabled(multiworld, player, "randomize_kingdom_gates"):
        gates = roll_kingdom_gates(
            world.random, KINGDOM_MOON_GATES,
            pool_gate_capacities(item_pool, KINGDOM_MOON_GATES))
        world.rolled_kingdom_gates = gates
        # Surface the rolls in the generation log — without this, a fill
        # failure gives no way to correlate against the rolled thresholds.
        logging.info("randomize_kingdom_gates rolled: %s", gates)
    # See _demote_surplus_kingdom_moons for the why. Runs in every mode so
    # the default goal still benefits from the demotion (which is what the
    # `all_off` peace-toggle scenarios rely on). Under multi_moon_shuffle the
    # strategy flips to PM-first so demoted Multi-Moons exist to satisfy the
    # MM<->MM-location matching (see _apply_multi_moon_rules).
    _demote_surplus_kingdom_moons(
        item_pool, gates,
        prefer_demoting_multimoons=is_option_enabled(
            multiworld, player, "multi_moon_shuffle"))
    _demote_mobility_only_abilities(item_pool)
    # Roll the re-fight/Dark Side multi-moon bonus grants (deterministic per
    # seed). Rolled unconditionally so slot_data always carries them; inert
    # when the MM items were dropped (festival goal) since the client never
    # receives a Mushroom/Dark Side Multi-Moon to trigger a grant.
    _roll_mm_bonus_grants(world)
    return item_pool


def _demote_mobility_only_abilities(item_pool: list) -> None:
    """Demote a small, hand-audited set of progression-classified ability items
    that are NOT strictly required to reach anything, from progression to useful.

    This relieves the progression fill: these items are marked ``advancement``
    (so they avoid junk_only slots) yet are referenced by NO location's
    ``requires`` — fill_restrictive must still thread them through the narrow
    early frontier even though they open nothing, which is what FillErrors a
    tight ``minimal`` seed by 1-2 items. Demoting to ``useful`` drops them into
    the lenient non-progression fill instead. They are still placed, still
    received, still enforced in-game (the Switch P4 gate is independent of AP
    item classification) — only the fill PLACEMENT constraint is relaxed.

    The set is deliberately narrow and Devon-audited (do not widen without
    confirming the item gates nothing in-logic AND nothing in-game-critical):
      * Progressive Crouch beyond level 1 — the Crouch->Roll->Roll Boost chain
        is pure mobility; only basic Crouch (level 1) gates a moon, so the 1st
        copy stays progression and the 2nd/3rd demote.
      * Spin Throw — never strictly required for any check.
      * Ledge Grab — no longer a real ability (folded into Wall Slide); pending
        full removal as a check, demote so it never constrains the fill.

    NOT touched (gate progression in-game and/or via entrance-shuffled moons):
    Progressive Ground Pound (Dive), Progressive Jump (height routes), Yoshi
    (shuffled Mushroom moons), Bowser / Spark pylon (region-gating captures).
    """
    DEMOTE_ALL = {"Spin Throw", "Ledge Grab"}
    KEEP_FIRST = {"Progressive Crouch": 1}  # name -> # of progression copies kept
    kept: dict[str, int] = {}
    for it in item_pool:
        if not it.advancement:
            continue
        name = it.name
        if name in DEMOTE_ALL:
            it.classification = ItemClassification.useful
        elif name in KEEP_FIRST:
            kept[name] = kept.get(name, 0) + 1
            if kept[name] > KEEP_FIRST[name]:
                it.classification = ItemClassification.useful

# Called before rules for accessing regions and locations are created.
def before_set_rules(world: World, multiworld: MultiWorld, player: int):
    # entrance_shuffle: the shared location_table dicts still have their
    # original "region" fields (needed by set_rules to apply region-level
    # access rules). However, for shuffled locations the regionCheck from
    # the original kingdom is wrong once doors are remapped. We handle that
    # in after_set_rules by overriding the rules after set_rules completes.
    pass

# Locations whose Multi Moon / Power Moon can become PERMANENTLY UNOBTAINABLE on
# SMO 1.0.0 via documented sequence-break tricks. Marked `filler_only: true` in
# locations.json so the AP fill never places a progression item there — a player
# who hits the skip wouldn't be able to send the check, and a soft-lock would be
# unrecoverable on 1.0.0.
#
# Why these two (both Cascade Kingdom, 1.0.0-only):
#  - "Our First Power Moon": First Moon Skip (smo.wiki/First_Moon_Skip) — on
#    1.0.0 the Madame Broode loading zone is active before the first moon
#    spawns. Defeating her without first collecting it permanently invalidates
#    the moon's cutscene; trying to collect it later crashes the game and the
#    moon never registers in the save.
#  - "Multi Moon Atop the Falls": Broode Skip (smo.wiki/Broode_Skip) — collect
#    5 regular Power Moons via the 2P warp-painting trick and you can leave
#    Cascade without ever fighting Madame Broode. On 1.0.0 the Multi Moon is
#    then unobtainable for the rest of the save (1.0.1+ auto-awards it on
#    return; we target 1.0.0).
#
# Every other kingdom: per Mario Wiki Missable_content and the 1.0.0 / 1.0.1
# patch notes, no other moon is permanently missable in normal play or via
# documented 1.0.0 skips. The Cookatiel-fight / Big-Pot pair in Luncheon shares
# QuestNo 2->3 (only one collection advances scenario_no), but both moons stay
# physically collectible in either order, so neither is missable.
def _apply_filler_only_rules(world: World, multiworld: MultiWorld, player: int) -> None:
    filler_only_names = {
        loc["name"] for loc in world.location_table
        if loc.get("filler_only", False)
    }
    if not filler_only_names:
        return
    from worlds.generic.Rules import add_item_rule
    for region in multiworld.regions:
        if region.player != player:
            continue
        for location in region.locations:
            if location.name in filler_only_names:
                add_item_rule(location, lambda item: not item.advancement)


def _apply_multi_moon_rules(world: World, multiworld: MultiWorld, player: int) -> None:
    """multi_moon_shuffle: Multi-Moon items only on `multi_moon: true`
    locations, and vice versa — a closed 21<->21 matching (the pinned Ruined
    Multi-Moon is one fixed point of it; the other 20 float). The 21 are the 14
    story-boss MMs plus the 6 Mushroom re-fights + Dark Side arrival added by
    the re-fight/Dark Side bundle feature.

    Rules are additive with any existing item rule on the location
    (add_item_rule ANDs): notably "Cascade: Multi Moon Atop the Falls" is
    also filler_only, so it can only take a DEMOTED (non-progression)
    Multi-Moon — the demotion in after_create_items always leaves several.
    Event locations (Victory) have no multi_moon flag and reject MM items
    like every other non-MM location; the Victory event item passes.
    """
    from worlds.generic.Rules import add_item_rule

    def is_mm_item(item) -> bool:
        return item.name.endswith(" Multi-Moon")

    mm_location_names = {
        loc["name"] for loc in world.location_table if loc.get("multi_moon")
    }
    for region in multiworld.regions:
        if region.player != player:
            continue
        for location in region.locations:
            if location.name in mm_location_names:
                add_item_rule(location, is_mm_item)
            else:
                add_item_rule(location, lambda item: not is_mm_item(item))


def _apply_junk_only_rules(world: World, multiworld: MultiWorld, player: int) -> None:
    """P3: Mushroom Kingdom + Dark Side moon locations are junk-only AP checks.

    They remain collectible in-game with vanilla post-game gating, but the AP
    fill must never place progression OR useful items there — only filler/traps.
    Locations are tagged `junk_only: true` in locations.json. Stricter than
    `filler_only` (which only blocks progression), matching the design's
    "filled only with filler/traps" intent.
    """
    junk_only_names = {
        loc["name"] for loc in world.location_table
        if loc.get("junk_only", False)
    }
    if not junk_only_names:
        return
    from worlds.generic.Rules import add_item_rule
    for region in multiworld.regions:
        if region.player != player:
            continue
        for location in region.locations:
            if location.name in junk_only_names:
                add_item_rule(
                    location,
                    lambda item: not item.advancement and not item.useful,
                )


# Goal values (Options.py Goal) whose route makes the Moon post-win layers (re-arrival
# + moon-rock) reachable. Empty today: under both mushroom_kingdom (0, leaving Moon ends
# the game) and festival (1, Moon dropped entirely) those moons are uncollectable. A
# future Dark/Darker-Side goal would add its value here to lift the filler restriction.
GOALS_WITH_MOON_POSTWIN = frozenset()


def _apply_moon_postwin_rules(world: World, multiworld: MultiWorld, player: int) -> None:
    """Force the Moon Kingdom post-win layer to filler.

    The re-arrival (leave-and-return) and moon-rock Moon moons are physically
    uncollectable before the game-clear goal (leaving Moon = win), so the AP fill must
    never strand a progression OR useful item behind one. They are tagged
    `moon_postwin: true` in locations.json by compile_moon_logic.py (shine_map-driven).
    Restriction matches junk_only strength and is gated on the goal via
    GOALS_WITH_MOON_POSTWIN so a future Dark/Darker-Side goal collects them normally.
    """
    if get_option_value(multiworld, player, "goal") in GOALS_WITH_MOON_POSTWIN:
        return
    postwin_names = {
        loc["name"] for loc in world.location_table if loc.get("moon_postwin")
    }
    if not postwin_names:
        return
    from worlds.generic.Rules import add_item_rule
    for region in multiworld.regions:
        if region.player != player:
            continue
        for location in region.locations:
            if location.name in postwin_names:
                add_item_rule(
                    location,
                    lambda item: not item.advancement and not item.useful,
                )


def _apply_no_logic(world: World, multiworld: MultiWorld, player: int) -> None:
    """no_logic testing mode: make every location and region trivially reachable.

    Overrides the access_rule on every entrance and location for this player
    with "always accessible", and relaxes the world's accessibility to minimal,
    so a seed generates regardless of whether the moon-requirement logic is
    satisfiable. Item-placement rules (filler_only / junk_only / multi_moon) are
    left intact — those constrain *what* lands where, not *reachability*, so the
    pool still fills sanely. Reserved for testing; seeds may be unwinnable.
    """
    def _always(state) -> bool:
        return True

    for region in multiworld.regions:
        if region.player != player:
            continue
        for entrance in region.exits:
            entrance.access_rule = _always
        for location in region.locations:
            location.access_rule = _always

    # Relax the accessibility check so the fill never fails on an unreachable
    # location (defensive; with every rule True everything is reachable anyway).
    acc = getattr(world.options, "accessibility", None)
    if acc is not None:
        minimal = getattr(acc, "option_minimal", None)
        if minimal is not None:
            acc.value = minimal
    logging.info("no_logic enabled: all access rules forced True, "
                 "accessibility relaxed to minimal")


def _relax_full_accessibility(world: World, multiworld: MultiWorld, player: int) -> None:
    """Relax this slot's accessibility from ``full`` to ``minimal``.

    This world is NOT satisfiable under ``full`` accessibility: the entrance
    shuffle x randomize_kingdom_gates region graph leaves a sphere-0 of ~3
    locations, and the greedy filler cannot open all ~776 locations through it
    (FillError, ~200 unplaced). The design has always targeted ``minimal`` — the
    loopback seed says so verbatim — but the AP yaml TEMPLATE defaults
    ``accessibility: full``, so a player using the template default hits the
    wall. Rather than fail generation, relax full -> minimal here (the same
    mechanism _apply_no_logic uses), with a log so it's never silent.

    Only ``full`` is relaxed: a player who deliberately picked ``minimal`` or
    ``items`` keeps their choice.
    """
    acc = getattr(world.options, "accessibility", None)
    if acc is None:
        return
    full = getattr(acc, "option_full", None)
    minimal = getattr(acc, "option_minimal", None)
    if full is None or minimal is None or acc.value != full:
        return
    acc.value = minimal
    logging.info(
        "accessibility relaxed full -> minimal for player %d: this world's "
        "entrance-shuffle/kingdom-gate logic is not satisfiable under full "
        "accessibility (see _relax_full_accessibility).", player)


# Called after rules for accessing regions and locations are created, in case you want to see or modify that information.
def after_set_rules(world: World, multiworld: MultiWorld, player: int):
    _relax_full_accessibility(world, multiworld, player)
    _apply_filler_only_rules(world, multiworld, player)
    _apply_junk_only_rules(world, multiworld, player)
    _apply_moon_postwin_rules(world, multiworld, player)
    if is_option_enabled(multiworld, player, "multi_moon_shuffle"):
        _apply_multi_moon_rules(world, multiworld, player)
    # Entrance shuffle: override location access rules for shuffled locations.
    # set_rules would have applied "interior_requires AND original_regionCheck".
    # With remapped doors, the regionCheck comes from the wrong kingdom, so we
    # replace it with just the interior_requires (the door entrance handles the
    # kingdom gate + peace gate).
    _es_mode = _entrance_shuffle_mode(multiworld, player)
    if _es_mode == EntranceShuffle.option_simple:
        _apply_entrance_shuffle_location_rules(world, multiworld, player)
        # D3: re-apply the interior-intrinsic scenario gates that the rule
        # replacement above stripped from pooled-subarea moons. MUST run after
        # _apply_entrance_shuffle_location_rules (which set_rule-REPLACES the rule);
        # add_rule here ANDs the scenario gate back on top.
        _apply_subarea_scenario_gates(world, multiworld, player)
        # Re-apply the DOOR entrance access rules (kingdom/subarea/peace + the door's
        # {CascadeDeparture()}-style scenario gate). The Manual core set_rules
        # overwrote them with each door's home-region regionCheck (see
        # _wire_entrance_shuffle Step 3 clobber note); this set_rule wins.
        _apply_entrance_shuffle_door_rules(world, multiworld, player)
    elif _es_mode == EntranceShuffle.option_decoupled:
        # Same replace-then-re-gate dance as simple for LOCATIONS (both
        # helpers key off the world attrs the decoupled prepare pass set) —
        # but NO door pass: every decoupled port entrance is sourced from a
        # region the Manual core set_rules never touches (interior / Arrival
        # regions aren't in regions.json), so the wiring-time rules survive
        # un-clobbered. The one decoupled entrance that IS clobbered — each
        # kingdom's "{K} -> {K} Arrival" flight edge — WANTS its clobbered
        # rule (the kingdom's own requires = honest flight arrival; see
        # _wire_decoupled_entrances).
        _apply_entrance_shuffle_location_rules(world, multiworld, player)
        _apply_subarea_scenario_gates(world, multiworld, player)
    if is_option_enabled(multiworld, player, "start_at_cap_peace"):
        _apply_start_at_cap_peace_rules(world, multiworld, player)
    # Must run last so it wins over the access rules set in set_rules.
    if is_option_enabled(multiworld, player, "no_logic"):
        _apply_no_logic(world, multiworld, player)


def _apply_start_at_cap_peace_rules(
    world: World, multiworld: MultiWorld, player: int
) -> None:
    """Open the Cap Kingdom REGION from sphere 0 for the start-at-Cap-peace save.

    Flipping CapPeace() to True (hooks/Rules.py) makes Cap's peace/re-arrival moons
    pass their own {CapPeace()} location gate, but the Cap *region* is reached only via
    the Cascade -> Sand -> Cap region path, and the Sand->Cap entrance inherits Sand's
    egress requires {KingdomMoons(Cascade,5)} (the Manual engine gates a region's
    OUTGOING entrances — see hooks/Rules.py::CascadeDeparture). So without this, Cap is
    not region-reachable until the Cascade leave-gate regardless of CapPeace.

    On the Cap-peace save the player physically boots inside a peaceful Cap with the
    Odyssey landed, so Cap is reachable from frame zero. Sand is already sphere-0
    reachable (Cascade is the free start and the Cascade->Sand edge is ungated), so
    freeing Cap's incoming entrance makes the whole Cap region sphere-0 reachable.
    Per-location gates inside Cap (captures, abilities, CapPeace itself) are untouched,
    so this strictly loosens reachability. See docs/handoff-cap-peace-sphere-0.md."""
    from worlds.generic.Rules import set_rule
    cap = multiworld.get_region("Cap Kingdom", player)
    for entrance in cap.entrances:
        set_rule(entrance, lambda state: True)
    logging.info(
        "start_at_cap_peace: freed %d Cap Kingdom region entrance(s) (player %d)",
        len(cap.entrances), player)


def _apply_subarea_scenario_gates(
    world: World, multiworld: MultiWorld, player: int
) -> None:
    """Re-apply interior-intrinsic scenario gates to shuffled subarea moons (D3).

    Under entrance_shuffle ON, _apply_entrance_shuffle_location_rules replaces each
    shuffled location's access rule with its move-set-only interior requires, which
    DROPS the scenario gate compile_moon_logic.py baked into locations.json. That
    classification needs the gitignored shine_map (build-time only), so it can't be
    recomputed at gen time — it's precompiled into data/subarea_scenario_gates.json
    ({location_name: fragment}, pooled-subarea moons only).

    The gate is interior-intrinsic: it depends on the moon's own kingdom quest state,
    not on which door now leads in. So it rides the member LOCATION (which moves with
    the interior region under shuffle), enforced exactly once. Door-side kingdom /
    subarea-item / moon-pipe-peace gates ride the door entrance separately
    (make_door_access_rule) and are orthogonal to this scenario gate.

    OFF mode keeps the baked locations.json gate and never calls this.
    """
    from ..entrance_logic import load_data_json, make_scenario_gate_rule
    try:
        gates: dict = load_data_json("subarea_scenario_gates.json")
    except FileNotFoundError:
        return

    from worlds.generic.Rules import add_rule

    shuffled_locs: set[str] = getattr(world, "_entrance_shuffled_locs", set())
    applied = 0
    for loc_name, fragment in gates.items():
        # Every exported key is a pooled-subarea moon and therefore in shuffled_locs;
        # the guard also skips any toggled-off location removed in after_create_regions.
        if loc_name not in shuffled_locs:
            continue
        try:
            loc_obj = multiworld.get_location(loc_name, player)
        except Exception:
            continue
        add_rule(loc_obj, make_scenario_gate_rule(
            fragment, world, multiworld, player))
        applied += 1
    logging.info(
        "entrance_shuffle: re-applied %d interior scenario gates (D3, player %d)",
        applied, player)


def _apply_entrance_shuffle_location_rules(
    world: World, multiworld: MultiWorld, player: int
) -> None:
    """Override access rules for shuffled locations to interior-only requires.

    set_rules bakes in the original-kingdom regionCheck, which is wrong when
    doors are remapped.  We replace each shuffled location's access_rule with
    a closure that only evaluates the interior-only requires string.
    """
    from worlds.generic.Rules import set_rule
    from ..entrance_logic import evaluate_interior_requires

    interior_req_map: dict[str, str] = getattr(world, "_interior_requires", {})
    shuffled_locs: set[str] = getattr(world, "_entrance_shuffled_locs", set())

    for loc_name in shuffled_locs:
        try:
            loc_obj = multiworld.get_location(loc_name, player)
        except Exception:
            continue
        req_str = interior_req_map.get(loc_name, "")
        if req_str:
            set_rule(
                loc_obj,
                lambda state, r=req_str, w=world, p=player:
                    evaluate_interior_requires(state, r, w, p),
            )
        else:
            set_rule(loc_obj, lambda state: True)

# The item name to create is provided before the item is created, in case you want to make changes to it
def before_create_item(item_name: str, world: World, multiworld: MultiWorld, player: int) -> str:
    return item_name

# The item that was created is provided after creation, in case you want to modify the item
def after_create_item(item: SMOItem, world: World, multiworld: MultiWorld, player: int) -> SMOItem:
    return item

# This method is run towards the end of pre-generation, before the place_item options have been handled and before AP generation occurs
def before_generate_basic(world: World, multiworld: MultiWorld, player: int) -> list:
    pass

# This method is run at the very end of pre-generation, once the place_item options have been handled and before AP generation occurs
def after_generate_basic(world: World, multiworld: MultiWorld, player: int):
    pass

# This is called before slot data is set and provides an empty dict ({}), in case you want to modify it before the world fills it
def before_fill_slot_data(slot_data: dict, world: World, multiworld: MultiWorld, player: int) -> dict:
    # Rolled kingdom gates (randomize_kingdom_gates option). Consumed by the
    # client/Switch mod for display + future in-game gate sync; absent when
    # the option is off (clients treat absence as vanilla gates).
    rolled = getattr(world, "rolled_kingdom_gates", None)
    if rolled:
        slot_data["kingdom_gates"] = dict(rolled)
    # Entrance shuffle bijection: {door_subarea: interior_subarea}.
    # The Switch mod reads this to remap door loads. Absent when off.
    entrance_map = getattr(world, "_entrance_map", None)
    if entrance_map is not None:
        slot_data["entrance_map"] = entrance_map
    # Re-fight / Dark Side multi-moon bonus side-grants (see
    # _roll_mm_bonus_grants). The client folds these into the capture/ability
    # unlock paths as each Mushroom/Dark Side Multi-Moon arrives. Absent when
    # nothing was rolled (never, in practice) so old clients treat it as empty.
    bonus_captures = getattr(world, "mm_bonus_captures", None)
    if bonus_captures:
        slot_data["mm_bonus_captures"] = list(bonus_captures)
    bonus_abilities = getattr(world, "mm_bonus_abilities", None)
    if bonus_abilities:
        slot_data["mm_bonus_abilities"] = list(bonus_abilities)
    return slot_data

# This is called after slot data is set and provides the slot data at the time, in case you want to check and modify it after the world fills it
def after_fill_slot_data(slot_data: dict, world: World, multiworld: MultiWorld, player: int) -> dict:
    # When talkatoo_mode is on, ship a per-kingdom sphere-safe ordered list
    # of AP-pool moon shine_ids so the bridge can keep a per-kingdom cursor
    # + window of 3. Without this, fresh-start seeds can soft-lock when all
    # 3 Talkatoo picks in a kingdom are gated behind items not yet received.
    if not slot_data.get("talkatoo_mode"):
        return slot_data
    from ..talkatoo_order import build_talkatoo_order
    # locations.json's `progression: true` flag is the canonical source.
    # The Switch's MoonGetHook bypasses the Talkatoo block for these via
    # isProgressionShine — they're never gated by the cursor-window, so
    # don't include them in the ordered list.
    progression_names = {
        loc["name"] for loc in location_table
        if loc.get("progression", False)
    }
    slot_data["talkatoo_order"] = build_talkatoo_order(
        world, multiworld, player, progression_names)
    return slot_data

# This is called right at the end, in case you want to write stuff to the spoiler log
def before_write_spoiler(world: World, multiworld: MultiWorld, spoiler_handle) -> None:
    """Log the entrance-shuffle bijection so the spoiler tells you which physical
    door now leads to each interior subarea.

    Keyed by INTERIOR (the subarea a moon lives in), because the usual question is
    "I have a moon in interior X — which door do I take to get there?". Each block
    also lists the moons inside that interior, so Ctrl-F on a moon name lands you on
    the right block and you can read off the door above it.
    """
    bijection: dict[str, str] | None = getattr(world, "_entrance_map", None)
    if not bijection:
        return  # entrance_shuffle disabled (or nothing rolled) — nothing to log

    subareas: dict = getattr(world, "_entrance_subareas", None) or {}

    def _kingdom(sub: str) -> str:
        return (subareas.get(sub, {}) or {}).get("kingdom", "?")

    def _moons(sub: str) -> list[str]:
        return (subareas.get(sub, {}) or {}).get("location_names", [])

    try:
        slot_name = multiworld.get_player_name(player=world.player)
    except Exception:
        slot_name = str(world.player)

    # Reverse to interior -> door for the lookup the player actually does.
    interior_to_door = {interior: door for door, interior in bijection.items()}

    shuffled = sorted(
        (interior for door, interior in bijection.items() if door != interior),
        key=lambda i: (_kingdom(i), i),
    )
    unchanged = sorted(d for d, i in bijection.items() if d == i)

    spoiler_handle.write(f"\n\nEntrance Shuffle ({slot_name}):\n")
    if not shuffled:
        spoiler_handle.write("  (all entrances rolled to their vanilla interiors)\n")
    for interior in shuffled:
        door = interior_to_door[interior]
        spoiler_handle.write(
            f"\n  To reach \"{interior}\" ({_kingdom(interior)}): "
            f"use the door for \"{door}\" ({_kingdom(door)})\n"
        )
        for moon in _moons(interior):
            spoiler_handle.write(f"      moon inside: {moon}\n")
    if unchanged:
        spoiler_handle.write(
            "\n  Unchanged (door leads to its own vanilla interior): "
            + ", ".join(unchanged) + "\n"
        )
