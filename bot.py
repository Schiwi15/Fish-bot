# bot.py — Discord Economy + Casino + Jobs (hourly pay) + Bank + Interest
# Requires: discord.py  (pip install discord.py)

import os
import json
import asyncio
import random
from threading import Lock
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import discord
from discord.ext import commands, tasks

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or "PASTE_YOUR_TOKEN_HERE"
PREFIX = "!"
DATA_FILE = "data.json"
JOBS_FILE = "jobs.json"

# Job / Economy Settings
JOB_OFFERS_COUNT = 3          # wie viele zufällige Jobs angezeigt werden
JOB_OFFERS_TTL_MIN = 30       # Angebote laufen nach 30 Minuten ab
BANK_INTEREST_PER_HOUR = 0.01 # 1% pro Stunde (auf Bank)
HOURLY_LOOP_INTERVAL_MIN = 1  # wie oft wir prüfen (Minuten)

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = False
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# =========================
# PERSISTENCE
# =========================
_data_lock = Lock()
_data: Dict[str, Any] = {}   # {"users": { "<uid>": { ... } }, "meta": {...}}

def _now() -> datetime:
    # wir nutzen naive UTC-zeiten ( kompatibel zu str(datetime.utcnow()) )
    return datetime.utcnow()

def _iso(dt: Optional[datetime]) -> str:
    return (dt or _now()).isoformat()

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _ensure_root():
    global _data
    if "users" not in _data:
        _data["users"] = {}
    if "meta" not in _data:
        _data["meta"] = {"created_at": _iso(_now())}

def _ensure_user(user_id: int):
    _ensure_root()
    uid = str(user_id)
    if uid not in _data["users"]:
        _data["users"][uid] = {
            # Neues Schema
            "wallet": 1000,             # ehemals "money"
            "bank": 0,
            "inventory": [],
            # Jobs
            "job": None,                # string name
            "income": 0,                # coins/hour
            "last_pay": _iso(_now()),   # Zeitstempel letzte Job-Auszahlung
            # Job-Angebote
            "job_offers": [],           # Liste von Job-Namen
            "offers_expires": None,     # ISO
            # Banking
            "last_interest": _iso(_now())  # für Zins-Berechnung
        }
    else:
        # Migration: money -> wallet
        prof = _data["users"][uid]
        if "wallet" not in prof and "money" in prof:
            prof["wallet"] = prof.get("money", 0)
        if "bank" not in prof:
            prof["bank"] = 0
        if "inventory" not in prof:
            prof["inventory"] = []
        if "job" not in prof:
            prof["job"] = None
        if "income" not in prof:
            prof["income"] = 0
        if "last_pay" not in prof:
            prof["last_pay"] = _iso(_now())
        if "job_offers" not in prof:
            prof["job_offers"] = []
        if "offers_expires" not in prof:
            prof["offers_expires"] = None
        if "last_interest" not in prof:
            prof["last_interest"] = _iso(_now())

def load_data():
    global _data
    if not os.path.exists(DATA_FILE):
        _data = {"users": {}, "meta": {"created_at": _iso(_now())}}
        save_data()
        return
    with _data_lock:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                _data = json.load(f)
            _ensure_root()
        except Exception:
            # Backup defekter Datei
            backup = f"{DATA_FILE}.backup-{int(_now().timestamp())}"
            try:
                os.rename(DATA_FILE, backup)
            except Exception:
                pass
            _data = {"users": {}, "meta": {"created_at": _iso(_now())}}
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
# JOBS IO
# =========================
def load_jobs() -> List[Dict[str, Any]]:
    # Erstelle Standard-Jobs wenn Datei nicht vorhanden
    if not os.path.exists(JOBS_FILE):
        jobs = [
            {"name": "Baker",       "income": 150},
            {"name": "Programmer",  "income": 300},
            {"name": "Mechanic",    "income": 200},
            {"name": "Streamer",    "income": 100},
            {"name": "Teacher",     "income": 180},
            {"name": "Pilot",       "income": 400},
            {"name": "Designer",    "income": 220},
            {"name": "Doctor",      "income": 260},
            {"name": "Police",      "income": 210},
        ]
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_random_jobs(jobs: List[Dict[str, Any]], count=JOB_OFFERS_COUNT):
    return random.sample(jobs, min(count, len(jobs)))

# =========================
# HELPER (TEXT)
# =========================
def show_stats_text(profile: Dict[str, Any]) -> str:
    inv = profile.get("inventory", [])
    inv_text = ", ".join(inv) if inv else "Empty"
    return (
        f"💰 **Wallet:** ${profile.get('wallet', 0)}\n"
        f"🏦 **Bank:** ${profile.get('bank', 0)}\n"
        f"🎒 **Inventory:** {inv_text}\n"
        f"👔 **Job:** {profile.get('job') or 'None'}"
    )

# =========================
# SHOP (wie vorher)
# =========================
SHOP_ITEMS = {
    "watch": {"name": "Watch", "price": 50},
    "necklace": {"name": "Necklace", "price": 100},
    "laptop": {"name": "Laptop", "price": 300},
}

# Roulette & Blackjack
ROULETTE_CHOICES = {
    "red": "Red",
    "black": "Black",
    "odd": "Odd",
    "even": "Even"
}

def roulette_spin() -> str:
    return random.choice(["Red", "Black", "Odd", "Even"])

def blackjack_draw() -> (int, int):
    return random.randint(1, 11), random.randint(1, 11)

def crime_outcome() -> bool:
    return random.choice([True, False])

# =========================
# BOT EVENTS
# =========================
@bot.event
async def on_ready():
    load_data()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name=f"{PREFIX}help"))
    # Hintergrund-Task für Auszahlungen & Zinsen starten
    if not hourly_economy.is_running():
        hourly_economy.start()

# =========================
# HELP
# =========================
@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🎮 Economy & Casino – Commands",
        description=f"Prefix: `{PREFIX}`",
        color=0x2ecc71
    )
    embed.add_field(
        name="Profile & Stats",
        value="\n".join([
            f"`{PREFIX}start` – Create profile",
            f"`{PREFIX}stats` – Show wallet, bank, inventory, job",
            f"`{PREFIX}balance` – Shortcut for wallet & bank"
        ]),
        inline=False
    )
    embed.add_field(
        name="Jobs",
        value="\n".join([
            f"`{PREFIX}jobs` – Show {JOB_OFFERS_COUNT} random job offers (valid {JOB_OFFERS_TTL_MIN} min)",
            f"`{PREFIX}job <number>` – Claim a shown job"
        ]),
        inline=False
    )
    embed.add_field(
        name="Bank",
        value="\n".join([
            f"`{PREFIX}bank deposit <amount>` – Move from wallet ➜ bank",
            f"`{PREFIX}bank withdraw <amount>` – Move from bank ➜ wallet",
            f"💡 Bank earns {int(BANK_INTEREST_PER_HOUR*100)}% interest/hour"
        ]),
        inline=False
    )
    embed.add_field(
        name="Roulette",
        value=f"`{PREFIX}roulette <bet> <red|black|odd|even>` – Place a bet",
        inline=False
    )
    embed.add_field(
        name="Blackjack",
        value=f"`{PREFIX}blackjack <bet>` – Simple 1-card duel",
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
# BASICS: START, STATS, BALANCE
# =========================
@bot.command(name="start")
async def start_cmd(ctx: commands.Context):
    load_data()
    _ensure_user(ctx.author.id)
    save_data()
    profile = get_user_profile(ctx.author.id)
    await ctx.reply(
        f"✨ Profile ready! You start with **$ {profile['wallet']}**.\n" +
        show_stats_text(profile),
        mention_author=False
    )

@bot.command(name="stats")
async def stats_cmd(ctx: commands.Context):
    load_data()
    _ensure_user(ctx.author.id)
    profile = get_user_profile(ctx.author.id)
    await ctx.reply(show_stats_text(profile), mention_author=False)

@bot.command(name="balance")
async def balance_cmd(ctx: commands.Context):
    load_data()
    _ensure_user(ctx.author.id)
    p = get_user_profile(ctx.author.id)
    await ctx.reply(f"💰 Wallet: ${p['wallet']}\n🏦 Bank: ${p['bank']}", mention_author=False)

# =========================
# JOBS
# =========================
@bot.command(name="jobs")
async def jobs_cmd(ctx: commands.Context):
    load_data()
    prof = get_user_profile(ctx.author.id)

    # prüfe, ob Angebote existieren & gültig sind
    offers_valid = False
    if prof.get("job_offers"):
        exp = _parse_iso(prof.get("offers_expires"))
        if exp and _now() < exp:
            offers_valid = True

    # wenn nicht gültig -> neue generieren
    if not offers_valid:
        jobs_list = load_jobs()
        selected = get_random_jobs(jobs_list, JOB_OFFERS_COUNT)
        prof["job_offers"] = [j["name"] for j in selected]
        prof["offers_expires"] = _iso(_now() + timedelta(minutes=JOB_OFFERS_TTL_MIN))
        set_user_profile(ctx.author.id, prof)

    # Ausgabe
    jobs_list = load_jobs()
    job_map = {j["name"]: j for j in jobs_list}
    lines = []
    for i, name in enumerate(prof["job_offers"], start=1):
        info = job_map.get(name, {"income": "?"})
        lines.append(f"**{i}.** {name} – {info['income']} Coins/hour")
    await ctx.reply(
        "Available jobs (valid until {} UTC):\n{}\n\nUse `!job <number>` to claim."
        .format(prof['offers_expires'], "\n".join(lines)),
        mention_author=False
    )

@bot.command(name="job")
async def job_cmd(ctx: commands.Context, job_num: int = None):
    if job_num is None:
        return await ctx.reply(f"Usage: `{PREFIX}job <number>`", mention_author=False)

    load_data()
    prof = get_user_profile(ctx.author.id)

    # validiere Angebote
    exp = _parse_iso(prof.get("offers_expires"))
    if not prof.get("job_offers") or not exp or _now() > exp:
        return await ctx.reply("❌ No valid job offers. Use `!jobs` first.", mention_author=False)

    if job_num < 1 or job_num > len(prof["job_offers"]):
        return await ctx.reply("❌ Invalid job number.", mention_author=False)

    jobs_list = load_jobs()
    job_map = {j["name"]: j for j in jobs_list}

    chosen_name = prof["job_offers"][job_num - 1]
    chosen = job_map.get(chosen_name)
    if not chosen:
        return await ctx.reply("❌ This job no longer exists.", mention_author=False)

    # Setze Job
    prof["job"] = chosen["name"]
    prof["income"] = int(chosen["income"])
    prof["last_pay"] = _iso(_now())

    # optional: offers invalidieren, damit man nicht mehrfach claimt
    prof["job_offers"] = []
    prof["offers_expires"] = None

    set_user_profile(ctx.author.id, prof)
    await ctx.reply(
        f"✅ You have taken the job **{chosen['name']}**! Income: {chosen['income']} Coins per hour.",
        mention_author=False
    )

# =========================
# PAYOUT & INTEREST (BACKGROUND)
# =========================
@tasks.loop(minutes=HOURLY_LOOP_INTERVAL_MIN)
async def hourly_economy():
    # Diese Routine:
    # - zahlt Job-Einkommen für volle Stunden seit last_pay aus
    # - zahlt Bankzinsen pro vergangener Stunde seit last_interest
    try:
        load_data()
        changed = False
        now = _now()

        for uid, prof in list(_data.get("users", {}).items()):
            # JOB-AUSZAHLUNG
            if prof.get("job") and prof.get("income", 0) > 0:
                last = _parse_iso(prof.get("last_pay")) or now
                elapsed = now - last
                hours = int(elapsed.total_seconds() // 3600)
                if hours > 0:
                    payout = prof["income"] * hours
                    prof["wallet"] = int(prof.get("wallet", 0)) + int(payout)
                    prof["last_pay"] = _iso(last + timedelta(hours=hours))
                    changed = True

            # BANK-ZINSEN
            last_i = _parse_iso(prof.get("last_interest")) or now
            elapsed_i = now - last_i
            hours_i = int(elapsed_i.total_seconds() // 3600)
            if hours_i > 0 and prof.get("bank", 0) > 0 and BANK_INTEREST_PER_HOUR > 0:
                bank = float(prof.get("bank", 0))
                # stündlicher Zinseszins
                for _ in range(hours_i):
                    bank *= (1.0 + BANK_INTEREST_PER_HOUR)
                prof["bank"] = int(bank)
                prof["last_interest"] = _iso(last_i + timedelta(hours=hours_i))
                changed = True

        if changed:
            save_data()
    except Exception as e:
        print(f"[hourly_economy] error: {e}")

# =========================
# BANK (separat)
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
    load_data()
    prof = get_user_profile(ctx.author.id)
    if amount > prof["wallet"]:
        return await ctx.reply("❌ Not enough in wallet.", mention_author=False)
    prof["wallet"] -= amount
    prof["bank"] += amount
    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"💵 Deposited **${amount}**.\n" + show_stats_text(prof), mention_author=False)

@bank_group.command(name="withdraw")
async def bank_withdraw(ctx: commands.Context, amount: int = None):
    if amount is None or amount <= 0:
        return await ctx.reply("❌ Enter a positive amount.", mention_author=False)
    load_data()
    prof = get_user_profile(ctx.author.id)
    if amount > prof["bank"]:
        return await ctx.reply("❌ Not enough on bank.", mention_author=False)
    prof["bank"] -= amount
    prof["wallet"] += amount
    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"💵 Withdrew **${amount}**.\n" + show_stats_text(prof), mention_author=False)

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

    load_data()
    profile = get_user_profile(ctx.author.id)
    price = SHOP_ITEMS[item_key]["price"]
    name = SHOP_ITEMS[item_key]["name"]

    if profile["wallet"] < price:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    profile["wallet"] -= price
    profile["inventory"].append(name)
    set_user_profile(ctx.author.id, profile)

    await ctx.reply(f"✅ You bought a **{name}** for **${price}**.\n" +
                    show_stats_text(profile), mention_author=False)

# =========================
# CRIME
# =========================
@bot.command(name="rob")
async def rob_cmd(ctx: commands.Context):
    load_data()
    profile = get_user_profile(ctx.author.id)
    success = crime_outcome()
    if success:
        reward = random.randint(100, 500)
        profile["wallet"] += reward
        msg = f"💰 You successfully robbed a store and earned **${reward}**!"
    else:
        penalty = random.randint(50, 150)
        profile["wallet"] -= penalty
        msg = f"❌ You got caught and lost **${penalty}**!"
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(msg + "\n" + show_stats_text(profile), mention_author=False)

@bot.command(name="scam")
async def scam_cmd(ctx: commands.Context):
    load_data()
    profile = get_user_profile(ctx.author.id)
    success = crime_outcome()
    if success:
        reward = random.randint(50, 300)
        profile["wallet"] += reward
        msg = f"💰 You successfully scammed someone and earned **${reward}**!"
    else:
        penalty = random.randint(25, 100)
        profile["wallet"] -= penalty
        msg = f"❌ You got caught and lost **${penalty}**!"
    set_user_profile(ctx.author.id, profile)
    await ctx.reply(msg + "\n" + show_stats_text(profile), mention_author=False)

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

    load_data()
    profile = get_user_profile(ctx.author.id)
    if bet > profile["wallet"]:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    result = roulette_spin()

    msg = await ctx.reply("🎰 Spinning the wheel...", mention_author=False)
    await asyncio.sleep(2)
    win = (ROULETTE_CHOICES[choice] == result)

    if win:
        profile["wallet"] += bet
        outcome = "🎉 You won!"
    else:
        profile["wallet"] -= bet
        outcome = "❌ You lost!"

    set_user_profile(ctx.author.id, profile)
    await msg.edit(content=f"🎰 The wheel landed on **{result}**!\n{outcome}\n" +
                            show_stats_text(profile))

# =========================
# BLACKJACK
# =========================
@bot.command(name="blackjack")
async def blackjack_cmd(ctx: commands.Context, bet: int = None):
    if bet is None:
        return await ctx.reply(f"🃏 Usage: `{PREFIX}blackjack <bet>`", mention_author=False)
    if bet <= 0:
        return await ctx.reply("❌ Bet must be a positive number.", mention_author=False)

    load_data()
    profile = get_user_profile(ctx.author.id)
    if bet > profile["wallet"]:
        return await ctx.reply("❌ You don't have enough money!", mention_author=False)

    player_card, dealer_card = blackjack_draw()

    if player_card > dealer_card:
        profile["wallet"] += bet
        result = "🎉 You won!"
    elif player_card < dealer_card:
        profile["wallet"] -= bet
        result = "❌ You lost!"
    else:
        result = "🤝 It's a tie!"

    set_user_profile(ctx.author.id, profile)

    await ctx.reply(
        f"🃏 **Blackjack**\nYour card: **{player_card}**\nDealer's card: **{dealer_card}**\n{result}\n" +
        show_stats_text(profile),
        mention_author=False
    )

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
import os

if __name__ == "__main__":
    token_file = "token.txt"
    TOKEN = None

    # Try reading token from file
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            TOKEN = f.read().strip()

    # If no token, prompt user
    if not TOKEN:
        TOKEN = input("Enter your Discord bot token: ").strip()
        # Save token to file for next time
        with open(token_file, "w") as f:
            f.write(TOKEN)
        print(f"Token saved to {token_file}.")

    if not TOKEN:
        print("[ERROR] No token provided. Exiting.")
    else:
        bot.run(TOKEN)

