"""Kivy UI for SMOClient.

THIS MODULE PULLS KIVY. Never import it from anywhere that runs at
apworld load time — generation hosts may not have a display server. Only
SMOContext.run_gui() reaches it, and run_gui is only called from
client/main.py inside the Launcher subprocess.

Subclasses CommonClient's GameManager, which sets up the Kivy window,
log surfaces, and the input box wired into ClientCommandProcessor.

Replaces the Flask web tracker (deleted in this phase): the snapshot
info that used to live at http://localhost:8000/ is now a "Tracker"
tab; AP / Switch connection info is a "Connections" tab.
"""

from __future__ import annotations

import time
import typing

# IMPORTANT: kvui MUST be imported before any kivy.* module. kvui asserts
# `"kivy" not in sys.modules` at module top (for frozen-build compatibility),
# so any prior `from kivy.X import Y` here would trip the assert and prevent
# the GUI from starting. Same reason Wargroove imports kvui first.
from kvui import GameManager

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

if typing.TYPE_CHECKING:  # pragma: no cover
    from .context import SMOContext


# Polling interval for tracker + connections refresh. State changes drive
# at human speed (moon collects, item arrivals, save loads) so 1.5s mirrors
# the old web tracker's setInterval and keeps Kivy's frame budget free.
_REFRESH_INTERVAL = 1.5


class _LiveLabel(Label):
    """Plain Label sized to its text content; pinned top-left in a ScrollView.

    Kivy's default Label is fixed-height and clips text; this binds height
    to texture_size so multi-line text grows the scrollable region.
    """

    def __init__(self, **kwargs):
        super().__init__(
            markup=True,
            valign="top",
            halign="left",
            size_hint_y=None,
            padding=(dp(10), dp(10)),
            **kwargs,
        )
        self.bind(width=self._refit, texture_size=self._refit)

    def _refit(self, *_):
        self.text_size = (self.width - dp(20), None)
        self.height = max(self.texture_size[1] + dp(20), dp(60))


class SmoManager(GameManager):
    """Window for the SMOClient.

    Two extra log streams (Archipelago + SMO) and two custom tabs
    (Tracker + Connections) on top of the GameManager baseline.
    """

    logging_pairs = [
        ("Client", "Archipelago"),
        ("SMO", "SMO"),
    ]
    base_title = "Archipelago SMO Client"

    def __init__(self, ctx: "SMOContext"):
        super().__init__(ctx)
        self._tracker_label: _LiveLabel | None = None
        self._connections_label: _LiveLabel | None = None

    def build(self):
        container = super().build()
        # Tracker tab: live snapshot mirror of received items + checked
        # locations grouped by kingdom (was the Flask web tracker).
        tracker_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        self._tracker_label = _LiveLabel(text="(connecting…)")
        tracker_scroll.add_widget(self._tracker_label)
        self.add_client_tab("Tracker", tracker_scroll)

        # Connections tab: AP/Switch endpoint summary + datapackage state.
        # (Replaces the debug `POST /api/test/inject-deathlink` button —
        # use `/inject_deathlink` in the command bar instead, landing in
        # Phase 5.)
        conn_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        self._connections_label = _LiveLabel(text="(connecting…)")
        conn_scroll.add_widget(self._connections_label)
        self.add_client_tab("Connections", conn_scroll)

        Clock.schedule_interval(self._refresh_panels, _REFRESH_INTERVAL)
        return container

    # ------------------------------------------------------------ panel refresh

    def _refresh_panels(self, _dt) -> None:
        try:
            if self._tracker_label is not None:
                self._tracker_label.text = _format_tracker(self.ctx)
            if self._connections_label is not None:
                self._connections_label.text = _format_connections(self.ctx)
        except Exception:
            # Don't let a transient render error kill the scheduled refresh;
            # Clock.schedule_interval cancels on exception.
            import logging
            logging.getLogger("SMO").exception("panel refresh failed")


def _format_tracker(ctx: "SMOContext") -> str:
    """Tracker tab body — Kivy BBCode markup string."""
    snap = ctx.state.snapshot()
    caps = snap.get("captures_unlocked") or []
    kingdoms = snap.get("kingdoms_unlocked") or []
    moons_recv = snap.get("moons_received_by_kingdom") or {}
    moons_chk = snap.get("moons_checked_by_kingdom") or {}
    recent = snap.get("recent_items") or []

    parts: list[str] = []
    parts.append(
        f"[b]Slot[/b] {snap.get('slot') or '—'}    "
        f"[b]Seed[/b] {snap.get('seed') or '—'}    "
        f"[b]Items[/b] {snap.get('received_count', 0)}    "
        f"[b]Checks[/b] {snap.get('checked_count', 0)}    "
        f"[b]Deaths[/b] {snap.get('death_count', 0)}"
    )
    parts.append("")
    parts.append("[b]Kingdoms unlocked[/b]")
    parts.append(", ".join(kingdoms) if kingdoms else "[i](none yet)[/i]")
    parts.append("")
    parts.append("[b]Captures unlocked[/b]")
    parts.append(", ".join(caps) if caps else "[i](none yet)[/i]")
    parts.append("")
    parts.append("[b]Moons by kingdom (checked / received)[/b]")
    all_k = sorted(set(moons_recv) | set(moons_chk))
    if all_k:
        for k in all_k:
            parts.append(f"  {k}:    {moons_chk.get(k, 0)} / {moons_recv.get(k, 0)}")
    else:
        parts.append("[i](nothing yet)[/i]")
    parts.append("")
    parts.append("[b]Recent items[/b]")
    if recent:
        # Reverse so newest is first, like the old web tracker.
        for it in reversed(recent[-20:]):
            label = it.get("name") or it.get("shine_id") or it.get("cap") or it.get("kingdom") or it.get("kind")
            sender = it.get("from") or "?"
            parts.append(f"  {label} [i]from[/i] {sender}")
    else:
        parts.append("[i](none yet)[/i]")
    return "\n".join(parts)


def _format_connections(ctx: "SMOContext") -> str:
    """Connections tab body — Kivy BBCode markup string."""
    snap = ctx.state.snapshot()
    parts: list[str] = []
    parts.append("[b]Archipelago[/b]")
    parts.append(f"  Status: {snap.get('ap_conn', 'disconnected')}")
    parts.append(f"  Slot:   {snap.get('slot') or '—'}")
    parts.append(f"  Seed:   {snap.get('seed') or '—'}")
    server_addr = getattr(ctx, "server_address", None) or "—"
    parts.append(f"  Server: {server_addr}")
    parts.append(f"  Items received: {snap.get('received_count', 0)}")
    parts.append("")
    parts.append("[b]Switch[/b]")
    parts.append(f"  Status: {snap.get('switch_conn', 'disconnected')}")
    if ctx.switch is not None:
        host = getattr(ctx.switch, "_host", "?")
        port = getattr(ctx.switch, "_port", "?")
        parts.append(f"  Listen: {host}:{port}")
    else:
        parts.append("  Listen: (server not started)")
    parts.append(f"  Checks forwarded: {snap.get('checked_count', 0)}")
    parts.append(f"  Deaths observed: {snap.get('death_count', 0)}")
    parts.append("")
    parts.append("[b]Data package[/b]")
    parts.append(f"  Items known:     {len(ctx.dp.item_id_to_name)}")
    parts.append(f"  Locations known: {len(ctx.dp.location_id_to_name)}")
    parts.append(f"  Scout cache:     {len(ctx.scout_cache)} entries")
    parts.append("")
    parts.append("[b]DeathLink[/b]: " + ("ENABLED" if ctx.deathlink_enabled else "disabled"))
    parts.append("")
    parts.append(f"[i]refreshed {time.strftime('%H:%M:%S')}[/i]")
    return "\n".join(parts)
