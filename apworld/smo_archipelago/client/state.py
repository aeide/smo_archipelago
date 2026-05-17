"""Bridge-side mirror of game state.

The bridge maintains an authoritative snapshot independently of any single
connection: AP can drop, the Switch can reboot, the bridge keeps state. Both
sides resync from this snapshot when they reconnect.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .protocol import ItemRef


@dataclass
class ItemEvent:
    item: ItemRef
    sender: str = "self"  # "self" or another player's name
    received_at: float = field(default_factory=time.time)


@dataclass
class CheckEvent:
    item: ItemRef
    checked_at: float = field(default_factory=time.time)


class BridgeState:
    """Thread-safe snapshot. Web tracker reads it; AP/Switch loops mutate it."""

    def __init__(self):
        self._lock = threading.RLock()
        self.ap_conn: str = "disconnected"
        self.switch_conn: str = "disconnected"
        self.seed: str = ""
        self.slot: str = ""
        self.received_items: list[ItemEvent] = []
        self.checked_locations: list[CheckEvent] = []
        self.captures_unlocked: set[str] = set()
        self.kingdoms_unlocked: set[str] = set()
        self.moons_received_by_kingdom: dict[str, int] = {}
        self.moons_checked_by_kingdom: dict[str, int] = {}
        self.last_messages: list[str] = []  # PrintJSON-style log (cap 200)
        self.death_count: int = 0  # M4 DeathLink: how many times Mario died
        # AP-classification moon coloring. Populated when AP's LocationInfo
        # reply lands (scouted at Connected) and replayed to the Switch on
        # every (re)connect via SwitchServer._on_hello. Key is SMO's
        # ShineInfo::shineId int; value is the palette index for
        # rs::setStageShineAnimFrame.
        self.shine_palette: dict[int, int] = {}
        # Dedup keyset for checked_locations. Snapshot replays emit synthetic
        # checks for everything in the save; without dedup the list would
        # grow on every reconnect. Key is the full ItemRef identity (canonical
        # OR raw fields, whichever the producer filled in).
        self._checked_keys: set[tuple] = set()
        # Snapshot accumulator. begin_snapshot resets it; chunks append; end
        # returns the raw entries for downstream dispatch. Single in-flight
        # snapshot — the TCP stream is serial, so no need for epoch keying.
        self._pending_snapshot_active: bool = False
        self._pending_snapshot_entries: list[dict] = []
        self._pending_snapshot_save_slot: int | None = None
        self.last_snapshot_save_slot: int | None = None

    # ---------- AP <-> internal ----------

    def set_ap_conn(self, conn: str) -> None:
        with self._lock:
            self.ap_conn = conn

    def set_switch_conn(self, conn: str) -> None:
        with self._lock:
            self.switch_conn = conn

    def add_received_item(self, evt: ItemEvent) -> None:
        with self._lock:
            self.received_items.append(evt)
            if evt.item.kind == "capture" and evt.item.cap:
                self.captures_unlocked.add(evt.item.cap)
            elif evt.item.kind == "kingdom" and evt.item.kingdom:
                self.kingdoms_unlocked.add(evt.item.kingdom)
            elif evt.item.kind == "moon" and evt.item.kingdom:
                self.moons_received_by_kingdom[evt.item.kingdom] = (
                    self.moons_received_by_kingdom.get(evt.item.kingdom, 0) + 1
                )

    def add_checked_location(self, evt: CheckEvent) -> bool:
        """Append a CheckEvent. Returns True if newly added, False if duplicate.

        Dedup uses the full ItemRef identity (canonical + raw fields). Snapshot
        replay paths rely on this — they emit synthetic checks for every owned
        shine on every reconnect, and we don't want `checked_locations` to grow
        unboundedly.
        """
        key = (
            evt.item.kind,
            evt.item.kingdom, evt.item.shine_id, evt.item.cap,
            evt.item.stage_name, evt.item.object_id, evt.item.shine_uid,
            evt.item.hack_name,
        )
        with self._lock:
            if key in self._checked_keys:
                return False
            self._checked_keys.add(key)
            self.checked_locations.append(evt)
            if evt.item.kind == "moon" and evt.item.kingdom:
                self.moons_checked_by_kingdom[evt.item.kingdom] = (
                    self.moons_checked_by_kingdom.get(evt.item.kingdom, 0) + 1
                )
            return True

    def add_log(self, text: str) -> None:
        with self._lock:
            self.last_messages.append(text)
            if len(self.last_messages) > 200:
                self.last_messages = self.last_messages[-200:]

    def bump_death_count(self) -> None:
        with self._lock:
            self.death_count += 1

    def set_shine_palette(self, entries: dict[int, int]) -> None:
        """Replace the (shine_uid -> palette) table with the given entries.

        Called once per AP `LocationInfo` reply. Non-zero values overwrite
        existing entries; zero is treated as a "no override" sentinel and
        also stored so reconnect-replay reflects the same intent.
        """
        with self._lock:
            self.shine_palette = dict(entries)

    def all_shine_palette(self) -> dict[int, int]:
        with self._lock:
            return dict(self.shine_palette)

    # ---------- Snapshot for web tracker / replay ----------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "ap_conn": self.ap_conn,
                "switch_conn": self.switch_conn,
                "seed": self.seed,
                "slot": self.slot,
                "received_count": len(self.received_items),
                "checked_count": len(self.checked_locations),
                "death_count": self.death_count,
                "captures_unlocked": sorted(self.captures_unlocked),
                "kingdoms_unlocked": sorted(self.kingdoms_unlocked),
                "moons_received_by_kingdom": dict(self.moons_received_by_kingdom),
                "moons_checked_by_kingdom": dict(self.moons_checked_by_kingdom),
                "recent_items": [
                    {
                        "kind": e.item.kind,
                        "kingdom": e.item.kingdom,
                        "shine_id": e.item.shine_id,
                        "cap": e.item.cap,
                        "name": e.item.name,
                        "from": e.sender,
                        "at": e.received_at,
                    }
                    for e in self.received_items[-50:]
                ],
                "recent_messages": list(self.last_messages[-50:]),
            }

    def all_received_items(self) -> list[ItemEvent]:
        with self._lock:
            return list(self.received_items)

    def all_checked_locations(self) -> list[CheckEvent]:
        with self._lock:
            return list(self.checked_locations)

    # ---------- Snapshot accumulator (M4.5) ----------

    def begin_snapshot(self, save_slot: int | None) -> None:
        """Open a fresh snapshot accumulator, discarding any in-flight one.

        State is per-connection: the TCP stream is single-Switch, single-thread
        on the bridge end, so begin/chunk/end always arrive in order. If the
        Switch reconnects mid-snapshot the connection drops first and the new
        connection starts a fresh snapshot anyway.
        """
        with self._lock:
            self._pending_snapshot_active = True
            self._pending_snapshot_entries = []
            self._pending_snapshot_save_slot = save_slot

    def add_snapshot_chunk_shines(self, stage_name: str, shines: list[dict]) -> None:
        """Append per-stage shine entries from a StateChunkMsg."""
        with self._lock:
            if not self._pending_snapshot_active:
                return
            for s in shines:
                if not isinstance(s, dict):
                    continue
                self._pending_snapshot_entries.append({
                    "kind": "moon",
                    "stage_name": stage_name,
                    "object_id": s.get("object_id"),
                    "shine_uid": s.get("shine_uid"),
                })

    def add_snapshot_chunk_meta(
        self,
        captures: list[str] | None,
        goal_reached: bool | None,
    ) -> None:
        """Append cross-stage `_meta` chunk entries (captures + goal)."""
        with self._lock:
            if not self._pending_snapshot_active:
                return
            for hack in (captures or []):
                if isinstance(hack, str) and hack:
                    self._pending_snapshot_entries.append({
                        "kind": "capture",
                        "hack_name": hack,
                    })
            # goal_reached is dispatched separately by switch_server, not
            # accumulated as an entry. Stash it on a separate flag for the
            # caller to read on end_snapshot.
            if goal_reached is not None:
                self._pending_snapshot_goal = bool(goal_reached)

    def end_snapshot(self) -> tuple[list[dict], bool]:
        """Finalize: returns (entries, goal_reached_flag) and resets buffer."""
        with self._lock:
            entries = list(self._pending_snapshot_entries)
            goal = bool(getattr(self, "_pending_snapshot_goal", False))
            self.last_snapshot_save_slot = self._pending_snapshot_save_slot
            self._pending_snapshot_active = False
            self._pending_snapshot_entries = []
            self._pending_snapshot_save_slot = None
            self._pending_snapshot_goal = False
            return entries, goal
