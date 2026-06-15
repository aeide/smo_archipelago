"""Tests for P1 CoinGrant implementation.

Verifies four layers via pure source-parse (no Archipelago imports, no
module execution) so the suite runs in the standard test job on Python 3.10
without SMOAP_LIVE_AP.

  1. Protocol layer (client/protocol.py): CoinGrant dataclass fields, t value.
  2. State layer (client/state.py): compute_cap_coin_total definition, "Cap"
     key lookup, x100 multiplication, and defensive max(0, ...) clamp.
  3. Server layer (client/switch_server.py): CoinGrant imported, push_coin_grant
     defined and wired, _run_post_hello_replay calls it.
  4. Context layer (client/context.py): cap_moon_received_this_batch flag set for
     "Cap" kingdom moons, push_coin_grant called from _process_received_items.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parents[1] / "client"


# Helpers

def _src(filename: str) -> str:
    return (CLIENT_ROOT / filename).read_text(encoding="utf-8")


def _fn_body(src: str, fn_name: str) -> str:
    """Extract the body of the first function/method matching fn_name."""
    m = re.search(
        r"(?:async\s+)?def " + re.escape(fn_name) + r"\b(.+?)(?=\n    (?:async\s+)?def |\nclass |\Z)",
        src, re.DOTALL,
    )
    assert m, f"{fn_name} not found in source"
    return m.group(1)


# 1. Protocol layer

def test_protocol_syntax_valid():
    ast.parse(_src("protocol.py"))


def test_coin_grant_class_exists():
    assert "class CoinGrant" in _src("protocol.py")


def test_coin_grant_t_field():
    src = _src("protocol.py")
    m = re.search(r"class CoinGrant.*?(?=\nclass |\Z)", src, re.DOTALL)
    assert m, "CoinGrant class body not found"
    body = m.group(0)
    assert 't: str = "coin_grant"' in body, \
        'CoinGrant must have t: str = "coin_grant" field'


def test_coin_grant_total_field():
    src = _src("protocol.py")
    m = re.search(r"class CoinGrant.*?(?=\nclass |\Z)", src, re.DOTALL)
    assert m
    assert "total: int = 0" in m.group(0), \
        "CoinGrant must have total: int = 0 field"


def test_coin_grant_before_serialization_helpers():
    src = _src("protocol.py")
    coin_idx = src.find("class CoinGrant")
    encode_idx = src.find("def encode(")
    assert coin_idx != -1, "CoinGrant not found"
    assert encode_idx != -1, "encode() not found"
    assert coin_idx < encode_idx, \
        "CoinGrant must be defined before the encode() serialisation helper"


# 2. State layer

def test_state_syntax_valid():
    ast.parse(_src("state.py"))


def test_compute_cap_coin_total_defined():
    assert "def compute_cap_coin_total(" in _src("state.py")


def test_compute_cap_coin_total_uses_cap_key():
    body = _fn_body(_src("state.py"), "compute_cap_coin_total")
    assert '"Cap"' in body or "'Cap'" in body, \
        'compute_cap_coin_total must look up moons_received_by_kingdom["Cap"]'


def test_compute_cap_coin_total_multiplies_by_100():
    body = _fn_body(_src("state.py"), "compute_cap_coin_total")
    assert "* 100" in body or "*100" in body, \
        "compute_cap_coin_total must multiply by 100 (coins per moon)"


def test_compute_cap_coin_total_clamps_negative():
    body = _fn_body(_src("state.py"), "compute_cap_coin_total")
    assert "max(0" in body, \
        "compute_cap_coin_total must clamp with max(0, ...) to avoid negative totals"


def test_compute_cap_coin_total_uses_lock():
    body = _fn_body(_src("state.py"), "compute_cap_coin_total")
    assert "_lock" in body, \
        "compute_cap_coin_total must hold self._lock (thread-safe read)"


def test_compute_cap_coin_total_int_return_annotation():
    src = _src("state.py")
    m = re.search(r"def compute_cap_coin_total\(.*?\)\s*->\s*int", src)
    assert m, "compute_cap_coin_total should have -> int return annotation"


# 3. Server layer

def test_switch_server_syntax_valid():
    ast.parse(_src("switch_server.py"))


def test_switch_server_imports_coin_grant():
    src = _src("switch_server.py")
    m = re.search(r"from \.protocol import \([^)]+\)", src, re.DOTALL)
    assert m, "protocol import block not found"
    assert "CoinGrant" in m.group(0), "CoinGrant must be in the protocol import block"


def test_push_coin_grant_defined():
    assert "async def push_coin_grant(" in _src("switch_server.py")


def test_push_coin_grant_calls_compute():
    body = _fn_body(_src("switch_server.py"), "push_coin_grant")
    # P3-3b: push_coin_grant now uses compute_total_coin_grant (Cap moons +
    # duplicate capture/ability coins). compute_cap_coin_total stays as the
    # Cap-only helper but is no longer what push_coin_grant calls.
    assert "compute_total_coin_grant" in body, \
        "push_coin_grant must call state.compute_total_coin_grant()"


def test_push_coin_grant_sends_coin_grant_msg():
    body = _fn_body(_src("switch_server.py"), "push_coin_grant")
    assert "CoinGrant(" in body, \
        "push_coin_grant must construct and send a CoinGrant message"


def test_push_coin_grant_no_ops_on_zero():
    body = _fn_body(_src("switch_server.py"), "push_coin_grant")
    assert "== 0" in body or "not total" in body, \
        "push_coin_grant must short-circuit when total is 0"


def test_push_coin_grant_in_post_hello_replay():
    body = _fn_body(_src("switch_server.py"), "_run_post_hello_replay")
    assert "push_coin_grant" in body, \
        "_run_post_hello_replay must call push_coin_grant() for HELLO replay"


def test_push_coin_grant_after_kingdom_gates():
    body = _fn_body(_src("switch_server.py"), "_run_post_hello_replay")
    gates_idx = body.find("push_kingdom_gates")
    coin_idx = body.find("push_coin_grant")
    assert gates_idx != -1, "push_kingdom_gates not found in _run_post_hello_replay"
    assert coin_idx != -1, "push_coin_grant not found in _run_post_hello_replay"
    assert gates_idx < coin_idx, \
        "push_coin_grant must follow push_kingdom_gates in HELLO replay"


# 4. Context layer

def test_context_syntax_valid():
    ast.parse(_src("context.py"))


def test_context_has_cap_moon_flag():
    # P3-3b renamed cap_moon_received_this_batch -> coin_relevant_this_batch
    # (now also set for captures/abilities, since their clones convert to coins).
    assert "coin_relevant_this_batch" in _src("context.py")


def test_context_cap_flag_gated_on_cap_kingdom():
    src = _src("context.py")
    m = re.search(r"coin_relevant_this_batch\s*=\s*True", src)
    assert m, "coin_relevant_this_batch = True not found in context.py"
    window = src[max(0, m.start() - 200): m.end() + 100]
    assert "Cap" in window, \
        'coin_relevant_this_batch must be set when ref.kingdom == "Cap"'


def test_context_calls_push_coin_grant():
    body = _fn_body(_src("context.py"), "_process_received_items")
    assert "push_coin_grant" in body, \
        "_process_received_items must call switch.push_coin_grant() on Cap moon arrival"


def test_context_cap_flag_inside_moon_branch():
    src = _src("context.py")
    moon_match = re.search(
        r"if ref\.kind.*?MOON.*?moon_received_this_batch\s*=\s*True",
        src, re.DOTALL,
    )
    assert moon_match, "moon_received_this_batch = True block not found"
    after = src[moon_match.start(): moon_match.end() + 200]
    assert "coin_relevant_this_batch" in after, \
        "coin_relevant_this_batch must be set inside the moon-kind branch (Cap)"
