# Bot Scape icons

`hub.svg` / `hub-*.png` / `hub.ico` are the launcher dashboard mark: gold frame,
three dashboard tiles and a green play control. Its square silhouette distinguishes
the hub from the game client's robot shield. PNG and ICO sizes: 16, 24, 32, 48,
64, 128 and 256 px. Transparent corners work on dark and light taskbars.

Rebuild with `python assets/brand/generate.py` (Pillow and fontTools; Windows
Georgia Bold and Segoe UI fonts). The hub SVG geometry is defined by `hub_emblem()`
in the generator, on a 16 px grid, and used for every raster export. The command
also rebuilds the existing brand assets without changing the client design.
`preview.html` and `hub-comparison.png` show before/after native ICO frames.

The game client retains `logo.svg`, `logo-*.png`, `app.ico` and `runelite/`.
Do not point `launcher/fetch_runelite.py` at the hub assets.

Build the Windows launcher with:

```
dotnet build launcher/stub/BotScape.csproj -c Release
```

The result is `launcher/stub/bin/Release/net48/BotScape.exe`; packaging copies
it to the installed root. Its embedded hub icon also supplies the updater icon
and any desktop/Start menu shortcut that targets this executable. An installer
should use `BotScape.exe,0` as IconLocation and `BotScape.Hub` as AppUserModelID.
On startup the stub repairs icons/identity on existing shortcuts targeting this
exact executable in the current user's desktop and Start menu. It preserves the
existing policy of creating no new shortcuts. The installer is external to this
repository.

`LAUNCHER.pyw` opens Edge with its existing dedicated profile. The favicon is
`/brand/hub.ico`. `launcher/hub-window.ps1` loads `launcher/HubWindow.cs` to set
the native window icons and Windows shell identity/relaunch data only for that
profile's browser process. It stays alive while that browser does, to keep native
icon handles valid and handle new app windows/DPI changes. Embedded mode leaves
the containing launcher's native window alone. Browser fallback uses the favicon.
