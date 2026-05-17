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
            if (!recvIntoBuf()) {
                SMOAP_LOG_WARN("recv error or peer closed; reconnecting");
                disconnect();
                continue;
            }
        }

        // Drain ALL complete lines from read_buf_ each iteration. When the
        // bridge sends N messages in a single TCP push (e.g. hello_ack +
        // checked_replay + ap_state at handshake time, or a kill arriving
        // right after a queued item), Select only fires once on the socket;
        // we must walk the buffer to completion or the trailing messages
        // wait indefinitely for the next socket event before being parsed.
        // Also drains leftover lines on iterations where Select timed out.
        char line_buf[kInboundLineCap];
        std::size_t line_len = 0;
        while (popLine(line_buf, line_len)) {
            handleLine(line_buf, line_len);
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
    read_buf_len_ = 0;
    ApState::instance().conn.store(ConnState::Disconnected);
}

void ApClient::sendHello() {
    Hello hello;
    hello.mod_ver = SMO_AP_MOD_VERSION_STRING;
    hello.smo_ver = SMO_VERSION_STRING;
    smoap::util::json::LineBuffer line;
    encodeHello(line, hello);
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
    smoap::util::json::LineBuffer line;  // reused across chunks

    void flushIfNeeded(const char* stage) {
        if (current_active && current.stage_name != stage) {
            encodeStateChunk(line, current);
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
            encodeStateChunk(line, current);
            nn::socket::Send(sock_fd, line.data(), line.size(), 0);
            current_active = false;
        }
    }
};

}  // namespace

void ApClient::sendSnapshot() {
    auto& st = ApState::instance();
    smoap::util::json::LineBuffer line;  // reused across all snapshot messages

    // 1) state_begin
    {
        StateBegin b;
        b.mod_ver = SMO_AP_MOD_VERSION_STRING;
        // M4.5 has no save-slot accessor wired up yet; M5/M6 will populate
        // this from GameDataHolder. -1 omits the field on the wire.
        b.save_slot = -1;
        encodeStateBegin(line, b);
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
        encodeStateChunk(line, meta);
        nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
    }

    // 4) state_end
    encodeStateEnd(line);
    nn::socket::Send(socket_fd_, line.data(), line.size(), 0);
    SMOAP_LOG_INFO("[conn] snapshot sent");
}

void ApClient::pumpOnce() {
    // Peek-then-pop: a failed Send leaves the entry queued for the next pump
    // cycle. Combined with the snapshot on (re)connect, this means brief
    // disconnects don't lose outbound checks (the deque covers the gap; the
    // snapshot covers anything beyond it).
    auto& st = ApState::instance();
    smoap::util::json::LineBuffer line;  // reused across loop iterations
    Check c;
    while (st.outbound_checks.peek(c)) {
        encodeCheck(line, c);
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
            encodeGoal(line);
            if (nn::socket::Send(socket_fd_, line.data(), line.size(), 0) < 0) return;
        }
        if (e.death) {
            // The Switch doesn't have a useful wall-clock; the bridge stamps
            // time when it converts the death to an AP Bounce. Send ts_ms=0
            // and let the bridge fill it in.
            Death d{.ts_ms = e.ts_ms};
            encodeDeath(line, d);
            if (nn::socket::Send(socket_fd_, line.data(), line.size(), 0) < 0) return;
            // Clear the debounce flag so the next death can be reported.
            st.death_pending_send.store(false, std::memory_order_release);
        }
        st.outbound_status.popDiscard();
    }
}

bool ApClient::recvIntoBuf() {
    // Cap incoming read at the headroom remaining in read_buf_. If we already
    // hold a partial unterminated line that fills the buffer, the next call
    // to popLine will see the overflow and reset.
    const std::size_t avail = kInboundLineCap - read_buf_len_;
    if (avail == 0) {
        // No headroom — popLine's overflow guard will reset us next call.
        // Recv into a small throwaway buffer so we don't stall the socket.
        char drain[256];
        nn::socket::Recv(socket_fd_, drain, sizeof(drain), 0);
        return true;
    }
    const std::size_t cap = avail < 1024 ? avail : 1024;
    const int n = nn::socket::Recv(socket_fd_, read_buf_ + read_buf_len_,
                                   cap, 0);
    if (n <= 0) return false;
    read_buf_len_ += static_cast<std::size_t>(n);
    return true;
}

bool ApClient::popLine(char* out, std::size_t& out_len) {
    // Find first '\n' in [0, read_buf_len_).
    std::size_t nl = read_buf_len_;
    for (std::size_t i = 0; i < read_buf_len_; ++i) {
        if (read_buf_[i] == '\n') { nl = i; break; }
    }
    if (nl == read_buf_len_) {
        // Cap runaway lines so a malformed peer can't grow the buffer forever.
        if (read_buf_len_ >= kInboundLineCap) {
            SMOAP_LOG_WARN("read_buf overflow without newline; resyncing");
            read_buf_len_ = 0;
        }
        return false;
    }
    // Copy line bytes to caller. Bounded by kInboundLineCap on both sides.
    for (std::size_t i = 0; i < nl; ++i) out[i] = read_buf_[i];
    out_len = nl;
    // Shift any remaining bytes left over the consumed line + '\n'.
    const std::size_t consumed = nl + 1;
    const std::size_t remaining = read_buf_len_ - consumed;
    for (std::size_t i = 0; i < remaining; ++i) {
        read_buf_[i] = read_buf_[consumed + i];
    }
    read_buf_len_ = remaining;
    return true;
}

void ApClient::handleLine(char* line, std::size_t line_len) {
    // Reader decodes escapes in place — caller's buffer is already mutable.
    //
    // DecodedMsg holds large fixed-size buffers (notably CheckedReplay::ids,
    // 128 × sizeof(ItemRef) ≈ 65 KiB). Stack-allocating it from handleLine
    // would blow the worker thread's 64 KiB stack. As a function-local
    // static it lives in BSS — single instance reused across calls. Safe
    // because handleLine is only ever called from the worker thread, and we
    // dispatch on m.t so stale variant fields from a previous call are
    // never read (each `decode` writes whichever variant matches its `t`).
    static DecodedMsg m;
    if (!decode(line, line_len, m)) {
        SMOAP_LOG_WARN("malformed message from bridge: %.*s",
                       static_cast<int>(line_len), line);
        return;
    }
    // Tiny strcmp wrapper — m.t is char[] now, not std::string.
    auto eq = [](const char* a, const char* b) {
        while (*a && *b && *a == *b) { ++a; ++b; }
        return *a == '\0' && *b == '\0';
    };
    if (eq(m.t, "hello_ack")) {
        auto& st = ApState::instance();
        // Publish local_slot + deathlink_enabled BEFORE the conn.store(Ready)
        // release. The frame thread observes conn == Ready first (acquire),
        // then reads local_slot — no separate fence needed. Toast filter
        // compares item.from against local_slot to skip self-grants.
        // M6.1: HelloAck::slot is now a fixed char[] (not std::string) —
        // no .c_str() needed. snprintf still safest for length-bounded copy.
        std::snprintf(st.local_slot, sizeof(st.local_slot),
                      "%s", m.hello_ack.slot);
        st.deathlink_enabled.store(m.hello_ack.deathlink_enabled, std::memory_order_relaxed);
        st.conn.store(ConnState::Ready, std::memory_order_release);
        SMOAP_LOG_INFO("hello_ack: ok=%d seed=%s slot=%s deathlink_enabled=%d",
                       m.hello_ack.ok ? 1 : 0,
                       m.hello_ack.seed,
                       m.hello_ack.slot,
                       m.hello_ack.deathlink_enabled ? 1 : 0);
    } else if (eq(m.t, "checked_replay")) {
        for (std::size_t i = 0; i < m.checked_replay.id_count; ++i) {
            const auto& ref = m.checked_replay.ids[i];
            Check synth{};
            synth.kind = ref.kind;
            copyCheckField(synth.kingdom, ref.kingdom);
            // ref.shine_id is char[kMediumFieldCap=128]; copyCheckField truncates
            // to kCheckFieldCap=64. Shine ids historically fit in 64 (see Check's
            // existing kCheckFieldCap shine_id field) so this is consistent.
            copyCheckField(synth.shine_id, ref.shine_id);
            copyCheckField(synth.cap, ref.cap);
            ApState::instance().locations_checked.tryInsert(ApState::hashCheck(synth));
        }
        if (m.checked_replay.truncated) {
            SMOAP_LOG_WARN("checked_replay: TRUNCATED at %u entries — bridge "
                           "sent more than CheckedReplay::kMaxIds; bump that "
                           "cap if this becomes routine",
                           static_cast<unsigned>(m.checked_replay.id_count));
        } else {
            SMOAP_LOG_INFO("checked_replay: %u entries",
                           static_cast<unsigned>(m.checked_replay.id_count));
        }
    } else if (eq(m.t, "item")) {
        ApState::instance().inbound.push(m.item);
    } else if (eq(m.t, "ap_state")) {
        // UI hint only.
    } else if (eq(m.t, "print")) {
        SMOAP_LOG_INFO("[bridge] %s", m.print.text);
    } else if (eq(m.t, "pong")) {
        // Liveness ack — could update last_rx_ns here in a future iteration.
    } else if (eq(m.t, "err")) {
        SMOAP_LOG_WARN("bridge err code=%s ctx=%s", m.err.code, m.err.ctx);
    } else if (eq(m.t, "kill")) {
        // Inbound DeathLink. Collapse to a single pending-bit; multiple
        // bounces between frames overwrite each other (producer-side debounce).
        // The frame thread's maybeApplyInboundKill handles the
        // "Mario already dying" / "too soon since last kill" / "deathlink
        // disabled in hello_ack" / "no cached PlayerHitPointData yet" gates.
        SMOAP_LOG_INFO("[deathlink in] queued source=%s cause=%s",
                       m.kill.source, m.kill.cause);
        ApState::instance().inbound_kill_pending.store(true, std::memory_order_release);
    } else if (eq(m.t, "moon_label")) {
        // M6 phase A.5 — Channel A. Publish the label for the upcoming
        // cutscene to consume. Deadline = now + valid_for_ms; the frame
        // thread drops anything past deadline.
        const auto now = ApState::nowMs();
        const auto deadline = (m.moon_label.valid_for_ms > 0)
            ? now + m.moon_label.valid_for_ms
            : 0;  // 0 = never expire (use sparingly; bridge default is 4000)
        SMOAP_LOG_INFO("[moon_label] seq=%d text='%s' valid_for=%dms",
                       m.moon_label.seq,
                       m.moon_label.text,  // char[] decays to const char*
                       m.moon_label.valid_for_ms);
        ApState::instance().setPendingMoonLabel(
            m.moon_label.text, m.moon_label.seq, deadline);
    } else if (eq(m.t, "shine_scouts")) {
        // AP-classification moon color. Bridge sends one or more chunks of
        // (shine_uid -> palette) after AP LocationInfo lands, and a full
        // replay on every HELLO. Push each into the SPSC ring; the frame
        // thread folds them into ApState::shine_palette in applyOnFrame.
        // Ring is sized 4096 — well above the seed's ~565 moons — so a full
        // replay in one HELLO won't backpressure.
        auto& ring = ApState::instance().inbound_scouts;
        std::size_t pushed = 0, dropped = 0;
        for (std::size_t i = 0; i < m.shine_scouts.entry_count; ++i) {
            if (ring.push(m.shine_scouts.entries[i])) {
                ++pushed;
            } else {
                ++dropped;
            }
        }
        if (m.shine_scouts.truncated) {
            SMOAP_LOG_WARN("[shine-color] shine_scouts chunk truncated at %zu entries; "
                           "bridge sent more than ShineScouts::kMaxEntries — bump cap",
                           m.shine_scouts.entry_count);
        }
        SMOAP_LOG_INFO("[shine-color] enqueued %zu palette entries (dropped %zu)",
                       pushed, dropped);
    } else {
        SMOAP_LOG_WARN("unknown message t=%s", m.t);
    }
}

}  // namespace smoap::ap
