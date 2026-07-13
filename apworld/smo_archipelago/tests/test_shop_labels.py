"""Tests for the Crazy Cap shop-label channel (shop_labels.py + the
Connected-handler wiring in context.py).

Regression context (2026-07-13 playtest bug): a purchased shop moon's
PRE-purchase label read "Lost Kingdom Power Moon" but the check that was
actually reported/granted was a "Cap Kingdom Power Moon". Two independent
things were audited to find and pin this down:

  1. Static data agreement — SHOP_LOCATION_TO_FILEKEY's per-kingdom
     (file_name, key) guesses vs. the real "<Kingdom>: Shopping in <City>"
     location set in locations.json. This audit found Mushroom and Moon
     Kingdom shop locations were silently missing from the table (the
     module's own comment incorrectly claimed those kingdoms have no
     shop) — a real coverage gap, fixed alongside this test, but NOT the
     Lost/Cap mismatch itself (the 11 pre-existing entries' stage-prefix
     guesses all check out against a real shine_table.h snapshot).

  2. The actual root cause: `_derive_and_push_shop_labels()` (called near
     the top of the Connected handler in context.py) reads `scout_cache`
     synchronously, but the cache is only cleared/re-warmed LATER in that
     same handler (the `request_scout` call further down). Location ids
     are stable across a reconnect/reseed (same location-name set) but
     the item AT each id is per-seed — so a scout_cache entry left over
     from a prior seed is stale at the moment of that first read, and
     gets pushed to the Switch as a real (if wrong) label instead of
     degrading to "no label yet". The fix clears `scout_cache`
     unconditionally at the top of the Connected handler, before any
     label composition can read it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APWORLD_ROOT = Path(__file__).resolve().parents[1]

from client.shop_labels import SHOP_LOCATION_TO_FILEKEY  # noqa: E402


# ---- Part A: static data-agreement tests (no AP / Archipelago needed) -----


def _load_locations() -> list[dict]:
    return json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8")
    )


def _shopping_location_names() -> set[str]:
    """Every AP location that follows the "<Kingdom>: Shopping ..." shop
    convention — the authoritative set SHOP_LOCATION_TO_FILEKEY must cover."""
    return {
        loc["name"] for loc in _load_locations()
        if ": Shopping" in loc.get("name", "")
    }


def test_every_shop_labels_entry_matches_a_real_location():
    """Every key in the static table must be a real AP location name — a
    typo'd or stale key silently never overrides anything (falls through
    to vanilla text) instead of failing loudly."""
    real_names = {loc["name"] for loc in _load_locations()}
    for ap_loc_name in SHOP_LOCATION_TO_FILEKEY:
        assert ap_loc_name in real_names, (
            f"{ap_loc_name!r} is not a location in locations.json — "
            "typo, rename, or stale entry"
        )


def test_every_shopping_location_has_a_shop_labels_entry():
    """Regression for the Mushroom/Moon gap: every "<Kingdom>: Shopping
    ..." location in locations.json must have a SHOP_LOCATION_TO_FILEKEY
    entry, even if its (file_name, key) tuple isn't verified yet. A
    location present in-game but absent from the table gets zero label
    coverage with no signal that anything is missing."""
    missing = _shopping_location_names() - set(SHOP_LOCATION_TO_FILEKEY)
    assert not missing, (
        f"locations.json has shop location(s) with no shop_labels.py "
        f"entry: {sorted(missing)}"
    )


def test_shop_labels_table_has_no_locations_outside_the_real_set():
    """Inverse of the above — catches a table entry for a location that
    doesn't (or no longer) exist as a "Shopping" location."""
    extra = set(SHOP_LOCATION_TO_FILEKEY) - _shopping_location_names()
    assert not extra, (
        f"shop_labels.py has entries for non-shop or unknown "
        f"location(s): {sorted(extra)}"
    )


def test_file_key_tuples_are_unique_per_location():
    """No two different AP shop locations may share a (file_name, key)
    pair. If they did, the Switch's ShopItemMessageHook would substitute
    ONE location's scouted content for BOTH physical shop stages — the
    exact "label describes a different location's item than what's
    actually behind this slot" failure mode this bug report describes."""
    seen: dict[tuple[str, str], str] = {}
    for ap_loc_name, key in SHOP_LOCATION_TO_FILEKEY.items():
        if not key[0] or not key[1]:
            continue  # unpopulated placeholder, not a real collision risk
        prior = seen.get(key)
        assert prior is None, (
            f"(file,key)={key!r} is assigned to both {prior!r} and "
            f"{ap_loc_name!r} — the Switch can only show one location's "
            "content for this slot"
        )
        seen[key] = ap_loc_name


# ---- Part B: regression test for the scout_cache staleness bug ------------


def _find_archipelago() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "vendor" / "Archipelago"
        if (cand / "CommonClient.py").exists():
            return cand
        worktrees = parent.parent
        if worktrees.name == "worktrees":
            main_cand = worktrees.parent.parent / "vendor" / "Archipelago"
            if (main_cand / "CommonClient.py").exists():
                return main_cand
    return None


_AP = _find_archipelago()
if _AP is not None and str(_AP) not in sys.path:
    sys.path.insert(0, str(_AP))

try:  # pragma: no cover
    import ModuleUpdate  # type: ignore[import-not-found]
    ModuleUpdate.update_ran = True
except ImportError:
    pass

pytest.importorskip(
    "CommonClient",
    reason="Archipelago checkout not present; init the vendor/Archipelago submodule.",
)

from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


class _StubSwitch:
    """Minimal switch surface for the Connected handler, extended (beyond
    test_slot_change_reset.py's stub) with every method the handler calls
    when `display_enabled=True` drives `_derive_and_push_shop_labels` all
    the way through."""

    def __init__(self) -> None:
        self.shop_label_pushes: list[list[dict]] = []
        # Current active table as last actually pushed to the "Switch" —
        # unlike shop_label_pushes (append-only history), this reflects
        # what a real Switch's lookupShopLabel would answer right now.
        # context.py's own dedup means a call that computes the SAME
        # entries as last time never reaches push_shop_labels() at all,
        # so this can go stale (on purpose) across a suppressed push —
        # which is exactly the state we need to inspect for the
        # regression below.
        self.current_shop_labels: list[dict] = []

    def set_capturesanity_enabled(self, enabled: bool) -> None:
        pass

    async def push_capturesanity_replay(self) -> None:
        pass

    def set_abilitysanity_enabled(self, enabled: bool) -> None:
        pass

    async def push_ability_state(self) -> None:
        pass

    def set_deathlink_enabled(self, enabled: bool) -> None:
        pass

    async def push_deathlink_helloack(self) -> None:
        pass

    def set_talkatoo_pool(self, mode: bool, pool: dict) -> None:
        pass

    async def push_talkatoo_pool(self) -> None:
        pass

    def set_kingdom_gates(self, gates: dict) -> None:
        pass

    async def push_kingdom_gates(self) -> None:
        pass

    def set_cap_peace_start(self, enabled: bool) -> None:
        pass

    async def push_cap_peace_start(self) -> None:
        pass

    def set_entrance_map(self, mapping: dict) -> None:
        pass

    def set_port_matching(self, mapping: dict) -> None:
        pass

    async def push_entrance_map(self) -> None:
        pass

    def set_shop_labels(self, entries: list[dict]) -> None:
        self.current_shop_labels = entries

    async def push_shop_labels(self) -> None:
        self.shop_label_pushes.append(list(self.current_shop_labels))

    async def send_ap_state(self, conn: str) -> None:
        pass

    async def drain_pending_snapshot(self) -> None:
        pass


def _make_ctx() -> tuple[SMOContext, BridgeState, _StubSwitch]:
    state = BridgeState()
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=state,
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
        display_enabled=True,  # required: compose_shop_label_for_location
                                # early-returns None when this is False.
    )
    ctx.colors.enabled = False
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]
    return ctx, state, sw


def _label_for(entries: list[dict], key: tuple[str, str]) -> str | None:
    for e in entries:
        if (e["file"], e["key"]) == key:
            return e["label"]
    return None


CAP_KEY = SHOP_LOCATION_TO_FILEKEY["Cap: Shopping in Bonneton"]


def _cap_loc_id(ctx: SMOContext) -> int:
    """Real AP location id for Cap's shop location. `CommonContext`
    pre-populates `location_names`/`item_names` for every locally
    registered game (SMO's own AutoWorldRegister entry included), and
    `_populate_datapackage_from_self()` (run every Connected) mirrors that
    into `ctx.dp` — so the real static id is already available after the
    first Connected without needing a live AP server."""
    return ctx.dp.location_name_to_id["Cap: Shopping in Bonneton"]


def _cap_item_id(ctx: SMOContext) -> int:
    return ctx.dp.item_name_to_id["Cap Kingdom Power Moon"]


def _lost_item_id(ctx: SMOContext) -> int:
    return ctx.dp.item_name_to_id["Lost Kingdom Power Moon"]


@pytest.mark.asyncio
async def test_connected_then_scout_arrival_reflects_the_scouted_item():
    """Sanity / production-shaped happy path: Connected fires first (scout
    cache is necessarily still cold — real scouting is a network
    round-trip that can't complete before Connected returns), THEN a
    LocationInfo-equivalent scout reply arrives and re-derives the shop
    labels. Mirrors the real two-call-site design documented on
    `_derive_and_push_shop_labels`."""
    ctx, _state, sw = _make_ctx()
    ctx.auth = "PlayerA"
    # format_shop_moon_label reads "for <recipient>" whenever the scouted
    # item's recipient slot doesn't match ctx.auth; route it to "self" here
    # so the composed label is the bare item name, not truncated "... for
    # <name>" text — irrelevant to what this test is checking.
    ctx.player_names[0] = "PlayerA"

    await ctx._handle_ap_package("Connected", {"slot_data": {}})
    assert _label_for(sw.current_shop_labels, CAP_KEY) is None  # cold cache, degrades safely

    # Scout reply for this seed arrives (the LocationInfo call site does
    # exactly this: absorb, then re-derive).
    ctx.scout_cache.absorb(_cap_loc_id(ctx), item=_cap_item_id(ctx), recipient=0)
    await ctx._derive_and_push_shop_labels()

    assert _label_for(sw.current_shop_labels, CAP_KEY) == "Cap Kingdom Power Moon"


@pytest.mark.asyncio
async def test_reconnect_does_not_leak_stale_scout_cache_into_shop_label_push():
    """The actual regression. Seed A's shop scout (item 5002, "Lost
    Kingdom Power Moon") is absorbed and pushed while connected to seed A.
    The player then reconnects under the SAME slot to a freshly generated
    seed B — a routine reconnect in this project's regen loop. Location
    ids are stable across reseeds, so `scout_cache`'s seed-A entry at
    CAP_LOC_ID isn't naturally invalidated by anything else in the
    handler, and seed B's real scout for that location hasn't arrived yet
    (it's a fresh network round-trip that starts only after Connected
    returns).

    Before the fix: `_derive_and_push_shop_labels()` (called near the top
    of the Connected handler) reads the stale `scout_cache` before it's
    ever cleared, recomputes the SAME entries as seed A's last push, and
    context.py's dedup-by-signature then suppresses re-sending them — so
    the Switch is left showing seed A's "Lost Kingdom Power Moon" label
    for a slot that seed B actually fills with something else. The label
    never self-corrects until a fresh scout for that exact location
    happens to arrive.

    After the fix: `scout_cache` is cleared unconditionally at the top of
    the Connected handler, so the first push after reconnecting to seed B
    computes a DIFFERENT (empty) signature, is NOT suppressed, and
    actively clears the stale entry instead of leaving it live.
    """
    ctx, _state, sw = _make_ctx()

    # Seed A: Cap's shop slot legitimately scouted to hold a "Lost Kingdom
    # Power Moon" item — a perfectly normal AP fill (items aren't tied to
    # the kingdom of the location they're placed at).
    ctx.auth = "PlayerA"
    # format_shop_moon_label reads "for <recipient>" whenever the scouted
    # item's recipient slot doesn't match ctx.auth; route it to "self" here
    # so the composed label is the bare item name, not truncated "... for
    # <name>" text — irrelevant to what this test is checking.
    ctx.player_names[0] = "PlayerA"
    await ctx._handle_ap_package("Connected", {"slot_data": {}})
    ctx.scout_cache.absorb(_cap_loc_id(ctx), item=_lost_item_id(ctx), recipient=0)
    await ctx._derive_and_push_shop_labels()
    assert _label_for(sw.current_shop_labels, CAP_KEY) == "Lost Kingdom Power Moon"

    # Reconnect under the same slot to a freshly generated seed B. No new
    # scout has arrived for CAP_LOC_ID yet — only the reconnect itself has
    # happened so far, exactly like the moment a player walks toward a
    # shop right after a regen+reconnect.
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    current_label = _label_for(sw.current_shop_labels, CAP_KEY)
    assert current_label != "Lost Kingdom Power Moon", (
        "shop label channel still shows a stale scout_cache entry from "
        "the previous seed after a reconnect — this is the 2026-07-13 "
        "label/grant mismatch bug (label predicted one kingdom's item, "
        "the actual purchase grants whatever the new seed really placed "
        "there)"
    )
