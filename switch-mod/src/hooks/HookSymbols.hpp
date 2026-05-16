// Mangled symbol catalog for hooks.
//
// All InstallAtSymbol() calls pull their mangled name from here so version
// bumps are isolated to this single file. exlaunch resolves these via
// nn::ro::LookupSymbol() at module load.
//
// Provenance:
//   - 3 of 8 symbols (drawMain, GameSystem::init, Scene::endInit) are byte-
//     identical to the names lunakit hooks in src/program/main.cpp on SMO
//     1.0.0. Verified working.
//   - The other 5 (moon setter, capture startHack, scenario setter, save
//     init, wedding demo) were computed from MonsterDruide1/OdysseyDecomp
//     forward-declarations passed through aarch64-none-elf-g++. Itanium ABI
//     mangling is deterministic from the signature alone, so these names
//     are 1.0.0-correct as long as the decomp signatures match the runtime
//     symbol — verify by nm against the combined cart+SMO-Downgrade-overlay
//     binary before depending on them in M4+.

#pragma once

namespace smoap::sym {

// --- Frame pump ---
// HakoniwaSequence::drawMain() const  (override of al::Sequence)
// Source: lunakit src/program/main.cpp UpdateLunaKit hook (verified on 1.0.0)
inline constexpr const char* kHakoniwaSequenceDrawMain =
    "_ZNK16HakoniwaSequence8drawMainEv";

// --- Game system init ---
// GameSystem::init()
// Source: lunakit src/program/main.cpp GameSystemInit hook (verified on 1.0.0).
// NOTE: NOT sead::GameSystem — this is SMO's GameSystem in the global
// namespace. Lunakit hooks it for the same reason we want it: late-enough
// in init that the heap is up but early enough to set up our subsystems.
inline constexpr const char* kGameSystemInit =
    "_ZN10GameSystem4initEv";

// --- Scene init (kingdom transition signal) ---
// al::Scene::endInit(const al::ActorInitInfo&)
// Source: lunakit src/program/main.cpp SceneEndInitHook (verified on 1.0.0)
inline constexpr const char* kAlSceneEndInit =
    "_ZN2al5Scene7endInitERKNS_13ActorInitInfoE";

// --- Moon flag set ---
// GameDataFile::setGotShine(const ShineInfo*)
// Source: MonsterDruide1/OdysseyDecomp src/System/GameDataFile.h:252
// Rationale: this is THE chokepoint that flips the moon-collected bit. It's
// called from setGotShine(GameDataHolderAccessor, const ShineInfo*) in
// GameDataFunction.cpp:528 and from the ShineActor on collect.
inline constexpr const char* kGameDataFileSetGotShine =
    "_ZN12GameDataFile11setGotShineEPK9ShineInfo";

// --- Capture acquired (gates + check) ---
// PlayerHackKeeper::startHack(al::HitSensor*, al::HitSensor*, al::LiveActor*)
// Source: MonsterDruide1/OdysseyDecomp src/Player/PlayerHackKeeper.h:47
// HOOK MODE: TRAMPOLINE in M4 (read-only check), REPLACE-with-conditional in M7
// (refuse if cap not unlocked). Third arg is the LiveActor we're hacking —
// extract its name via the actor's hack-data table to identify the cap-type.
inline constexpr const char* kPlayerHackKeeperStartHack =
    "_ZN16PlayerHackKeeper9startHackEPN2al9HitSensorES2_PNS0_9LiveActorE";

// PlayerHackKeeper::forceKillHack()
// Source: MonsterDruide1/OdysseyDecomp src/Player/PlayerHackKeeper.h
// Used by M7 to abort an in-progress capture when AP hasn't unlocked it.
// Called from CaptureStartHook callback right after Orig has populated the
// keeper, so we can read the cap name (getCurrentHackName) and decide to
// cancel without ever needing to know the name pre-startHack.
//
// We chose forceKillHack over cancelHack: playtested 2026-05-16, cancelHack
// returned cleanly (no crash) but did NOT release Mario — likely because the
// hack state machine hasn't fully entered the dive-in demo at the moment
// startHack returns, and cancelHack is a soft "player wants out" path that
// is a no-op in that window. forceKillHack is the hardest teardown, used
// internally for kingdom transitions / boss-defeat resets. Body is also
// not decompiled but the name + caller pattern suggests it's the right tool.
inline constexpr const char* kPlayerHackKeeperForceKillHack =
    "_ZN16PlayerHackKeeper13forceKillHackEv";

// --- Scenario flag set ---
// GameDataFile::setMainScenarioNo(s32)  (s32 = int on aarch64)
// Source: MonsterDruide1/OdysseyDecomp src/System/GameDataFile.h:456
// Useful for tracker UI ("Mario is on Mission 3 of Cap Kingdom").
inline constexpr const char* kGameDataFileSetMainScenarioNo =
    "_ZN12GameDataFile17setMainScenarioNoEi";

// --- Save data load ---
// GameDataFile::initializeData()
// Source: MonsterDruide1/OdysseyDecomp src/System/GameDataFile.h:202
// CAVEAT: this is one candidate; it's the post-load init pass. If it doesn't
// fire on every save reload, fall back to hooking GameDataFile's read(...)
// override (search Ghidra for ByamlSave::read overrides on GameDataFile).
inline constexpr const char* kGameDataFileInitializeData =
    "_ZN12GameDataFile14initializeDataEv";

// --- Goal trigger (Bowser-defeat wedding cutscene fires) ---
// DemoPeachWedding::makeActorAlive()  (override of al::LiveActor)
// Source: MonsterDruide1/OdysseyDecomp src/Demo/DemoPeachWedding.h:8
// This is the precise moment the wedding ending demo activates. Idempotent
// guard via ApState::goal_sent so a "watch credits twice" scenario doesn't
// re-fire.
inline constexpr const char* kDemoPeachWeddingMakeActorAlive =
    "_ZN16DemoPeachWedding14makeActorAliveEv";

// --- Mario death (DeathLink outbound) ---
// PlayerHitPointData::kill()
// Source: lunakit-vendor/src/game/GameData/PlayerHitPointData.h:25
// Single chokepoint: all death paths (PlayerStateDamageLife, fall area,
// drown, poison, abyss) converge here when HP transitions to 0. Idempotent
// guard via ApState::death_pending_send so respawn-area double-calls don't
// re-fire DeathLink bounces.
inline constexpr const char* kPlayerHitPointDataKill =
    "_ZN18PlayerHitPointData4killEv";

// =============================================================================
// M6 — moon counter HUD substitution (phase A).
// =============================================================================
//
// Goal: surface AP-credit counts in the in-game moon counter without flipping
// any actual shine flags. We hook the two getters SMO uses for HUD/menu
// rendering and return orig() + our AP-credit total.
//
// Provenance: forward-declared in lunakit-vendor/src/game/GameData/
// GameDataFunction.h:129,131 (cited from OdysseyDecomp). Mangled via
// aarch64-none-elf-g++ -c on a minimal forward-decl TU (see scripts/check_
// nso_symbols.py for the full symbol list verified against main.nso).

// GameDataFunction::getCurrentShineNum(GameDataHolderAccessor)
// Returns total moon count across all kingdoms (HUD top-left "x/N").
inline constexpr const char* kGameDataFunctionGetCurrentShineNum =
    "_ZN16GameDataFunction18getCurrentShineNumE22GameDataHolderAccessor";

// GameDataFunction::getGotShineNum(GameDataHolderAccessor, s32 file_id)
// CAVEAT (M6 phase D audit): the int parameter is `file_id` (save-slot index,
// default -1), NOT a world id, per OdysseyDecomp src/System/GameDataFunction.h.
// Returns global lifetime collected moons from the given save slot. SMO's
// per-kingdom HUD reads GameDataFile::getShineNum(world_id) directly via
// inlined field access — there's no symbol to hook for the per-kingdom view.
// CLAUDE.md's note that this hook never fires in normal Cascade play is
// consistent with that finding. The misleading "GotShineNum" reads as
// "per-kingdom" because that's the natural interpretation of "world" in SMO
// terminology, but the API is save-slot-scoped. Kept hooked as defense.
inline constexpr const char* kGameDataFunctionGetGotShineNum =
    "_ZN16GameDataFunction14getGotShineNumE22GameDataHolderAccessori";

// =============================================================================
// M6 phase D — moon-deposit debit (AP credit decrements on Odyssey toss).
// =============================================================================
//
// When Mario hand-tosses moons at an Odyssey, vanilla SMO does NOT mutate
// `mShineNum` directly. It calls GameDataFile::addPayShine(s32) which grows
// a separate `PayShineNum` counter; the HUD's spendable-fuel total is
// `getCurrentShineNum() = ShineNum - PayShineNum` clamped to 0.
//
// GameDataFile::addPayShine(s32) IS INLINED into all callers in 1.0.0 main.nso
// and not present in dynsym. The PUBLIC WRAPPER GameDataFunction::addPayShine
// (GameDataHolderWriter, int) IS in dynsym — verified via
// scripts/check_nso_symbols.py. Same hookability pattern as addHackDictionary.
// All game-side payment paths route through this wrapper per OdysseyDecomp.
//
// addPayShineCurrentAll() is the "pay everything in current kingdom" variant
// (probably used in kingdom-complete celebrations). We hook it secondarily so
// non-per-toss payments aren't lost; for those, the count is computed via the
// AP-credit balance for currentKingdom.
//
// getCurrentWorldIdNoDevelop is the safe `getCurrentWorldId` variant that
// clamps the develop-state `-1` return to 0. We resolve it via
// nn::ro::LookupSymbol once and call through a function pointer (same as
// addHackDictionary), since this is read-only inside our hook callback.
inline constexpr const char* kGameDataFunctionAddPayShine =
    "_ZN16GameDataFunction11addPayShineE20GameDataHolderWriteri";
inline constexpr const char* kGameDataFunctionAddPayShineCurrentAll =
    "_ZN16GameDataFunction21addPayShineCurrentAllE20GameDataHolderWriter";
inline constexpr const char* kGameDataFunctionGetCurrentWorldIdNoDevelop =
    "_ZN16GameDataFunction26getCurrentWorldIdNoDevelopE22GameDataHolderAccessor";

// =============================================================================
// M6 phase B — capture grant (addHackDictionary + idempotency probe).
// =============================================================================
//
// Goal: when AP grants a capture item, the mod writes the cap's hack_name into
// SMO's hack dictionary so the capture compendium / gameplay treats it as
// owned. Idempotency uses isExistInHackDictionary to skip redundant calls.
//
// Provenance: same OdysseyDecomp forward-decls in lunakit-vendor/src/game/
// GameData/GameDataFunction.h:361,362. Mangled via aarch64-none-elf-g++ -c.

// GameDataFunction::addHackDictionary(GameDataHolderWriter, const char* hack_name)
inline constexpr const char* kGameDataFunctionAddHackDictionary =
    "_ZN16GameDataFunction17addHackDictionaryE20GameDataHolderWriterPKc";

// GameDataFunction::isExistInHackDictionary(GameDataHolderAccessor, const char* hack_name)
inline constexpr const char* kGameDataFunctionIsExistInHackDictionary =
    "_ZN16GameDataFunction23isExistInHackDictionaryE22GameDataHolderAccessorPKc";

// =============================================================================
// M6 phase A.5 — moon-get cutscene label substitution (Channel A).
// =============================================================================
//
// Goal: when Mario collects a moon, replace the cutscene's "TxtScenario" pane
// text with AP-aware text (e.g. "Sent Cap Power Moon -> P3" / "Got X!").
//
// All four target symbols verified in SMO 1.0.0 main.nso .dynsym via
// scripts/check_nso_symbols.py (HIT). Layout offsets + pane name derived
// from disassembling each call site (see plan
// i-wrote-a-plan-fluffy-otter.md "Phase 0 findings").
//
// Three cutscene-state functions cover all moon collects:
//   - StageSceneStateGetShine::exeDemoGet — regular moons
//       layout @ self+0x20, pane "TxtScenario"
//   - StageSceneStateGetShineMain::exeDemoGetStart — main story moons
//       layout @ self+0x40, pane "TxtScenario"
//   - StageSceneStateGetShineGrand::exeDemoGetStart — grand shines
//       layout @ self+0x40, pane "TxtScenario"
//
// (StageSceneStateGetShineGrand::exeDemoGetFirst exists but doesn't touch
// the title pane — multi-grand-shine intro state, no label work needed.)

// StageSceneStateGetShine::exeDemoGet()  — regular moon cutscene (every frame)
inline constexpr const char* kStageSceneStateGetShineExeDemoGet =
    "_ZN23StageSceneStateGetShine10exeDemoGetEv";

// StageSceneStateGetShineMain::exeDemoGetStart()  — story moon cutscene
inline constexpr const char* kStageSceneStateGetShineMainExeDemoGetStart =
    "_ZN27StageSceneStateGetShineMain15exeDemoGetStartEv";

// StageSceneStateGetShineGrand::exeDemoGetStart()  — grand shine cutscene
inline constexpr const char* kStageSceneStateGetShineGrandExeDemoGetStart =
    "_ZN28StageSceneStateGetShineGrand15exeDemoGetStartEv";

// al::setPaneStringFormat(al::IUseLayout*, char* paneName, char* fmt, ...)
// SDK helper that writes formatted text into a named pane. VARARG (the
// trailing `z` in the mangled name = `...`). We pass "%s" as the format
// and the AP text as the single arg so any non-`%` characters are safe.
inline constexpr const char* kAlSetPaneStringFormat =
    "_ZN2al19setPaneStringFormatEPNS_10IUseLayoutEPKcS3_z";

// =============================================================================
// "Cappy Messenger" — in-game speech bubble for AP item notifications.
// =============================================================================
//
// Goal: route AP item notifications through SMO's existing Cappy speech-bubble
// pipeline (rs::tryShowCapMessage*) so we get Nintendo's font, layout, and
// animation for free — sidestepping the sead::TextWriter font-init dead end.
//
// Mechanism: call rs::tryShowCapMessagePriorityLow with a magic label
// (kArchipelagoLabel below). The MSBT lookup for that label is intercepted by
// MessageHolderTryGetTextHook, which returns a pointer to our own UTF-16
// buffer holding "Got <name> from <sender>!". The rest of the CapMessage
// pipeline runs unmodified.
//
// Provenance: all 3 symbols mangled via aarch64-none-elf-g++ from forward
// decls matching MonsterDruide1/OdysseyDecomp lib/al/Library/Message/
// MessageHolder.h and src/MapObj/CapMessageShowInfo.h, and verified present in
// real 1.0.0 main.nso via scripts/check_nso_symbols.py.

// CapMessageLayout::exeDelay does:
//   if (isStageMessage)
//      if (isExistLabelInStageMessage(holder, mstxt, label))
//          text = getStageMessageString(holder, mstxt, label);
//   else
//      if (isExistLabelInSystemMessage(holder, mstxt, label))
//          text = getSystemMessageString(holder, mstxt, label);
//
// rs::tryShowCapMessagePriorityLow passes isStageMessage=false so only the
// system path fires in our scenario, but we hook all 4 for robustness in
// case future code paths use the stage variant. Each trampoline:
//   - returns our buffer / true when the label matches kArchipelagoLabel
//     and CappyMessenger has a buffer ready
//   - otherwise tail-calls Orig
//
// These DON'T go through al::MessageHolder::tryGetText — that's a deeper
// internal that some lookups bypass entirely. Hooking the top-level
// per-mstxt-file accessors above is what actually intercepts CapMessage's
// text resolution. The (string-existence-bool, get-string-text) pair maps
// 1:1 to our (in_use_flag, buffer_pointer) state.

inline constexpr const char* kAlIsExistLabelInSystemMessage =
    "_ZN2al27isExistLabelInSystemMessageEPKNS_17IUseMessageSystemEPKcS4_";
inline constexpr const char* kAlGetSystemMessageString =
    "_ZN2al22getSystemMessageStringEPKNS_17IUseMessageSystemEPKcS4_";
inline constexpr const char* kAlIsExistLabelInStageMessage =
    "_ZN2al26isExistLabelInStageMessageEPKNS_17IUseMessageSystemEPKcS4_";
inline constexpr const char* kAlGetStageMessageString =
    "_ZN2al21getStageMessageStringEPKNS_17IUseMessageSystemEPKcS4_";

// rs::tryShowCapMessagePriorityLow(const al::IUseSceneObjHolder*,
//                                  const char* label, s32 delay, s32 wait)
// The "polite" Cappy-speech entry point: queues behind any active high-
// priority message and returns false silently if the scene/state can't accept
// one (2D, cutscene, paused). We call this each frame from CappyMessenger::
// tryPump until it returns true.
//
// We do NOT trampoline this — we resolve the address via nn::ro::LookupSymbol
// and call through a function pointer (same pattern as M6 phase B's
// addHackDictionary).
inline constexpr const char* kRsTryShowCapMessagePriorityLow =
    "_ZN2rs28tryShowCapMessagePriorityLowEPKN2al18IUseSceneObjHolderEPKcii";

// rs::isActiveCapMessage(const al::IUseSceneObjHolder*)
// Probe: returns true while a CapMessage is on screen. CappyMessenger::tryPump
// checks this to keep our backing buffer stable for the duration of an active
// balloon (the buffer must not be overwritten while SMO is reading from it).
//
// Also resolved via LookupSymbol + function pointer.
inline constexpr const char* kRsIsActiveCapMessage =
    "_ZN2rs18isActiveCapMessageEPKN2al18IUseSceneObjHolderE";

// =============================================================================
// M-color — per-shine palette override (AP classification -> moon color).
// =============================================================================
//
// Implemented as inline patches at 4 BL call sites inside Shine::init
// (offsets 0x1cdce4 / 0x1cdd3c / 0x1cddcc / 0x1cde24 on 1.0.0). See
// hooks/ShineAppearanceHook.cpp. No symbol lookup needed.
//
// The patched BLs target rs::setStageShineAnimFrame(al::LiveActor*,
// const char*, s32, bool) — we don't hook it, we just substitute the color
// arg right before the BL fires. Earlier attempts to trampoline-hook that
// symbol directly crashed because it's also called from ShineTowerRocket
// (and other non-Shine actors) where Shine-class field offsets aren't valid.

// =============================================================================
// M7 Path A — world-map kingdom-order gate (three-layer architecture).
// =============================================================================
//
// Forces linear progression at SMO's two world-map bifurcations by substituting
// gated worldIds with their prerequisite kingdom's worldId at every layer the
// world-map UI / fork cinematic can ask "what kingdom is at this slot?". From
// SMO's perspective the gated kingdom is never offered.
//
// Eight symbols total, organized in three layers:
//
//   Layer 1 — regular world-map UI per-slot query (4 overloads by ptr-type):
//     The Odyssey's world map, opened any time after the post-Sand /
//     post-Metro fork has been resolved, calls these to populate slot N with
//     a worldId. Verified firing on LiveActor + Scene overloads in playtest.
//
//   Layer 2 — post-Multi-Moon FORK cinematic per-slot query (2 overloads):
//     The one-time "newly unlocked" presentation that plays right after
//     collecting a kingdom's Multi-Moon uses these instead of Layer 1.
//     Verified firing as the Scene overload in the 2026-05-17 fork playtest.
//
//   Layer 3 — actual stage-commit chokepoint (BACKSTOP, 2 functions):
//     Substitutes the `stage` arg if neither Layer 1 nor Layer 2 caught the
//     destination. Substitution at this layer can produce broken cutscene
//     visuals (Mario in destination kingdom without the Odyssey, frozen
//     camera — per CLAUDE.md M7 section's prior-iteration failure log), so
//     the WARN log on a fired backstop is a signal that an upstream catch
//     needs adding.
//
// All 8 verified against SMO 1.0.0 main.nso via scripts/check_nso_symbols.py.

// ---- Layer 1: regular world-map UI ----
inline constexpr const char* kGameDataFunctionGetUnlockWorldIdForWorldMap_Holder =
    "_ZN16GameDataFunction27getUnlockWorldIdForWorldMapEPK14GameDataHolderi";
inline constexpr const char* kGameDataFunctionGetUnlockWorldIdForWorldMap_LayoutActor =
    "_ZN16GameDataFunction27getUnlockWorldIdForWorldMapEPKN2al11LayoutActorEi";
inline constexpr const char* kGameDataFunctionGetUnlockWorldIdForWorldMap_Scene =
    "_ZN16GameDataFunction27getUnlockWorldIdForWorldMapEPKN2al5SceneEi";
inline constexpr const char* kGameDataFunctionGetUnlockWorldIdForWorldMap_LiveActor =
    "_ZN16GameDataFunction27getUnlockWorldIdForWorldMapEPKN2al9LiveActorEi";

// ---- Layer 2: post-Multi-Moon FORK cinematic ----
inline constexpr const char* kGameDataFunctionCalcNextLockedWorldIdForWorldMap_LayoutActor =
    "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al11LayoutActorEi";
inline constexpr const char* kGameDataFunctionCalcNextLockedWorldIdForWorldMap_Scene =
    "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al5SceneEi";

// ---- Layer 3: stage-commit BACKSTOP ----
inline constexpr const char* kGameDataFunctionTryChangeNextStageWithDemoWorldWarp =
    "_ZN16GameDataFunction35tryChangeNextStageWithDemoWorldWarpE20GameDataHolderWriterPKc";
inline constexpr const char* kGameDataFunctionTryChangeNextStageWithWorldWarpHole =
    "_ZN16GameDataFunction35tryChangeNextStageWithWorldWarpHoleE20GameDataHolderWriterPKc";

// =============================================================================
// Legacy / aliasing — kept so existing call sites don't break.
// =============================================================================
inline constexpr const char* kSeadGameSystemCtor       = kGameSystemInit;
inline constexpr const char* kShineGetSetter           = kGameDataFileSetGotShine;
inline constexpr const char* kScenarioNoSetter         = kGameDataFileSetMainScenarioNo;
inline constexpr const char* kSaveDataLoad             = kGameDataFileInitializeData;
inline constexpr const char* kEndingDemoStart          = kDemoPeachWeddingMakeActorAlive;

}  // namespace smoap::sym
