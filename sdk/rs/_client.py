from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import botscape as gateway
from ._codec import RSObject, Result, decode


class RSError(RuntimeError):
    def __init__(self, message, code=None, method=None):
        super().__init__(message)
        self.message = message
        self.code, self.method = code, method


class StaleEntityError(RSError):
    pass


class FeatureUnavailable(RuntimeError):
    """Permanent capability gap; do not feed this into reconnection loops."""


def result(success, message="", **fields):
    return Result(success=bool(success), message=message, **fields)


def unsupported(feature):
    return result(False, f"{feature} isn't on this server yet", reason="unsupported")


def matches(pattern, text):
    if pattern is None:
        return True
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(text or ""))
    return str(pattern).lower() in (text or "").lower()


def main_name():
    args = sys.argv[1:]
    if "--main" in args:
        return args[args.index("--main") + 1].lower()
    return os.environ.get("BOT_MAIN") or Path(sys.argv[0]).resolve().parent.name.lower()


def configure_script():
    """Remove only the manager prefix; preserve script-specific positional args.

    In particular, AIOFighter's monster and AutoQuester's quest remain intact.
    Child processes inherit RS_BOT/BOT_MAIN after the prefix has been removed.
    """
    args = sys.argv[1:]
    if "--main" in args:
        idx = args.index("--main")
        if idx + 1 >= len(args):
            raise SystemExit("--main requires a character name")
        os.environ["BOT_MAIN"] = args[idx + 1].lower()
        del args[idx:idx + 2]
        if args and not args[0].startswith("-"):
            os.environ["RS_BOT"] = args.pop(0).lower()
        sys.argv[1:] = args
    elif args and not args[0].startswith("-") and gateway.read_env(args[0]):
        os.environ["RS_BOT"] = args.pop(0).lower()
        os.environ.setdefault("BOT_MAIN", os.environ["RS_BOT"])
        sys.argv[1:] = args
    os.environ.setdefault("BOT_MAIN", Path(sys.argv[0]).resolve().parent.name.lower())
    os.environ.setdefault("RS_BOT", os.environ["BOT_MAIN"])
    gap = SCRIPT_GAPS.get(Path(sys.argv[0]).stem)
    if gap and not any(flag in args for flag in ("--list", "--audit")):
        print(f"Stopped: {gap} isn't on this server yet", flush=True)
        raise SystemExit(3)
    # Standalone scripts don't share core.run's exception handler.
    previous = sys.excepthook
    def hook(kind, error, tb):
        if isinstance(error, (FeatureUnavailable, RSError)):
            print(f"Stopped: {error}", flush=True)
        else:
            previous(kind, error, tb)
    sys.excepthook = hook


# Confirmed absent content modules, or required state/actions absent in gateway. (Agility, Thieving,
# Fishing, Cooking, Runecrafting, Herblore and Crafting are on the server now.)
SCRIPT_GAPS = {
    "Jewellery": "Jewellery crafting and enchanting",
    "Collect": "Snape grass spawns at the script's collection sites",
    "AutoQuester": "Quest routes and quest progress support",
    "Magic": "Spell targeting through the gateway",
}


def connect_sync(bot=None, port=None, host="127.0.0.1", *, check=True):
    gap = SCRIPT_GAPS.get(Path(sys.argv[0]).stem)
    if gap:
        print(f"Stopped: {gap} isn't on this server yet", flush=True)
        raise SystemExit(3)
    gateway.stop_stray_brain()
    client = SyncClient(bot, port, host)
    if check:
        client._login()
    return client


class SyncClient:
    def __init__(self, bot=None, port=None, host="127.0.0.1"):
        # Explicit API names are respected; the shim has already set RS_BOT for scripts.
        self.bot_name = (bot or os.environ.get("RS_BOT") or main_name()).lower()
        self.bot = self.sdk = self
        env = gateway.read_env(main_name())
        if not env and not os.environ.get("BOT_MAIN") and "--main" not in sys.argv:
            env = gateway.read_env(self.bot_name)
        self._gateway = gateway.Bot(self.bot_name, env.get("PASSWORD"))
        self._chat_id, self._messages = 0, []
        self._received = 0
        self._tick = None
        self._combat_target = None
        self._failures = {}
        self.last_unsupported = None

    def _unsupported(self, feature):
        outcome = unsupported(feature)
        self.last_unsupported = outcome
        return outcome

    def _login(self):
        try:
            self._gateway.login()
        except gateway.GatewayError as error:
            raise RSError(str(error)) from None

    def close(self):
        """Release local controller resources; manager owns the character session."""

    def __enter__(self):
        self._login()
        return self

    def __exit__(self, *args):
        self.close()

    # User-reported: scripts idled between actions. Every state read is a round trip to the server
    # (twice with chat), and a single step can read it dozens of times: reads within 120 ms (a fifth
    # of a game tick) share one answer. Sending an action clears it.
    _CACHE_SECONDS = 0.12

    def _raw(self):
        cached = getattr(self, "_raw_cache", None)
        if cached and time.monotonic() - cached[0] < self._CACHE_SECONDS:
            return cached[1]
        try:
            raw = gateway.request("GET", f"/bots/{gateway._q(self.bot_name)}/state")
        except gateway.GatewayError as error:
            raise RSError(str(error)) from None
        if raw.get("status") != "online" or not raw.get("state"):
            self._raw_cache = None
            raise RSError(f"{self.bot_name} is {raw.get('status')}: {raw.get('error') or ''}")
        # Only a good answer is reused (an "offline, no state" one got cached and crashed the AIO).
        self._raw_cache = (time.monotonic(), raw)
        if raw["state"]["tick"] != self._tick:
            self._tick = raw["state"]["tick"]
            self._received = time.monotonic()
        return raw

    @staticmethod
    def _entity(value, kind):
        item = dict(value)
        if kind == "loc":
            old_names = {"Oak tree": "Oak", "Willow tree": "Willow", "Yew tree": "Yew"}
            item["serverName"] = item.get("name")
            item["name"] = old_names.get(item.get("name"), item.get("name"))
        ops = list(item.get("ops") or [])
        if kind == "inv":
            ops += [None] * max(0, 5 - len(ops))
            if not ops[4]:
                ops[4] = "Drop"
        elif kind == "ground":
            ops = [None, None, "Take"]
        item.update({"$kind": kind, "options": [op for op in ops if op],
                     "optionsWithIndex": [{"text": op, "opIndex": i + 1} for i, op in enumerate(ops) if op]})
        if kind == "npc":
            # Snapshot has no other-NPC engagement data: unknown, not 'reachable=True'.
            item.update(inCombat=None, reachable=None)
        return item

    def get_state(self, allow_stale=False):
        raw = self._raw()["state"]
        tick = raw["tick"]
        # Chat only needs asking once per state answer.
        if getattr(self, "_chat_for", None) is self._raw_cache:
            chat = []
        else:
            try:
                chat = gateway.request("GET", f"/bots/{gateway._q(self.bot_name)}/chat?since={self._chat_id}")
            except gateway.GatewayError as error:
                raise RSError(str(error)) from None
            self._chat_for = self._raw_cache
        for msg in chat:
            self._chat_id = max(self._chat_id, msg["id"])
            self._messages.append(dict(msg, tick=msg.get("tick", tick)))
        self._messages = self._messages[-100:]
        stats = raw["stats"]
        skills = [dict(name=name.capitalize(), level=s["level"], baseLevel=s["base"], experience=s["xp"])
                  for name, s in stats.items()]
        p = dict(raw["player"])
        hp = stats.get("hitpoints", {})
        target = next((n for n in raw["npcs"] if n["index"] == self._combat_target), None)
        fighting = bool(target and target.get("hp", 0) > 0 and p["interacting"])
        p.update(worldX=p["x"], worldZ=p["z"], hp=hp.get("level"), maxHp=hp.get("base"),
                 animId=None, respawnCount=None,
                 combat=dict(inCombat=fighting, targetType="npc" if fighting else None,
                             targetIndex=self._combat_target if fighting else None))
        d = raw.get("dialog")
        dialog = dict(isOpen=bool(d), options=[], text="", interface=None)
        if d:
            dialog.update(d)
            dialog.update(text=" ".join(d.get("texts", [])),
                          options=[dict(text=txt, index=i, option=i) for i, txt in enumerate(d.get("options", []))])
        state = dict(tick=tick, player=p, skills=skills, gameMessages=self._messages,
                     dialog=dialog, modalOpen=bool(d or "bankmain" in raw["interfaces"]),
                     interfaces=raw["interfaces"], shop=self._shop(raw.get("shop")),
                     interface=dict(isOpen=False, options=[]), combatStyle=None,
                     capabilities=dict(animation=False, combatTarget=False, shopStock=True,
                                       questProgress=False, scanRadius=15))
        for source, dest, kind in [("inventory", "inventory", "inv"), ("equipment", "equipment", "equipment"),
                                    ("bank", "bankItems", "bank"), ("npcs", "nearbyNpcs", "npc"),
                                    ("locs", "nearbyLocs", "loc"), ("groundItems", "groundItems", "ground"),
                                    ("players", "nearbyPlayers", "player")]:
            state[dest] = [self._entity(e, kind) for e in raw.get(source, [])]
        return decode(state)

    @staticmethod
    def _shop(shop):
        """The open shop's stock as the scripts read it (name, buyPrice, count)."""
        if not shop:
            return dict(isOpen=False, shopItems=[])
        items = [dict(name=i.get("name"), buyPrice=i.get("price"), sellPrice=i.get("sellPrice"),
                      count=i.get("count", 0), id=i.get("id"), slot=i.get("slot"))
                 for i in shop.get("stock", [])]
        return dict(isOpen=True, shopItems=items, name=shop.get("name"))

    def get_state_age(self):
        self._raw()  # live snapshots; never pretend a cached value is current
        return (time.monotonic() - self._received) * 1000

    def get_inventory(self): return self.get_state().inventory
    def get_equipment(self): return self.get_state().equipment
    def get_bank_items(self): return self.get_state().bankItems
    def get_nearby_npcs(self): return self.get_state().nearbyNpcs
    def get_nearby_locs(self): return self.get_state().nearbyLocs
    def get_nearby_players(self): return self.get_state().nearbyPlayers
    def get_ground_items(self): return self.get_state().groundItems
    def get_dialog(self): return self.get_state().dialog
    def get_skills(self): return self.get_state().skills
    def get_skill(self, name):
        # OSRS shows "Runecraft"; the server's stat is "runecrafting".
        name = {"runecraft": "runecrafting"}.get(name.lower(), name.lower())
        return next((s for s in self.get_skills() if s.name.lower() == name), None)
    def get_skill_xp(self, name): return self.get_skill(name).experience
    def require_feature(self, feature):
        gaps = {}  # shops and rune essence travel are on the server now
        if feature in gaps:
            raise FeatureUnavailable(f"{gaps[feature]} isn't on this server yet")
    def count_inventory_items(self, pattern):
        return sum(i.count for i in self.get_inventory() if matches(pattern, i.name))
    def is_bank_open(self): return "bankmain" in self.get_state().interfaces

    @staticmethod
    def _find(items, target=None):
        if isinstance(target, dict):
            # An npc is found by its index alone: it walks, so the x/z it was seen at go stale
            # (Thieving's Man pickpocketing failed with "No nearby npc matching" in script-problems.log).
            keys = ("index",) if target.get("index") is not None else ("id", "slot", "x", "z")
            return next((i for i in items if all(i.get(k) == target[k] for k in keys if k in target)), None)
        if isinstance(target, (int, float)):
            return next((i for i in items if i.get("slot", i.get("index", i.get("id"))) == target), None)
        found = [i for i in items if matches(target, i.get("name"))]
        return min(found, key=lambda i: (len(i.get("name") or ""), i.get("distance", 0)), default=None)

    def find_inventory_item(self, pattern): return self._find(self.get_inventory(), pattern)
    def find_bank_item(self, pattern): return self._find(self.get_bank_items(), pattern)
    def find_equipment_item(self, pattern): return self._find(self.get_equipment(), pattern)
    find_equipped_item = find_equipment_item
    def find_nearby_npc(self, pattern, options=None): return self._find(self.get_nearby_npcs(), pattern)
    def find_nearby_loc(self, pattern, options=None): return self._find(self.get_nearby_locs(), pattern)
    def find_ground_item(self, pattern, options=None): return self._find(self.get_ground_items(), pattern)
    def scan_nearby_locs(self, radius=15):
        # The gateway cannot widen visibility. Do not fabricate unseen entities.
        return [l for l in self.get_nearby_locs() if l.distance <= (radius or 15)]

    def wait_for_ticks(self, ticks=1):
        start = self._raw()["state"]["tick"]
        # Waits out a stalled server: 5 s stopped simba's scripts during slow ticks ("Server snapshots stopped
        # advancing", 26 times on 2026-11-09, none at a restart). A server that's really gone still ends it.
        end = time.monotonic() + max(30, (ticks or 1) * 1.2 + 20)
        while time.monotonic() < end:
            if self._raw()["state"]["tick"] >= start + (ticks or 1):
                return self.get_state()
            time.sleep(.15)
        raise RSError("Server snapshots stopped advancing")

    def _send(self, **action):
        self._raw_cache = None
        try:
            self._gateway.act(action)
            return result(True, "Action queued; effect not yet confirmed")
        except gateway.GatewayError as error:
            return result(False, str(error))

    def _wait(self, predicate, timeout=8):
        end = time.monotonic() + timeout
        initial_tick = self._raw()["state"]["tick"]
        while time.monotonic() < end:
            raw = self._raw()
            if predicate(raw["state"]):
                return result(True, "Effect confirmed")
            if raw["state"]["tick"] > initial_tick and raw.get("lastActionError"):
                return result(False, raw["lastActionError"])
            time.sleep(.25)
        return result(False, "No effect before timeout; content may be unavailable or target unreachable", reason="timeout")

    @staticmethod
    def _changed(before, after):
        return any(before.get(key) != after.get(key) for key in ("inventory", "equipment", "bank", "stats", "dialog", "interfaces"))

    def _effect(self, action, timeout=8, started=False):
        before = self._raw()["state"]
        seen = self._chat_id
        sent = self._send(**action)
        if not sent.success: return sent
        # "I can't reach that!" (a Man behind a wall): fail at once instead of after the whole timeout.
        def done(s):
            if s["tick"] > before["tick"] and (
                    self._changed(before, s) or s["player"]["level"] != before["player"]["level"] or
                    (started and s["player"]["delayed"] and not before["player"]["delayed"])):
                return True
            return any(m.get("id", 0) > seen and "can't reach" in m.text.lower() for m in self.get_state().gameMessages)
        outcome = self._wait(done, timeout)
        if outcome.success and any(m.get("id", 0) > seen and "can't reach" in m.text.lower()
                                   for m in self.get_state().gameMessages):
            return result(False, "I can't reach that!", reason="unreachable")
        if not outcome.success and outcome.reason == "timeout":
            messages = self.get_state().gameMessages
            if any(m.get("id", 0) > seen and "nothing interesting happens" in m.text.lower() for m in messages):
                return self._unsupported(f"{action['type']} interaction for target {action.get('id', action.get('index', 'item'))}")
        return outcome

    def send_walk(self, x, z, running=None): return self._send(type="walk", x=int(x), z=int(z))
    def _travel(self, x, z, tolerance, timeout):
        """Server-side world travel (see BotTravel): plan the route and walk it."""
        previous = (self._raw()["state"].get("travel") or {}).get("id")
        try:
            self._gateway.run_on()     # user-requested: run whenever there's energy, long trips too
        except Exception:
            pass
        sent = self._send(type="travel", x=x, z=z, tolerance=tolerance)
        if not sent.success:
            return sent
        end = time.monotonic() + timeout
        waited, resent = 0, False
        while time.monotonic() < end:
            trip = self._raw()["state"].get("travel") or {}
            # The new trip hasn't started yet (an earlier trip to the same place doesn't count).
            if (trip.get("target") or [None, None])[:2] != [x, z] or (previous is not None and trip.get("id") == previous):
                waited += 1
                if waited == 10 and not resent:  # the action was dropped (busy, a dialogue): ask again once
                    resent = True
                    self._send(type="travel", x=x, z=z, tolerance=tolerance)
                elif waited > 20:
                    return result(False, f"Travel to ({x}, {z}) didn't start", reason="timeout")
                time.sleep(0.6)
                continue
            if trip.get("status") == "arrived":
                return result(True, "Arrived")
            if trip.get("status") == "failed":
                return result(False, trip.get("message") or "No route", reason="unreachable")
            time.sleep(1.2)
        self._send(type="stop_travel")
        return result(False, f"Travel to ({x}, {z}) timed out", reason="timeout")

    def walk_to(self, x, z, tolerance=3, options=None):
        timeout = (options or {}).get("timeout", 120000) / 1000
        try:
            self._gateway.run_on()     # every script runs when there's run energy
        except Exception:
            pass
        p = self._raw()["state"]["player"]
        if max(abs(x - p["x"]), abs(z - p["z"])) > 15:
            # Far away: let the server plan the whole route (doors, stairs, ladders, caves).
            return self._travel(x, z, tolerance if tolerance is not None else 3, max(timeout, 600))
        end = time.monotonic() + timeout
        last, stationary, opened = None, 0, set()
        while time.monotonic() < end:
            p = self._raw()["state"]["player"]
            pos = (p["x"], p["z"])
            dx, dz = x - pos[0], z - pos[1]
            distance = max(abs(dx), abs(dz))
            if distance <= (tolerance if tolerance is not None else 3):
                return result(True, "Arrived")
            stationary = stationary + 1 if last == pos else 0
            last = pos
            if stationary >= 2:
                doors = [l for l in self.get_nearby_locs() if l.distance <= 4 and
                         any(matches(re.compile(r"^open$", re.I), o) for o in l.options) and
                         (l.id, l.x, l.z) not in opened]
                if doors:
                    door = min(doors, key=lambda l: l.distance)
                    opened.add((door.id, door.x, door.z))
                    self._send(type="loc", id=door.id, x=door.x, z=door.z, op=self._op(door, "Open"))
                    time.sleep(1.2)
                    stationary = 0
                    continue
                if stationary >= 4:
                    return self._travel(x, z, tolerance if tolerance is not None else 3, max(end - time.monotonic(), 60))
            # Local routefinder has a finite search window. Click intermediate tiles.
            scale = min(1, 12 / distance)
            sent = self.send_walk(round(pos[0] + dx * scale), round(pos[1] + dz * scale))
            if not sent.success: return sent
            time.sleep(1.8)
        return result(False, f"Walk timed out before ({x}, {z})", reason="timeout")

    @staticmethod
    def _op(entity, option=None):
        if isinstance(option, (int, float)): return int(option)
        if option is None: return 1
        for o in entity.optionsWithIndex:
            if matches(option, o.text): return o.opIndex
        if isinstance(option, str) and option.lower() in gateway.DEFAULT_OPS:
            return gateway.DEFAULT_OPS[option.lower()]
        return None

    def _interact(self, kind, target, option=None, timeout=10, complete=False):
        items = self.get_nearby_locs() if kind == "loc" else self.get_nearby_npcs()
        ent = self._find(items, target)
        if not ent: return result(False, f"No nearby {kind} matching {target}", reason="not_found")
        op = self._op(ent, option)
        if op is None: return result(False, f"{ent.name} has no option {option}")
        if ent.distance > 2:
            moved = self.walk_to(ent.x, ent.z, 2, {"timeout": 20000})
            if not moved.success: return moved
        action = dict(type=kind, op=op)
        action.update(dict(id=ent.id, x=ent.x, z=ent.z) if kind == "loc" else dict(index=ent.index))
        if complete:
            before = self._raw()["state"]
            skill = "mining" if matches("mine", str(option)) else "woodcutting"
            sent = self._send(**action)
            if not sent.success: return sent
            return self._wait(lambda s: s["stats"][skill]["xp"] > before["stats"][skill]["xp"]
                              or s["inventory"] != before["inventory"], timeout)
        return self._effect(action, timeout, started=True)

    def interact_loc(self, target, option=None): return self._interact("loc", target, option)
    def interact_npc(self, target, option=None): return self._interact("npc", target, option)
    def open_door(self, target=None): return self.interact_loc(target or re.compile(r"door|gate", re.I), "Open")
    def chop_tree(self, target=None): return self._interact("loc", target or "Tree", re.compile("chop", re.I), 35, True)

    def mine_rock(self, target=None, options=None):
        # LostCity rocks are all 'Rocks'; Bot Scape names their ore in the loc.
        pattern = target
        if not isinstance(target, dict):
            text = target.pattern if isinstance(target, re.Pattern) else str(target or "")
            text = re.sub(r"(?:\\?\s*ore)", "", text, flags=re.I)
            pattern = re.compile(text, re.I) if text else re.compile("rocks", re.I)
        return self._interact("loc", pattern, "Mine", (options or {}).get("timeout", 35000) / 1000, True)

    def send_use_item(self, slot, option=1, interface_id=None):
        return self._send(type="held", slot=int(slot), op=int(option or 1))
    def send_drop_item(self, slot): return self.send_use_item(slot, 5)
    def send_use_item_on_item(self, source_slot, target_slot):
        return self._send(type="use_on_item", slot=int(source_slot), target=int(target_slot))
    def send_talk_to_npc(self, npc_index): return self._send(type="npc", index=int(npc_index), op=1)

    def drop_item(self, target, amount="all"):
        remaining = 28 if amount in (None, -1, "all") else int(amount)
        dropped = 0
        while dropped < remaining:
            ent = self.find_inventory_item(target)
            if not ent: break
            sent = self.send_drop_item(ent.slot)
            if not sent.success: return sent
            r = self._wait(lambda s: not any(i["slot"] == ent.slot and i["id"] == ent.id for i in s["inventory"]))
            if not r.success: return r
            dropped += 1
        return result(dropped > 0, f"Dropped {dropped} slots", amountDropped=dropped)

    def pickup_item(self, target):
        ent = self.find_ground_item(target)
        if not ent: return result(False, "Ground item not visible", reason="not_found")
        before = sum(i.count for i in self.get_inventory() if i.id == ent.id)
        seen = self._chat_id
        sent = self._send(type="obj", id=ent.id, x=ent.x, z=ent.z, op=3)
        if not sent.success: return sent
        # Behind a fence ("I can't reach that!"): say so at once instead of waiting 15 s for nothing.
        end = time.monotonic() + 15
        while time.monotonic() < end:
            state = self._raw()["state"]
            if sum(i["count"] for i in state["inventory"] if i["id"] == ent.id) > before:
                return result(True, "Picked up")
            if any(m.get("id", 0) > seen and "can't reach" in m.text.lower() for m in self.get_state().gameMessages):
                return result(False, "I can't reach that!", reason="unreachable")
            time.sleep(0.6)
        return result(False, "No pickup before timeout", reason="timeout")

    def _held(self, target, option, dest=None):
        item = self.find_inventory_item(target)
        if not item: return result(False, f"Inventory item not found: {target}")
        op = self._op(item, option)
        if op is None: return result(False, f"{item.name} has no {option} option")
        if dest:
            before = sum(i.count for i in self.get_equipment() if i.id == item.id)
            sent = self.send_use_item(item.slot, op)
            if not sent.success: return sent
            return self._wait(lambda s: sum(i["count"] for i in s[dest] if i["id"] == item.id) > before)
        before = sum(i.count for i in self.get_inventory() if i.id == item.id)
        sent = self.send_use_item(item.slot, op)
        if not sent.success: return sent
        return self._wait(lambda s: sum(i["count"] for i in s["inventory"] if i["id"] == item.id) < before)

    def equip_item(self, target):
        return self._held(target, re.compile(r"^(wield|wear|equip)$", re.I), "equipment")
    def eat_food(self, target=None):
        if target is None:
            target = next((i for i in self.get_inventory() if self._op(i, "Eat")), None)
            if not target: return result(False, "No food in inventory")
        return self._held(target, "Eat")
    def unequip_item(self, target):
        return self._unsupported("Removing equipment through the gateway (equipment slot component mapping missing)")

    def open_bank(self, timeout=10000):
        if self.is_bank_open(): return result(True, "Bank already open")
        seen = self._chat_id
        booth = next((l for l in self.get_nearby_locs() if self._op(l, re.compile(r"^bank$", re.I))), None)
        banker = next((n for n in self.get_nearby_npcs() if self._op(n, re.compile(r"^bank$", re.I))), None)
        ent = booth or banker
        if not ent: return result(False, "No nearby bank booth or banker")
        action = dict(type="loc", id=ent.id, x=ent.x, z=ent.z) if booth else dict(type="npc", index=ent.index)
        action["op"] = self._op(ent, "Bank")
        sent = self._send(**action)
        if not sent.success: return sent
        outcome = self._wait(lambda s: "bankmain" in s["interfaces"], (timeout or 10000) / 1000)
        if not outcome.success:
            state = self.get_state()
            if any(m.get("id", 0) > seen and "nothing interesting happens" in m.text.lower()
                   for m in state.gameMessages):
                return self._unsupported(f"Banking at {ent.name} ({ent.get('x')}, {ent.get('z')})")
        return outcome

    def close_interface(self, timeout=5000):
        sent = self._send(type="close")
        if not sent.success: return sent
        return self._wait(lambda s: not s.get("dialog") and "bankmain" not in s["interfaces"], (timeout or 5000) / 1000)
    close_bank = close_interface
    close_shop = close_interface
    dismiss_blocking_ui = close_interface

    def _bank_transfer(self, target, amount, withdraw=False):
        if not self.is_bank_open(): return result(False, "Bank is not open")
        amount = -1 if amount in (None, -1, "all") else int(amount)
        if amount == 0: return result(True, "No items requested")
        total = 0
        misses = 0
        for _ in range(60):
            source = self.get_bank_items() if withdraw else self.get_inventory()
            ent = self._find(source, target)
            if not ent: break
            remaining = amount - total if amount >= 0 else -1
            if remaining == 0: break
            quantity = "all" if remaining < 0 else 10 if remaining >= 10 else 5 if remaining >= 5 else 1
            op = ({1: 2, 5: 3, 10: 4, "all": 7} if withdraw else {1: 3, 5: 4, 10: 5, "all": 8})[quantity]
            before = sum(i.count for i in source if i.id == ent.id)
            r = self._send(type="button", component="bankmain:items" if withdraw else "bankside:items",
                           op=op, sub=ent.slot, obj=ent.id)
            if not r.success: return r
            key = "bank" if withdraw else "inventory"
            r = self._wait(lambda s: sum(i["count"] for i in s[key] if i["id"] == ent.id) < before, 5)
            if not r.success:
                # The bank tidies itself just after a deposit, so the slot can move under the click
                # ("bank withdrawal failed" now and then in script-problems.log): look it up again.
                misses += 1
                if misses >= 3: return result(False, r.message, amountTransferred=total)
                continue
            after = sum(i["count"] for i in self._raw()["state"][key] if i["id"] == ent.id)
            total += before - after
            if withdraw and amount < 0: break
        return result(total > 0 and (amount < 0 or total >= amount), f"Transferred {total} items", amountTransferred=total)

    def deposit_item(self, target, amount=-1): return self._bank_transfer(target, amount)
    def withdraw_item(self, target, amount=1, options=None):
        if (options or {}).get("asNote"): return self._unsupported("Bank note selection through the gateway")
        return self._bank_transfer(target, amount, True)

    def send_click_dialog(self, option=None):
        d = self.get_dialog()
        if not d.isOpen: return result(False, "No dialog is open")
        return self._send(type="choose", option=int(option or 0) + 1) if d.options else self._send(type="continue")
    def click_dialog_by_text(self, pattern):
        option = next((o.index for o in self.get_dialog().options if matches(pattern, o.text)), None)
        return self.send_click_dialog(option) if option is not None else result(False, f"No dialog option matches {pattern}")
    def send_click_component(self, component_id):
        # Numeric packed ids in LostCity refer to revision 225, never send them to rev 233.
        if not isinstance(component_id, str) or ":" not in component_id:
            return self._unsupported("LostCity interface component IDs on revision 233")
        return self._send(type="button", component=component_id)
    def talk_to(self, target):
        ent = self.find_nearby_npc(target)
        if not ent: return result(False, "NPC not visible")
        seen = self._chat_id
        r = self._send(type="npc", index=ent.index, op=self._op(ent, re.compile("talk", re.I)) or 1)
        if not r.success: return r
        outcome = self._wait(lambda s: bool(s.get("dialog")), 15)
        if not outcome.success:
            messages = self.get_state().gameMessages
            if any(m.get("id", 0) > seen and "nothing interesting happens" in m.text.lower() for m in messages):
                return self._unsupported(f"Dialogue for {ent.name}")
        return outcome

    def use_item_on_loc(self, item, loc, options=None):
        ent, target = self.find_inventory_item(item), self.find_nearby_loc(loc)
        if not ent or not target: return result(False, "Inventory item or location not visible")
        # Raw food on a range, ore on a furnace...: a "How many?" menu (skillmulti) opens first and has
        # to be answered (make all), or nothing happens (cooking "made nothing" until this).
        g = self._gateway
        before = sorted((i["name"], i.get("count", 1)) for i in g.inventory())
        seen = self._chat_id
        g.act(dict(type="use_on_loc", slot=ent.slot, id=target.id, x=target.x, z=target.z))
        end = time.monotonic() + (options or {}).get("timeout", 12000) / 1000
        chose = False
        while time.monotonic() < end:
            time.sleep(0.6)
            d = g.dialog()
            if d and d.get("interface") == "skillmulti" and not chose:
                g.choose(1)
                chose = True
                end = max(end, time.monotonic() + 10)
                continue
            if sorted((i["name"], i.get("count", 1)) for i in g.inventory()) != before:
                return result(True, "Effect confirmed")
        # Say what the game said (e.g. "I can't reach that!"): "No effect" alone left a cooking stop
        # in script-problems.log unexplained.
        said = [m.text for m in self.get_state().gameMessages if m.get("id", 0) > seen]
        return result(False, "No effect before timeout" + (f" (game: {said[-1]})" if said else ""), reason="timeout")
    def use_item_on_npc(self, item, npc, options=None):
        ent, target = self.find_inventory_item(item), self.find_nearby_npc(npc)
        if not ent or not target: return result(False, "Inventory item or NPC not visible")
        return self._effect(dict(type="use_on_npc", slot=ent.slot, index=target.index))

    def burn_logs(self, logs_target=None):
        box = self.find_inventory_item(re.compile(r"^tinderbox$", re.I))
        logs = self.find_inventory_item(logs_target or re.compile("logs", re.I))
        if not box or not logs: return result(False, "Need tinderbox and logs")
        xp = self.get_skill_xp("Firemaking")
        seen = self._chat_id
        r = self.send_use_item_on_item(box.slot, logs.slot)
        if not r.success: return r
        outcome = self._wait(lambda s: s["stats"]["firemaking"]["xp"] > xp, 20)
        if not outcome.success:
            messages = [m for m in self.get_state().gameMessages if m.get("id", 0) > seen]
            # A failed lighting attempt or blocked tile is not absent content.
            if any("nothing interesting happens" in m.text.lower() for m in messages):
                return self._unsupported("Firemaking item-on-item handling in the running server")
            if messages:
                return result(False, messages[-1].text, reason=outcome.reason)
        return outcome

    def clear_message_boxes(self):
        """Click through "click here to continue" boxes (a level-up message stops a make-all batch and
        stays open): the next use-item-on-item then opens the make menu, not behind the message."""
        for _ in range(4):
            d = self.get_dialog()
            if not d.isOpen or d.options:
                return
            self.send_click_dialog()
            time.sleep(0.8)

    def wait_inventory_settled(self, limit=72):
        """Until the backpack is unchanged for 3 looks in a row (3.6 s, longer than one 3-tick make).
        Two looks 1.2 s apart fell between two bows of a running batch, and the knife used again stopped
        it after every bow (user-reported: it fletched one longbow at a time)."""
        inv, same, end = None, 0, time.monotonic() + limit
        while time.monotonic() < end:
            now = [(i.slot, i.id) for i in self.get_inventory()]
            same = same + 1 if now == inv else 0
            if same >= 3: return
            inv = now
            time.sleep(1.2)

    def fletch_logs(self, product=None):
        # A "make all" from the last call may still be cutting: the logs it reads now can turn into
        # bows before the knife lands ("Knife on Longbow (u)" in missing content). Wait until the
        # inventory stops changing, then use the last logs, which are cut last.
        self.wait_inventory_settled()
        self.clear_message_boxes()
        knife = self.find_inventory_item(re.compile(r"^knife$", re.I))
        species = next((name for name in ("Oak", "Willow", "Maple", "Yew", "Magic")
                        if product and name.lower() in product.lower()), None)
        log_pattern = re.compile(r"^" + (species + r" logs" if species else "Logs") + r"$", re.I)
        pattern = log_pattern if product else re.compile("logs", re.I)
        logs = max((i for i in self.get_inventory() if matches(pattern, i.name)), key=lambda i: i.slot, default=None)
        if not knife or not logs: return result(False, "Need knife and logs")
        xp = self.get_skill_xp("Fletching")
        seen = self._chat_id
        # The make menu already open (left from the last try): answer it instead of opening another.
        if not self.get_dialog().options:
            r = self.send_use_item_on_item(knife.slot, logs.slot)
            if not r.success: return r
            r = self._wait(lambda s: bool(s.get("dialog")) or s["stats"]["fletching"]["xp"] > xp, 5)
        else:
            r = result(True, "Make menu already open")
        if not r.success:
            messages = [m for m in self.get_state().gameMessages if m.get("id", 0) > seen]
            if any("nothing interesting happens" in m.text.lower() for m in messages):
                return self._unsupported("Fletching item-on-item handling in the running server")
            if messages:
                return result(False, messages[-1].text, reason=r.reason)
            return r
        # The product list menu shows up as a dialog with options, like a chat choice. A level-up
        # message can be on top of it: click through it first (pura sat 3 minutes at the open menu
        # after reaching Fletching level 2).
        dialog = self.get_dialog()
        for _ in range(3):
            if dialog.options or not dialog.isOpen:
                break
            self.send_click_dialog()
            time.sleep(0.8)
            dialog = self.get_dialog()
        if dialog.options:
            normalize = lambda text: re.sub(r"[^a-z]", "", text.lower()).replace("unstrung", "").removesuffix("s")
            wanted = normalize(product or "")
            found = next((o.index for o in dialog.options if wanted in normalize(o.text)), None)
            if found is None: return result(False, f"No product {product}; options: {[o.text for o in dialog.options]}")
            self.send_click_dialog(found)
        return self._wait(lambda s: s["stats"]["fletching"]["xp"] > xp, 10)

    def smith_at_anvil(self, product="dagger", options=None):
        # Do not claim that the requested product was made: this server chooses it.
        return self._unsupported("Smithing product selection (server automatically chooses its recipe)")

    def attack(self, target, timeout=30000):
        npc = self.find_nearby_npc(target)
        if not npc: return result(False, "NPC not visible")
        op = self._op(npc, "Attack")
        if not op: return result(False, f"Cannot attack {npc.name}")
        self._combat_target = npc.index
        before = self._raw()["state"]
        seen = self._chat_id
        sent = self._send(type="npc", index=npc.index, op=op)
        if not sent.success: return sent
        # Behind a closed door ("I can't reach that!"): say so at once, the caller opens it or picks another.
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if any(m.get("id", 0) > seen and "can't reach" in m.text.lower() for m in self.get_state().gameMessages):
                return result(False, "I can't reach that!", reason="unreachable")
            if self._raw()["state"]["player"].get("interacting"):
                break
            time.sleep(0.3)
        combat_skills = ("attack", "strength", "defence", "ranged", "magic", "hitpoints")
        gone = {"yes": False}

        def started(s):
            # Started = fighting it (a tick later), not its first damaging hit: at low levels most hits
            # are 0s and that wait idled for seconds (user-reported: scripts slow to fight).
            if ((s["tick"] > before["tick"] and s["player"].get("interacting"))
                    or any(n["index"] == npc.index and n["hp"] < npc.hp for n in s["npcs"])
                    or any(s["stats"].get(k, {}).get("xp", 0) > before["stats"].get(k, {}).get("xp", 0)
                           for k in combat_skills)):
                return True
            # User-reported 2026-11-09 (AIO Fighter slow to move on): the monster died or left before we got
            # to it (someone else's kill) and this waited the whole 30 s. Give up at once instead.
            target = next((n for n in s["npcs"] if n["index"] == npc.index), None)
            if target is None or (target.get("hp") or 0) <= 0:
                gone["yes"] = True
                return True
            return False

        outcome = self._wait(started, (timeout or 30000) / 1000)
        if gone["yes"]:
            return result(False, "The target died or left first", reason="gone")
        return outcome

    # Shops go through the gateway now (they were placeholders that always failed: AIO couldn't buy
    # its first net, axe or pickaxe).
    def open_shop(self, target=None):
        try:
            return result(bool(self._gateway.open_shop(target)), "")
        except Exception as e:
            return result(False, str(e))

    def buy_from_shop(self, target, amount=1):
        try:
            self._gateway.buy(target, amount)
            return result(True, "")
        except Exception as e:
            return result(False, str(e))
    def pickpocket_npc(self, target): return self._unsupported("Thieving")
    def craft_leather(self, product=None): return self._unsupported("Crafting")
    def craft_jewelry(self, options=None): return self._unsupported("Jewellery crafting")
    def enchant_item(self, target, level, options=None): return self._unsupported("Enchanting")
    def string_amulet(self, target=None, options=None): return self._unsupported("Amulet stringing")
    def cast_spell(self, target, spell_component, timeout=None): return self._unsupported("Spell targeting through the gateway")
    def send_set_combat_style(self, style): return self._unsupported("Combat style selection through the gateway")
    def send_set_tab(self, tab_index): return result(True, "Server-side characters have no client tabs")
    def find_path(self, dest_x, dest_z, max_waypoints=None):
        raise FeatureUnavailable("Global pathfinding isn't on this server yet; use walk_to's bounded local waypoints")
