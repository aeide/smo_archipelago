-- SMO Archipelago — Archipelago autotracker glue.
-- Mappings (ITEM_MAPPING, LOCATION_MAPPING) are in scripts/mappings.lua.

-- KINGDOM_PREFIXES — for the per-item kingdom_credits composite recompute.
local KINGDOM_PREFIXES = {
  "cap", "cascade", "sand", "lake", "wooded", "cloud", "lost",
  "metro", "snow", "seaside", "luncheon", "ruined", "bowser_s",
  "moon", "mushroom",
}

local function recompute_kingdom_credits(prefix)
  local pm = Tracker:FindObjectForCode(prefix .. "_kingdom_power_moon")
  local mm = Tracker:FindObjectForCode(prefix .. "_kingdom_multi_moon")
  local credits = Tracker:FindObjectForCode(prefix .. "_credits")
  if credits then
    local pm_c = (pm and pm.AcquiredCount) or 0
    local mm_c = (mm and mm.AcquiredCount) or 0
    credits.AcquiredCount = pm_c + 3 * mm_c
  end
end

local function recompute_all_credits()
  for _, p in ipairs(KINGDOM_PREFIXES) do recompute_kingdom_credits(p) end
end

local function kingdom_of_code(code)
  for _, p in ipairs(KINGDOM_PREFIXES) do
    if code == (p .. "_kingdom_power_moon") or code == (p .. "_kingdom_multi_moon") then
      return p
    end
  end
  return nil
end

-- onClear runs on every (re)connect. Reset the tracker state, then snap
-- the OPTIONS table to match the player's seed via slot_data so logic
-- evaluates correctly against the YAML they actually generated with.
function onClear(slot_data)
  for _, mapping in pairs(ITEM_MAPPING) do
    local obj = Tracker:FindObjectForCode(mapping[1])
    if obj then
      if mapping[2] == "toggle" then
        obj.Active = false
      else
        obj.AcquiredCount = 0
      end
    end
  end
  recompute_all_credits()

  if slot_data then
    -- Each apworld option key arrives as 0/1 (Toggle / DefaultOnToggle) or
    -- an integer (Choice — e.g. `goal`). Booleans get normalized; numerics
    -- pass through so is_goal(N) can compare directly against OPTIONS.goal.
    for k, v in pairs(slot_data) do
      if v == 0 or v == false or v == "0" then
        OPTIONS[k] = false
      elseif v == 1 or v == true or v == "1" then
        OPTIONS[k] = true
      else
        OPTIONS[k] = v
      end
    end
  end
end

function onItem(index, item_id, item_name, player_number)
  local mapping = ITEM_MAPPING[item_id]
  if not mapping then return end
  local obj = Tracker:FindObjectForCode(mapping[1])
  if not obj then return end
  if mapping[2] == "toggle" then
    obj.Active = true
  else
    obj.AcquiredCount = (obj.AcquiredCount or 0) + 1
  end
  local k = kingdom_of_code(mapping[1])
  if k then recompute_kingdom_credits(k) end
end

function onLocation(location_id, location_name)
  local code = LOCATION_MAPPING[location_id]
  if not code then return end
  local obj = Tracker:FindObjectForCode(code)
  if obj then
    obj.AvailableChestCount = 0
  end
end

Archipelago:AddClearHandler("smo", onClear)
Archipelago:AddItemHandler("smo", onItem)
Archipelago:AddLocationHandler("smo", onLocation)
