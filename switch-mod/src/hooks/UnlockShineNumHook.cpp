// Hooks on GameDataFunction::findUnlockShineNum +
// GameDataFunction::findUnlockShineNumByWorldId.
//
// These are the game's "how many moons does the Odyssey need to leave this
// kingdom" reads (header: OdysseyHeaders game/System/GameDataFunction.h;
// both wrap GameDataHolder::findUnlockShineNum(bool* isCountTotal, s32)).
// The world-map UI's required-count display and the Odyssey launch check
// route through them, so overriding the return here is the single lie that
// keeps the in-game gate consistent with the rolled AP logic.
//
// randomize_kingdom_gates: the bridge ships rolled thresholds in a
// kingdom_gates message (full-overwrite -> ApState::kingdom_gate[bit],
// -1 = vanilla). Both trampolines call Orig first (preserves the
// isGameClear/isCountTotal out-param), then substitute the rolled value
// when one is present for the resolved kingdom. Bridge offline or slot
// still -1 -> vanilla value passes through untouched.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"  // depositedEffectiveMoons (chain-return)
#include "../game/KingdomUnlock.hpp"
#include "../game/OdysseyRescue.hpp"     // isKingdomChainReachedOnlySave (P5)
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdint>

struct GameDataHolderAccessor {
    void* mData;
};

namespace smoap::hooks {

namespace {

using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);

// Same plumbing as ShineNumGetHook/AddPayShineHook: resolve the kingdom
// Mario is currently in via the cached GameDataHolder.
std::uint8_t resolveCurrentKingdomBit() {
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(s.get_current_world_id_fn);
    GameDataHolderAccessor acc{holder};
    return smoap::game::kingdomBitForWorldId(fn(acc));
}

int rolledGateForBit(std::uint8_t bit) {
    if (bit >= 17) return -1;
    return smoap::ap::ApState::instance().kingdom_gate[bit].load(
        std::memory_order_relaxed);
}

// SMO's two world-map detour pairs are FREE DETOURS (see
// docs/v3-feasibility/future-feasibility-lake-wooded-free-detour.md): after the
// bifurcation the player may fly the siblings in either order, and the Odyssey
// must be launchable at 0 moons so the onward flight opens the instant Mario
// arrives — rather than after collecting that kingdom's leave-fuel.
//   - Post-Sand:  Lake <-> Wooded  (exit into Cloud)
//   - Post-Metro: Snow <-> Seaside (exit into Luncheon)
//
// The takeoff gate is getPayShineNum(cur) >= findUnlockShineNum(cur), reading
// the CURRENT-WORLD findUnlockShineNum out-of-line — so forcing that to 0 for
// these four kingdoms opens the crossing (proven in-game, iterations 2-4).
// Trade-off accepted by Devon: the in-kingdom takeoff gauge reads the same
// current-world value, so it shows 0/"full"; the world-map GLOBE per-kingdom
// label reads the by-world variant (left at the rolled value) and still shows
// the true threshold. The "finish the detour before the exit" enforcement lives
// solely in the combined exit gate (evaluateDetourExitGate, gated on BOTH
// siblings' moons). NOTE: a discarded experiment tried to keep the gauge at the
// real count by leaving findUnlockShineNum alone and forcing
// isUnlockedNextWorld true instead — that function is NOT the predicate
// consulted at the takeoff seam (it never fired), so it's not used here.
bool isFreeDetourBit(std::uint8_t bit) {
    static const std::uint8_t s_lake    = smoap::game::kingdomBitFor("Lake");
    static const std::uint8_t s_wooded  = smoap::game::kingdomBitFor("Wooded");
    static const std::uint8_t s_snow    = smoap::game::kingdomBitFor("Snow");
    static const std::uint8_t s_seaside = smoap::game::kingdomBitFor("Seaside");
    return bit < 17 && (bit == s_lake || bit == s_wooded ||
                        bit == s_snow || bit == s_seaside);
}

// P4/P5 chain-return takeoff allowance: active for `bit` when that kingdom is
// chain-reached-ONLY — the combined marker in OdysseyRescue::
// isKingdomChainReachedOnly: (session bit OR save-derived alreadyGo) AND NOT
// legitimately unlocked (2026-07-09 walk fix: the raw session-bit OR zeroed
// flight-visited Cascade's gate after a chain door led back into it; an
// unlocked kingdom must keep its honest gate) — AND its rolled leave-gate is
// still unpaid. Payment reverts the GAUGE to honest but does NOT clear
// chain-reached-ness (Devon ruling 2026-07-08: paying never legitimizes
// story-forward travel; the flight bounce keys on the persistent marker, not
// on this allowance).
bool chainAllowanceActive(std::uint8_t bit, int vanilla_gate) {
    if (bit >= 17) return false;
    const bool chain = smoap::game::isKingdomChainReachedOnly(
        bit, smoap::game::worldIdFromKingdomShort(smoap::game::kingdomForBit(bit)));
    if (!chain) return false;
    const int rolled = rolledGateForBit(bit);
    const int gate = rolled >= 0 ? rolled : vanilla_gate;
    return smoap::game::depositedEffectiveMoons(bit) < gate;
}

void logSubstitution(const char* which, std::uint8_t bit, int orig, int rolled) {
    // Rate-limit: only log on change — these reads fire per-frame while the
    // world map / launch UI is open.
    static std::uint8_t s_last_bit = 0xff;
    static int s_last_rolled = -2;
    if (bit != s_last_bit || rolled != s_last_rolled) {
        SMOAP_LOG_INFO("[kingdom-gates] %s: kingdom=%s(bit=%u) vanilla=%d -> rolled=%d",
                       which,
                       bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>",
                       bit, orig, rolled);
        s_last_bit = bit;
        s_last_rolled = rolled;
    }
}

// ── Gauge-vs-gate caller PROBE (2026-07-13, Devon playtest) ────────────────
//
// Symptom: in every allowance kingdom (free-detour + entrance-shuffle chain-
// reached), the in-Odyssey takeoff gauge reads "full on moons" and never shows
// the rolled required count. Cause: the current-world findUnlockShineNum we
// force to 0 to OPEN the takeoff gate is the SAME out-of-line read the gauge
// DISPLAY consumes (isUnlockedNextWorld inlines its own copy — proven not the
// in-kingdom seam; the globe labels use the by-world member variant which we
// leave rolled and which already reads correctly). The gate & gauge call sites
// both live in StageSceneStateWorldMap.cpp, which is UNDECOMPILED — so the only
// way to tell the two reads apart is by caller PC.
//
// The trampoline redirects the function entry with a plain B (Trampoline.h
// writeBranch), NOT a BL, so on entry to this handler x30/LR still holds the
// game caller's return address. __builtin_return_address(0), captured as the
// FIRST statement of the handler (before orig() runs), yields it. We convert to
// a main.nso text offset — the same units ShopItemMessageHook documents — and
// log each distinct caller exactly once. The BL that made the call is at
// (offset - 4).
//
// This probe changes NO behavior (the hooks still return exactly what they did
// before), so takeoff / free-detour / chain-return all behave identically during
// the diagnostic walk. Phase 2 (the actual fix) adds a two-line check: for the
// caller offset(s) identified as the DISPLAY/gauge read, return the rolled value
// instead of 0, while the GATE caller keeps getting 0. See the walk script in
// docs/handoff-takeoff-gauge-count.md.
std::uintptr_t mainOffsetOfRet(void* lr) {
    auto* main = hk::ro::getMainModule();
    if (!main) return 0;
    const std::uintptr_t base = main->range().start();
    const std::uintptr_t pc = reinterpret_cast<std::uintptr_t>(lr);
    return pc >= base ? (pc - base) : pc;  // raw fallback if somehow below base
}

void logGateProbe(const char* tag, std::uint8_t bit, void* lr, int orig) {
    const std::uintptr_t off = mainOffsetOfRet(lr);
    // Rate-limit PER caller offset (re-log at most once/second) rather than
    // permanently dedup — the gauge read only fires while the takeoff / world-map
    // UI is open, so a permanent dedup would suppress it if it reuses an offset
    // already seen at arrival. With windowed re-logging, opening that UI re-logs
    // whatever fires during it, timestamped, so Devon can point at the gauge's
    // caller. Global cap keeps a long session from flooding the Switch tab.
    constexpr std::int64_t kRelogMs = 1000;
    constexpr int kMaxLines = 400;
    struct Slot { std::uintptr_t off; std::int64_t last_ms; };
    static Slot s_slots[16] = {};
    static int s_n = 0;
    static int s_lines = 0;
    const std::int64_t now = smoap::ap::ApState::nowMs();
    Slot* slot = nullptr;
    for (int i = 0; i < s_n; ++i)
        if (s_slots[i].off == off) { slot = &s_slots[i]; break; }
    if (!slot) {
        if (s_n < 16) slot = &s_slots[s_n++];
    } else if (now - slot->last_ms < kRelogMs) {
        return;  // logged this offset recently — stay quiet
    }
    if (slot) slot->off = off, slot->last_ms = now;
    if (s_lines >= kMaxLines) return;
    ++s_lines;
    SMOAP_LOG_INFO("[gate-probe] caller ret=+0x%lx (BL@+0x%lx) via %s "
                   "kingdom=%s(bit=%u) origVanilla=%d t=%ldms -- record offsets "
                   "seen WHILE the takeoff gauge is on screen",
                   static_cast<unsigned long>(off),
                   static_cast<unsigned long>(off - 4), tag,
                   bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>", bit,
                   orig, static_cast<long>(now));
}

// ── Phase 2 apply table (DORMANT until populated) ──────────────────────────
//
// After the probe walk (docs/handoff-takeoff-gauge-count.md), fill this with the
// main.nso RETURN offset(s) — the `+0x…` values the [gate-probe] lines print —
// of the DISPLAY / gauge read(s), i.e. the caller(s) that feed the on-screen
// "needs N moons" / "full on moons" text. For a read whose caller is in this
// set we return the TRUE rolled required count instead of 0, so the gauge shows
// the real threshold; the takeoff-enable GATE caller is NOT in the set, still
// gets 0, and takeoff stays open under the allowance.
//
// Leave the lone `0` sentinel to keep today's behavior EXACTLY (isDisplayCaller
// returns false for every real caller). Offset 0 is the module base and can
// never be a genuine return address, so the sentinel matches nothing.
constexpr std::uintptr_t kDisplayCallerOffsets[] = {
    0,  // sentinel — append real display-caller offset(s) here to activate the fix
    // Top-left moon-count HUD read (the "collected / required" circles). Pinned by
    // the 2026-07-14 Sand-vs-Wooded contrast: in a LEGIT-progressed kingdom (Sand,
    // post-Cascade) the HUD renders correctly and the ONLY free-wrapper caller that
    // executes is +0x202dcc (returning the rolled required count); in a free-detour
    // kingdom (Wooded) the same +0x202dcc is forced to 0 and the HUD blanks to
    // "Full". So +0x202dcc feeds the HUD. Making JUST this caller honest restores
    // the HUD while the takeoff GATE stays open. DELIBERATELY EXCLUDED:
    //   +0x30b96c  — the free-wrapper takeoff GATE/readiness caller. It does NOT
    //                execute in a legit-unlocked kingdom (Sand) — only when the
    //                world isn't legitimately unlocked (Wooded/chain) — the
    //                signature of the unlock check, not a per-frame HUD render.
    //                Stays forced to 0 so takeoff remains open under the allowance.
    //   +0x1ff308  — transient free-wrapper caller seen alongside the gate; kept 0.
    //   +0x2c83d88 / +0x52a0f4 / +0x533c10 — MEMBER-seam reads. The +0x2c83d88
    //                override fired (shown=18) yet the HUD stayed blank, proving the
    //                HUD does not read the member seam; excluded.
    0x202dcc,  // top-left moon-count HUD required-count read (free current-world wrapper)
};

// Decisive confirmation that a Phase-2 DISPLAY override actually FIRED and what
// value it returned. Distinct tag from [gate-probe] (which logs BEFORE the apply
// and so looks identical whether or not the fix is deployed). If this line does
// NOT appear in the log, the Phase-2 build is not deployed. If it appears with
// shown=<rolled> but the on-screen gauge/bubble still reads "Full on Power
// Moons", then this caller is NOT what drives that text — the text reads the
// free-wrapper GATE value (which we must keep at 0), i.e. it is the game's
// readiness state and cannot show a nonzero count while takeoff is open.
void logGaugeFix(const char* seam, void* lr, std::uint8_t bit, int orig, int shown) {
    const std::uintptr_t off = mainOffsetOfRet(lr);
    constexpr std::int64_t kRelogMs = 1000;
    struct Slot { std::uintptr_t off; std::int64_t last_ms; };
    static Slot s_slots[8] = {};
    static int s_n = 0;
    const std::int64_t now = smoap::ap::ApState::nowMs();
    Slot* slot = nullptr;
    for (int i = 0; i < s_n; ++i)
        if (s_slots[i].off == off) { slot = &s_slots[i]; break; }
    if (!slot) { if (s_n < 8) slot = &s_slots[s_n++]; }
    else if (now - slot->last_ms < kRelogMs) return;
    if (slot) slot->off = off, slot->last_ms = now;
    SMOAP_LOG_INFO("[gauge-fix] DISPLAY override FIRED via %s caller=+0x%lx "
                   "kingdom=%s(bit=%u) orig=%d -> shown=%d (if gauge still 'Full', "
                   "this caller is not the gauge/bubble driver)",
                   seam, static_cast<unsigned long>(off),
                   bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>", bit,
                   orig, shown);
}

// True when `lr` (a game caller return address) is a known display/gauge read.
bool isDisplayCaller(void* lr) {
    const std::uintptr_t off = mainOffsetOfRet(lr);
    if (off == 0) return false;
    for (std::uintptr_t d : kDisplayCallerOffsets)
        if (d != 0 && d == off) return true;
    return false;
}

// The value a DISPLAY read should show while an allowance forces the GATE open:
// the rolled required count if one is set for this kingdom, else the vanilla
// count. Never 0 (that's the gate-only value).
int displayCountForBit(std::uint8_t bit, int orig_vanilla) {
    const int rolled = rolledGateForBit(bit);
    return rolled >= 0 ? rolled : orig_vanilla;
}

HkTrampoline<int, bool*, GameDataHolderAccessor> unlockShineNumHook =
    hk::hook::trampoline([](bool* is_game_clear,
                            GameDataHolderAccessor accessor) -> int {
        // MUST be the first statement: the trampoline enters via a plain B so
        // x30 still holds the game caller's return address here. See the probe
        // header above.
        void* const lr = __builtin_return_address(0);
        const int orig = unlockShineNumHook.orig(is_game_clear, accessor);
        const std::uint8_t bit = resolveCurrentKingdomBit();
        // Free-detour kingdoms: force the CURRENT-WORLD leave-threshold to 0 so
        // the Odyssey takes off at 0 moons and the sibling crossing opens the
        // instant Mario arrives. This is the PROVEN lever (iterations 2-4,
        // confirmed in-game): the takeoff gate is getPayShineNum(cur) >=
        // findUnlockShineNum(cur), reading THIS function out-of-line, so 0
        // satisfies it. The isUnlockedNextWorld force-true experiment did NOT
        // open the takeoff — that function is not the gate consulted at the
        // takeoff seam (no [free-detour] line EVER fired in the 2026-06-25 log),
        // so the real fix lives here, not there.
        //
        // Trade-off (accepted as cosmetic in iteration 4): the IN-KINGDOM takeoff
        // gauge reads this same current-world value, so it shows 0/"full". The
        // world-map GLOBE per-kingdom label reads the by-world variant below and
        // still shows the true rolled threshold (e.g. Snow 10 / Seaside 10).
        if (isFreeDetourBit(bit)) {
            logGateProbe("free-detour[FORCED-0]", bit, lr, orig);
            // Phase 2: a DISPLAY caller shows the true count; the GATE caller
            // still gets 0 so takeoff stays open. Dormant while the table holds
            // only the sentinel (isDisplayCaller == false → returns 0 as before).
            if (isDisplayCaller(lr)) {
                const int shown = displayCountForBit(bit, orig);
                logGaugeFix("free-detour", lr, bit, orig, shown);
                return shown;
            }
            logSubstitution("findUnlockShineNum[free-detour]", bit, orig, 0);
            return 0;
        }
        // P4 decoupled — chain-return takeoff allowance (Devon ruling
        // 2026-07-07/08): in a kingdom reached via a port chain whose rolled
        // leave-gate is still UNPAID, open the takeoff (return 0, the proven
        // free-detour lever) so the player can fly back out. The "visited
        // kingdoms only" half of the ruling is enforced downstream at the
        // Layer-2 flight commit (WorldMapSelectHook's chain-return bounce),
        // which reads the chain_allowance_bit flag set here — the same read
        // the launch check consumes, so the two can never disagree. Once the
        // gate is paid (deposited >= threshold) everything reverts to the
        // honest rolled/vanilla behavior, gauge included. Trade-off while
        // active: the in-kingdom takeoff gauge reads 0/"full" (same accepted
        // cosmetic as the free-detour kingdoms).
        {
            auto& st = smoap::ap::ApState::instance();
            if (chainAllowanceActive(bit, orig)) {
                st.chain_allowance_bit.store(bit, std::memory_order_relaxed);
                logGateProbe("chain-return[FORCED-0]", bit, lr, orig);
                // Phase 2 (dormant): DISPLAY caller shows the true count; the
                // GATE caller still gets 0. Note chain_allowance_bit is stored
                // ABOVE regardless, so the WorldMapSelectHook bounce keys off the
                // same allowance whether this read is gate or display.
                if (isDisplayCaller(lr)) {
                    const int shown = displayCountForBit(bit, orig);
                    logGaugeFix("chain-return", lr, bit, orig, shown);
                    return shown;
                }
                logSubstitution("findUnlockShineNum[chain-return]", bit,
                                orig, 0);
                return 0;
            }
            st.chain_allowance_bit.store(0xff, std::memory_order_relaxed);
        }
        // NOTE: Cascade is NOT special-cased here anymore. The "beat Broode to
        // leave" escape used to zero Cascade's current-world gate (and the member
        // worker + isUnlockedNextWorld) once Broode's Multi-Moon was collected, but
        // that made the in-kingdom takeoff gauge read 0/"full" and hid the
        // moons-to-unlock counter. The Cascade escape now lives entirely in
        // EntranceShuffleHook::processCascadeOdysseyDivert (walking into the Odyssey
        // door warps straight to Cap, never reaching the globe/gate), so Cascade can
        // keep its true rolled gate here and display correctly. See
        // [[cap-return-and-cascade-arrival-demo]].
        logGateProbe("honest-rolled", bit, lr, orig);
        const int rolled = rolledGateForBit(bit);
        if (rolled < 0) return orig;
        logSubstitution("findUnlockShineNum", bit, orig, rolled);
        return rolled;
    });

HkTrampoline<int, bool*, GameDataHolderAccessor, int> unlockShineNumByWorldIdHook =
    hk::hook::trampoline([](bool* is_game_clear,
                            GameDataHolderAccessor accessor,
                            int world_id) -> int {
        const int orig = unlockShineNumByWorldIdHook.orig(
            is_game_clear, accessor, world_id);
        const std::uint8_t bit = smoap::game::kingdomBitForWorldId(world_id);
        // NOTE: do NOT free-detour-zero the by-world variant. Decomp:
        // selectability is GameDataFile::isUnlockedWorld(world_id) (does not read
        // this), and the launch check (isUnlockedNextWorld) uses only the
        // current-world findUnlockShineNum. This variant feeds the world-map's
        // per-kingdom required-count DISPLAY, so leaving it at the rolled value
        // shows the real Lake/Wooded thresholds (e.g. 7/18) while the crossing
        // stays free via the current-world zero above.
        const int rolled = rolledGateForBit(bit);
        if (rolled < 0) return orig;
        logSubstitution("findUnlockShineNumByWorldId", bit, orig, rolled);
        return rolled;
    });

// ── P5 finding 11 — the story-launch predicate seam (chain-reached kingdoms) ──
//
// A chain-reached post-peace kingdom's "chase Bowser" story launch refuses
// until the rolled gate is paid, even though the gauge (the free current-world
// findUnlockShineNum above) reads 0 under the allowance — so the launch
// consults a read we don't hook. The launch state machine (ShineTowerRocket
// exeNoStart*/receiveEvent nerves) is undecompiled; the best out-of-line
// candidate is the SHARED member worker GameDataHolder::findUnlockShineNum
// (bool*, s32) const, which both free wrappers bottom out in and which FIRED
// in the 2026-06-29 Cascade rounds (it did NOT open the in-cabin globe gate
// there — the story launch is a DIFFERENT site, which is exactly what this
// hook's logging decides on the next walk; see
// docs/plan-p5-cross-world-loads.md §2.5).
//
// Behavior: under an active chain-return allowance for the CURRENT world,
// return 0 for reads of that world; all other reads pass through. The two
// free-fn hooks above call orig -> THIS trampoline fires nested; under the
// allowance orig()==0 either way for the current world, and the by-world hook
// still substitutes the rolled value afterwards, so globe labels stay honest.
// Logging is scoped to current-world reads and rate-limited on change.
HkTrampoline<int, void*, bool*, int> holderFindUnlockShineNumHook =
    hk::hook::trampoline([](void* self, bool* is_count_total,
                            int world_id) -> int {
        void* const lr = __builtin_return_address(0);  // game caller (see probe hdr)
        const int orig = holderFindUnlockShineNumHook.orig(
            self, is_count_total, world_id);
        const std::uint8_t bit = smoap::game::kingdomBitForWorldId(world_id);
        const std::uint8_t cur = resolveCurrentKingdomBit();
        if (bit >= 17 || bit != cur) return orig;  // current-world reads only
        const bool allow = chainAllowanceActive(bit, orig);
        // Probe the MEMBER seam too — if the gauge reads the by-world member with
        // the current world id (rather than the free current-world wrapper), its
        // caller shows up here instead. Tagged distinctly so Devon can tell the
        // two families apart in the log.
        logGateProbe(allow ? "member[FORCED-0]" : "member[honest]", bit, lr, orig);
        static std::uint8_t s_last_bit = 0xff;
        static int s_last_ret = -2;
        // Phase 2 (dormant): if the gauge reads the member seam, a display caller
        // shows the true count while the gate caller keeps getting 0.
        int ret;
        if (allow && isDisplayCaller(lr)) {
            ret = displayCountForBit(bit, orig);
            logGaugeFix("member", lr, bit, orig, ret);
        } else if (allow)
            ret = 0;
        else
            ret = orig;
        if ((bit != s_last_bit || ret != s_last_ret)) {
            static int s_log = 0;
            if (s_log < 80) {
                ++s_log;
                SMOAP_LOG_INFO("[chain-launch] member findUnlockShineNum "
                               "worldId=%d (%s) orig=%d -> %d%s #%d",
                               world_id, smoap::game::kingdomForBit(bit), orig,
                               ret, allow ? " (allowance ZERO)" : "", s_log);
            }
            s_last_bit = bit;
            s_last_ret = ret;
        }
        return ret;
    });

void installHolderFindUnlockShineNumHook() {
    ptr addr = hk::ro::lookupSymbol(smoap::sym::kGameDataHolderFindUnlockShineNum);
    if (addr == 0)
        addr = hk::ro::lookupSymbol(
            smoap::sym::kGameDataHolderFindUnlockShineNumNonConst);
    if (addr == 0) {
        SMOAP_LOG_WARN("[chain-launch] GameDataHolder::findUnlockShineNum "
                       "lookup FAILED — story-launch allowance seam disabled "
                       "(S&Q remains the escape hatch)");
        return;
    }
    holderFindUnlockShineNumHook.installAtPtr(addr);
    SMOAP_LOG_INFO("[chain-launch] member findUnlockShineNum hook @ 0x%lx",
                   static_cast<unsigned long>(addr));
}

// NOTE: the Cascade "force the takeoff gate open" hooks (isUnlockedNextWorld +
// the shared member worker GameDataHolder::findUnlockShineNum) were REMOVED
// 2026-06-29. They were the round 1-3 attempts to let the player fly out of
// Cascade post-Broode without paying the rolled gate; the working escape is now
// the door divert in EntranceShuffleHook::processCascadeOdysseyDivert (walking
// into the Odyssey warps straight to Cap, never reaching the globe/gate). Forcing
// the gate to 0 also made the in-kingdom takeoff gauge read 0/"full" and hid the
// moon counter — removing them restores correct UI. See
// [[cap-return-and-cascade-arrival-demo]].

}  // namespace

void installUnlockShineNumHook() {
    SMOAP_LOG_INFO("installing UnlockShineNumHook -> "
                   "GameDataFunction::findUnlockShineNum");
    unlockShineNumHook.installAtSym<
        "_ZN16GameDataFunction18findUnlockShineNumEPb22GameDataHolderAccessor">();
    // P5 finding 11 — member-worker seam (soft install; see the hook's header).
    installHolderFindUnlockShineNumHook();
}

void installUnlockShineNumByWorldIdHook() {
    SMOAP_LOG_INFO("installing UnlockShineNumByWorldIdHook -> "
                   "GameDataFunction::findUnlockShineNumByWorldId");
    unlockShineNumByWorldIdHook.installAtSym<
        "_ZN16GameDataFunction27findUnlockShineNumByWorldIdEPb22GameDataHolderAccessori">();
}

}  // namespace smoap::hooks
