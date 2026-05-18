-- SMO Archipelago PopTracker pack — entry point.
-- Order matters: logic.lua defines OPTIONS before autotracking populates it,
-- and items must be registered before locations reference their codes.

ScriptHost:LoadScript("scripts/logic.lua")
ScriptHost:LoadScript("scripts/mappings.lua")

Tracker:AddItems("items/items.json")
Tracker:AddItems("items/credits.json")

Tracker:AddMaps("maps/maps.json")
Tracker:AddLocations("locations/locations.json")

Tracker:AddLayouts("layouts/tracker.json")
Tracker:AddLayouts("layouts/broadcast.json")

-- Archipelago handlers only register when the user picks the AP variant.
-- Offline mode (a different variant) skips autotracking; OPTIONS keeps the
-- defaults set in logic.lua, which match the apworld's default YAML.
if Archipelago and Archipelago.AddItemHandler then
  ScriptHost:LoadScript("scripts/autotracking.lua")
end
