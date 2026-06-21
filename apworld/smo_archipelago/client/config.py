"""Bridge configuration. Loaded from TOML, overridable via CLI/env."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApConfig:
    host: str = ""
    port: int = 38281
    slot: str = ""
    password: str = ""
    items_handling: int = 0b111


@dataclass
class SwitchConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 17777


@dataclass
class BridgeOptions:
    log_level: str = "INFO"
    web_tracker: bool = True
    web_port: int = 8000
    # Path to a local Archipelago checkout. The bridge needs this to import
    # CommonClient. Resolution order: this field -> SMOAP_AP_PATH env var ->
    # default `<repo>/vendor/Archipelago` (typically a git submodule).
    archipelago_path: str = ""
    # Paths to the raw-ID resolution tables. Default to the data/ siblings.
    shine_map_path: str = ""
    capture_map_path: str = ""


@dataclass
class DeathLinkOptions:
    """DeathLink (one player dies, everyone dies). Off by default."""
    enabled: bool = False


# Kingdom -> palette index for our OWN slot's moon items. The Switch's
# ShineAppearanceHook reserves a contiguous palette block starting at
# KINGDOM_PALETTE_BASE; a scouted moon check that grants one of our moon
# items is colored by the GRANTED moon's kingdom (not the kingdom the check
# physically sits in). Keep this order in lock-step with kPaletteColors3D /
# kPaletteColorsDot in switch-mod/src/hooks/ShineAppearanceHook.cpp (block
# base 5, SMO natural kingdom order incl. Cloud + Dark/Darker).
KINGDOM_PALETTE_BASE = 5
KINGDOM_PALETTE_ORDER = (
    "Cap", "Cascade", "Sand", "Lake", "Wooded", "Cloud", "Lost",
    "Metro", "Snow", "Seaside", "Luncheon", "Ruined", "Bowser's",
    "Moon", "Mushroom", "Dark", "Darker",
)
_KINGDOM_PALETTE_INDEX = {
    k: KINGDOM_PALETTE_BASE + i for i, k in enumerate(KINGDOM_PALETTE_ORDER)
}


@dataclass
class ColorsConfig:
    """Maps a foreign-game AP item classification -> ShineAppearanceHook
    recolor-table index.

    The Switch's ShineAppearanceHook holds a fixed Color4f table and tints the
    moon body material at Shine::init by the index the bridge ships per
    shine_uid. The classification defaults below cover FOREIGN-game items at our
    checks (progression=green, useful=yellow, trap=red, filler/junk=grey via the
    index-0 recolor). Our OWN slot's moon items are colored by the granted
    moon's kingdom instead — see for_kingdom() / KINGDOM_PALETTE_*.

    Keep these indices in lock-step with kPaletteColors3D/Dot in
    switch-mod/src/hooks/ShineAppearanceHook.cpp.
    """
    enabled: bool = True
    progression: int = 1
    useful: int = 2
    trap: int = 3
    filler: int = 0

    def for_classification(self, classification: str) -> int:
        """Look up the palette index for a wire-form classification string.

        Unknown strings (including None-as-empty) fall through to filler.
        """
        if classification == "progression":
            return self.progression
        if classification == "useful":
            return self.useful
        if classification == "trap":
            return self.trap
        return self.filler

    def for_kingdom(self, kingdom: str | None) -> int | None:
        """Palette index for one of our own slot's moon items, keyed on the
        GRANTED moon's kingdom.

        Returns None for an unknown/empty kingdom so the caller falls back to
        the classification color. Short kingdom form ("Cap", "Bowser's",
        "Dark") as parsed out of the item name by DataPackage.classify_item.
        """
        if not kingdom:
            return None
        return _KINGDOM_PALETTE_INDEX.get(kingdom)


@dataclass
class Config:
    ap: ApConfig = field(default_factory=ApConfig)
    switch: SwitchConfig = field(default_factory=SwitchConfig)
    bridge: BridgeOptions = field(default_factory=BridgeOptions)
    deathlink: DeathLinkOptions = field(default_factory=DeathLinkOptions)
    colors: ColorsConfig = field(default_factory=ColorsConfig)

    @classmethod
    def load(cls, path: Path | str | None) -> "Config":
        cfg = cls()
        if path is not None:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            if "ap" in raw:
                cfg.ap = ApConfig(**{**cfg.ap.__dict__, **raw["ap"]})
            if "switch" in raw:
                cfg.switch = SwitchConfig(**{**cfg.switch.__dict__, **raw["switch"]})
            if "bridge" in raw:
                cfg.bridge = BridgeOptions(**{**cfg.bridge.__dict__, **raw["bridge"]})
            if "deathlink" in raw:
                cfg.deathlink = DeathLinkOptions(**{**cfg.deathlink.__dict__, **raw["deathlink"]})
            if "colors" in raw:
                cfg.colors = ColorsConfig(**{**cfg.colors.__dict__, **raw["colors"]})

        env_password = os.environ.get("SMOAP_PASSWORD")
        if env_password:
            cfg.ap.password = env_password
        return cfg

    def apply_overrides(
        self,
        ap_addr: str | None = None,
        slot: str | None = None,
        web_tracker: bool | None = None,
        log_level: str | None = None,
        archipelago_path: str | None = None,
    ) -> None:
        if archipelago_path is not None:
            self.bridge.archipelago_path = archipelago_path
        if ap_addr:
            host, _, port = ap_addr.partition(":")
            self.ap.host = host
            if port:
                self.ap.port = int(port)
        if slot is not None:
            self.ap.slot = slot
        if web_tracker is not None:
            self.bridge.web_tracker = web_tracker
        if log_level is not None:
            self.bridge.log_level = log_level
