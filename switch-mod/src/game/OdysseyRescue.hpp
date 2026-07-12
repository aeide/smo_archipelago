// OdysseyRescue — Lost Kingdom softlock prevention.
//
// In vanilla SMO, arriving in Lost Kingdom (stage ClashWorldHomeStage)
// physically grounds the Odyssey ("in disrepair") and blocks backtracking
// until it is released — unique among SMO kingdoms (the only other kingdom
// that grounds-and-blocks is Ruined, handled differently; see below).
//
// In our randomizer the fill may place the kingdom-internal moons required
// to release the Odyssey anywhere in the pre-arrival reachable set
// (Sand/Lake/Wooded/etc.). A player who rushes into Lost without sweeping
// those upstream checks arrives with 0 AP credits for the current kingdom,
// can't release the Odyssey, and can't fly back to grab the moons stranded
// in upstream checks. Permanent softlock.
//
// This module mirrors Kgamer77/SuperMarioOdysseyArchipelago v1.2's
// updatePlayerInfo() fix: a per-frame (throttled) sweep that detects the
// crashed Odyssey state and unconditionally force-repairs it via SMO's own
// GameDataFunction:: entry points. Unlike Kgamer77 we don't gate on local
// moon counts — the user wants free warp regardless of how many local moons
// they've collected.
//
// Ruined Kingdom is intentionally NOT swept. Ruined grounds the Odyssey via
// the Lord of Lightning boss-attack state, which vanilla releases the instant
// the player beats the dragon and collects the Ruined Multi-Moon. AP fill
// pins that Multi-Moon to its vanilla location (the dragon) via the
// "place_item" entry on "Ruined: Battle with the Lord of Lightning!" in
// locations.json, so beating the dragon always repairs the Odyssey and lets
// the player leave. The old Ruined backtrack-repair path is gone: it risked a
// mUnlockWorldNum counter overshoot that made the post-boss autopilot skip
// Bowser straight to Moon.

#pragma once

namespace smoap::game {

// Resolve the 5 GameDataFunction symbols via hk::ro::lookupSymbol and cache
// function pointers in module-local statics. Call from hkMain after sail's
// nn::ro plumbing is up (i.e., alongside the existing
// installDepositKingdomLookupSymbol / installPayShineSnapshotSymbol calls).
//
// If any symbol fails to resolve, the sweep self-disables (logs once on each
// call attempt). All 5 names live in switch-mod/src/hooks/HookSymbols.hpp
// under the "OdysseyRescue" header; mirrored in
// switch-mod/syms/game/SmoApSymbols.sym.
void installOdysseyRescueSymbols();

// Per-frame softlock sweep. Call from drawMainHook (already running per-
// frame). The function itself is cheap (one boolean read in steady state) but
// since the underlying state changes only on stage transitions, throttle to
// ~60 frames at the call site to keep the log surface clean and match
// Kgamer77's proven cadence.
void runOdysseySoftlockSweep();

// Force the Odyssey into its present + boardable save-state (the parked pose
// every Odyssey-flight arrival shows): activateHome + upHomeLevel(0->1) +
// launchHome on the cached GameDataHolder. No-op once the Odyssey is already
// owned (post-Broode / normal revisit). Call from a changeNextStage commit
// BEFORE the destination stage loads, so the stage init reads the acquired
// state — the "write the bit before the reader runs" pattern. `tag` is a
// caller label for the one-shot diagnostic log. Resolves its mutators
// independently; a missing symbol self-disables only this path.
//
// Primary use: the Cap->Cascade first-arrival fix (driven from
// CascadeBroodeRespawnHook via EntranceShuffleHook's changeNextStage seam) so
// the Odyssey is parked + boardable in Cascade before Madame Broode — Broode
// herself is kept present by the broode-respawn scenario force.
void forceAcquireOdyssey(const char* tag);

// Logger spike (2026-06-27): dump the first-visit / world-warp-demo flag set
// (isAlreadyGoWorld / isFirstTimeNextWorld / isForwardWorldWarpDemo /
// isPlayDemoWorldWarp / isEnterStageFirst) for the current world, NOW, with the
// given tag. READ-ONLY. Unlike the throttled sweep variant this fires
// unconditionally on every call — use it at the changeNextStage commit (before
// orig) to capture the first-arrival demo decision while it's still pending,
// since the transient demo flags may be cleared by the time the per-frame sweep
// reads them post-arrival. Self-disables if its getters didn't resolve.
void logWorldWarpDemoDiagNow(const char* tag);

// Cap-departure destination unlock. Forcing Cap into its return layout
// (CapReturnScenarioHook) skips the prologue's scripted unlockWorld(Cascade), so
// a boardable Odyssey in Cap would have nowhere to fly. This unlocks Cascade
// (GameDataFunction::unlockWorld at getWorldIndexWaterfall) so the Odyssey world
// map offers it. Idempotent — unlockWorld just adds to the unlocked set, so it's
// a no-op on a save that already has Cascade unlocked (e.g. the start_at_cap_peace
// save, created by real flight). Self-disabling if its symbols didn't resolve.
// Call from the Cap changeNextStage commit alongside forceAcquireOdyssey.
void forceUnlockCascadeDestination(const char* tag);

// First-arrival parked-pose FIX (2026-06-27). Mark Cascade "already visited"
// (GameProgressData::setAlreadyGoWorld for the Waterfall world index) so the
// engine runs the normal PARKED Odyssey flight landing instead of the buried
// first-visit demo. The warpdemo spike proved isAlreadyGoWorld(Cascade) is the
// buried-vs-parked discriminator (0 = buried first arrival, 1 = parked return
// flight; identical forced scenario + entrance id otherwise). Call from the
// Cascade pre-Broode changeNextStage commit BEFORE orig, passing the
// GameDataFile* the hook receives (we read mGameProgressData @ +0x6a8 off it).
// Idempotent and self-disabling if its symbols didn't resolve.
void forceCascadeAlreadyVisited(void* gameDataFile, const char* tag);

// ---- P4 decoupled — chain-arrival normalization (generalized Cascade
// treatment, Devon 2026-07-08) --------------------------------------------

// Generalized forceCascadeAlreadyVisited: mark ANY world already-visited
// (GameProgressData::setAlreadyGoWorld) before a chain-arrival commit so the
// engine runs the parked flight landing instead of the buried first-visit
// demo. Same +0x6a8 GameProgressData read, same idempotence. world_id is the
// SMO internal id (worldIdFromKingdomShort). No-op for invalid ids / missing
// symbols.
void forceAlreadyVisitedWorld(void* gameDataFile, int world_id, const char* tag);

// Read helper for the chain-return flight bounce: has the save officially
// recorded Mario as having traveled to world_id (GameDataFunction::
// isAlreadyGoWorld)? Returns false when unresolved / holder not cached —
// callers treat that as "not visited" (conservative toward bouncing).
bool isWorldAlreadyGo(int world_id);

// REMOVED (P4 finding 12, Devon ruling 2026-07-08): forceUnlockWorld(world_id)
// — the chain-arrival unlockWorld call. Decomp-confirmed
// (GameProgressData::unlockNextWorld) that unlockWorld on a late kingdom
// monotonically unlocks EVERY earlier kingdom on the globe (mUnlockWorldNum
// counter, written to the save) and raises mHomeLevel. Chain kingdoms are
// listed via the RAM-only listing force below instead; never re-add an
// unlockWorld call on the chain path. (The Lost sweep's unlockWorld of the
// CURRENT world remains — that shape can't overshoot.)

// P5 chain-return hardening (docs/plan-p5-cross-world-loads.md §2.1) --------

// RAW per-world unlock read (GameDataFunction::isUnlockedWorld free fn,
// GameProgressData::isUnlockWorld member fallback via game_data_file_cache).
// out_ok is set false when NEITHER read is available (symbols unresolved /
// caches cold) — callers must fail closed on that. NOTE: this reads the
// mIsUnlockWorld RAM array that tickChainKingdomListing FORCES for chain
// kingdoms, so a forced world reads unlocked here — prefer isWorldUnlockedHonest
// for the chain-only derivation.
bool isWorldUnlockedRaw(int world_id, bool* out_ok);

// HONEST per-world unlock read (P5 T-C, §9.3): isWorldUnlockedRaw with OUR own
// listing forces subtracted (ApState::chain_unlock_forced_bits). Returns false
// for a world whose mIsUnlockWorld entry we set purely to place a boardable
// ship — so the exist-fix (RAM force) and the chain-only marker are no longer
// mutually exclusive. A world we never forced reads exactly its raw value, so a
// legitimately unlocked kingdom can NEVER be flipped to chain-only (regression
// guard, 2026-07-09 Cascade lesson). This is the read the chain-only derivation
// uses; the raw variant remains for callers wanting the literal RAM state.
bool isWorldUnlockedHonest(int world_id, bool* out_ok);

// Save-derived "chain-reached-only" marker: isAlreadyGoWorld(w) &&
// !isWorldUnlockedRaw(w). Both inputs are save-backed, so this survives
// save/quit/reload, is independent of gate payment, and self-clears when the
// kingdom is later unlocked legitimately (story progression). Returns false
// (fail closed) when the unlock read is unavailable. NOTE: on a save already
// polluted by the removed unlockWorld overshoot this reads false for chain
// kingdoms (they're unlocked there) — session bits cover until re-seed.
bool isKingdomChainReachedOnlySave(int world_id);

// Per-frame (caller-throttled) listing force: for every chain-reached-only
// world, set GameProgressData::mIsUnlockWorld[w] = true so the globe lists it
// as a return-flight destination. RAM-only (updateList rebuilds the array and
// write() never serializes it), clobber-proof by re-assertion — same pattern
// as the costume-door OpenKeySwitch force. Needs game_data_file_cache; cold
// cache = no-op (before the first stage transition of a session, when no
// chain kingdom can need listing anyway).
void tickChainKingdomListing();

// COMBINED "chain-reached-only" read for the allowance + bounce sites
// (2026-07-09 walk fix). The old form ORed the session chain bit with the
// save-derived marker, but the session bit is set by ANY remapped overworld
// commit — including one into a kingdom the player already legitimately
// unlocked (first live case: a chain door back into flight-visited Cascade
// zeroed its takeoff gate, `[chain-launch] ... orig=5 -> 0`). A legitimately
// UNLOCKED kingdom must never count as chain-only, whatever the session bit
// says: unlocked ⇒ the honest gate + free story-forward travel apply.
//
//   chain-only := (session bit || isAlreadyGoWorld) && !isWorldUnlockedRaw
//
// When the unlock read is unavailable (out_ok false) this degrades to the
// session bit alone (the save-derived arm keeps its documented fail-closed
// shape). `bit` is the kingdom bit, `world_id` the SMO world id — pass both
// (callers already have them; keeps this free of the bit<->id tables).
bool isKingdomChainReachedOnly(int bit, int world_id);

}  // namespace smoap::game
