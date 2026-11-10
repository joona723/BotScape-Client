"""Bot Scape SDK: drive a server-side bot through the local bot gateway.

    from botscape import run

    def main(bot):
        rock = bot.find_loc("Copper rocks")
        bot.interact_loc(rock, "Mine")
        bot.wait_until(lambda: bot.inv_count("Copper ore") > 0, timeout=30)

    run(main)

Group trading (two logged-in group members, controlled by the same script):

    main.trade_request(member.name)
    main.wait_ticks(2)
    member.trade_request(main.name)
    member.wait_ticks(2)
    main.trade_offer("Coins", 100)
    member.trade_offer("Lobster", 5)
    main.trade_accept()       # first screen
    member.trade_accept()
    main.trade_accept()       # confirmation screen
    member.trade_accept()
    assert main.trade_state()["screen"] == 0

Bots are characters played by the server itself (no game client). Every action is sent as the
same click a real client would make, so the game's rules apply to bots exactly as to players.
Only the standard library is used.
"""

import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GATEWAY = os.environ.get("BOT_GATEWAY", "http://127.0.0.1:7780")
ACTIVITY_URL = os.environ.get("BOT_ACTIVITY", "http://127.0.0.1:8080/api/activity")
SCRIPT_NAME = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else ""
TICK = 0.6
ROOT = Path(__file__).resolve().parent.parent


class GatewayError(RuntimeError):
    pass


# Sign-in token from POST /auth (see sign_in); every other gateway call sends it.
TOKEN = os.environ.get("BOT_TOKEN")
# The name and password to sign in again with when the server forgets the token (it restarted).
CREDENTIALS = None

# Where the Slayer masters stand: (x, z, level, npc name in game). Aya stands in Burthorpe for
# Turael, Achtryn in Canifis for Mazchna.
SLAYER_MASTERS = {
    "Turael": (2931, 3536, 0, "Aya"),
    "Spria": (3091, 3267, 0, "Spria"),
    "Mazchna": (3510, 3510, 0, "Achtryn"),
    "Vannaka": (3145, 9914, 0, "Vannaka"),
    "Chaeldar": (2441, 4431, 0, "Chaeldar"),
    "Konar": (1308, 3786, 0, "Konar quo Maten"),
    "Nieve": (2432, 3423, 0, "Nieve"),
    "Duradel": (2868, 2983, 1, "Duradel"),
    "Krystilia": (3109, 3516, 0, "Krystilia"),
}


def sign_in(name, password):
    """Sign in with a character's name and password. The token covers its main and all clones."""
    global TOKEN, CREDENTIALS
    result = request("POST", "/auth", {"name": name, "password": password or ""})
    TOKEN = result["token"]
    if password:
        CREDENTIALS = (name, password)
    return TOKEN


_VIA = f"{os.path.splitext(os.path.basename(sys.argv[0] or 'script'))[0][:14] or 'script'} {os.getpid()}"


class _NotSent(OSError):
    """The connection never opened: nothing reached the server, so trying again is safe."""


_CONN = threading.local()


def _send(method, path, data, headers, timeout):
    """(status, body) over one kept-alive connection per thread. User-reported: WMI Provider Host took the
    server PC's CPU; netstat showed 11,194 connections on the gateway port: every request opened a new one
    (urllib closes it), and Windows keeps each closed one for 2 minutes."""
    url = urllib.parse.urlsplit(GATEWAY)
    conn = getattr(_CONN, "conn", None)
    if conn is None or _CONN.url != (url.scheme, url.netloc):
        kind = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        conn = kind(url.netloc, timeout=timeout)
        _CONN.conn, _CONN.url = conn, (url.scheme, url.netloc)
    conn.timeout = timeout
    for attempt in range(2):
        reused = conn.sock is not None
        if not reused:
            try:
                conn.connect()
            except OSError as e:
                conn.close()
                raise _NotSent(str(e)) from None
        conn.sock.settimeout(timeout)
        try:
            conn.request(method, url.path.rstrip("/") + path, body=data, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.will_close:
                conn.close()
            return resp.status, body
        except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            conn.close()
            # The server dropped an idle kept-alive connection before reading the request: send it again once
            # on a new one. On a fresh connection that's a real failure.
            if not reused or attempt:
                raise _NotSent("connection closed by the server") from None
        except BaseException:
            conn.close()
            raise


def request(method, path, body=None, timeout=15, _retry=True, _attempt=1):
    data = None if body is None else json.dumps(body).encode()
    # The server's login log shows how characters sign in (user-requested): scripts unless told otherwise.
    # The script and its process id (the server names them when a second driver cuts a trip short).
    headers = {"Content-Type": "application/json", "X-BotScape-Via": os.environ.get("BOTSCAPE_VIA") or _VIA}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    try:
        status, raw = _send(method, path, data, headers, timeout)
    except _NotSent as e:
        # A connection that never opened (timed out, refused, reset) means nothing was sent: try again a
        # few times before giving up. One failed connect stopped whole runs and the AIO then paused that
        # skill for 30 minutes (2026-11-01: dozens of "timed out" stops in an hour).
        if _attempt < 4:
            time.sleep(2 * _attempt)
            return request(method, path, body, timeout, _retry, _attempt + 1)
        raise GatewayError(f"Bot gateway is not reachable at {GATEWAY} ({e}). Is the server running?") from None
    except TimeoutError:
        # No answer in time: a GET (reading the state) is safe to ask again; an action might have happened.
        if method == "GET" and _attempt < 3:
            return request(method, path, body, timeout, _retry, _attempt + 1)
        raise
    if status >= 400:
        if status == 401 and _retry and CREDENTIALS and path != "/auth":
            # The server restarted (an update) and forgot our token: sign in again and carry on.
            sign_in(*CREDENTIALS)
            return request(method, path, body, timeout, _retry=False)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        raise GatewayError((payload.get("error") if isinstance(payload, dict) else None) or f"HTTP {status} for {path}")
    return json.loads(raw or b"null")


def report_activity(name, text, script=SCRIPT_NAME):
    """Tell the live map, manager and client what a character is doing (empty text clears it)."""
    def send():
        try:
            data = json.dumps({"name": name, "text": text, "script": script}).encode()
            req = urllib.request.Request(ACTIVITY_URL, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2).close()
        except Exception:
            pass  # the map server being down must never break a script
    import threading
    threading.Thread(target=send, daemon=True).start()


def _q(name):
    return urllib.request.quote(name.lower())


def read_env(main):
    """bots/<main>/bot.env as a dict."""
    env = {}
    path = ROOT / "bots" / main / "bot.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def _matcher(pattern):
    if pattern is None:
        return lambda _name: True
    if isinstance(pattern, re.Pattern):
        return lambda name: bool(name) and bool(pattern.search(name))
    wanted = pattern.lower()
    return lambda name: bool(name) and name.lower() == wanted


class Bot:
    def __init__(self, name, password=None):
        self.name = name.lower()
        self.password = password
        # The password is the main's (bot.env), so sign in as the main: its token covers every clone. Signing in
        # as the clone checked the main's password against the clone's own and failed (problems log 2026-11-09:
        # after a restart 4 clones got "Wrong character name or password" and locked 127.0.0.1 out for everyone).
        self.account = (os.environ.get("BOT_MAIN") or self.name).lower()
        global CREDENTIALS
        if password and CREDENTIALS is None:
            CREDENTIALS = (self.account, password)
        self._state = None
        self._chat_seen = 0

    # --- session -----------------------------------------------------------------------------

    def login(self, timeout=60):
        """Sign in, log in (if not already online) and wait until the bot is in the world."""
        if not TOKEN:
            if not self.password:
                raise GatewayError(f"No password for {self.name}: put PASSWORD=... in bot.env")
            sign_in(self.account, self.password)
        status = self.status()
        if status != "online":
            if not self.password:
                raise GatewayError(f"No password for {self.name}: put PASSWORD=... in bot.env")
            request("POST", f"/bots/{_q(self.name)}/login", {"password": self.password})
        end = time.time() + timeout
        while time.time() < end:
            data = request("GET", f"/bots/{_q(self.name)}/state")
            if data["status"] == "online" and data["state"]:
                self._state = data["state"]
                return self
            if data["status"] == "error":
                raise GatewayError(data["error"])
            time.sleep(0.5)
        raise GatewayError(f"{self.name} did not log in within {timeout}s")

    def logout(self):
        request("POST", f"/bots/{_q(self.name)}/logout")

    def status(self):
        for bot in request("GET", "/bots"):
            if bot["name"] == self.name:
                return bot["status"]
        return "offline"

    # --- state -------------------------------------------------------------------------------

    def state(self):
        """The latest snapshot (the server refreshes it every game tick)."""
        data = request("GET", f"/bots/{_q(self.name)}/state")
        if data["status"] != "online":
            raise GatewayError(f"{self.name} is {data['status']}" + (f": {data['error']}" if data["error"] else ""))
        if data.get("lastActionError"):
            self.log(f"(action refused: {data['lastActionError']})")
        self._state = data["state"]
        return self._state

    @property
    def player(self):
        return self.state()["player"]

    @property
    def position(self):
        p = self.player
        return p["x"], p["z"], p["level"]

    def inventory(self):
        return self.state()["inventory"]

    def bank(self):
        return self.state()["bank"]

    def stats(self):
        return self.state()["stats"]

    def level(self, skill):
        return self.stats()[skill.lower()]["base"]

    def xp(self, skill):
        return self.stats()[skill.lower()]["xp"]

    def inv_items(self, pattern=None):
        match = _matcher(pattern)
        return [item for item in self.inventory() if match(item["name"])]

    def inv_count(self, pattern=None):
        return sum(item["count"] for item in self.inv_items(pattern))

    def inv_full(self):
        return len(self.inventory()) >= 28

    def dialog(self):
        return self.state().get("dialog")

    def find_loc(self, pattern=None, option=None):
        """Nearest object matching name (exact, case-insensitive) or a compiled regex."""
        return self._nearest(self.state()["locs"], pattern, option)

    def find_npc(self, pattern=None, option=None):
        return self._nearest(self.state()["npcs"], pattern, option)

    def find_ground_item(self, pattern=None):
        return self._nearest(self.state()["groundItems"], pattern, None)

    def find_locs(self, pattern=None, option=None):
        return self._filter(self.state()["locs"], pattern, option)

    def find_npcs(self, pattern=None, option=None):
        return self._filter(self.state()["npcs"], pattern, option)

    @staticmethod
    def _filter(entities, pattern, option):
        match = _matcher(pattern)
        result = [e for e in entities if match(e.get("name"))]
        if option:
            result = [e for e in result if _op_index(e.get("ops"), option)]
        return result

    def _nearest(self, entities, pattern, option):
        found = self._filter(entities, pattern, option)
        return min(found, key=lambda e: e.get("distance", 0)) if found else None

    def new_messages(self):
        """Chatbox messages received since the last call."""
        messages = request("GET", f"/bots/{_q(self.name)}/chat?since={self._chat_seen}")
        if messages:
            self._chat_seen = messages[-1]["id"]
        return [m["text"] for m in messages]

    # --- actions -----------------------------------------------------------------------------

    def act(self, *actions):
        """Queue raw gateway actions for the next game tick."""
        request("POST", f"/bots/{_q(self.name)}/action", list(actions))

    def walk(self, x, z):
        self.act({"type": "walk", "x": x, "z": z})

    def trade_state(self):
        """Trade screen (0/1/2), partner, both offers/acceptances, values and requests."""
        return self.state().get("trade") or {"screen": 0, "requests": []}

    def trade_request(self, name):
        """Walk to a nearby player and request/accept their fresh trade invitation."""
        target = next((p for p in self.state()["players"]
                       if p["name"].casefold() == name.casefold()), None)
        if target is None:
            raise GatewayError(f"Trade partner {name!r} is not nearby.")
        self.act({"type": "trade_request", "index": target["index"]})

    def trade_offer(self, item, quantity=1):
        """Offer an inventory item by name/id (or a snapshot item with a slot)."""
        if isinstance(item, dict):
            slot = item["slot"]
        else:
            found = next((obj for obj in self.state()["inventory"]
                          if obj["id"] == item or obj["name"].casefold() == str(item).casefold()), None)
            if found is None:
                raise GatewayError(f"No {item!r} in inventory.")
            slot = found["slot"]
        self.act({"type": "trade_offer", "slot": slot, "quantity": quantity})
        self.wait_ticks(1)

    def trade_remove(self, slot, quantity=1):
        """Remove items by offer slot from trade_state()['offer']."""
        self.act({"type": "trade_remove", "slot": slot, "quantity": quantity})
        self.wait_ticks(1)

    def trade_accept(self):
        """Accept the currently visible screen; call again to confirm the second screen."""
        screen = self.trade_state()["screen"]
        self.act({"type": "trade_accept", "screen": screen})
        self.wait_ticks(1)

    def trade_decline(self):
        """Cancel the trade or outgoing request, retaining all offered items."""
        self.act({"type": "trade_decline"})
        self.wait_ticks(1)

    def walk_to(self, x, z, tolerance=1, timeout=60, level=None):
        """Get within `tolerance` tiles of (x, z): a short walk, or a world trip when it's far."""
        px, pz, plevel = self.position
        if max(abs(px - x), abs(pz - z)) > 15 or (level is not None and level != plevel):
            return self.travel(x, z, level=level, tolerance=tolerance, timeout=max(timeout, 600))
        end = time.time() + timeout
        while time.time() < end:
            px, pz, _ = self.position
            if max(abs(px - x), abs(pz - z)) <= tolerance:
                return True
            self.walk(x, z)
            self.wait_ticks(3)
        return False

    def run_on(self, min_energy=10):
        """Turns running on (the run orb by the minimap) when it's off and there's at least
        min_energy % run energy. Returns True if running."""
        p = self.player
        if p.get("running"):
            return True
        if (p.get("runEnergy") or 0) < min_energy:
            return False
        self.click("orbs:runbutton")
        self.wait_ticks(1)
        return bool(self.player.get("running"))

    def travel(self, x, z, level=None, tolerance=1, timeout=600):
        """Go anywhere in the world: the server plans the route (doors, stairs, ladders, caves)
        and walks it. Returns True on arrival, False if there's no route or it gave up."""
        try:
            self.run_on()   # user-requested: run whenever there's energy
        except GatewayError:
            pass
        action = {"type": "travel", "x": x, "z": z, "tolerance": tolerance}
        if level is not None:
            action["level"] = level
        previous = (self.state().get("travel") or {}).get("id")
        self.act(action)
        end = time.time() + timeout
        last = None
        _restarts = 0
        _unstuck = False
        while time.time() < end:
            trip = self.state().get("travel") or {}
            # The new trip hasn't started yet (an earlier trip to the same place doesn't count).
            if (trip.get("target") or [None, None])[:2] != [x, z] or (previous is not None and trip.get("id") == previous):
                self.wait_ticks(1)
                continue
            status, message = trip.get("status"), trip.get("message")
            if message and message != last:
                self.log(f"Travel: {message}")
                last = message
            if status == "arrived":
                return True
            if status == "failed":
                # Cut short by the character's game client opening, closing or reconnecting (a hub update
                # reopens them): not a failed route, so walk on. Those cost a 30-minute pause of the skill
                # as "Stopped" (server log: "trip ... stopped (logout or client change)").
                if message == "Stopped" and _restarts < 3:
                    _restarts += 1
                    self.wait_ticks(2)
                    previous = trip.get("id")
                    self.act(action)
                    continue
                # Places the planner can't leave by itself: the rune essence mine and some upstairs rooms
                # (server script-problems log 2026-11-10: "No route to 3013, 3355" from Falador castle's floor 2
                # and from the essence mine, again and again, in Construction, Farming, Mining...).
                if not _unstuck and (self._unstick(level) or (str(message).startswith("No route") and self._home_teleport())):
                    _unstuck = True
                    previous = trip.get("id")
                    self.act(action)
                    continue
                return False
            self.wait_ticks(2)
        self.act({"type": "stop_travel"})
        return False

    def _unstick(self, target_level=None):
        """Out of the rune essence mine (its portals) or down to the ground floor (the nearest stairs or ladder
        down). True if the bot moved somewhere the route planner can start from."""
        def first_op(entity, names):
            ops = [o.lower() for o in (entity.get("ops") or []) if o]
            return next((n for n in names if n.lower() in ops), None)

        def in_mine():
            x, z, _ = self.position
            return 2880 <= x < 2944 and 4800 <= z < 4864

        if in_mine():
            self.log("Travel: taking the portal out of the essence mine")
            for _ in range(4):
                portals = self.find_locs("Portal") + self.find_npcs("Portal")
                portal = next((p for p in portals if first_op(p, ("Use", "Enter", "Exit"))), None)
                if portal is None:
                    return False
                act = self.interact_npc if "index" in portal else self.interact_loc
                act(portal, first_op(portal, ("Use", "Enter", "Exit")))
                for _ in range(10):
                    self.wait_ticks(1)
                    if not in_mine():
                        return True
            return False
        moved = False
        downs = ("Climb-down", "Climb down", "Go-down", "Walk-down")
        for _ in range(4):
            level = self.position[2]
            # Only down towards where it's going (quest drill 2026-11-10: talking to Sanfew upstairs, a "No route" to
            # him took the bot downstairs, away from him).
            if level == 0 or (target_level is not None and level <= target_level):
                break
            x, z, _ = self.position
            stairs = [l for l in self.find_locs(re.compile(r"(?i)staircase|stairs|ladder")) if first_op(l, downs)]
            if not stairs:
                break
            near = min(stairs, key=lambda l: abs(l["x"] - x) + abs(l["z"] - z))
            self.log(f"Travel: climbing down the {str(near.get('name', 'stairs')).lower()} (floor {level})")
            self.interact_loc(near, first_op(near, downs))
            for _ in range(15):
                self.wait_ticks(1)
                if self.position[2] != level:
                    moved = True
                    break
            else:
                break
        return moved

    def _home_teleport(self):
        """Home Teleport from whichever spellbook is open (free, 30-minute cooldown). True once it moved the bot:
        the route planner can start from home when it can't from where the bot stands."""
        before = self.position
        self.log("Travel: no route from here, casting Home Teleport")
        for book in ("standard", "lunar", "zaros", "arceuus"):
            try:
                self.act({"type": "spell", "spell": f"magic_spellbook:teleport_home_{book}"})
            except GatewayError:
                continue
            for _ in range(25):
                self.wait_ticks(1)
                if self.position != before and not self.player.get("delayed"):
                    return True
        return False

    def interact_loc(self, loc, option=None):
        self.act({"type": "loc", "id": loc["id"], "x": loc["x"], "z": loc["z"], "op": _op(loc, option)})

    def interact_npc(self, npc, option=None):
        self.act({"type": "npc", "index": npc["index"], "op": _op(npc, option)})

    def attack(self, npc):
        self.interact_npc(npc, "Attack")

    def take(self, item):
        self.act({"type": "obj", "id": item["id"], "x": item["x"], "z": item["z"], "op": 3})

    def item_option(self, item, option):
        """Click an inventory item option (e.g. "Drop", "Eat", "Wield", "Bury")."""
        self.act({"type": "held", "slot": item["slot"], "op": _op(item, option)})

    def drop(self, item):
        self.item_option(item, "Drop")

    def drop_all(self, pattern):
        for item in self.inv_items(pattern):
            self.drop(item)
            self.wait_ticks(1)

    def use_on_loc(self, item, loc):
        self.act({"type": "use_on_loc", "slot": item["slot"], "id": loc["id"], "x": loc["x"], "z": loc["z"]})

    def use_on_obj(self, item, ground):
        """Use an inventory item on an item lying on the ground (a tinderbox on logs on the floor)."""
        self.act({"type": "use_on_obj", "slot": item["slot"], "id": ground["id"], "x": ground["x"], "z": ground["z"]})

    def use_on_npc(self, item, npc):
        self.act({"type": "use_on_npc", "slot": item["slot"], "index": npc["index"]})

    def use_on_item(self, item, target):
        self.act({"type": "use_on_item", "slot": item["slot"], "target": target["slot"]})

    def click(self, component, op=1, sub=-1, obj=-1):
        """Click an interface component by name, e.g. "bankmain:depositinv"."""
        self.act({"type": "button", "component": component, "op": op, "sub": sub, "obj": obj})

    def resume(self, component, sub=-1):
        """Resume a pause button, e.g. a room in the Room Creation Menu: resume("poh_add_room:kitchen", 3)."""
        self.act({"type": "resume", "component": component, "sub": sub})

    def special(self):
        """Toggle the special attack (the orb); the next attack uses it, instant specs fire now."""
        self.click("orbs:specbutton")

    def continue_dialog(self):
        self.act({"type": "continue"})

    def enter_count(self, value):
        """Answer an "Enter amount" box."""
        self.act({"type": "count", "value": int(value)})

    def pick_obj(self, item_id):
        """Answer an item search box (GE search, ::spawn) with an item id."""
        self.act({"type": "pick_obj", "id": int(item_id)})

    def choose(self, option, quantity=None):
        """Pick a dialog option by number (1-based) or by its text.

        On a Make-X chatbox (dialog interface "skillmulti", e.g. after knife on logs) the options
        are the products; quantity is how many to make (default: All, the dialog's "max").
        """
        if isinstance(option, str):
            dialog = self.dialog() or {}
            options = [o.lower() for o in dialog.get("options", [])]
            if option.lower() not in options:
                raise GatewayError(f"No dialog option '{option}' (have {dialog.get('options')})")
            option = options.index(option.lower()) + 1
        action = {"type": "choose", "option": option}
        if quantity is not None:
            action["quantity"] = int(quantity)
        self.act(action)

    def say(self, text):
        self.act({"type": "say", "text": text})

    def command(self, text):
        self.act({"type": "command", "text": text})

    def close_interface(self):
        self.act({"type": "close"})

    # --- banking -----------------------------------------------------------------------------

    def bank_open(self):
        return "bankmain" in self.state()["interfaces"]

    def open_bank(self, timeout=20):
        """Open the nearest bank booth or chest (walking there first)."""
        if self.bank_open():
            return True
        booth = self.find_loc(re.compile(r"bank", re.I), "Bank") or self.find_loc(None, "Bank")
        if booth:
            self.interact_loc(booth, "Bank")
        else:
            banker = self.find_npc(None, "Bank")
            if not banker:
                raise GatewayError("No bank booth or banker in view")
            self.interact_npc(banker, "Bank")
        return self.wait_until(self.bank_open, timeout)

    def deposit_inventory(self):
        self.click("bankmain:depositinv")
        self.wait_ticks(2)

    def deposit(self, item, amount="all"):
        """Deposit an inventory item while the bank is open: amount 1, 5, 10 or "all"."""
        op = {1: 3, 5: 4, 10: 5, "all": 8}[amount]
        self.click("bankside:items", op=op, sub=item["slot"], obj=item["id"])

    def withdraw(self, pattern, amount=1):
        """Withdraw from the open bank: 1, 5, 10, "all", or any other count (made of 10s, 5s and 1s;
        a stack like coins of 50 or more is withdrawn whole)."""
        match = _matcher(pattern)
        item = next((i for i in self.bank() if match(i["name"])), None)
        if item is None:
            raise GatewayError(f"No {pattern} in the bank")
        ops = {1: 2, 5: 3, 10: 4, "all": 7}
        if amount not in ops:
            if amount >= 50:
                amount = "all"
            else:
                for size in (10, 5, 1):
                    while amount >= size:
                        self.click("bankmain:items", op=ops[size], sub=item["slot"], obj=item["id"])
                        self.wait_ticks(1)
                        amount -= size
                return
        self.click("bankmain:items", op=ops[amount], sub=item["slot"], obj=item["id"])
        self.wait_ticks(1)

    # --- slayer ------------------------------------------------------------------------------

    def quests(self):
        """Bot Scape's quests: [{name, state, done_value, status ('not_started'/'started'/'done'),
        quest_points}]. The state is the quest's own var, the same one the quest list reads."""
        return (self.state().get("quests") or {}).get("list", [])

    def quest(self, name):
        """One quest's entry by (case-insensitive) name, or None."""
        name = name.lower()
        return next((q for q in self.quests() if q["name"].lower() == name), None)

    def quest_points(self):
        return (self.state().get("quests") or {}).get("points", 0)

    def slayer(self):
        """{"task": "hill giants" or None, "remaining", "monsters": [npc ids], "area", "master",
        "points", "streak"}."""
        return self.state().get("slayer") or {}

    def get_slayer_task(self, master="Turael", timeout=60):
        """Go to a Slayer master (see SLAYER_MASTERS) and ask for an assignment. Returns the task
        dict (see slayer()), or None when the master refused (combat level, Slayer level...)."""
        x, z, level, name = SLAYER_MASTERS[master]
        if not self.travel(x, z, level=level, tolerance=4):
            raise GatewayError(f"Couldn't get to {master}")
        npc = self.find_npc(name, "Assignment")
        if npc is None:
            raise GatewayError(f"{name} isn't here")
        self.interact_npc(npc, "Assignment")
        # Walk up to them and wait for them to answer.
        if not self.wait_until(lambda: self.dialog() is not None, timeout=20):
            return None
        end = time.time() + timeout
        while time.time() < end and self.dialog():
            self.continue_dialog()
            self.wait_ticks(2)
        task = self.slayer()
        return task if task.get("task") else None

    def task_spots(self):
        """Where the task's monsters are in the world, nearest first:
        [{"x", "z", "level", "count", "name", "distance"}] (another floor counts as far)."""
        ids = self.slayer().get("monsters") or []
        if not ids:
            return []
        x, z, level = self.position
        return request("GET", f"/world/npcs?ids={','.join(map(str, ids))}&x={x}&z={z}&level={level}")

    def best_slayer_master(self):
        """The highest Slayer master this bot can use (combat level and Slayer level)."""
        combat = self.player.get("combatLevel") or 3
        slayer = self.level("slayer")
        # The quest that lets you reach each master (problems log 2026-11-09: Slayer walked to Mazchna in Canifis
        # and the Paterdomus barrier turned it back: "You need to complete Priest in Peril to pass").
        reach = {"Mazchna": "Priest in Peril", "Chaeldar": "Lost City", "Duradel": "Shilo Village"}
        for name, need_combat, need_slayer in (("Duradel", 100, 50), ("Nieve", 85, 1), ("Chaeldar", 70, 1),
                                               ("Vannaka", 40, 1), ("Mazchna", 20, 1)):
            quest = self.quest(reach[name]) if name in reach else None
            if name in reach and (quest or {}).get("status") != "done":
                continue
            if combat >= need_combat and slayer >= need_slayer:
                return name
        return "Spria"

    def is_task_monster(self, npc):
        """Is this npc (from find_npcs) on the bot's Slayer task?"""
        return npc.get("id") in (self.slayer().get("monsters") or [])

    # --- prayer ------------------------------------------------------------------------------

    def prayers(self):
        """{"points": prayer points left, "active": ["Protect from Magic", ...]}."""
        return self.state().get("prayer") or {"points": 0, "active": []}

    def pray(self, name, on=True):
        """Turn a prayer on (or off with on=False), e.g. bot.pray("Protect from Magic"). The server
        clicks that prayer's button; turning on a protection prayer turns the other one off."""
        self.act({"type": "prayer", "name": name, "on": on})
        self.wait_ticks(1)

    def prayers_off(self):
        for name in list(self.prayers().get("active", [])):
            self.pray(name, on=False)

    # --- grand exchange ----------------------------------------------------------------------

    def go_to_ge(self):
        """Travel to the Grand Exchange (offers can only be made there)."""
        return self.travel(3164, 3485, tolerance=4)

    def ge_offers(self):
        """[{"slot", "type": "buy"/"sell", "item", "id", "price", "completed", "total", "finished",
        "aborted", "collectItems", "collectCoins"}]."""
        return self.state().get("ge") or []

    def ge_buy(self, item, quantity=1, price=None):
        """Offer to buy (item name or id). Price defaults to the guide price; coins are taken now."""
        action = {"type": "ge_buy", "item": item, "quantity": quantity}
        if price is not None:
            action["price"] = price
        self.act(action)
        self.wait_ticks(2)

    def ge_sell(self, item, quantity=None, price=None):
        """Offer to sell (item name or id; noted or not). Quantity defaults to everything carried."""
        action = {"type": "ge_sell", "item": item}
        if quantity is not None:
            action["quantity"] = quantity
        if price is not None:
            action["price"] = price
        self.act(action)
        self.wait_ticks(2)

    def ge_history(self):
        """The last 20 finished trades: [{"type": "buy"/"sell", "item", "id", "count", "price" (each), "time"}]."""
        return self.state().get("geHistory") or []

    def ge_modify(self, slot, quantity=None, price=None):
        """Change an active offer's quantity and/or price, keeping what it already traded."""
        action = {"type": "ge_modify", "slot": slot}
        if quantity is not None:
            action["quantity"] = quantity
        if price is not None:
            action["price"] = price
        self.act(action)
        self.wait_ticks(2)

    def ge_set(self, name):
        """Swap an item set (e.g. "Rune armour set (lg)") for its pieces, or the pieces for the set."""
        self.act({"type": "ge_set", "set": name})
        self.wait_ticks(2)

    def ge_abort(self, slot):
        self.act({"type": "ge_abort", "slot": slot})
        self.wait_ticks(2)

    def ge_collect(self, bank=False):
        """Collect every finished item and coin (to the bank with bank=True)."""
        self.act({"type": "ge_collect", "bank": bank})
        self.wait_ticks(2)

    # --- shops -------------------------------------------------------------------------------

    def shop(self):
        """The open shop, or None: {"title", "stock": [{slot, name, count, price}], "sell": [...]}."""
        return self.state().get("shop")

    def open_shop(self, keeper=None, timeout=20):
        """Talk-trade with the nearest shopkeeper (an NPC with a "Trade" option) and wait for the shop."""
        if self.shop():
            return True
        npc = self.find_npc(keeper, "Trade") if keeper else self.find_npc(None, "Trade")
        if npc is None:
            raise GatewayError(f"No shopkeeper{' ' + keeper if keeper else ''} with a Trade option in view")
        self.interact_npc(npc, "Trade")
        return self.wait_until(lambda: self.shop() is not None, timeout)

    def buy(self, pattern, amount=1):
        """Buy from the open shop. Any amount: sent as 50s, 10s, 5s and 1s."""
        match = _matcher(pattern)
        shop = self.shop() or {}
        item = next((i for i in shop.get("stock", []) if match(i["name"])), None)
        if item is None:
            raise GatewayError(f"The shop has no {pattern}")
        for size in (50, 10, 5, 1):
            while amount >= size:
                self.act({"type": "shop_buy", "slot": item["slot"], "amount": size})
                amount -= size
                self.wait_ticks(1)

    def sell(self, pattern, amount=1):
        """Sell inventory items to the open shop (any amount, sent as 50s, 10s, 5s and 1s)."""
        match = _matcher(pattern)
        for size in (50, 10, 5, 1):
            while amount >= size:
                item = next((i for i in self.inventory() if match(i["name"])), None)
                if item is None:
                    return
                self.act({"type": "shop_sell", "slot": item["slot"], "amount": size})
                amount -= size
                self.wait_ticks(1)

    # --- magic -------------------------------------------------------------------------------

    @staticmethod
    def _spell(name):
        """"Wind Strike" or "wind_strike" -> the spellbook component "magic_spellbook:wind_strike"."""
        return name if ":" in name else "magic_spellbook:" + name.strip().lower().replace(" ", "_")

    def cast_on_npc(self, spell, npc):
        self.act({"type": "spell_on_npc", "spell": self._spell(spell), "index": npc["index"]})

    def cast_on_player(self, spell, player):
        """A spell on another player from state()["players"] (e.g. Tele Block)."""
        self.act({"type": "spell_on_player", "spell": self._spell(spell), "index": player["index"]})

    def cast_on_item(self, spell, item):
        self.act({"type": "spell_on_item", "spell": self._spell(spell), "slot": item["slot"]})

    def emote(self, name):
        """Perform an emote from the emote tab by name, e.g. "Jump for Joy"."""
        self.act({"type": "emote", "name": name})

    def cast(self, spell):
        """A spell without a target, e.g. "Varrock Teleport"."""
        self.act({"type": "spell", "spell": self._spell(spell)})

    # --- waiting -----------------------------------------------------------------------------

    def wait_ticks(self, ticks=1):
        time.sleep(TICK * ticks)

    def wait_until(self, predicate, timeout=30, poll=0.3):
        end = time.time() + timeout
        while time.time() < end:
            if predicate():
                return True
            time.sleep(poll)
        return False

    def idle(self):
        p = self.player
        return not p["interacting"] and not p["hasRoute"] and not p["moving"]

    def log(self, message):
        print(message, flush=True)
        report_activity(self.name, str(message))


def _op_index(ops, option):
    if not ops or option is None:
        return None
    for i, op in enumerate(ops):
        if op and op.lower() == option.lower():
            return i + 1
    return None


# Options the game client shows when the cache leaves the slot empty: inventory items get "Drop"
# as option 5 and ground items get "Take" as option 3.
DEFAULT_OPS = {"drop": 5, "take": 3}


def _op(entity, option):
    if option is None:
        return 1
    index = _op_index(entity.get("ops"), option)
    if index is None:
        ops = entity.get("ops") or []
        default = DEFAULT_OPS.get(option.lower())
        if default and (len(ops) < default or ops[default - 1] is None):
            return default
        raise GatewayError(f"{entity.get('name')} has no option '{option}' (options: {entity.get('ops')})")
    return index


def script_options(options):
    """The options a script offers, with the player's choices.

    A script declares them at the top as OPTIONS = {"cook": ("Cook the chicken", True), ...}
    (name: (label, default)). A True/False default is a checkbox, a whole number a number field
    (e.g. a level goal). The hub shows them on the script's card and the client asks for them when
    you press Run; the choices are saved in .options.json next to the script. On the command line
    --no-<name> / --<name> (checkboxes) and --<name> 50 (numbers) win. Returns {name: value}.
    """
    script = Path(sys.argv[0]).resolve()
    saved = {}
    try:
        saved = json.loads((script.parent / ".options.json").read_text(encoding="utf-8")).get(script.name, {})
    except (OSError, ValueError, AttributeError):
        pass
    args = sys.argv[1:]
    chosen = {}
    for name, (_label, default) in options.items():
        if isinstance(default, bool):
            value = bool(saved.get(name, default))
            if f"--no-{name}" in args:
                value = False
            elif f"--{name}" in args:
                value = True
        else:
            try:
                value = int(saved.get(name, default))
            except (TypeError, ValueError):
                value = int(default)
            if f"--{name}" in args and args.index(f"--{name}") + 1 < len(args):
                try:
                    value = int(args[args.index(f"--{name}") + 1])
                except ValueError:
                    pass
        chosen[name] = value
    return chosen


def _process_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5                   # access denied: it exists
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def stop_stray_brain():
    """Script-problems log 2026-11-10: AIO brains from the night before kept running next to the new ones, so each
    character did two things at once (one thieved while the other chopped, quested and banked). AIO.py writes the
    character's owner (bots/<main>/.aio_owner[.<clone>].json) and tags its scripts with AIO_BRAIN; a script an
    older brain started (no tag, a different live owner) stops that brain, and itself with it."""
    args = sys.argv[1:]
    if ("--main" in args or (args and not args[0].startswith("--"))
            or Path(sys.argv[0]).name == "AIO.py" or not os.environ.get("RS_BOT")):
        return   # started by the hub or by hand
    main_name = (os.environ.get("BOT_MAIN") or "simba").lower()
    character = os.environ["RS_BOT"].lower()
    owner_file = (Path(__file__).resolve().parents[1] / "bots" / main_name
                  / (".aio_owner.json" if character == main_name else f".aio_owner.{character}.json"))
    if os.environ.get("AIO_BRAIN"):
        _watch_owner(owner_file, os.environ["AIO_BRAIN"], character)
        return   # started by the new AIO
    try:
        owner = int(json.loads(owner_file.read_text()).get("pid") or 0)
    except (OSError, ValueError, AttributeError, TypeError):
        return
    parent = os.getppid()
    if not owner or owner == parent or not _process_alive(owner):
        return
    print(f"Stopped: an older AIO brain (process {parent}) started this while a newer one (process {owner}) runs "
          f"{character}: stopping the older brain.", flush=True)
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(parent)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    raise SystemExit(3)


def _watch_owner(owner_file, brain, character):
    """Script-problems log 2026-11-10 16:57: a new brain took cyril over while its old brain's Runecrafting kept
    running, so for 15 minutes one script ran to the Body altar while the other thieved with the same backpack. A
    script its brain tagged (AIO_BRAIN) stops itself once another live brain owns the character."""
    def watch():
        while True:
            time.sleep(20)
            try:
                owner = json.loads(owner_file.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(owner, dict) or owner.get("id") in (None, brain):
                continue
            if not _process_alive(int(owner.get("pid") or 0)):
                continue
            print(f"Stopped: a newer AIO brain (process {owner.get('pid')}) runs {character} now.", flush=True)
            os._exit(3)

    threading.Thread(target=watch, name="aio-owner-watch", daemon=True).start()


def run(main):
    """Run `main(bot)` for the character named on the command line.

    python Mining.py <character> [--main <main>]

    The password comes from bots/<main>/bot.env (clones use their main's password).
    """
    stop_stray_brain()
    args = sys.argv[1:]
    script_main = Path(sys.argv[0]).resolve().parent.name
    # AIO starts skill scripts with no character on the command line: it sets BOT_MAIN (the main) and RS_BOT
    # (the main or a clone) instead, like lib/core.py reads (problems log 2026-11-09: Construction and Slayer
    # tried to sign in as "botscape", the scripts folder's name).
    main_name = (args[args.index("--main") + 1] if "--main" in args
                 else os.environ.get("BOT_MAIN") or script_main)
    character = (args[0] if args and not args[0].startswith("--")
                 else os.environ.get("RS_BOT") or main_name)
    env = read_env(main_name)
    os.environ.setdefault("BOT_MAIN", main_name)      # Bot signs in as the main (see Bot.__init__)
    bot = Bot(character, env.get("PASSWORD"))
    try:
        bot.login()
        bot.log(f"Starting {SCRIPT_NAME} at {bot.position[0]}, {bot.position[1]}")
        main(bot)
    except KeyboardInterrupt:
        pass
    except GatewayError as e:
        bot.log(f"Stopped: {e}")
        sys.exit(1)
    finally:
        report_activity(character, "")
