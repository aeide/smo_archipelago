"""Widget-tree regression test for the merged "Archipelago" tab.

The SMO tracker (moons/captures/abilities/DeathLink) was moved out of the
old Odyssey split and INTO the built-in Archipelago log tab, so the tab
now shows the tracker on the left and the AP "most recent finds" log on
the right. gui.py._build_ap_split() constructs that 50/50 horizontal
split; this test asserts its shape (order + size hints) without standing
up a full GameManager + SMOContext — the same isolation strategy
test_switch_pill_layout.py uses for _bind_switch_pill_layout.

The load-bearing invariants this guards:
  * the tracker is the LEFT child, the AP log is the RIGHT child;
  * both get size_hint_x == 0.5 so neither half starves the other.

Skipped when Kivy / a display backend isn't available — the layout is
structural to a UI we don't ship to CI.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("KIVY_NO_ARGS", "1")


# vendor/Archipelago hosts kvui.py; in a worktree the submodule may not be
# checked out, so probe parent dirs for a populated copy. Mirrors
# test_switch_pill_layout._find_kvui_dir.
def _find_kvui_dir() -> str | None:
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(8):
        cand = os.path.join(here, "vendor", "Archipelago", "kvui.py")
        if os.path.isfile(cand):
            return os.path.dirname(cand)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


_KVUI_DIR = _find_kvui_dir()
if _KVUI_DIR and _KVUI_DIR not in sys.path:
    sys.path.insert(0, _KVUI_DIR)

try:
    # gui.py imports kvui at module top; kvui asserts kivy isn't loaded yet,
    # so this import MUST precede any direct `kivy.*` pull. If kvui/kivy deps
    # aren't present, skip the whole module.
    from client.gui import _build_ap_split
except Exception as exc:  # pragma: no cover — env-dependent
    pytest.skip(f"client.gui unavailable: {exc}", allow_module_level=True)

try:
    from kivy.config import Config  # noqa: E402

    Config.set("graphics", "window_state", "hidden")

    from kivy.base import EventLoop  # noqa: E402
    from kivy.uix.boxlayout import BoxLayout  # noqa: E402
    from kivy.uix.label import Label  # noqa: E402
    from kivy.uix.scrollview import ScrollView  # noqa: E402
    from kivy.uix.widget import Widget  # noqa: E402

    EventLoop.ensure_window()
except Exception as exc:  # pragma: no cover — no display backend
    pytest.skip(f"Kivy window backend unavailable: {exc}",
                allow_module_level=True)


def _make_split():
    """Build a split with a real ScrollView (tracker stand-in) and a plain
    Widget standing in for the AP UILog — _build_ap_split only touches
    size_hint_x + add_widget, so a bare Widget exercises it faithfully
    without the kvui RecycleView machinery."""
    tracker_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
    tracker_scroll.add_widget(Label(text="(connecting…)"))
    ap_log = Widget()
    split = _build_ap_split(tracker_scroll, ap_log)
    return split, tracker_scroll, ap_log


def test_split_is_horizontal_box_with_both_panels():
    split, tracker_scroll, ap_log = _make_split()
    assert isinstance(split, BoxLayout)
    assert split.orientation == "horizontal"
    # Both panels parented under the split.
    assert tracker_scroll.parent is split
    assert ap_log.parent is split
    assert len(split.children) == 2


def test_tracker_is_left_ap_log_is_right():
    """Kivy prepends on add_widget, so children[] is reverse insertion
    order: the first-added tracker ends up last, the AP log first. Assert
    the visual left→right order (tracker, then AP log) survives that."""
    split, tracker_scroll, ap_log = _make_split()
    # children[-1] is the first widget added (leftmost); children[0] the last.
    assert split.children[-1] is tracker_scroll, "tracker must be the LEFT panel"
    assert split.children[0] is ap_log, "AP log must be the RIGHT panel"


def test_both_panels_are_half_width():
    split, tracker_scroll, ap_log = _make_split()
    assert tracker_scroll.size_hint_x == pytest.approx(0.5)
    assert ap_log.size_hint_x == pytest.approx(0.5)
