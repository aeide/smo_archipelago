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

## Sign-off questions for Devon

1. **D3** — accept "reload evicts to last unlocked kingdom" as the v1 rule
   (no current-world write on chain arrival)?
2. **D5** — agree with the v1 overworld exclusions (Moon, Mushroom, Dark,
   Darker, Ruined)? Anything else you'd pull (Bowser's? Lost?) or keep?
3. **D6** — endgame-via-chain: permanently out, or "out for v1, revisit"?
4. **D1** — confirm chains should NOT reduce flight costs (a chain visit
   doesn't discount that kingdom's Odyssey gate)?

On sign-off, P3b (port-graph data model) starts with these as fixed
constraints; the in-game probes in D2/D4 fold into P4's walk matrix.
