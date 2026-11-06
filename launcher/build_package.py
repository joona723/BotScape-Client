"""Builds the Bot Scape player package and its download manifest.

    python launcher/build_package.py            -> dist/botscape/ + dist/botscape/manifest.json

The package is what the Zazuosu launcher installs (kind "files": every file listed with its size and
an id that changes when the file does) and what BotScape.exe updates from:

    BotScape.exe              the Bot Scape launcher (update check, desktop shortcut, opens the hub)
    LAUNCHER.pyw, launcher/   the hub (its window) and the client downloader/patcher
    CLIENT.bat                opens the game client
    sdk/, scripts/templates/  the Python SDK and the script template (not our script pack)
    assets/                   icons and artwork
    runtime/python/           Python (the official embeddable build)
    runtime/jre/              Java 21 (Eclipse Temurin JRE) for the game client

Not included: the RuneLite client itself (downloaded from RuneLite's own servers on the player's PC
the first time they play, then patched there) and anything private (server keys, saves).
Copy dist/botscape/ to the zazuosu server's downloads/botscape/ to publish it.
"""
import hashlib
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "botscape"
CACHE = ROOT / "tools" / "package-cache"
BASE_URL = "https://zazuosu.com/downloads/botscape/"

PYTHON_URL = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip"
JRE_URL = "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"

# (source, destination) pairs; directories are copied recursively.
CONTENT = [
    ("LAUNCHER.pyw", "LAUNCHER.pyw"),
    ("launcher/ui", "launcher/ui"),
    ("launcher/fetch_runelite.py", "launcher/fetch_runelite.py"),
    ("launcher/hub-window.ps1", "launcher/hub-window.ps1"),
    ("launcher/HubWindow.cs", "launcher/HubWindow.cs"),
    ("launcher/package/CLIENT.bat", "CLIENT.bat"),
    ("launcher/stub/bin/Release/net48/BotScape.exe", "BotScape.exe"),
    ("launcher/stub/bin/Release/net48/BotScape.exe.config", "BotScape.exe.config"),
    ("sdk", "sdk"),
    # Not the Bot Scape script pack (scripts/botscape): it stays on the host PC (2026-10-30).
    # Only these Bot Scape originals ship with the game (they show under "Bot Scape scripts").
    ("scripts/botscape/Lumby Chicken Killer.py", "scripts/botscape/Lumby Chicken Killer.py"),
    ("scripts/templates", "scripts/templates"),
    ("assets/icons", "assets/icons"),
    ("assets/brand", "assets/brand"),
    ("assets/ui", "assets/ui"),
    ("tools/runelite/lib/botscape-plugin.jar", "tools/runelite/lib/botscape-plugin.jar"),
]
SKIP_PARTS = {"__pycache__", ".git", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".bak", ".log", ".orig"}


def fetch_cached(url, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print("downloading", url)
        req = urllib.request.Request(url, headers={"User-Agent": "BotScape-build/1.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            path.write_bytes(resp.read())
    return path


def copy(src, dst):
    if src.is_dir():
        for file in src.rglob("*"):
            if file.is_file() and not (SKIP_PARTS & set(file.parts)) and file.suffix not in SKIP_SUFFIXES \
                    and ".bak" not in file.name:
                target = dst / file.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def add_python():
    target = DIST / "runtime" / "python"
    with zipfile.ZipFile(fetch_cached(PYTHON_URL, "python-embed.zip")) as z:
        z.extractall(target)
    # The ._pth file would put Python in isolated mode, which leaves the script's own folder off
    # sys.path (the scripts import their lib/ from there): without it Python finds its stdlib zip
    # next to the exe as usual.
    for pth in target.glob("python*._pth"):
        pth.unlink()


def add_jre():
    target = DIST / "runtime" / "jre"
    with zipfile.ZipFile(fetch_cached(JRE_URL, "temurin-jre21.zip")) as z:
        top = z.namelist()[0].split("/")[0]
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename[len(top) + 1:]
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))


def add_public_key():
    """Only the RSA modulus (public), for patching the client: never the private key."""
    key = (ROOT / "rsmod" / ".data" / "client.key").read_text()
    modulus = next(line for line in key.splitlines() if line.lower().startswith("modulus:"))
    (DIST / "launcher").mkdir(parents=True, exist_ok=True)
    (DIST / "launcher" / "client-key.txt").write_text(modulus + "\n")


def manifest(version):
    files = []
    for file in sorted(DIST.rglob("*")):
        if not file.is_file() or file.name in ("manifest.json",):
            continue
        rel = file.relative_to(DIST).as_posix()
        digest = hashlib.sha1(file.read_bytes()).hexdigest()[:16]
        files.append({"path": rel, "size": file.stat().st_size, "id": f"{file.stat().st_size}-{digest}"})
    return {"version": version, "notes": f"Bot Scape {version}", "base": BASE_URL, "files": files}


def main():
    stub = ROOT / "launcher/stub/bin/Release/net48/BotScape.exe"
    if not stub.exists():
        sys.exit("Build BotScape.exe first: dotnet build launcher/stub/BotScape.csproj -c Release")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for src, dst in CONTENT:
        copy(ROOT / src, DIST / dst)
    add_public_key()
    add_python()
    add_jre()
    version = time.strftime("%Y.%m.%d.%H%M")
    (DIST / "version.txt").write_text(version)
    data = manifest(version)
    (DIST / "manifest.json").write_text(json.dumps(data, separators=(",", ":")))
    size = sum(f["size"] for f in data["files"])
    print(f"Bot Scape {version}: {len(data['files'])} files, {size / 1e6:.0f} MB -> {DIST}")


if __name__ == "__main__":
    main()
