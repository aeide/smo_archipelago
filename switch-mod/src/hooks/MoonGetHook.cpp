// Hook on GameDataFile::setGotShine(const ShineInfo*).
//
// Reads (stageName, objectId, shineId) from the ShineInfo* via the layout
// mirror in game/ShineInfoLayout.hpp (no transitive lunakit-vendor pull-in)
// and ships the raw IDs to the bridge. The bridge resolves them against
// shine_map.json into the AP location name.

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE
#include "../ap/ApFrameBridge.hpp"
#include "../ap/ApState.hpp"
#include "../game/MoonApply.hpp"
#include "../game/ShineInfoLayout.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

class GameDataFile;
class ShineInfo;

namespace smoap::hooks {

namespace {

// Quick sanity check: do the first few bytes of a string pointer look like
// ASCII? If the offset is wrong we'll get random bytes or kernel addresses;
// using strlen / %s on those is fatal. Reject anything that doesn't smell
// like a normal printable string in the first 8 bytes.
bool stringSane(const char* s) {
    if (!s) return false;
    // Reject obvious junk pointer patterns (kernel addresses, low pages).
    auto p = reinterpret_cast<std::uintptr_t>(s);
    if (p < 0x10000) return false;  // null-ish page
    for (int i = 0; i < 8; ++i) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c == 0) return i > 0;       // empty string allowed only if first byte is non-null below... actually accept c==0 if i>0
        if (c < 0x20 || c > 0x7e) return false;
    }
    return true;
}

HOOK_DEFINE_TRAMPOLINE(MoonGetHook) {
    static void Callback(GameDataFile* self, const ShineInfo* info) {
        Orig(self, info);
        SMOAP_LOG_INFO("MoonGetHook fired: info=%p", info);
        if (!info) return;
        const char* stage = smoap::game::shine_info_layout::stageName(info);
        SMOAP_LOG_INFO("MoonGetHook: stage_ptr=%p", stage);
        const char* obj = smoap::game::shine_info_layout::objectId(info);
        SMOAP_LOG_INFO("MoonGetHook: obj_ptr=%p", obj);
        const char* scen = smoap::game::shine_info_layout::scenObjId(info);
        SMOAP_LOG_INFO("MoonGetHook: scen_ptr=%p", scen);
        const int uid = smoap::game::shine_info_layout::shineId(info);
        SMOAP_LOG_INFO("MoonGetHook: uid=%d", uid);

        const bool stage_ok = stringSane(stage);
        const bool obj_ok = stringSane(obj);
        const bool scen_ok = stringSane(scen);
        SMOAP_LOG_INFO("MoonGetHook: probe stage=%s obj=%s scen=%s uid=%d",
                       stage_ok ? stage : "<bad>",
                       obj_ok ? obj : "<bad>",
                       scen_ok ? scen : "<bad>",
                       uid);
        // The canonical moon identifier SMO emits is ObjId — a placement-file
        // reference like "obj214". This was confirmed end-to-end against
        // MoonFlow's ShineInfo schema (https://github.com/Amethyst-szs/MoonFlow):
        // display names are looked up by ("ScenarioName_" + ObjId) in the
        // per-stage MSBT, but ObjId alone is the stable identity. scenObjId
        // (offset 0x130) is just "ScenarioName_objN" — redundant. Keep the
        // probe log above for diagnostics, but report ObjId.
        if (stage_ok && obj_ok) {
            SMOAP_LOG_INFO("MoonGetHook: reporting stage=%s id=%s uid=%d", stage, obj, uid);
            smoap::ap::reportMoonChecked(stage, obj, uid);
        } else {
            SMOAP_LOG_WARN("MoonGetHook: insane string ptrs stage_ok=%d obj_ok=%d — "
                           "offsets in ShineInfoLayout.hpp likely wrong; dropping",
                           stage_ok ? 1 : 0, obj_ok ? 1 : 0);
        }
    }
};
}  // namespace

void installMoonGetHook() {
    SMOAP_LOG_INFO("installing MoonGetHook -> %s", smoap::sym::kGameDataFileSetGotShine);
    softInstallAtSymbol<MoonGetHook>(smoap::sym::kGameDataFileSetGotShine);
}

}  // namespace smoap::hooks
