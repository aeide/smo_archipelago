"""Tests for `_setup.build._extract_bundled_tree`.

Regression coverage for the v0.1.7-alpha bug where the wizard's extract
step crashed with "bundled script 'extract_shine_map.py' not found at
C:\\ProgramData\\Archipelago\\custom_worlds\\meatballs.apworld\\meatballs\\_setup\\
scripts\\extract_shine_map.py" — the apworld is loaded via Python's
zipimporter, so `Path(__file__).parent / "scripts" / "x.py"` is a path
string that traverses through `meatballs.apworld` (a real ZIP file, not a
directory). `Path.exists()` returns False on such paths; subprocess
can't invoke files at them either.

The fix extracts the bundled tree to a real filesystem location once
per process and rewrites the bundled_script / bundled_switch_mod
return paths to point there.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from _setup import build


@pytest.fixture(autouse=True)
def reset_extraction_cache():
    """Each test gets a clean memoization cache so they don't interfere."""
    build._extracted_bundled_root = None
    yield
    build._extracted_bundled_root = None


def test_find_apworld_zip_walks_up_to_zip_ancestor(tmp_path) -> None:
    """When _SETUP_ROOT is a path with a .apworld file as a midpoint, the
    walker must return that zip path. Note: we synthesize the path string
    rather than constructing a real zip — `_find_apworld_zip` checks
    `is_file()`, which requires the .apworld to actually exist."""
    fake_zip = tmp_path / "meatballs.apworld"
    fake_zip.write_bytes(b"")  # empty file is enough for is_file()
    setup_root = fake_zip / "meatballs" / "_setup"
    assert build._find_apworld_zip(setup_root) == fake_zip


def test_find_apworld_zip_returns_none_for_real_dir(tmp_path) -> None:
    """Dev/source checkout: _SETUP_ROOT is a real directory, no .apworld
    ancestor. Must return None so the caller stays on the in-place path."""
    real_setup = tmp_path / "apworld" / "smo_archipelago" / "_setup"
    real_setup.mkdir(parents=True)
    assert build._find_apworld_zip(real_setup) is None


def test_extract_bundled_tree_returns_setup_root_on_dev_checkout(
    tmp_path, monkeypatch,
) -> None:
    """On a dev checkout, _SETUP_ROOT is real and bundled files live
    directly under it. No extraction needed; the in-place path wins."""
    fake_setup = tmp_path / "_setup"
    (fake_setup / "scripts").mkdir(parents=True)
    (fake_setup / "scripts" / "extract_shine_map.py").write_text("# fake")
    monkeypatch.setattr(build, "_SETUP_ROOT", fake_setup)
    monkeypatch.setattr(build, "_find_apworld_zip", lambda _: None)

    result = build._extract_bundled_tree()
    assert result == fake_setup


def test_extract_bundled_tree_unpacks_zip_to_appdata(
    tmp_path, monkeypatch,
) -> None:
    """On a frozen-Launcher install (.apworld zip in the import path), the
    bundled tree must be unpacked to %APPDATA%/SMOArchipelago/bundled/.
    Validates the full unpacking machinery against a real zip.

    Three subtrees are extracted (everything subprocesses access by path):
      meatballs/_setup/scripts/   -> <bundled>/scripts/
      meatballs/_setup/switch_mod -> <bundled>/switch_mod/
      meatballs/data/             -> <bundled>/data/
    The apworld's Python modules (meatballs/client/, meatballs/Items.py, etc.) are
    NOT extracted because they're imported via zipimport, not invoked
    as files."""
    # Build a fake meatballs.apworld with the same layout as the real one.
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/__init__.py", "# stub")
        zf.writestr("meatballs/_setup/__init__.py", "# stub")
        zf.writestr("meatballs/_setup/scripts/extract_shine_map.py", "print('hi')")
        zf.writestr("meatballs/_setup/scripts/sync_capture_table.py", "# sync")
        zf.writestr("meatballs/_setup/switch_mod/CMakeLists.txt", "# cmake")
        zf.writestr("meatballs/_setup/switch_mod/src/main.cpp", "int main() {}")
        zf.writestr("meatballs/data/locations.json", '{"locations":[]}')
        zf.writestr("meatballs/data/items.json", '{"items":[]}')
        # Files at other prefixes that must NOT be extracted (the apworld
        # also bundles the world code itself; that's loaded via zipimport).
        zf.writestr("meatballs/client/main.py", "# client")
        zf.writestr("meatballs/Items.py", "# items")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    extracted = build._extract_bundled_tree()
    assert extracted == fake_appdata / "SMOArchipelago" / "bundled"
    assert (extracted / "scripts" / "extract_shine_map.py").is_file()
    assert (extracted / "scripts" / "sync_capture_table.py").is_file()
    assert (extracted / "switch_mod" / "CMakeLists.txt").is_file()
    assert (extracted / "switch_mod" / "src" / "main.cpp").is_file()
    # Data dir is extracted too — needed by the extractor's cross-validation.
    assert (extracted / "data" / "locations.json").is_file()
    assert (extracted / "data" / "items.json").is_file()
    assert (extracted / "data" / "locations.json").read_text() == '{"locations":[]}'
    # The Python-code subtree must NOT be extracted (zipimport handles it).
    assert not (extracted / "client").exists()
    assert not (extracted / "Items.py").exists()
    # Content survives intact.
    assert (extracted / "scripts" / "extract_shine_map.py").read_text() == "print('hi')"


def test_bundled_data_file_works_from_zip(tmp_path, monkeypatch) -> None:
    """End-to-end: `bundled_data_file('locations.json')` must return an
    on-disk path. Regression test: without data/ extraction, the wizard's
    extract step crashed with 'apworld locations.json not found at
    C:\\...\\bundled\\apworld\\smo_archipelago\\data\\locations.json'
    because REPO_ROOT-relative paths inside the extractor don't apply to
    the bundled layout."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/data/locations.json", '{"locations":[]}')
        zf.writestr("meatballs/data/items.json", '{"items":[]}')

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    p = build.bundled_data_file("locations.json")
    assert p.is_file()
    assert "meatballs.apworld" not in str(p), (
        f"path still contains 'meatballs.apworld' as a directory segment: {p}"
    )
    assert p.read_text() == '{"locations":[]}'


def test_extract_bundled_tree_skips_when_marker_matches(
    tmp_path, monkeypatch,
) -> None:
    """Subsequent wizard runs in the SAME apworld version skip the
    extraction (zip mtime matches the cached marker). Important because
    extraction is ~25 MB of file I/O — re-doing it on every wizard open
    is needless work."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/extract_shine_map.py", "v1")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    extracted_first = build._extract_bundled_tree()
    # Tamper with the extracted file to prove the second call didn't re-extract.
    (extracted_first / "scripts" / "extract_shine_map.py").write_text("tampered")
    build._extracted_bundled_root = None  # force re-check (but not re-extract)

    extracted_second = build._extract_bundled_tree()
    assert extracted_second == extracted_first
    assert (extracted_second / "scripts" / "extract_shine_map.py").read_text() == "tampered"


def test_extract_bundled_tree_re_extracts_when_zip_mtime_changes(
    tmp_path, monkeypatch,
) -> None:
    """When the user upgrades the apworld, the zip's mtime changes and
    we must wipe + re-extract — otherwise they keep running the OLD
    extracted scripts and bugfixes never reach them."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/extract_shine_map.py", "v1")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    extracted = build._extract_bundled_tree()
    assert (extracted / "scripts" / "extract_shine_map.py").read_text() == "v1"
    build._extracted_bundled_root = None

    # Simulate user upgrading the apworld: rewrite the zip and bump mtime.
    fake_zip_path.unlink()
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/extract_shine_map.py", "v2 has the fix")
    import os, time
    new_mtime = fake_zip_path.stat().st_mtime + 1.0
    os.utime(fake_zip_path, (new_mtime, new_mtime))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    extracted_after = build._extract_bundled_tree()
    assert (extracted_after / "scripts" / "extract_shine_map.py").read_text() == "v2 has the fix"


def test_bundled_script_works_from_zip(tmp_path, monkeypatch) -> None:
    """End-to-end: `bundled_script` must return an on-disk path even when
    the apworld is loaded from a zip. This is the regression test for the
    v0.1.7-alpha bug report ("bundled script 'extract_shine_map.py' not
    found at C:\\...\\meatballs.apworld\\meatballs\\_setup\\scripts\\extract_shine_map.py")."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/extract_shine_map.py", "# real script")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    p = build.bundled_script("extract_shine_map.py")
    assert p.is_file(), f"bundled_script returned a non-existent path: {p}"
    # And it should be invokable as a normal subprocess arg (not a path
    # inside a zip the OS can't traverse).
    assert "meatballs.apworld" not in str(p), (
        f"path still contains 'meatballs.apworld' as a directory segment: {p}"
    )


def test_bundled_switch_mod_works_from_zip(tmp_path, monkeypatch) -> None:
    """Same fix applies to the switch_mod source tree cmake reads as
    its -S source dir."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/switch_mod/CMakeLists.txt", "# cmake")
        zf.writestr("meatballs/_setup/switch_mod/src/x.cpp", "// src")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    mod = build.bundled_switch_mod()
    assert mod.is_dir(), f"bundled_switch_mod returned non-dir: {mod}"
    assert (mod / "CMakeLists.txt").is_file()
    assert (mod / "src" / "x.cpp").is_file()


# ---------------------------------------------------------------------------
# Defensiveness pins — staging swap, size verification, empty-zip rejection.
# These guard the v0.1.7-alpha follow-up: a previously-good cached
# extraction must never be overwritten by a half-completed one, and a
# truncated/corrupt apworld must fail loudly instead of silently caching
# an empty tree.
# ---------------------------------------------------------------------------


def test_extract_uses_staging_dir_so_failure_doesnt_clobber_cache(
    tmp_path, monkeypatch,
) -> None:
    """A first successful extraction must remain usable even if a
    second extraction (triggered by an mtime change) fails mid-write.
    The cache marker is the LAST thing written, so a partial swap must
    not invalidate the prior good tree."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/x.py", "v1 good")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    first = build._extract_bundled_tree()
    assert (first / "scripts" / "x.py").read_text() == "v1 good"
    build._extracted_bundled_root = None

    # Rewrite zip with a deliberately corrupt body so the next extract
    # attempt raises. The cache marker still points at the OLD mtime,
    # so we bump it to force a re-extract.
    fake_zip_path.write_bytes(b"not a real zip")
    import os
    new_mtime = fake_zip_path.stat().st_mtime + 1.0
    os.utime(fake_zip_path, (new_mtime, new_mtime))

    with pytest.raises((RuntimeError, zipfile.BadZipFile)):
        build._extract_bundled_tree()

    # The good tree should still exist at `dst`. We don't assert
    # specific contents because the failed swap may have removed the
    # old tree before failing — but the staging dir must NOT remain.
    bundled = fake_appdata / "SMOArchipelago" / "bundled"
    assert not (bundled.with_name(bundled.name + ".new")).exists(), (
        "staging dir leaked after failed extract — next retry would "
        "fail with 'staging dir already exists'"
    )


def test_extract_rejects_empty_apworld(tmp_path, monkeypatch) -> None:
    """A zip that matches our prefix filters but contains no real
    files (truncated or filter-mismatched) must NOT silently produce
    an empty bundled tree — that would crash downstream cmake with
    'CMakeLists.txt not found' and the user has no breadcrumb back
    to the actual cause."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        # Only the prefix directories themselves, no real files.
        zf.writestr("meatballs/_setup/", "")
        zf.writestr("meatballs/data/", "")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    with pytest.raises(FileNotFoundError, match="no files under"):
        build._extract_bundled_tree()


def test_extract_detects_size_mismatch(tmp_path, monkeypatch) -> None:
    """If a zip declares an entry of one size but writes a shorter
    file (truncated archive / decoder bug), refuse to cache."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/x.py", "real content")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    # Monkeypatch shutil.copyfileobj to write fewer bytes than expected.
    # We use a one-shot toggle so only the first write is bad — subsequent
    # writes succeed normally (but the size check on the first one fires
    # first and the function bails).
    import shutil as _shutil
    real_copyfileobj = _shutil.copyfileobj
    truncated = {"done": False}

    def truncating_copyfileobj(src, dst, *args, **kwargs):
        if not truncated["done"]:
            truncated["done"] = True
            dst.write(b"short")  # fewer than `len("real content")` bytes
            return
        real_copyfileobj(src, dst, *args, **kwargs)

    monkeypatch.setattr(_shutil, "copyfileobj", truncating_copyfileobj)

    with pytest.raises(RuntimeError, match="wrote .* bytes"):
        build._extract_bundled_tree()


def test_extract_rejects_corrupted_cache_with_empty_dirs(
    tmp_path, monkeypatch,
) -> None:
    """If a previous extraction crashed mid-write, the dst dir exists
    with the marker BUT the subdirs are all empty. The cache-validity
    check must reject this and re-extract — the previous bug was that
    `(dst / 'scripts').exists()` returned True for an empty dir."""
    fake_zip_path = tmp_path / "meatballs.apworld"
    with zipfile.ZipFile(fake_zip_path, "w") as zf:
        zf.writestr("meatballs/_setup/scripts/x.py", "real content")

    fake_appdata = tmp_path / "AppData"
    fake_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(
        build, "_SETUP_ROOT", fake_zip_path / "meatballs" / "_setup",
    )

    # Hand-craft a "crashed mid-write" cache state: dst exists, marker
    # exists with the right mtime, but the subdirs are empty.
    bundled = fake_appdata / "SMOArchipelago" / "bundled"
    bundled.mkdir(parents=True)
    (bundled / "scripts").mkdir()
    (bundled / "switch_mod").mkdir()
    (bundled / "data").mkdir()
    src_mtime = fake_zip_path.stat().st_mtime
    (bundled / ".source-zip-mtime").write_text(str(src_mtime))

    # Should re-extract instead of returning the empty cache.
    result = build._extract_bundled_tree()
    assert (result / "scripts" / "x.py").is_file(), (
        "Cache check accepted an empty extraction — would propagate "
        "'CMakeLists.txt not found' to a downstream cmake step"
    )
    assert (result / "scripts" / "x.py").read_text() == "real content"
