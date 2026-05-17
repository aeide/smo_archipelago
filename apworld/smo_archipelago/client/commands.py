"""Pure command parsing for SMOClient's `/`-commands.

`parse_command()` is the load-bearing function — pure input string ->
ParseResult dataclass. The Kivy GUI's ClientCommandProcessor (in
context.py) calls each `_cmd_*` method, which delegates to this parser
so wire fidelity matches what the (deleted) stdin REPL produced.

Before Phase 5 this file owned an asyncio stdin reader thread that
drove the same parser. After the merge, the Kivy command bar is the
input surface and the parser stays — only the I/O loop went away.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .datapackage import ClassifiedItem, DataPackage
from .maps import CaptureMap
from .protocol import ItemKind, ItemMsg, MoonLabelMsg
from .state import BridgeState

log = logging.getLogger(__name__)


HELP_TEXT = """\
SMO Client commands (type with leading /):
  /grant <item> [--class=<C>]       send a kingdom-specific moon item.
                                    Examples:
                                      /grant Cascade Kingdom Power Moon
                                      /grant Cascade Kingdom Multi-Moon --class=progression
                                    --class controls classification on the wire
                                    (progression|useful|trap|filler; default filler).
                                    Drives M-color shine palette in-game.
  /capture <name> [--class=<C>]     send a capture-unlock item.   e.g. /capture Goomba
                                    Auto-resolves cap -> hack_name via CaptureMap so the
                                    wire payload matches a real AP-issued capture.
  /kingdom <name> [--class=<C>]     send a kingdom-unlock item.   e.g. /kingdom Sand
  /label <text>                     send a MoonLabelMsg directly (Channel A visual
                                    test). seq is auto-assigned high (999999) so it
                                    beats any pending bridge-issued label.
  /smo_status                       show client-side tracker state
  /inject_deathlink [src] [cause]
                                    bypass AP entirely and synthesize a KillMsg
                                    straight to the Switch (debug)
"""

_VALID_CLASSIFICATIONS = ("progression", "useful", "trap", "filler")


@dataclass
class ParseResult:
    """Outcome of parsing a single command line.

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
            return ParseResult(info="status unavailable (no client state attached)")
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
            return ParseResult(
                error="usage: grant <item name> [--class=progression|useful|trap|filler]"
            )
        name, classification, err = _extract_class_flag(arg)
        if err:
            return ParseResult(error=err)
        ci = dp.classify_item(name)
        if ci.kind != ItemKind.MOON:
            return ParseResult(error=(
                f"'{name}' did not classify as a moon (got {ci.kind.value!r}); "
                f"use `capture` or `kingdom` for those"))
        return ParseResult(item=_classified_to_itemmsg(ci, name, classification))

    if cmd == "capture":
        if not arg:
            return ParseResult(error="usage: capture <name>")
        name, classification, err = _extract_class_flag(arg)
        if err:
            return ParseResult(error=err)
        ci = ClassifiedItem(kind=ItemKind.CAPTURE, name=name, cap=name)
        # Resolve cap -> hack_name via the same CaptureMap the AP receive
        # path uses, so command-bar injection produces the same wire
        # payload as a real AP-issued capture. Identity-passthrough on miss.
        hack = None
        if capture_map is not None:
            hack = capture_map.cap_to_hack(name)
        msg = _classified_to_itemmsg(ci, name, classification)
        msg.hack_name = hack
        return ParseResult(item=msg)

    if cmd == "kingdom":
        if not arg:
            return ParseResult(error="usage: kingdom <name>")
        name, classification, err = _extract_class_flag(arg)
        if err:
            return ParseResult(error=err)
        ci = ClassifiedItem(kind=ItemKind.KINGDOM, name=name, kingdom=name)
        return ParseResult(item=_classified_to_itemmsg(ci, name, classification))

    if cmd == "label":
        if not arg:
            return ParseResult(error="usage: label <text>")
        # 999999 sits well above any sane bridge-issued seq; useful for
        # standalone visual tests where you want to override a stale
        # pending label.
        return ParseResult(label=MoonLabelMsg(text=arg, seq=999999))

    return ParseResult(error=f"unknown command: {cmd!r}; type `help`")


def _extract_class_flag(arg: str) -> tuple[str, str, str | None]:
    """Strip `--class=<value>` from `arg` and return (name, classification, error).

    Default classification is "filler". Position-independent: the flag can
    appear at any whitespace boundary inside the name and is stripped out.
    """
    classification = "filler"
    tokens = arg.split()
    kept: list[str] = []
    for tok in tokens:
        if tok.startswith("--class="):
            value = tok[len("--class="):].strip().lower()
            if value not in _VALID_CLASSIFICATIONS:
                return arg, classification, (
                    f"--class={value!r} not one of {_VALID_CLASSIFICATIONS}"
                )
            classification = value
        else:
            kept.append(tok)
    name = " ".join(kept).strip()
    if not name:
        return arg, classification, "item name is empty after stripping flags"
    return name, classification, None


def _classified_to_itemmsg(
    ci: ClassifiedItem, raw_name: str, classification: str = "filler",
) -> ItemMsg:
    ref = ci.to_ref()
    # ItemRef.name is only populated for OTHER kind; for grant/capture/kingdom
    # preserve the raw user input so the mod logs it clearly.
    return ItemMsg(
        kind=ref.kind,
        kingdom=ref.kingdom,
        shine_id=ref.shine_id,
        cap=ref.cap,
        name=ref.name or raw_name,
        from_="repl",
        classification=classification,
    )
