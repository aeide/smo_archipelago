// TCP client to the PC bridge.
//
// Owns a single nn::socket TCP connection on a dedicated worker thread.
// The frame thread (drawMain trampoline) only touches ApState's lock-free
// SPSC rings; this thread does all blocking I/O.
//
// Thread sequence:
//   1. start() (called from frame thread inside GameSystemInit hook):
//      saves target, spawns worker, returns immediately.
//   2. initNetworking() (frame thread, before start): nn::nifm::Initialize +
//      SubmitNetworkRequestAndWait. nn::socket::Initialize is owned by SMO
//      itself — it's already brought up by the time GameSystem::init returns
//      (BSD RegisterClient happens during the Orig call). Calling Initialize
//      a second time asserts inside InitializeCommon. LunaKit avoids this by
//      installing a REPLACE no-op hook on nn::socket::Initialize and doing
//      its own bring-up first; we just piggy-back on SMO's.
//   3. threadMain() loop: connectOnce -> sendHello -> Select+recv read,
//      pumpOnce drain outbound, error-on-disconnect with backoff retry.

#include "ApClient.hpp"

#include <cstdint>
#include <cstring>

#include "nn/nifm.h"
#include "nn/os.h"
#include "nn/socket.hpp"
// nx.h is the C-linkage umbrella for libnx (svc + result + ...). Including
// the inner headers directly from C++ gives C++ mangling and unresolved
// links against the assembly stubs.
#include "lib/nx/nx.h"

#include "ApProtocol.hpp"
#include "ApState.hpp"
#include "../game/CaptureGate.hpp"
#include "../game/MoonApply.hpp"
#include "../util/Log.hpp"

namespace smoap::ap {

namespace {

// BSD socket constants (not exposed by lunakit's nn/socket.hpp).
constexpr int kAfInet      = 2;
constexpr int kSockStream  = 1;
constexpr int kSolSocket   = 0xffff;
constexpr int kSoKeepAlive = 0x0008;

constexpr std::size_t kWorkerStackSize = 64 * 1024;

// Exponential backoff caps (ms): 1s, 2s, 5s, 10s, 30s.
constexpr std::uint32_t kBackoffCapMs = 30 * 1000;

// Stack must be page-aligned; size must be a multiple of page size. nn::os
// CreateThread takes the BASE address + size (svcCreateThread takes top).
alignas(0x1000) std::byte g_worker_stack[kWorkerStackSize];
nn::os::ThreadType g_worker_thread{};

extern "C" void workerEntry(void* arg) {
    static_cast<ApClient*>(arg)->threadMain();
    // Should not return; if we do, just sleep forever.
    while (true) svcSleepThread(INT64_MAX);
}

}  // namespace

ApClient& ApClient::instance() {
    static ApClient s;
    return s;
}

void ApClient::initNetworking() {
    SMOAP_LOG_INFO("[frame] nn::nifm::Initialize");
    const Result nifm_rc = nn::nifm::Initialize();
    if (R_FAILED(nifm_rc)) {
        SMOAP_LOG_ERROR("[frame] nn::nifm::Initialize FAILED rc=0x%x", nifm_rc);
        return;
    }
    SMOAP_LOG_INFO("[frame] SubmitNetworkRequestAndWait");
    nn::nifm::SubmitNetworkRequestAndWait();
    const bool net_up = nn::nifm::IsNetworkAvailable();
    SMOAP_LOG_INFO("[frame] network available: %s", net_up ? "YES" : "NO");

    // nn::socket::Initialize is intentionally NOT called here — SMO already
    // initialized the BSD client during GameSystem::init (Orig). A second
    // Initialize asserts inside nn::socket::detail::InitializeCommon.
    SMOAP_LOG_INFO("[frame] networking ready (sockets owned by SMO)");
}

void ApClient::start(const BridgeTarget& target) {
    target_ = target;
    running_ = true;
    SMOAP_LOG_INFO("ApClient::start target=%s:%u", target.host.c_str(), target.port);

    // Use nn::os::CreateThread (NOT raw svcCreateThread): the worker calls
    // nn::socket::Socket which is an IPC to the bsd: service, and IPC needs
    // per-thread nn-runtime state that only nn::os-managed threads have.
    // Raw svcCreateThread threads NULL-deref inside HipcSimpleClientSession
    // Manager::Allocate -> InternalCriticalSectionImplByHorizon::Enter.
    // Use the no-coreNum overload — nn::os picks the process's default core
    // internally. The 7-arg overload would forward our value to the kernel
    // SVC, which only accepts 0..N (process-allowed cores) or -2 ("default");
    // -1 / IdealCoreDontCare returns InvalidCoreId from svcCreateThread.
    //
    // Priority must be in nn::os range [0, 31] (0 = highest, 16 = default,
    // 31 = lowest). svcCreateThread accepts a wider 0..63 range; nn::os is
    // stricter and aborts InvalidPriority on anything outside [0, 31].
    const Result rc = nn::os::CreateThread(
        &g_worker_thread, &workerEntry, this,
        g_worker_stack, kWorkerStackSize,
        /*priority=*/16);
    if (R_FAILED(rc)) {
        SMOAP_LOG_ERROR("ApClient: nn::os::CreateThread failed (rc=0x%x)", rc);
        running_ = false;
        return;
    }
    nn::os::SetThreadName(&g_worker_thread, "smoap-worker");
    nn::os::StartThread(&g_worker_thread);
}

void ApClient::stop() {
    running_ = false;
    disconnect();
    // We don't join the thread — the module lives for the process lifetime.
}

void ApClient::requestRehello() {
    // Set the atomic; the worker reads it on the next loop iteration and
    // closes-and-reopens. We do NOT call disconnect() here because we're on
    // the frame thread and socket close should be owned by the worker.
    rehello_requested_.store(true, std::memory_order_release);
}

void ApClient::threadMain() {
    SMOAP_LOG_INFO("[worker] thread started, target=%s:%u",
                   target_.host.c_str(), target_.port);
    // nifm Initialize was done on the frame thread inside
    // GameSystemInitHook::Callback because it's an nn-IPC call and our
    // raw-svcCreateThread worker can't make those. Socket bring-up is
    // SMO's; the worker only does socket-level ops (Socket, Connect,
    // Send, Recv, Select) which empirically work on raw threads.
    SMOAP_LOG_INFO("[worker] entering connect loop");

    std::uint32_t backoff_ms = target_.retry_ms;

    while (running_) {
        // Drain any frame-thread re-HELLO request before doing anything else.
        bool expected = true;
        if (rehello_requested_.compare_exchange_strong(expected, false)) {
            SMOAP_LOG_INFO("re-HELLO requested; cycling connection");
            disconnect();
        }

        if (socket_fd_ < 0) {
            ApState::instance().conn.store(ConnState::Connecting);
            if (!connectOnce()) {
                SMOAP_LOG_WARN("connect failed; sleeping %u ms before retry", backoff_ms);
                svcSleepThread(static_cast<s64>(backoff_ms) * 1'000'000);  // ms -> ns
                backoff_ms = backoff_ms < kBackoffCapMs ? backoff_ms * 2 : kBackoffCapMs;
                continue;
            }
            backoff_ms = target_.retry_ms;  // reset on success
            sendHello();
            sendSnapshot();
            ApState::instance().conn.store(ConnState::Hello);
        }

        // Wait up to recv_timeout_ms for inbound data.
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(socket_fd_, &rfds);
        struct timeval tv;
        tv.tv_sec  = static_cast<long>(target_.recv_timeout_ms / 1000);
        tv.tv_usec = static_cast<long>((target_.recv_timeout_ms % 1000) * 1000);
        const int sel = nn::socket::Select(socket_fd_ + 1, &rfds, nullptr, nullptr, &tv);

        if (sel < 0) {
            SMOAP_LOG_WARN("Select returned error; reconnecting");
            disconnect();
            continue;
        }
        if (sel > 0 && FD_ISSET(socket_fd_, &rfds)) {
            std::string line;
            if (!readOneLine(line)) {
                SMOAP_LOG_WARN("recv error or peer closed; reconnecting");
                disconnect();
                continue;
            }
            if (!line.empty()) handleLine(line);
        }

        pumpOnce();
    }

    SMOAP_LOG_INFO("ApClient worker exiting");
    disconnect();
}

bool ApClient::connectOnce() {
    SMOAP_LOG_INFO("[conn] Socket(AF_INET, SOCK_STREAM, 0)");
    socket_fd_ = nn::socket::Socket(kAfInet, kSockStream, 0);
    SMOAP_LOG_INFO("[conn] Socket returned fd=%d", socket_fd_);
    if (socket_fd_ < 0) {
        SMOAP_LOG_WARN("[conn] Socket() failed");
        socket_fd_ = -1;
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = kAfInet;
    addr.sin_port   = nn::socket::InetHtons(target_.port);
    if (nn::socket::InetAton(target_.host.c_str(), &addr.sin_addr) == 0) {
        SMOAP_LOG_WARN("[conn] InetAton failed for %s", target_.host.c_str());
        nn::socket::Close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }
    SMOAP_LOG_INFO("[conn] connecting to %s:%u", target_.host.c_str(), target_.port);

    const Result rc = nn::socket::Connect(socket_fd_,
                                          reinterpret_cast<const sockaddr*>(&addr),
                                          sizeof(addr));
    if (R_FAILED(rc)) {
        SMOAP_LOG_WARN("[conn] Connect FAILED rc=0x%x", rc);
        nn::socket::Close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }

    const int keepalive = 1;
    nn::socket::SetSockOpt(socket_fd_, kSolSocket, kSoKeepAlive,
                           &keepalive, sizeof(keepalive));

    SMOAP_LOG_INFO("[conn] CONNECTED to %s:%u (fd=%d)",
                   target_.host.c_str(), target_.port, socket_fd_);
    return true;
}

void ApClient::disconnect() {
    if (socket_fd_ >= 0) {
        nn::socket::Close(socket_fd_);
        socket_fd_ = -1;
    }
    read_buf_.clear();
    ApState::instance().conn.store(ConnState::Disconnected);
}

void ApClient::sendHello() {
    Hello hello;
    hello.mod_ver = SMO_AP_MOD_VERSION_STRING;
    hello.smo_ver = SMO_VERSION_STRING;
    const std::string line = encodeHello(hello);
    SMOAP_LOG_INFO("[conn] sending HELLO (%zu bytes)", line.size());
    const int sent = nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
    SMOAP_LOG_INFO("[conn] HELLO send returned %d", sent);
}

namespace {

// Per-stage shine accumulator used by sendSnapshot's enumeration callback.
// We bucket shines by stage_name so each kingdom emits one StateChunk message
// (instead of one chunk per shine), keeping wire chatter low and respecting
// the 8 KiB per-line cap.
struct SnapshotBuilder {
    int sock_fd = -1;
    StateChunk current;
    bool current_active = false;

    void flushIfNeeded(const char* stage) {
        if (current_active && current.stage_name != stage) {
            const std::string line = encodeStateChunk(current);
            nn::socket::Send(sock_fd, line.data(), line.size(), 0);
            current = StateChunk{};
            current_active = false;
        }
    }
    void addShine(const char* stage, const char* obj, int uid) {
        if (!stage || !*stage) return;
        flushIfNeeded(stage);
        if (!current_active) {
            current.stage_name = stage;
            current_active = true;
        }
        ShineEntry s;
        if (obj) s.object_id = obj;
        s.shine_uid = uid;
        current.shines.push_back(std::move(s));
    }
    void finalize() {
        if (current_active) {
            const std::string line = encodeStateChunk(current);
            nn::socket::Send(sock_fd, line.data(), line.size(), 0);
            current_active = false;
        }
    }
};

}  // namespace

void ApClient::sendSnapshot() {
    auto& st = ApState::instance();

    // 1) state_begin
    {
        StateBegin b;
        b.mod_ver = SMO_AP_MOD_VERSION_STRING;
        // M4.5 has no save-slot accessor wired up yet; M5/M6 will populate
        // this from GameDataHolder. -1 omits the field on the wire.
        b.save_slot = -1;
        const std::string line = encodeStateBegin(b);
        if (nn::socket::Send(socket_fd_, line.data(), line.size(), 0) < 0) {
            SMOAP_LOG_WARN("[snapshot] state_begin send failed; aborting");
            return;
        }
    }

    // 2) per-stage chunks. M4.5 stub for enumerateOwnedShines emits nothing,
    //    so the only wire output here is when M5/M6 lands the real impl.
    SnapshotBuilder builder{};
    builder.sock_fd = socket_fd_;
    smoap::game::enumerateOwnedShines(
        [](void* ctx, const char* stage, const char* obj, int uid) {
            auto* b = static_cast<SnapshotBuilder*>(ctx);
            b->addShine(stage, obj, uid);
        },
        &builder);
    builder.finalize();

    // 3) _meta chunk: cross-stage state. Always emitted so the bridge sees
    //    the goal flag (and so we have a "snapshot is complete" canary).
    {
        StateChunk meta;
        meta.stage_name = "_meta";
        smoap::game::enumerateOwnedCaptures(
            [](void* ctx, const char* hack) {
                auto* m = static_cast<StateChunk*>(ctx);
                if (hack && *hack) m->captures.emplace_back(hack);
            },
            &meta);
        meta.include_goal_reached = true;
        meta.goal_reached = st.goal_sent;
        const std::string line = encodeStateChunk(meta);
        nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
    }

    // 4) state_end
    {
        const std::string line = encodeStateEnd();
        nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
    }
    SMOAP_LOG_INFO("[conn] snapshot sent");
}

void ApClient::pumpOnce() {
    // Peek-then-pop: a failed Send leaves the entry queued for the next pump
    // cycle. Combined with the snapshot on (re)connect, this means brief
    // disconnects don't lose outbound checks (the deque covers the gap; the
    // snapshot covers anything beyond it).
    auto& st = ApState::instance();
    Check c;
    while (st.outbound_checks.peek(c)) {
        const std::string line = encodeCheck(c);
        SMOAP_LOG_INFO("[pump] peek check kind=%d stage=%s obj=%s (line=%u bytes)",
                       static_cast<int>(c.kind),
                       c.stage_name[0] ? c.stage_name : "<empty>",
                       c.object_id[0] ? c.object_id : "<empty>",
                       static_cast<unsigned>(line.size()));
        const int n = nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
        if (n < 0) {
            SMOAP_LOG_WARN("[pump] check Send returned %d; leaving in queue for retry", n);
            return;
        }
        SMOAP_LOG_INFO("[pump] check Send returned %d (sent %u bytes)", n,
                       static_cast<unsigned>(line.size()));
        st.outbound_checks.popDiscard();
    }
    StatusEvent e;
    while (st.outbound_status.peek(e)) {
        if (e.goal) {
            const std::string line = encodeGoal();
            if (nn::socket::Send(socket_fd_, line.data(), line.size(), 0) < 0) return;
        }
        if (e.death) {
            // The Switch doesn't have a useful wall-clock; the bridge stamps
            // time when it converts the death to an AP Bounce. Send ts_ms=0
            // and let the bridge fill it in.
            Death d{.ts_ms = e.ts_ms};
            const std::string line = encodeDeath(d);
            if (nn::socket::Send(socket_fd_, line.data(), line.size(), 0) < 0) return;
            // Clear the debounce flag so the next death can be reported.
            st.death_pending_send.store(false, std::memory_order_release);
        }
        st.outbound_status.popDiscard();
    }
}

bool ApClient::readOneLine(std::string& out) {
    out.clear();
    char chunk[1024];
    const int n = nn::socket::Recv(socket_fd_, chunk, sizeof(chunk), 0);
    if (n <= 0) return false;
    read_buf_.append(chunk, static_cast<std::size_t>(n));

    const auto nl = read_buf_.find('\n');
    if (nl == std::string::npos) {
        // Cap runaway lines.
        if (read_buf_.size() > kMaxLineBytes) {
            SMOAP_LOG_WARN("read_buf overflow without newline; resyncing");
            read_buf_.clear();
        }
        return true;  // success but no complete line yet
    }
    out.assign(read_buf_, 0, nl);
    read_buf_.erase(0, nl + 1);
    return true;
}

void ApClient::handleLine(const std::string& line) {
    // Reader decodes escapes in place — copy to mutable buffer.
    std::string buf(line);
    DecodedMsg m;
    if (!decode(buf.data(), buf.size(), m)) {
        SMOAP_LOG_WARN("malformed message from bridge: %.*s",
                       static_cast<int>(line.size()), line.data());
        return;
    }
    if (m.t == "hello_ack") {
        ApState::instance().conn.store(ConnState::Ready);
        SMOAP_LOG_INFO("hello_ack: ok=%d seed=%s slot=%s",
                       m.hello_ack.ok ? 1 : 0,
                       m.hello_ack.seed.c_str(),
                       m.hello_ack.slot.c_str());
    } else if (m.t == "checked_replay") {
        for (const auto& ref : m.checked_replay.ids) {
            Check synth{};
            synth.kind = ref.kind;
            copyCheckField(synth.kingdom, ref.kingdom.c_str());
            copyCheckField(synth.shine_id, ref.shine_id.c_str());
            copyCheckField(synth.cap, ref.cap.c_str());
            synth.slot = ref.slot;
            ApState::instance().locations_checked.tryInsert(ApState::hashCheck(synth));
        }
        SMOAP_LOG_INFO("checked_replay: %u entries",
                       static_cast<unsigned>(m.checked_replay.ids.size()));
    } else if (m.t == "item") {
        ApState::instance().inbound.push(m.item);
    } else if (m.t == "ap_state") {
        // UI hint only.
    } else if (m.t == "print") {
        SMOAP_LOG_INFO("[bridge] %s", m.print.text.c_str());
    } else if (m.t == "pong") {
        // Liveness ack — could update last_rx_ns here in a future iteration.
    } else if (m.t == "err") {
        SMOAP_LOG_WARN("bridge err code=%s ctx=%s",
                       m.err.code.c_str(), m.err.ctx.c_str());
    } else if (m.t == "kill") {
        // M4: log only. Actual Mario-kill on inbound DeathLink lands in M6
        // alongside the moon-grant / state-write machinery (we need an
        // accessor for PlayerActorHakoniwa* first).
        SMOAP_LOG_INFO("kill (DeathLink in) source=%s cause=%s",
                       m.kill.source.c_str(), m.kill.cause.c_str());
    } else {
        SMOAP_LOG_WARN("unknown message t=%s", m.t.c_str());
    }
}

}  // namespace smoap::ap
