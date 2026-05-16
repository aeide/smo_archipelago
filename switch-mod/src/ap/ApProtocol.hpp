// Wire format mirror for the Switch <-> Bridge channel.
// Authoritative spec lives in docs/wire-protocol.md and bridge/smo_ap_bridge/protocol.py.
//
// Single persistent TCP connection. Each message is one '\n'-terminated line
// of UTF-8 JSON. Field "t" is the message type. Max line: 8 KiB.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace smoap::ap {

inline constexpr std::size_t kMaxLineBytes = 8 * 1024;

enum class ItemKind : std::uint8_t {
    Moon = 0,
    Capture = 1,
    Kingdom = 2,
    Shop = 3,
    Other = 4,
};

const char* toWire(ItemKind k);          // "moon" / "capture" / ...
ItemKind fromWire(const std::string& s); // returns Other for unknown

// Switch -> Bridge ----------------------------------------------------------

struct Hello {
    std::string mod_ver;
    std::string smo_ver;
    std::string cap_table_hash;
};

// Fixed-size char buffer used for Check string fields. libstdc++'s
// std::string allocator path NULL-derefs in our subsdk9 context for any
// string that exceeds SSO (~15 bytes), same root cause as the std::set
// crash. Keeping checks allocation-free here means the frame thread can
// produce them without touching the broken allocator. 64 bytes covers every
// stage name, moon objectId, capture, and kingdom string SMO emits.
inline constexpr std::size_t kCheckFieldCap = 64;

// Copy a C-string into a fixed buffer, null-terminating. Null src -> empty.
inline void copyCheckField(char (&dst)[kCheckFieldCap], const char* src) {
    if (!src) { dst[0] = '\0'; return; }
    std::size_t i = 0;
    while (i + 1 < kCheckFieldCap && src[i] != '\0') {
        dst[i] = src[i];
        ++i;
    }
    dst[i] = '\0';
}

struct Check {
    ItemKind kind = ItemKind::Moon;
    // legacy resolved fields (still used by inbound items / shop / kingdom)
    char kingdom[kCheckFieldCap] = {};
    char shine_id[kCheckFieldCap] = {};
    char cap[kCheckFieldCap] = {};
    int slot = -1;  // -1 means absent
    // M4 raw identifiers — bridge resolves these via shine_map.json / capture_map.json
    char stage_name[kCheckFieldCap] = {};  // moons: ShineInfo::stageName
    char object_id[kCheckFieldCap] = {};   // moons: ShineInfo::objectId
    int shine_uid = -1;                    // moons: ShineInfo::shineId
    char hack_name[kCheckFieldCap] = {};   // captures: PlayerHackKeeper::getCurrentHackName
};

struct Status {
    std::string kingdom;
    int scenario = -1;
    int moons_collected = -1;
    std::string stage_name;  // M4: raw stage at the time of the scenario flip
};

struct Goal {};

struct Death {
    std::int64_t ts_ms = 0;
};

struct Ping {
    std::int64_t ts_ms = 0;
};

struct Log {
    std::string level = "info";
    std::string msg;
};

// State snapshot. Sent by the Switch on every (re)connect right after HELLO,
// and (transitively) on save load via SaveLoadHook -> requestRehello. Three
// kinds of message in sequence: one StateBegin, N StateChunk (per-stage shines
// + a trailing "_meta" chunk for cross-stage data), one StateEnd.
//
// Carries RAW SMO identifiers (stage_name, object_id, shine_uid, hack_name)
// matching M4's Check semantics; the bridge resolves via shine_map.json /
// capture_map.json. The bridge is the source of truth for what AP knows; the
// snapshot lets AP learn about anything collected while disconnected.
//
// These structs live on the WORKER thread (ApClient). std::string is safe
// there (Encoder uses it internally already); only the frame-thread Check
// requires the char[64] dance.

struct StateBegin {
    std::string mod_ver;
    int save_slot = -1;  // -1 means absent; bridge does NOT fence on this
};

struct ShineEntry {
    std::string object_id;
    int shine_uid = -1;
};

struct StateChunk {
    // Per-stage chunk: stage_name = SMO stage key (e.g. "CapWorldHomeStage"),
    //   shines = list of {object_id, shine_uid}.
    // Cross-stage "_meta" chunk: stage_name = "_meta", captures = list of raw
    //   hack_names, include_goal_reached/goal_reached for the goal flag.
    std::string stage_name;
    std::vector<ShineEntry> shines;
    std::vector<std::string> captures;
    bool include_goal_reached = false;
    bool goal_reached = false;
};

struct StateEnd {};

// Bridge -> Switch ----------------------------------------------------------

struct HelloAck {
    bool ok = false;
    std::string seed;
    std::string slot;
    std::string cap_table_hash;
    // Bridge-owned DeathLink toggle. Mod ships the inbound apply path
    // unconditionally; this flag gates whether we act on inbound kill messages
    // so the user enables DeathLink in bridge config without rebuilding.
    bool deathlink_enabled = false;
    std::string err;
};

struct ItemRef {
    ItemKind kind = ItemKind::Other;
    std::string kingdom;
    std::string shine_id;
    std::string cap;
    std::string name;
    int slot = -1;
};

struct CheckedReplay {
    std::vector<ItemRef> ids;
};

struct Item {
    ItemKind kind = ItemKind::Other;
    std::string kingdom;
    std::string shine_id;
    std::string cap;
    std::string name;
    int slot = -1;
    std::string from;
};

struct Print {
    std::string text;
};

struct ApStateMsg {
    // Renamed from ApState to avoid collision with class smoap::ap::ApState
    // (the in-process singleton). Carries the bridge's view of the AP-server
    // connection state.
    std::string conn;  // "disconnected" | "connecting" | "ready"
};

struct Pong {
    std::int64_t ts_ms = 0;
};

struct Err {
    std::string code;
    std::string ctx;
};

struct Kill {
    // DeathLink forwarded from another slot. M4 logs this; killing Mario
    // belongs to M6 where we also have the player-state-write machinery.
    std::string source;
    std::string cause;
};

// (de)serialization --------------------------------------------------------
// Implementations in ApProtocol.cpp use util/Json.hpp (no STL exceptions).

std::string encodeHello(const Hello&);
std::string encodeCheck(const Check&);
std::string encodeStatus(const Status&);
std::string encodeGoal();
std::string encodeDeath(const Death&);
std::string encodePing(const Ping&);
std::string encodeLog(const Log&);
std::string encodeStateBegin(const StateBegin&);
std::string encodeStateChunk(const StateChunk&);
std::string encodeStateEnd();

// Returns true on parse success and fills the discriminated union outputs.
struct DecodedMsg {
    std::string t;
    HelloAck hello_ack{};
    CheckedReplay checked_replay{};
    Item item{};
    Print print{};
    ApStateMsg ap_state{};
    Pong pong{};
    Err err{};
    Kill kill{};
};
bool decode(const char* data, std::size_t len, DecodedMsg& out);

}  // namespace smoap::ap
