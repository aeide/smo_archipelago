# Design — decoupled entrances × kingdom order (P3a)

**Status: SIGNED OFF by Devon 2026-07-07** (D3 accept-eviction, D5 modified —
Ruined + Mushroom IN, D6 permanently out, D1 no-discount). Constraints below
are FIXED for P3b–3e.
Inputs: [devon-p0-decoupled-spike-results.md](devon-p0-decoupled-spike-results.md)
(empirical), `switch-mod/src/game/KingdomOrderGate.cpp` (current order machinery),
[plan-decoupled-entrances.md](plan-decoupled-entrances.md) (phase plan),
[v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md](v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md)
(original risk analysis).

## The collision is smaller than the feasibility doc feared

The 2026-06-20 feasibility write-up treated "the kingdom-order gate" as a hard
wall that decoupled chains would smash into. **That wall has since been mostly
dismantled by the free-detour work:** `KingdomOrderGate.cpp`'s strict fork-order
rule table is now EMPTY (sentinel only — both historical Lake/Wooded and
Snow/Seaside entries are gone), so the BACKSTOP on
`tryChangeNextStageWithDemoWorldWarp` is inert. What actually enforces
progression today:

1. **The moon-deposit economy** — the Odyssey's per-kingdom leave costs
   (vanilla or `randomize_kingdom_gates`-rolled, via `UnlockShineNumHook`).
2. **The two detour exit gates** (`processDetourExitGate`) — both siblings'
   thresholds before the flight onward to Cloud / Luncheon.
3. **The logic mirror** — `regions.json`'s `{KingdomMoons(...)}` chain.

None of these is an *order* table; they're an *economy*. That reframes P3a from
"relax or disable the order gate" to: **model chains as a second access channel
alongside the flight economy, which stays untouched.**

---

## D1 — Two-channel access model (the core decision)

A kingdom overworld is reachable via EITHER:

- **Flight** (the existing channel): the `regions.json` chain with
  `{KingdomMoons}` gates — semantics, totals, and rolled-gate behavior all
  unchanged.
- **Chain** (the new channel): a port-graph path from the start kingdom
  through matched ports, each edge carrying its forward/reverse rules
  (P3b's job).

Logic-side this is additive: kingdom regions gain chain entrances alongside
their flight entrance; a region is reachable when ANY entrance rule passes.
Chain access neither satisfies nor consumes flight gates — flying out of a
kingdom still costs the same moons even if you first visited its neighbor
on foot.

**Rationale:** Devon's goal is widening early options, not deleting the moon
economy. Keeping flight untouched means `randomize_kingdom_gates`, the
`kingdom_gates` wire msg, `UnlockShineNumHook`, and the sum-preserved totals
need ZERO changes under this mode.

### D1 erratum — the "keep flight untouched" implementation discounted the economy (fixed 2026-07-12)

The *intent* above ("chain access neither satisfies nor consumes flight gates")
is right, but the two-channel *implementation* violated it. Under the Manual
egress quirk ([handoff-region-gating-egress.md](handoff-region-gating-egress.md))
each `regions.json` flight edge K → J carries only K's OWN single-hop
`{KingdomMoons}` gate; the cumulative economy emerges solely from `reach()`
having to traverse the whole chain. The chain channel's free
"K Arrival → K" presence edge lets on-foot arrival grant the K region directly,
so `reach()` stops accumulating the flight chain — and `reach(Moon Kingdom)`
collapsed from the full ~124-moon cost to ~one kingdom's gate. Decoupled seeds
generated with ~8-sphere playthroughs and ~200 stranded progression items;
worse, they were physically unwinnable (logic promised a Bowser's → Moon flight
the player could never perform without having flown TO Bowser's, per D3).

**Fix (`hooks/World.py::_apply_decoupled_flight_economy`, decoupled-only):** after
the core `set_rules` clobber, `add_rule` (AND) a recursive `flight_reach(K)`
predicate — "could have FLOWN to K", computed over `regions.json` `connects_to`
as an OR-over-parents recursion, exempting Pokino and all "K Arrival"
destinations — onto every inter-kingdom flight edge. The core single-hop rule
survives as a conjunct; chain arrival can still WIDEN where you stand and which
overworld checks open, but a chain-reached K can no longer open K's onward FLIGHT
edge unless the whole gate chain up to K is genuinely satisfied. `reach(Moon)` is
restored to the full 124 (or the rolled sum-preserved total). Full audit +
plan: [handoff-decoupled-flight-economy-fix.md](handoff-decoupled-flight-economy-fix.md).

## D2 — Switch-side order machinery: no changes

- Strict-order table: already empty; stays empty. Nothing to relax.
- **Detour exit gates stay active.** They key on `cur` being a sibling
  HomeStage and gate only the *flight* commit; a chain landing in
  Cloud/Luncheon arrives from a subarea stage → the gate no-ops (P0 confirmed
  this null-origin behavior). A chain bypassing the detour thresholds is the
  *point* of the mode, not a leak.
- **Cascade Odyssey divert + first-arrival forcing:** unchanged — both are
  scoped to Cascade-home/cabin transitions. One validation item: chain-arrival
  into Cascade pre-Broode keeps the live scenario (the Broode force fires only
  on cabin-origin commits) — confirm Broode + her MM still spawn correctly for
  a chain-first visit.

## D3 — Save/reload rule: "the Odyssey is home" (accept eviction)

P0 confirmed: save+quit+reload in a chain-reached kingdom reloads Mario into
his last *officially-unlocked* kingdom. **Decision: this is the intended v1
rule, not a bug.** Chains are excursions; persistence of "current world"
belongs to the flight channel.

- **Why not write the unlock/current-world bit on chain arrival:** the
  MoonRockHook investigation established that scenario numbers are recomputed
  from quest state at every load — mutating world-unlock state for a kingdom
  whose story hasn't started is exactly the class of write that produced
  mid-story scenario corruption before. High risk, low reward; defer to the
  approach-B fidelity pass if ever.
- **Free consequence:** reload becomes the universal escape hatch. A player
  who chains into somewhere they can't traverse out of is never hard-stuck —
  save+reload returns home. Logic must still never *require* reload (P3b/c's
  per-direction rules handle real reachability), but this bounds the worst
  case of any logic bug to an annoyance instead of a softlock.
- Client/tracker: `reportArrival` already reveals chain-reached kingdoms and
  their rolled exit gates (P0 confirmed). Keep — it's correct under the
  two-channel model.

## D4 — Peace/scenario composition: channel-agnostic (no special casing)

P0 confirmed a chain-reached kingdom loads in its true current story scenario
(pre-peace layout for an untouched kingdom, live scenario otherwise). So the
existing peace-gate model is already correct under chains: `{XPeace()}` =
canReachLocation(story anchor), which is satisfied by *playing that kingdom's
story*, however Mario got there. No per-channel scenario logic needed.

**The load-bearing assumption to validate in-game (first probe of P4):**
story quests are completable on foot in a chain-reached kingdom — boss
spawns, multi-moon payout, scenario advance — with no hidden dependency on
the Odyssey being parked. Probe: chain into Sand pre-story, run the Broodal
fight, confirm scenario advances and nothing warps Mario to a nonexistent
ship. Any story event that *does* assume the ship is a candidate for that
kingdom's overworld exclusion (D5) rather than new mechanism.

## D5 — Overworld pool: curated subset (Devon-modified 2026-07-07)

Excluded from the door-mouth pool in v1: **Moon, Dark Side, Darker Side
only.** Moon's overworld hosts the endgame sequence (wedding → credits →
goal); Dark/Darker are post-game and Moon-coupled ("leave Moon = win").

**Ruined and Mushroom are IN** (Devon's call, overriding the draft):

- **Mushroom — data verified present and correct (2026-07-07):**
  entrance_stages.json v2 carries its subareas with door_mouths on
  `PeachWorldHomeStage` (shop, Picture Match `Fukuwarai2`, `PeachCastleGate`,
  8-bit rooms, Yoshi clouds, boss re-fight arenas…); `subareas.json` has
  `location_names` back-filled for every Mushroom subarea; all its moons are
  matched AP locations. Goal integrity is automatic: every Mushroom check is
  `junk_only: true`, so nothing progression-bearing can ever land there —
  chain-reaching Mushroom early opens junk checks only. Their `requires` are
  `""` (unauthored — harmless for junk under minimal accessibility; note if
  they're ever promoted). **Precedent that pre-clear on-foot Mushroom is a
  known-good game state: vanilla itself does it** — the hidden Luncheon
  painting warps Mario to PeachWorld pre-game-clear (the same mechanic that
  forced the credits-hook goal-detection redesign). The `CreditsStartHook`
  goal producer fires only on StaffRollScene init, so a chain arrival can
  never false-fire the goal — already proven by that painting case.
- **Ruined:** its overworld (`BossRaidWorldHomeStage`) has two subarea
  door-mouths (Roulette Tower, Mummy Army), both extracted with port_ids.
  The "no backtracking" property is about the Lord-of-Lightning boss not
  respawning (why its MM stays pinned) — unchanged and orthogonal; a chain
  arrival in the Ruined overworld can always leave through its matched
  door-mouths or reload-evict (D3).

Subarea ports from ALL kingdoms (including Moon/Dark/Darker) stay in the
pool — the exclusion is overworld door-mouths only.

**Erratum (P3b, 2026-07-07):** the paragraph above is wrong as written —
exclusion must propagate DOOR-WISE. If an excluded overworld mouth stayed
vanilla while its door's interior mouth were rematched, the player would see
an asymmetric door (walk in vanilla, walk back → somewhere else). Since
Moon/Dark/Darker subareas' only doors hang off excluded overworlds, those
subareas drop from the decoupled matching entirely; their checks stay
flight-reachable exactly as today. Implemented in `port_graph.py`
(`build_port_graph`), guarded by `test_excluded_kingdoms_have_no_mouths`.

**Festival-goal note:** under `goal: festival`, post-Metro regions are
emptied (`FESTIVAL_REGIONS_TO_EMPTY`); their overworld door-mouths must also
drop out of the pool under that goal (landing there would open zero checks
and confuse tracking).

## D6 — Goal-chain integrity: endgame-via-chain PERMANENTLY out

Devon's decision: not "v1-only" — Moon door-mouths never enter the pool.
The victory location stays reachable only through the flight chain
(`{KingdomMoons(Bowser's,8)}` etc.): the goal can never be logic-satisfied by
a chain and the moon economy stays the spine of every seed. No `requires`
changes needed. Any future proposal to admit Moon door-mouths is a design
regression against this decision, not an open question.

## D7 — Option surface

`entrance_shuffle: decoupled` implies everything above; **no new toggles in
v1.** (Candidate future sub-option, deliberately deferred: subarea-chains-only
vs. overworlds-in-pool. Adding it now doubles the test matrix before the mode
exists.)

## D8 — Interaction with capturesanity/abilitysanity

Chain-edge reverse rules lean heavily on ability/capture tokens (reach-the-exit
interior requirements). Two prerequisites before P3b lands:

- The **abilitysanity precollect fix**
  ([handoff-abilitysanity-precollect-fix.md](handoff-abilitysanity-precollect-fix.md))
  must be merged — decoupled logic multiplies the ability-token dependence
  that made abilitysanity=off unsatisfiable.
- P3c's generation probe matrix must include the off-combinations
  (abilitysanity/capturesanity off × decoupled) so the fix's guarantee holds
  under the new graph.

## D9 — Mushroom check promotion under decoupled (Devon, 2026-07-07)

Since decoupled chains make Mushroom reachable at virtually any time, its 43
checks are PROMOTED from junk-only to full checks **iff
`entrance_shuffle == decoupled`**:

- **Mechanism:** `locations.json` keeps `junk_only: true` (static data);
  `_apply_junk_only_rules` (`hooks/World.py`) exempts Mushroom-Kingdom-category
  locations when the mode is decoupled. Off/simple behavior stays
  byte-identical. Dark/Darker junk_only checks are NOT exempted (their
  overworlds are excluded, D5).
- **Requires:** all 43 Mushroom locations have back-filled records in
  `moon_requirements.json` (verified 1:1, 2026-07-07 — sourced from Devon's
  `SMO Requirements.xlsx` via the import pipeline). Devon re-runs
  `compile_moon_logic.py` on the romfs machine (NEVER without
  shine_map/world_scenarios present — see CLAUDE.md) to fill their
  `requires:""`. Compiled requires ship unconditionally: under off/simple the
  checks are post-goal junk where a movement gate is also correct. No
  shine_table resync needed (names don't change).
- **⚠ The in-game unknown (probe before relying on it):** the vanilla
  painting-warp precedent proves pre-clear Mushroom LOADS safely, but in
  vanilla that scenario has NO moons placed — Mushroom moons spawn in the
  post-clear scenario. P4's walk matrix must probe whether moons/NPCs spawn
  in a chain-reached pre-clear Mushroom. If not, the contingency is the
  established scenario-floor pattern (`capArrivalScenarioOverride` /
  CapReturnScenarioHook): floor commits into `PeachWorldHomeStage` to the
  post-clear placement scenario, never lowering a higher one. Mushroom has no
  story to corrupt, so this is the low-risk variant of the pattern — but it
  is a switch-mod change and stays OUT of scope until the probe demands it.
- **Goal integrity unaffected:** the victory location lives in Moon Kingdom
  (D6); Mushroom holding progression under decoupled is exactly the intended
  widening of the fill surface.

## D10 — Mushroom arrival route: exit-portals, guaranteed at roll time (Devon, 2026-07-17)

Spun out of the evidence-seed investigation
([handoff-decoupled-mushroom-overworld-reachability.md](handoff-decoupled-mushroom-overworld-reachability.md),
seed 91455467025183402260). Devon's rulings, in an AskUserQuestion round:

- **Mechanism: exit-portals ARE the MK route** (over tower post-boss return and
  a game-clear gate). Every matched pair is a two-way portal — walking into
  either mouth lands at the other mouth's marker (`compile_port_remaps`
  semantics, applied in-game by the P2 compound exit key; Devon: "they can all
  chain", confirmed by his moonpipe → red flower room → Sand shop chain). A
  pair (MK door ↔ interior exit mouth) therefore delivers Mario INTO the MK
  overworld when the interior is exited through that mouth.
- **Early MK moons are fine**: once the route is real, MK overworld checks in
  early spheres are the mode's intended chain widening (same as any kingdom).
  Victory is untouched — it lives in Moon Kingdom (D6) behind the D1-erratum
  flight economy.
- **The roll must GUARANTEE the route.** Two connectivity-model errata in
  `port_matching.py` (both 2026-07-17):
  1. **Mushroom erratum** — kingdom HomeStages rooted the connectivity model
     "because every kingdom is flight-reachable", which is false for
     post-game Mushroom. `NON_ROOT_KINGDOMS` stages are no longer roots: the
     roller must wire ≥1 MK door to rooted territory, and a matching whose MK
     cluster is only self-rooted (every MK door on a sole-mouth dead-end
     partner) fails the checker.
  2. **Directed erratum** — the undirected stage-connectivity model could not
     see full-interior deadlocks (two subareas' only entry-capable mouths
     paired with each other — seen live in probe seeds) or the far-side
     one-way rule. Phase 1 now grows a DIRECTED frontier over the
     `_directed_model` nodes (full/far per subarea, per-NON_ROOT-kingdom
     overworld, rooted territory), so every subarea's FULL interior and the
     MK overworld get a monotone reachability certificate at roll time;
     `directed_full_interior_strands` re-validates every roll (retry backstop).
- **Sphere-1 in the evidence seed was NOT a false-reachability bug**: logic
  faithfully mirrored the portal pairs; the seed's routes ran through
  Wintery Flower Road / Push Block Peril exits into MK doors. The failures
  were legibility (the spoiler read as one-directional — now carries a
  two-way legend) and the unvalidated in-game landing (D9's pre-clear
  moon-spawn probe, still owed a walk).

## Sign-off record (Devon, 2026-07-07)

1. **D3** — ACCEPTED: reload evicts to last unlocked kingdom; no
   current-world write on chain arrival.
2. **D5** — MODIFIED then accepted: exclude Moon/Dark/Darker only; Ruined
   and Mushroom stay in the pool. Mushroom data verified (see D5).
3. **D6** — PERMANENTLY OUT: endgame-via-chain is closed, not deferred.
4. **D1** — CONFIRMED: chains never discount flight costs.
5. **D9** — ADDED at Devon's request: Mushroom checks promoted from
   junk-only iff decoupled; requires compiled from SMO Requirements.xlsx
   data; pre-clear moon-spawn probe added to P4.

These are fixed constraints for P3b–3e. The in-game probes in D2/D4/D9 fold
into P4's walk matrix.
