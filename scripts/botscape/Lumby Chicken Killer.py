"""Lumby Chicken Killer: kills chickens north of Lumbridge, picks up their feathers and bones, buries the
bones for Prayer XP and, if you want, cooks the raw chicken and banks it. A Bot Scape original:
it comes with the game and is kept up to date (copy it into your scripts folder to make your own).

Press Run on its card in the launcher or in the client's Bot Scape panel, or run it yourself:

    python "Lumby Chicken Killer.py" <your character>               with the options ticked in the launcher
    python "Lumby Chicken Killer.py" <your character> --no-collect  leave the raw chicken on the ground
    python "Lumby Chicken Killer.py" <your character> --no-cook     don't cook (bank the raw chicken)
    python "Lumby Chicken Killer.py" <your character> --no-bank     don't bank chicken (drop it)
    python "Lumby Chicken Killer.py" <your character> --kills 50    stop after 50 chickens
    python "Lumby Chicken Killer.py" <your character> --attack_goal 40 --strength_goal 99

What it uses from the SDK (sdk/botscape.py): bot.run_on + bot.travel (runs anywhere), bot.find_npc / bot.attack,
bot.find_ground_item / bot.take, bot.item_option (Bury, Eat, Drop), bot.find_loc / bot.use_on_loc
(raw chicken on the range), bot.choose (the cooking menu), bot.open_bank / bot.deposit, and
bot.wait_until / bot.wait_ticks / bot.log.
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
from botscape import GatewayError, run, script_options  # noqa: E402

# Options: shown as checkboxes on this script's card in the launcher (your choices are saved).
# Running it yourself: --no-collect / --no-cook / --no-bank turn one off.
ICON = "botscape"   # the Bot Scape emblem on its card: a Bot Scape original script

OPTIONS = {
    "collect": ("Pick up raw chicken", True),
    "cook": ("Cook the chicken in Lumbridge castle's kitchen (does Cook's Assistant first)", True),
    "bank": ("Bank the chicken (off: drop it)", True),
    "kills": ("Stop after this many chickens (0 = keep going)", 0),
    "attack_goal": ("Attack goal (0 = don't train Attack)", 99),
    "strength_goal": ("Strength goal (0 = don't train Strength)", 99),
    "defence_goal": ("Defence goal (0 = don't train Defence)", 99),
}

COOP = (3233, 3295, 0)      # the chicken coop north of Lumbridge, east of the farm (ground floor)
KITCHEN = (3209, 3214, 0)   # Lumbridge castle kitchen (ground floor), its range is here
BANK = (3208, 3220, 2)      # Lumbridge castle bank, top floor
FOOD = ["Cooked chicken", "Shrimps", "Bread", "Trout", "Salmon", "Lobster"]


def main(bot):
    options = script_options(OPTIONS)
    collect = options["collect"]
    cook = collect and options["cook"]
    # The castle kitchen's range (the Cook-o-matic) is only for those who finished Cook's Assistant:
    # with cooking on, the script does the quest first.
    if cook:
        try:
            cook = cooks_assistant(bot)
        except Exception as e:             # no egg, no coins...: just don't cook
            bot.log(f"Couldn't do Cook's Assistant ({e}); the raw chicken gets banked instead")
            cook = False
    bank_food = options["bank"]
    goal = options["kills"] or None
    goals = {skill: options[f"{skill}_goal"] for skill in ("attack", "strength", "defence")}
    goals = {skill: level for skill, level in goals.items() if level > 0}
    wanted = ["Feather", "Bones"] + (["Raw chicken"] if collect else [])
    loot_pattern = re.compile("^(" + "|".join(wanted) + ")$")
    bot.log(f"Chicken script: collect={'on' if collect else 'off'}, cook={'on' if cook else 'off'}, "
            f"bank chicken={'on' if bank_food else 'off'}"
            + (", goals: " + ", ".join(f"{skill.title()} {level}" for skill, level in goals.items()) if goals else "")
            + (f", {goal} kills" if goal else ""))

    # User-requested: fight with a weapon when there is one (before banking the backpack, which would
    # put a carried sword away too).
    equip_weapon(bot)
    # A backpack full of other things (the starting items) leaves no room for loot: bank it first.
    if len(bot.inventory()) > 8:
        bank(bot, bank_food)

    kills = 0
    while goal is None or kills < goal:
        if goals and all(bot.level(skill) >= level for skill, level in goals.items()):
            bot.log("Goals reached: " + ", ".join(f"{skill.title()} {bot.level(skill)}" for skill in goals))
            break
        train_toward(bot, goals)
        if bot.inv_full():
            if cook and bot.inv_count("Raw chicken"):
                cook_chicken(bot)
            bank(bot, bank_food)
            continue
        if not near(bot, COOP, 12):
            bot.log("Walking to the chicken coop...")
            go(bot, *COOP)
            continue

        eat_if_hurt(bot)
        if bot.player["interacting"]:    # still fighting: don't click another chicken
            bot.wait_ticks(1)
            continue
        chicken = pick_chicken(bot)
        if chicken is None:
            tidy_up(bot, loot_pattern)     # no chicken free: pick up our own feathers still lying around
            bot.wait_ticks(3)              # they respawn quickly
            continue

        bot.new_messages()                 # only what the game says from now on counts
        bot.attack(chicken)
        if cant_reach(bot):
            # Behind the fence or a shut gate: walk to it with the server's route planner (it opens
            # the coop's gates on the way) and try once more, else leave it alone for a minute.
            reached = False
            if bot.travel(chicken["x"], chicken["z"], tolerance=1, timeout=30):
                bot.new_messages()
                bot.attack(chicken)
                reached = not cant_reach(bot)
            if not reached:
                bot.log(f"Can't reach the chicken at ({chicken['x']}, {chicken['z']}): skipping it for a minute")
                UNREACHABLE[chicken["index"]] = time.time() + UNREACHABLE_SECONDS
                continue
        # Fight until that chicken is gone (dead) or 30 seconds pass. Where it is gets followed: it wanders
        # during the fight, and looting where it stood at the first click left the feathers of every chicken
        # that died a few tiles away (user-reported: feather piles all over the pen).
        last = {"at": (chicken["x"], chicken["z"])}
        def gone():
            alive = next((n for n in bot.state()["npcs"] if n["index"] == chicken["index"]), None)
            if alive:
                last["at"] = (alive["x"], alive["z"])
            return alive is None
        dead = bot.wait_until(gone, timeout=30)
        if dead:
            kills += 1
            bot.log(f"Killed chicken #{kills}")
            loot(bot, loot_pattern, at=last["at"])
            bury_bones(bot)

    # Done: cook and bank what we still carry.
    if cook and bot.inv_count("Raw chicken"):
        cook_chicken(bot)
    bank(bot, bank_food)
    bot.log(f"Done: {kills} chickens killed.")


# The combat tab's style buttons: accurate trains Attack, aggressive Strength, defensive Defence
# (slot 3 for every weapon, unarmed too).
STYLE_BUTTON = {"attack": "combat_interface:0", "strength": "combat_interface:1", "defence": "combat_interface:3"}
TRAINING = {"skill": None}


def train_toward(bot, goals):
    """Fights in the style of the skill furthest below its goal (lowest level first)."""
    behind = [skill for skill, level in goals.items() if bot.level(skill) < level]
    if not behind:
        return
    skill = min(behind, key=bot.level)
    if TRAINING["skill"] != skill:
        bot.click(STYLE_BUTTON[skill])
        bot.wait_ticks(1)
        TRAINING["skill"] = skill
        bot.log(f"Training {skill.title()} ({bot.level(skill)} of {goals[skill]})")


def pick_chicken(bot):
    """The chicken to attack next. A hurt chicken right next to us is the one attacking us: fight
    back first ("I'm already under attack" otherwise). Chickens someone else is fighting are left
    alone: hurt ones that aren't next to us, and ones standing next to another player."""
    state = bot.state()
    me = bot.name.lower()
    others = [p for p in state.get("players", []) if (p.get("name") or "").lower() != me]
    # Dead ones (0 hitpoints, in their death animation) aren't targets: attacking one leaves you
    # swinging at nothing once it vanishes to respawn.
    chickens = [n for n in state["npcs"] if n["name"] == "Chicken" and (n.get("hp") or 0) > 0]

    def hurt(n):
        return (n.get("hp") or 0) < (n.get("maxHp") or 0)

    def next_to_player(n):
        return any(abs(p["x"] - n["x"]) <= 1 and abs(p["z"] - n["z"]) <= 1 for p in others)

    attacker = next((n for n in chickens if n.get("fightingMe") or (n["distance"] <= 1 and hurt(n))), None)
    if attacker:
        return attacker
    # User-requested: only chickens it can get to. Ones it couldn't reach lately (behind a fence or a
    # shut gate) are skipped for a while, and so are strays far from the coop. Closest first.
    now = time.time()
    # User-reported (2026-11-11: bots stood idle among free chickens): the server says which ones fight someone
    # else; "next to another player" left none free in a crowded coop (the old rule stays for older servers).
    def taken(n):
        return n["fightingOther"] if "fightingOther" in n else hurt(n) or next_to_player(n)
    free = [n for n in chickens if not taken(n)
            and UNREACHABLE.get(n["index"], 0) < now
            and abs(n["x"] - COOP[0]) <= COOP_RANGE and abs(n["z"] - COOP[1]) <= COOP_RANGE]
    return min(free, key=lambda n: n["distance"]) if free else None


# Chickens it couldn't reach: npc index -> until when they're skipped.
UNREACHABLE = {}
UNREACHABLE_SECONDS = 60
COOP_RANGE = 12   # chickens further than this from the coop are strays somewhere else


def cant_reach(bot, ticks=4):
    """True if the game said "I can't reach that!" within the next few ticks."""
    for _ in range(ticks):
        bot.wait_ticks(1)
        if any("can't reach" in m.lower() for m in bot.new_messages()):
            return True
    return False


def go(bot, *spot):
    """Walk somewhere, running whenever there's run energy."""
    bot.run_on()
    bot.travel(*spot)


def near(bot, spot, distance):
    x, z, level = bot.position
    return level == 0 and abs(x - spot[0]) <= distance and abs(z - spot[1]) <= distance


# Piles the bot couldn't pick up (across the coop's fence: user-reported, skkke stood outside trying to take
# "Feather (15)" forever) -> when it may try again.
SKIP_PILES = {}
SKIP_SECONDS = 300


def skipped(g):
    return SKIP_PILES.get((g["name"], g["x"], g["z"]), 0) > time.time()


def take_or_skip(bot, item, here):
    """Take a pile; when it's still there afterwards (or the game said it can't reach it), leave it for 5 minutes."""
    bot.new_messages()
    try:
        bot.take(item)
    except GatewayError as e:          # someone else took it, or it vanished
        bot.log(f"Couldn't take {item['name']}: {e}")
        return False
    # Taken when that pile is gone (or got smaller): walking to it can take a few ticks.
    key = (item["name"], item["x"], item["z"], item.get("count", 1))
    taken = bot.wait_until(lambda: all((g["name"], g["x"], g["z"], g.get("count", 1)) != key for g in here()), timeout=6)
    if not taken or any("can't reach" in m.lower() for m in bot.new_messages()):
        SKIP_PILES[(item["name"], item["x"], item["z"])] = time.time() + SKIP_SECONDS
        bot.log(f"Can't get to the {item['name'].lower()} at ({item['x']}, {item['z']}): leaving it for 5 minutes")
        return False
    return True


def loot(bot, pattern, at=None):
    """Pick up what the chicken dropped. User-reported: kills were often left unlooted. The drop shows up a
    tick or two after the chicken vanishes, and looting looked right away and gave up when nothing was there
    yet; now it waits for the drop where the chicken died, then takes each item and checks it's gone."""
    def here():
        wanted = pattern if hasattr(pattern, "search") else re.compile(pattern, re.I)   # a compiled pattern takes no flags
        # User-requested: only our own loot (the server marks drops "mine"; other players' piles stay theirs).
        items = [g for g in (bot.state().get("groundItems") or []) if wanted.search(g.get("name", ""))
                 and g.get("mine", True) and not skipped(g)]
        if at is not None:
            items = [g for g in items if abs(g["x"] - at[0]) <= 3 and abs(g["z"] - at[1]) <= 3]
        return items
    bot.wait_until(lambda: here(), timeout=4)
    for _ in range(6):
        items = here()
        if not items or bot.inv_full():
            return
        if not take_or_skip(bot, items[0], here):
            return


def tidy_up(bot, pattern, radius=6, most=3):
    """Our own feathers and bones still lying near the bot (kills it lost track of): a few piles, nearest first,
    while there's no chicken to attack. Other players' loot is left alone (user-requested)."""
    wanted = pattern if hasattr(pattern, "search") else re.compile(pattern, re.I)
    me = bot.player
    for _ in range(most):
        if bot.inv_full():
            return
        piles = [g for g in (bot.state().get("groundItems") or []) if wanted.search(g.get("name", ""))
                 and g.get("mine") and not skipped(g) and max(abs(g["x"] - me["x"]), abs(g["z"] - me["z"])) <= radius]
        if not piles:
            return
        pile = min(piles, key=lambda g: max(abs(g["x"] - me["x"]), abs(g["z"] - me["z"])))
        if not take_or_skip(bot, pile, lambda: bot.state().get("groundItems") or []):
            return


def bury_bones(bot):
    for bones in [i for i in bot.inventory() if i["name"] == "Bones"]:
        bot.item_option(bones, "Bury")
        bot.wait_ticks(2)


def eat_if_hurt(bot):
    hp = bot.stats()["hitpoints"]
    if hp["level"] >= hp["base"] // 2:
        return
    food = next((i for i in bot.inventory() if i["name"] in FOOD), None)
    if food:
        bot.log("Eating")
        bot.item_option(food, "Eat")
        bot.wait_ticks(2)


def cook_chicken(bot):
    """Cook every raw chicken on the range in Lumbridge castle's kitchen."""
    bot.log(f"Cooking {bot.inv_count('Raw chicken')} raw chicken in the castle kitchen")
    go(bot, *KITCHEN)
    cooking_range = bot.find_loc(re.compile(r"^(Cooking range|Range)$", re.I))
    if cooking_range is None:
        bot.log("Couldn't find the range; banking the raw chicken instead")
        return
    for _ in range(3):                     # a level-up message can interrupt "cook all"
        raw = next((i for i in bot.inventory() if i["name"] == "Raw chicken"), None)
        if raw is None:
            break
        bot.use_on_loc(raw, cooking_range)
        # The "How many do you wish to cook?" menu: cook all of them.
        if bot.wait_until(lambda: (bot.dialog() or {}).get("options"), timeout=10):
            bot.choose(1)
        before = bot.inv_count("Raw chicken")
        bot.wait_until(lambda: bot.inv_count("Raw chicken") == 0, timeout=3 * before + 10)
    # Burnt chicken is no good to anyone.
    for burnt in [i for i in bot.inventory() if i["name"] == "Burnt chicken"]:
        bot.item_option(burnt, "Drop")
        bot.wait_ticks(1)
    bot.log(f"Cooked chicken: {bot.inv_count('Cooked chicken')}")


def bank(bot, bank_food):
    """Bank the whole backpack at Lumbridge castle: the loot and anything else carried (starting
    gear, tools, runes...), so every slot is free for feathers, bones and chicken. User-reported:
    with the starting items in the backpack it filled up and never banked them."""
    if not bank_food:
        for food in [i for i in bot.inventory() if i["name"] in ("Raw chicken", "Cooked chicken")]:
            bot.item_option(food, "Drop")
            bot.wait_ticks(1)
    if not bot.inventory():
        return
    bot.log("Banking the backpack at Lumbridge castle: " + ", ".join(sorted({i["name"] for i in bot.inventory()})))
    equip_weapon(bot)
    go(bot, *BANK)
    bot.open_bank()
    bot.deposit_inventory()
    bot.wait_ticks(1)
    # A better weapon waiting in the bank (the group's shared bank) comes out and gets wielded.
    better = best_weapon(bot, bot.bank(), worn_weapon(bot))
    if better:
        try:
            bot.withdraw(re.compile(f"^{re.escape(better['name'])}$"), 1)
        except GatewayError:
            better = None
    bot.close_interface()
    if better:
        equip_weapon(bot)


# --- weapon -------------------------------------------------------------------------------------
# Melee weapons by metal, with the Attack level each needs (OSRS).
METALS = [("Dragon", 60), ("Rune", 40), ("Adamant", 30), ("Mithril", 20), ("Black", 10), ("Steel", 5),
          ("Iron", 1), ("Bronze", 1)]
MELEE = re.compile(r"^(Bronze|Iron|Steel|Black|Mithril|Adamant|Rune|Dragon) "
                   r"(dagger|sword|scimitar|longsword|mace|battleaxe|warhammer|spear|hasta|2h sword|claws)$")


def weapon_rank(bot, name):
    """How good a melee weapon is (higher is better), or None if it isn't one simba can wield."""
    m = MELEE.match(name or "")
    if not m:
        return None
    for rank, (metal, level) in enumerate(reversed(METALS)):
        if metal == m.group(1):
            return rank if bot.level("attack") >= level else None
    return None


def worn_weapon(bot):
    return next((i for i in bot.state().get("equipment") or [] if i and i.get("slot") == 3), None)


def best_weapon(bot, items, current):
    """The best wieldable melee weapon in `items` that beats `current` (the worn one), or None."""
    have = weapon_rank(bot, current["name"]) if current else None
    if current and have is None:
        return None          # wielding something else (a staff, a bow): leave it
    ranked = [(weapon_rank(bot, i["name"]), i) for i in items if i]
    ranked = [(r, i) for r, i in ranked if r is not None and (have is None or r > have)]
    return max(ranked, key=lambda ri: ri[0])[1] if ranked else None


def equip_weapon(bot):
    """Wield the best melee weapon carried, if it beats what's worn (or nothing is)."""
    item = best_weapon(bot, bot.inventory(), worn_weapon(bot))
    if item is None:
        return
    bot.log(f"Wielding {item['name']}")
    try:
        bot.item_option(item, "Wield")
    except GatewayError as e:
        bot.log(f"Couldn't wield {item['name']}: {e}")
        return
    bot.wait_ticks(2)


# --- Cook's Assistant ------------------------------------------------------------------------------
# The castle kitchen's range is only for those who helped the Cook, so with cooking on the script
# does the quest first: the Cook wants an egg, a bucket of milk and a pot of flour. Group ironman:
# all of it gathered around Lumbridge, never bought at the Grand Exchange.

SUPPLIES = ["Egg", "Bucket of milk", "Pot of flour"]
TOWN = (3222, 3218, 0)      # Lumbridge's courtyard: men and women to pickpocket
STORE = (3212, 3246, 0)     # Lumbridge general store (sells buckets)
COWS = (3253, 3270, 0)      # the dairy cows east of the river
WHEAT = (3158, 3300, 0)     # the wheat field by the Mill Lane Mill
MILL_TOP = (3166, 3306, 2)  # the mill's top floor: hopper and its controls
MILL_BIN = (3166, 3305, 0)  # the flour bin on the ground floor
BUCKET_COINS = 2       # a bucket costs 2 coins at the general store; one pickpocket gives 3


def cooks_assistant(bot):
    """Does Cook's Assistant if it isn't done yet. True when it is done."""
    if quest_done(bot):
        return True
    bot.log("Cook's Assistant first: the castle kitchen's range needs it")
    get_supplies(bot)
    # The first talk starts the quest; the ingredients are handed over in the next one (as in
    # OSRS). Keep talking until the quest is really complete.
    for attempt in range(4):
        talk_to_cook(bot)
        bot.wait_ticks(2)
        if quest_done(bot):
            break
        status = (bot.quest("Cook's Assistant") or {}).get("status")
        bot.log(f"Cook's Assistant: {status}, talking to the Cook again")
    if quest_done(bot):
        bot.log("Cook's Assistant complete!")
        return True
    bot.log("Cook's Assistant isn't finished; cooking stays off")
    return False


def quest_done(bot):
    return (bot.quest("Cook's Assistant") or {}).get("status") == "done"


def carried(bot, name):
    return any(i["name"] == name and not i.get("noted") for i in bot.inventory())


def missing(bot):
    return [name for name in SUPPLIES if not carried(bot, name)]


def get_supplies(bot):
    """Group ironman: everything gathered, nothing from the Grand Exchange. An egg from the chicken
    coop, the pot from the castle kitchen's table, a bucket from Lumbridge's general store (coins
    pickpocketed from men and women), milk from a dairy cow, flour milled from wheat at the mill."""
    if not missing(bot):
        bot.log("All of Cook's Assistant's ingredients are in the backpack")
        return
    bot.log("Cook's Assistant needs " + ", ".join(missing(bot)))
    # The bank only when the backpack is too full to gather into (user-requested): put away
    # everything else (keeping the ingredients and the tools to make them), and while there take
    # out whatever of them is already banked.
    free = 28 - len(bot.inventory())
    if free >= SLOTS_NEEDED:
        return gather(bot)
    bot.log(f"Backpack nearly full ({free} free): banking first")
    go(bot, *BANK)
    bot.open_bank()
    for item in list(bot.inventory()):
        if item["name"] not in KEEP:
            bot.deposit(item, "all")
            bot.wait_ticks(1)
    banked = {b["name"] for b in bot.bank()}
    for name in SUPPLIES + ["Pot", "Bucket", "Grain"]:
        if name in banked and not carried(bot, name) and not made_from(bot, name):
            bot.withdraw(name, 1)
    if "Coins" in banked:
        bot.withdraw("Coins", "all")
    bot.close_interface()
    gather(bot)


def gather(bot):
    """The missing ingredients, in one loop around Lumbridge."""
    # One loop around Lumbridge, shortest first: the pot (castle kitchen, same building as the bank),
    # coins in the courtyard, the bucket at the general store just north, milk at the cows north-
    # east, the egg in the coop next to them, then the wheat field and the mill north-west; the
    # Cook is the last stop, back at the castle.
    if not carried(bot, "Pot of flour") and not carried(bot, "Pot"):
        take_pot(bot)
    if not carried(bot, "Bucket of milk"):
        if not carried(bot, "Bucket"):
            buy_bucket(bot)
        milk_cow(bot)
    if not carried(bot, "Egg"):
        get_egg(bot)
    if not carried(bot, "Pot of flour"):
        make_flour(bot)
    if missing(bot):
        raise RuntimeError("Couldn't get " + ", ".join(missing(bot)))


# Free backpack slots gathering needs (pot, bucket, grain, egg and coins); fewer: bank first.
SLOTS_NEEDED = 5

# Kept in the backpack while gathering: the ingredients and what they're made with.
KEEP = {"Egg", "Bucket of milk", "Pot of flour", "Pot", "Bucket", "Grain", "Coins", "Coin pouch"}


def made_from(bot, name):
    """Is `name` (a tool) not needed because what it makes is already carried?"""
    return {"Pot": "Pot of flour", "Bucket": "Bucket of milk", "Grain": "Pot of flour"}.get(name) in \
        {i["name"] for i in bot.inventory()}


def wait_for_item(bot, name, ticks=12):
    return bot.wait_until(lambda: carried(bot, name), timeout=ticks * 0.6 + 2)


def get_egg(bot):
    bot.log("Picking up an egg in the chicken coop")
    go(bot, *COOP)
    if not bot.wait_until(lambda: bot.find_ground_item("Egg") is not None, timeout=120):
        raise RuntimeError("No egg appeared in the chicken coop.")
    bot.take(bot.find_ground_item("Egg"))
    wait_for_item(bot, "Egg")


def take_pot(bot):
    bot.log("Taking the pot from the castle kitchen's table")
    go(bot, *KITCHEN)
    if not bot.wait_until(lambda: bot.find_ground_item("Pot") is not None, timeout=120):
        raise RuntimeError("No pot on the kitchen table.")
    bot.take(bot.find_ground_item("Pot"))
    wait_for_item(bot, "Pot")


def coins(bot):
    return sum(i.get("count", 1) for i in bot.inventory() if i["name"] == "Coins")


def pickpocket_coins(bot, wanted):
    """Pickpocket men and women in Lumbridge until we have `wanted` coins (they hit back when
    caught: that's just a stun, and we eat if hurt)."""
    bot.log(f"Pickpocketing men and women for {wanted} coins")
    go(bot, *TOWN)
    for _ in range(60):
        open_pouches(bot)
        if coins(bot) >= wanted:
            return
        eat_if_hurt(bot)
        mark = next((n for n in bot.state()["npcs"] if n["name"] in ("Man", "Woman") and n["distance"] <= 12), None)
        if mark is None:
            bot.wait_ticks(3)
            continue
        bot.interact_npc(mark, "Pickpocket")
        bot.wait_ticks(4)                  # the attempt, or the stun when caught
    open_pouches(bot)
    if coins(bot) < wanted:
        raise RuntimeError("Couldn't pickpocket enough coins.")


def open_pouches(bot):
    """Pickpocketing gives coin pouches (as in OSRS): open them for the coins."""
    pouch = next((i for i in bot.inventory() if i["name"] == "Coin pouch"), None)
    if pouch is None:
        return
    for option in ("Open-all", "Open"):
        try:
            bot.item_option(pouch, option)
            bot.wait_ticks(2)
            return
        except Exception:
            continue


def buy_bucket(bot):
    if coins(bot) < BUCKET_COINS:
        pickpocket_coins(bot, BUCKET_COINS)
    bot.log("Buying a bucket at Lumbridge's general store")
    go(bot, *STORE)
    bot.open_shop("Shop keeper")
    bot.buy("Bucket", 1)
    bot.close_interface()
    if not wait_for_item(bot, "Bucket"):
        raise RuntimeError("Couldn't buy a bucket.")


def milk_cow(bot):
    bot.log("Milking a dairy cow")
    go(bot, *COWS)
    cow = bot.find_loc("Dairy cow")
    if cow is None:
        raise RuntimeError("No dairy cow found.")
    # The cows stand in a fenced pen: walk right up to one (through its gate) first.
    bot.run_on()
    bot.travel(cow["x"], cow["z"], 0, tolerance=1)
    cow = bot.find_loc("Dairy cow")
    bot.interact_loc(cow, "Milk")
    if not wait_for_item(bot, "Bucket of milk", 20):
        raise RuntimeError("Couldn't milk the cow.")


def make_flour(bot):
    """Grain from the wheat field, into the windmill's hopper (top floor), the controls, then the
    flour bin on the ground floor fills the pot."""
    if not carried(bot, "Grain"):
        bot.log("Picking wheat")
        go(bot, *WHEAT)
        wheat = bot.find_loc("Wheat")
        if wheat is None:
            raise RuntimeError("No wheat in the field.")
        bot.interact_loc(wheat, "Pick")
        if not wait_for_item(bot, "Grain", 15):
            raise RuntimeError("Couldn't pick wheat.")
    bot.log("Milling the grain into flour")
    go(bot, *MILL_TOP)
    grain = next(i for i in bot.inventory() if i["name"] == "Grain")
    bot.use_on_loc(grain, bot.find_loc("Hopper"))
    bot.wait_until(lambda: not carried(bot, "Grain"), timeout=15)
    bot.interact_loc(bot.find_loc("Hopper controls"), "Operate")
    bot.wait_ticks(5)
    # The bin fills an empty pot (AIO bots' problems log 2026-11-10: "The flour bin gave no flour." with no pot:
    # the kitchen's pot hadn't respawned when the loop started).
    if not carried(bot, "Pot"):
        take_pot(bot)
        if not carried(bot, "Pot"):
            raise RuntimeError("No empty pot for the flour (the castle kitchen's pot didn't respawn).")
    go(bot, *MILL_BIN)
    bot.interact_loc(bot.find_loc("Flour bin"), "Empty")
    if not wait_for_item(bot, "Pot of flour", 15):
        raise RuntimeError("The flour bin gave no flour.")


def talk_to_cook(bot):
    go(bot, *KITCHEN)
    cook = bot.find_npc("Cook")
    if cook is None:
        raise RuntimeError("The Cook isn't in the castle kitchen.")
    bot.interact_npc(cook, "Talk-to")
    bot.wait_until(lambda: bot.dialog(), timeout=15)
    # Click through; when there's a choice, pick the one that helps the Cook.
    prefer = ["what's wrong", "happy to help", "i've got", "i have", "ingredients", "yes"]
    quiet = 0
    for _ in range(60):
        dialog = bot.dialog()
        if not dialog:
            quiet += 1
            if quiet > 2:
                break
            bot.wait_ticks(1)
            continue
        quiet = 0
        options = dialog.get("options") or []
        if options:
            pick = next((i + 1 for want in prefer for i, o in enumerate(options) if want in o.lower()), 1)
            bot.choose(pick)
        else:
            bot.continue_dialog()
        bot.wait_ticks(1)
    bot.close_interface()


run(main)
