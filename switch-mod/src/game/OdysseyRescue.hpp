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

}  // namespace smoap::game
