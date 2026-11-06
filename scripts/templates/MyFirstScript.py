"""My first script: kills chickens north of Lumbridge, picks up their feathers and bones, buries the
bones for Prayer XP and, if you want, cooks the raw chicken and banks it. Edit me!

Your own scripts live in this folder (bots/<your name>/). Every .py file here shows up under
"My scripts" in the launcher and in the client's Bot Scape panel; press Run there, or run it yourself:

    python MyFirstScript.py <your character>               with the options ticked in the launcher
    python MyFirstScript.py <your character> --no-collect  leave the raw chicken on the ground
    python MyFirstScript.py <your character> --no-cook     don't cook (bank the raw chicken)
    python MyFirstScript.py <your character> --no-bank     don't bank chicken (drop it)
    python MyFirstScript.py <your character> --kills 50    stop after 50 chickens
    python MyFirstScript.py <your character> --attack_goal 40 --strength_goal 99

What it uses from the SDK (sdk/botscape.py): bot.run_on + bot.travel (runs anywhere), bot.find_npc / bot.attack,
bot.find_ground_item / bot.take, bot.item_option (Bury, Eat, Drop), bot.find_loc / bot.use_on_loc
(raw chicken on the range), bot.choose (the cooking menu), bot.open_bank / bot.deposit, and
bot.wait_until / bot.wait_ticks / bot.log.
"""

import re
import sys
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
            bot.wait_ticks(3)              # they respawn quickly
            continue

        bot.attack(chicken)
        # Fight until that chicken is gone (dead) or 30 seconds pass.
        dead = bot.wait_until(lambda: all(n["index"] != chicken["index"] for n in bot.state()["npcs"]), timeout=30)
        if dead:
            kills += 1
            bot.log(f"Killed chicken #{kills}")
            loot(bot, loot_pattern)
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

    attacker = next((n for n in chickens if n["distance"] <= 1 and hurt(n)), None)
    if attacker:
        return attacker
    free = [n for n in chickens if not hurt(n) and not next_to_player(n)]
    return free[0] if free else None


def go(bot, *spot):
    """Walk somewhere, running whenever there's run energy."""
    bot.run_on()
    bot.travel(*spot)


def near(bot, spot, distance):
    x, z, level = bot.position
    return level == 0 and abs(x - spot[0]) <= distance and abs(z - spot[1]) <= distance


def loot(bot, pattern):
    """Pick up what the chicken dropped (the nearest few items of the kinds we want)."""
    for _ in range(4):
        item = bot.find_ground_item(pattern)
        if item is None or item.get("distance", 99) > 4 or bot.inv_full():
            return
        try:
            bot.take(item)
        except GatewayError as e:          # someone else took it, or it vanished
            bot.log(f"Couldn't take {item['name']}: {e}")
            return
        bot.wait_ticks(2)


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
    keep = {"Feather"} | ({"Raw chicken", "Cooked chicken"} if bank_food else set())
    if not bank_food:
        for food in [i for i in bot.inventory() if i["name"] in ("Raw chicken", "Cooked chicken")]:
            bot.item_option(food, "Drop")
            bot.wait_ticks(1)
    if not any(i["name"] in keep for i in bot.inventory()):
        return
    bot.log("Banking at Lumbridge castle: " + ", ".join(sorted(keep)))
    go(bot, *BANK)
    bot.open_bank()
    for item in [i for i in bot.inventory() if i["name"] in keep]:
        bot.deposit(item, "all")
    bot.close_interface()


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
