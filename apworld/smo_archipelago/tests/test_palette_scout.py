"""Tests for SMOContext._push_palette_for_scout_batch — the per-shine
palette derivation that drives ShineAppearanceHook's in-world moon recolor.

Regression (2026-06-22): own-slot ABILITY and CAPTURE checks were falling
through to the AP classification color. Since both are progression items,
they rendered as the animated progression gradient (green<->#316b84) that
is meant for FOREIGN-game items. Devon wants own abilities to read as Dark
Side power moons (tan #e4bb8f -> palette "Dark") and own captures to read
as Mushroom Kingdom power moons (gold -> palette "Mushroom"). Own moons were
already colored by their granted kingdom; foreign items keep the
classification color.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


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

from client.config import ColorsConfig  # noqa: E402
from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


# Resolved palette indices the C++ ShineAppearanceHook renders:
#   Dark     -> static tan tint #e4bb8f (NOT the animated cycle).
#   Mushroom -> vanilla frame 0 (authentic gold).
#   Cap      -> the granted-kingdom block entry.
_DARK = ColorsConfig().for_kingdom("Dark")
_MUSHROOM = ColorsConfig().for_kingdom("Mushroom")
_CAP = ColorsConfig().for_kingdom("Cap")
_PROGRESSION = ColorsConfig().progression


def _make_ctx() -> tuple[SMOContext, list[dict[int, int]]]:
    """SMOContext wired so _push_palette_for_scout_batch can run offline.

    Returns the context and a list that captures each batch handed to
    send_shine_scouts (the wire push), so tests assert on the pushed
    {shine_uid: palette_index} mapping directly.
    """
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
        display_enabled=False,
    )
    ctx.colors.enabled = True
    ctx.slot = 1  # our own slot number

    # --- datapackage: four moon CHECKS, each granting a different item ---
    # All four physical locations are moon checks (the recolor only touches
    # ItemKind.MOON locations). The GRANTED item is what decides the color.
    ctx.dp.location_id_to_name = {
        1000: "Cascade: Ability Check",
        1001: "Cascade: Capture Check",
        1002: "Cascade: Moon Check",
        1003: "Cascade: Foreign Check",
    }
    ctx.dp._location_categories = {
        name: ["Cascade Kingdom"] for name in ctx.dp.location_id_to_name.values()
    }
    ctx.dp.item_id_to_name = {
        1: "Backflip",                 # own ability
        2: "Goomba",                   # own capture
        3: "Cap Kingdom Power Moon",   # own moon
        4: "Some Foreign Item",        # foreign-game item
    }
    ctx.dp._item_categories = {
        "Backflip": ["Ability"],
        "Goomba": ["Capture"],
        "Cap Kingdom Power Moon": ["Moon"],
        # foreign item intentionally absent — classify_item -> OTHER, but it
        # belongs to another slot so it never reaches classify_item anyway.
    }

    # --- shine_map: each check's (kingdom, shine_id) -> a unique shine_uid ---
    ctx.shine_map._uid_by_location = {
        ("Cascade", "Ability Check"): 5001,
        ("Cascade", "Capture Check"): 5002,
        ("Cascade", "Moon Check"): 5003,
        ("Cascade", "Foreign Check"): 5004,
    }

    pushed: list[dict[int, int]] = []

    async def _capture(batch: dict[int, int]) -> None:
        pushed.append(dict(batch))

    ctx.send_shine_scouts = _capture
    return ctx, pushed


def _scout_args() -> dict:
    # NetworkItem-shaped dicts: own items use our slot (player=1); the
    # foreign item is another player (player=2) and carries the progression
    # flag bit (1) so the classification fallback resolves to progression.
    return {
        "locations": [
            {"location": 1000, "item": 1, "player": 1, "flags": 1},
            {"location": 1001, "item": 2, "player": 1, "flags": 1},
            {"location": 1002, "item": 3, "player": 1, "flags": 1},
            {"location": 1003, "item": 4, "player": 2, "flags": 1},
        ]
    }


@pytest.mark.asyncio
async def test_own_ability_colored_dark_side_tan():
    ctx, pushed = _make_ctx()
    await ctx._push_palette_for_scout_batch(_scout_args())
    assert pushed, "expected a palette batch to be pushed"
    palette = pushed[-1]
    assert palette[5001] == _DARK


@pytest.mark.asyncio
async def test_own_capture_colored_mushroom_gold():
    ctx, pushed = _make_ctx()
    await ctx._push_palette_for_scout_batch(_scout_args())
    palette = pushed[-1]
    assert palette[5002] == _MUSHROOM


@pytest.mark.asyncio
async def test_own_moon_colored_by_granted_kingdom():
    ctx, pushed = _make_ctx()
    await ctx._push_palette_for_scout_batch(_scout_args())
    palette = pushed[-1]
    assert palette[5003] == _CAP


@pytest.mark.asyncio
async def test_foreign_item_keeps_classification_color():
    ctx, pushed = _make_ctx()
    await ctx._push_palette_for_scout_batch(_scout_args())
    palette = pushed[-1]
    assert palette[5004] == _PROGRESSION


@pytest.mark.asyncio
async def test_ability_and_capture_never_get_progression_gradient():
    """The crux of the regression: own ability/capture must NOT resolve to
    the progression classification index (the animated foreign-game cycle)."""
    ctx, pushed = _make_ctx()
    await ctx._push_palette_for_scout_batch(_scout_args())
    palette = pushed[-1]
    assert palette[5001] != _PROGRESSION  # ability
    assert palette[5002] != _PROGRESSION  # capture
