"""Bot Scape launcher: run scripts on your character and your group members, watch them on the live map.

    pythonw LAUNCHER.pyw [main-character]

A small local web app: this file runs the backend (scripts, output, auto-added members) on
http://127.0.0.1:8090 and opens the interface in its own app window (Edge, no browser bars).
Closing the window stops your scripts and the launcher.

Settings (server address, your main character) live in launcher/settings.json. This is the
players' app; running the game server is done with the host tools (SERVER.bat / STOP.bat).
"""

import ast
import base64
import json
import os
import socket
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "launcher" / "ui"
SETTINGS_FILE = ROOT / "launcher" / "settings.json"
# The host's own hub (next to the server) on 8090; a player install on 8092, so both can run on one PC.
PORT = 8090 if (ROOT / "SERVER.bat").exists() else 8092


def _arg(name, default=None):
    """The value after a command-line flag (e.g. --server 192.168.1.5)."""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


# Embedded mode: the Zazuosu launcher shows this hub inside its own window. No window of our own,
# sign-in with the player's zazuosu.com account (token in ZAZUOSU_TOKEN), and we exit when the
# launcher does (--parent-pid).
EMBEDDED = "--embedded" in sys.argv
if EMBEDDED:
    PORT = int(_arg("--port", "8091"))
    # Its own settings: the character comes from the zazuosu sign-in, never a local default.
    SETTINGS_FILE = ROOT / "launcher" / "settings-embedded.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LEVELS_PER_CLONE = 100
def member_names(main, count):
    """Names for group members added automatically, after the main character: simba1, simba2, ...
    (the main's name is shortened so each fits the 12-letter limit). User-requested 2026-10-30;
    numbered from 1 since 2026-10-31. Members can be renamed later."""
    for n in range(1, count + 1):
        yield main[:12 - len(str(n))].rstrip() + str(n)
# Players' installs (no SERVER.bat) connect to the hosted server; a PC with the server on it talks to itself.
DEFAULT_SERVER = "127.0.0.1" if (ROOT / "SERVER.bat").exists() else "botscape.zazuosu.com"
DEFAULT_SETTINGS = {"main": "", "server": DEFAULT_SERVER, "auto_clone": False}


# --- settings ------------------------------------------------------------------------------------

def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if EMBEDDED:
        settings["main"] = ""
    try:
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        settings["main"] = sys.argv[1].lower()
    if _arg("--server"):
        settings["server"] = _arg("--server")
    return settings


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


SETTINGS = load_settings()


def server_host():
    return SETTINGS.get("server") or DEFAULT_SERVER


def gateway_url():
    return f"http://{server_host()}:7780"


def map_url():
    return f"http://{server_host()}:8080"


def is_host():
    """This computer runs the game server (it has it installed and talks to itself)."""
    if EMBEDDED:
        return False  # a player's launcher: always signs in as the player, never as the host
    return (ROOT / "SERVER.bat").exists() and server_host() in ("127.0.0.1", "localhost")


def bot_dir(main=None):
    return ROOT / "bots" / (main or SETTINGS["main"])


def read_env(main=None):
    env = {}
    path = bot_dir(main) / "bot.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


# --- talking to the server -----------------------------------------------------------------------

ADMIN_KEY_FILE = ROOT / "rsmod" / ".data" / "gateway-admin.key"
AUTH = {"token": None}


ZAZUOSU = {"status": "signed-out", "error": None, "retry_at": 0}
# The zazuosu account's profile (name and picture) for the header's profile button.
PROFILE = {"name": None, "avatar": None}
# User-requested: the hub notices a new Bot Scape version by itself (every 10 minutes) and offers to
# update; BotScape.exe installs it and opens the hub again. Not on the host PC or inside the Zazuosu
# launcher (that one updates the game itself).
UPDATE = {"latest": None}
MANIFEST_URL = "https://zazuosu.com/downloads/botscape/manifest.json"
NEWS_URL = "https://zazuosu.com/osrs/api/news"
NEWS = {"at": 0.0, "posts": []}


def installed_version():
    try:
        return (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def check_update(_body=None):
    """Asks zazuosu.com for the newest version; an error text if it can't be reached."""
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "BotScape-hub"})
        with urllib.request.urlopen(req, timeout=15) as r:
            latest = json.load(r).get("version")
    except Exception:
        return "Couldn't reach zazuosu.com to check for updates."
    UPDATE["latest"] = latest if latest and latest != installed_version() else None
    return None


AUTO_UPDATE_DELAY = 30   # seconds between finding a new version and installing it


def update_check_loop():
    """User-requested: updates are applied by themselves. Every 2 minutes it asks for a new version;
    when there is one it counts down 30 seconds (shown on the update button) and installs it
    (running scripts carry over, game clients reopen)."""
    while True:
        check_update()
        if UPDATE["latest"]:
            UPDATE["applyAt"] = UPDATE.get("applyAt") or time.time() + AUTO_UPDATE_DELAY
            while time.time() < UPDATE["applyAt"]:
                time.sleep(1)
            if not update_now({}):
                return          # the hub closes for the update
            UPDATE["applyAt"] = None
        time.sleep(120)


def player_install():
    """An installed copy of Bot Scape (updates itself). A development folder (git, or the server's
    SERVER.bat) never does: its files come from the developer, an update would overwrite them."""
    return (ROOT / "BotScape.exe").exists() and not (ROOT / ".git").exists() and not (ROOT / "SERVER.bat").exists()


def update_now(_body):
    """Close this hub (scripts stop) and let BotScape.exe install the update and reopen it."""
    if not player_install():
        return "This is a development folder: it doesn't update itself."
    stub = ROOT / "BotScape.exe"
    if not stub.exists():
        return "BotScape.exe is missing: reinstall Bot Scape."
    scripts = {who: RUNNER.scripts.get(who) for who in RUNNER.running()}
    RUNNER.stop_all()
    # The game clients get the new client too: close them now, reopen them after the update; the
    # scripts that were running carry on in the new version.
    reopen = close_game_clients()
    try:
        REOPEN_FILE.write_text(json.dumps({"clients": reopen, "scripts": scripts}), encoding="utf-8")
    except OSError:
        pass
    subprocess.Popen([str(stub)] + [a for a in sys.argv[1:]], cwd=ROOT)
    close_launcher_windows()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return None


REOPEN_FILE = ROOT / "launcher" / "reopen-clients.json"


def close_game_clients():
    """Closes this install's Bot Scape game clients; returns who they were logged in as."""
    query = ("Get-CimInstance Win32_Process -Filter \"Name='javaw.exe' or Name='java.exe'\" | "
             "? { $_.CommandLine -like '*botscape.root=" + str(ROOT).replace("'", "''") + "*' } | "
             "% { $_.CommandLine + '|' + $_.ProcessId }")
    names = []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-c", query], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return names
    for line in out.splitlines():
        command, _, pid = line.rpartition("|")
        m = re.search(r"-Dbotscape\.login=([^\s\"]*)", command)
        names.append(m.group(1) if m else "")
        if pid.strip().isdigit():
            # /t: the scripts the client started go too (it picks them up again when it reopens).
            subprocess.run(["taskkill", "/pid", pid.strip(), "/t", "/f"], capture_output=True, creationflags=NO_WINDOW)
    return names


def reopen_game_clients():
    """After an update: open the game clients the update closed (as the same characters)."""
    try:
        names = json.loads(REOPEN_FILE.read_text(encoding="utf-8"))
        REOPEN_FILE.unlink()
    except (OSError, ValueError):
        return
    clients = names.get("clients", []) if isinstance(names, dict) else names
    scripts = names.get("scripts", {}) if isinstance(names, dict) else {}
    for name in clients:
        open_client(name or None)
    if scripts:
        with RUNNER.lock:
            RUNNER.resume.update({who: script for who, script in scripts.items() if script})


def close_launcher_windows():
    query = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "? { $_.CommandLine -like '*.launcher-window*' } | % { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-c", query], creationflags=NO_WINDOW)
    except OSError:
        pass
ZAZUOSU_WEB = os.environ.get("BOTSCAPE_ZAZUOSU_URL", "https://zazuosu.com").rstrip("/")


# Signed in from the hub's own window (not through the Zazuosu launcher): the zazuosu session.
ZAZUOSU_SESSION_FILE = ROOT / "launcher" / "zazuosu-session.txt"


def zazuosu_token():
    token = os.environ.get("ZAZUOSU_TOKEN", "") or ZAZUOSU_ARG or ZAZUOSU.get("token") or ""
    if not token and ZAZUOSU_SESSION_FILE.exists():
        token = ZAZUOSU_SESSION_FILE.read_text(encoding="utf-8").strip()
    return token


def zazuosu_login(body):
    """User-requested: logged out, the hub asks for your zazuosu account (Log in or Create account,
    the same accounts as zazuosu.com and the Zazuosu launcher), then connects your character."""
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or not password:
        return "Enter your zazuosu username and password."
    route = "/register" if body.get("register") else "/login"
    req = urllib.request.Request(ZAZUOSU_WEB + route, method="POST",
                                 data=json.dumps({"username": username, "password": password}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "BotScape-hub"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            result = json.loads(e.read() or b"{}")
        except ValueError:
            result = {}
        return result.get("error") or f"zazuosu.com said no ({e.code})."
    except Exception:
        return "Couldn't reach zazuosu.com."
    token = result.get("token")
    if not token:
        return result.get("error") or "zazuosu.com didn't sign you in."
    ZAZUOSU_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    ZAZUOSU_SESSION_FILE.write_text(token, encoding="utf-8")
    ZAZUOSU.update(token=token, retry_at=0)
    if not zazuosu_sign_in():
        # Signed in to zazuosu; the character connects once the Bot Scape server answers.
        return None
    return None


def load_profile():
    """The zazuosu account's name and profile picture (GET /whoami with the launcher's token)."""
    token = zazuosu_token()
    if not token:
        return
    try:
        req = urllib.request.Request(ZAZUOSU_WEB + "/whoami", headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=5) as resp:
            me = json.loads(resp.read() or b"{}")
    except Exception:
        return
    avatar = me.get("avatarUrl")
    PROFILE.update(name=me.get("username"), avatar=(ZAZUOSU_WEB + avatar) if avatar and avatar.startswith("/") else avatar)


def set_avatar(body):
    """User-requested: change the zazuosu profile picture from the hub (the page crops it to a 256 px JPEG)."""
    token = zazuosu_token()
    if not token:
        return "Sign in with zazuosu to have a profile picture."
    image = str(body.get("image") or "")
    if not image:
        return "No picture picked."
    try:
        req = urllib.request.Request(ZAZUOSU_WEB + "/profile/avatar", method="POST",
                                     data=json.dumps({"mimeType": "image/jpeg", "imageBase64": image}).encode(),
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}").get("error") or f"zazuosu.com said {e.code}"
        except ValueError:
            return f"zazuosu.com said {e.code}"
    except Exception:
        return "Couldn't reach zazuosu.com."
    load_profile()
    return None


def logout():
    """Log out of Bot Scape here: forget the session (and, as a zazuosu player, the zazuosu sign-in;
    the Zazuosu launcher then asks for it again). A local account goes back to the account setup."""
    RUNNER.stop_all()
    AUTH["token"] = None
    if EMBEDDED:
        token = zazuosu_token()
        if token:
            try:
                req = urllib.request.Request(ZAZUOSU_WEB + "/logout", data=b"{}", method="POST",
                                             headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).close()
            except Exception:
                pass
        ZAZUOSU.update(status="signed-out", error="You logged out.")
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return None
    SETTINGS["main"] = ""
    save_settings(SETTINGS)
    PROFILE.update(name=None, avatar=None)
    # A zazuosu sign-in made in the hub's own window is forgotten too.
    ZAZUOSU.update(token=None, status="signed-out", error=None)
    try:
        ZAZUOSU_SESSION_FILE.unlink()
    except OSError:
        pass
    return None
# The Zazuosu launcher starts Bot Scape with --authtoken=<the player's zazuosu session>.
ZAZUOSU_ARG = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--authtoken=")), "")


def zazuosu_sign_in():
    """Embedded mode: sign in with the player's zazuosu.com account (the launcher's token). The
    server names their character after their zazuosu username and gives a fresh password, which the
    game client and scripts use (bots/<name>/bot.env)."""
    if time.time() < ZAZUOSU.get("retry_at", 0):
        return False
    ZAZUOSU["retry_at"] = time.time() + 15
    token = zazuosu_token()
    if not token:
        ZAZUOSU.update(status="error", error="The launcher didn't pass a zazuosu sign-in.")
        return False
    result = http("POST", gateway_url() + "/auth/zazuosu", {"token": token}, timeout=40, auth=False)
    if not result or not result.get("token"):
        ZAZUOSU.update(status="error", error=(result or {}).get("error") or "The Bot Scape server is offline.")
        return False
    name = result["name"]
    folder = bot_dir(name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bot.env").write_text(f"BOT_USERNAME={name}" + chr(10) + f"PASSWORD={result['password']}" + chr(10), encoding="utf-8")
    SETTINGS["main"] = name
    save_settings(SETTINGS)
    AUTH["token"] = result["token"]
    ZAZUOSU.update(status="signed-in", error=None)
    threading.Thread(target=load_profile, daemon=True).start()
    return True


def auth_headers():
    """The host uses the server's admin key; a player signs in with their own character."""
    if is_host() and ADMIN_KEY_FILE.exists():
        return {"X-Admin-Key": ADMIN_KEY_FILE.read_text().strip()}
    if EMBEDDED:
        # Only ever as the zazuosu account's own character.
        if not AUTH["token"] and not zazuosu_sign_in():
            return {}
        return {"Authorization": "Bearer " + AUTH["token"]}
    if not AUTH["token"]:
        password = read_env().get("PASSWORD")
        if password:
            result = http("POST", gateway_url() + "/auth", {"name": SETTINGS["main"], "password": password},
                          auth=False)
            AUTH["token"] = (result or {}).get("token")
    return {"Authorization": "Bearer " + AUTH["token"]} if AUTH["token"] else {}


HTTP_CONNS = threading.local()   # per thread: (scheme, host) -> a kept-alive connection


def http_send(method, url, data, headers, timeout):
    """(status, body) over a kept-alive connection per thread and server. User-reported: WMI Provider Host took the
    server PC's CPU walking ~11,000 closed connections; urllib opened (and closed) one for every request."""
    import http.client
    parts = urllib.parse.urlsplit(url)
    conns = HTTP_CONNS.__dict__.setdefault("by_host", {})
    key = (parts.scheme, parts.netloc)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    for attempt in range(2):
        conn = conns.get(key)
        if conn is None:
            kind = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
            conn = conns[key] = kind(parts.netloc, timeout=timeout)
        reused = conn.sock is not None
        conn.timeout = timeout
        if reused:
            conn.sock.settimeout(timeout)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.will_close:
                conn.close()
            return resp.status, body
        except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            conn.close()
            conns.pop(key, None)
            if not reused or attempt:   # only a stale kept-alive connection is worth one more try
                raise urllib.error.URLError("connection closed") from None
        except BaseException:
            conn.close()
            conns.pop(key, None)
            raise


def http(method, url, body=None, timeout=5, auth=True, _retry=True):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-BotScape-Via": "hub"}   # the server's login log (user-requested)
    if auth and url.startswith(gateway_url()):
        headers.update(auth_headers())
    status, raw = http_send(method, url, data, headers, timeout)
    if status >= 400:
        if status == 401 and auth and _retry and AUTH["token"] and url.startswith(gateway_url()):
            # The server restarted (an update) and forgot our sign-in: sign in again.
            AUTH["token"] = None
            return http(method, url, body, timeout, auth, _retry=False)
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"error": f"HTTP {status}"}
    return json.loads(raw or b"null")


def gw(method, path, body=None, timeout=5):
    return http(method, gateway_url() + path, body, timeout)


# --- scripts -------------------------------------------------------------------------------------

SKILL_WORDS = ["agility", "attack", "construction", "cooking", "crafting", "defence", "farming", "firemaking",
               "fishing", "fletching", "herblore", "hitpoints", "hunter", "magic", "mining", "prayer", "ranged",
               "runecrafting", "slayer", "smithing", "strength", "thieving", "woodcutting"]
SKILL_ALIASES = {"chop": "woodcutting", "mine": "mining", "thieve": "thieving", "fighter": "attack",
                 "quest": "quest", "jewellery": "crafting", "gear": "defence", "upgrade": "defence"}


def script_skill(name):
    low = name.lower()
    for skill in SKILL_WORDS:
        if skill in low:
            return skill
    for word, skill in SKILL_ALIASES.items():
        if word in low:
            return skill
    return None


def describe(path):
    """First line of the script's docstring."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r'^\s*(?:"""|\'\'\')\s*(.+?)$', text, re.M)
    if not match:
        return ""
    line = match.group(1).strip().rstrip('"').strip()
    return line[:180]


PACKAGED_SCRIPTS = ROOT / "scripts" / "botscape"   # ship with Bot Scape (updated with the game)


def script_entries(folder, source):
    entries = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.py"), key=lambda p: p.stem.lower()):
            if path.name.startswith("_") or path.name == "rs.py":
                continue
            entries.append({"id": f"{source}/{path.name}", "name": path.stem, "file": path.name,
                            "source": source, "description": describe(path), "skill": script_skill(path.stem),
                            "options": script_options(path), "icon": script_icon(path)})
    return entries


OPTIONS_CACHE = {}   # path -> (mtime, declared options)


def declared_options(path):
    """A script's OPTIONS = {"name": ("label", default), ...} (read without running it)."""
    mtime = path.stat().st_mtime
    cached = OPTIONS_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    found = []
    try:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OPTIONS" for t in node.targets):
                for name, (label, default) in ast.literal_eval(node.value).items():
                    kind = "bool" if isinstance(default, bool) else "int"
                    found.append({"key": str(name), "label": str(label), "type": kind,
                                  "default": bool(default) if kind == "bool" else int(default)})
    except (SyntaxError, ValueError, TypeError, OSError):
        found = []
    OPTIONS_CACHE[path] = (mtime, found)
    return found


def script_icon(path):
    """A script's ICON = "botscape" (the Bot Scape emblem: a Bot Scape original) or a skill's name."""
    try:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ICON" for t in node.targets):
                value = ast.literal_eval(node.value)
                return str(value).lower() if isinstance(value, str) else None
    except (SyntaxError, ValueError, OSError):
        pass
    return None


def read_options_file(folder):
    try:
        return json.loads((folder / ".options.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def script_options(path):
    """The script's options with the player's saved choices (shown as checkboxes on its card)."""
    saved = read_options_file(path.parent).get(path.name, {})
    out = []
    for o in declared_options(path):
        value = saved.get(o["key"], o["default"])
        try:
            value = bool(value) if o["type"] == "bool" else int(value)
        except (TypeError, ValueError):
            value = o["default"]
        out.append(dict(o, value=value))
    return out


def set_script_option(body):
    path = script_path(body.get("script", ""))
    if path is None or not path.exists():
        return "That script wasn't found."
    key = str(body.get("key", ""))
    option = next((o for o in declared_options(path) if o["key"] == key), None)
    if option is None:
        return f"{path.stem} has no option '{key}'."
    if option["type"] == "bool":
        value = bool(body.get("value"))
    else:
        try:
            value = max(0, min(1_000_000, int(body.get("value"))))
        except (TypeError, ValueError):
            return "Enter a whole number."
    data = read_options_file(path.parent)
    data.setdefault(path.name, {})[key] = value
    (path.parent / ".options.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return None


def set_script_options(body):
    """The options window's Start: every option of the script at once."""
    for key, value in (body.get("values") or {}).items():
        error = set_script_option({"script": body.get("script", ""), "key": key, "value": value})
        if error:
            return error
    return None


# User-requested: your scripts are kept with your character on the server, so signing in on
# another PC shows the same ones. Both ways every 30 s: a file changed on one side goes to the
# other (changed on both: the newer wins), one deleted since the last sync is deleted on the other
# side too. Only scripts and their data (.py .json .txt .md .csv, lib/ too), never bot.env, the
# scripts' own dot-files (logs, caches, options) or __pycache__. .script-sync.json remembers what
# was in sync last time.
SYNC_EXTENSIONS = {".py", ".json", ".txt", ".md", ".csv"}
SYNC = {"status": None, "at": 0}


def _sha1(data):
    import hashlib
    return hashlib.sha1(data).hexdigest()


def local_script_files(folder):
    files = {}
    for path in folder.rglob("*"):
        rel = path.relative_to(folder).as_posix()
        if (not path.is_file() or path.suffix.lower() not in SYNC_EXTENSIONS or path.name == "bot.env"
                or any(part.startswith(".") or part == "__pycache__" for part in rel.split("/"))):
            continue
        data = path.read_bytes()
        if len(data) <= 1_000_000:
            files[rel] = {"sha": _sha1(data), "mtime": int(path.stat().st_mtime * 1000)}
    return files


def sync_scripts():
    name = SETTINGS.get("main")
    folder = bot_dir(name) if name else None
    if not folder or not folder.exists():
        return
    base = f"/players/{urllib.parse.quote(name)}/scripts"
    remote_list = gw("GET", base, timeout=15)
    if not isinstance(remote_list, list):
        return  # offline or not signed in: try again later
    remote = {f["path"]: f for f in remote_list}
    local = local_script_files(folder)
    state_file = folder / ".script-sync.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    def q(rel):
        return "?path=" + urllib.parse.quote(rel)

    def upload(rel):
        path = folder / rel
        result = gw("PUT", base + q(rel), {"content": base64.b64encode(path.read_bytes()).decode(),
                                           "mtime": local[rel]["mtime"]}, timeout=30)
        if result and result.get("ok"):
            state[rel] = local[rel]["sha"]

    def download(rel):
        result = gw("GET", base + q(rel), timeout=30)
        if not result or "content" not in result:
            return
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["content"]))
        mtime = result.get("mtime", 0) / 1000
        if mtime:
            os.utime(path, (mtime, mtime))
        state[rel] = result["sha"]

    for rel in sorted(set(local) | set(remote)):
        mine, theirs, last = local.get(rel), remote.get(rel), state.get(rel)
        try:
            if mine and theirs:
                if mine["sha"] == theirs["sha"]:
                    state[rel] = mine["sha"]
                elif mine["sha"] == last:
                    download(rel)
                elif theirs["sha"] == last or mine["mtime"] >= theirs["mtime"]:
                    upload(rel)
                else:
                    download(rel)
            elif mine:
                if last is not None and last == mine["sha"]:
                    (folder / rel).unlink()  # deleted on another PC
                    state.pop(rel, None)
                else:
                    upload(rel)
            else:
                if last is not None and last == theirs["sha"]:
                    gw("DELETE", base + q(rel), timeout=15)  # deleted here
                    state.pop(rel, None)
                else:
                    download(rel)
        except OSError:
            continue  # a file in use: next time
    state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")
    SYNC.update(status="synced", at=time.time())


LOG_FOLDERS = (".aio-logs", ".quest-logs")
LOG_CHUNK = 2_000_000


def sync_logs():
    """User-requested: the group's AIO and quest logs reach the server from whichever PC runs it (the script sync
    leaves them out), so the scripts can be fixed from them there. Only what was added since last time goes up."""
    name = SETTINGS.get("main")
    folder = bot_dir(name) if name else None
    if not folder or not folder.exists():
        return
    base = f"/players/{urllib.parse.quote(name)}/logs"
    have = gw("GET", base, timeout=15)
    if not isinstance(have, dict) or "error" in have:
        return   # offline, not signed in, or an older server
    recent = time.time() - 3 * 86400
    for sub in LOG_FOLDERS:
        for path in sorted((folder / sub).glob("*.log")) if (folder / sub).exists() else []:
            try:
                size, changed = path.stat().st_size, path.stat().st_mtime
                if changed < recent:
                    continue
                rel = f"{sub}/{path.name}"
                sent = int(have.get(rel, 0))
                if size == sent:
                    continue
                if size < sent:
                    sent = 0   # cut short or started over here: send it again
                with open(path, "rb") as f:
                    f.seek(sent)
                    data = f.read(LOG_CHUNK)
                gw("POST", base + "?path=" + urllib.parse.quote(rel),
                   {"offset": sent, "content": base64.b64encode(data).decode()}, timeout=60)
            except OSError:
                continue


def script_sync_loop():
    while True:
        try:
            if not is_host():
                sync_scripts()
        except Exception as e:  # never let the sync take the hub down
            SYNC.update(status=f"error: {e}")
        try:
            if not is_host():
                sync_logs()
        except Exception:  # noqa: BLE001 - logs are a nice-to-have
            pass
        time.sleep(30)


def list_scripts():
    """Bot Scape's own scripts first, then the player's (bots/<main>/*.py)."""
    return script_entries(PACKAGED_SCRIPTS, "botscape") + script_entries(bot_dir(), "mine")


def script_path(script):
    """'botscape/Mining.py' or 'mine/MyScript.py' (a bare file name means the player's own)."""
    source, _, name = script.rpartition("/")
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    folder = PACKAGED_SCRIPTS if source == "botscape" else bot_dir()
    return folder / name


# User-requested: a script's right-click menu opens it in your code editor, or a terminal (plain or
# with an AI coding tool) in your scripts folder. Only programs found on this PC are offered.
def _first_existing(*paths):
    for path in paths:
        if path and Path(path).exists():
            return str(path)
    return None


def _env_path(var, *parts):
    base = os.environ.get(var)
    return str(Path(base, *parts)) if base else None


def find_editors():
    found = []
    candidates = [
        ("vscode", "VS Code", shutil.which("code") or _first_existing(
            _env_path("LOCALAPPDATA", "Programs", "Microsoft VS Code", "Code.exe"),
            _env_path("ProgramFiles", "Microsoft VS Code", "Code.exe"))),
        ("cursor", "Cursor", shutil.which("cursor") or _first_existing(
            _env_path("LOCALAPPDATA", "Programs", "cursor", "Cursor.exe"))),
        ("windsurf", "Windsurf", shutil.which("windsurf") or _first_existing(
            _env_path("LOCALAPPDATA", "Programs", "Windsurf", "Windsurf.exe"))),
        ("pycharm", "PyCharm", shutil.which("pycharm64") or shutil.which("pycharm")),
        ("sublime", "Sublime Text", shutil.which("subl") or _first_existing(
            _env_path("ProgramFiles", "Sublime Text", "sublime_text.exe"),
            _env_path("ProgramFiles", "Sublime Text 3", "sublime_text.exe"))),
        ("notepadpp", "Notepad++", _first_existing(
            _env_path("ProgramFiles", "Notepad++", "notepad++.exe"),
            _env_path("ProgramFiles(x86)", "Notepad++", "notepad++.exe"))),
    ]
    for key, name, exe in candidates:
        # A command-line launcher (bin\code.cmd) → the editor's own .exe next to its bin folder:
        # cmd mangles quoted paths with spaces ("Lumby Chicken Killer.py").
        if exe and exe.lower().endswith((".cmd", ".bat")):
            folder = Path(exe).resolve().parent.parent
            real = next((str(f) for f in folder.glob("*.exe") if f.stem.lower() in (key, name.lower().replace(" ", ""),
                                                                                    "code", "cursor", "windsurf")), None)
            exe = real or exe
        if exe:
            found.append({"id": key, "name": name, "exe": exe, "folder": key in ("vscode", "cursor", "windsurf", "sublime")})
    found.append({"id": "notepad", "name": "Notepad", "exe": "notepad.exe", "folder": False})
    return found


def find_ai_tools():
    tools = [("claude", "Claude Code"), ("codex", "Codex"), ("gemini", "Gemini CLI"), ("aider", "Aider")]
    return [{"id": cmd, "name": name} for cmd, name in tools if shutil.which(cmd)]


EDITORS = find_editors()
AI_TOOLS = find_ai_tools()


def open_in_editor(body):
    path = script_path(body.get("script", ""))
    editor = next((e for e in EDITORS if e["id"] == body.get("editor")), None)
    if path is None or not path.exists() or editor is None:
        return "That script or editor wasn't found."
    SETTINGS["editor"] = editor["id"]   # "Open in ..." uses the last editor you picked
    save_settings(SETTINGS)
    # Folder-aware editors get the whole scripts folder (and the file), so an AI in them sees it all.
    args = [editor["exe"], str(path.parent), str(path)] if editor["folder"] else [editor["exe"], str(path)]
    if editor["exe"].lower().endswith((".cmd", ".bat")):
        args = ["cmd", "/c"] + args
    subprocess.Popen(args, cwd=path.parent, creationflags=NO_WINDOW)
    return None


def open_terminal(body):
    folder = bot_dir()
    tool = body.get("tool") or ""
    if tool and tool not in {t["id"] for t in AI_TOOLS}:
        return "That AI tool wasn't found."
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.which("wt"):
        args = ["wt", "-d", str(folder)] + (["cmd", "/k", tool] if tool else [])
    else:
        args = ["cmd", "/c", "start", "", "cmd", "/k", f'cd /d "{folder}"' + (f" && {tool}" if tool else "")]
    subprocess.Popen(args, cwd=folder)
    return None


class Runner:
    """Script processes (one per character) and their combined output."""

    def __init__(self):
        self.procs = {}       # character -> (script, process, started)
        self.scripts = {}     # character -> the script id it last ran ("botscape/X.py")
        self.resume = {}      # character -> script id to restart once the server is back
        self.client_wait = {}  # character -> since when its resume waits for its game client
        self.held = set()     # characters stopped by hand: Auto doesn't restart them
        self.lines = deque(maxlen=3000)
        self.next_id = 1
        self.lock = threading.Lock()

    def add(self, who, text, kind="out"):
        with self.lock:
            self.lines.append({"id": self.next_id, "who": who, "text": text, "kind": kind,
                               "time": time.strftime("%H:%M:%S")})
            self.next_id += 1

    def since(self, after):
        with self.lock:
            return [line for line in self.lines if line["id"] > after]

    def running(self):
        with self.lock:
            return {who: {"script": s, "started": started} for who, (s, p, started) in self.procs.items()
                    if p.poll() is None}

    def run(self, who, script):
        # Not when another PC already runs a script on this character, whichever way this start came (resumed
        # after a restart or an update too). Two PCs drove simba's group at once: each walk cut the other's trips
        # short and closed its bank ("Stopped", "couldn't open Draynor bank"), user-reported via the logs.
        if who not in self.procs:
            try:
                running = http("GET", map_url() + "/api/running", timeout=3) or {}
            except Exception:
                running = {}
            other = running.get(who.lower()) if isinstance(running, dict) else None
            # Another computer: this one's own entries (a hub before an update had another process id) don't count.
            if isinstance(other, dict) and str(other.get("pc") or "").split(":")[0] not in ("", socket.gethostname()):
                with self.lock:
                    self.resume.pop(who, None)
                msg = f"Not started: {other.get('script') or 'a script'} already runs on {who} on {other.get('pc')}"
                self.add(who, msg, "error")
                return msg
        self.stop(who, quiet=True)
        path = script_path(script)
        if path is None or not path.exists():
            return f"No script {script}"
        python = sys.executable.replace("pythonw.exe", "python.exe")
        env = dict(os.environ, BOT_GATEWAY=gateway_url(), BOT_ACTIVITY=map_url() + "/api/activity",
                   PYTHONIOENCODING="utf-8", BOT_MAIN=SETTINGS["main"].lower(), RS_BOT=who.lower())
        auth_headers()
        if AUTH["token"]:
            env["BOT_TOKEN"] = AUTH["token"]
        proc = subprocess.Popen([python, "-u", str(path), who, "--main", SETTINGS["main"]], cwd=bot_dir(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", env=env, creationflags=NO_WINDOW)
        with self.lock:
            self.held.discard(who)
            self.procs[who] = (path.stem, proc, time.time())
            self.scripts[who] = script
            self.resume.pop(who, None)
        self.add(who, f"{path.stem} started", "start")
        threading.Thread(target=self.read, args=(who, proc, path.stem), daemon=True).start()
        return None

    def read(self, who, proc, script):
        lost = False
        for line in proc.stdout:
            line = line.rstrip("\n")
            kind = "error" if ("Traceback" in line or "Error" in line or line.startswith("Stopped")) else "out"
            lost = lost or bool(SERVER_GONE.search(line))
            self.add(who, line, kind)
        code = proc.wait()
        self.add(who, f"{script} stopped" + (f" (exit {code})" if code else ""), "stop")
        with self.lock:
            current = self.procs.get(who)
            ours = current is not None and current[1] is proc   # not stopped by hand (Stop removes it first)
            if ours:
                del self.procs[who]
        # User-requested: a script the server dropped (a restart, an update) carries on by itself
        # once the server is back.
        if ours and code and (lost or not server_reachable()):
            with self.lock:
                self.resume[who] = self.scripts.get(who)
            self.add(who, f"The server went away: {script} continues when it's back", "start")

    def resume_loop(self):
        """Restarts the scripts the server dropped, once it answers again (and logins work)."""
        back_since = None
        while True:
            time.sleep(5)
            if not self.resume:
                back_since = None
                continue
            if not server_reachable():
                back_since = None
                continue
            back_since = back_since or time.time()
            if time.time() - back_since < 20:      # give the restarted server a moment
                continue
            # A character with a game client open waits until that client has logged back in: a
            # script that logs in first plays an unseen session the client then takes over, and
            # looks running while doing nothing (user-reported). The rest start right away.
            online = None
            with self.lock:
                todo = dict(self.resume)
            for who, script in todo.items():
                if not script or who in self.running():
                    with self.lock:
                        self.resume.pop(who, None)
                    continue
                if client_open_for(who):
                    if online is None:
                        try:
                            online = {str(n).lower() for n in (gw("GET", "/players", timeout=3) or [])}
                        except Exception:
                            online = set()
                    if who.lower() not in online:
                        waited = self.client_wait.setdefault(who, time.time())
                        if time.time() - waited < 600:      # up to 10 minutes for the client
                            continue
                with self.lock:
                    self.resume.pop(who, None)
                self.client_wait.pop(who, None)
                self.add(who, "The server is back: continuing", "start")
                error = self.run(who, script)
                if error:
                    self.add(who, error, "error")

    def stop(self, who, quiet=False):
        with self.lock:
            self.resume.pop(who, None)
            entry = self.procs.pop(who, None)
        if entry and entry[1].poll() is None:
            subprocess.run(["taskkill", "/PID", str(entry[1].pid), "/T", "/F"], capture_output=True,
                           creationflags=NO_WINDOW)
            # Hand the character back: a server-side bot logs out, an attached one lets go.
            threading.Thread(target=gw, args=("POST", f"/bots/{urllib.parse.quote(who)}/logout"),
                             daemon=True).start()
            if not quiet:
                self.add(who, f"{entry[0]} stopped", "stop")

    def stop_all(self):
        # All at once (user-reported: STOP ALL felt chunky: each taskkill waited for the one before).
        threads = [threading.Thread(target=self.stop, args=(who,), daemon=True) for who in list(self.procs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)


# Script output that means the server went away (not a bug in the script).
SERVER_GONE = re.compile(r"not reachable|WinError 1006[01]|ConnectionReset|RemoteDisconnected|Connection aborted"
                         r"|Connection refused|timed out|server is offline|Server offline", re.I)


CLIENTS_OPEN = {"names": set(), "at": 0.0}


def clients_open():
    """Lower-case names with a game client of this install open, refreshed at most every 5 s in the background
    (the process query takes about a second; the character list asks every refresh)."""
    # A scan no longer uses WMI (see java_client_cmdlines), so it can be every 5 s again.
    if time.time() - CLIENTS_OPEN["at"] > 5:
        CLIENTS_OPEN["at"] = time.time()

        def scan():
            CLIENTS_OPEN["names"] = client_logins()
        threading.Thread(target=scan, daemon=True).start()
    return CLIENTS_OPEN["names"]


JAVA_CMDLINES = {}   # (pid, start time) -> command line: a process's command line never changes


def java_client_cmdlines():
    """Command lines of this install's game clients that have a window. No WMI: the process list is a
    Toolhelp snapshot, each new java's command line is read once from the process itself, and windows come
    from EnumWindows. User-reported: WMI Provider Host at 68 % on the server PC from the hubs' and the
    monitor's PowerShell process queries."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    k32, user32, ntdll = ctypes.windll.kernel32, ctypes.windll.user32, ctypes.windll.ntdll
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    pids = []
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in ("java.exe", "javaw.exe"):
                pids.append(entry.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    if not pids:
        JAVA_CMDLINES.clear()
        return []

    # Only a client with a window counts (Get-Process' MainWindowHandle: a visible, unowned top-level window).
    windowed = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):   # GW_OWNER
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windowed.add(pid.value)
        return True
    user32.EnumWindows(proc(on_window), 0)

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    seen, out = set(), []
    for pid in pids:
        handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                continue
            key = (pid, times[0].dwHighDateTime, times[0].dwLowDateTime)
            if key not in JAVA_CMDLINES:
                size = wintypes.ULONG(0)
                ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))  # ProcessCommandLineInformation
                buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(UNICODE_STRING)) + 2)
                if ntdll.NtQueryInformationProcess(handle, 60, buf, len(buf), ctypes.byref(size)) != 0:
                    continue
                us = UNICODE_STRING.from_buffer(buf)
                JAVA_CMDLINES[key] = ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
            seen.add(key)
            if pid in windowed:
                out.append(JAVA_CMDLINES[key])
        finally:
            k32.CloseHandle(handle)
    for key in set(JAVA_CMDLINES) - seen:
        del JAVA_CMDLINES[key]
    # Only this install's clients (the root, exactly: another install's path can start with this one's).
    mine = re.compile(r"botscape\.root=" + re.escape(str(ROOT)) + r"([\s\"]|$)", re.I)
    return [line for line in out if mine.search(line)]


def client_login_names():
    names = set()
    for line in java_client_cmdlines():
        m = re.search(r"-Dbotscape\.login=([^\s\"]*)", line)
        names.add(((m.group(1) if m else "") or SETTINGS.get("main", "")).lower())
    return names


def client_logins():
    try:
        return client_login_names()
    except Exception:  # noqa: BLE001 - a failed scan shows no client icons rather than ending the hub
        return set()


def client_open_for(who):
    """Is a Bot Scape game client of this install running as `who`?"""
    return who.lower() in client_logins()


def server_reachable():
    try:
        gw("GET", "/players", timeout=3)
        return True
    except Exception:
        return False


RUNNER = Runner()
threading.Thread(target=RUNNER.resume_loop, daemon=True).start()


# --- xp tracking ---------------------------------------------------------------------------------

class XpTracker:
    """XP per hour for each character since the launcher started (or the player pressed Reset).

    Family members share their skills, so the shared xp goes up on everyone at once; the server
    also reports the xp each character earned itself ("earned"), which is what is tracked here.
    An older server without it falls back to the shared xp (then every member shows the same).
    """

    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def update(self, name, stats):
        key = "earned" if any("earned" in s for s in stats.values()) else "xp"
        values = {skill: s.get(key, 0) for skill, s in stats.items()}
        now = time.time()
        with self.lock:
            sess = self.sessions.get(name)
            # A new session when there is none, or the server restarted (its counters went down).
            if not sess or sess["key"] != key or any(v < sess["now"].get(k, 0) for k, v in values.items()):
                sess = self.sessions[name] = {"key": key, "since": now, "start": values, "now": values,
                                              "first": {}, "lastGain": {}, "seen": now}
            for skill, value in values.items():
                if value > sess["now"].get(skill, 0):
                    # A skill's rate counts from just before its first gain, like RuneLite's xp tracker.
                    sess["first"].setdefault(skill, sess["seen"])
                    sess["lastGain"][skill] = now
            sess["now"], sess["seen"] = values, now

    def reset(self, name=None):
        with self.lock:
            for who in ([name] if name else list(self.sessions)):
                self.sessions.pop(who, None)

    def report(self, name):
        with self.lock:
            sess = self.sessions.get(name)
            if not sess:
                return None
            now = time.time()
            skills = {}
            for skill, first in sess["first"].items():
                gained = sess["now"].get(skill, 0) - sess["start"].get(skill, 0)
                if gained > 0:
                    hours = max(now - first, 60) / 3600
                    skills[skill] = {"gained": gained, "perHour": int(gained / hours),
                                     "lastGain": sess["lastGain"].get(skill)}
            total = sum(s["gained"] for s in skills.values())
            hours = max(now - min(sess["first"].values(), default=now), 60) / 3600
            return {"since": sess["since"], "ownXp": sess["key"] == "earned", "skills": skills,
                    "gained": total, "perHour": int(total / hours) if total else 0}


XP = XpTracker()


def family_xp(reports):
    """The whole family's rates: the sum of what each member earned."""
    reports = [r for r in reports if r]
    if not reports:
        return None
    if not all(r["ownXp"] for r in reports):
        return max(reports, key=lambda r: r["gained"])  # shared xp only: every member shows the same
    skills = {}
    for r in reports:
        for skill, s in r["skills"].items():
            out = skills.setdefault(skill, {"gained": 0, "perHour": 0, "lastGain": 0})
            out["gained"] += s["gained"]
            out["perHour"] += s["perHour"]
            out["lastGain"] = max(out["lastGain"] or 0, s["lastGain"] or 0)
    return {"since": min(r["since"] for r in reports), "ownXp": True, "skills": skills,
            "gained": sum(r["gained"] for r in reports), "perHour": sum(r["perHour"] for r in reports)}


# --- overview (polled by the UI) -----------------------------------------------------------------

class World:
    """Everything the interface shows, refreshed every two seconds in the background."""

    def __init__(self):
        self.data = {"online": False, "embedded": EMBEDDED, "zazuosu": {k: ZAZUOSU[k] for k in ("status", "error")}}
        self.lock = threading.Lock()
        self.auto_clone_wait = 0
        self.auto_aio_at = {}   # member -> when Auto last started AIO on it

    def loop(self):
        while True:
            try:
                self.refresh()
            except Exception as e:  # never let the poller die
                # User-reported: the hub showed "Server offline" now and then while the server was up. An
                # error further into a refresh (a slow group or activity read) isn't the server being down:
                # keep showing the last good picture.
                with self.lock:
                    self.data = dict(self.data, error=str(e))
            time.sleep(2)

    def refresh(self):
        main = SETTINGS["main"]
        start = time.time()
        try:
            bots = gw("GET", "/bots", timeout=6)
        except Exception:
            # A busy server PC sometimes takes a few seconds to answer: only a second miss in a row
            # (about 10 s without an answer) counts as offline.
            self.misses = getattr(self, "misses", 0) + 1
            if self.misses >= 2:
                with self.lock:
                    self.data = {"online": False, "embedded": EMBEDDED, "zazuosu": {k: ZAZUOSU[k] for k in ("status", "error")}}
            return
        self.misses = 0
        ms = int((time.time() - start) * 1000)
        online = set(gw("GET", "/players", timeout=3) or [])
        family = gw("GET", f"/families/{urllib.parse.quote(main)}", timeout=5) or {}
        # User-reported: a server that answers but can't read the group yet (still starting) showed a
        # made-up group (total level 0, next member at 100). Say it's starting instead.
        family_ready = bool(family) and not family.get("error")
        if not family_ready:
            family = {"main": main, "totalLevel": 0, "unlocked": 0, "nextUnlockAt": None, "clones": []}
        try:
            activities = http("GET", map_url() + "/api/activity", timeout=2) or {}
        except Exception:
            activities = {}
        bot_status = {b["name"]: b for b in bots or []}
        running = RUNNER.running()
        remote = self.share_running(running)
        characters = []
        names = [(main, "main", True)] + [(c["name"], f"member {c['index']}", c.get("unlocked", True))
                                         for c in family.get("clones", [])]
        # A member whose name a real player has plays under a hidden login name and shows its own.
        shown = {c["name"]: c.get("display") or c["name"] for c in family.get("clones", [])}
        family_state = None
        for name, role, unlocked in names:
            status = "online" if name in online else bot_status.get(name, {}).get("status", "offline")
            if not unlocked:
                status = "locked"
            entry = {"name": name, "display": shown.get(name, name), "role": role, "status": status, "unlocked": unlocked,
                     "activity": (activities.get(name) or {}).get("text"), "script": None,
                     "client": name.lower() in clients_open()}
            if name in running:
                entry["script"] = running[name]["script"]
                entry["started"] = running[name]["started"]
            elif name.lower() in remote:
                entry["remote"] = remote[name.lower()]
            # User-reported: an offline character kept its script's last line ("Thieving: No XP...")
            # for a few minutes after it stopped. Only show what it's doing while it does something.
            if status != "online" and not entry.get("script") and not entry.get("remote"):
                entry["activity"] = None
            if name in online:
                state = (gw("GET", f"/players/{urllib.parse.quote(name)}/state", timeout=3) or {}).get("state")
                if state:
                    p = state["player"]
                    hp = state["stats"].get("hitpoints", {})
                    entry.update({"x": p["x"], "z": p["z"], "plane": p["level"], "combat": p["combatLevel"],
                                  "total": p["totalLevel"], "hp": hp.get("level"), "maxHp": hp.get("base"),
                                  "runEnergy": p.get("runEnergy"), "stats": state["stats"],
                                  "inventory": state.get("inventory", []), "equipment": state.get("equipment", []),
                                  # The Character tab's quest list (user-requested), like the web page's.
                                  "quests": [{k: q.get(k) for k in ("name", "status", "quest_points")}
                                             for q in (state.get("quests") or {}).get("list", [])],
                                  "collection": state.get("collection")})
                    XP.update(name, state["stats"])
                    family_state = family_state or state
            entry["xp"] = XP.report(name)
            characters.append(entry)
        overview = {
            "online": True, "ms": ms, "main": main, "server": server_host(), "host": is_host(),
            "family": family, "familyReady": family_ready, "characters": characters, "autoClone": SETTINGS.get("auto_clone", False),
            "skills": family_state["stats"] if family_state else None,
            "bank": family_state["bank"] if family_state else None,
            "familyXp": family_xp([c["xp"] for c in characters]),
            "hasAccount": bool(read_env().get("PASSWORD")),
            "embedded": EMBEDDED, "zazuosu": {k: ZAZUOSU[k] for k in ("status", "error")},
            "editors": [{"id": e["id"], "name": e["name"]} for e in EDITORS], "aiTools": AI_TOOLS,
            "editor": SETTINGS.get("editor"),
            "update": UPDATE["latest"], "version": installed_version(),
            "updateIn": max(0, int(UPDATE["applyAt"] - time.time())) if UPDATE.get("applyAt") else None,
        }
        with self.lock:
            self.data = overview
        if family_ready:
            self.maybe_auto_clone(family)
        self.maybe_auto_aio(characters)

    # User-requested: a script another PC runs on one of your characters shows here too. Every hub
    # tells the server (the map server's /api/running) what it runs; what other PCs run comes back.
    def share_running(self, running):
        try:
            answer = http("POST", map_url() + "/api/running", {"pc": PC_NAME, "scripts": {
                n.lower(): {"script": r["script"], "started": r["started"]} for n, r in running.items()}}, timeout=2) or {}
            # Stop requests from a game client (its Stop on a "Running in the hub" card).
            for name in answer.get("stop", []) if isinstance(answer, dict) else []:
                who = next((n for n in running if n.lower() == name), None)
                if who:
                    RUNNER.held.add(who)
                    RUNNER.stop(who)
                    RUNNER.add(who, "Stopped from the game client", "stop")
            everyone = http("GET", map_url() + "/api/running", timeout=2) or {}
        except Exception:
            return {}
        if not isinstance(everyone, dict) or "error" in everyone:
            return {}
        return {n: r for n, r in everyone.items() if isinstance(r, dict) and r.get("pc") != PC_NAME}

    def maybe_auto_clone(self, family):
        if not SETTINGS.get("auto_clone", False) or time.time() < self.auto_clone_wait:
            return
        # -1: members need no levels (admin rule); don't add any automatically then.
        if family.get("unlocked", 0) < 0 or len(family.get("clones", [])) >= family.get("unlocked", 0):
            return
        taken = {c["name"].lower() for c in family.get("clones", [])} | {SETTINGS["main"].lower()}
        for name in member_names(SETTINGS["main"], 30):
            if name.lower() in taken:
                continue
            result = gw("POST", f"/families/{urllib.parse.quote(SETTINGS['main'])}/clones", {"name": name.lower()},
                        timeout=15) or {}
            if not result.get("error"):
                RUNNER.add(None, f"{result['name']} joined the group (member {result['index']})", "start")
                return
        self.auto_clone_wait = time.time() + 600

    # User-requested: with Auto on, the group's members train by themselves: AIO starts on every unlocked
    # member that runs nothing, the leader too (user-requested 2026-11-08: the leader sat offline). A character
    # you stopped by hand stays stopped until you run something on it, one you play in a client is left alone;
    # one whose AIO ended is retried after 5 min.
    def maybe_auto_aio(self, characters):
        if not SETTINGS.get("auto_clone", False):
            return
        script = next((s["id"] for source in ("mine", "botscape") for s in list_scripts()
                       if s["source"] == source and s["name"].lower() == "aio"), None)
        if script is None:
            return
        running = RUNNER.running()
        for c in characters:
            who = c["name"]
            if (not c.get("unlocked") or who in running or c.get("remote") or who in RUNNER.resume
                    or who in RUNNER.held or time.time() - self.auto_aio_at.get(who, 0) < 300):
                continue
            self.auto_aio_at[who] = time.time()
            if client_open_for(who):   # you're playing it yourself
                continue
            RUNNER.add(who, "Auto: starting AIO", "start")
            error = RUNNER.run(who, script)
            if error:
                RUNNER.add(who, error, "error")

    def get(self):
        with self.lock:
            data = dict(self.data)
        if data.get("online"):
            # Scripts can change between polls; report them fresh.
            running = RUNNER.running()
            for c in data.get("characters", []):
                r = running.get(c["name"])
                c["script"], c["started"] = (r["script"], r["started"]) if r else (None, None)
        data["scripts"] = list_scripts()
        data["main"] = SETTINGS["main"]
        # Signed in = a character with its password here. Not signed in but a zazuosu session is
        # saved (the server was offline when you logged in): connect it now.
        signed_in = bool(SETTINGS["main"]) and bool(read_env().get("PASSWORD"))
        if not signed_in and not EMBEDDED and not is_host() and zazuosu_token() and data.get("online"):
            threading.Thread(target=zazuosu_sign_in, daemon=True).start()
        data["signedIn"] = signed_in
        data["hasAccount"] = bool(read_env().get("PASSWORD"))   # also while the server is offline
        data["zazuosuPending"] = bool(zazuosu_token()) and not signed_in
        data["profile"] = {"name": PROFILE["name"] or SETTINGS["main"], "avatar": PROFILE["avatar"]}
        data["host"] = is_host()
        data["mapUrl"] = map_url() + "/map"
        return data


PC_NAME = f"{socket.gethostname()}:{os.getpid()}"   # this hub, in the scripts it reports
WORLD = World()


# --- actions -------------------------------------------------------------------------------------

def find_edge():
    for path in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(path).exists():
            return path
    return shutil.which("msedge")


def focus_client(who):
    """User-requested: a client already open as `who` comes to the front instead of opening another one.
    True if one was found."""
    root = str(ROOT).replace("'", "''")
    login = re.sub(r"[^A-Za-z0-9_ ]", "", who or "").lower()
    main = re.sub(r"[^A-Za-z0-9_ ]", "", SETTINGS.get("main", "")).lower()
    script = (
        "Add-Type -Name W -Namespace B -MemberDefinition '"
        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(System.IntPtr h);"
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(System.IntPtr h, int c);"
        "[DllImport(\"user32.dll\")] public static extern bool IsIconic(System.IntPtr h);';"
        "$found = $false;"
        "Get-CimInstance Win32_Process -Filter \"Name='javaw.exe' or Name='java.exe'\" | "
        "? { $_.CommandLine -like '*botscape.root=" + root + "*' } | % {"
        " $m = [regex]::Match($_.CommandLine, '-Dbotscape\.login=([^\s\"]*)');"
        " $l = if ($m.Success -and $m.Groups[1].Value) { $m.Groups[1].Value.ToLower() } else { '" + main + "' };"
        " if ($l -eq '" + login + "') { $h = (Get-Process -Id $_.ProcessId).MainWindowHandle;"
        "  if ($h -ne 0) { if ([B.W]::IsIconic($h)) { [B.W]::ShowWindow($h, 9) | Out-Null };"
        "   [B.W]::SetForegroundWindow($h) | Out-Null; $found = $true } } };"
        "if ($found) { 'yes' }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-c", script], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "yes" in out


CLIENT_LAUNCH = {"lock": threading.Lock(), "at": 0.0}
CLIENT_GAP = 10   # seconds between two clients starting


def open_client(character):
    if focus_client(character or SETTINGS.get("main", "")):
        return None
    bat = ROOT / "CLIENT.bat"
    if not bat.exists():
        return "The client isn't installed (CLIENT.bat missing)."

    def launch():
        # User-reported: after an update only one of several clients came back, the others showed an
        # error. They all start RuneLite with the same profile folder at the same moment; one at a
        # time, CLIENT_GAP seconds apart, they don't trip over each other.
        with CLIENT_LAUNCH["lock"]:
            wait = CLIENT_LAUNCH["at"] + CLIENT_GAP - time.time()
            if wait > 0:
                time.sleep(wait)
            subprocess.Popen(["cmd", "/c", str(bat), SETTINGS["main"], character or "", server_host()], cwd=ROOT,
                             creationflags=NO_WINDOW)
            CLIENT_LAUNCH["at"] = time.time()
    threading.Thread(target=launch, daemon=True).start()
    RUNNER.add(character, "Opening the client" + (f" as {character}" if character else ""), "start")
    return None


def start_server():
    if not is_host():
        return "Only the computer that hosts the server can start it."
    log = open(ROOT / "server.log", "w", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(ROOT / "SERVER.bat")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=NO_WINDOW)
    python = sys.executable.replace("pythonw.exe", "python.exe")
    subprocess.Popen([python, str(ROOT / "launcher" / "config_server.py")], cwd=ROOT, creationflags=NO_WINDOW)
    RUNNER.add(None, "Starting the server (about 20 seconds)…", "start")
    return None


def stop_server():
    if not is_host():
        return "Only the computer that hosts the server can stop it."
    RUNNER.stop_all()
    gw("POST", "/admin/shutdown")
    RUNNER.add(None, "Server stopping (everyone online is saved)…", "stop")
    return None


def run_here(who, script):
    """Run a script here, unless the game client or another hub already runs one on the character:
    two scripts on one character walk it back and forth (it happened, user-reported)."""
    other = next((c.get("remote") for c in WORLD.get().get("characters", []) if c["name"] == who and c.get("remote")), None)
    if other and who not in RUNNER.running():
        where = "the game client" if "game client" in str(other.get("pc", "")) else "another PC"
        RUNNER.add(who, f"Not started: {other.get('script')} already runs on {who} in {where} (stop it first)", "error")
        return f"{other.get('script')} already runs on {who} in {where}: stop it first."
    return RUNNER.run(who, script)


def stop_everyone():
    """User-reported: STOP ALL left scripts running. It only stopped this hub's own; scripts a game
    client or another hub runs on the group's characters are asked to stop too (like each card's Stop)."""
    RUNNER.held.update(RUNNER.procs)
    RUNNER.stop_all()
    # The ones running elsewhere are asked in the background: the button answers right away.
    threading.Thread(target=stop_remote_members, daemon=True).start()
    return None


def restart_everyone():
    """User-requested: a Restart button next to STOP ALL. Every script this hub runs is stopped and started again
    with the same script, so they load an updated version (an AIO brain only reads its code when it starts)."""
    running = {who: RUNNER.scripts.get(who) for who in RUNNER.running()}
    running = {who: script for who, script in running.items() if script}
    if not running:
        return "Nothing is running here to restart."

    def again():
        RUNNER.stop_all()
        time.sleep(3)   # the logouts go through first
        for who, script in running.items():
            error = RUNNER.run(who, script)
            if error:
                RUNNER.add(who, error, "error")
    threading.Thread(target=again, daemon=True).start()
    return None


def stop_remote_members():
    try:
        everyone = http("GET", map_url() + "/api/running", timeout=3) or {}
    except Exception:
        everyone = {}
    group = {SETTINGS.get("main", "").lower()} | {n.lower() for n in member_names_known()}
    for name, run in (everyone.items() if isinstance(everyone, dict) else []):
        if isinstance(run, dict) and run.get("pc") != PC_NAME and name.lower() in group:
            RUNNER.held.add(name)
            try:
                http("POST", map_url() + "/api/stop", {"name": name.lower()}, timeout=3)
            except Exception:
                pass
    return None


def member_names_known():
    """The group's character names from the last character list the hub built."""
    try:
        return [c["name"] for c in (WORLD.data.get("characters") or [])]
    except Exception:
        return []


def stop_character(who):
    """Stop its script here, or (user-requested) ask the hub or game client that runs it elsewhere."""
    RUNNER.held.add(who)
    if who in RUNNER.running():
        RUNNER.stop(who)
        return None
    try:
        http("POST", map_url() + "/api/stop", {"name": who.lower()}, timeout=3)
    except Exception:
        return "Couldn't reach the server to stop it."
    RUNNER.add(who, "Asked the other launcher/client to stop its script", "stop")
    return None


def name_group(body):
    """User-requested: the group's own name (shown on the highscores); blank clears it."""
    result = gw("POST", f"/families/{urllib.parse.quote(SETTINGS['main'])}/name",
                {"name": str(body.get("name", ""))}, timeout=15)
    if not result:
        return "The server didn't answer (is it updated and online?)"
    return result.get("error")


def rename_member(body):
    """User-requested: renames a group member. Its script is stopped and it's logged out first (the
    server only renames an offline member)."""
    old = str(body.get("character", "")).strip()
    new = re.sub(r" +", " ", str(body.get("name", "")).strip().lower())
    if not re.fullmatch(r"[a-z0-9_ ]{1,12}", new):
        return "Use 1-12 letters, digits, spaces or underscores."
    RUNNER.held.add(old)       # Auto mustn't start it again meanwhile
    RUNNER.stop(old, quiet=True)
    gw("POST", f"/bots/{urllib.parse.quote(old)}/logout")
    path = f"/families/{urllib.parse.quote(SETTINGS['main'])}/clones/{urllib.parse.quote(old)}/rename"
    error = None
    for _ in range(10):        # the logout takes a moment
        result = gw("POST", path, {"name": new}, timeout=15) or {}
        error = result.get("error")
        if not error or "online" not in error:
            break
        time.sleep(1)
    if error:
        RUNNER.held.discard(old)
        return error
    RUNNER.held.discard(old)
    WORLD.auto_aio_at.pop(old, None)
    RUNNER.add(new, f"{old} is now called {new}", "start")
    return None


def setup_account(main, password):
    main = main.strip().lower()
    if not re.fullmatch(r"[a-z0-9_ ]{1,12}", main):
        return "Use 1-12 letters, digits, spaces or underscores."
    if not 4 <= len(password) <= 20:
        return "The password must be 4-20 characters."
    folder = bot_dir(main)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bot.env").write_text(f"BOT_USERNAME={main}\nPASSWORD={password}\n", encoding="utf-8")
    SETTINGS["main"] = main
    save_settings(SETTINGS)
    AUTH["token"] = None
    return None


ACTIONS = {
    "run": lambda b: run_here(b["character"], b["script"]),
    "stop": lambda b: stop_character(b["character"]),
    "run-team": lambda b: [run_here(c["name"], b["script"]) for c in WORLD.get().get("characters", [])
                           if c.get("unlocked")] and None,
    "stop-all": lambda b: stop_everyone(),
    "restart-all": lambda b: restart_everyone(),
    "xp-reset": lambda b: XP.reset(b.get("character")),
    "logout": lambda b: (RUNNER.stop(b["character"], quiet=True),
                         gw("POST", f"/bots/{urllib.parse.quote(b['character'])}/logout")) and None,
    "client": lambda b: open_client(b.get("character")),
    "clone": lambda b: (lambda r: r.get("error"))(
        gw("POST", f"/families/{urllib.parse.quote(SETTINGS['main'])}/clones", {"name": b["name"].lower()},
           timeout=15) or {}),
    "rename": rename_member,
    "group-name": name_group,
    "settings": lambda b: (SETTINGS.update({k: v for k, v in b.items() if k == "auto_clone"}),
                           save_settings(SETTINGS), AUTH.update(token=None)) and None,
    "folder": lambda b: os.startfile(bot_dir()) and None,
    "open-editor": open_in_editor,
    "script-option": set_script_option,
    "script-options": set_script_options,
    "update": update_now,
    "check-update": check_update,
    "open-terminal": open_terminal,
    "account": lambda b: setup_account(b.get("main", ""), b.get("password", "")),
    "logout": lambda b: logout(),
    "profile-avatar": set_avatar,
    "zazuosu-login": zazuosu_login,
}


# --- web server ----------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/overview":
            return self.send(200, WORLD.get())
        if url.path == "/api/news":
            # User-requested: the website's News in the hub too (zazuosu.com/osrs/api/news, cached a minute).
            if time.time() - NEWS["at"] > 60:
                try:
                    NEWS["posts"] = (http("GET", NEWS_URL, timeout=8, auth=False) or {}).get("posts") or NEWS["posts"]
                    NEWS["at"] = time.time()
                except Exception:  # noqa: BLE001 - offline: the last ones
                    pass
            return self.send(200, {"posts": NEWS["posts"]})
        if url.path == "/api/hiscores":
            try:
                return self.send(200, gw("GET", "/hiscores", timeout=10) or {})
            except Exception:
                return self.send(200, {"error": "Server offline"})
        if url.path == "/api/quest-journal":
            q = urllib.parse.parse_qs(url.query)
            who, quest = q.get("character", [""])[0], q.get("quest", [""])[0]
            try:
                return self.send(200, gw("GET", f"/players/{urllib.parse.quote(who)}/quest?name={urllib.parse.quote(quest)}") or {})
            except Exception as e:
                return self.send(200, {"error": str(e)})
        if url.path == "/api/output":
            after = int(urllib.parse.parse_qs(url.query).get("after", ["0"])[0])
            return self.send(200, RUNNER.since(after))
        name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
        path = (UI_DIR / name).resolve()
        if UI_DIR.resolve() in path.parents and path.is_file():
            types = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                     ".png": "image/png", ".svg": "image/svg+xml"}
            return self.send(200, path.read_bytes(), types.get(path.suffix, "application/octet-stream"))
        # Artwork: /brand/... and /ui/... from assets/, anything else from assets/icons/.
        first, _, rest = name.partition("/")
        base = ROOT / "assets" / first if first in ("brand", "ui") and rest else ROOT / "assets" / "icons"
        asset = (base / (rest if base.name != "icons" else name)).resolve()
        if base.resolve() in asset.parents and asset.is_file():
            types = {".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
            return self.send(200, asset.read_bytes(), types.get(asset.suffix, "application/octet-stream"))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        action = self.path.strip("/").removeprefix("api/")
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        handler = ACTIONS.get(action)
        if handler is None:
            return self.send(404, {"error": f"unknown action {action}"})
        try:
            error = handler(body)
        except Exception as e:
            error = str(e)
        self.send(200 if not error else 400, {"ok": not error, "error": error})


def open_window():
    url = f"http://127.0.0.1:{PORT}/"
    edge = find_edge()
    if edge:
        # Its own profile, without Edge's first-run, sign-in, sync and restore prompts.
        window = subprocess.Popen([edge, f"--app={url}", "--window-size=1440,900",
                                 f"--user-data-dir={ROOT / '.launcher-window'}", "--no-first-run",
                                 "--no-default-browser-check", "--disable-sync", "--hide-crash-restore-bubble",
                                 "--disable-features=msImplicitSignin,msEdgeWelcomePage,EdgeSigninProfilePrompt"])
        # Favicon handles browser UI; Windows shell properties keep the taskbar
        # and pinned relaunch icon distinct from both Edge and the game client.
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(ROOT / "launcher" / "hub-window.ps1"), "-Root", str(ROOT)],
                             creationflags=NO_WINDOW)
        except OSError:
            pass  # The hub can still use its favicon if native shell integration is unavailable.
        return window
    webbrowser.open(url)
    return None


def watch_parent(pid):
    """Embedded mode: exit (stopping our scripts) when the Zazuosu launcher closes."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    RUNNER.stop_all()
    os._exit(0)


def stop_orphan_scripts():
    """User-reported: a hub that ended abruptly (closed, crashed, replaced by an update) left its
    scripts running, so a character had two or three AIOs at once walking it back and forth and
    taking each other's items from the shared bank. At start: stop this install's scripts whose
    hub or client is gone (one started by a live hub or game client keeps its parent and stays)."""
    query = ("$all = @{}; Get-CimInstance Win32_Process | % { $all[[int]$_.ProcessId] = $_ }; "
             "$all.Values | ? { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*" +
             str(ROOT / "bots").replace("'", "''") + "*' -and -not $all.ContainsKey([int]$_.ParentProcessId) } | "
             "% { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-c", query], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for pid in out.split():
        if pid.isdigit() and int(pid) != os.getpid():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
            RUNNER.add(None, f"Stopped a script left running by a closed launcher (process {pid})", "stop")


def main_embedded():
    ThreadingHTTPServer.allow_reuse_address = False
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=stop_orphan_scripts, daemon=True).start()
    threading.Thread(target=WORLD.loop, daemon=True).start()
    threading.Thread(target=zazuosu_sign_in, daemon=True).start()
    threading.Thread(target=script_sync_loop, daemon=True).start()
    parent = _arg("--parent-pid")
    if parent and parent.isdigit():
        watch_parent(int(parent))
    else:
        server_thread_wait()


def main():
    if EMBEDDED:
        return main_embedded()
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        open_window()  # already running: just show it
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=stop_orphan_scripts, daemon=True).start()
    if ZAZUOSU_ARG:
        # Opened from the Zazuosu launcher: sign in as the player's zazuosu account first.
        zazuosu_sign_in()
    threading.Thread(target=WORLD.loop, daemon=True).start()
    if player_install():
        threading.Thread(target=update_check_loop, daemon=True).start()
    threading.Thread(target=reopen_game_clients, daemon=True).start()
    threading.Thread(target=script_sync_loop, daemon=True).start()
    window = open_window()
    if window is None:
        server_thread_wait()
        return
    window.wait()
    # Edge hands a new window to an already-open one and exits at once, so wait for every
    # launcher window to be gone, not just the process we started.
    while launcher_windows_open():
        time.sleep(3)
    # The window closed: stop the scripts this launcher started, then exit.
    RUNNER.stop_all()
    server.shutdown()


def launcher_windows_open():
    """Is an Edge process using the launcher's window profile still running?"""
    query = ("@(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "? { $_.CommandLine -like '*.launcher-window*' }).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-c", query], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout.strip()
        return int(out or 0) > 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def server_thread_wait():
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        RUNNER.stop_all()


if __name__ == "__main__":
    main()
