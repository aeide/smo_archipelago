// OdysseyRescue — Lost Kingdom softlock prevention.
//
// In vanilla SMO, arriving in Lost Kingdom (stage ClashWorldHomeStage)
// physically grounds the Odyssey ("in disrepair") and blocks both forward
// and backward flight until ~10 Lost moons are collected.
//
// In our randomizer the fill may place the kingdom-internal moons required
// to release the Odyssey anywhere in the pre-arrival reachable set
// (Sand/Lake/Wooded/etc.). A player who rushes into Lost without sweeping
// those upstream checks arrives with 0 Lost AP credits, can't release the
// Odyssey, and can't fly back to grab the moons stranded in upstream
// checks. Permanent softlock.
//
// Fix mirrors Kgamer77/SuperMarioOdysseyArchipelago v1.2's
// updatePlayerInfo() pattern: a per-frame (throttled) sweep that detects
// the wrecked Odyssey state and unconditionally force-repairs it via SMO's
// own GameDataFunction:: entry points. Unlike Kgamer77 we don't gate on
// local moon counts — the user wants free warp regardless of how many
// local moons they've collected.
//
// Ruined Kingdom is intentionally NOT handled here. Ruined gets the
// Odyssey grounded by the Lord-of-Lightning boss-attack state, but in
// our randomizer Ruined moons are filler (not progression) and entry to
// Bowser's Kingdom has no per-kingdom moon gate. Vanilla flow takes Mario
// from Ruined to Bowser via the post-boss-defeat autopilot cinematic;
// no patching is needed.

#pragma once

namespace smoap::game {

// Resolve the GameDataFunction symbols Lost rescue needs via
// hk::ro::lookupSymbol and cache function pointers in module-local
// statics. Call from hkMain after sail's nn::ro plumbing is up (alongside
// the existing installDepositKingdomLookupSymbol /
// installPayShineSnapshotSymbol calls). If any symbol fails to resolve,
// the sweep self-disables.
void installOdysseyRescueSymbols();

// Per-frame softlock sweep. Call from drawMainHook (already running per-
// frame). The function itself is cheap (one boolean read in steady state)
// but since the underlying state changes only on stage transitions,
// throttle to ~60 frames at the call site to keep the log surface clean.
void runOdysseySoftlockSweep();

}  // namespace smoap::game
