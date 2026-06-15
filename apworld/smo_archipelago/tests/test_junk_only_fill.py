"""Regression guards for the P3 junk_only fill economy.

Background (2026-06-14): P3 added 67 `junk_only` Mushroom/Dark Side/Darker Side
locations whose item rule rejects BOTH advancement AND useful items — only
filler/traps may land there. Re-enabling the capture items (which had been
wrongly dropped from the pool) pushed the non-filler item count past the number
of non-junk locations, and `_demote_surplus_kingdom_moons` was classifying the
surplus kingdom moons as `useful`, which junk_only slots also reject. Result:
`remaining_fill` "No more spots to place N items" with ~47 moons unplaced and
the junk_only locations unfilled.

Fix: surplus kingdom moons are demoted to `filler` (not `useful`) so they can
fill the junk_only slots. These source-parse checks guard the invariant without
needing a live Archipelago generation (the full check is the SMOAP_LIVE_AP
generation sweep in test_apworld_generation.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


def _world_src() -> str:
    return (APWORLD_ROOT / "hooks" / "World.py").read_text(encoding="utf-8")


def _demote_body() -> str:
    src = _world_src()
    m = re.search(
        r"def _demote_surplus_kingdom_moons\b(.+?)(?=\ndef )", src, re.DOTALL
    )
    assert m, "_demote_surplus_kingdom_moons not found in hooks/World.py"
    return m.group(1)


def test_surplus_moons_demoted_to_filler_not_useful():
    body = _demote_body()
    assert "ItemClassification.filler" in body, (
        "_demote_surplus_kingdom_moons must classify surplus moons as filler so "
        "they can fill the 67 junk_only locations."
    )
    # No `classification = ItemClassification.useful` assignment may remain —
    # useful items are rejected by junk_only locations.
    assert not re.search(
        r"classification\s*=\s*ItemClassification\.useful", body
    ), (
        "_demote_surplus_kingdom_moons still demotes to useful; useful items "
        "cannot fill junk_only locations (causes remaining_fill FillError)."
    )


def test_junk_only_rule_blocks_advancement_and_useful():
    src = _world_src()
    m = re.search(
        r"def _apply_junk_only_rules\b(.+?)(?=\ndef )", src, re.DOTALL
    )
    assert m, "_apply_junk_only_rules not found in hooks/World.py"
    body = m.group(1)
    # The item rule must reject both advancement and useful (filler/trap only).
    assert "not item.advancement" in body and "not item.useful" in body, (
        "junk_only item rule must reject both advancement and useful items."
    )


def test_junk_only_location_count_nonzero():
    """Sanity: the junk_only locations exist (the thing that needs filler)."""
    locs = json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8")
    )
    junk = [l for l in locs if l.get("junk_only")]
    assert len(junk) >= 60, f"expected ~67 junk_only locations, found {len(junk)}"
