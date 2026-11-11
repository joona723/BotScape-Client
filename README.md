# Bot Scape: hub and client

The source of what players install for **Bot Scape** (the OSRS-style bot server at zazuosu.com): the hub
window, the game client patcher, the RuneLite plugin, the Python SDK the scripts use, and the launcher exe.
The game server is not in this repository.

This repository is a copy, made from the main project with `tools/export_client_repo.py`; it's here so
anyone can read exactly what the player package does.

## What's here

| Path | What it is |
| --- | --- |
| `launcher/stub/Program.cs` | `BotScape.exe`: checks `https://zazuosu.com/downloads/botscape/manifest.json` for updates, downloads changed files, opens the hub |
| `LAUNCHER.pyw`, `launcher/ui/` | The hub: a local web app on `http://127.0.0.1:8090`, shown in its own Edge app window. Runs your scripts, shows the group, bank, map |
| `launcher/hub-window.ps1`, `launcher/HubWindow.cs` | The hub's window |
| `launcher/fetch_runelite.py` | Downloads RuneLite 1.11.19 from RuneLite's own servers (checked against RuneLite's sha256 list) and patches it to log in to the Bot Scape server |
| `launcher/client-key.txt` | The Bot Scape server's public RSA key, which the patcher puts in the client |
| `Open-RuneLite.bat` | Starts the patched client |
| `client-plugin/` | The Bot Scape RuneLite plugin (scripts, group, bank, live map panels) |
| `sdk/` | The Python SDK scripts use to control your character through the server |
| `scripts/templates/`, `scripts/botscape/Lumby Chicken Killer.py` | The script template and an example script |
| `assets/` | Icons and artwork |
| `launcher/build_package.py` | How the player package is assembled (also downloads Python from python.org and Java 21 from adoptium.net) |

## What the client patch changes

`fetch_runelite.py` takes the official RuneLite jars and changes only what's needed to play on Bot Scape
instead of Jagex's servers: the login RSA key (to the Bot Scape key above), the check that the game
config comes from `.jagex.com`, the window title, icons and splash (Bot Scape's), RuneLite's Discord presence
(off), and it strips the jar signatures those edits invalidate.

## Where it connects

- `zazuosu.com`: sign-in, updates (`/downloads/botscape/`), profile pictures, hiscores
- `botscape.zazuosu.com`: the game server (game port 43594, bot gateway 7780, client config 8080)
- RuneLite's servers, python.org and adoptium.net: only to download the official RuneLite, Python and Java

## Building

- `BotScape.exe`: `dotnet build launcher/stub/BotScape.csproj -c Release` (.NET Framework 4.8)
- The plugin: `javac --release 21` against the RuneLite jars `fetch_runelite.py` downloads, then jar it
  together with `client-plugin/res`
