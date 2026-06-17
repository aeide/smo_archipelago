"""AP ability-item -> concrete in-game move mapping.

The AP item pool ships *ability items* (some progressive — they arrive
multiple times and each receipt unlocks the next move in a chain). The
player thinks in terms of the actual moves (Crouch, Roll, Roll Boost),
not the pool item name ("Progressive Crouch"), so both the Odyssey-tab
"Abilities owned" list and the in-game unlock bubble translate through
this table.

THIS TABLE IS MIRRORED IN C++ at switch-mod/src/ap/ApState.cpp
(abilityMoveAtLevel). Keep the two in sync — the level ordering here is
the load-bearing contract that maps a received count to a move, and it
must match the gating thresholds in AbilityGateHook.cpp:

    Progressive Crouch        >=1 Crouch  >=2 Roll  >=3 Roll Boost
    Progressive Ground Pound  >=1 Ground Pound  >=2 Dive   (>=3 clone)
    Progressive Jump          >=1 Double Jump   >=2 Triple Jump
    Wall Slide                >=1 Wall Slide    (>=2 clone)

Counts beyond the listed moves are duplicate "clone" copies that convert
to coins (see state.compute_total_coin_grant) and unlock no new move.
"""

from __future__ import annotations

# Progressive / multi-grant items: 1-indexed level -> move name, in the
# order the levels arrive. A received count of N means the player owns
# moves[:N] (clamped). Items NOT in this table are single-grant: the move
# name equals the item name and any extra copies are clones (coins only).
PROGRESSIVE_MOVES: dict[str, list[str]] = {
    "Progressive Crouch": ["Crouch", "Roll", "Roll Boost"],
    "Progressive Ground Pound": ["Ground Pound", "Dive"],
    "Progressive Jump": ["Double Jump", "Triple Jump"],
    "Wall Slide": ["Wall Slide"],
}


def moves_owned(item_name: str, count: int) -> list[str]:
    """Concrete moves unlocked by owning `count` copies of `item_name`.

    For a progressive item, the first `count` levels (clamped to the
    chain length). For a single-grant item, the move == the item name
    once `count >= 1` (extra copies are clones and add no move).
    """
    if count <= 0 or not item_name:
        return []
    chain = PROGRESSIVE_MOVES.get(item_name)
    if chain is None:
        return [item_name]
    return chain[:count]


def newly_unlocked_move(item_name: str, new_count: int) -> str | None:
    """The move unlocked when an item's count rises TO `new_count`.

    Returns None when reaching `new_count` unlocks no new move (a clone
    copy past the end of the chain) — the unlock bubble should fall back
    to a duplicate/coins message in that case. Mirrors the C++ unlock
    bubble in ApState.cpp::applyAbilityState.
    """
    if new_count <= 0 or not item_name:
        return None
    chain = PROGRESSIVE_MOVES.get(item_name)
    if chain is None:
        # Single-grant: only the first copy unlocks the move.
        return item_name if new_count == 1 else None
    if new_count <= len(chain):
        return chain[new_count - 1]
    return None
