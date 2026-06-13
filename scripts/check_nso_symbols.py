#!/usr/bin/env python3
"""Search SMO main.nso dynsym for mangled symbol names.

NSO sections are LZ4-compressed. This script decompresses rodata (which
contains .dynstr) and searches for symbol name strings directly.

Usage:
    python scripts/check_nso_symbols.py .romfs-cache/main addCoin
    python scripts/check_nso_symbols.py .romfs-cache/main addPayShine addHackDictionary

Requires: lz4  (pip install lz4)
"""

import struct
import sys

def search_nso(path: str, patterns: list[str]) -> None:
    try:
        import lz4.block
    except ImportError:
        print("ERROR: lz4 not installed. Run: pip install lz4")
        sys.exit(1)

    data = open(path, "rb").read()
    if data[:4] != b"NSO0":
        print(f"ERROR: not an NSO file (magic={data[:4]!r})")
        sys.exit(1)

    flags = struct.unpack_from("<I", data, 0x0C)[0]

    def section(hdr_off, csize_off):
        foff, _moff, usize = struct.unpack_from("<III", data, hdr_off)
        csize = struct.unpack_from("<I", data, csize_off)[0]
        return foff, csize, usize

    text_foff,   text_csize,   text_usize   = section(0x10, 0x60)
    rodata_foff, rodata_csize, rodata_usize = section(0x20, 0x64)

    def decomp(foff, csize, usize, flag_bit):
        raw = data[foff:foff+csize]
        if flags & flag_bit:
            return lz4.block.decompress(raw, uncompressed_size=usize)
        return raw

    print(f"Decompressing sections from {path} ({len(data):,} bytes)...")
    text   = decomp(text_foff,   text_csize,   text_usize,   1)
    rodata = decomp(rodata_foff, rodata_csize, rodata_usize, 2)
    combined = text + rodata
    print(f"  text={len(text):,}  rodata={len(rodata):,}\n")

    any_miss = False
    for pat in patterns:
        needle = pat.encode()
        hit = needle in combined
        sec = "text" if needle in text else ("rodata" if needle in rodata else "?")
        tag = f"HIT [{sec}]" if hit else "MISS"
        print(f"  {tag:<14}  {pat}")
        if not hit:
            any_miss = True

    if any_miss:
        print("\nMISS means the symbol is absent from dynsym — "
              "sail will abort module init if that symbol is referenced "
              "by a HkTrampoline::installAtSym call. Use hk::ro::lookupSymbol "
              "+ nullptr check instead for optional symbols.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_nso_symbols.py <main.nso> [pattern ...]")
        sys.exit(1)
    path = sys.argv[1]
    patterns = sys.argv[2:] or [
        "_ZN16GameDataFunction7addCoinE20GameDataHolderWriteri",
    ]
    search_nso(path, patterns)
