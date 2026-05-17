"""Asyncio TCP server for the Switch.

One Switch connection at a time (extras are rejected). On HELLO we replay the
full received-items history and the set of locations already checked, so the
Switch module always re-applies state idempotently after a reboot.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from . import protocol
from .protocol import (
    ApStateMsg,
    CheckedReplayMsg,
    ErrMsg,
    HelloAckMsg,
    ItemMsg,
    KillMsg,
    MoonLabelMsg,
    PongMsg,
    ShineScoutsMsg,
)
from .state import BridgeState, CheckEvent, ItemEvent

# Max scout entries per ShineScoutsMsg. Each entry is ~25 bytes wire; 200
# stays well under MAX_LINE_BYTES (8 KiB) even with TOML-driven larger
# palette ints. Switch merges chunks by shine_uid overwrite, so order and
# count are immaterial.
_SCOUT_CHUNK_SIZE = 200

log = logging.getLogger(__name__)


CheckHandler = Callable[[dict], Awaitable["int | None"]]  # returns AP loc_id or None
GoalHandler = Callable[[], Awaitable[None]]
DeathHandler = Callable[[int], Awaitable[None]]
LabelComposer = Callable[[int], "str | None"]              # loc_id -> label text
SwitchReadyHandler = Callable[[], Awaitable[None]]         # fired post-HELLO


class SwitchServer:
    def __init__(
        self,
        host: str,
        port: int,
        state: BridgeState,
        on_check: CheckHandler,
        on_goal: GoalHandler,
        on_death: DeathHandler | None = None,
        deathlink_enabled: bool = False,
        compose_moon_label: LabelComposer | None = None,
        on_switch_ready: SwitchReadyHandler | None = None,
    ):
        self._host = host
        self._port = port
        self._state = state
        self._on_check = on_check
        self._on_goal = on_goal
        self._on_death = on_death
        self._deathlink_enabled = deathlink_enabled
        self._compose_label = compose_moon_label
        self._on_switch_ready = on_switch_ready
        self._writer: asyncio.StreamWriter | None = None
        self._writer_lock = asyncio.Lock()
        self._server: asyncio.AbstractServer | None = None

    def is_connected(self) -> bool:
        """True iff a Switch is currently attached and the socket is open.
        Used by SMOContext to gate the AP dial on Switch presence."""
        w = self._writer
        return w is not None and not w.is_closing()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        log.info("switch server listening on %s", addrs)

    async def stop(self) -> None:
        # Close the active Switch connection FIRST. Python 3.12+'s
        # Server.wait_closed() waits for both the listener and every active
        # client task to finish; _handle_client is parked in reader.read()
        # so the connection task never returns on its own — the listener
        # closing doesn't kick connected clients. Without this teardown,
        # a clean window-close hangs forever whenever the Switch (or
        # Ryujinx) is still connected.
        async with self._writer_lock:
            w = self._writer
            self._writer = None
        if w is not None:
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

    # ---- broadcast: bridge -> switch ----

    async def send_item(self, item: ItemMsg) -> None:
        await self._send(item)

    async def send_print(self, text: str) -> None:
        await self._send(protocol.PrintMsg(text=text))

    async def send_ap_state(self, conn: str) -> None:
        await self._send(ApStateMsg(conn=conn))

    async def send_kill(self, kill: KillMsg) -> None:
        await self._send(kill)

    async def send_moon_label(self, label: MoonLabelMsg) -> None:
        await self._send(label)

    async def send_shine_scouts(self, palette: dict[int, int]) -> None:
        """Push (shine_uid -> palette) to the Switch, chunked.

        Caller is responsible for filtering zero-palette entries if it
        considers them noise; we send everything so the Switch can
        explicitly clear a previously-set uid by writing 0.
        """
        if not palette:
            return
        items = list(palette.items())
        for i in range(0, len(items), _SCOUT_CHUNK_SIZE):
            chunk = items[i : i + _SCOUT_CHUNK_SIZE]
            await self._send(ShineScoutsMsg(entries=[
                {"shine_uid": uid, "palette": p} for uid, p in chunk
            ]))

    async def _send(self, msg: Any) -> None:
        async with self._writer_lock:
            w = self._writer
            if w is None or w.is_closing():
                return
            try:
                w.write(protocol.encode(msg))
                await w.drain()
            except (ConnectionResetError, BrokenPipeError):
                log.warning("switch write failed; closing")
                try:
                    w.close()
                except Exception:
                    pass
                self._writer = None

    # ---- per-connection handler ----

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if self._writer is not None and not self._writer.is_closing():
            log.warning("rejecting extra Switch connection from %s (one already active)", peer)
            try:
                writer.write(protocol.encode(ErrMsg(code="busy", ctx="connect")))
                await writer.drain()
            finally:
                writer.close()
            return

        log.info("switch connected from %s", peer)
        self._writer = writer
        self._state.set_switch_conn("connecting")

        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    log.info("switch disconnected (EOF)")
                    break
                buffer.extend(chunk)
                for line in protocol.iter_lines(buffer):
                    try:
                        msg = protocol.decode(line)
                        await self._dispatch(msg)
                    except Exception:
                        log.exception("error handling message: %r", line[:200])
                        await self._send(ErrMsg(code="bad_message", ctx="rx"))
        except (ConnectionResetError, BrokenPipeError):
            log.info("switch connection reset")
        finally:
            self._state.set_switch_conn("disconnected")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if self._writer is writer:
                self._writer = None

    async def _dispatch(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "hello":
            await self._on_hello(msg)
        elif t == "check":
            await self._dispatch_check(msg)
        elif t == "goal":
            log.info("switch reported goal completion")
            await self._on_goal()
        elif t == "death":
            ts_ms = int(msg.get("ts_ms") or 0)
            log.info("switch reported death ts_ms=%d", ts_ms)
            if self._on_death is not None:
                await self._on_death(ts_ms)
        elif t == "status":
            log.debug("switch status: %s", msg)
        elif t == "ping":
            await self._send(PongMsg(ts_ms=msg.get("ts_ms", int(time.time() * 1000))))
        elif t == "log":
            self._state.add_log(f"[switch:{msg.get('level', 'info')}] {msg.get('msg', '')}")
        elif t == "state_begin":
            self._state.begin_snapshot(save_slot=msg.get("save_slot"))
            log.info("snapshot begin: mod_ver=%s save_slot=%s",
                     msg.get("mod_ver"), msg.get("save_slot"))
        elif t == "state_chunk":
            stage = msg.get("stage_name", "")
            if stage == "_meta":
                self._state.add_snapshot_chunk_meta(
                    captures=msg.get("captures"),
                    goal_reached=msg.get("goal_reached"),
                )
            else:
                self._state.add_snapshot_chunk_shines(stage, msg.get("shines") or [])
        elif t == "state_end":
            await self._on_state_end()
        else:
            log.warning("unknown message type from Switch: %s", t)
            await self._send(ErrMsg(code="unknown_kind", ctx=str(t)))

    async def _dispatch_check(self, msg: dict) -> None:
        """Forward a check (live or snapshot-derived) to AP and record locally.

        BridgeState.add_checked_location dedupes via the full ItemRef identity,
        so snapshot replays don't grow the list (or trigger spurious tracker
        increments) on every reconnect.

        M6 phase A.5: if the Switch sent a non-zero `seq` and AP returned a
        resolved location_id and Channel A is wired, synthesize a
        MoonLabelMsg in the same TCP push (Nagle-batched) so it arrives
        before the cutscene fires.
        """
        loc_id = await self._on_check(msg)
        seq = msg.get("seq") or 0
        if loc_id is not None and seq and self._compose_label is not None:
            try:
                text = self._compose_label(loc_id)
            except Exception:
                log.exception("compose_moon_label failed for loc_id=%s seq=%s", loc_id, seq)
                text = None
            if text:
                await self.send_moon_label(MoonLabelMsg(text=text, seq=seq))
        self._state.add_checked_location(
            CheckEvent(item=protocol.ItemRef(
                kind=msg.get("kind", "moon"),
                kingdom=msg.get("kingdom"),
                shine_id=msg.get("shine_id"),
                cap=msg.get("cap"),
                stage_name=msg.get("stage_name"),
                object_id=msg.get("object_id"),
                shine_uid=msg.get("shine_uid"),
                hack_name=msg.get("hack_name"),
            ))
        )

    async def _on_state_end(self) -> None:
        entries, goal_reached = self._state.end_snapshot()
        log.info("snapshot end: %d entries goal=%s", len(entries), goal_reached)
        for entry in entries:
            synthetic = {"t": "check", **entry}
            await self._dispatch_check(synthetic)
        if goal_reached:
            log.info("snapshot reports goal already reached; forwarding")
            await self._on_goal()

    async def _on_hello(self, msg: dict) -> None:
        log.info("switch HELLO: mod=%s smo=%s", msg.get("mod_ver"), msg.get("smo_ver"))
        await self._send(HelloAckMsg(
            ok=True,
            seed=self._state.seed,
            slot=self._state.slot,
            cap_table_hash=msg.get("cap_table_hash", ""),
            deathlink_enabled=self._deathlink_enabled,
        ))
        self._state.set_switch_conn("ready")

        # Replay snapshots so the Switch can re-apply state idempotently.
        replay_ids = [evt.item for evt in self._state.all_checked_locations()]
        await self._send(CheckedReplayMsg(ids=replay_ids))
        for evt in self._state.all_received_items():
            await self._send(ItemMsg(
                kind=evt.item.kind,
                kingdom=evt.item.kingdom,
                shine_id=evt.item.shine_id,
                cap=evt.item.cap,
                name=evt.item.name,
                from_=evt.sender,
                # M6 phase B: hack_name was resolved bridge-side when the item
                # was first received; carry it through replay so the Switch
                # mod can grant the capture after reconnect without needing
                # bridge to re-resolve.
                hack_name=evt.item.hack_name,
                classification=evt.item.classification,
            ))

        # Replay the shine-palette scout map so a Switch reconnect after the
        # bridge has already received LocationInfo doesn't lose colors.
        await self.send_shine_scouts(self._state.all_shine_palette())

        await self._send(ApStateMsg(conn=self._state.ap_conn))

        # Fire the post-HELLO callback last so SMOContext can promote a
        # pending AP-connect (SNI-style two-stage gate): the user clicked
        # Connect earlier but the AP dial was deferred until the Switch
        # was up. Sending the HelloAck/replay first means the new AP
        # connection has already had its state pushed when it lands.
        if self._on_switch_ready is not None:
            try:
                await self._on_switch_ready()
            except Exception:
                log.exception("on_switch_ready callback failed")
