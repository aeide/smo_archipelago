"""Wire format for the Switch <-> Bridge channel.

Single persistent TCP connection. Each message is one line of UTF-8 JSON
terminated by '\n'. Field 't' is the message type. All ids/strings are
canonical (sourced from the apworld's data/items.json) so the Switch can do
a static lookup without holding the AP datapackage.

Max line length: 8 KiB. Longer lines are rejected and the parser resyncs to
the next '\n'.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable

MAX_LINE_BYTES = 8 * 1024


class ItemKind(str, Enum):
    MOON = "moon"
    CAPTURE = "capture"
    KINGDOM = "kingdom"
    SHOP = "shop"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Switch -> Bridge
# ---------------------------------------------------------------------------

@dataclass
class HelloMsg:
    t: str = "hello"
    mod_ver: str = ""
    smo_ver: str = ""
    cap_table_hash: str = ""


@dataclass
class CheckMsg:
    """A location was just checked in-game.

    Either the legacy resolved fields (kingdom + shine_id / cap) OR the M4 raw
    SMO identifiers (stage_name + object_id / hack_name) may be set. The
    bridge prefers raw fields and resolves them via shine_map / capture_map.
    """
    t: str = "check"
    kind: str = ItemKind.MOON.value
    kingdom: str | None = None
    shine_id: str | None = None
    cap: str | None = None
    slot: int | None = None  # for shop slots
    # M4 raw identifiers (Switch sends, bridge resolves)
    stage_name: str | None = None   # moons: ShineInfo::stageName
    object_id: str | None = None    # moons: ShineInfo::objectId
    shine_uid: int | None = None    # moons: ShineInfo::shineId
    hack_name: str | None = None    # captures: PlayerHackKeeper::getCurrentHackName


@dataclass
class StatusMsg:
    t: str = "status"
    kingdom: str | None = None
    scenario: int | None = None
    moons_collected: int | None = None
    stage_name: str | None = None  # M4: raw stage at the flag flip


@dataclass
class GoalMsg:
    t: str = "goal"


@dataclass
class DeathMsg:
    """Mario died on the Switch. Bridge (when DeathLink is enabled) converts
    this into an AP Bounce so other DeathLink-tagged slots take damage too."""
    t: str = "death"
    ts_ms: int = 0


@dataclass
class PingMsg:
    t: str = "ping"
    ts_ms: int = 0


@dataclass
class LogMsg:
    t: str = "log"
    level: str = "info"
    msg: str = ""


# State snapshot. Sent by the Switch on every (re)connect (right after HELLO).
# Three kinds of message in sequence: one StateBeginMsg, N StateChunkMsg
# (per-stage shines + a trailing "_meta" chunk for cross-stage data), one
# StateEndMsg. The bridge accumulates them and on StateEndMsg dispatches
# each entry through the same `check` path live moon-get hooks use, so the
# AP server learns about anything the Switch collected during a disconnect.
#
# Carries RAW SMO identifiers (stage_name, object_id, shine_uid, hack_name)
# matching M4's check semantics; the bridge resolves them via shine_map.json
# / capture_map.json. Re-sending the same snapshot is a no-op because the
# bridge dedupes at AP-id level (`_ctx.locations_checked`).
#
# Triggers on the Switch side:
#   - Right after sendHello() on every (re)connect
#   - SaveLoadHook calls requestRehello() which closes/reopens the TCP
#     connection, which re-runs sendHello + the snapshot

@dataclass
class StateBeginMsg:
    t: str = "state_begin"
    mod_ver: str = ""
    save_slot: int | None = None  # informational; bridge does NOT fence on it


@dataclass
class StateChunkMsg:
    """One stage's worth of owned shines, OR the cross-stage `_meta` chunk.

    Per-stage chunk: `stage_name` is the SMO stage key (e.g. "CapWorldHomeStage"),
    `shines` is a list of {object_id, shine_uid} dicts.

    `_meta` chunk (stage_name == "_meta"): populates `captures` (raw hack_name
    strings) and `goal_reached`. The bridge is the source of truth for kingdom
    unlocks (received items), so we don't echo them back here.
    """
    t: str = "state_chunk"
    stage_name: str = ""
    shines: list[dict] | None = None  # [{"object_id": "...", "shine_uid": N}]
    captures: list[str] | None = None  # raw hack_names; only on `_meta` chunk
    goal_reached: bool | None = None   # only on `_meta` chunk


@dataclass
class StateEndMsg:
    t: str = "state_end"


# ---------------------------------------------------------------------------
# Bridge -> Switch
# ---------------------------------------------------------------------------

@dataclass
class HelloAckMsg:
    t: str = "hello_ack"
    ok: bool = True
    seed: str = ""
    slot: str = ""
    cap_table_hash: str = ""
    # Bridge-owned DeathLink toggle. The Switch mod ships the apply path
    # unconditionally but only acts on inbound kill messages when this flag is
    # set here, so the user enables/disables DeathLink in bridge config rather
    # than rebuilding the mod. Older Switch builds (M4-era) ignore the field.
    deathlink_enabled: bool = False
    err: str | None = None


@dataclass
class ItemRef:
    """Minimum info to locate an item or check on the Switch.

    Carries both canonical (kingdom/shine_id/cap) AND raw M4 identifiers
    (stage_name/object_id/shine_uid/hack_name). Raw identifiers are filled
    in when the source was a raw-ID `check` (or a snapshot entry); they're
    used by `BridgeState` to dedupe CheckEvents across snapshot replays
    that don't carry canonical fields.

    NOTE: raw fields are STRIPPED when this ItemRef is serialized into a
    CheckedReplayMsg (see `to_replay_dict()`), because the C++ parser at
    `switch-mod/src/ap/ApProtocol.cpp:parseItemRefBody` rejects unknown
    fields. Internal use only — never reach the wire.
    """
    kind: str = ItemKind.MOON.value
    kingdom: str | None = None
    shine_id: str | None = None
    cap: str | None = None
    slot: int | None = None
    name: str | None = None  # for OTHER kinds where we just have a label
    # M4 raw identifiers (preserved for dedup; not sent in CheckedReplay)
    stage_name: str | None = None
    object_id: str | None = None
    shine_uid: int | None = None
    hack_name: str | None = None

    def to_replay_dict(self) -> dict[str, Any]:
        """Wire payload for inclusion in a CheckedReplayMsg.

        Strips the raw M4 fields because the C++ ItemRef parser
        (`parseItemRefBody`) rejects unknown keys.
        """
        return _strip_none({
            "kind": self.kind,
            "kingdom": self.kingdom,
            "shine_id": self.shine_id,
            "cap": self.cap,
            "slot": self.slot,
            "name": self.name,
        })


@dataclass
class CheckedReplayMsg:
    t: str = "checked_replay"
    ids: list[ItemRef] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "ids": [ref.to_replay_dict() for ref in self.ids],
        }


@dataclass
class ItemMsg:
    """Item granted by AP to be applied on Switch."""
    t: str = "item"
    kind: str = ItemKind.MOON.value
    kingdom: str | None = None
    shine_id: str | None = None
    cap: str | None = None
    slot: int | None = None
    name: str | None = None
    from_: str = "self"

    def to_wire(self) -> dict[str, Any]:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return _strip_none(d)


@dataclass
class PrintMsg:
    t: str = "print"
    text: str = ""


@dataclass
class ApStateMsg:
    t: str = "ap_state"
    conn: str = "disconnected"  # disconnected | connecting | authed | ready


@dataclass
class PongMsg:
    t: str = "pong"
    ts_ms: int = 0


@dataclass
class ErrMsg:
    t: str = "err"
    code: str = ""
    ctx: str = ""


@dataclass
class KillMsg:
    """DeathLink bounce forwarded by the bridge: another slot died, so the
    Switch should kill Mario. M4 only logs this on the Switch side; actual
    killing lands in M6 with the player-state-write machinery."""
    t: str = "kill"
    source: str = ""
    cause: str = ""


# ---------------------------------------------------------------------------
# (de)serialization helpers
# ---------------------------------------------------------------------------

def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def encode(msg: Any) -> bytes:
    """Serialize a dataclass message to a single line of bytes including '\n'."""
    if hasattr(msg, "to_wire"):
        d = msg.to_wire()
    else:
        d = _strip_none(asdict(msg))
    line = json.dumps(d, separators=(",", ":"), ensure_ascii=False)
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ValueError(f"encoded message exceeds {MAX_LINE_BYTES} bytes")
    return (line + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict[str, Any]:
    """Decode one line into a dict. Caller dispatches on 't'."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    return json.loads(line)


def iter_lines(buffer: bytearray) -> Iterable[bytes]:
    """Yield complete '\n'-terminated lines from buffer; consume them in place.

    Lines longer than MAX_LINE_BYTES are skipped (resync to next '\n').
    Returns when buffer has no more complete lines.
    """
    while True:
        nl = buffer.find(b"\n")
        if nl < 0:
            if len(buffer) > MAX_LINE_BYTES:
                # No newline in 8KB+ of data — drop everything; corrupt stream.
                buffer.clear()
            return
        line = bytes(buffer[:nl])
        del buffer[: nl + 1]
        if len(line) > MAX_LINE_BYTES:
            continue  # skip oversized line, resync
        if line.strip():
            yield line
