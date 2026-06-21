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


# Called before regions and locations are created. Victory location is included, but Victory event is not placed yet.
def before_create_regions(world: World, multiworld: MultiWorld, player: int):
    if not is_option_enabled(multiworld, player, "entrance_shuffle"):
        return

    from ..entrance_logic import (
        build_entrance_pool, build_interior_requires_map, build_moonpipe_subarea_set,
    )

    subareas, exclusions = _load_entrance_data()
    pool = build_entrance_pool(subareas, exclusions)
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

    from ..entrance_logic import make_door_access_rule
    from worlds.generic.Rules import set_rule

    subareas: dict = world._entrance_subareas
    moonpipe: frozenset[str] = world._entrance_moonpipe
    shuffled_locs: set[str] = world._entrance_shuffled_locs

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

        # Set the door's access rule.
        is_moon_pipe = door_subarea in moonpipe  # door IS a moon-pipe opening
        rule = make_door_access_rule(
            door_subarea, subareas.get(door_subarea, {}).get("kingdom", ""),
            is_moon_pipe, world, multiworld, player
        )
        set_rule(entrance, rule)

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
def before_create_items_filler(item_pool: list, world: World, multiworld: MultiWorld, player: int) -> list:
    # multi_moon_shuffle: under the FESTIVAL goal, "Metro: A Traditional
    # Festival!" is the victory location and can't hold an item, leaving
    # 14 Multi-Moon items for only 13 fillable MM locations. Drop ONE Metro
    # Multi-Moon (Metro has two) to balance the matching; adjust_filler_items
    # tops the freed slot back up with filler.
    # Under any other goal the festival is a real 14th MM location (it
    # survived __init__.create_regions as a normal check), so 14 items match
    # 14 locations exactly — no drop.
    if (is_option_enabled(multiworld, player, "multi_moon_shuffle")
            and get_option_value(multiworld, player, "goal") == 1):  # festival
        for i, it in enumerate(item_pool):
            if it.name == "Metro Kingdom Multi-Moon":
                item_pool.pop(i)
                break
    # abilitysanity OFF: strip the Ability-category items from the pool (the
    # freed slots are topped up with filler by adjust_filler_items, same as the
    # moon-count trim below). Runs here so the reduced pool flows into
    # adjust_filler_items / after_create_items unchanged when the option is on.
    _drop_ability_items_if_disabled(item_pool, world, multiworld, player)
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
    return item_pool

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
    locations, and vice versa — a closed 14<->14 matching (the pinned Ruined
    Multi-Moon is one fixed point of it; the other 13 float).

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


# Called after rules for accessing regions and locations are created, in case you want to see or modify that information.
def after_set_rules(world: World, multiworld: MultiWorld, player: int):
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
    if is_option_enabled(multiworld, player, "entrance_shuffle"):
        _apply_entrance_shuffle_location_rules(world, multiworld, player)
        # D3: re-apply the interior-intrinsic scenario gates that the rule
        # replacement above stripped from pooled-subarea moons. MUST run after
        # _apply_entrance_shuffle_location_rules (which set_rule-REPLACES the rule);
        # add_rule here ANDs the scenario gate back on top.
        _apply_subarea_scenario_gates(world, multiworld, player)
    # Must run last so it wins over the access rules set in set_rules.
    if is_option_enabled(multiworld, player, "no_logic"):
        _apply_no_logic(world, multiworld, player)


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
    pass
