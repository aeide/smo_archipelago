# Handoff: SMO Client tab rework — tracker + AP log merged, Odyssey = logs only

**Recommended model: Sonnet 5.** Self-contained Python/Kivy refactor with fast local
iteration and existing test patterns. The only hard part is kvui archaeology (reading
`vendor/Archipelago/kvui.py` to see how `logging_pairs` tabs are built), which is
reading-comprehension, not deep reasoning. Opus would be overkill.

## Goal (Devon's preference order)

1. **Preferred:** Move the Odyssey tab's LEFT panel (the tracker: moons-by-kingdom
   table, captures unlocked, abilities owned, DeathLink) INTO the "Archipelago" tab,
   so Archipelago = tracker on one side + the existing AP log ("most recent finds")
   on the other. The Odyssey tab then shows ONLY the SMO Client log (the current
   right half, `UILog(logging.getLogger("SMO"))`) — consider renaming its purpose in
   the module docstring.
2. **Fallback** (only if re-parenting the built-in Archipelago tab content proves
   infeasible/fragile): add a new tab "Tracker" that clones the current Odyssey
   split, but its right half shows the Archipelago-tab content (the "Client" logger
   UILog) instead of the SMO log. Odyssey stays as-is.

## What's already known (read 2026-07-17)

`apworld/smo_archipelago/client/gui.py`:
- Tracker left panel = `_format_odyssey(ctx)` rendered into a `_LiveLabel` inside a
  `ScrollView`, refreshed every 1.5 s by `_refresh_panels` (Clock interval).
- Right panel = `UILog(logging.getLogger("SMO"))`. Both halves live in
  `odyssey_split`, added via `self.add_client_tab("Odyssey", odyssey_split)` in
  `SmoManager.build()` after `super().build()`.
- The "Archipelago" tab is NOT built by us — it comes from
  `SmoManager.logging_pairs = [("Client", "Archipelago")]`, consumed by the base
  `GameManager.build()` in `vendor/Archipelago/kvui.py`.

## First step

Read `vendor/Archipelago/kvui.py` (`GameManager.build`, `add_client_tab`, how
`logging_pairs` tabs/panels are constructed and stored). Decide between:
- (a) after `super().build()`, locate the Archipelago tab's content widget,
  detach it, and re-parent it into a horizontal BoxLayout with the tracker
  ScrollView (mirror the existing `odyssey_split` construction); or
- (b) drop `("Client", "Archipelago")` from `logging_pairs` and build the merged
  tab ourselves with our own `UILog(logging.getLogger("Client"))` — CHECK first
  that nothing in kvui/CommonClient indexes the pair or the tab by name
  (hint highlighting, `log_panels`, etc.) before choosing this.
If both look fragile across kvui versions, take Devon's fallback (option 2 above)
— it's pure addition, zero base-class surgery.

## Guardrails

- `kvui` MUST be imported before any `kivy.*` module (assert at kvui top; comment
  in gui.py explains).
- Never import Kivy at apworld load time — gui.py is only reached via
  `SMOContext.run_gui()`.
- Keep the `_LiveLabel`/text_size binding patterns as-is; the docstrings document
  two runaway-layout bugs (switch pill, `_wrapping_label`) — don't "simplify" them.
- File work via Read/Edit/Write ONLY (Linux shell serves stale/truncated files —
  CLAUDE.md). GUI can't run in the sandbox; hand a launch test to Devon on Windows.
- Existing UI regression tests: `apworld/smo_archipelago/tests/` (e.g.
  `test_switch_pill_layout.py`) show the headless-testing pattern — add one for
  the new layout if practical (widget-tree assertions, not pixel tests).

## Acceptance

- Archipelago tab: tracker panel + AP log side by side; tracker still refreshes
  on the 1.5 s tick; hints tab, top bar, Switch pill untouched.
- Odyssey tab: SMO log only (or, fallback: new Tracker tab present, Odyssey unchanged).
- Update the module docstring's tab inventory (it's load-bearing documentation).
- Rebuild note for Devon: client ships inside the apworld zip → run
  `python scripts/install_apworld.py` (plain, Windows) before launching. No
  switch-mod rebuild.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (especially the stale-shell-mount
> warning and the install_apworld regen loop), then
> docs/handoff-gui-tracker-merge.md, and implement it. Start by reading
> vendor/Archipelago/kvui.py to understand how GameManager builds the
> logging_pairs tabs before touching gui.py. Prefer Devon's option 1 (merge
> tracker into the Archipelago tab, Odyssey becomes logs-only); fall back to the
> Tracker-tab clone only if re-parenting the base tab is fragile. Use Read/Edit/
> Write for all file work — never shell cat/grep/diff. Add a headless widget-tree
> test if practical, update gui.py's docstring tab inventory, and finish by
> telling Devon the exact verification steps (install_apworld.py, launch client,
> what to eyeball on each tab).
