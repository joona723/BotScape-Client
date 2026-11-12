"""Makes tools/runelite/lib/botscape-plugin.jar, the Bot Scape plugin the game client loads, when it's missing.

The player download ships the plugin built; a copy cloned from the BotScape-Client repository has only its source
(client-plugin/src and res). User-reported (2026-11-12): such a client was plain RuneLite, so it didn't log in by
itself and had no Scripts or Group panels. Open-RuneLite.bat runs this first:

- with a Java 21+ JDK (JAVA_HOME or javac on PATH) it builds the plugin from this folder's source, so the plugin
  you run is the code you can read;
- without one it downloads the same plugin the player download has, from zazuosu.com.

    python launcher/build_plugin.py [--force]
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "tools" / "runelite" / "lib"
JAR = LIB / "botscape-plugin.jar"
SRC = ROOT / "client-plugin" / "src"
RES = ROOT / "client-plugin" / "res"
DOWNLOAD = "https://zazuosu.com/downloads/botscape/tools/runelite/lib/botscape-plugin.jar"


def find_javac():
    """A javac of Java 21 or newer, or None."""
    names = ["javac.exe", "javac"]
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates += [Path(os.environ["JAVA_HOME"]) / "bin" / n for n in names]
    candidates += [Path(p) for p in (shutil.which("javac"),) if p]
    for javac in candidates:
        if not javac.is_file():
            continue
        try:
            out = subprocess.run([str(javac), "-version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"javac (\d+)", out.stdout + out.stderr)
        if m and int(m.group(1)) >= 21:
            return javac
    return None


def build(javac):
    sources = [str(p) for p in SRC.rglob("*.java")]
    classpath = os.pathsep.join(str(j) for j in LIB.glob("*.jar") if j.name != JAR.name)
    with tempfile.TemporaryDirectory() as out:
        result = subprocess.run([str(javac), "--release", "21", "-nowarn", "-encoding", "UTF-8", "-proc:full",
                                 "-cp", classpath, "-d", out, *sources], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout + result.stderr)
            return False
        tmp = JAR.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for base in (Path(out), RES):
                for path in base.rglob("*"):
                    if path.is_file():
                        z.write(path, path.relative_to(base).as_posix())
        tmp.replace(JAR)
    return True


def download():
    req = urllib.request.Request(DOWNLOAD, headers={"User-Agent": "Mozilla/5.0 BotScape"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    JAR.write_bytes(data)


def main():
    if JAR.exists() and "--force" not in sys.argv:
        return 0
    if not any(LIB.glob("*.jar")):
        print("The game client isn't downloaded yet (run launcher/fetch_runelite.py first).")
        return 1
    javac = find_javac() if SRC.is_dir() else None
    if javac:
        print(f"Building the Bot Scape plugin from client-plugin/src with {javac}...")
        if build(javac):
            print(f"Built {JAR}")
            return 0
        print("The build failed; downloading the plugin from zazuosu.com instead.")
    else:
        print("No Java 21+ JDK found (JAVA_HOME or javac): downloading the plugin from zazuosu.com.")
    try:
        download()
    except OSError as e:
        print(f"Couldn't download the plugin: {e}")
        return 1
    print(f"Downloaded {JAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
