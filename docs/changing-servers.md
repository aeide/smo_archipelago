# Changing servers, slots, and your PC

There are two categories of "I want to change something" — they have very
different costs. Knowing which is which saves time.

## TL;DR

| What you want to change | Rebuild required? | How |
|---|---|---|
| AP server address (host:port) | **No.** | Open SMO Client from the Archipelago Launcher, type the host/port and slot name into the **Connect** bar at the top of the window, and click **Connect**. A `.smoap` file is **not** needed; if you happen to have one from the organizer, double-clicking it just pre-fills the slot. |
| AP slot name | **No.** | Same as above: type your slot name into SMO Client's **Connect** bar and click **Connect**. |
| AP password | **No.** | Type it into the password field next to the **Connect** bar, then click **Connect**. |
| Switch listen port (PC side) | **No.** | Edit `host.yaml` or pass `--switch-port`. |
| Your PC's LAN IP | **Yes.** Re-run the setup wizard. | Open SMO Client from the Archipelago Launcher and type `/setup` in the command bar. |
| Switching to a different PC | **Yes.** Set up on the new PC. | Run the wizard on the new PC. |

## Per-session: server, slot, password

These all live in SMO Client's runtime configuration. The Switch mod doesn't
know or care about them — it only knows about your PC's LAN IP. So changing
any of these is a click-and-type operation, never a rebuild.

### From the SMO Client GUI

Type the host/port (e.g. `archipelago.gg:38281`) into the **Connect** bar
at the top of the SMO Client window, your slot name into the slot field,
and click **Connect**. To switch hosts mid-session, just clear the field,
type the new one, and click **Connect** again — SMO Client will disconnect
from the old server and connect to the new one.

### By double-clicking a `.smoap` file (optional convenience)

If the multiworld's organizer hands you a `<player>.smoap` file, you can
double-click it instead of typing the slot name by hand — Archipelago
Launcher routes it through to SMO Client with the slot name pre-filled.
If the `.smoap`'s optional host field is also set, the Connect bar is
pre-populated too; otherwise type it in and click **Connect**.

`.smoap` files are convenience, not a requirement. You can always join a
multiworld by opening SMO Client from the Archipelago Launcher and typing
the host/port and slot name into the Connect bar yourself.

### Per-session DeathLink toggle

The default is set in `host.yaml` (`smo_options.deathlink_default`). To
override for a single launch, pass `--deathlink` on the CLI. The Switch
mod respects whatever SMO Client tells it during the HELLO handshake, so
flipping the flag mid-session requires a SMO Client restart but no rebuild.

## Per-machine: your PC's LAN IP

This is the rebuild-required case. Your PC's IP is baked into the Switch
module (`subsdk9`) at compile time, because retail Switch firmware doesn't
let our module read configuration from the SD card at runtime.

You need to re-run the wizard when:

- You move to a new LAN with a different IP range
- Your router gave you a different DHCP lease and the old IP no longer works
- You switch to using a different PC to run SMO Client

### Quickest path

1. Open SMO Client from the Archipelago Launcher (click "SMO Client" in
   the Clients list).
2. Type `/setup` in the command bar.
3. The wizard opens in a fresh window. Walk forward — you can usually
   skip-by-rechecking the prereqs and extraction pages (their outputs are
   cached at `%APPDATA%/SMOArchipelago/data/`), edit the PC IP page with
   the new value, let it rebuild, and re-deploy.
4. Restart your Switch / Ryujinx so it picks up the new module.

### What the wizard does behind the scenes

`cmake` reconfigures with the new IP, recompiles, and re-deploys the
resulting `subsdk9` to the same destination you picked originally (SD card
or Ryujinx). Build takes about a minute. The Switch mod reconnects to the
new IP on next boot.

## Per-machine: deploy target (SD ↔ Ryujinx)

If you developed against Ryujinx and now want to play on a real Switch (or
vice versa), re-run setup and pick the other deploy target. **No rebuild
needed** — the build artifacts (`subsdk9`, `main.npdm`, `ap_config.json`)
are the same bytes for both targets. The wizard remembers your last choice
in `%APPDATA%/SMOArchipelago/setup_state.json`, so subsequent re-runs
default to that target.

## What never needs a rebuild

Nothing else does. Items, locations, regions, options, the apworld's
internal logic — those all live in the apworld zip, which is loaded fresh
every time SMO Client or AP-server starts. Update the apworld by replacing
the file in `custom_worlds/` and restarting.

A Switch-mod **wire-protocol** change (rare; new message types added
between SMO Archipelago releases) does require both an updated SMO Client
AND a re-deployed Switch module. The wizard's `/setup` flow handles both
in one shot.
