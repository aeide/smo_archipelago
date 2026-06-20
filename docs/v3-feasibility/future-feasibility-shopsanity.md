# Shopsanity — golden / purple / full (Devon, 2026-06-20)

**Goal.** Add a YAML `shopsanity` option (`golden` / `purple` / `full`, plus off) that
turns Crazy Cap shop slots into AP checks:

- **`golden`** — the gold-coin shop's **outfits** (NOT the first two slots: the
  Life-Up Heart and the already-shuffled Power Moon) become **filler** checks; buying
  a slot fires the check. Optionally randomize their coin costs from YAML. Purpose:
  make gold coins meaningful.
- **`purple`** — each kingdom's **regional (purple-coin) shop** outfits, stickers, and
  trophies become **filler** checks (a few exceptions). Purpose: make purple coins
  meaningful. **Exception:** 11 moons require specific regional outfits (always a
  hat + an outfit, always the first two purchasable items in that shop). Those outfit
  items stay in the pool as **useful** items (progression only when their gated
  moon/entrance does), and the gated moon gets a logic rule requiring them.
- **`full`** — both.

**Status: investigated, NOT started. Estimate ~75% feasible, HIGH effort.** Every
piece has a clear path and — crucially — the load-bearing Switch chokepoints already
exist as **decompiled** functions; the cost is breadth (apworld data + a new wire/table
tier + the 11-moon logic), not a fundamental unknown.

---

## What already exists

- The apworld already models the shop **Power Moon** per kingdom as an AP location
  ("`<Kingdom>: Shopping in <City>`", 11 kingdoms with shops — see
  [client/shop_labels.py](../../apworld/smo_archipelago/client/shop_labels.py) and
  [data/locations.json](../../apworld/smo_archipelago/data/locations.json)). So
  "a shop slot is an AP check" is a shape the project already supports — but only for
  the Moon slot, which is detected as a normal shine collection (MoonGetHook), not via
  a shop-purchase hook.
- [ShopItemMessageHook.cpp](../../switch-mod/src/hooks/ShopItemMessageHook.cpp) already
  patches the shop's item-label text sites (`ShopLayoutInfo::updateItemPartsData` →
  `al::getSystemMessageString`), so we already know how to read/override what a shop
  slot displays. That's the same UI surface a shopsanity label would ride.
- [AddPayShineHook.cpp](../../switch-mod/src/hooks/AddPayShineHook.cpp) already handles
  purple-coin (`addPayShine`) accounting — the purple-coin currency plumbing is known.

## The decisive finding: clean, decompiled purchase chokepoints

[ClothUtil.h](../../switch-mod/lib/OdysseyHeaders/game/Util/ClothUtil.h) exposes exactly
what shopsanity needs, as ordinary (decompiled) `ClothUtil::` free functions:

- **Detect a purchase:** `buyItem(user, const ShopItem::ItemInfo*)`,
  `buyItemInShopItemList(user, itemIdx)`, `buyCloth(user, clothName)`. `buyItem` looks
  like a single chokepoint for all purchasable types — the `ItemInfo` carries the
  item's identity and `ShopLayoutInfo`'s `enum ItemType { Cloth, Cap, Gift, Sticker,
  UseItem, Moon }` tags what it is. (Per CLAUDE.md, verify it's not inlined before
  committing a hook — but it's a Util free function called from the shop UI, the kind
  that stays out-of-line.)
- **Query owned state (for HELLO replay / save reconciliation):**
  `isBuyItem(accessor, ItemInfo*)`, `isHaveCloth(...)`, and the full catalogs
  `getClothList` / `getCapList` / `getGiftList` / `getStickerList`
  (+ `GameDataHolder::mItemCloth/mItemCap/mItemGift/mItemSticker`). So the Switch can
  enumerate every shop item and whether it's been bought — the same way the shine
  snapshot enumerates owned moons.
- **Grant an outfit on AP item receipt (for the 11 gating outfits):**
  `buyCloth(user, clothName)` / registering into the cloth list — so an outfit
  delivered as an AP item can be made functionally wearable.

This is a fundamentally more favorable situation than the coin-model swap: these are
documented, decompiled APIs with clear signatures, not an undecompiled actor body.

---

## What has to be built

### 1. apworld (medium, the breadth is data)

- **Option** `shopsanity` (Choice: off/golden/purple/full) in
  [hooks/Options.py](../../apworld/smo_archipelago/hooks/Options.py); optional
  cost-randomization sub-options.
- **Locations** for each shuffled shop slot, gated behind the option
  ([hooks/Helpers.py](../../apworld/smo_archipelago/hooks/Helpers.py)
  `before_is_location_enabled`, the same opt-out pattern capturesanity uses). Names
  must match whatever identity the Switch reports (see the table tier below).
- **The 11 gating outfits as `useful` items** + a logic rule on each gated moon
  (`requires` referencing the outfit item). Devon to supply the 11-moon ↔ outfit list.
  This is ordinary Rules.py/regions work once the list exists.
- **Cost randomization** (optional): roll per-slot costs, ship them to the Switch
  (slot_data → wire), the Switch overrides the displayed/charged price.

### 2. The "slot availability" data problem (the golden wrinkle Devon flagged)

The gold-coin shop's outfit catalog **unlocks progressively as you reach new
kingdoms** — SMO even has `GameDataFunction::getWorldNumForNewReleaseShop` /
`getWorldIdForNewReleaseShop`, i.e. each new-release outfit is tied to a world number.
So each golden-shop location needs a **logic gate "reached kingdom N."** This requires
a static list: *slot → (kingdom/world it unlocks at)*. It's enumerable (the runtime
`getShopItemInfoList` + the new-release world id give it), and Devon offered to build
the list. The purple shops are simpler (each kingdom's regional catalog is available
once you're in that kingdom), but still need a per-kingdom slot list.

**IP note:** displayed item names are Nintendo strings; the internal cloth identifiers
(passed to `buyCloth`) are functional. Treat any extracted name table like
`shine_map`/`capture_map` — gitignored, regenerated locally; the join table that maps
shop identity → AP location is the `shine_table.h`/`capture_table.h` analogue and
follows the same IP regime.

### 3. Switch tier (medium–high, but chokepoints are known)

- **New hook on `ClothUtil::buyItem`** (and/or `buyItemInShopItemList`): on purchase,
  resolve `ItemInfo` → AP location and send a `check`. Reuse `CheckMsg` with a new
  `kind` ("shop") carrying the item identity (cloth name / type+index) — additive,
  fixed-buffer safe.
- **New `shop_table.h`** (auto-generated, gitignored) joining shop-item identity →
  AP location id — the direct analogue of `shine_table.h`/`capture_table.h`, generated
  by a new `sync_shop_table.py` from `locations.json` × an extracted shop map.
- **Snapshot/replay:** extend the HELLO state snapshot to enumerate bought shop items
  (`isBuyItem` over the four lists) so an offline purchase replays on reconnect — same
  mechanism as owned shines.
- **Grant path:** on receiving an outfit AP item, call `buyCloth`/register it so the
  11 gating outfits become wearable.
- **Gating-outfit handling (design care):** for the 11, buying the in-shop slot must
  NOT also free-grant the wearable outfit (or the "useful item" gate is bypassed).
  Options: drop those 2 slots from the check set and keep them as item-granted-only, or
  suppress the vanilla unlock on those slots and require the AP item. Decide per the
  list.
- **Cost override** (if cost-rando on): override the `ItemInfo` price read / the charge
  site. The price lives on `ItemInfo`; needs a read or charge hook.

### 4. Wire + client

- `CheckMsg` shop kind (additive). Client maps it to the location id via the
  datapackage, exactly like moon/capture checks today.
- Cost-rando values flow slot_data → a small wire message (like `kingdom_gates`).
- Shop labels (optional polish): reuse the ShopItemMessageHook surface to show the AP
  item name in the slot, like the existing shop-moon label substitution.

---

## Risks / unknowns (why 75%, not higher)

- **Breadth, not depth.** The mechanism is proven (decompiled chokepoints), but the
  feature spans apworld options + locations + items + logic, a new wire kind, a new
  generated table + extractor, snapshot/replay extension, and a grant path. That's a
  lot of surface to get right — high effort, more places to bug.
- **Slot enumeration + unlock timing** must be accurate or locations become
  unreachable (an outfit gated behind a kingdom the logic doesn't know about). Mitigated
  by Devon's lists + runtime catalogs, but it's the main correctness risk.
- **The 11 gating outfits** need careful in-game handling so the useful-item gate
  isn't bypassed by simply buying the slot. Solvable, but a design decision per slot.
- **`buyItem` inline check** — verify out-of-line before hooking (CLAUDE.md rule).
- **Save reconciliation** — bought items persist in the SMO save; the snapshot must
  reconcile them on HELLO like shines, or re-buying re-fires checks (or never fires
  after an offline buy). The `isBuyItem` enumeration covers this but must be wired.
- **Cost rando + currency** — purple slots charge purple coins, gold slots gold coins;
  cost override must target the right currency and not break the shop's affordability UI.

---

## Recommendation

Strong candidate — the hard part (Switch-side purchase detection) is already a solved
shape in SMO's decompiled `ClothUtil`. Suggested order: (1) **`purple` first** — it's
per-kingdom and self-contained, and exercises the whole new tier (hook → table →
wire → check → snapshot) on a bounded slot set; fold in the 11 gating outfits once the
core works. (2) Then **`golden`**, which adds the progressive new-release unlock-timing
logic on top. (3) `full` is just both enabled. Build the `ClothUtil::buyItem` hook +
`shop_table` extractor first as a spike to de-risk the data/identity mapping before the
apworld breadth.

**Why ~75%:** feasible with known chokepoints and a direct analogue to the existing
shine/capture table+hook+snapshot machinery, but it's a wide, multi-tier feature with
real data-accuracy and gating-design risk — high effort, several independent places to
get right.

Sources consulted (disk-truth reads this session):
[ClothUtil.h](../../switch-mod/lib/OdysseyHeaders/game/Util/ClothUtil.h),
[ShopLayoutInfo.h](../../switch-mod/lib/OdysseyHeaders/game/Layout/ShopLayoutInfo.h),
[GameDataHolder.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataHolder.h),
[GameDataFunction.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h),
[ShopItemMessageHook.cpp](../../switch-mod/src/hooks/ShopItemMessageHook.cpp),
[client/shop_labels.py](../../apworld/smo_archipelago/client/shop_labels.py),
[data/locations.json](../../apworld/smo_archipelago/data/locations.json).
