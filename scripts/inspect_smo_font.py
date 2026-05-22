#!/usr/bin/env python3
"""Dump per-font ASCII / Latin-1 / General-Punctuation coverage for the SMO 1.0.0
LocalizedData/USen FontData.szs.

Why this exists: SMO ships eight BFFNT fonts (TitleFont60, MessageFont38, ...)
in a yaz0-compressed SARC archive. Each font has a sparse glyph table — not
every ASCII character has a renderable glyph. When an in-game string contains
a missing codepoint, the speech bubble may render a blank or drop the line
tail at the missing glyph (observed for "..." vs "…" in Cappy bubbles).

This script parses every BFFNT's CMAP blocks and reports:
  - ASCII printable (0x20..0x7E) present / missing
  - Selected non-ASCII punctuation (smart quotes, dashes, ellipsis, ©, ™, °, ...)
  - Latin-1 supplement coverage
  - A summary of other supported codepoint blocks

The output drives switch-mod/src/util/MsgFontSafe.cpp's substitution table for
the speech-bubble + cutscene-label rendering path (MessageFont38.bffnt).

Re-run after a SMO version bump to confirm the table is still accurate.

Requires the romfs cache (`.romfs-cache/romfs/.../FontData.szs`) populated via
`scripts/extract_shine_map.py`. Uses oead (already a wizard prereq) for yaz0 +
SARC parsing — invoke from `scripts/.extract-venv/Scripts/python.exe`.
"""

from __future__ import annotations

import argparse
import struct
import sys
import unicodedata
from pathlib import Path


def parse_bffnt_cmap(buf: bytes) -> set[int]:
    """Return the set of codepoints that have a non-sentinel glyph index.

    BFFNT (Switch v4.x) format:
      Header: magic 'FFNT'(4) + BOM(2) + hdr_size(2) + version(4) + file_size(4)
              + num_blocks(2) + pad(2)  -- total 20 bytes
      Blocks: each starts with 4-char magic + u32 size. CMAP blocks contain:
              code_begin(u32) + code_end(u32) + mapping_method(u16) +
              pad(u16) + next_offset(u32), followed by mapping-method-specific
              payload.
              Methods: 0 = Direct (sequential glyph IDs),
                       1 = Table  (u16[code_end-code_begin+1] glyph IDs;
                                   0xFFFF means "no glyph"),
                       2 = Scan   (u16 count, then count * (u32 cp, u16 gid)).

    We assume little-endian (BOM = 0xFEFF, true for every SMO font we've
    inspected). Big-endian would be trivial to add but not needed.
    """
    if buf[:4] != b'FFNT':
        raise ValueError(f"unexpected magic {buf[:4]!r}")
    endian = '<'
    bom = struct.unpack_from(endian + 'H', buf, 4)[0]
    if bom != 0xFEFF:
        raise ValueError(f"non-LE BOM 0x{bom:04X} — not supported here")
    header_size = struct.unpack_from(endian + 'H', buf, 6)[0]

    supported: set[int] = set()
    pos = header_size
    while pos + 8 <= len(buf):
        bmagic = buf[pos:pos + 4]
        bsize = struct.unpack_from(endian + 'I', buf, pos + 4)[0]
        if bsize == 0:
            break
        if bmagic == b'CMAP':
            code_begin, code_end, method, _pad, _next_off = struct.unpack_from(
                endian + 'IIHHI', buf, pos + 8)
            payload_off = pos + 8 + 16
            if method == 0:
                for cp in range(code_begin, code_end + 1):
                    supported.add(cp)
            elif method == 1:
                n = code_end - code_begin + 1
                for i in range(n):
                    gid = struct.unpack_from(endian + 'H', buf,
                                             payload_off + 2 * i)[0]
                    if gid != 0xFFFF:
                        supported.add(code_begin + i)
            elif method == 2:
                count = struct.unpack_from(endian + 'H', buf, payload_off)[0]
                # Entries are u32 cp + u16 gid, 8-byte stride (with 2 bytes of
                # padding to keep alignment for the next entry).
                for i in range(count):
                    eoff = payload_off + 4 + i * 8
                    cp = struct.unpack_from(endian + 'I', buf, eoff)[0]
                    gid = struct.unpack_from(endian + 'H', buf, eoff + 4)[0]
                    if gid != 0xFFFF:
                        supported.add(cp)
        pos += bsize
    return supported


def block_of(cp: int) -> str:
    if 0x0000 <= cp <= 0x007F: return 'Basic Latin'
    if 0x0080 <= cp <= 0x00FF: return 'Latin-1 Supplement'
    if 0x0100 <= cp <= 0x017F: return 'Latin Extended-A'
    if 0x0180 <= cp <= 0x024F: return 'Latin Extended-B'
    if 0x0370 <= cp <= 0x03FF: return 'Greek'
    if 0x0400 <= cp <= 0x04FF: return 'Cyrillic'
    if 0x2000 <= cp <= 0x206F: return 'General Punctuation'
    if 0x20A0 <= cp <= 0x20CF: return 'Currency Symbols'
    if 0x2100 <= cp <= 0x214F: return 'Letterlike Symbols'
    if 0x2200 <= cp <= 0x22FF: return 'Math Operators'
    if 0x2460 <= cp <= 0x24FF: return 'Enclosed Alphanumerics'
    if 0x25A0 <= cp <= 0x25FF: return 'Geometric Shapes'
    if 0x2600 <= cp <= 0x26FF: return 'Misc Symbols'
    if 0x2700 <= cp <= 0x27BF: return 'Dingbats'
    if 0x3000 <= cp <= 0x303F: return 'CJK Symbols/Punct'
    if 0x3040 <= cp <= 0x309F: return 'Hiragana'
    if 0x30A0 <= cp <= 0x30FF: return 'Katakana'
    if 0x4E00 <= cp <= 0x9FFF: return 'CJK Unified'
    if 0xFF00 <= cp <= 0xFFEF: return 'Halfwidth/Fullwidth Forms'
    if 0xE000 <= cp <= 0xF8FF: return 'Private Use Area'
    return f'block-0x{cp >> 8:02x}xx'


# Codepoints worth highlighting in the punctuation report — chosen for likely
# appearance in player slot names / typographic conversion (smart quotes from
# Word, en-dashes from autocorrect, ellipsis, etc.).
PUNCT_CHECKS = [
    (0x00A9, '(C) U+00A9 COPYRIGHT'),
    (0x00AE, '(R) U+00AE REGISTERED'),
    (0x2122, 'TM  U+2122 TRADEMARK'),
    (0x00B0, 'deg U+00B0 DEGREE'),
    (0x00B7, '.   U+00B7 MIDDLE DOT'),
    (0x00A1, '!   U+00A1 INVERTED EXCLAM'),
    (0x00BF, '?   U+00BF INVERTED QUEST'),
    (0x00D7, 'x   U+00D7 MULTIPLY'),
    (0x00F7, '/   U+00F7 DIVIDE'),
    (0x00DF, 'ss  U+00DF SHARP S'),
    (0x00C7, 'C   U+00C7 C CEDILLA CAP'),
    (0x00E7, 'c   U+00E7 c cedilla'),
    (0x00D1, 'N   U+00D1 N TILDE CAP'),
    (0x00F1, 'n   U+00F1 n tilde'),
    (0x00C5, 'A   U+00C5 A RING'),
    (0x00E1, 'a   U+00E1 a acute'),
    (0x00E8, 'e   U+00E8 e grave'),
    (0x00E9, 'e   U+00E9 e acute'),
    (0x00ED, 'i   U+00ED i acute'),
    (0x00F3, 'o   U+00F3 o acute'),
    (0x2010, '-   U+2010 HYPHEN'),
    (0x2013, '-   U+2013 EN DASH'),
    (0x2014, '-   U+2014 EM DASH'),
    (0x2015, '-   U+2015 HORIZONTAL BAR'),
    (0x2018, "'   U+2018 LSQUO"),
    (0x2019, "'   U+2019 RSQUO"),
    (0x201C, '"   U+201C LDQUO'),
    (0x201D, '"   U+201D RDQUO'),
    (0x2026, '... U+2026 ELLIPSIS'),
    (0x2022, '*   U+2022 BULLET'),
    (0x2032, "'   U+2032 PRIME"),
    (0x2033, '"   U+2033 DOUBLE PRIME'),
]


def report_font(name: str, supported: set[int]) -> None:
    print(f'=== {name} ({len(supported)} codepoints) ===')
    print()

    # ASCII printable summary
    ascii_present = ''.join(chr(c) for c in range(0x20, 0x7F) if c in supported)
    ascii_missing = ''.join(chr(c) for c in range(0x20, 0x7F)
                            if c not in supported)
    print(f'ASCII printable present ({len(ascii_present)}/95):')
    print(f'  {ascii_present!r}')
    if ascii_missing:
        print(f'ASCII printable MISSING ({len(ascii_missing)}):')
        print(f'  {ascii_missing!r}')
    print()

    # Curated punctuation checks
    print('Selected non-ASCII punctuation:')
    for cp, label in PUNCT_CHECKS:
        mark = 'YES' if cp in supported else 'no '
        print(f'  {mark}  {label}')
    print()

    # Block-level summary for the rest
    from collections import Counter
    other = sorted(cp for cp in supported if cp >= 0x80)
    c = Counter(block_of(cp) for cp in other)
    print(f'Non-ASCII coverage by block ({len(other)} codepoints):')
    for blk, n in c.most_common():
        print(f'  {n:>5}  {blk}')
    print()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--font-data',
        default='.romfs-cache/romfs/LocalizedData/USen/LayoutData/FontData.szs',
        help='Path to FontData.szs (yaz0-compressed SARC of .bffnt files)')
    parser.add_argument(
        '--only',
        default=None,
        help='Restrict report to one font (e.g. MessageFont38.bffnt)')
    args = parser.parse_args(argv)

    try:
        import oead  # type: ignore[import-not-found]
    except ImportError:
        print('ERROR: oead not importable. Re-run from the extract venv:\n'
              '  scripts/.extract-venv/Scripts/python.exe '
              + ' '.join(sys.argv), file=sys.stderr)
        return 2

    src = Path(args.font_data)
    if not src.is_file():
        print(f'ERROR: {src} not found. Run scripts/extract_shine_map.py '
              'against an SMO 1.0.0 NSP/XCI to populate .romfs-cache/.',
              file=sys.stderr)
        return 2

    raw = src.read_bytes()
    if raw[:4] == b'Yaz0':
        raw = oead.yaz0.decompress(raw)
    if raw[:4] != b'SARC':
        print(f'ERROR: decompressed payload is not SARC (got {raw[:4]!r})',
              file=sys.stderr)
        return 2

    sarc = oead.Sarc(raw)
    fonts = [f for f in sarc.get_files() if f.name.endswith('.bffnt')]
    fonts.sort(key=lambda f: f.name)

    print(f'Source: {src}')
    print(f'Fonts:  {len(fonts)}')
    print()

    for f in fonts:
        if args.only and f.name != args.only:
            continue
        try:
            supported = parse_bffnt_cmap(bytes(f.data))
        except Exception as e:  # noqa: BLE001
            print(f'=== {f.name} ===\n  parse error: {e}\n')
            continue
        report_font(f.name, supported)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
