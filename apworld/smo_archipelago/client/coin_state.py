"""Per-save persistence of the coin total already applied to the SMO save.

Why this exists (2026-07-12): the Switch grants AP coins via
``GameDataFunction::addCoin`` and SMO PERSISTS coins in its save file. But the
Switch's idempotency high-water mark (``ApState::coins_applied``) is in-memory
and resets to 0 on every game boot — so on each boot the client re-sent the
cumulative ``coin_grant`` total and the Switch re-applied the whole thing on
top of what the save already held, doubling coins every reboot (Devon's find:
"extremely easy to max out on coins").

Fix: the client remembers, per (seed, slot), how many coins it has confirmed
applied to that save, and ships it as ``CoinGrant.baseline``. The Switch seeds
``coins_applied = max(coins_applied, baseline)`` before applying
``total - coins_applied`` — so coins are granted exactly once across reboots.

Persistence lives in ``%APPDATA%/SMOArchipelago/coins_applied.json`` (co-located
with the wizard's extracted maps, keyed by ``"<seed>\\x00<slot>"``). Keyed to the
AP (seed, slot) because that's the closest stable proxy for "this SMO save".
Known edge cases (accepted, documented): starting a FRESH SMO save for an
already-played (seed, slot) will under-grant once (baseline suppresses the
re-grant); playing the same slot from a different PC resets the baseline and
double-grants once. Both are rare and self-correct as new coins arrive.
"""

from __future__ import annotations

import json
from pathlib import Path

from .setup_state import _user_data_dir

_COINS_FILENAME = "coins_applied.json"


def _coins_path() -> Path:
    # Co-locate with the maps sentinel (parent of the maps `data/` subdir) so a
    # wizard re-extraction that wipes `data/` can't drop the coin ledger.
    return _user_data_dir().parent / _COINS_FILENAME


def _key(seed: str, slot: str) -> str:
    return f"{seed}\x00{slot}"


def _load_all() -> dict:
    try:
        raw = _coins_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_applied(seed: str, slot: str) -> int:
    """Coins already confirmed applied to the (seed, slot) save. 0 if unknown.

    Returns 0 for an empty seed/slot (client not yet AP-connected) so a
    pre-connect push can't accidentally suppress a real grant.
    """
    if not seed or not slot:
        return 0
    val = _load_all().get(_key(seed, slot))
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return 0


def save_applied(seed: str, slot: str, total: int) -> None:
    """Record `total` as the coins now applied to the (seed, slot) save.

    Monotonic: never lowers a stored value (a stale/lower push must not
    reopen the re-grant window). No-op on empty seed/slot. Best-effort — an
    I/O failure just means the baseline isn't advanced this session (worst
    case a one-time re-grant next boot, never a crash).
    """
    if not seed or not slot:
        return
    total = max(0, int(total))
    data = _load_all()
    key = _key(seed, slot)
    if total <= int(data.get(key, 0) or 0):
        return
    data[key] = total
    path = _coins_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
