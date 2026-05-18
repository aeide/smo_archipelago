"""Regression test for the top-bar Switch-status pill layout.

A previous fix to vertically center the pill text bound
`text_size = widget_size`. That created a feedback loop with the existing
`texture_size -> width` binding: the texture grew to fill text_size,
which grew width, which re-grew text_size — runaway-growth on a real
top bar (eating the AP server input) or collapse-to-2px on a
zero-height layout. In either case the user couldn't type a server
address.

The fix bounds only the height axis of `text_size`, leaving the width
unconstrained so the texture reports its natural text width back to the
auto-width binding.

This test reproduces the layout in-process with a hidden Kivy window
and asserts the pill width is reasonable (≈ texture width + padding)
and stable across multiple layout passes.

Skipped when Kivy / a display backend isn't available — the binding
logic is structural to a UI we don't ship to CI.
"""

from __future__ import annotations

import os
import sys

import pytest

# kvui asserts kivy isn't loaded yet, so the import has to happen BEFORE
# any `kivy.*` pull. The skipif chain hides ImportError when Kivy or its
# SDL2 backend isn't installed (extraction-only test machines, headless
# CI runners).
os.environ.setdefault("KIVY_NO_ARGS", "1")

# vendor/Archipelago hosts kvui.py. Test machines that lack the
# submodule (or its native SDL2 deps) skip the whole module. In a
# worktree the submodule is usually not checked out, so we also probe
# the main repo (parents of the worktree dir) for a populated copy —
# kvui only needs to be importable, it doesn't have to belong to this
# git tree.
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
    # gui.py imports kvui at module top. kvui asserts kivy isn't loaded
    # yet, so this import MUST happen before any direct `kivy.*` pull
    # (including pytest.importorskip("kivy"), which would load kivy and
    # trip the assert). If kvui/kivy/Manual deps aren't present, skip.
    from client.gui import _bind_switch_pill_layout
except Exception as exc:  # pragma: no cover — env-dependent
    pytest.skip(f"client.gui unavailable: {exc}", allow_module_level=True)

# Hide the window — Config.set must happen before EventLoop.ensure_window.
try:
    from kivy.config import Config  # noqa: E402

    Config.set("graphics", "window_state", "hidden")

    from kivy.base import EventLoop  # noqa: E402
    from kivy.metrics import dp  # noqa: E402
    from kivy.uix.boxlayout import BoxLayout  # noqa: E402
    from kivy.uix.button import Button  # noqa: E402
    from kivy.uix.label import Label  # noqa: E402
    from kivy.uix.textinput import TextInput  # noqa: E402

    EventLoop.ensure_window()
except Exception as exc:  # pragma: no cover — no display backend
    pytest.skip(f"Kivy window backend unavailable: {exc}",
                allow_module_level=True)


def _build_topbar(window_width_dp: float = 800.0,
                  row_height_dp: float = 30.0):
    """Build a top bar that mirrors GameManager.connect_layout shape:
    [Server: label][server input][Connect button][pill]."""
    row = BoxLayout(orientation="horizontal",
                    height=dp(row_height_dp),
                    size_hint_y=None)
    label = Label(text="Server:", size_hint_x=None, width=dp(60))
    addr = TextInput(text="archipelago.gg")
    btn = Button(text="Connect", size_hint_x=None, width=dp(80))
    pill = Label(
        text="Off",
        markup=True,
        size_hint_x=None,
        size_hint_y=None,
        width=dp(60),
        height=row.height,
        halign="center",
        valign="middle",
        padding=(dp(6), 0),
        text_size=(None, row.height),
    )
    _bind_switch_pill_layout(pill)
    for w in (label, addr, btn, pill):
        row.add_widget(w)
    row.size = (dp(window_width_dp), dp(row_height_dp))
    return row, label, addr, btn, pill


def _settle(row, widgets, passes: int = 5):
    for _ in range(passes):
        for w in widgets:
            if hasattr(w, "texture_update"):
                w.texture_update()
        row.do_layout()


def test_switch_pill_fits_text_and_doesnt_eat_server_input():
    """Pill should hug its text width; server input should keep most of
    the top bar (a few hundred dp on an 800dp-wide window)."""
    row, _label, addr, _btn, pill = _build_topbar()
    # 20 passes — the buggy `size→text_size` binding takes a few
    # iterations to fully exit the fit-to-text band, so we settle past
    # that point before asserting.
    _settle(row, (pill, addr, _btn, _label), passes=20)

    # Pill should be narrow: tex width of "Off" + dp(12) padding pair.
    # texture_size[0] is platform-font-dependent (~15-25px), so allow a
    # generous range — the regression we care about is "not 600px wide
    # eating the input" and "not collapsed to 2px".
    assert dp(15) < pill.width < dp(100), (
        f"pill width {pill.width} outside the expected fit-to-text band"
    )

    # The TextInput is the only flex widget — it should absorb most of
    # the row's remaining width. On an 800dp window with three fixed-
    # width widgets (60 + 80 + ~45 = ~185dp), the input deserves the
    # remaining ~615dp.
    assert addr.width > dp(400), (
        f"server input width {addr.width} got squashed — the pill is "
        f"probably eating the top bar (regression of df5e3a4)"
    )


def test_switch_pill_width_is_stable_across_layout_passes():
    """The fix removed the size→text_size→texture_size→width feedback.
    Multiple layout passes should converge to a steady width, not
    runaway-grow or oscillate."""
    row, _label, addr, _btn, pill = _build_topbar()
    _settle(row, (pill, addr, _btn, _label), passes=2)
    w1 = pill.width
    _settle(row, (pill, addr, _btn, _label), passes=8)
    w2 = pill.width
    assert abs(w2 - w1) < 0.5, (
        f"pill width changed across layout passes ({w1} -> {w2}); a "
        f"feedback loop in the bindings is likely"
    )


def test_switch_pill_height_axis_is_bound_for_valign():
    """`valign='middle'` is a no-op without `text_size[1]` set. Confirm
    the height-axis binding fires and produces a non-None text_size
    height matching widget height."""
    row, _label, addr, _btn, pill = _build_topbar()
    _settle(row, (pill, addr, _btn, _label))

    # text_size width should remain None so the texture is free to
    # report natural text width — that's what feeds the auto-width
    # binding. text_size height should equal the widget height so
    # valign='middle' has a box to center within.
    assert pill.text_size[0] is None, (
        f"text_size[0] = {pill.text_size[0]}; binding it locks the "
        f"texture to widget width and reintroduces the df5e3a4 loop"
    )
    assert pill.text_size[1] == pytest.approx(pill.height), (
        f"text_size[1] {pill.text_size[1]} != height {pill.height} — "
        f"valign='middle' will be a no-op"
    )


def test_buggy_binding_demonstrates_the_regression():
    """Lock in *why* we use the height-only binding. If you bind
    text_size = widget_size, the texture grows to fill text_size,
    width grows to texture + padding, text_size grows again — runaway
    growth or collapse depending on layout context. This test wires
    the regressed bindings on a fresh pill and asserts the width ends
    up outside the fit-to-text band, proving the bug still reproduces
    with this Kivy version."""
    row = BoxLayout(orientation="horizontal", height=dp(30),
                    size_hint_y=None)
    addr = TextInput(text="archipelago.gg")
    row.add_widget(Label(text="Server:", size_hint_x=None, width=dp(60)))
    row.add_widget(addr)
    row.add_widget(Button(text="Connect", size_hint_x=None, width=dp(80)))

    bad_pill = Label(
        text="Off",
        markup=True,
        size_hint_x=None,
        size_hint_y=None,
        width=dp(60),
        height=row.height,
        halign="center",
        valign="middle",
        padding=(dp(6), 0),
    )
    bad_pill.bind(
        texture_size=lambda lbl, sz: setattr(lbl, "width", sz[0] + dp(12)),
        size=lambda lbl, sz: setattr(lbl, "text_size", sz),
    )
    row.add_widget(bad_pill)
    row.size = (dp(800), dp(30))
    _settle(row, (bad_pill, addr), passes=8)

    # Bug manifests as either runaway growth or collapse; both leave
    # the ~15-100dp fit band that the fixed binding lands in.
    in_fit_band = dp(15) < bad_pill.width < dp(100)
    assert not in_fit_band, (
        f"buggy binding produced fit-band width {bad_pill.width}; "
        f"either the regression no longer reproduces (re-evaluate this "
        f"test) or Kivy semantics changed under us"
    )
