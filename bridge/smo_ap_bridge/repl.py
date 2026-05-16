"""Interactive REPL for the bridge — inject items directly to the connected Switch.

Designed for fast M6 playtest iteration: no AP server required, no save-load
gymnastics. Boot the bridge with `--repl`, launch the mod, then type:

    grant Cascade Kingdom Power Moon
    grant Cascade Kingdom Multi-Moon
    capture Goomba
    kingdom Sand
    status
    help / quit

Commands route through the same DataPackage.classify_item path AP-issued
items use, so the wire format is identical. The sender field is set to
"repl" so mod-side log lines read `from=repl` and you can tell them apart
from real AP grants.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from dataclasses import dataclass
from typing import Awaitable, Callable

from .datapackage import ClassifiedItem, DataPackage
from .maps import CaptureMap
from .protocol import ItemKind, ItemMsg, MoonLabelMsg
from .state import BridgeState, ItemEvent

log = logging.getLogger(__name__)


HELP_TEXT = """\
Commands:
  grant <item name>      send a kingdom-specific moon item.
                         Examples:
                           grant Cascade Kingdom Power Moon
                           grant Cascade Kingdom Multi-Moon
  capture <name>         send a capture-unlock item.   e.g. capture Goomba
  kingdom <name>         send a kingdom-unlock item.   e.g. kingdom Sand
  label <text>           send a MoonLabelMsg directly (Channel A visual
                         test). seq is auto-assigned high (999999) so it
                         beats any pending bridge-generated label.
  status                 echo bridge-side tracker state
  help                   this message
  quit                   shut the bridge down
"""


@dataclass
class ParseResult:
    """Outcome of parsing a single REPL line.

    Exactly one (or none) of `item`, `label`, `info`, `error`, `quit` is set.
    """
    item: ItemMsg | None = None
    label: MoonLabelMsg | None = None
    info: str | None = None
    error: str | None = None
    quit: bool = False


def parse_command(
    line: str,
    dp: DataPackage,
    state: BridgeState | None = None,
    capture_map: CaptureMap | None = None,
) -> ParseResult:
    """Pure parser — line -> action. Unit-testable without I/O."""
    s = line.strip()
    if not s:
        return ParseResult()  # silent no-op
    parts = s.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("quit", "exit", "q"):
        return ParseResult(quit=True)
    if cmd in ("help", "?", "h"):
        return ParseResult(info=HELP_TEXT)
    if cmd == "status":
        if state is None:
            return ParseResult(info="status unavailable (no bridge state attached)")
        n_items = len(state.received_items)
        n_checks = len(state.checked_locations)
        n_caps = len(state.captures_unlocked)
        n_kings = len(state.kingdoms_unlocked)
        moons_by_k = ", ".join(
            f"{k}={v}" for k, v in sorted(state.moons_received_by_kingdom.items())
        ) or "(none)"
        last = ""
        if n_items > 0:
            evt = state.received_items[-1]
            last = (f"  last item: kind={evt.item.kind} kingdom={evt.item.kingdom!r}"
                    f" shine_id={evt.item.shine_id!r} cap={evt.item.cap!r}"
                    f" from={evt.sender!r}\n")
        return ParseResult(info=(
            f"received_items={n_items} (by kingdom: {moons_by_k})\n"
            f"checked_locations={n_checks}\n"
            f"captures_unlocked={n_caps}, kingdoms_unlocked={n_kings}\n"
            + last
        ))

    if cmd == "grant":
        if not arg:
            return ParseResult(error="usage: grant <item name>")
        ci = dp.classify_item(arg)
        if ci.kind != ItemKind.MOON:
            return ParseResult(error=(
                f"'{arg}' did not classify as a moon (got {ci.kind.value!r}); "
                f"use `capture` or `kingdom` for those"))
        return ParseResult(item=_classified_to_itemmsg(ci, arg))

    if cmd == "capture":
        if not arg:
            return ParseResult(error="usage: capture <name>")
        ci = ClassifiedItem(kind=ItemKind.CAPTURE, name=arg, cap=arg)
        # M6 phase B: resolve cap -> hack_name via the same CaptureMap the
        # ap_client path uses, so REPL injection has the same wire payload
        # as a real AP-issued capture. Identity-passthrough if no map entry.
        hack = None
        if capture_map is not None:
            hack = capture_map.cap_to_hack(arg)
        msg = _classified_to_itemmsg(ci, arg)
        msg.hack_name = hack
        return ParseResult(item=msg)

    if cmd == "kingdom":
        if not arg:
            return ParseResult(error="usage: kingdom <name>")
        ci = ClassifiedItem(kind=ItemKind.KINGDOM, name=arg, kingdom=arg)
        return ParseResult(item=_classified_to_itemmsg(ci, arg))

    if cmd == "label":
        if not arg:
            return ParseResult(error="usage: label <text>")
        # 999999 sits well above any sane bridge-issued seq; useful for
        # standalone visual tests where you want to override a stale
        # pending label.
        return ParseResult(label=MoonLabelMsg(text=arg, seq=999999))

    return ParseResult(error=f"unknown command: {cmd!r}; type `help`")


def _classified_to_itemmsg(ci: ClassifiedItem, raw_name: str) -> ItemMsg:
    ref = ci.to_ref()
    # ItemRef.name is only populated for OTHER kind; for grant/capture/kingdom
    # preserve the raw user input so the mod logs it clearly.
    return ItemMsg(
        kind=ref.kind,
        kingdom=ref.kingdom,
        shine_id=ref.shine_id,
        cap=ref.cap,
        slot=ref.slot,
        name=ref.name or raw_name,
        from_="repl",
    )


# ---- async I/O loop ----

SendItem = Callable[[ItemMsg], Awaitable[None]]
SendMoonLabel = Callable[[MoonLabelMsg], Awaitable[None]]


async def run_repl(
    send_item: SendItem,
    dp: DataPackage,
    state: BridgeState,
    shutdown_event: asyncio.Event,
    capture_map: CaptureMap | None = None,
    send_moon_label: SendMoonLabel | None = None,
) -> None:
    """Read stdin via a daemon thread; dispatch commands on the asyncio loop.

    asyncio on Windows can't add_reader for stdin, so a dedicated daemon
    thread runs blocking input() and posts lines through run_coroutine_
    threadsafe. The thread exits on process shutdown.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def reader() -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except Exception:
                line = ""
            if not line:  # EOF (Ctrl-Z on Windows, Ctrl-D on POSIX, or stdin closed)
                asyncio.run_coroutine_threadsafe(queue.put("__EOF__"), loop)
                return
            asyncio.run_coroutine_threadsafe(queue.put(line), loop)

    threading.Thread(target=reader, name="bridge-repl-stdin", daemon=True).start()

    log.info("REPL ready — type `help` for commands")
    _print_prompt()
    while not shutdown_event.is_set():
        try:
            line = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        if line == "__EOF__":
            log.info("REPL: stdin closed; shutting down")
            shutdown_event.set()
            return

        result = parse_command(line, dp, state, capture_map)
        if result.error:
            print(f"  err: {result.error}", flush=True)
        if result.info:
            print(result.info, end="" if result.info.endswith("\n") else "\n", flush=True)
        if result.item is not None:
            # Mirror what ap_client.py does on ReceivedItems: persist into
            # BridgeState so reconnect-replay survives. sender="repl" makes
            # this distinguishable from real AP-sourced items.
            from .protocol import ItemRef
            ref = ItemRef(
                kind=result.item.kind,
                kingdom=result.item.kingdom,
                shine_id=result.item.shine_id,
                cap=result.item.cap,
                slot=result.item.slot,
                name=result.item.name,
                hack_name=result.item.hack_name,
            )
            state.add_received_item(ItemEvent(item=ref, sender="repl"))
            try:
                await send_item(result.item)
                print(f"  -> sent {result.item.kind} kingdom={result.item.kingdom!r} "
                      f"shine_id={result.item.shine_id!r} cap={result.item.cap!r}",
                      flush=True)
            except Exception as e:
                print(f"  send failed: {e!r}", flush=True)
        if result.label is not None:
            if send_moon_label is None:
                print("  err: bridge wasn't started with a moon-label sender "
                      "(missing wiring in __main__)", flush=True)
            else:
                try:
                    await send_moon_label(result.label)
                    print(f"  -> sent moon_label text={result.label.text!r} "
                          f"seq={result.label.seq}", flush=True)
                except Exception as e:
                    print(f"  send_moon_label failed: {e!r}", flush=True)
        if result.quit:
            shutdown_event.set()
            return
        _print_prompt()


def _print_prompt() -> None:
    sys.stdout.write("smo-ap-bridge> ")
    sys.stdout.flush()
