"""Downloads the RuneLite build matching the server's game revision (233) and patches it for Bot Scape.

    python launcher/fetch_runelite.py

Puts every artifact from RuneLite's bootstrap (checked against its sha256) in tools/runelite/lib,
then swaps the game's login RSA key in the injected client for the Bot Scape server's key, the same
way the RSProx launcher does, so the client logs in to our server directly.
"""

import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# RuneLite 1.11.19, the build for OSRS revision 233 (see RSProx's revision table).
COMMIT = "cea91b9921a3647683ba8a5c22ec75c752c91b07"
BOOTSTRAP = f"https://raw.githubusercontent.com/runelite/static.runelite.net/{COMMIT}/bootstrap.json"
LIB = ROOT / "tools" / "runelite" / "lib"
KEY_FILE = ROOT / "rsmod" / ".data" / "client.key"
# Player installs have no server: just the public modulus (never the private key).
if not KEY_FILE.exists():
    KEY_FILE = ROOT / "launcher" / "client-key.txt"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BotScape/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def windows_artifact(name):
    natives = re.search(r"natives-([a-z0-9-]+)\.jar$", name)
    return natives is None or natives.group(1) == "windows"


def main():
    LIB.mkdir(parents=True, exist_ok=True)
    bootstrap = json.loads(fetch(BOOTSTRAP))
    (LIB.parent / "bootstrap.json").write_text(json.dumps(bootstrap, indent=2), encoding="utf-8")
    artifacts = [a for a in bootstrap["artifacts"] if windows_artifact(a["name"])]
    for done, artifact in enumerate(artifacts, 1):
        name = artifact["name"]
        # The hub shows this while the client gets ready (user-requested 2026-11-12: nothing showed for minutes).
        print(f"progress {done}/{len(artifacts)}", flush=True)
        target = LIB / name
        if (LIB.parent / "original" / name).exists():
            continue  # patched copy lives in lib
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == artifact["hash"]:
            continue
        data = fetch(artifact["path"])
        if hashlib.sha256(data).hexdigest() != artifact["hash"]:
            sys.exit(f"Hash mismatch for {name}")
        target.write_bytes(data)
        print(f"downloaded {name}")
    patch_rsa()
    patch_config_host()
    print("RuneLite is ready in", LIB)


# RuneLite's window icons and startup splash -> the Bot Scape emblem (assets/brand, drawn by Codex).
BRAND_IMAGES = {
    "net/runelite/client/ui/runelite_16.png": ("logo-64.png", 16),
    "net/runelite/client/ui/runelite_128.png": ("logo-128.png", 128),
    "net/runelite/client/ui/runelite_splash.png": ("logo-256.png", 200),
}


def brand_image(source, size):
    # Pre-rendered at this size (the player package has them; it ships without Pillow).
    rendered = ROOT / "assets" / "brand" / "runelite" / f"{Path(source).stem}-{size}.png"
    if rendered.exists():
        return rendered.read_bytes()
    path = ROOT / "assets" / "brand" / source
    if not path.exists():
        return None
    from io import BytesIO

    from PIL import Image

    image = Image.open(path).convert("RGBA")
    image.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2), image)
    out = BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def unsigned(name, data):
    """Entries for a patched jar: drop the jar signature, which no longer matches."""
    upper = name.upper()
    if upper.startswith("META-INF/") and upper.endswith((".SF", ".RSA", ".DSA", ".EC")):
        return None
    if upper == "META-INF/MANIFEST.MF":
        # Keep only the main section; the per-entry SHA-256 digests follow the first blank line.
        main_section = data.split(bytes([13, 10, 13, 10]), 1)[0]
        return main_section + bytes([13, 10, 13, 10])
    return data


def patch_config_host():
    """RuneLite only loads jav_config from *.jagex.com or *.runescape.com; allow any host (the Bot
    Scape server may be 127.0.0.1 or zazuosu.com).

    The check is `host.endsWith(".jagex.com")` in ClientLoader.downloadConfig; its string constant
    becomes "" (every host ends with it). Class-file string constants carry their own length, so the
    edit is safe. The patched jar's name changed with this (botscape-anyhost-...), so Open-RuneLite.bat
    re-patches installs made with the old 127.0.0.1-only patch; that old jar is removed.
    """
    source = next((LIB.parent / "original").glob("client-*.jar"), None) or next(LIB.glob("client-*.jar"))
    original = LIB.parent / "original" / source.name
    if source.parent == LIB:
        original.parent.mkdir(exist_ok=True)
        source.replace(original)
    old = bytes([1, 0, 10]) + b".jagex.com"  # CONSTANT_Utf8, length 10
    new = bytes([1, 0, 0])
    for old_jar in LIB.glob("botscape-client-*.jar"):
        old_jar.unlink()  # the earlier 127.0.0.1-only patch: two patched clients on the classpath clash
    patched = LIB / ("botscape-anyhost-" + source.name)
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "net/runelite/client/rs/ClientLoader.class":
                if data.count(old) != 1:
                    sys.exit("Unexpected ClientLoader: jav_config host check not found")
                data = data.replace(old, new)
            if info.filename in BRAND_IMAGES:
                data = brand_image(*BRAND_IMAGES[info.filename]) or data
            if info.filename == "net/runelite/client/runelite.properties":
                # Our own name in the title bar, and no RuneLite Discord presence.
                data = (data.replace(b"runelite.title=RuneLite", b"runelite.title=Bot Scape")
                        .replace(b"runelite.discord.enable=true", b"runelite.discord.enable=false"))
            data = unsigned(info.filename, data)
            if data is not None:
                out.writestr(info, data)
    print(f"allowed any jav_config host in {patched.name}")


def patch_rsa():
    modulus = next(line.split(":", 1)[1].strip() for line in KEY_FILE.read_text().splitlines()
                   if line.lower().startswith("modulus:"))
    source = next((LIB.parent / "original").glob("injected-client-*.jar"), None)
    if source is None:
        source = next(LIB.glob("injected-client-*.jar"))
        (LIB.parent / "original").mkdir(exist_ok=True)
        source = source.replace(LIB.parent / "original" / source.name)
    # The game itself refuses hosts other than Jagex's and local ones (error_game_invalidhost): its
    # check ends with host.endsWith(".jagex.com"), and that constant becomes "" (every host ends with
    # it) in the class that holds the check (the one with "invalidhost"). The jar's new name makes
    # Open-RuneLite.bat re-patch installs made before this; the old jar is removed (two clash).
    (LIB / "botscape-injected-client.jar").unlink(missing_ok=True)
    patched = LIB / "botscape-injected-anyhost-client.jar"
    ours = modulus.lower().encode()
    found = 0
    hosts = 0
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".class") and not info.filename.startswith("org/"):
                for match in re.finditer(rb"(?<![0-9a-f])[0-9a-f]{%d}(?![0-9a-f])" % len(ours), data):
                    data = data[:match.start()] + ours + data[match.end():]
                    found += 1
                if b"invalidhost" in data and bytes([1, 0, 10]) + b".jagex.com" in data:
                    data = data.replace(bytes([1, 0, 10]) + b".jagex.com", bytes([1, 0, 0]), 1)
                    hosts += 1
            data = unsigned(info.filename, data)
            if data is not None:
                out.writestr(info, data)
    if found != 1:
        sys.exit(f"Expected one RSA key in {source.name}, found {found}")
    if hosts != 1:
        sys.exit(f"Expected one host check in {source.name}, found {hosts}")
    print(f"patched login key in {source.name} -> {patched.name}")


if __name__ == "__main__":
    main()
