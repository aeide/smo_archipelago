Resume prompt — SMO Archipelago P4, picking up 2026-06-15 (cont. 5)

Two open follow-ups from last session. All P4 code is uncommitted; I build+test on Windows. Context lives in docs/plan-p4-detail.md (2026-06-15 cont. 5 entry + the "NEXT-SESSION HANDOFF — Ledge Grab debugging plan" block) and the CLAUDE.md P4 status line.

1. Abilities still not showing in the SMO Client — confirmed NOT a code bug. The new "Abilities owned" section + client/abilities.py move-name mapping are done and unit-tested (21 pass in test_ability_wire.py), and the in-game move-name unlock bubble works ✅. The reason the GUI list is empty: the client runs from the installed zip vendor/Archipelago/custom_worlds/meatballs.apworld (mtime 2026-06-14), which predates the 2026-06-15 client edits. First thing: walk me through running python scripts/install_apworld.py, then I relaunch the SMO Client and confirm owned abilities appear as moves (e.g. "Crouch, Roll, Roll Boost"). If they still don't show after the zip rebuild + relaunch, debug from there.

2. Ledge Grab gate still fails in-game. The judge-hook approach (grabCeilJudgeHook on _ZNK19PlayerJudgeGrabCeil5judgeEv, gated Ledge Grab>=1, decoupled from Wall Slide) did NOT work — twice now. Before writing more code, have me gather diagnostics: with Wall Slide owned but Ledge Grab NOT owned, attempt a ledge grab and report whether AbilityGate: suppressed Ledge Grab (log slot 8) appears in the Odyssey-tab log.

If it fires but Mario still grabs → judge isn't the chokepoint; pivot to the state-eject fallback.
If it never fires → the judge isn't on the grab path (inlined/different judge); pivot to state-eject.
Fallback plan: hook PlayerStateGrabCeil::appear (_ZN19PlayerStateGrabCeil6appearEv, already verified HIT) and defer a grab-cancel from the frame pump, modeled on tickPendingUncapture in CaptureStartHook.cpp. Verify any new symbol with python scripts\check_nso_symbols.py .romfs-cache\main <sym> before installAtSym.
Don't start the other hard abilities (Progressive Jump, Side Flip, Cap Bounce, Ground Pound Jump, Up/Down Throw) until these two are resolved.