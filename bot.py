TOKEN = "MTQwODMxNjY0MzE5MjM0NDYyNg.Gt97g1.qGKtx0qVy8KXxhVnV3ILeBkjfBs82CQG6wg3Vw"

import os
import json
import asyncio
import random
from threading import Lock
from datetime import datetime
from typing import Dict, Any, List

import discord
from discord.ext import commands

# =========================
# CONFIG
# =========================
PREFIX = "!"
DATA_FILE = "data.json"


# Intents (Default + Message Content)
intents = discord.Intents.default()
intents.message_content = True
intents.members = False  # set True if needed

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# =========================
# PERSISTENCE
# =========================
_data_lock = Lock()
_data: Dict[str, Any] = {}

def _ensure_user(user_id: int):
    uid = str(user_id)
    if uid not in _data.get("users", {}):
        _data["users"][uid] = {
            "money": 1000,
            "inventory": []  # List[str]
        }

def load_data():
    global _data
    if not os.path.exists(DATA_FILE):
        _data = {"users": {}, "meta": {"created_at": datetime.utcnow().isoformat()}}
        save_data()
        return
    with _data_lock:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                _data = json.load(f)
            if "users" not in _data:
                _data["users"] = {}
        except Exception:
            # If file is corrupted, create a new structure (backup old)
            backup = f"{DATA_FILE}.backup-{int(datetime.utcnow().timestamp())}"
            try:
                os.rename(DATA_FILE, backup)
            except Exception:
                pass
            _data = {"users": {}, "meta": {"created_at": datetime.utcnow().isoformat()}}
            save_data()

def save_data():
    with _data_lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)

def get_user_profile(user_id: int) -> Dict[str, Any]:
    _ensure_user(user_id)
    return _data["users"][str(user_id)]

def set_user_profile(user_id: int, profile: Dict[str, Any]):
    _data["users"][str(user_id)] = profile
    save_data()

# =========================
# HELPER FUNCTIONS (GAME LOGIC)
# =========================
def show_stats_text(money: int, inventory: List[str]) -> str:
    inv_text = ", ".join(inventory) if inventory else "Empty"
    return f"💰 **Money:** ${money}\n🎒 **Inventory:** {inv_text}"

def work_income(choice: str) -> int:
    # Your original: Income 50-300, job selection is just style
    return random.randint(50, 300)

ROULETTE_CHOICES = {
    "red": "Red",
    "black": "Black",
    "odd": "Odd",
    "even": "Even"
}

def roulette_spin() -> str:
    return random.choice(["Red", "Black", "Odd", "Even"])

def blackjack_draw() -> (int, int):
    # Your original: 1-11
    return random.randint(1, 11), random.randint(1, 11)

def crime_outcome() -> bool:
    return random.choice([True, False])

# Shop items as in original
SHOP_ITEMS = {
    "watch": {"name": "Watch", "price": 50},
    "necklace": {"name": "Necklace", "price": 100},
    "laptop": {"name": "Laptop", "price": 300},
}

# =========================
# BOT EVENTS
# =========================
@bot.event
async def on_ready():
    load_data()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name=f"{PREFIX}help"))

# =========================
# HELP
# =========================
@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🎮 Casino RPG – Commands",
        description=f"Prefix: `{PREFIX}`",
        color=0x2ecc71
    )
    embed.add_field(
        name="Profile & Stats",
        value="\n".join([
            f"`{PREFIX}start` – Create profile (if not existing)",
            f"`{PREFIX}stats` – Show money & inventory"
        ]),
        inline=False
    )
    embed.add_field(
        name="Work",
        value="\n".join([
            f"`{PREFIX}work <developer|teacher|designer>` – Work & earn income"
        ]),
        inline=False
    )
    embed.add_field(
        name="Roulette",
        value="\n".join([
            f"`{PREFIX}roulette <bet> <red|black|odd|even>` – Place a bet"
        ]),
        inline=False
    )
    embed.add_field(
        name="Blackjack",
        value=f"`{PREFIX}blackjack <bet>` – Simple 1-card duel",
        inline=False
    )
    embed.add_field(
        name="Bank (same as original – **no separate bank balance**)",
        value="\n".join([
            f"`{PREFIX}bank deposit <amount>` – Deposit money (deducts from balance)",
            f"`{PREFIX}bank withdraw <amount>` – Withdraw money (adds to balance)"
        ]),
        inline=False
    )
    embed.add_field(
        name="Shop",
        value="\n".join([
            f"`{PREFIX}shop list` – Show items",
            f"`{PREFIX}shop buy <watch|necklace|laptop>` – Buy an item"
        ]),
        inline=False
    )
    embed.add_field(
        name="Crime",
        value="\n".join([
            f"`{PREFIX}rob` – Rob a store",
            f"`{PREFIX}scam` – Scam someone"
        ]),
        inline=False
    )
    embed.set_footer(text="Tip: Amounts are integers. Inventory is user-bound.")
    await ctx.reply(embed=embed, mention_author=False)

# =========================
# BASICS: START & STATS
# =========================
@bot.command(name="start")
async def start_cmd(ctx: commands.Context):
    profile = get_user_profile(ctx.author.id)
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(f"✨ Profile ready! You start with **$ {profile['money']}**.\n" +
                    show_stats_text(profile['money'], profile['inventory']),
                    mention_author=False)

@bot.command(name="stats")
async def stats_cmd(ctx: commands.Context):
    profile = get_user_profile(ctx.author.id)
    await ctx.reply(show_stats_text(profile["money"], profile["inventory"]), mention_author=False)

# =========================
# WORK
# =========================
@bot.command(name="work")
async def work_cmd(ctx: commands.Context, job: str = None):
    if job is None or job.lower() not in {"developer", "teacher", "designer"}:
        return await ctx.reply("👔 **Choose a job:** `developer`, `teacher`, `designer`", mention_author=False)

    profile = get_user_profile(ctx.author.id)
    income = work_income(job.lower())
    profile["money"] += income
    set_user_profile(ctx.author.id, profile)

    await ctx.reply(f"💼 You worked as **{job.capitalize()}** and earned **${income}**.\n" +
                    show_stats_text(profile["money"], profile["inventory"]),
                    mention_author=False)

# =========================
# ROULETTE
# =========================
@bot.command(name="roulette")
async def roulette_cmd(ctx: commands.Context, bet: int = None, choice: str = None):
    if bet is None or choice is None:
        return await ctx.reply(f"🎲 Usage: `{PREFIX}roulette <bet> <red|black|odd|even>`", mention_author=False)
    choice = choice.lower()
    if choice not in ROULETTE_CHOICES:
        return await ctx.reply("❌ Invalid choice! Use: `red`, `black`, `odd`, `even`.", mention_author=False)
    if bet <= 0:
        return await ctx.reply("❌ Bet must be a positive number.", mention_author=False)

    profile = get_user_profile(ctx.author.id)
    if bet > profile["money"]:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    result = roulette_spin()

    msg = await ctx.reply("🎰 Spinning the wheel...", mention_author=False)
    await asyncio.sleep(2)
    win = False
    chosen_result = ROULETTE_CHOICES[choice]
    if (choice == "red" and result == "Red") or \
       (choice == "black" and result == "Black") or \
       (choice == "odd" and result == "Odd") or \
       (choice == "even" and result == "Even"):
        win = True

    if win:
        profile["money"] += bet
        outcome = "🎉 You won!"
    else:
        profile["money"] -= bet
        outcome = "❌ You lost!"

    set_user_profile(ctx.author.id, profile)
    await msg.edit(content=f"🎰 The wheel landed on **{result}**!\n{outcome}\n" +
                            show_stats_text(profile["money"], profile["inventory"]))

# =========================
# BLACKJACK (simple version as in original)
# =========================
@bot.command(name="blackjack")
async def blackjack_cmd(ctx: commands.Context, bet: int = None):
    if bet is None:
        return await ctx.reply(f"🃏 Usage: `{PREFIX}blackjack <bet>`", mention_author=False)
    if bet <= 0:
        return await ctx.reply("❌ Bet must be a positive number.", mention_author=False)

    profile = get_user_profile(ctx.author.id)
    if bet > profile["money"]:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    player_card, dealer_card = blackjack_draw()

    if player_card > dealer_card:
        profile["money"] += bet
        result = "🎉 You won!"
    elif player_card < dealer_card:
        profile["money"] -= bet
        result = "❌ You lost!"
    else:
        result = "🤝 It's a tie!"

    set_user_profile(ctx.author.id, profile)

    await ctx.reply(
        f"🃏 **Blackjack**\nYour card: **{player_card}**\nDealer's card: **{dealer_card}**\n{result}\n" +
        show_stats_text(profile["money"], profile["inventory"]),
        mention_author=False
    )

# =========================
# BANK (as original: only adjusts money – no separate bank balance)
# =========================
@bot.group(name="bank", invoke_without_command=True)
async def bank_group(ctx: commands.Context):
    await ctx.reply(
        f"🏦 Usage:\n`{PREFIX}bank deposit <amount>`\n`{PREFIX}bank withdraw <amount>`",
        mention_author=False
    )

@bank_group.command(name="deposit")
async def bank_deposit(ctx: commands.Context, amount: int = None):
    if amount is None or amount <= 0:
        return await ctx.reply("❌ Enter a positive amount.", mention_author=False)
    profile = get_user_profile(ctx.author.id)
    if amount > profile["money"]:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)
    profile["money"] -= amount
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(f"💵 You deposited **${amount}**.\n" +
                    show_stats_text(profile["money"], profile["inventory"]),
                    mention_author=False)

@bank_group.command(name="withdraw")
async def bank_withdraw(ctx: commands.Context, amount: int = None):
    if amount is None or amount <= 0:
        return await ctx.reply("❌ Enter a positive amount.", mention_author=False)
    profile = get_user_profile(ctx.author.id)
    profile["money"] += amount
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(f"💵 You withdrew **${amount}**.\n" +
                    show_stats_text(profile["money"], profile["inventory"]),
                    mention_author=False)

# =========================
# SHOP
# =========================
@bot.group(name="shop", invoke_without_command=True)
async def shop_group(ctx: commands.Context):
    await ctx.reply(
        f"🛒 Usage:\n`{PREFIX}shop list`\n`{PREFIX}shop buy <watch|necklace|laptop>`",
        mention_author=False
    )

@shop_group.command(name="list")
async def shop_list(ctx: commands.Context):
    lines = []
    for key, item in SHOP_ITEMS.items():
        lines.append(f"**{item['name']}** (${item['price']}) – key: `{key}`")
    await ctx.reply("🛒 **Shop Items**\n" + "\n".join(lines), mention_author=False)

@shop_group.command(name="buy")
async def shop_buy(ctx: commands.Context, item_key: str = None):
    if item_key is None:
        return await ctx.reply(f"❌ Usage: `{PREFIX}shop buy <watch|necklace|laptop>`", mention_author=False)
    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        return await ctx.reply("❌ Invalid item key. Use `shop list`.", mention_author=False)

    profile = get_user_profile(ctx.author.id)
    price = SHOP_ITEMS[item_key]["price"]
    name = SHOP_ITEMS[item_key]["name"]

    if profile["money"] < price:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    profile["money"] -= price
    profile["inventory"].append(name)
    set_user_profile(ctx.author.id, profile)

    await ctx.reply(f"✅ You bought a **{name}** for **${price}**.\n" +
                    show_stats_text(profile["money"], profile["inventory"]),
                    mention_author=False)

# =========================
# CRIME
# =========================
@bot.command(name="rob")
async def rob_cmd(ctx: commands.Context):
    profile = get_user_profile(ctx.author.id)
    success = crime_outcome()
    if success:
        reward = random.randint(100, 500)
        profile["money"] += reward
        msg = f"💰 You successfully robbed a store and earned **${reward}**!"
    else:
        penalty = random.randint(50, 150)
        profile["money"] -= penalty
        msg = f"❌ You got caught and lost **${penalty}**!"
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(msg + "\n" + show_stats_text(profile["money"], profile["inventory"]), mention_author=False)

@bot.command(name="scam")
async def scam_cmd(ctx: commands.Context):
    profile = get_user_profile(ctx.author.id)
    success = crime_outcome()
    if success:
        reward = random.randint(50, 300)
        profile["money"] += reward
        msg = f"💰 You successfully scammed someone and earned **${reward}**!"
    else:
        penalty = random.randint(25, 100)
        profile["money"] -= penalty
        msg = f"❌ You got caught and lost **${penalty}**!"
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(msg + "\n" + show_stats_text(profile["money"], profile["inventory"]), mention_author=False)

# =========================
# ERROR HANDLING
# =========================
@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.BadArgument):
        return await ctx.reply("❌ Invalid argument (expected a number?)", mention_author=False)
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.reply("❌ Missing argument.", mention_author=False)
    if isinstance(error, commands.CommandNotFound):
        return  # ignore unknown commands
    try:
        await ctx.reply("⚠️ An error occurred.", mention_author=False)
    except Exception:
        pass
    raise error  # for console

# =========================
# START
# =========================
    bot.run(TOKEN)
