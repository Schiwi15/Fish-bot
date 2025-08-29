# bot.py — Discord Economy + Casino + Jobs + Bank + Slots + Lottery + Rob + Leaderboard + Shop (Shields & Boosts)
# Python 3.x, discord.py 2.x
# Prefix (!) + Slash-Commands via hybrid commands

import os
import json
import asyncio
import random
from threading import Lock
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Literal

import discord
from discord.ext import commands, tasks

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or "PASTE_YOUR_TOKEN_HERE"
PREFIX = "!"
DATA_FILE = "data.json"
JOBS_FILE = "jobs.json"
ITEMS_FILE = "items.json"
LOTTO_FILE = "lottery.json"

# Economy / Game Settings
JOB_OFFERS_COUNT = 3
JOB_OFFERS_TTL_MIN = 30
HOURLY_LOOP_INTERVAL_MIN = 1  # prüft alle 1 Min. (Zahlungen/Effekte)
ROB_COOLDOWN_MIN = 60
ROB_SUCCESS_CHANCE = 0.5
ROB_LOOT_MIN_PCT = 0.10
ROB_LOOT_MAX_PCT = 0.30
ROB_FAIL_FINE_MIN = 50
ROB_FAIL_FINE_MAX = 150

SLOTS_SYMBOLS = ["🍒", "🍋", "⭐", "🍇", "💎"]
SLOTS_JACKPOT_MULT = 5
SLOTS_TWOMATCH_MULT = 2

LOTTO_TICKET_PRICE = 100
LOTTO_WIN_PCT = 0.70  # 70% des Pots an Gewinner

# Boost Defaults (werden auch in items.json abgelegt)
DEFAULT_ITEMS = [
    # Permanentes Deko-Item-Beispiel
    {"key": "watch", "name": "Watch", "price": 50, "type": "cosmetic"},
    {"key": "necklace", "name": "Necklace", "price": 100, "type": "cosmetic"},
    {"key": "laptop", "name": "Laptop", "price": 300, "type": "cosmetic"},

    # Shield (blockt Robs)
    {"key": "shield_24h", "name": "Shield 24h", "price": 500, "type": "shield", "duration_hours": 24},

    # Boosts
    {"key": "boost_job10_6h", "name": "Job Boost +10% (6h)", "price": 400, "type": "job_boost", "percent": 10, "duration_hours": 6},
    {"key": "boost_job25_6h", "name": "Job Boost +25% (6h)", "price": 900, "type": "job_boost", "percent": 25, "duration_hours": 6},
    {"key": "boost_luck5_6h", "name": "Luck Boost +5% (6h)", "price": 350, "type": "luck_boost", "percent": 5, "duration_hours": 6},
    {"key": "boost_interest10_24h", "name": "Interest Boost +10% (24h)", "price": 800, "type": "interest_boost", "percent": 10, "duration_hours": 24},
]

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # für robustere Member-Operationen (rob, leaderboard-Namen etc.)
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# =========================
# PERSISTENCE
# =========================
_data_lock = Lock()
_data: Dict[str, Any] = {}   # {"users": {...}, "meta": {...}}
_lotto: Dict[str, Any] = {}  # {"jackpot": int, "tickets":[{"user_id": str}], "last_draw": ISO}

def _now() -> datetime:
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
            "wallet": 1000,
            "bank": 0,
            "inventory": [],    # kosmetische items
            "job": None,
            "income": 0,
            "last_pay": _iso(_now()),
            "job_offers": [],
            "offers_expires": None,
            "last_interest": _iso(_now()),
            "effects": {},
            "rob_cooldown_until": None,
        }
    else:
        # Migration älterer Felder
        prof = _data["users"][uid]
        if "wallet" not in prof and "money" in prof:
            prof["wallet"] = prof.get("money", 0)
        prof.setdefault("bank", 0)
        prof.setdefault("inventory", [])
        prof.setdefault("job", None)
        prof.setdefault("income", 0)
        prof.setdefault("last_pay", _iso(_now()))
        prof.setdefault("job_offers", [])
        prof.setdefault("offers_expires", None)
        prof.setdefault("last_interest", _iso(_now()))
        prof.setdefault("effects", {})
        prof.setdefault("rob_cooldown_until", None)

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

# ---- jobs & items & lottery files
def load_jobs() -> List[Dict[str, Any]]:
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

def load_items() -> List[Dict[str, Any]]:
    if not os.path.exists(ITEMS_FILE):
        with open(ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ITEMS, f, indent=2, ensure_ascii=False)
    with open(ITEMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_lottery():
    global _lotto
    if not os.path.exists(LOTTO_FILE):
        _lotto = {"jackpot": 0, "tickets": [], "last_draw": None}
        save_lottery()
        return
    with open(LOTTO_FILE, "r", encoding="utf-8") as f:
        _lotto = json.load(f)

def save_lottery():
    with open(LOTTO_FILE, "w", encoding="utf-8") as f:
        json.dump(_lotto, f, indent=2, ensure_ascii=False)

def get_random_jobs(jobs: List[Dict[str, Any]], count=JOB_OFFERS_COUNT):
    return random.sample(jobs, min(count, len(jobs)))

# =========================
# HELPERS
# =========================
def effect_active(profile: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    eff = profile.get("effects", {}).get(key)
    if not eff:
        return None
    until = _parse_iso(eff.get("until"))
    if until and _now() < until:
        return eff
    # abgelaufen -> löschen
    profile["effects"].pop(key, None)
    return None

def add_effect(profile: Dict[str, Any], key: str, hours: int, extra: Optional[Dict[str, Any]] = None):
    if "effects" not in profile:
        profile["effects"] = {}
    eff = {"until": _iso(_now() + timedelta(hours=hours))}
    if extra:
        eff.update(extra)
    profile["effects"][key] = eff

def get_job_income_with_boost(profile: Dict[str, Any]) -> int:
    base = int(profile.get("income", 0))
    jb = effect_active(profile, "job_boost")
    if jb:
        pct = int(jb.get("percent", 0))
        base = int(round(base * (1 + pct/100.0)))
    return base

def get_slots_luck_bonus(profile: Dict[str, Any]) -> int:
    lb = effect_active(profile, "luck_boost")
    return int(lb.get("percent", 0)) if lb else 0

def show_stats_text(profile: Dict[str, Any]) -> str:
    inv = profile.get("inventory", [])
    inv_text = ", ".join(inv) if inv else "Empty"
    shield_info = "Active" if effect_active(profile, "shield") else "None"
    job_line = f"{profile.get('job') or 'None'} ({get_job_income_with_boost(profile)} /h)" if profile.get("job") else "None"
    return (
        f"💰 **Wallet:** ${profile.get('wallet', 0)}\n"
        f"🏦 **Bank:** ${profile.get('bank', 0)}\n"
        f"👔 **Job:** {job_line}\n"
        f"🛡️ **Shield:** {shield_info}\n"
        f"🎒 **Inventory:** {inv_text}"
    )

# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    load_data()
    load_lottery()
    load_items()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name=f"{PREFIX}help"))
    if not economy_loop.is_running():
        economy_loop.start()
    # Slash-Befehle synchronisieren
    try:
        await bot.tree.sync()
        print("✅ Slash-Commands synchronisiert.")
    except Exception as e:
        print(f"Slash-Sync Fehler: {e}")

# =========================
# BACKGROUND LOOP (Jobs zahlen, Effekte aufräumen)
# =========================
@tasks.loop(minutes=HOURLY_LOOP_INTERVAL_MIN)
async def economy_loop():
    try:
        load_data()
        changed = False
        now = _now()

        for uid, prof in list(_data.get("users", {}).items()):
            # Effekte automatisch aufräumen (shield/boosts)
            for key in list(prof.get("effects", {}).keys()):
                effect_active(prof, key)  # ruft zugleich cleanup auf

            # Job-Auszahlung pro volle Stunde
            if prof.get("job") and prof.get("income", 0) > 0:
                last = _parse_iso(prof.get("last_pay")) or now
                elapsed = now - last
                hours = int(elapsed.total_seconds() // 3600)
                if hours > 0:
                    pay_per_hour = get_job_income_with_boost(prof)
                    payout = pay_per_hour * hours
                    prof["wallet"] = int(prof.get("wallet", 0)) + int(payout)
                    prof["last_pay"] = _iso(last + timedelta(hours=hours))
                    changed = True

            # Rob-Cooldown aufräumen
            rc = _parse_iso(prof.get("rob_cooldown_until"))
            if rc and now >= rc:
                prof["rob_cooldown_until"] = None
                changed = True

        if changed:
            save_data()
    except Exception as e:
        print(f"[economy_loop] error: {e}")

# =========================
# HELP (hybrid)
# =========================
@commands.hybrid_command(name="help", description="Show all commands")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🎮 Economy & Casino – Commands",
        description=f"Prefix: `{PREFIX}`  •  Slash: `/`",
        color=0x2ecc71
    )
    embed.add_field(
        name="Profile",
        value="\n".join([
            f"`{PREFIX}start` / `/start` – Create profile",
            f"`{PREFIX}stats` / `/stats` – Show stats",
            f"`{PREFIX}balance` / `/balance` – Wallet & Bank"
        ]),
        inline=False
    )
    embed.add_field(
        name="Jobs",
        value="\n".join([
            f"`{PREFIX}jobs` / `/jobs` – Show {JOB_OFFERS_COUNT} random offers (valid {JOB_OFFERS_TTL_MIN} min)",
            f"`{PREFIX}job <number>` / `/job number:` – Claim a job"
        ]),
        inline=False
    )
    embed.add_field(
        name="Bank",
        value="\n".join([
            f"`{PREFIX}bank deposit <amount>` / `/bank_deposit amount:`",
            f"`{PREFIX}bank withdraw <amount>` / `/bank_withdraw amount:`",
        ]),
        inline=False
    )
    embed.add_field(
        name="Casino",
        value="\n".join([
            f"`{PREFIX}slots <bet>` / `/slots bet:`",
            f"`{PREFIX}roulette <bet> <red|black|odd|even>` / `/roulette ...`",
            f"`{PREFIX}blackjack <bet>` / `/blackjack bet:`",
        ]),
        inline=False
    )
    embed.add_field(
        name="Lottery",
        value="\n".join([
            f"`{PREFIX}lotto buy` / `/lotto_buy` – Buy ticket ({LOTTO_TICKET_PRICE})",
            f"`{PREFIX}lotto draw` / `/lotto_draw` – Draw winner (admin)"
        ]),
        inline=False
    )
    embed.add_field(
        name="PvP Rob",
        value=f"`{PREFIX}rob @user` / `/rob user:` – Steal from a user (cooldown {ROB_COOLDOWN_MIN} min, shield blocks)",
        inline=False
    )
    embed.add_field(
        name="Shop",
        value="\n".join([
            f"`{PREFIX}shop list` / `/shop_list`",
            f"`{PREFIX}shop buy <key>` / `/shop_buy key:`"
        ]),
        inline=False
    )
    embed.add_field(
        name="Leaderboard",
        value=f"`{PREFIX}leaderboard` / `/leaderboard` – Top 10 by net worth",
        inline=False
    )
    await ctx.reply(embed=embed, mention_author=False)

bot.add_command(help_cmd)

# =========================
# BASICS (hybrid)
# =========================
@commands.hybrid_command(name="start", description="Create profile")
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

@commands.hybrid_command(name="stats", description="Show your stats")
async def stats_cmd(ctx: commands.Context):
    load_data()
    _ensure_user(ctx.author.id)
    profile = get_user_profile(ctx.author.id)
    await ctx.reply(show_stats_text(profile), mention_author=False)

@commands.hybrid_command(name="balance", description="Wallet & Bank")
async def balance_cmd(ctx: commands.Context):
    load_data()
    _ensure_user(ctx.author.id)
    p = get_user_profile(ctx.author.id)
    await ctx.reply(f"💰 Wallet: ${p['wallet']}\n🏦 Bank: ${p['bank']}", mention_author=False)

# =========================
# BANK (hybrid: einzelne commands)
# =========================
@commands.hybrid_command(name="bank_deposit", description="Deposit from wallet to bank")
async def bank_deposit_cmd(ctx: commands.Context, amount: int):
    if amount <= 0:
        return await ctx.reply("❌ Enter a positive amount.", mention_author=False)
    load_data()
    prof = get_user_profile(ctx.author.id)
    if amount > prof["wallet"]:
        return await ctx.reply("❌ Not enough in wallet.", mention_author=False)
    prof["wallet"] -= amount
    prof["bank"] += amount
    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"💵 Deposited **${amount}**.\n" + show_stats_text(prof), mention_author=False)

@commands.hybrid_command(name="bank_withdraw", description="Withdraw from bank to wallet")
async def bank_withdraw_cmd(ctx: commands.Context, amount: int):
    if amount <= 0:
        return await ctx.reply("❌ Enter a positive amount.", mention_author=False)
    load_data()
    prof = get_user_profile(ctx.author.id)
    if amount > prof["bank"]:
        return await ctx.reply("❌ Not enough on bank.", mention_author=False)
    prof["bank"] -= amount
    prof["wallet"] += amount
    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"💵 Withdrew **${amount}**.\n" + show_stats_text(prof), mention_author=False)

# Legacy prefix bank group (für Kompatibilität)
@bot.group(name="bank", invoke_without_command=True)
async def bank_group(ctx: commands.Context):
    await ctx.reply(
        f"🏦 Usage:\n`{PREFIX}bank deposit <amount>`\n`{PREFIX}bank withdraw <amount>`",
        mention_author=False
    )

@bank_group.command(name="deposit")
async def bank_deposit_prefix(ctx: commands.Context, amount: int = None):
    if amount is None:
        return await ctx.reply("Usage: !bank deposit <amount>", mention_author=False)
    await bank_deposit_cmd(ctx, amount)

@bank_group.command(name="withdraw")
async def bank_withdraw_prefix(ctx: commands.Context, amount: int = None):
    if amount is None:
        return await ctx.reply("Usage: !bank withdraw <amount>", mention_author=False)
    await bank_withdraw_cmd(ctx, amount)

# =========================
# JOBS (hybrid)
# =========================
@commands.hybrid_command(name="jobs", description="Show random job offers")
async def jobs_cmd(ctx: commands.Context):
    load_data()
    prof = get_user_profile(ctx.author.id)
    offers_valid = False
    if prof.get("job_offers"):
        exp = _parse_iso(prof.get("offers_expires"))
        if exp and _now() < exp:
            offers_valid = True

    if not offers_valid:
        jobs_list = load_jobs()
        selected = get_random_jobs(jobs_list, JOB_OFFERS_COUNT)
        prof["job_offers"] = [j["name"] for j in selected]
        prof["offers_expires"] = _iso(_now() + timedelta(minutes=JOB_OFFERS_TTL_MIN))
        set_user_profile(ctx.author.id, prof)

    jobs_list = load_jobs()
    job_map = {j["name"]: j for j in jobs_list}
    lines = []
    for i, name in enumerate(prof["job_offers"], start=1):
        info = job_map.get(name, {"income": "?"})
        lines.append(f"**{i}.** {name} – {info['income']} Coins/hour")
    await ctx.reply(
        "Available jobs (valid until {} UTC):\n{}\nUse `!job <number>` or `/job number:` to claim."
        .format(prof['offers_expires'], "\n".join(lines)),
        mention_author=False
    )

@commands.hybrid_command(name="job", description="Claim a job")
async def job_cmd(ctx: commands.Context, number: int):
    load_data()
    prof = get_user_profile(ctx.author.id)
    exp = _parse_iso(prof.get("offers_expires"))
    if not prof.get("job_offers") or not exp or _now() > exp:
        return await ctx.reply("❌ No valid job offers. Use `!jobs` first.", mention_author=False)
    if number < 1 or number > len(prof["job_offers"]):
        return await ctx.reply("❌ Invalid job number.", mention_author=False)

    jobs_list = load_jobs()
    job_map = {j["name"]: j for j in jobs_list}
    chosen_name = prof["job_offers"][number - 1]
    chosen = job_map.get(chosen_name)
    if not chosen:
        return await ctx.reply("❌ This job no longer exists.", mention_author=False)

    prof["job"] = chosen["name"]
    prof["income"] = int(chosen["income"])
    prof["last_pay"] = _iso(_now())
    prof["job_offers"] = []
    prof["offers_expires"] = None
    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"✅ You took **{chosen['name']}**: {chosen['income']} /h.", mention_author=False)

# =========================
# SLOTS (hybrid)
# =========================
@commands.hybrid_command(name="slots", description="Spin the slot machine")
async def slots_cmd(ctx: commands.Context, bet: int):
    if bet <= 0:
        return await ctx.reply("❌ Bet must be positive.", mention_author=False)
    load_data()
    prof = get_user_profile(ctx.author.id)
    if bet > prof["wallet"]:
        return await ctx.reply("❌ Not enough money.", mention_author=False)

    prof["wallet"] -= bet

    # Luck boost: kleine Chance, einen Slot zu "nudgen" (z. B. 0–5%)
    luck = get_slots_luck_bonus(prof)  # Prozent
    rolls = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]

    # Mit Glück: mit kleiner Wahrscheinlichkeit mach ein 2er zu 3er Match
    if luck > 0 and random.random() < (luck / 100.0):
        if rolls[0] == rolls[1] or rolls[1] == rolls[2] or rolls[0] == rolls[2]:
            common = rolls[1] if rolls[0] == rolls[1] else (rolls[2] if rolls[1] == rolls[2] else rolls[0])
            rolls = [common, common, common]

    win_mult = 0
    if rolls[0] == rolls[1] == rolls[2]:
        win_mult = SLOTS_JACKPOT_MULT
    elif rolls[0] == rolls[1] or rolls[1] == rolls[2] or rolls[0] == rolls[2]:
        win_mult = SLOTS_TWOMATCH_MULT

    winnings = bet * win_mult
    prof["wallet"] += winnings
    set_user_profile(ctx.author.id, prof)

    outcome = "🎉 JACKPOT!" if win_mult == SLOTS_JACKPOT_MULT else ("✅ Small win!" if win_mult == SLOTS_TWOMATCH_MULT else "❌ No win.")
    # Net change anzeigen
    change = winnings if winnings > 0 else -bet
    change_str = f"+${change}" if change > 0 else f"-${abs(change)}"
    await ctx.reply(f"🎰 | {' '.join(rolls)} | {outcome}\nResult: **{change_str}**\n" + show_stats_text(prof), mention_author=False)

# =========================
# LOTTERY (hybrid)
# =========================
@commands.hybrid_command(name="lotto_buy", description="Buy a lottery ticket")
async def lotto_buy_cmd(ctx: commands.Context):
    load_data()
    load_lottery()
    prof = get_user_profile(ctx.author.id)
    if prof["wallet"] < LOTTO_TICKET_PRICE:
        return await ctx.reply(f"❌ Need ${LOTTO_TICKET_PRICE}.", mention_author=False)

    prof["wallet"] -= LOTTO_TICKET_PRICE
    set_user_profile(ctx.author.id, prof)

    _lotto["tickets"].append({"user_id": str(ctx.author.id)})
    _lotto["jackpot"] = int(_lotto.get("jackpot", 0)) + LOTTO_TICKET_PRICE
    save_lottery()

    await ctx.reply(f"🎟️ Ticket purchased! Current jackpot: ${_lotto['jackpot']}.", mention_author=False)

@commands.hybrid_command(name="lotto_draw", description="Draw a lottery winner (admin)")
@commands.has_permissions(manage_guild=True)
async def lotto_draw_cmd(ctx: commands.Context):
    load_data()
    load_lottery()
    if not _lotto.get("tickets"):
        return await ctx.reply("No tickets sold yet.", mention_author=False)

    winner_ticket = random.choice(_lotto["tickets"])
    winner_id = int(winner_ticket["user_id"])
    jackpot_win = int(_lotto["jackpot"] * LOTTO_WIN_PCT)

    prof = get_user_profile(winner_id)
    prof["wallet"] += jackpot_win
    set_user_profile(winner_id, prof)

    # Reset lottery (rest „verfällt“)
    _lotto["last_draw"] = _iso(_now())
    _lotto["tickets"] = []
    _lotto["jackpot"] = 0
    save_lottery()

    user_obj = ctx.guild.get_member(winner_id) or (await ctx.guild.fetch_member(winner_id))
    await ctx.reply(f"🎉 Lottery Winner: **{user_obj.mention}** wins **${jackpot_win}**!", mention_author=False)

# =========================
# ROB (hybrid)
# =========================
@commands.hybrid_command(name="rob", description="Attempt to rob another user")
async def rob_cmd(ctx: commands.Context, user: discord.Member):
    if user.id == ctx.author.id:
        return await ctx.reply("❌ You cannot rob yourself.", mention_author=False)
    if user.bot:
        return await ctx.reply("❌ You cannot rob bots.", mention_author=False)

    load_data()
    attacker = get_user_profile(ctx.author.id)
    victim = get_user_profile(user.id)

    # Check cooldown
    rc = _parse_iso(attacker.get("rob_cooldown_until"))
    if rc and _now() < rc:
        left = rc - _now()
        mins = int(left.total_seconds() // 60)
        return await ctx.reply(f"⌛ Rob cooldown active: {mins} min left.", mention_author=False)

    # Victim shield?
    if effect_active(victim, "shield"):
        return await ctx.reply("🛡️ Target is protected by a shield.", mention_author=False)

    if victim["wallet"] <= 0:
        return await ctx.reply("Target has nothing to steal.", mention_author=False)

    # Attempt
    success = random.random() < ROB_SUCCESS_CHANCE
    if success:
        pct = random.uniform(ROB_LOOT_MIN_PCT, ROB_LOOT_MAX_PCT)
        loot = int(victim["wallet"] * pct)
        loot = max(1, loot)
        victim["wallet"] -= loot
        attacker["wallet"] += loot
        msg = f"😈 Success! You stole **${loot}** from {user.mention}."
    else:
        fine = random.randint(ROB_FAIL_FINE_MIN, ROB_FAIL_FAIL_MAX) if 'ROB_FAIL_FAIL_MAX' in globals() else random.randint(ROB_FAIL_FINE_MIN, ROB_FAIL_FINE_MAX)
        fine = min(fine, attacker["wallet"])
        attacker["wallet"] -= fine
        msg = f"🚨 Caught! You paid a fine of **${fine}**."

    # Set cooldown
    attacker["rob_cooldown_until"] = _iso(_now() + timedelta(minutes=ROB_COOLDOWN_MIN))

    set_user_profile(ctx.author.id, attacker)
    set_user_profile(user.id, victim)

    await ctx.reply(msg, mention_author=False)

# =========================
# SHOP (hybrid)
# =========================
@commands.hybrid_command(name="shop_list", description="List shop items")
async def shop_list_cmd(ctx: commands.Context):
    items = load_items()
    lines = []
    for it in items:
        line = f"**{it['name']}** (${it['price']}) – key: `{it['key']}`"
        if it["type"] == "shield":
            line += f" • Shield {it.get('duration_hours', 0)}h"
        elif it["type"].endswith("_boost"):
            line += f" • +{it.get('percent', 0)}% for {it.get('duration_hours', 0)}h"
        lines.append(line)
    await ctx.reply("🛒 **Shop Items**\n" + "\n".join(lines), mention_author=False)

@commands.hybrid_command(name="shop_buy", description="Buy a shop item by key")
async def shop_buy_cmd(ctx: commands.Context, key: str):
    key = key.lower().strip()
    items = load_items()
    catalog = {i["key"]: i for i in items}
    if key not in catalog:
        return await ctx.reply("❌ Invalid item key. Use `!shop list`.", mention_author=False)

    load_data()
    prof = get_user_profile(ctx.author.id)
    item = catalog[key]
    price = int(item["price"])
    if prof["wallet"] < price:
        return await ctx.reply("❌ Not enough money.", mention_author=False)

    prof["wallet"] -= price
    itype = item["type"]

    if itype == "cosmetic":
        prof["inventory"].append(item["name"])
    elif itype == "shield":
        add_effect(prof, "shield", item.get("duration_hours", 24))
    elif itype == "job_boost":
        add_effect(prof, "job_boost", item.get("duration_hours", 6), {"percent": int(item.get("percent", 0))})
    elif itype == "luck_boost":
        add_effect(prof, "luck_boost", item.get("duration_hours", 6), {"percent": int(item.get("percent", 0))})
    elif itype == "interest_boost":
        add_effect(prof, "interest_boost", item.get("duration_hours", 24), {"percent": int(item.get("percent", 0))})
    else:
        prof["inventory"].append(item["name"])  # fallback

    set_user_profile(ctx.author.id, prof)
    await ctx.reply(f"✅ Purchased **{item['name']}** for **${price}**.\n" + show_stats_text(prof), mention_author=False)

# Legacy prefix shop group (Kompatibilität)
@bot.group(name="shop", invoke_without_command=True)
async def shop_group(ctx: commands.Context):
    await ctx.reply(
        f"🛒 Usage:\n`{PREFIX}shop list`\n`{PREFIX}shop buy <key>`",
        mention_author=False
    )

@shop_group.command(name="list")
async def shop_list_prefix(ctx: commands.Context):
    await shop_list_cmd(ctx)

@shop_group.command(name="buy")
async def shop_buy_prefix(ctx: commands.Context, key: str = None):
    if not key:
        return await ctx.reply("Usage: !shop buy <key>", mention_author=False)
    await shop_buy_cmd(ctx, key)

# =========================
# ROULETTE (hybrid)
# =========================
ROULETTE_CHOICES = {"red": "Red", "black": "Black", "odd": "Odd", "even": "Even"}

def roulette_spin() -> str:
    return random.choice(list(ROULETTE_CHOICES.values()))

@commands.hybrid_command(name="roulette", description="Roulette bet")
async def roulette_cmd(ctx: commands.Context, bet: int, choice: Literal["red", "black", "odd", "even"]):
    if bet <= 0:
        return await ctx.reply("❌ Bet must be positive.", mention_author=False)

    load_data()
    profile = get_user_profile(ctx.author.id)
    if bet > profile["wallet"]:
        return await ctx.reply("❌ Not enough money.", mention_author=False)

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

    await msg.edit(content=f"🎰 The wheel landed on **{result}**!\n{outcome}\n" + show_stats_text(profile))

# =========================
# BLACKJACK (hybrid, simple)
# =========================
def blackjack_draw() -> (int, int):
    return random.randint(1, 11), random.randint(1, 11)

@commands.hybrid_command(name="blackjack", description="Simple blackjack duel")
async def blackjack_cmd(ctx: commands.Context, bet: int):
    if bet <= 0:
        return await ctx.reply("❌ Bet must be positive.", mention_author=False)
    load_data()
    profile = get_user_profile(ctx.author.id)
    if bet > profile["wallet"]:
        return await ctx.reply("❌ Not enough money.", mention_author=False)

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
# LEADERBOARD (hybrid)
# =========================
@commands.hybrid_command(name="leaderboard", description="Top 10 by net worth")
async def leaderboard_cmd(ctx: commands.Context):
    load_data()
    users = _data.get("users", {})
    ranking = []
    for uid, prof in users.items():
        net = int(prof.get("wallet", 0)) + int(prof.get("bank", 0))
        ranking.append((uid, net))
    ranking.sort(key=lambda x: x[1], reverse=True)
    top = ranking[:10]
    lines = []
    for idx, (uid, net) in enumerate(top, start=1):
        member = ctx.guild.get_member(int(uid))
        if not member:
            try:
                member = await ctx.guild.fetch_member(int(uid))
            except Exception:
                member = None
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{idx}.** {name} – ${net}")
    if not lines:
        lines = ["No players yet."]
    await ctx.reply("🏆 **Leaderboard (Net Worth)**\n" + "\n".join(lines), mention_author=False)

# =========================
# ERROR HANDLING
# =========================
# Prefix/hybrid (Prefix-Seite)
@bot.event
async def on_command_error(ctx: commands.Context, error):
    try:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            return await ctx.reply("❌ You don't have permission.", mention_author=False)
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply(f"❌ Missing argument.", mention_author=False)
        if isinstance(error, commands.BadArgument):
            return await ctx.reply("❌ Invalid argument.", mention_author=False)
        await ctx.reply(f"⚠️ An error occurred: {error}", mention_author=False)
    except Exception:
        pass
    # Für Logs
    raise error

# Slash/hybrid (App-Commands-Seite)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    # Versuche, dem Nutzer eine sichtbare Fehlermeldung zu geben (ephemeral)
    try:
        content = "⚠️ An error occurred while executing the command."
        if isinstance(error, discord.app_commands.MissingPermissions):
            content = "❌ You don't have permission."
        elif isinstance(error, discord.app_commands.CommandInvokeError):
            # eigentliche Exception innen
            inner = getattr(error, "original", None)
            content = f"⚠️ Error: {inner or error}"
        elif isinstance(error, discord.app_commands.TransformError):
            content = "❌ Invalid argument."
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except Exception:
        pass
    # Zusätzlich im Log ausgeben
    print(f"[slash error] {repr(error)}")

# Optional: einfaches Logging vor jedem Command
@bot.before_invoke
async def _log_before_invoke(ctx: commands.Context):
    try:
        print(f"[CMD] {ctx.author} -> {ctx.command.qualified_name} {ctx.args[2:] if len(ctx.args)>2 else ''}")
    except Exception:
        pass
# =========================
# GIT UPDATE COMMAND
# =========================

import discord
from discord.ext import commands
import subprocess
import os
import sys

bot = commands.Bot(command_prefix="/", intents=discord.Intents.all())

@bot.command(name="gitupdate")
async def gitupdate(ctx):
    if ctx.author.id not in [1121504039146889248, 806806527192334356]:
        await ctx.send("❌ You don't have permission to run this command.")
        return

    msg = await ctx.send("📥 Downloading latest version from Git...")

    try:
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd="/root/Fish-bot",
            capture_output=True,
            text=True
        )
        reset = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd="/root/Fish-bot",
            capture_output=True,
            text=True
        )

        output = f"**Fetch output:**\n{result.stdout or result.stderr}\n"
        output += f"**Reset output:**\n{reset.stdout or reset.stderr}\n"

        await msg.edit(content="✅ Git update complete.\n" + (output[:1800] if output else "No output."))

        await ctx.send("🔄 Restarting bot with new changes...")

        # Restart bot by replacing current process
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        await msg.edit(content=f"⚠️ Error while running git update:\n```\n{e}\n```")

# =========================
# START
# =========================
if __name__ == "__main__":
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        print("[WARN] Please set DISCORD_BOT_TOKEN or paste your token in TOKEN.")
    bot.run(TOKEN)
