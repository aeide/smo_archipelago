# First-time setup

This page describes everything a brand-new SMO Archipelago player needs to
do once on their machine. After this, joining a multiworld is just
double-clicking your `.smoap` file.

> **Platform:** Windows only today. Linux and macOS aren't blocked by
> design, but the setup wizard and several scripts assume `%APPDATA%`,
> `C:/devkitPro`, the Windows Python launcher (`py -3.12`), and similar
> Windows-specific paths. No one has tested the flow on other platforms.

## Hard requirements

Before you start, confirm all three:

| Requirement | Why | What to do if you don't have it |
|---|---|---|
| **Super Mario Odyssey 1.0.0** | Every public SMO mod (lunakit, OdysseyDecomp, ours) targets the original 1.0.0 release. 1.1.0+ have different symbol offsets, struct layouts, and patched behaviors — our module won't load on them. | If you're on 1.1.0, 1.2.0, or 1.3.0, downgrade to 1.0.0 using [Istador/odyssey-downgrade](https://github.com/Istador/odyssey-downgrade). Follow that tool's README — it's a one-time process that removes the update overlay so the cartridge / base NSP runs as 1.0.0. |
| **Switch firmware 21.x or earlier** | The subsdk9-style modules we rely on use a homebrew lifecycle Nintendo changed in firmware 22. **FW22 is NOT supported** by this project, even though Atmosphere 1.11+ technically boots on it. | Stay on FW 21.x. If you've already updated to FW22 or later, there is currently no downgrade path back to 21.x on a stock Switch — you'd need to wait for SMO Archipelago to add FW22 compatibility (no ETA). |
| **Atmosphere CFW** running on the above firmware | The mod ships as an Atmosphere overlay (`exefs/subsdk9`). | Follow one of the community guides — [NH Switch Guide](https://nh-server.github.io/switch-guide/) is the canonical starting point. Make sure you're on FW 21.x BEFORE setting up Atmosphere; don't update past 21.x. |

## What you'll end up with

- `smo.apworld` installed in your Archipelago install's `custom_worlds/`
- Moon + capture name tables extracted from your own SMO 1.0.0 NSP, sitting
  in `%APPDATA%/SMOArchipelago/data/`
- A compiled Switch module (`subsdk9` + `main.npdm` + `ap_config.json`)
  sitting in `%APPDATA%/SMOArchipelago/build/`
- That module copied to **either** your modded Switch's SD card **or**
  Ryujinx's mods directory (your choice; you can re-run setup and pick the
  other one later)

You only need to run this once per machine. **Changing AP server or slot
does NOT require re-running setup** — see
[changing servers](changing-servers.md).

## Prerequisites

The wizard checks for all of these before doing anything and links you to
install pages for whatever's missing. Best to install them up-front to avoid
back-and-forth:

| Prerequisite | Used for | How to get it |
|---|---|---|
| **Archipelago** | The framework SMOClient runs inside | https://github.com/ArchipelagoMW/Archipelago/releases |
| **Python 3.12** | The moon/capture extractor (`oead` has no Python 3.13+ wheel) | https://www.python.org/downloads/release/python-3120/#files |
| **devkitPro + devkitA64** | Cross-compiler for the Switch module | https://devkitpro.org/wiki/Getting_Started |
| **CMake 3.24+** | Build orchestrator | https://cmake.org/download/ |
| **Ninja** | Build backend | https://github.com/ninja-build/ninja/releases (or `winget install Ninja-build.Ninja`) |
| **hactool** | Extracts RomFS from your SMO NSP | https://github.com/SciresM/hactool/releases |
| **prod.keys** (Switch console keys) | hactool needs them to decrypt the NSP | Dump with [Lockpick_RCM](https://github.com/Lockpick-Switch/Lockpick_RCM) → place at `%USERPROFILE%\.switch\prod.keys` |
| **Your SMO 1.0.0 NSP** | Source of moon + capture names | Your legally-purchased copy. **Not** a patched version — 1.0.0 only. |
| **A modded Switch** | Where SMO actually runs | Atmosphere CFW on a modded Switch (FW 21.x or earlier) |

> ⚠️ **Why so many tools?** SMO Archipelago is "play your own Switch", not
> "play an emulated ROM". The mod that talks to AP runs inside SMO on the
> Switch itself, which means it has to be cross-compiled per-user with the
> bridge PC's LAN IP baked in. Pre-built binaries can't ship because they'd
> incorporate Nintendo SDK derivations. The wizard automates as much of
> the build as it can, but the toolchain itself has to live on your
> machine.

## The flow

1. **Download `smo.apworld`** from the
   [Releases page](https://github.com/mdietz94/smo_archipelago/releases).
2. **Drop it into Archipelago's `custom_worlds/`** directory. On Windows the
   path is typically `%LOCALAPPDATA%\Archipelago\custom_worlds\` or
   wherever you installed Archipelago.
3. **Generate a multiworld with an SMO slot.** If this is your first time
   using Archipelago at all, the short version:
   1. Open the Archipelago Launcher and click *Generate Template*. This
      writes a YAML stub for every installed game into your `Players/`
      directory; find the one labeled **Spicy Meatball Overdrive**
      (that's how this apworld registers).
   2. Edit the YAML to set your `name` and any options you care about
      (defaults are sensible — see the *Include...* toggles' inline
      docstrings for the per-toggle impact).
   3. Click *Generate*. The Launcher produces a per-player zip in
      `output/`. Extract it; alongside the usual `.archipelago` /
      `.zip` files you'll find a `<player>.smoap` — that's your
      personal "join this multiworld as this slot" file.
   See AP's
   [Setting up a YAML](https://archipelago.gg/tutorial/Archipelago/setup/en)
   tutorial for the longer walkthrough.
4. **Double-click your `.smoap` file.** Archipelago Launcher routes it to
   **SMO Client** (that's how the entry appears in the Launcher's Clients
   list). On first run, SMO Client notices you haven't set up yet and
   opens the setup wizard.
5. **Walk the wizard.** Eight pages, in order:
   1. Welcome — read the overview.
   2. Prerequisites — wizard checks the table above; click "Install..." for
      anything missing, install it, click "Re-check".
   3. SMO NSP picker — browse to your SMO 1.0.0 NSP.
   4. Extract maps — wizard runs the extractor (~30s the first time
      because it sets up a Python 3.12 venv with `oead`, then faster on
      re-runs). Outputs land in `%APPDATA%/SMOArchipelago/data/`.
   5. Bridge PC IP — wizard pre-fills the IP it thinks your Switch should
      use to reach this PC. Confirm or override. This IP is baked into the
      Switch module — changing it later requires re-running setup.
   6. Build Switch module — wizard runs `sync_capture_table.py` then
      `cmake -G Ninja -DBRIDGE_HOST=<your ip>` then `cmake --build`.
      Takes about a minute end to end.
   7. Deploy target — usually **Real Switch (SD card)**:
      - **SD card:** wizard auto-detects mounted drives with an
        `atmosphere/` directory; pick yours or browse to it. Files land
        at `<drive>:\atmosphere\contents\0100000000010000\`. Eject the
        SD card and plug it into your modded Switch.
      - **Custom folder:** writes the same `atmosphere/contents/...`
        subtree under a folder of your choice — useful if you sync your
        SD card through DBI, Goldleaf, a network share, or UMS later.
      - **Ryujinx:** if you happen to already have Ryujinx set up
        locally, it's a supported target — the wizard copies to
        `%APPDATA%/Ryujinx/mods/contents/...`. (Ryujinx itself is no
        longer publicly distributed; the wizard works with whichever
        copy you already have.)
   8. Done — click "Launch SMOClient now" to immediately connect to the
      multiworld using the slot the `.smoap` file specified.
6. **Boot SMO.** On your Switch (or in Ryujinx, if that's where you
   deployed) — the mod loads on game start.
   It dials the bridge PC every couple seconds until SMOClient is listening
   (port 17777 by default); the SMOClient GUI flips from "waiting for
   Switch" to "ready" the moment HELLO arrives.

## After setup

Joining additional multiworlds is just **double-click the `.smoap`**. The
wizard runs only on first launch (and on `/setup` from the SMOClient
command bar if you want to re-trigger it explicitly). Subsequent launches
go straight to SMOClient with the slot name pre-filled in the Connect bar.

## Troubleshooting

### "Prerequisite missing" but I installed it

Open a fresh terminal — `cmake`, `ninja`, and `hactool` are PATH-based, and
a shell that was open before you installed them won't see them. devkitPro's
`DEVKITPRO` env var also needs a fresh shell. Re-launch the wizard from the
Archipelago Launcher and click "Re-check".

### Extraction fails with "oead build failed"

Confirm you actually have Python 3.12 (not 3.13). The wizard's prereq check
finds it via `py -3.12` on Windows; if you have Python 3.13 installed but
not 3.12, `oead` has no wheel for 3.13 and pip will try to build it from
source (slow + fragile). Install Python 3.12 from
https://www.python.org/downloads/release/python-3120/#files alongside any
other Pythons.

### Build fails with "aarch64-none-elf-g++ not found"

devkitPro didn't install devkitA64. Re-run the devkitPro installer and
make sure the "Switch development" component is selected. The wizard's
prereq check verifies the cross-compiler binary, not just the env var.

### Switch boots SMO but the mod doesn't load

Check the mod log on the SD card / Ryujinx sd folder at
`atmosphere/contents/0100000000010000/smoap.log`. Most often the cause is
the bridge PC's firewall blocking inbound port 17777, or the IP baked into
the mod doesn't match the bridge PC's current IP (LAN reassignment). Use
`/setup` in SMOClient to re-run the wizard with the new IP.

### "Wizard launched but window doesn't show up"

Kivy can be slow to spin up the first time (3-10s on cold start). If
nothing appears after 30s, check the Archipelago Launcher's log window for
errors — most likely a missing Kivy dependency (re-run AP's setup) or a
DPI scaling issue on Windows (try `set KIVY_DPI=96` before launching).

## Reset / re-run

If anything goes wrong and you want a clean slate:

```pwsh
# Delete all wizard outputs (will trigger setup on next .smoap open):
Remove-Item -Recurse -Force "$env:APPDATA\SMOArchipelago"
```

Or, from inside a running SMOClient, type `/setup` in the command bar —
that spawns the wizard in a fresh window without wiping anything; the
wizard's pages remember what's already been done so you can re-run only
the steps you actually changed (e.g. only the Bridge-IP and Build pages
if you just moved to a new LAN).
