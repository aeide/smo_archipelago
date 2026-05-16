// TCP client to the bridge.
//
// Owns a single nn::socket TCP connection; runs its own background thread.
// Reads line-delimited JSON, dispatches into ApState. Writes outbound messages
// from ApState rings.
//
// Reconnect policy: exponential backoff (1, 2, 5, 10, 30 cap) seconds.

#pragma once

#include <atomic>
#include <cstdint>
#include <string>

namespace smoap::ap {

struct BridgeTarget {
    std::string host;
    std::uint16_t port = 17777;
    std::uint32_t retry_ms = 3000;
    std::uint32_t recv_timeout_ms = 200;
};

class ApClient {
public:
    static ApClient& instance();

    // Call ONCE from a frame-thread context (GameSystemInit hook callback,
    // after Orig). Does the nifm + nn::socket bring-up that requires an
    // nn-aware thread. start() depends on this having completed.
    void initNetworking();

    void start(const BridgeTarget& target);
    void stop();

    // Frame-thread API: ask the worker to close + reopen its socket so a
    // fresh HELLO triggers the bridge's checked_replay. SaveLoadHook calls
    // this after a save reload clears our session dedupe set.
    void requestRehello();

    // Pump outbound rings into the wire. Called by the socket thread.
    void pumpOnce();

    void threadMain();  // public for the worker entry trampoline

private:
    ApClient() = default;

    bool connectOnce();
    void disconnect();
    void sendHello();
    // M4.5 reconciliation: walks GameDataHolder via game::enumerateOwnedShines
    // / enumerateOwnedCaptures and emits state_begin / N x state_chunk /
    // state_end on the wire. Called from the worker thread right after
    // sendHello on every (re)connect — and transitively on save load via
    // SaveLoadHook -> requestRehello -> reconnect -> sendHello -> sendSnapshot.
    // M4.5 ships with the enumerate functions as no-op stubs (M5/M6 fills
    // them in), so the snapshot currently emits begin + _meta + end only,
    // which the bridge processes as an empty diff (no AP traffic).
    void sendSnapshot();
    // Read from socket into read_buf_. Returns false on socket close/error.
    // Does NOT extract lines — popLine pulls one at a time off read_buf_.
    bool recvIntoBuf();
    // Pop the next complete \n-terminated line from read_buf_ into `out`.
    // Returns false if no complete line is buffered. Decoupling this from
    // recv is critical: when the bridge sends N messages in one TCP push,
    // we must drain ALL of them before going back to Select (which only
    // checks the socket, not the buffer). Pre-split implementation conflated
    // these and silently held messages for indefinite time.
    bool popLine(std::string& out);
    void handleLine(const std::string& line);

    BridgeTarget target_{};
    std::atomic<bool> running_{false};
    std::atomic<bool> rehello_requested_{false};
    int socket_fd_{-1};
    std::string read_buf_;  // accumulator for partial lines
};

}  // namespace smoap::ap
