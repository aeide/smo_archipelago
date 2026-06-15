"""Generate switch-mod/src/ap/capture_table.h from apworld/data/items.json.

Run after pulling new apworld data so the Switch's bit-index assignments
stay in sync with the bridge's classification.

When apworld/smo_archipelago/client/data/capture_map.json is also present
(extracted by scripts/extract_shine_map.py from the user's local NSP dump),
emits a second parallel `kCaptureHackNames` array so the Switch-side gate
can look up by SMO-internal hack_name (e.g. "TRex", "Wanwan") rather than
the apworld English name (e.g. "T-Rex", "Chain Chomp"). PlayerHackKeeper::
getCurrentHackName returns the hack_name, so without this mapping the
M7 deny path fail-opens for every diverged cap. Identity passthrough for
the ~36 captures whose apworld name matches the hack_name 1:1.

Some apworld captures are a many-hack-names-to-one-cap collapse (Nintendo
ships Puzzle Part as separate Lake/Metro variants — GotogotonLake +
GotogotonCity — but the apworld randomizes them as a single "Puzzle Part"
item). The parallel kCaptureHackNames slot can only hold one of those; the
*other* variant is emitted in kCaptureHackAliases as (hack_name, bit) so
captureBitFor and reconcileCaptureDictionary can resolve both directions.

Usage:
    python scripts/sync_capture_table.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# Split part-captures. The in-game journal (and the extracted capture_map.json)
# names BOTH puzzle parts "Puzzle Part" and BOTH picture-match parts
# "Picture Match Part", each with a DISTINCT hack_name; capture_map.json
# therefore has NO key for the four split item names the apworld now ships.
# This MUST stay in sync with client/maps.py::VARIANT_CAP_HACK_OVERRIDE —
# without it the four variants fall through to identity and the Switch
# capture-gate fail-opens for them (the same class of bug that left every
# diverged capture ungated when capture_map.json wasn't found at all).
VARIANT_CAP_HACK_OVERRIDE: dict[str, str] = {
    "Puzzle Part (Lake Kingdom)": "GotogotonLake",
    "Puzzle Part (Metro Kingdom)": "GotogotonCity",
    "Picture Match Part (Goomba)": "FukuwaraiFacePartsKuribo",
    "Picture Match Part (Mario)": "FukuwaraiFacePartsMario",
}


def _user_data_dir() -> Path:
    """Per-user data dir where the setup wizard's extractor writes the maps.

    Mirrors client/setup_state.py::_user_data_dir so a plain
    `python scripts/sync_capture_table.py` finds the SAME capture_map.json
    the running SMOClient loads. (Previously this script only looked at the
    in-repo client/data/ — which release/dev checkouts don't populate
    because the maps are Nintendo IP — so the build loop silently emitted an
    identity hack-name table and the capture gate fail-opened. 2026-06-14.)
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "SMOArchipelago" / "data"
    return Path.home() / ".local" / "share" / "SMOArchipelago" / "data"


def _resolve_capture_map(repo_root: Path) -> Path:
    """First existing capture_map.json, search order matching the client:
      1. %APPDATA%/SMOArchipelago/data/ (or XDG) — wizard extractor output
      2. legacy in-repo apworld/smo_archipelago/client/data/ (dev-only)
    Returns the %APPDATA% path even when absent so the --help/default text
    and the "MISSING" diagnostic point at the canonical location.
    """
    wizard = _user_data_dir() / "capture_map.json"
    if wizard.exists():
        return wizard
    legacy = (
        repo_root / "apworld" / "smo_archipelago" / "client" / "data"
        / "capture_map.json"
    )
    if legacy.exists():
        return legacy
    return wizard


def main(argv: list[str] | None = None) -> int:
    # Defaults are computed off this script's location, matching the dev
    # source-checkout layout. When invoked from the wizard inside AP's
    # frozen Launcher the bundled apworld layout doesn't match those
    # defaults (items.json is at <bundled>/data/ rather than
    # <bundled>/apworld/smo_archipelago/data/, switch_mod has an
    # underscore not a hyphen, capture_map.json lives in %APPDATA%/...
    # /data/ where the extractor wrote it). The wizard passes explicit
    # --items / --capture-map / --out so all three paths resolve.
    here = Path(__file__).resolve().parent.parent
    default_items = here / "apworld" / "smo_archipelago" / "data" / "items.json"
    default_out = here / "switch-mod" / "src" / "ap" / "capture_table.h"
    default_capture_map = _resolve_capture_map(here)

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--items", type=Path, default=default_items,
                    help=f"apworld items.json (default: {default_items})")
    ap.add_argument("--out", type=Path, default=default_out,
                    help=f"output capture_table.h (default: {default_out})")
    ap.add_argument("--capture-map", type=Path, default=default_capture_map,
                    help=f"optional capture_map.json for hack_name mapping "
                         f"(default: {default_capture_map})")
    args = ap.parse_args(argv)

    items_path = args.items
    out_path = args.out
    capture_map_path = args.capture_map

    if not items_path.exists():
        print(f"items.json not found at {items_path}", file=sys.stderr)
        return 1

    items = json.loads(items_path.read_text(encoding="utf-8"))
    captures = [it["name"] for it in items if "Capture" in (it.get("category") or [])]

    if not captures:
        print(f"no Capture-category items found in {items_path}", file=sys.stderr)
        return 1

    # Build cap -> [hack_names] lookup, preserving insertion order from
    # capture_map.json. Missing capture_map.json → identity per cap.
    cap_to_hacks: dict[str, list[str]] = {}
    if capture_map_path.exists():
        entries = json.loads(capture_map_path.read_text(encoding="utf-8"))
        for e in entries:
            if "cap" in e and "hack_name" in e:
                cap_to_hacks.setdefault(e["cap"], []).append(e["hack_name"])
    # Primary hack_name per apworld cap:
    #   1. VARIANT_CAP_HACK_OVERRIDE — the 4 split part-captures whose item
    #      names don't exist as capture_map.json keys (Nintendo journals both
    #      variants under one name). Must win over capture_map so the splits
    #      don't fall through to identity.
    #   2. first hack_name seen in capture_map.json (matches
    #      CaptureMap._reverse.setdefault on the Python side; keeps the
    #      wire-format hack_name field consistent across bridge ↔ Switch).
    #   3. identity (capture_map.json absent / cap not listed).
    def _primary_hack(name: str) -> str:
        if name in VARIANT_CAP_HACK_OVERRIDE:
            return VARIANT_CAP_HACK_OVERRIDE[name]
        if name in cap_to_hacks:
            return cap_to_hacks[name][0]
        return name

    hack_names = [_primary_hack(name) for name in captures]
    diverged = sum(1 for cap, hack in zip(captures, hack_names) if cap != hack)
    # Any extra hack_names past the first map to the same bit as their cap.
    # Without these aliases, captureBitFor() returns 0xff for the extras and
    # captureBlocked() fail-opens. Bug surfaced 2026-05-26 — user reported
    # Lake-Kingdom Puzzle Part capturing through without the AP item.
    # (With the P3 split each variant item maps 1:1 via the override, so the
    # collapsed-pair aliases are normally empty now; kept for any future
    # cap that legitimately shares one item name across multiple hacks.)
    aliases: list[tuple[str, int]] = []
    for i, name in enumerate(captures):
        if name in VARIANT_CAP_HACK_OVERRIDE:
            continue
        for extra in cap_to_hacks.get(name, [])[1:]:
            aliases.append((extra, i))

    cap_body  = "\n".join(f'    "{name}",' for name in captures)
    hack_body = "\n".join(f'    "{name}",' for name in hack_names)
    alias_body = "\n".join(f'    {{"{h}", {b}}},' for h, b in aliases)
    if not alias_body:
        # std::array can't be zero-sized in some toolchains via this syntax;
        # the consumer iterates so an empty list collapses naturally. Keep
        # the array shape consistent (size = aliases.size()) and emit nothing
        # in the body.
        alias_body = ""
    source_line = (
        "// Hack-name mapping source: apworld/smo_archipelago/client/data/capture_map.json"
        if capture_map_path.exists()
        else "// Hack-name mapping: identity (capture_map.json absent — run "
             "scripts/extract_shine_map.py to populate)"
    )
    alias_decl = (
        f"inline constexpr std::array<CaptureHackAlias, {len(aliases)}> "
        f"kCaptureHackAliases = {{{{\n{alias_body}\n}}}};\n"
        if aliases
        else f"inline constexpr std::array<CaptureHackAlias, 0> "
             f"kCaptureHackAliases = {{}};\n"
    )
    content = (
        "// AUTO-GENERATED by scripts/sync_capture_table.{ps1,py} — DO NOT EDIT.\n"
        "// Source: apworld/smo_archipelago/data/items.json (Capture category)\n"
        f"{source_line}\n"
        f"// Count: {len(captures)} captures, {diverged} diverged hack/cap "
        f"pairs, {len(aliases)} extra hack-name aliases\n"
        "\n"
        "#pragma once\n"
        "\n"
        "#include <array>\n"
        "#include <cstdint>\n"
        "#include <string_view>\n"
        "\n"
        "namespace smoap::game {\n"
        "\n"
        f"inline constexpr std::array<std::string_view, {len(captures)}> kCaptureNames = {{\n"
        f"{cap_body}\n"
        "};\n"
        "\n"
        "// Parallel to kCaptureNames — kCaptureHackNames[i] is the SMO-internal\n"
        "// hack_name (what PlayerHackKeeper::getCurrentHackName returns) for the\n"
        "// apworld capture at kCaptureNames[i]. captureBitFor() searches both so\n"
        "// the M7 deny path matches by hack_name and the M6-B apply path matches\n"
        "// by apworld cap. Identity entries (same value as kCaptureNames) are\n"
        "// harmless duplicates.\n"
        f"inline constexpr std::array<std::string_view, {len(captures)}> kCaptureHackNames = {{\n"
        f"{hack_body}\n"
        "};\n"
        "\n"
        "// Many-hack-to-one-cap aliases. Nintendo ships Puzzle Part and Picture\n"
        "// Match Part as two distinct hack_names each (Lake/Metro variants;\n"
        "// Mario/Goomba face parts) but the apworld collapses each pair into a\n"
        "// single randomizable item. The kCaptureHackNames slot only holds the\n"
        "// first variant; the rest live here. captureBitFor() and\n"
        "// reconcileCaptureDictionary() consult this so both variants block /\n"
        "// pre-populate correctly when the player owns the AP item.\n"
        "struct CaptureHackAlias {\n"
        "    std::string_view hack_name;\n"
        "    std::uint8_t bit;\n"
        "};\n"
        f"{alias_decl}"
        "\n"
        "}  // namespace smoap::game\n"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(captures)} capture names + {len(aliases)} aliases to "
          f"{out_path} ({diverged} diverged hack/cap pairs, "
          f"capture_map.json {'found' if capture_map_path.exists() else 'MISSING — using identity'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
