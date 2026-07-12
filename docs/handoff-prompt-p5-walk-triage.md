# Handoff prompt — P5 walk triage session (Fable)

Devon: fill every `<<< ... >>>` placeholder with your walk results, then paste the
whole block below the line into a fresh Fable session. Delete this file whenever;
do not commit it with placeholders unfilled.

---

Read CLAUDE.md first. Then read, in order:

1. `docs/plan-p5-cross-world-loads.md` §5 — the 2026-07-09 session record. §5.1 is
   the lever verdict (lever 1 dead → B1 + B2 shipped), §5.2 what shipped and where,
   §5.3 the open items, **§5.4 the walk matrix this session's results follow**.
2. `docs/plan-decoupled-entrances.md` — the "P5 session 2026-07-09 (fifth)" block.
3. Memories: [[p5-cross-world-load-crash-class]], [[p4-chain-return-open-findings]],
   [[p4-topology-no-oo-shipped]].

**Repo state:** branch `complete-entrance-randomizer`, committed through 83f3c3e.
The B1/B2 implementation, the chain-bit poisoning fix, the client reconnect fix,
and all doc updates are UNCOMMITTED in the working tree (see §5.2 for the file
list). **Never stage `switch-mod/sys` or `cap-start.bin`.** Pytest only via
`.venv\Scripts\python -m pytest apworld\smo_archipelago\tests` (1013 passed /
98 skipped at last session end; no apworld/client changes since, so it should be
unchanged). Seed: spoiler `AP_16310405358685788791`, regenerated 07-09 9:41 —
**NO reseed happened or is needed** unless a triage outcome below demands one.
Ryujinx is portable: logs at `E:\Ryubin\Logs`, mods at
`%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`.

**Build state:** subsdk9 built 2026-07-09 10:38 AM, staged to
`switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\`; I copied it to
Ryujinx myself before walking. BRIDGE_HOST 192.168.4.100.

## WALK RESULTS (against the §5.4 matrix)

- **Item 0 — boot install lines** (6× `[p5-prearm] <symbol> @`, both trigger
  lines, `[p5-b1] tryChangeNextStageWithDemoWorldWarp @`):
  all present, logs at boot.txt
- **Item 1 — foreign-interior entry + Swinging Along the High-Rises (Wooded
  "Crowded Elevator" door) — THE B2 RACE VERDICT:**
  immediate crash this time - logs at swinging-crash.txt
- **Item 2 — foreign-overworld exit (8-Bit Chasm Lifts 'Lift2DExit' → Sand):**
  crashed entering 8-bit chasm, log at crash-entering-8bit-chasm.txt. also crashed leaving this subarea in the previous build, i have those logs at subarea-exit-to-sand-crash.txt
- **Item 3 — W3 signal in Sand (finding 11):** globe at 0, bounce behavior,
  then 16 moons deposited → story launch:
  globe was at 0 but i was able to leave because lost kingdom unlocked itself and everything before it - see my additional notes in anything else, specifically notes 3 and 4.
- **Item 4 — retrace/:return backstop:**
  untested - read the spoiler log at E:\smo_archipelago\vendor\Archipelago\output\AP_16310405358685788791_Spoiler.txt and give me a route
- **Item 5 — legit-kingdom regression (chain door into flight-visited kingdom):**
  untested - read the spoiler log at E:\smo_archipelago\vendor\Archipelago\output\AP_16310405358685788791_Spoiler.txt and give me a route
- **Item 6 — PBP-cold class as B1 warp:**
  untested - read the spoiler log at E:\smo_archipelago\vendor\Archipelago\output\AP_16310405358685788791_Spoiler.txt and give me a route
- **B1 UX verdict (mine):** acceptable
- **Lost/Ruined design decision (mine, §5.3):**  lift
  exemption with story guards
- **Anything else:** i have a few additional notes:
note 1: i turned start_at_cap_peace FALSE but exiting cap tower still advanced it to world peace. if this option is flagged to false cap kingdom needs to stay vanilla
note 2: i turned abilitysanity and capturesanity off, but i found a moon with Jizo - need to ensure that when abilitysanity is false, no abilities are shuffled in the pool, and when capturesanity is off, no captures are shuffled into the pool
note 3: i chained in to lost kingdom and there was no odyssey, but then from within lost kingdom i chained to luncheon kingdom and then the odyssey was there, so _some_ odyssey chain logic is working. logs at chain-to-lost-then-luncheon.txt
note 4: continuing in the note 3 log, when i boarded the odyssey to fly back to cap or cascade from luncheon, i was also given sand, wooded, lake, cloud, and lost kingdom as options, but not snow, seaside, or luncheon itself. it seems the "last visited" kingdom is become the latest unlock in this new system, rather than the actual latest unlock. only cap and cascade should be available on this screen as i have never left cascade. hovering over each of the kingdoms past cascade shows a "new" icon in the top left corner, indicating i have never visited it, and attempting to fly to lost did bring me to lost no problem. however, attempting to fly to metro kingdom from lost kingdom FINALLY bounced me back to cascade

Log files: all logs are in E:\Ryubin\Logs and the individual files were mentioned in the notes above

## WORK ORDER

1. **Verify R0 FIRST, always** — deployed
   `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\subsdk9` mtime must be
   ≥ 2026-07-09 10:38 AND postdate every source under `switch-mod/src/`; the item-0
   install lines must be in every log. A stale binary voided a full walk once
   already. If stale, stop triage and say so.
2. **Triage each matrix item against the logs.** Pre-derived decision branches —
   do not re-derive these, but DO verify the logs actually support the branch you
   take:
   - **Item 1 pass** (pre-arm fired, Swinging loads clean) → the P5 crash class is
     CLOSED for interiors. **Item 1 fail with the pre-arm firing** → the stage
     load lost the race to the async world load. The next seam is making
     `HakoniwaSequence::exeLoadStage` wait on
     `WorldResourceLoader::isEndLoadWorldResource()` before advancing — but READ
     THE DECOMP of exeLoadStage's step logic FIRST (raw.githubusercontent.com/
     MonsterDruide1/OdysseyDecomp) before committing to any seam; the CLAUDE.md
     rule about inlined predicates applies with full force here.
   - **Item 2/6 pass but B1 UX rejected** → the fallback is routing overworld
     targets through B2 too (one-line change in `routeRemappedCrossWorld`,
     EntranceShuffleHook.cpp) — but that inherits item 1's race verdict, so only
     valid if item 1 passed.
   - **Item 3: [chain-launch] fired at the refusal** → finding 11's seam is
     confirmed, close it. **Refusal happened silently** → the launch reads
     something else; P5 doc §2.5 lists fallback candidates; decomp read mandatory
     before picking.
   - **Item 5 fail (`allowance ZERO` with unlocked=1)** → bug in
     `OdysseyRescue::isKingdomChainReachedOnly` or its call sites
     (UnlockShineNumHook.cpp / WorldMapSelectHook.cpp); the intended predicate is
     `(session bit || alreadyGo) && !isWorldUnlockedRaw`.
   - **Lost/Ruined per my decision:** (a) accept → doc-only; (b) lift exemption →
     switch-mod change in the chain-arrival normalization with story-state guards
     (Lost's crash-repair sweep + Ruined's pinned Multi-Moon are why the exemption
     exists — the guards must cover both); (c) pool-exclude → apworld change in
     port matching + RESEED, and note the no-O↔O topology invariant
     ([[p4-topology-no-oo-shipped]]) when touching the pool.
3. **Update `docs/plan-p5-cross-world-loads.md` (new §6) +
   `docs/plan-decoupled-entrances.md` (sixth-session block) + the two memories**
   with the verdicts, exactly as prior sessions did.
4. **Then author the NEXT handoff prompt — this is the main deliverable.** Write
   it to `docs/handoff-prompt-p5-execution.md`. It targets an EXECUTION session
   running **Sonnet if every task you assign is mechanical and fully specified
   (exact file, exact function, exact edit, no seam choices left), Opus if any
   task requires decomp navigation, a new hook chokepoint choice, or multi-file
   design judgment**. State your model pick and why at the top of the file. You do
   the thinking in THIS session — the execution prompt must contain zero open
   design questions. Requirements for that prompt:
   - Self-contained: the executor may have none of this context. Open with "Read
     CLAUDE.md first" and list the specific doc sections + memories to read.
   - Per task: file path, function, the decided approach, the reason it was
     decided (one line, with a doc pointer), and the verification step
     (log line to expect / test to run / symbol check via
     `scripts/check_nso_symbols.py .romfs-cache/main.nso <mangled>`).
   - Carry the standing constraints verbatim: never stage `switch-mod/sys` or
     `cap-start.bin`; never commit Nintendo IP (CLAUDE.md list); pytest via
     `.venv\Scripts\python -m pytest apworld\smo_archipelago\tests`; symbol
     constants go in HookSymbols.hpp (sail DB only for installAtSym targets);
     Devon builds and walks — the executor edits, runs pytest where applicable,
     and updates docs/memories, nothing more.
   - If triage closed everything with no code work left, say so instead of
     inventing tasks, and make the execution prompt a commit-preparation order
     (what to commit, in what logical groups, what must never be staged).

Implement nothing in this session beyond doc/memory updates — the thinking and
the execution prompt ARE the deliverable.
