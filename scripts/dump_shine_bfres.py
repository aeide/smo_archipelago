#!/usr/bin/env python3
"""Pull ShineDot.szs (and Shine.szs as a control) out of the SMO RomFS,
decompress the Yaz0 + SARC, and dump every BFRES material's parameter list
so we can pick the (material_name, parameter_name) for the M-color 2D
override path. Local-only — outputs Nintendo IP and stays gitignored.

Usage (from repo root, after the SMO RomFS has been dumped via
`hactool ... --romfs=.romfs-cache/program.romfs.bin program.nca`):

    scripts/.extract-venv/Scripts/python.exe scripts/dump_shine_bfres.py

The RomFS reader is a minimal hand-rolled walker — we just need the
directory tree to find /ObjectData/<file>, then pull the file's bytes out
of the data section. No hash-table use; the linear walk is fine for this.
"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROMFS_BIN = REPO / ".romfs-cache" / "program.romfs.bin"

# Files we care about. ShineDot is the failing 2D variant; Shine/Grand are
# the working controls so we can sanity-check our parser by confirming
# their materials match what 3D recolor visibly applies.
WANT = [
    "/ObjectData/ShineDot.szs",
    "/ObjectData/Shine.szs",
    "/ObjectData/ShineGrand.szs",
]


# ---------- RomFS reader -----------------------------------------------------

def read_romfs_header(buf: memoryview) -> dict:
    h = {
        "header_size":           struct.unpack_from("<Q", buf, 0x00)[0],
        "dir_hash_off":          struct.unpack_from("<Q", buf, 0x08)[0],
        "dir_hash_size":         struct.unpack_from("<Q", buf, 0x10)[0],
        "dir_meta_off":          struct.unpack_from("<Q", buf, 0x18)[0],
        "dir_meta_size":         struct.unpack_from("<Q", buf, 0x20)[0],
        "file_hash_off":         struct.unpack_from("<Q", buf, 0x28)[0],
        "file_hash_size":        struct.unpack_from("<Q", buf, 0x30)[0],
        "file_meta_off":         struct.unpack_from("<Q", buf, 0x38)[0],
        "file_meta_size":        struct.unpack_from("<Q", buf, 0x40)[0],
        "data_off":              struct.unpack_from("<Q", buf, 0x48)[0],
    }
    return h


def read_dir_meta(buf: memoryview, off: int) -> dict:
    parent, sibling, child_dir, child_file, hash_chain, name_len = struct.unpack_from(
        "<IIIIII", buf, off)
    name = bytes(buf[off + 0x18 : off + 0x18 + name_len]).decode("utf-8", "replace")
    return {
        "parent": parent,
        "sibling": sibling,
        "child_dir": child_dir,
        "child_file": child_file,
        "name": name,
    }


def read_file_meta(buf: memoryview, off: int) -> dict:
    parent, sibling, data_off, data_size, hash_chain, name_len = struct.unpack_from(
        "<IIQQII", buf, off)
    name = bytes(buf[off + 0x20 : off + 0x20 + name_len]).decode("utf-8", "replace")
    return {
        "parent": parent,
        "sibling": sibling,
        "data_off": data_off,
        "data_size": data_size,
        "name": name,
    }


def walk_directory(dir_buf: memoryview, file_buf: memoryview,
                   dir_off: int, prefix: str = "") -> dict[str, dict]:
    """Recursively walk the RomFS dir tree. Returns {abs_path: file_meta} for files."""
    out: dict[str, dict] = {}
    cur = read_dir_meta(dir_buf, dir_off)
    here = prefix + ("/" + cur["name"] if cur["name"] else "")

    # children files
    fo = cur["child_file"]
    while fo != 0xFFFFFFFF:
        fm = read_file_meta(file_buf, fo)
        out[here + "/" + fm["name"]] = fm
        fo = fm["sibling"]

    # children dirs
    do = cur["child_dir"]
    while do != 0xFFFFFFFF:
        out.update(walk_directory(dir_buf, file_buf, do, here))
        d = read_dir_meta(dir_buf, do)
        do = d["sibling"]

    return out


def extract_file(romfs_path: Path, want_paths: list[str]) -> dict[str, bytes]:
    """Pull each wanted path out of the RomFS image as bytes."""
    fh = romfs_path.open("rb")
    header_bytes = fh.read(0x50)
    h = read_romfs_header(memoryview(header_bytes))
    fh.seek(h["dir_meta_off"])
    dir_buf = memoryview(fh.read(h["dir_meta_size"]))
    fh.seek(h["file_meta_off"])
    file_buf = memoryview(fh.read(h["file_meta_size"]))

    tree = walk_directory(dir_buf, file_buf, 0, "")

    out: dict[str, bytes] = {}
    for p in want_paths:
        if p not in tree:
            print(f"!! {p} not in RomFS tree", file=sys.stderr)
            continue
        fm = tree[p]
        fh.seek(h["data_off"] + fm["data_off"])
        out[p] = fh.read(fm["data_size"])
        print(f"   {p} -> {fm['data_size']:,} bytes", file=sys.stderr)
    return out


# ---------- SARC + Yaz0 + BFRES walker ---------------------------------------

def decompress_yaz0(data: bytes) -> bytes:
    # oead understands Yaz0 + SARC; rely on it rather than rolling our own.
    import oead
    return bytes(oead.yaz0.decompress(data))


def find_bfres_in_sarc(sarc_data: bytes) -> list[tuple[str, bytes]]:
    import oead
    sarc = oead.Sarc(sarc_data)
    out: list[tuple[str, bytes]] = []
    for f in sarc.get_files():
        if f.name.endswith(".bfres"):
            out.append((f.name, bytes(f.data)))
    return out


def dump_strings_heuristic(bfres: bytes) -> list[str]:
    """Conservative scan: NX BFRES stores names as a 2-byte little-endian
    length prefix followed by UTF-8 bytes + a terminating null. The struct
    layout for material/parameter slots is version-dependent and a wrong
    guess yields wild offsets (see parse_bfres_materials), but the *strings
    themselves* live in a single contiguous string-pool inside the BFRES
    and we can fish them out by looking for `[len_lo, len_hi, ...ascii..., 0]`
    sequences.

    Returns a deduped, lexically-sorted list of plausible identifier names.
    """
    out: set[str] = set()
    n = len(bfres)
    i = 0
    while i < n - 3:
        ln = bfres[i] | (bfres[i + 1] << 8)
        if 1 <= ln <= 64:
            end = i + 2 + ln
            if end < n and bfres[end] == 0:
                s = bytes(bfres[i + 2 : end])
                # Accept ASCII identifier-ish payloads only — material and
                # shader param names follow Nintendo's `[A-Za-z][A-Za-z0-9_]*`
                # naming for the most part. Drop anything with whitespace,
                # punctuation, or non-ASCII bytes.
                if all(0x21 <= b <= 0x7e for b in s):
                    text = s.decode("ascii", "replace")
                    if (text[0].isalpha() or text[0] == "_") and all(
                            c.isalnum() or c in "_." for c in text):
                        out.add(text)
        i += 1
    return sorted(out)


def parse_bfres_materials(bfres: bytes) -> list[dict]:
    """Walk a BFRES (NX) and emit per-material parameter listings.

    BFRES (NX) on Switch has the format:
      +0x00 'FRES' magic
      +0x04 version / endian / header_size
      +0x10 'FRES' file name offset
      ...
      +0x20: 12 sub-file group offsets (FMDL, FSKA, FSHA, FTXP, FVIS, FSHU,
                                        FSCN, embedded, string table, ...)
      The FMDL list is at offset_table[0]; each FMDL has a list of FMATs.
      Each FMAT has a list of parameters and a list of textures.

    We do NOT need a full parser — the parameter and material *names* are
    null-terminated strings in the file's string table, and they collectively
    look like 'Mtl0' / 'Diffuse0' / 'BaseColorRate' etc. Picking them out
    accurately requires walking the BFRES structures rather than just running
    strings(1) over the whole blob (which would include shader names, etc.).

    The "Switch BFRES" docs are public (e.g. https://mk8.tockdom.com/wiki/BFRES_(File_Format))
    so the parsing here is reverse-engineered from the public spec, not from
    leaked Nintendo material.

    Layout details we use:
      FRES header: at +0x18, the relative-pointer to the FMDL group is at
      offset 0x40 (FMDL group ptr). The 'BNTX' textures block is at +0x50
      etc. We just need FMDL → FMAT walking.
    """
    # Strict header check
    assert bfres[:4] == b'FRES', f"not a BFRES: {bfres[:4]!r}"

    # NX BFRES: 64-bit pointers, little-endian, header size 0x180.
    # FMDL group: relative ptr at +0x20 (from start of FRES header).
    # The "group" is a ResDict that holds N FMDL entries.
    def u64(off): return struct.unpack_from("<Q", bfres, off)[0]
    def u32(off): return struct.unpack_from("<I", bfres, off)[0]
    def u16(off): return struct.unpack_from("<H", bfres, off)[0]

    def read_str(off):
        # NX BFRES strings: 2-byte length prefix followed by UTF-8 bytes
        # + a terminating null.
        if off == 0 or off >= len(bfres):
            return ""
        length = u16(off)
        return bytes(bfres[off + 2 : off + 2 + length]).decode("utf-8", "replace")

    # FMDL group: at +0x18 of header is the FMDL ResDict pointer.
    # Actually, the layout per the public wiki is:
    #   +0x18: FileName (string ptr)
    #   +0x20: file_path (string ptr)
    #   +0x28: model_group_ptr
    #   +0x30: model_group_dict_ptr
    #   +0x38: skeletal_anim_group_ptr
    #   +0x40: skeletal_anim_dict_ptr
    #   ...
    fmdl_arr = u64(0x28)
    fmdl_dict = u64(0x30)
    if fmdl_arr == 0:
        return []

    # ResDict header (16 bytes):
    #   +0x00 'magic' (always 0)
    #   +0x04 num_entries
    #   then num_entries+1 patricia-trie nodes (16 bytes each: ref+left+right+key)
    # We just want the names + array ordering. The corresponding FMDL array is
    # at fmdl_arr; entry size is sizeof(FMDL) which is variable, but the array
    # is a packed list of (FMDL ptr) — no, actually it IS a packed list of
    # FMDL structs. Each FMDL is 0x68 bytes? Need to check via the
    # entry-pointer layout.
    #
    # Simpler approach: iterate the ResDict to get names, look up each FMDL
    # via the dict's pointer-to-entry.

    n = u32(fmdl_dict + 4)
    results = []
    for i in range(1, n + 1):  # skip root entry [0]
        node_off = fmdl_dict + 0x10 + i * 0x10
        name_ptr = u64(node_off + 0x08)
        fmdl_name = read_str(name_ptr) if name_ptr else f"<noname#{i}>"
        # The actual FMDL pointer is in the array `fmdl_arr` at index (i-1).
        # FMDL entries are 0x68 bytes (NX). The FMAT array ptr is at +0x28
        # of the FMDL, with FMAT count at +0x42 or +0x43 depending on
        # version. Safer: deref the FMDL by dict-entry's "self pointer" if
        # present.
        # On NX the array elements are pointers, so:
        fmdl_ptr = u64(fmdl_arr + (i - 1) * 8)
        if fmdl_ptr == 0:
            continue
        # FMDL @ fmdl_ptr:
        #   +0x18: ResDict<FMAT> ptr (material dict)
        #   +0x20: FMAT array ptr
        #   +0x2C: u16 fmat_count (offset varies; on NX it's typically +0x44)
        # Try both common offsets and accept whichever yields a small count.
        fmat_arr = u64(fmdl_ptr + 0x20)
        fmat_dict = u64(fmdl_ptr + 0x28)
        # FMAT count: u16 at fmdl + 0x44 on NX
        fmat_count = u16(fmdl_ptr + 0x44) if (fmdl_ptr + 0x44) < len(bfres) else 0
        if fmat_count == 0 or fmat_count > 64:
            # Fallback: use the dict's own count
            fmat_count = u32(fmat_dict + 4) if fmat_dict else 0

        mats = []
        for m in range(fmat_count):
            fmat_ptr = u64(fmat_arr + m * 8)
            if fmat_ptr == 0:
                continue
            # FMAT @ fmat_ptr:
            #   +0x00 'FMAT' magic
            #   +0x10 name ptr
            #   +0x60 shader_param_array ptr
            #   +0x68 shader_param_dict ptr
            #   +0xA4 u16 num_shader_params
            magic = bytes(bfres[fmat_ptr : fmat_ptr + 4])
            if magic != b'FMAT':
                continue
            mname_ptr = u64(fmat_ptr + 0x10)
            mname = read_str(mname_ptr) if mname_ptr else "<noname>"
            shader_param_arr = u64(fmat_ptr + 0x60)
            shader_param_dict = u64(fmat_ptr + 0x68)
            num_sp = u16(fmat_ptr + 0xA4) if (fmat_ptr + 0xA4) < len(bfres) else 0
            if num_sp == 0 or num_sp > 256:
                num_sp = u32(shader_param_dict + 4) if shader_param_dict else 0
            # ShaderParam entry on NX is 0x20 bytes: u8 type, u8 _pad, u16 size,
            #   u16 offset, u16 dependency_idx, u32 _pad, u64 name_ptr
            params = []
            entry_size = 0x20
            for p in range(num_sp):
                pe = shader_param_arr + p * entry_size
                if pe + entry_size > len(bfres):
                    break
                ptype = bfres[pe]
                pname_ptr = u64(pe + 0x10)
                pname = read_str(pname_ptr) if pname_ptr else "<noname>"
                params.append({"name": pname, "type": ptype})
            mats.append({"material": mname, "params": params})
        results.append({"model": fmdl_name, "materials": mats})
    return results


# ---------- main -------------------------------------------------------------

def main() -> int:
    if not ROMFS_BIN.exists():
        print(f"ERROR: {ROMFS_BIN} not found. Run hactool first to dump "
              f"the RomFS section (see script docstring).", file=sys.stderr)
        return 2

    print(f"[romfs] reading {ROMFS_BIN}", file=sys.stderr)
    blobs = extract_file(ROMFS_BIN, WANT)

    for path, raw in blobs.items():
        print(f"\n=== {path} ({len(raw):,} bytes raw) ===")
        if raw[:4] != b"Yaz0":
            print(f"  unexpected magic {raw[:4]!r}, expected Yaz0")
            continue
        decomp = decompress_yaz0(raw)
        print(f"  yaz0-decompressed: {len(decomp):,} bytes")
        bfres_files = find_bfres_in_sarc(decomp)
        if not bfres_files:
            print(f"  no .bfres inside SARC; SARC files:")
            import oead
            for f in oead.Sarc(decomp).get_files():
                print(f"    {f.name} ({len(f.data):,} bytes)")
            continue
        for bname, bbytes in bfres_files:
            print(f"  bfres: {bname} ({len(bbytes):,} bytes)")
            names = dump_strings_heuristic(bbytes)
            # Bucket by guessed kind so the output is readable.
            color_like = [n for n in names if any(k in n.lower() for k in (
                "color", "diffuse", "specular", "emit", "tint", "rate"))]
            material_like = [n for n in names if any(k in n.lower() for k in (
                "mtl", "material", "body", "shine"))]
            param_like = [n for n in names if (
                # Standard Nintendo shader param naming: lowercased, suffix-_X
                # or with caps mid-name. Exclude things that look like model
                # / mesh / bone names.
                ("_" in n or n[:1].islower()) and not any(
                    k in n.lower() for k in ("mesh", "bone", "model"))
            )]
            print(f"    color-like strings ({len(color_like)}):")
            for n in color_like:
                print(f"      {n}")
            print(f"    material-like strings ({len(material_like)}):")
            for n in material_like:
                print(f"      {n}")
            print(f"    other plausible-param strings ({len(param_like) - len(color_like)} extra):")
            extras = sorted(set(param_like) - set(color_like))
            for n in extras[:40]:
                print(f"      {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
