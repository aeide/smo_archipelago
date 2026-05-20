// M6 phase D — moon deposit detection.
//
// Two hooks together cover all paths Mario can spend moons through:
//   - AddPayShineHook:    per-toss debit (the common case)
//   - AddPayShineAllHook: "pay current kingdom in full" (less common — kingdom
//                         clear celebrations and similar bulk-payment events)
//
// Both queue a PaySnapshot (per-kingdom PayShineNum reading from the live
// GameDataHolder) into ApState's pending_pay_snapshots ring for the worker
// thread to ship to the bridge. The bridge derives outstanding from
// (lifetime_received_AP − PayShineNum). See AddPayShineHook.cpp for details.

#pragma once

namespace smoap::hooks {

void installAddPayShineHook();
void installAddPayShineAllHook();

}  // namespace smoap::hooks
