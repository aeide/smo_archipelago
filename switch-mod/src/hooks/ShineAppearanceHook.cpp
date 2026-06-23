// Per-classification Power Moon recolor via material-parameter override.
//
// Trampolines Shine::init and writes AP-classification tint directly into
// the body material's color slots. See production switch-mod's
// ShineAppearanceHook.cpp for the full design narrative.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <cstdint>

#include "../ap/ApFrameBridge.hpp"
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdio>

namespace smoap::hooks {

namespace {

struct Color4f {
    float r, g, b, a;
};

// ---------------------------------------------------------------------------
// Palette index layout (LOCK-STEP with the client — see
// apworld/smo_archipelago/client/config.py: ColorsConfig defaults +
// KINGDOM_PALETTE_BASE / KINGDOM_PALETTE_ORDER). The bridge emits one
// palette index per scouted shine; this table renders it.
//
//   0  junk / filler        -> dull grey   (foreign-game junk)
//   1  progression          -> green
//   2  useful               -> yellow      (was cyan; repointed for P5)
//   3  trap                 -> red
//   4  (legacy light-green, unused by the current classifier — kept so the
//       kingdom block stays at the plan's `5 + kingdom_id` offset)
//   5..21  our own slot's moon items, colored by the GRANTED moon's
//          kingdom (NOT the check's physical kingdom). Block base = 5,
//          17 kingdoms in SMO natural order incl. Cloud + Dark/Darker.
//
// HYBRID per-kingdom recolor (P5, frames harvested in-game 2026-06-21):
//
// Vanilla SMO tints Power Moons per kingdom by driving a "Color" material
// animation to a per-kingdom frame (Shine::getColorFrame() reads it back).
// The in-game harvest found vanilla uses only 10 DISTINCT frames (0..9): 11
// kingdoms map to a distinct frame, but 8 collapse to frame 0 (the default
// gold moon). For the 11 frame-distinct kingdoms we reproduce the AUTHENTIC
// vanilla color by re-driving that "Color" anim to the granted kingdom's
// frame (see kKingdomColorFrame + rs::setStageShineAnimFrame below) — those
// kingdoms' Color4f rows in the tables below are UNUSED except as a
// symbol-miss fallback. For the 6 frame-0 kingdoms Devon wants visually
// distinct (Cascade/Cloud/Lost/Ruined/Dark/Darker) we keep the material-tint
// path with custom hues. The classification colors (idx 0..4) are always
// material tints (no vanilla frame). The two mechanisms never combine:
// the frame-override path returns BEFORE writeBodyTint, because
// setMaterialProgrammable would freeze the very anim we just set.
//
// Material tints are MULTIPLICATIVE against the gold base material; values
// exceed 1.0 to brighten. The 6 custom hues are Devon's hex scaled up to a
// max channel of ~2.6 (hue preserved exactly, brightness normalized to the
// neighbors) — expect an in-game tuning pass since the base material biases
// the result. Keep the two tables (and the client's KINGDOM_PALETTE_ORDER)
// in the same order.
// ---------------------------------------------------------------------------
inline constexpr std::size_t kKingdomPaletteBase = 5;   // == client KINGDOM_PALETTE_BASE
inline constexpr std::size_t kKingdomCount       = 17;
inline constexpr std::size_t kPaletteCount       = kKingdomPaletteBase + kKingdomCount;  // 22

constexpr Color4f kPaletteColors3D[kPaletteCount] = {
    {0.45f, 0.45f, 0.50f, 1.0f},  // 0  junk / filler  -> grey
    {0.20f, 1.80f, 0.20f, 1.0f},  // 1  progression    -> green (darkened per Devon)
    {2.60f, 2.30f, 0.28f, 1.0f},  // 2  useful         -> yellow
    {2.80f, 0.28f, 0.28f, 1.0f},  // 3  trap           -> red
    {0.55f, 1.00f, 0.55f, 1.0f},  // 4  (legacy light-green, unused)
    {1.40f, 1.70f, 2.60f, 1.0f},  // 5  Cap       -> pale ice blue
    {2.60f, 1.61f, 0.16f, 1.0f},  // 6  Cascade   -> #f99a0f orange  (custom tint)
    {0.30f, 2.40f, 2.10f, 1.0f},  // 7  Sand      -> frame-override 5 (Color4f unused)
    {0.40f, 0.95f, 2.80f, 1.0f},  // 8  Lake      -> frame-override 7 (Color4f unused)
    {0.30f, 2.40f, 0.55f, 1.0f},  // 9  Wooded    -> frame-override 2 (Color4f unused)
    {2.51f, 2.57f, 2.60f, 1.0f},  // 10 Cloud     -> #e4e9ec pale white (custom tint)
    {2.60f, 0.30f, 2.17f, 1.0f},  // 11 Lost      -> #eb1bc4 magenta  (custom tint)
    {2.80f, 2.10f, 0.20f, 1.0f},  // 12 Metro     -> frame-override 1 (Color4f unused)
    {1.00f, 2.20f, 2.70f, 1.0f},  // 13 Snow      -> frame-override 4 (Color4f unused)
    {2.80f, 0.85f, 1.70f, 1.0f},  // 14 Seaside   -> frame-override 8 (Color4f unused)
    {2.80f, 1.35f, 0.80f, 1.0f},  // 15 Luncheon  -> frame-override 6 (Color4f unused)
    {2.60f, 2.10f, 2.52f, 1.0f},  // 16 Ruined    -> #d1a9cb pale lavender (custom tint)
    {2.80f, 0.30f, 0.55f, 1.0f},  // 17 Bowser's  -> frame-override 3 (Color4f unused)
    {2.10f, 2.10f, 1.85f, 1.0f},  // 18 Moon      -> frame-override 9 (Color4f unused)
    {0.95f, 2.60f, 0.40f, 1.0f},  // 19 Mushroom  -> frame-override 0 (Color4f unused)
    {2.60f, 2.13f, 1.63f, 1.0f},  // 20 Dark      -> #e4bb8f warm tan (custom tint)
    {2.60f, 2.13f, 1.63f, 1.0f},  // 21 Darker    -> #e4bb8f warm tan (custom tint, == Dark)
};
constexpr Color4f kPaletteColorsDot[kPaletteCount] = {
    {0.50f, 0.50f, 0.55f, 1.0f},  // 0  junk / filler  -> grey
    {0.24f, 1.68f, 0.24f, 1.0f},  // 1  progression    -> green (darkened per Devon)
    {2.40f, 2.10f, 0.32f, 1.0f},  // 2  useful         -> yellow
    {2.60f, 0.36f, 0.36f, 1.0f},  // 3  trap           -> red
    {0.60f, 1.00f, 0.60f, 1.0f},  // 4  (legacy light-green, unused)
    {1.40f, 1.70f, 2.60f, 1.0f},  // 5  Cap
    {2.60f, 1.61f, 0.16f, 1.0f},  // 6  Cascade   #f99a0f (custom tint)
    {0.30f, 2.40f, 2.10f, 1.0f},  // 7  Sand       frame-override 5 (unused)
    {0.40f, 0.95f, 2.80f, 1.0f},  // 8  Lake       frame-override 7 (unused)
    {0.30f, 2.40f, 0.55f, 1.0f},  // 9  Wooded     frame-override 2 (unused)
    {2.51f, 2.57f, 2.60f, 1.0f},  // 10 Cloud     #e4e9ec (custom tint)
    {2.60f, 0.30f, 2.17f, 1.0f},  // 11 Lost      #eb1bc4 (custom tint)
    {2.80f, 2.10f, 0.20f, 1.0f},  // 12 Metro      frame-override 1 (unused)
    {1.00f, 2.20f, 2.70f, 1.0f},  // 13 Snow       frame-override 4 (unused)
    {2.80f, 0.85f, 1.70f, 1.0f},  // 14 Seaside    frame-override 8 (unused)
    {2.80f, 1.35f, 0.80f, 1.0f},  // 15 Luncheon   frame-override 6 (unused)
    {2.60f, 2.10f, 2.52f, 1.0f},  // 16 Ruined    #d1a9cb (custom tint)
    {2.80f, 0.30f, 0.55f, 1.0f},  // 17 Bowser's   frame-override 3 (unused)
    {2.10f, 2.10f, 1.85f, 1.0f},  // 18 Moon       frame-override 9 (unused)
    {0.95f, 2.60f, 0.40f, 1.0f},  // 19 Mushroom   frame-override 0 (unused)
    {2.60f, 2.13f, 1.63f, 1.0f},  // 20 Dark      #e4bb8f (custom tint)
    {2.60f, 2.13f, 1.63f, 1.0f},  // 21 Darker    #e4bb8f (custom tint, == Dark)
};

inline const Color4f& shinePaletteColor(int shine_type, std::size_t pal_idx) {
    return shine_type == 1 ? kPaletteColorsDot[pal_idx] : kPaletteColors3D[pal_idx];
}

// --- Classification-color animated gradient (2026-06-22) ---------------------
// Devon loved the Cap green<->blue cycle, so it's now the treatment for ALL FOUR
// classification colors (the moon colors for foreign-game items): each cycles
// between its primary (idx 0 grey / 1 green / 2 yellow / 3 red) and the SAME
// #316b84 Archipelago-logo-blue secondary. Kingdom-specific moon colors (palette
// idx 5+) are untouched — they keep their authentic vanilla frames/tints.
//
// The cycle is a per-frame re-tint driven by ApState::nowMs() (monotonic ms) so
// every on-screen moon stays phase-synced and it's frame-rate independent. The
// material params persist once set, hence the per-frame re-write (Shine::control
// trampoline below). Primaries come from kPaletteColors[0..3] — the green (idx 1)
// was darkened earlier per Devon and dwells a little longer (kCyclePrimaryHold).
//
// ⚠ REVERT: set kClassColorCycle = false. Classification moons fall back to their
// static per-classification tints (writeBodyTint) and the per-frame Shine::control
// hook is not installed (zero per-frame cost). Kingdom colors are unaffected.
//
// This supersedes the earlier Cap-cycle TEST and the frame-exact classification
// pinning (progression->Sand frame etc.) — a gradient needs an RGB endpoint, so
// the classification colors are RGB tints again, not vanilla frames.
inline constexpr bool         kClassColorCycle      = true;
inline constexpr std::size_t  kClassPaletteMax      = 3;     // idx 0..3 cycle
inline constexpr std::int64_t kCyclePeriodMs        = 2600;  // primary->blue->primary
// Fraction of each period dwelling fully on the primary before the blue excursion
// (Devon wanted it to linger on the color; 0 = plain symmetric triangle).
inline constexpr float        kCyclePrimaryHoldFrac = 0.40f;
// Shared secondary endpoint: #316b84, scaled to a max channel of 2.6 to match the
// hue brightness (multiplicative): (49,107,132)/255 * (2.6/0.518) = (0.97,2.11,2.60).
constexpr Color4f kCycleSecondary3D  = {0.97f, 2.11f, 2.60f, 1.0f};  // #316b84
constexpr Color4f kCycleSecondaryDot = {0.97f, 2.11f, 2.60f, 1.0f};  // #316b84

// --- Per-frame color ENFORCEMENT (2026-06-22) -------------------------------
// Problem: the recolor used to be applied only at discrete MOMENTS — Shine::init
// plus a re-assert when vanilla calls rs::setStageShineAnimFrame (the appear/
// popup path, which fires for treasure chests). Any moon coloured through a
// DIFFERENT path slips through and shows its vanilla color:
//   * kingdom timer-challenge moons spawn without hitting setStageShineAnimFrame
//     -> stay default gold;
//   * the "Got a Moon!" get cutscene re-shows/re-drives the moon AFTER init
//     -> our one-shot override is clobbered -> the color visibly changes mid-
//        cutscene ("jarring");
//   * Toad-given moons — same class of miss.
// Shine.cpp is undecompiled upstream (only Item/Shine.h exists), so we can't
// hook those individual paths. Instead we enforce the color EVERY FRAME from
// Shine::control — the one chokepoint that ticks for every live Shine no matter
// how it spawned or which cutscene state it's in. The classification cycle
// (idx 0..3) already rode this hook; this flag extends the per-frame re-assert
// to the kingdom colors (frame-override + static-tint) too, so the color is
// "kept through" the cutscene and every spawn path lands coloured.
//
// Cost: one palette resolve + (frame re-drive | tint write) per visible Shine
// per frame — same order as the existing classification cycle. ⚠ REVERT: set
// false to return to moment-based application (init + setStageShineAnimFrame).
inline constexpr bool kPerFrameColorEnforce = true;

// --- Recolor the VISIBLE model, not just the Shine (2026-06-23) --------------
// The "You got a Moon!" get cutscene shows the moon as a SEPARATE demo model
// actor (Shine::addDemoModelActor / addDemoActorWithModel — OdysseyHeaders
// game/Item/Shine.h), NOT the Shine's own world model. So writing material
// params against the Shine actor recolors the now-hidden world model while the
// demo model the player actually sees stays vanilla GOLD — which reads as the
// orange Cascade/default tint regardless of the granted kingdom (confirmed by a
// "Got Wooded Power Moon!" screenshot where the held-up moon was gold, not
// Wooded blue, 2026-06-23). Fix: per frame, recolor Shine::getCurrentModel()
// (the demo model during the cutscene, the world model otherwise) IN ADDITION
// to the Shine actor. Palette/type still resolve from the Shine; the color is
// written to whichever model is visible. ⚠ REVERT: set false to recolor only
// the Shine actor (the demo cutscene reverts to vanilla gold, no crash).
inline constexpr bool kRecolorVisibleModel = true;

// --- TEST (2026-06-22): preview classification PULSES on two real kingdoms ----
// Devon wants to eyeball the trap and useful gradients quickly, so force:
//   Cap kingdom (palette idx 5)     -> trap   pulse (red <-> #316b84)
//   Lake kingdom (palette idx 5+3)  -> useful pulse (yellow <-> #316b84)
// ⚠ REVERT: set kPulseKingdomTest = false — Cap/Lake return to their authentic
// vanilla colors, no color loss. Independent of kClassColorCycle (but the cycle
// must be on for the pulse to animate; it is).
inline constexpr bool         kPulseKingdomTest = false;
inline constexpr std::size_t  kPulseCapPalIdx   = kKingdomPaletteBase;      // 5  Cap
inline constexpr std::size_t  kPulseLakePalIdx  = kKingdomPaletteBase + 3;  // 8  Lake

// True if this resolved palette should run the animated cycle: the classification
// colors (idx 0..3) always, plus the two test-forced kingdoms while the preview is on.
inline bool isCyclePal(std::size_t pal_idx) {
    if (pal_idx <= kClassPaletteMax) return true;
    return kPulseKingdomTest &&
           (pal_idx == kPulseCapPalIdx || pal_idx == kPulseLakePalIdx);
}

// The classification primary (0..3) a cycling palette pulses toward — identity for
// real classification colors, the test remap for the two forced kingdoms.
inline std::size_t cyclePalIdx(std::size_t pal_idx) {
    if (kPulseKingdomTest) {
        if (pal_idx == kPulseCapPalIdx)  return 3;  // Cap  -> trap   (red)
        if (pal_idx == kPulseLakePalIdx) return 2;  // Lake -> useful (yellow)
    }
    return pal_idx;
}

// Linear interpolate two multiplicative tints (alpha pinned to 1).
inline Color4f lerpColor(const Color4f& a, const Color4f& b, float t) {
    return {a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t,
            a.b + (b.b - a.b) * t, 1.0f};
}

// Authentic vanilla per-kingdom color frame (harvested in-game 2026-06-21 via
// the [shine-colorframe] diagnostic). Index = kingdom_id == pal_idx -
// kKingdomPaletteBase, SAME order as the palette tables / client
// KINGDOM_PALETTE_ORDER. A value >= 0 means "drive the vanilla 'Color' anim to
// this frame" (authentic recolor via rs::setStageShineAnimFrame). kColorFrameTint
// (-1) means the kingdom has no distinct vanilla frame (it shares frame 0 with
// the default gold moon) — fall through to the custom material tint instead.
// The six kColorFrameTint kingdoms are exactly Devon's frame-0 picks
// (Cascade/Cloud/Lost/Ruined/Dark/Darker). Cap + Mushroom keep authentic
// frame 0 (intentionally identical — their models get differentiated later).
inline constexpr int kColorFrameTint = -1;
constexpr int kKingdomColorFrame[kKingdomCount] = {
    0,               // 0  Cap       frame 0 (natural authentic gold).
    kColorFrameTint, // 1  Cascade   tint #f99a0f
    5,               // 2  Sand      frame 5
    7,               // 3  Lake      frame 7
    2,               // 4  Wooded    frame 2
    kColorFrameTint, // 5  Cloud     tint #e4e9ec
    kColorFrameTint, // 6  Lost      tint #eb1bc4
    1,               // 7  Metro     frame 1
    4,               // 8  Snow      frame 4
    8,               // 9  Seaside   frame 8
    6,               // 10 Luncheon  frame 6
    kColorFrameTint, // 11 Ruined    tint #d1a9cb
    3,               // 12 Bowser's  frame 3
    9,               // 13 Moon      frame 9
    0,               // 14 Mushroom  frame 0
    kColorFrameTint, // 15 Dark      tint #e4bb8f
    kColorFrameTint, // 16 Darker    tint #e4bb8f
};

// isMatAnim selects which al material-anim family rs::setStageShineAnimFrame
// restarts the "Color" anim as: true -> al::startMtpAnim (texture pattern),
// false -> al::startMclAnim (material color). The Shine "Color" anim is a
// material COLOR animation -> false (Mcl). VERIFIED in-game 2026-06-21: a
// normal Shine (unique_id 893) recolored via the Mcl path with no crash and the
// [shine-frame] override logged success. Do NOT flip this to true — Mtp has no
// "Color" anim and would null-deref on every moon. (The one crash seen that day
// was a stub Pyramid-linked Shine with no Mcl anim player at all; that is now
// guarded by s_isMclAnimExist, not by the family bool.)
inline constexpr bool kColorAnimIsMatAnim = false;

inline constexpr const char kShineMaterialName_3D[]  = "BodyMT";
inline constexpr const char kShineMaterialName_Dot[] = "BodyMT00";

inline const char* shineMaterialNameForType(int shine_type) {
    return shine_type == 1 ? kShineMaterialName_Dot : kShineMaterialName_3D;
}

inline constexpr std::size_t kShineMShineIdxOffset = 0x290;
inline constexpr std::size_t kShineMTypeOffset     = 0x1a0;

inline constexpr std::size_t kGameDataHolder_mGameDataFileOffset = 0x20;
inline constexpr std::size_t kGameDataFile_mShineHintListOffset  = 0x9A0;
inline constexpr std::size_t kHintInfo_Size                      = 0x238;
inline constexpr std::size_t kHintInfo_UniqueIdOffset            = 0x1F0;
inline constexpr int         kShineHintListMaxIndex              = 0x400;

inline int resolveShineIndexToUniqueId(int index) {
    if (index < 0 || index >= kShineHintListMaxIndex) return -1;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return -1;
    const auto* gdf = *reinterpret_cast<const void* const*>(
        reinterpret_cast<const std::uint8_t*>(gdh)
            + kGameDataHolder_mGameDataFileOffset);
    if (!gdf) return -1;
    const auto* hint_base = *reinterpret_cast<const std::uint8_t* const*>(
        reinterpret_cast<const std::uint8_t*>(gdf)
            + kGameDataFile_mShineHintListOffset);
    if (!hint_base) return -1;
    return *reinterpret_cast<const int*>(
        hint_base + index * kHintInfo_Size + kHintInfo_UniqueIdOffset);
}

using SetMaterialProgrammableFn      = void (*)(void* actor);
using SetModelMaterialParameterRgbaFn = void (*)(
    const void* actor, const char* mat, const char* param, const Color4f&);
using SetModelMaterialParameterF32Fn  = void (*)(
    const void* actor, const char* mat, const char* param, float v);
using IsExistMaterialFn               = bool (*)(const void* actor, const char* name);
using IsExistModelFn                  = bool (*)(const void* actor);
// rs::setStageShineAnimFrame(LiveActor*, const char* stageName, s32 frame,
// bool isMatAnim). With stageName==nullptr and frame>=0 it drives the vanilla
// "Color" anim straight to `frame` and stops it — the authentic per-kingdom
// recolor. Resolved via lookupSymbol (graceful on miss → frame-override skipped).
using SetStageShineAnimFrameFn        = void (*)(
    void* actor, const char* stage_name, int frame, bool is_mat_anim);

SetMaterialProgrammableFn       s_setMaterialProgrammable       = nullptr;
SetModelMaterialParameterRgbaFn s_setModelMaterialParameterRgba = nullptr;
SetModelMaterialParameterF32Fn  s_setModelMaterialParameterF32  = nullptr;
IsExistMaterialFn               s_isExistMaterial               = nullptr;
IsExistModelFn                  s_isExistModel                  = nullptr;
SetStageShineAnimFrameFn        s_setStageShineAnimFrame        = nullptr;
// al::isMclAnimExist(const LiveActor*, const char* animName) — same shape as
// IsExistMaterialFn. Guards the frame-override against stub linked-Shines that
// have a model but no Mcl "Color" anim player (would null-deref in
// startMclAnimAndSetFrameAndStop). See HookSymbols.hpp::kAlIsMclAnimExist.
IsExistMaterialFn               s_isMclAnimExist                = nullptr;
// Shine::getCurrentModel() -> al::LiveActor*. Returns the Shine's currently
// SHOWN model — the demo model during the get cutscene, the world model
// otherwise. Lets the per-frame recolor target the actually-visible model.
// See HookSymbols.hpp::kShineGetCurrentModel. nullptr on miss → fall back to
// the Shine actor (pre-fix behavior).
using GetCurrentModelFn               = void* (*)(void* shine);
GetCurrentModelFn               s_getCurrentModel               = nullptr;

void writeBodyTint(void* actor, const char* mat_name, const Color4f& tint,
                   bool is_dot) {
    s_setMaterialProgrammable(actor);
    if (s_setModelMaterialParameterF32 != nullptr) {
        s_setModelMaterialParameterF32(actor, mat_name, "enable_uniform0_mul_color", 1.0f);
        if (!is_dot) {
            s_setModelMaterialParameterF32(actor, mat_name, "enable_base_color_mul_color", 1.0f);
            s_setModelMaterialParameterF32(actor, mat_name, "enable_uniform1_mul_color",   1.0f);
        }
    }
    s_setModelMaterialParameterRgba(actor, mat_name, "uniform0_mul_color", tint);
    if (!is_dot) {
        s_setModelMaterialParameterRgba(actor, mat_name, "base_color_mul_color", tint);
        s_setModelMaterialParameterRgba(actor, mat_name, "uniform1_mul_color",   tint);
        s_setModelMaterialParameterRgba(actor, mat_name, "const_color0",         tint);
    }
}

// Write the current point of a classification color's primary<->#316b84 cycle as
// a flat tint. Triangle wave on ApState::nowMs() so the color sweeps
// primary->blue->primary over kCyclePeriodMs. Called every frame from the
// Shine::control trampoline (the material params persist, so re-writing each frame
// is what makes it animate) and once at init from tryWriteShineTint for a seamless
// first frame. Caller must have already confirmed the model + material are present.
void applyClassCycleColor(void* actor, const char* mat_name, bool is_dot,
                          std::size_t pal_idx) {
    const std::int64_t ms = smoap::ap::ApState::nowMs();
    std::int64_t ph = ms % kCyclePeriodMs;
    if (ph < 0) ph += kCyclePeriodMs;  // nowMs is monotonic >=0; defensive
    const float p = static_cast<float>(ph) / static_cast<float>(kCyclePeriodMs);
    // Hold fully on the primary (t=0) for the first kCyclePrimaryHoldFrac of the
    // period, then a primary->blue->primary triangle over the remainder.
    float t;
    if (p < kCyclePrimaryHoldFrac) {
        t = 0.0f;
    } else {
        const float q = (p - kCyclePrimaryHoldFrac) / (1.0f - kCyclePrimaryHoldFrac);
        t = q < 0.5f ? q * 2.0f : (1.0f - q) * 2.0f;  // 0 -> 1 -> 0
    }
    // Primary = this classification's palette color; secondary = shared #316b84.
    const Color4f& a = is_dot ? kPaletteColorsDot[pal_idx] : kPaletteColors3D[pal_idx];
    const Color4f& b = is_dot ? kCycleSecondaryDot : kCycleSecondary3D;
    writeBodyTint(actor, mat_name, lerpColor(a, b, t), is_dot);
}

// Resolve a Shine* to its AP palette index, or -1 if there is no override
// (unknown shine, out-of-range unique_id, or kNoPaletteOverride). Shared by the
// Shine::init trampoline AND the rs::setStageShineAnimFrame trampoline so the
// two color paths can never disagree on a moon's color. `self` is the Shine.
inline int resolveShinePalIdx(const void* self) {
    const auto* shine = reinterpret_cast<const std::uint8_t*>(self);
    const int index = *reinterpret_cast<const int*>(
        shine + kShineMShineIdxOffset);
    const int unique_id = resolveShineIndexToUniqueId(index);
    if (unique_id <= 0 ||
        static_cast<std::size_t>(unique_id) >=
            smoap::ap::ApState::kMaxShineUid) {
        return -1;
    }
    const std::uint8_t pal =
        smoap::ap::ApState::instance().getShinePalette(unique_id);
    if (pal == smoap::ap::ApState::kNoPaletteOverride) return -1;
    return static_cast<int>(pal < kPaletteCount ? pal : 0);
}

inline int readShineType(const void* self) {
    return *reinterpret_cast<const int*>(
        reinterpret_cast<const std::uint8_t*>(self) + kShineMTypeOffset);
}

// For a kingdom palette index, the authentic vanilla "Color" frame to drive, or
// kColorFrameTint (-1) if this kingdom has no distinct vanilla frame (it shares
// frame 0 with the gold default — fall back to a custom material tint instead).
// Classification colors (idx 0..4) are never frame-driven -> always -1: idx 0..3
// get the animated material-tint cycle (applyClassCycleColor), idx 4 a static tint.
inline int kingdomColorFrameForPal(std::size_t pal_idx) {
    if (pal_idx < kKingdomPaletteBase) return kColorFrameTint;
    // TEST: the two pulse-forced kingdoms take the material-tint/cycle path
    // instead of their vanilla frame (revert via kPulseKingdomTest = false).
    if (kPulseKingdomTest &&
        (pal_idx == kPulseCapPalIdx || pal_idx == kPulseLakePalIdx))
        return kColorFrameTint;
    const std::size_t kingdom_id = pal_idx - kKingdomPaletteBase;
    return kingdom_id < kKingdomCount ? kKingdomColorFrame[kingdom_id]
                                      : kColorFrameTint;
}

// Apply our material-tint override on top of whatever the model is currently
// showing (classification idx 0..4 + the 6 frame-0 "tint" kingdoms). Returns
// false if the model/material isn't present so the caller can warn once. The
// isExistModel guard is required — some Shine paths complete without a model
// keeper (stub linked-Shines), and the parameter setters deref it unchecked.
bool tryWriteShineTint(void* self, int shine_type, std::size_t pal_idx) {
    if (s_isExistModel == nullptr || !s_isExistModel(self)) return false;
    const char* mat_name = shineMaterialNameForType(shine_type);
    if (s_isExistMaterial != nullptr && !s_isExistMaterial(self, mat_name))
        return false;
    const bool is_dot = shine_type == 1;
    // Classification colors (idx 0..3, plus the test-forced pulse kingdoms) get
    // the animated primary<->#316b84 cycle. Seed the first frame here; the
    // Shine::control trampoline keeps it animating. Gated on kClassColorCycle.
    if (kClassColorCycle && isCyclePal(pal_idx)) {
        applyClassCycleColor(self, mat_name, is_dot, cyclePalIdx(pal_idx));
        return true;
    }
    writeBodyTint(self, mat_name, shinePaletteColor(shine_type, pal_idx),
                  /*is_dot=*/is_dot);
    return true;
}

HkTrampoline<void, void*, const void*> shineInitColorOverride =
    hk::hook::trampoline([](void* self, const void* init_info) -> void {
        shineInitColorOverride.orig(self, init_info);
        if (!self) return;
        if (s_setMaterialProgrammable == nullptr ||
            s_setModelMaterialParameterRgba == nullptr) return;

        const int pal_idx_signed = resolveShinePalIdx(self);
        if (pal_idx_signed < 0) return;
        const std::size_t pal_idx = static_cast<std::size_t>(pal_idx_signed);
        const int shine_type = readShineType(self);

        // Required model-presence guard. Some Shine::init paths complete
        // without allocating mModelKeeper — confirmed for the linked-Shine
        // inside AppearSwitchTimer when re-entering Cascade after the
        // first multi-moon (scenario reload spawns the already-collected
        // shine as a stub). isExistMaterial, setMaterialProgrammable, and
        // setModelMaterialParameter* all deref the model keeper without a
        // null check and crash. isExistModel is the canonical null-safe
        // probe (used the same way in OdysseyDecomp's AppearSwitchTimer).
        if (s_isExistModel == nullptr || !s_isExistModel(self)) return;

        // Authentic per-kingdom frame override. For the 11 kingdoms with a
        // distinct vanilla color frame, re-drive the "Color" anim to the
        // GRANTED kingdom's frame and skip the material tint entirely (the two
        // never combine — writeBodyTint's setMaterialProgrammable would freeze
        // the anim we just set). The 6 frame-0 "tint" kingdoms (kColorFrameTint)
        // and the classification colors (idx 0..4) fall through to writeBodyTint.
        const int frame = kingdomColorFrameForPal(pal_idx);
        if (frame >= 0) {
            // Guard: stub linked-Shines (Pyramid's createLinksActorFromFactory
            // shine) pass isExistModel but carry no Mcl "Color" anim player, so
            // setStageShineAnimFrame -> startMclAnimAndSetFrameAndStop would
            // null-deref. Skip the frame path for them and fall through to the
            // material-tint fallback (the kingdom's Color4f row). When the symbol
            // didn't resolve, the guard is permissive (proceed as before).
            const bool color_anim_ok =
                s_isMclAnimExist == nullptr || s_isMclAnimExist(self, "Color");
            if (s_setStageShineAnimFrame != nullptr && color_anim_ok) {
                s_setStageShineAnimFrame(self, /*stageName=*/nullptr, frame,
                                         kColorAnimIsMatAnim);
                static int s_frame_logged = 0;
                if (s_frame_logged < 8) {
                    SMOAP_LOG_INFO("[shine-frame] override#%d type=%d frame=%d",
                                   s_frame_logged + 1, shine_type, frame);
                    ++s_frame_logged;
                }
                return;
            }
            // symbol missing / no Color anim -> material fallback below.
        }

        if (!tryWriteShineTint(self, shine_type, pal_idx)) {
            static bool s_warned[3] = {false, false, false};
            const char* mat_name = shineMaterialNameForType(shine_type);
            if (shine_type >= 0 && shine_type < 3 && !s_warned[shine_type]) {
                s_warned[shine_type] = true;
                SMOAP_LOG_WARN("[shine-color] type=%d has no material '%s' — "
                               "override disabled for this type",
                               shine_type, mat_name);
            }
            return;
        }

        static int s_logged = 0;
        if (s_logged < 8) {
            SMOAP_LOG_INFO("[shine-color] override#%d type=%d palette=%zu",
                           s_logged + 1, shine_type, pal_idx);
            ++s_logged;
        }
    });

// Re-assert our color override whenever the game re-drives a shine's vanilla
// "Color" anim. Vanilla calls rs::setStageShineAnimFrame from the appear/popup
// sequence (AFTER Shine::init) for moons that SPAWN at runtime — opening a
// treasure chest, starting a kingdom timer challenge, etc. Without this hook the
// init-time override above is silently overwritten and the spawned moon reverts
// to its vanilla per-kingdom color; moons already present at stage load never
// hit this second call, which is why only spawned ones looked wrong. The actor
// param is always the Shine (OdysseyDecomp src/Util/ItemUtil.cpp), so we resolve
// its palette the same way as init. We only call .orig() (never the patched
// entry), so there is no recursion.
HkTrampoline<void, void*, const char*, int, bool> setStageShineAnimFrameOverride =
    hk::hook::trampoline([](void* actor, const char* stage_name, int frame,
                            bool is_mat_anim) -> void {
        if (!actor) {
            setStageShineAnimFrameOverride.orig(actor, stage_name, frame,
                                                is_mat_anim);
            return;
        }
        const int pal_idx_signed = resolveShinePalIdx(actor);
        if (pal_idx_signed < 0) {
            setStageShineAnimFrameOverride.orig(actor, stage_name, frame,
                                                is_mat_anim);
            return;
        }
        const std::size_t pal_idx = static_cast<std::size_t>(pal_idx_signed);

        // Frame-override kingdom: substitute OUR granted kingdom's frame into
        // the vanilla call. Vanilla itself is the caller here, so the "Color"
        // anim is guaranteed present (it would crash its own call otherwise) —
        // no isMclAnimExist guard needed for this path.
        const int our_frame = kingdomColorFrameForPal(pal_idx);
        if (our_frame >= 0) {
            setStageShineAnimFrameOverride.orig(actor, stage_name, our_frame,
                                                is_mat_anim);
            return;
        }

        // Tint kingdom (frame 0 / kColorFrameTint) or classification color
        // (idx 0..4): let vanilla drive its frame first, then multiply our
        // material tint on top (programmable params win over the Mcl anim).
        setStageShineAnimFrameOverride.orig(actor, stage_name, frame,
                                            is_mat_anim);
        if (s_setMaterialProgrammable == nullptr ||
            s_setModelMaterialParameterRgba == nullptr) return;
        tryWriteShineTint(actor, readShineType(actor), pal_idx);
    });

// The Shine's currently-VISIBLE model: the demo model during the get cutscene,
// the world model otherwise. Falls back to the Shine actor itself when the
// getCurrentModel symbol didn't resolve or returns null (pre-fix behavior).
inline void* shineVisibleModel(void* self) {
    if (s_getCurrentModel != nullptr) {
        void* m = s_getCurrentModel(self);
        if (m != nullptr) return m;
    }
    return self;
}

// Apply the resolved color to ONE model actor. `shine_type` and `pal_idx` are
// resolved from the Shine; `model_actor` is the actor whose material we write —
// the Shine itself for world moons, or its demo model (getCurrentModel) for the
// get cutscene. Mirrors the init/control color decision (cycle → frame-override
// → static tint) and guards model + material presence per-actor, so a demo
// model lacking a model keeper or the "BodyMT" material is skipped (no crash,
// no recolor) rather than asserting it matches the Shine. Returns true if a
// color was written.
//
// The frame-override path drives the "Color" anim via setStageShineAnimFrame-
// Override.orig (NOT s_setStageShineAnimFrame, whose address is hooked): going
// through the hook would re-resolve the palette off `model_actor`, and the demo
// model is not a Shine — reading the mShineIdx offset off it yields garbage.
// .orig drives our already-resolved frame straight onto whatever model.
bool applyShineColorTo(void* model_actor, int shine_type, std::size_t pal_idx) {
    if (model_actor == nullptr) return false;
    if (s_isExistModel == nullptr || !s_isExistModel(model_actor)) return false;
    const char* mat_name = shineMaterialNameForType(shine_type);
    if (s_isExistMaterial != nullptr && !s_isExistMaterial(model_actor, mat_name))
        return false;

    if (kClassColorCycle && isCyclePal(pal_idx)) {
        applyClassCycleColor(model_actor, mat_name, /*is_dot=*/shine_type == 1,
                             cyclePalIdx(pal_idx));
        return true;
    }
    const int frame = kingdomColorFrameForPal(pal_idx);
    if (frame >= 0) {
        const bool color_anim_ok =
            s_isMclAnimExist == nullptr || s_isMclAnimExist(model_actor, "Color");
        if (s_setStageShineAnimFrame != nullptr && color_anim_ok) {
            setStageShineAnimFrameOverride.orig(model_actor, /*stageName=*/nullptr,
                                                frame, kColorAnimIsMatAnim);
            return true;
        }
        // symbol missing / no Color anim -> material-tint fallback below.
    }
    writeBodyTint(model_actor, mat_name, shinePaletteColor(shine_type, pal_idx),
                  /*is_dot=*/shine_type == 1);
    return true;
}

// Per-frame color hook. Shine::control runs every frame with `this` == the
// Shine, so this is the universal chokepoint for keeping a moon's color correct
// no matter how it spawned or which cutscene state it's in. Two jobs:
//   * classification shines (idx 0..3): advance the animated primary<->#316b84
//     cycle (applyClassCycleColor recomputes the lerp from the wall clock and
//     re-writes the material; the params persist otherwise) — kClassColorCycle.
//   * kingdom shines (idx 5+): re-assert the frame-override / static tint every
//     frame so the color survives the get cutscene and runtime spawn/appear
//     paths that the init + setStageShineAnimFrame hooks miss — kPerFrameColorEnforce.
// Installed when EITHER flag is on; with both off there is zero per-frame cost.
HkTrampoline<void, void*> shineControlColorCycle =
    hk::hook::trampoline([](void* self) -> void {
        shineControlColorCycle.orig(self);
        if (!self) return;
        if (s_setMaterialProgrammable == nullptr ||
            s_setModelMaterialParameterRgba == nullptr) return;
        const int pal = resolveShinePalIdx(self);
        if (pal < 0) return;
        const std::size_t pal_idx = static_cast<std::size_t>(pal);
        const int shine_type = readShineType(self);

        // Run the animated cycle whenever it applies (classification colors +
        // the test-forced pulse kingdoms); otherwise only when per-frame kingdom
        // enforcement is on. With both off there's nothing to re-assert.
        const bool is_cycle = kClassColorCycle && isCyclePal(pal_idx);
        if (!is_cycle && !kPerFrameColorEnforce) return;

        // Re-assert the color on the Shine's own model AND on its currently-
        // visible model. They differ during the "You got a Moon!" get cutscene,
        // where the moon is shown as a separate demo model actor — recoloring
        // only the Shine leaves that demo model vanilla gold (the bug Devon hit:
        // a Wooded moon's get screen showed gold, not Wooded blue). applyShine-
        // ColorTo guards model/material presence per-actor and internally picks
        // cycle / frame-override / static tint, identical to the Shine::init
        // path. This is what keeps the color pinned through the cutscene and
        // every runtime spawn/appear path (timer challenges, Toad hand-offs, …).
        applyShineColorTo(self, shine_type, pal_idx);
        if (kRecolorVisibleModel) {
            void* vis = shineVisibleModel(self);
            if (vis != self) {
                applyShineColorTo(vis, shine_type, pal_idx);
                static int s_vis_logged = 0;
                if (s_vis_logged < 4) {
                    SMOAP_LOG_INFO("[shine-color] recolored visible demo model "
                                   "(type=%d palette=%zu) — distinct from Shine",
                                   shine_type, pal_idx);
                    ++s_vis_logged;
                }
            }
        }
    });

template <typename FnPtr>
inline void resolveSymbol(const char* mangled, FnPtr& out, const char* label) {
    const ptr addr = hk::ro::lookupSymbol(mangled);
    if (addr == 0) {
        SMOAP_LOG_ERROR("%s lookup FAILED", label);
        out = nullptr;
        return;
    }
    out = reinterpret_cast<FnPtr>(addr);
    SMOAP_LOG_INFO("%s resolved @ 0x%lx", label, static_cast<unsigned long>(addr));
}

}  // namespace

void installShineAppearanceHook() {
    resolveSymbol(smoap::sym::kAlSetMaterialProgrammable,
                  s_setMaterialProgrammable, "setMaterialProgrammable");
    resolveSymbol(smoap::sym::kAlSetModelMaterialParameterRgba,
                  s_setModelMaterialParameterRgba, "setModelMaterialParameterRgba");
    resolveSymbol(smoap::sym::kAlSetModelMaterialParameterF32,
                  s_setModelMaterialParameterF32, "setModelMaterialParameterF32");
    resolveSymbol(smoap::sym::kAlIsExistMaterial,
                  s_isExistMaterial, "isExistMaterial");
    resolveSymbol(smoap::sym::kAlIsExistModel,
                  s_isExistModel, "isExistModel");
    // Authentic per-kingdom frame override (P5). Best-effort: a lookup miss
    // just disables the frame-override path and falls back to material tints.
    resolveSymbol(smoap::sym::kRsSetStageShineAnimFrame,
                  s_setStageShineAnimFrame, "setStageShineAnimFrame");
    // Guard for the frame path — stub linked-Shines lack the Mcl "Color" anim.
    resolveSymbol(smoap::sym::kAlIsMclAnimExist,
                  s_isMclAnimExist, "isMclAnimExist");
    // Visible-model resolver for the get-cutscene recolor. Best-effort: a lookup
    // miss (e.g. getCurrentModel inlined with no out-of-line copy) just disables
    // the demo-model recolor and falls back to recoloring the Shine actor. The
    // resolved-@/FAILED line in the log confirms which case this build hit.
    resolveSymbol(smoap::sym::kShineGetCurrentModel,
                  s_getCurrentModel, "Shine::getCurrentModel");

    if (s_setMaterialProgrammable != nullptr &&
        s_setModelMaterialParameterRgba != nullptr) {
        SMOAP_LOG_INFO("installing ShineInitColorOverride -> Shine::init");
        // Sail-resolved at link time so we don't need to bake the string here
        // — pass the catalog constant to the templated installAtSym via
        // util::TemplateString conversion. NOTE: HkTrampoline.installAtSym is
        // a consteval template, requires a literal — so we duplicate the
        // string here for now. Keep in sync with HookSymbols.hpp's kShineInit.
        shineInitColorOverride.installAtSym<
            "_ZN5Shine4initERKN2al13ActorInitInfoE">();

        // Re-assert the override when the game re-drives a shine's "Color" anim
        // during the appear/popup sequence (spawned moons: chests, timer
        // challenges). Install at the address we already resolved for
        // s_setStageShineAnimFrame (the symbol is intentionally NOT in the sail
        // .sym, so we install by ptr, gracefully skipping on a lookup miss).
        if (s_setStageShineAnimFrame != nullptr) {
            SMOAP_LOG_INFO("installing SetStageShineAnimFrameOverride -> "
                           "rs::setStageShineAnimFrame");
            const auto rc = setStageShineAnimFrameOverride.installAtPtr(
                reinterpret_cast<ptr>(s_setStageShineAnimFrame));
            if (rc.failed())
                SMOAP_LOG_ERROR("setStageShineAnimFrame trampoline install FAILED");
        } else {
            SMOAP_LOG_WARN("rs::setStageShineAnimFrame unresolved — spawned-moon "
                           "recolor not active");
        }

        // Per-frame Shine::control trampoline. Drives BOTH the classification
        // color cycle (kClassColorCycle) AND the kingdom-color enforcement that
        // keeps colors pinned through the get cutscene + runtime spawn paths
        // (kPerFrameColorEnforce). Installed only when at least one is enabled,
        // so flipping both flags false leaves zero per-frame cost.
        if (kClassColorCycle || kPerFrameColorEnforce) {
            SMOAP_LOG_INFO("installing ShineControlColorCycle -> Shine::control "
                           "(cycle=%d enforce=%d)",
                           static_cast<int>(kClassColorCycle),
                           static_cast<int>(kPerFrameColorEnforce));
            shineControlColorCycle.installAtSym<"_ZN5Shine7controlEv">();
        }
    }
}

}  // namespace smoap::hooks
