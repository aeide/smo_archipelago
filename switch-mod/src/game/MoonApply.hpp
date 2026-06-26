// Game-side moon-flag manipulation.
//
// Used both by the moon-get hook (extract coords from a just-collected shine)
// and by the AP item application path (write moon flags so SMO behaves as if
// a moon was collected, opening gates).

#pragma once

#include <cstdint>
#include <string>

namespace smoap::game {

// Write the moon-collected flag for (kingdom, shine_id) via GameDataHolder.
// Sets ApState::synthetic_grant_this_frame around the call so our own
// moon-get hook does not re-emit the check upstream.
//
// Idempotent: safe to call repeatedly with the same args (no-op if already set).
void grantShine(const std::string& kingdom, const std::string& shine_id);

// Reverse: from a ShineActor* (or whatever the hook receives), pull out the
// canonical kingdom name and shine_id used in apworld/data/locations.json.
// Returns false if the shine cannot be identified (silent drop).
bool extractShineCoords(/* ShineActor* shine, */
                       std::string& out_kingdom,
                       std::string& out_shine_id);

// M4.5 reconciliation: enumerate every shine the player has gotten in their
// active save. Called from the worker thread (ApClient::sendSnapshot) right
// after HELLO and on save load (transitively, via SaveLoadHook ->
// requestRehello -> reconnect -> sendHello -> sendSnapshot).
//
// Implementation lands in M5/M6 alongside grantShine — both need the same
// GameDataHolder traversal. Until then this is a stub that emits nothing,
// which is safe: bridge applies an empty snapshot as a no-op.
//
// `cb` is invoked with raw SMO identifiers (ShineInfo::stageName,
// ShineInfo::objectId, ShineInfo::shineId). Bridge resolves to canonical
// (kingdom, shine_id) via shine_map.json downstream — same path that handles
// live MoonGetHook checks.
using ShineEnumerationCallback = void(*)(void* ctx,
                                          const char* stage_name,
                                          const char* object_id,
                                          int shine_uid);
void enumerateOwnedShines(ShineEnumerationCallback cb, void* ctx);

// Tri-state "is this shine collected?" probe, matched by (stage_name,
// object_id). Walks GameDataFile::mShineHintList and reads HintInfo::isGet —
// the SAME proven mechanism enumerateOwnedShines uses (HELLO snapshot). This is
// the reliable collection source: GameDataFile::isGotShine(int) wants a shine
// INDEX, not the apworld shine_uid, so feeding it shine_uid mis-reports.
//
// Returns:
//    1  collected   (HintInfo entry found, isGet set)
//    0  uncollected  (HintInfo entry found, isGet clear)
//   -1  unknown      (game data not ready, or no matching hint entry)
// Callers that gate a "force" on uncollected MUST treat -1 as "don't force"
// (fail safe) — same direction as the old isGotShine==null guard.
int probeShineGot(const char* stage_name, const char* object_id);

// Resolve the GameDataFile::isGotShine(int) symbol once at module init.
// Wired from main.cpp next to the other M6-phase resolver calls. If lookup
// fails enumerateOwnedShines logs and emits nothing — the snapshot stays a
// safe no-op rather than crashing.
void installSnapshotSymbols();

}  // namespace smoap::game
