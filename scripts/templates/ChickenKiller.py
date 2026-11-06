"""Chicken Killer: a complete example bot that shows how a Bot Scape script works.

It walks to the chicken coop by Lumbridge's farm, kills chickens, picks up their feathers, buries
the bones for Prayer XP, eats when it's hurt, and banks the feathers at Lumbridge castle when the
backpack fills up. Copy it, rename it and change it into your own bot.

Every .py file in your scripts folder (bots/<your name>/) shows up in the launcher under
"My scripts"; press Run there, or run it yourself:

    python ChickenKiller.py <your character>             kill chickens until you stop it
    python ChickenKiller.py <your character> --kills 50  stop after 50 chickens

What it uses from the SDK (sdk/botscape.py): `bot.travel` (walks anywhere in the world), `bot.find_npc`
/ `bot.attack` (monsters), `bot.find_ground_item` / `bot.take` (loot), `bot.inventory` /
`bot.item_option` (backpack items: Bury, Eat), `bot.stats` (hitpoints), `bot.open_bank` /
`bot.deposit` (banking), `bot.wait_until` / `bot.wait_ticks` (waiting for the game) and `bot.log`
(what you see in the launcher's Output tab).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
from botscape import GatewayError, run  # noqa: E402

ICON = "botscape"   # the Bot Scape emblem on its card: a Bot Scape original script

COOP = (3233, 3295, 0)       # the chicken coop north of Lumbridge (east of the farm), ground floor
BANK = (3208, 3220, 2)       # Lumbridge castle bank, top floor
LOOT = re.compile(r"^(Feather|Bones|Raw chicken)$")   # names can be plain text or a regex
KEEP = {"Feather"}           # banked; bones are buried, raw chicken dropped
FOOD = ["Cooked chicken", "Shrimps", "Bread", "Trout", "Salmon", "Lobster"]


def main(bot):
    args = sys.argv[2:]
    goal = int(args[args.index("--kills") + 1]) if "--kills" in args else None
    kills = 0
    bot.log(f"Chicken Killer starting{f' ({goal} kills)' if goal else ''}.")

    while goal is None or kills < goal:
        if bot.inv_full():
            bank(bot)
            continue
        if not near(bot, COOP, 12):
            bot.log("Walking to the chicken coop...")
            go(bot, *COOP)
            continue

        eat_if_hurt(bot)
        chicken = bot.find_npc("Chicken")
        if chicken is None:
            bot.wait_ticks(3)              # they respawn quickly
            continue

        bot.attack(chicken)
        # Fight until that chicken is gone (dead) or 30 seconds pass.
        dead = bot.wait_until(lambda: all(n["index"] != chicken["index"] for n in bot.state()["npcs"]), timeout=30)
        if dead:
            kills += 1
            bot.log(f"Killed chicken #{kills}")
            loot(bot)
            bury_bones(bot)

    bot.log(f"Done: {kills} chickens killed.")


def go(bot, *spot):
    """Walk somewhere, running whenever there's run energy."""
    bot.run_on()
    bot.travel(*spot)


def near(bot, spot, distance):
    x, z, level = bot.position
    return level == 0 and abs(x - spot[0]) <= distance and abs(z - spot[1]) <= distance


def loot(bot):
    """Pick up what the chicken dropped (the nearest few items of the kinds we want)."""
    for _ in range(4):
        item = bot.find_ground_item(LOOT)
        if item is None or item.get("distance", 99) > 4 or bot.inv_full():
            return
        try:
            bot.take(item)
        except GatewayError as e:          # someone else took it, or it vanished
            bot.log(f"Couldn't take {item['name']}: {e}")
            return
        bot.wait_ticks(2)
    for raw in [i for i in bot.inventory() if i["name"] == "Raw chicken"]:
        bot.item_option(raw, "Drop")
        bot.wait_ticks(1)


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


def bank(bot):
    bot.log("Backpack full: banking everything at Lumbridge castle")
    go(bot, *BANK)
    bot.open_bank()
    bot.deposit_inventory()   # the feathers and anything else carried (starting items too)
    bot.wait_ticks(1)
    bot.close_interface()


run(main)
