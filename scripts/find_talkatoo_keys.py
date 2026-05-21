"""Search MSBT archives for Talkatoo (HintNpc) message keys.

Iterates SystemMessage.szs, StageMessage.szs, LayoutMessage.szs from the
romfs cache, extracts each MSBT inside, and prints any label that mentions
Hint / Parrot / Talkatoo or that lives in a file with one of those tokens
in its name. Output goes to stdout — pipe to a file if you want it saved.

Run via the extract venv:
    scripts/.extract-venv/Scripts/python.exe scripts/find_talkatoo_keys.py

Prereq: scripts/extract_shine_map.py has been run once so the venv +
.romfs-cache/ exist.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

try:
    import oead
except ImportError:
    sys.exit("ERROR: oead missing. Run scripts/extract_shine_map.py first to bootstrap the venv.")

REPO_ROOT = Path(__file__).resolve().parent.parent
ROMFS = REPO_ROOT / ".romfs-cache"
NEEDLES = ("hintbird", "hint_bird", "moonhintbird", "moonshinehintbird", "shinehintbird", "hintshine", "hintmoonshine")


def read_msbt_labels(data: bytes) -> list[tuple[str, str]]:
    """Return (label, value) pairs from a raw MSBT byte stream.

    Lightweight reader: skip headers, locate LBL1 + TXT2 sections, pair them
    up by index. SMO uses 0x0E/0x0F control codes which we skip past when
    converting UTF-16LE → ASCII-printable.
    """
    if data[:8] != b"MsgStdBn":
        return []
    # Endianness at +8: 0xFEFF = LE, 0xFFFE = BE.
    is_le = data[8:10] == b"\xff\xfe"
    if not is_le:
        # SMO is little-endian; bail otherwise rather than guess.
        return []

    sections = {}
    off = 0x20  # past MSBT header
    while off + 0x10 <= len(data):
        magic = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        if magic in (b"LBL1", b"TXT2", b"ATR1", b"NLI1", b"TSY1"):
            sections[magic] = (off + 0x10, size)
        off += 0x10 + size
        off = (off + 0xF) & ~0xF  # 16-byte align

    if b"LBL1" not in sections or b"TXT2" not in sections:
        return []

    # ---- parse LBL1 ----
    lbl_off, _ = sections[b"LBL1"]
    n_groups = struct.unpack_from("<I", data, lbl_off)[0]
    label_offsets = []
    p = lbl_off + 4
    for _ in range(n_groups):
        count, table_off = struct.unpack_from("<II", data, p)
        p += 8
        q = lbl_off + table_off
        for _ in range(count):
            name_len = data[q]; q += 1
            name = data[q:q + name_len].decode("ascii", errors="replace")
            q += name_len
            idx = struct.unpack_from("<I", data, q)[0]
            q += 4
            label_offsets.append((idx, name))

    # ---- parse TXT2 ----
    txt_off, _ = sections[b"TXT2"]
    n_entries = struct.unpack_from("<I", data, txt_off)[0]
    text_offsets = []
    for i in range(n_entries):
        off2 = struct.unpack_from("<I", data, txt_off + 4 + i * 4)[0]
        text_offsets.append(txt_off + off2)
    # End offset for each entry is the start of the next, or section end
    text_offsets.append(sections[b"TXT2"][0] + sections[b"TXT2"][1])

    results: list[tuple[str, str]] = []
    for idx, name in label_offsets:
        if idx >= n_entries:
            continue
        start = text_offsets[idx]
        end = text_offsets[idx + 1]
        raw = data[start:end]
        # Strip UTF-16LE, dropping control codes (0x0E/0x0F xx xx ...).
        text = []
        i = 0
        while i + 1 < len(raw):
            ch = raw[i] | (raw[i + 1] << 8)
            if ch == 0:
                break
            if ch == 0x0E or ch == 0x0F:
                # control code: tag (u16), kind (u16), [payload_len (u16) + payload]
                if i + 6 < len(raw):
                    plen = raw[i + 4] | (raw[i + 5] << 8)
                    i += 6 + plen
                    i = (i + 1) & ~1
                    continue
                break
            if 0x20 <= ch < 0x7F or ch in (0x0A, 0x09):
                text.append(chr(ch))
            else:
                text.append("?")
            i += 2
        results.append((name, "".join(text)))
    return results


def walk_archive(name: str, data: bytes) -> None:
    """Decompress a Yaz0 SARC and search every MSBT inside."""
    if data[:4] == b"Yaz0":
        data = oead.yaz0.decompress(data)
    if data[:4] != b"SARC":
        return
    sarc = oead.Sarc(data)
    archive_lower = name.lower()
    for f in sarc.get_files():
        fname = f.name
        if not fname.lower().endswith(".msbt"):
            continue
        labels = read_msbt_labels(bytes(f.data))
        if not labels:
            continue
        # Two filters: filename hits or label hits
        file_hit = any(n in fname.lower() for n in NEEDLES) or any(n in archive_lower for n in NEEDLES)
        for label, text in labels:
            label_hit = any(n in label.lower() for n in NEEDLES)
            if file_hit or label_hit:
                clean = text.replace("\n", "\\n")
                print(f"[{name}/{fname}] {label} = {clean[:200]}")


def main() -> int:
    if not ROMFS.exists():
        sys.exit(f"romfs cache missing: {ROMFS}")
    msg_dir = ROMFS / "LocalizedData" / "USen" / "MessageData"
    for szs in sorted(msg_dir.glob("*.szs")):
        walk_archive(szs.stem, szs.read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
