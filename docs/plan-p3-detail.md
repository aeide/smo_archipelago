# P3 detail — ability/capture item pool + tracking

Canonical P3 record (mirrors `docs/plan-p4-detail.md`). The body below is the 2026-06-13 3a
progress snapshot that was authored for CLAUDE.md and later trimmed when the Status section was
condensed; preserved here verbatim so the provenance isn't lost.

> ⚠️ **Read as history, not live status.** This snapshot lists "P3 DEFERRED to 3b" items
> (ability classification + wire, variant cap→hack override, the new-pool tests). Those were
> **subsequently completed** — CLAUDE.md Status records **P3 COMPLETE + committed**, and P4
> (ability enforcement) is done on top of them. So treat the "deferred" section as the original
> plan, all since landed.

---

P3 progress — 3a data half COMPLETE (2026-06-13), generation-validated (756 pass; only
pre-existing test_moon_rock_checks.py failures remain — those test a separate unimplemented
Moon-Rock-checks feature, not P3). Devon decisions locked: starters = Frog + Chain Chomp + 1
random ONLY (Spark pylon & Bowser are shuffled pool items, NOT precollected); part-captures split
into all 4 variants; plan-first (see docs/plan-p3-detail.md). Done this session:

data/items.json: +20 ability items (new Ability category; Wall Slide count 2, Progressive Jump
2, Progressive Crouch 3, Progressive Ground Pound 3 = 2 chain + 1 clone, rest count 1; all
progression:true). Capture roster: split Puzzle Part → Puzzle Part (Lake Kingdom) + Puzzle Part
(Metro Kingdom), Picture Match Part → Picture Match Part (Goomba) + Picture Match Part (Mario);
added Broode's Chain Chomp, Letter, Yoshi, Spark pylon (lowercase p — exact capture_map journal
name!), Bowser; clones (count 2) for Bullet Bill, Sherm, Parabones, Banzai Bill, Spark pylon,
Bowser.

data/locations.json: +68 junk-only checks — 43 Mushroom + 24 Dark Side + 1 Darker Side, names
taken VERBATIM from bridge/smo_ap_bridge/data/shine_map.json so they match what the Switch
reports. Each tagged junk_only:true. (Mushroom = 43 distinct shines; the 61
"toadette"/purchasable-dupe moons are intentionally excluded — their vanilla locations are
always-trash, but per Devon they could be repurposed as extra capture-host locations if more are
ever needed.)

data/regions.json: Mushroom Kingdom → Dark Side → Darker Side chained off Moon Kingdom (requires
"" — loose post-game gating so junk checks stay reachable; not the vanilla 250/500-moon gate,
which could strand reachability).

data/categories.json: Ability, Mushroom Kingdom, Dark Side, Darker Side (all hidden).

hooks/World.py: _apply_junk_only_rules (filler/trap ONLY — stricter than filler_only's
no-progression) wired into after_set_rules; FESTIVAL_ITEMS_TO_DROP += Letter, Yoshi, Bowser
(post-game captures with no home in festival mode).

tests/test_moon_requirements.py: matchable_location_names fixture now exempts junk_only locations
(they have no ability-logic requirements by design).

P3 DEFERRED to 3b (Opus + smo-build session):

Ability classification + wire (intentionally NOT done in 3a — stranding it just emits messages
nothing consumes): add ItemKind.ABILITY + classify_item (client/datapackage.py keys off the
category list), an ability_unlock wire msg (use a new t= so an old Switch ignores it gracefully,
like coin_grant did), ApState::ability_unlocked bitfield + dispatch + Cappy bubble, and
duplicate→100-coins via the P1 addCoin path. Abilities are TRACKED only in P3; enforcement is P4.

Variant capture cap→hack override (load-bearing for the split). bridge/smo_ap_bridge/data/
capture_map.json keys BOTH puzzle parts as "Puzzle Part" (hacks GotogotonLake / GotogotonCity)
and BOTH picture-match parts as "Picture Match Part" (FukuwaraiFacePartsKuribo /
FukuwaraiFacePartsMario). The split AP item names are correct for generation but won't resolve
cap→hack at runtime. Add a committed override mapping the 4 variant names → their hacks in the
bridge's capture resolution (client/maps.py CaptureMap, or wherever cap_to_hack lives) so the
Switch grants the right capture. Generation does NOT depend on this.

Tests for the new pool (ability item counts, the 4 split variants, clones at count 2, ID-stability
snapshot, junk_only locations never receive progression/useful).
