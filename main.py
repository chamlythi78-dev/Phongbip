from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import psycopg2  
from psycopg2 import extras
from datetime import datetime, timedelta
import os
import asyncio
import random

# HĂ m táº¡o mĂ£ ngáº«u nhiĂªn
def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [7398112999, 8619503816]
BOT_USERNAME = "zen88uytins1bot" 
MIN_WITHDRAW = 200000 

# THĂ”NG TIN Náº P TIá»€N
BANK_INFO = """
đŸ¦ **THĂ”NG TIN Náº P TIá»€N**
--------------------------
đŸ› NgĂ¢n hĂ ng: **VPBANK**
đŸ‘¤ CTK: **LUU TON DUONG**
đŸ’³ STK: `2709220899`
đŸ“ Ná»˜I DUNG CK: `{uid}`
--------------------------
â ï¸ *LÆ°u Ă½: Min náº¡p 20.000Ä‘. Báº¡n vui lĂ²ng nháº­p Ä‘Ăºng ID Ä‘á»ƒ há»‡ thá»‘ng kiá»ƒm tra nhanh nháº¥t!*
"""

# ===== DATABASE SETUP (POSTGRESQL) =====
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def query(q, args=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(q, args)
    res = None
    if cur.description:
        res = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return res

# --- KHá»I Táº O CĂC Báº¢NG ---
query("CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, reward INTEGER, uses INTEGER)")
query("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    balance BIGINT DEFAULT 0,
    refs INTEGER DEFAULT 0,
    refed INTEGER DEFAULT 0,
    bank TEXT DEFAULT NULL,
    stk TEXT DEFAULT NULL,
    name TEXT DEFAULT NULL,
    last_checkin TEXT,
    last_withdraw TEXT,
    total_bet BIGINT DEFAULT 0,
    rate_bonus INTEGER DEFAULT NULL
)
""")

query("CREATE TABLE IF NOT EXISTS game_rates (id INTEGER PRIMARY KEY, name TEXT, rate INTEGER)")

default_game_names = [
    "TĂ€I Xá»ˆU", "XĂ“C ÄÄ¨A", "ÄUA XE", "DĂ’ MĂŒN", 
    "PENALTY", "GĂ• MĂ•", "QUAY Sá»", "Báº¦U CUA"
]
for i, name in enumerate(default_game_names, 1):
    res = query("SELECT 1 FROM game_rates WHERE id=%s", (i,))
    if not res:
        query("INSERT INTO game_rates VALUES(%s, %s, 10)", (i, name))

# Äáº£m báº£o cĂ¡c cá»™t tá»“n táº¡i
try:
    query("ALTER TABLE users ADD COLUMN total_bet BIGINT DEFAULT 0")
except: pass
try:
    query("ALTER TABLE users ADD COLUMN rate_bonus INTEGER DEFAULT NULL")
except: pass

query("CREATE TABLE IF NOT EXISTS history (user_id BIGINT, amount BIGINT, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id BIGINT PRIMARY KEY)")

query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin', 
    'mt_penalty', 'mt_gomo', 'mt_nap', 'mt_rut', 
    'mt_xocdia', 'mt_quayso', 'mt_baucua'
]
for k in maintenance_keys:
    res = query("SELECT 1 FROM settings WHERE key=%s", (k,))
    if not res:
        query("INSERT INTO settings VALUES(%s, 0)", (k,))

# ===== HĂ€M KIá»‚M SOĂT Tá»ˆ Lá»† Má»I =====
def get_rate_by_id(game_id, user_id=None):
    # Æ¯u tiĂªn láº¥y tá»‰ lá»‡ riĂªng cá»§a ngÆ°á»i dĂ¹ng náº¿u cĂ³
    if user_id:
        res_user = query("SELECT rate_bonus FROM users WHERE user_id=%s", (user_id,))
        if res_user and res_user[0][0] is not None:
            return res_user[0][0]
            
    # Náº¿u khĂ´ng cĂ³ tá»‰ lá»‡ riĂªng, láº¥y tá»‰ lá»‡ chung cá»§a game
    res = query("SELECT rate FROM game_rates WHERE id=%s", (game_id,))
    return res[0][0] if res else 10

def check_win_by_id(game_id, user_id=None):
    rate = get_rate_by_id(game_id, user_id)
    return random.randint(1, 100) <= rate

def check_mt(key):
    res = query("SELECT value FROM settings WHERE key=%s", (key,))
    return res[0][0] == 1 if res else False

def get_next_multiplier(current_mult):
    if current_mult < 1.05:
        return 1.05
    elif current_mult < 1.10:
        return 1.10
    elif current_mult < 2.0:
        return round(current_mult + 0.10, 2)
    else:
        return round(current_mult + 0.20, 2)

# ===== USER UTILS =====
def get_user(uid):
    res = query("SELECT 1 FROM users WHERE user_id=%s", (uid,))
    if not res:
        query("INSERT INTO users(user_id) VALUES(%s)", (uid,))

def get_balance(uid):
    get_user(uid)
    res = query("SELECT balance FROM users WHERE user_id=%s", (uid,))
    return res[0][0] if res else 0

def is_banned(uid):
    res = query("SELECT 1 FROM banned WHERE user_id=%s", (uid,))
    return len(res) > 0 if res else False

def add_money(uid, amt, note):
    get_user(uid)
    now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
    query("UPDATE users SET balance=balance+%s WHERE user_id=%s", (amt, uid))
    query("INSERT INTO history VALUES(%s,%s,%s,%s)", (uid, amt, note, now_str))

def sub_money(uid, amt, note="withdraw"):
    get_user(uid)
    bal = get_balance(uid)
    if bal < amt:
        return False
    now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
    query("UPDATE users SET balance=balance-%s WHERE user_id=%s", (amt, uid))
    query("INSERT INTO history VALUES(%s,%s,%s,%s)", (uid, -amt, note, now_str))
    
    if note != "RĂºt tiá»n" and note != "withdraw" and "Admin" not in note:
        query("UPDATE users SET total_bet=total_bet+%s WHERE user_id=%s", (amt, uid))
    return True

# ===== NEW COMMANDS CHĂˆN THĂM =====
async def resetsdall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    query("UPDATE users SET balance = 0")
    await update.message.reply_text("âœ… ÄĂ£ xĂ³a toĂ n bá»™ sá»‘ dÆ° cá»§a táº¥t cáº£ ngÆ°á»i dĂ¹ng vá» 0!")

async def tileall_set_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not ctx.args:
        return await update.message.reply_text("âŒ CĂº phĂ¡p: `/tileall [sá»‘]`")
    try:
        new_rate = int(ctx.args[0])
        query("UPDATE game_rates SET rate = %s", (new_rate,))
        await update.message.reply_text(f"âœ… ÄĂ£ chá»‰nh táº¥t cáº£ game vá» tá»‰ lá»‡ tháº¯ng: `{new_rate}%`", parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ Tá»‰ lá»‡ pháº£i lĂ  sá»‘ nguyĂªn.")

async def tile1_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(ctx.args) < 2:
        return await update.message.reply_text("âŒ CĂº phĂ¡p: `/tile1 [ID] [Tá»‰_lá»‡]`\nVD: `/tile1 123456 10` (Chá»‰nh ID 123456 tháº¯ng 10%)")
    try:
        uid = int(ctx.args[0])
        rate = int(ctx.args[1])
        query("UPDATE users SET rate_bonus = %s WHERE user_id = %s", (rate, uid))
        await update.message.reply_text(f"âœ… ÄĂ£ Ă¡p dá»¥ng tá»‰ lá»‡ tháº¯ng `{rate}%` riĂªng cho ngÆ°á»i dĂ¹ng `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ Lá»—i dá»¯ liá»‡u nháº­p vĂ o.")

# ===== ADMIN COMMANDS =====
async def soduall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    users = query("SELECT user_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC")
    if not users:
        return await update.message.reply_text("Hiá»‡n khĂ´ng cĂ³ ai cĂ³ sá»‘ dÆ° lá»›n hÆ¡n 0.")
    
    text = "đŸ’° **DANH SĂCH Sá» DÆ¯ Táº¤T Cáº¢ ID:**\n"
    for u in users:
        text += f"ID: `{u[0]}` | Sá»‘ dÆ°: `{u[1]:,}Ä‘`\n"
    
    if len(text) > 4000:
        for x in range(0, len(text), 4000):
            await update.message.reply_text(text[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def tileall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    rates = query("SELECT id, name, rate FROM game_rates ORDER BY id ASC")
    text = "đŸ“ **Tá»ˆ Lá»† THáº®NG Táº¤T Cáº¢ GAME:**\n\n"
    for r in rates:
        text += f"đŸ†” `{r[0]}` | {r[1]}: `{r[2]}%` tháº¯ng\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def xoalsall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    query("DELETE FROM history")
    await update.message.reply_text("âœ… ÄĂ£ xoĂ¡ toĂ n bá»™ lá»‹ch sá»­ cÆ°á»£c, náº¡p vĂ  rĂºt cá»§a há»‡ thá»‘ng!")

async def xoals_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not ctx.args:
        return await update.message.reply_text("âŒ CĂº phĂ¡p: `/xoals [ID]`")
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM history WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"âœ… ÄĂ£ xoĂ¡ sáº¡ch lá»‹ch sá»­ cá»§a ngÆ°á»i dĂ¹ng: `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ ID khĂ´ng há»£p lá»‡.")

# ===== LOGIC GAMES ANIMATION =====
async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    track_length = 12
    pos_a, pos_b = 0, 0
    finish_line = "đŸ"
    
    msg = await ctx.bot.send_message(uid, "đŸ¦ **Sáº´N SĂ€NG...**")
    await asyncio.sleep(1)
    await msg.edit_text("đŸđŸ’¨ **XUáº¤T PHĂT!!!**")

    is_win = check_win_by_id(3, uid) # ID 3 ÄUA XE
    target_winner = choice if is_win else ("B" if choice == "A" else "A")

    while pos_a < track_length and pos_b < track_length:
        boost_a = random.randint(1, 3)
        boost_b = random.randint(1, 3)
        
        if target_winner == "A" and pos_a >= 8: boost_a = 4
        if target_winner == "B" and pos_b >= 8: boost_b = 4

        pos_a = min(pos_a + boost_a, track_length)
        pos_b = min(pos_b + boost_b, track_length)
        
        if pos_a == track_length and pos_b == track_length:
            if target_winner == "A": pos_b -= 1
            else: pos_a -= 1

        line_a = "â€”" * pos_a + "đŸï¸" + " " * (track_length - pos_a) + finish_line + " **(A)**"
        line_b = "â€”" * pos_b + "đŸï¸" + " " * (track_length - pos_b) + finish_line + " **(B)**"
        
        try:
            await msg.edit_text(f"đŸï¸ **ÄUA XE SIĂU Cáº¤P**\n\n`{line_a}`\n`{line_b}`", parse_mode="Markdown")
            await asyncio.sleep(0.8)
        except: pass

    winner = target_winner
    win = (choice == winner)
    
    if win:
        win_amt = int(amt * 1.95)
        add_money(uid, win_amt, f"Tháº¯ng Ä‘ua xe {winner}")
        res_text = f"đŸ‰ **CHIáº¾N THáº®NG!** Xe **{winner}** vá» nháº¥t!\nđŸ’° Nháº­n: `+{win_amt:,}Ä‘`"
    else:
        res_text = f"đŸ’€ **THáº¤T Báº I!** Xe **{winner}** Ä‘Ă£ tháº¯ng cuá»™c."

    await ctx.bot.send_message(uid, f"{res_text}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", parse_mode="Markdown")

async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"CÆ°á»£c {choice_code}"):
        return await update.message.reply_text("âŒ Báº¡n khĂ´ng Ä‘á»§ sá»‘ dÆ°.")

    msg_status = await update.message.reply_text("đŸ² **ÄANG Láº®C XĂC Xáº®C...**", parse_mode="Markdown")
    
    d1 = await update.message.reply_dice(emoji="đŸ²")
    d2 = await update.message.reply_dice(emoji="đŸ²")
    d3 = await update.message.reply_dice(emoji="đŸ²")
    
    results = [d1.dice.value, d2.dice.value, d3.dice.value]
    total = sum(results)
    
    c = choice_code.upper()
    is_chan, is_tai = (total % 2 == 0), (total >= 11)
    is_win = check_win_by_id(1, uid)
    
    win = False
    if is_win:
        if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or \
           (c == "XXX" and not is_tai) or (c == "XXT" and is_tai):
            win = True
    else:
        win = False 

    await asyncio.sleep(4)

    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Tháº¯ng {c}")
        status = f"âœ… **THáº®NG** | Nháº­n: `+{win_amt:,}Ä‘`"
    else: 
        status = f"âŒ **THUA**"
    
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"đŸ² Káº¿t quáº£: **{res_str}** => **{total}**\n{status}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", parse_mode="Markdown")

async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args:
        await update.message.reply_text("âŒ Vui lĂ²ng nháº­p kĂ¨m mĂ£. VD: `/code ABC123`")
        return
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=%s", (code_str,))
    if not data:
        await update.message.reply_text("âŒ MĂ£ quĂ  táº·ng khĂ´ng tá»“n táº¡i.")
        return
    reward, uses = data[0][1], data[0][2]
    if uses <= 0:
        await update.message.reply_text("âŒ MĂ£ quĂ  táº·ng nĂ y Ä‘Ă£ háº¿t lÆ°á»£t sá»­ dá»¥ng.")
        return
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=%s", (code_str,))
    await update.message.reply_text(f"đŸ‰ **NHáº¬N QUĂ€ THĂ€NH CĂ”NG!**\n\nđŸ’° Báº¡n nháº­n Ä‘Æ°á»£c: `+{reward:,}Ä‘`", parse_mode="Markdown")

# ===== ADMIN COMMANDS (CONT) =====
async def tilewin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        game_id = int(ctx.args[0])
        new_rate = int(ctx.args[1])
        if not (0 <= new_rate <= 100):
            return await update.message.reply_text("âŒ Tá»‰ lá»‡ tháº¯ng pháº£i tá»« 0% Ä‘áº¿n 100%!")
        query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
        res = query("SELECT name FROM game_rates WHERE id=%s", (game_id,))
        game_name = res[0][0] if res else "KhĂ´ng xĂ¡c Ä‘á»‹nh"
        await update.message.reply_text(
            f"âœ… **Cáº¬P NHáº¬T Tá»ˆ Lá»† THĂ€NH CĂ”NG**\n\n"
            f"đŸ® Game: `{game_id} - {game_name}`\n"
            f"đŸ“ˆ Tá»‰ lá»‡ tháº¯ng má»›i: `{new_rate}%`", 
            parse_mode="Markdown"
        )
    except:
        msg = (
            "â ï¸ **HÆ¯á»NG DáºªN CHá»ˆNH Tá»ˆ Lá»†**\n"
            "CĂº phĂ¡p: `/tilewin [Sá»‘_ID] [Tá»‰_lá»‡]`\n\n"
            "1. TĂ€I Xá»ˆU\n2. XĂ“C ÄÄ¨A\n3. ÄUA XE\n4. DĂ’ MĂŒN\n"
            "5. PENALTY\n6. GĂ• MĂ•\n7. QUAY Sá»\n8. Báº¦U CUA\n\n"
            "VD: `/tilewin 1 50` (Chá»‰nh TĂ i Xá»‰u tháº¯ng 50%)"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    def st(k): return "đŸ”´ OFF" if check_mt(k) else "đŸŸ¢ ON"
    kb = [
        [InlineKeyboardButton(f"đŸ² TĂ i Xá»‰u 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"đŸ’¿ XĂ³c ÄÄ©a: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
        [InlineKeyboardButton(f"đŸ Äua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), 
         InlineKeyboardButton(f"đŸ’£ DĂ² MĂ¬n: {st('mt_domin')}", callback_data="tg_mt_domin")],
        [InlineKeyboardButton(f"â½ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"), 
         InlineKeyboardButton(f"đŸªµ GĂµ MĂµ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
        [InlineKeyboardButton(f"đŸ”¢ Quay Sá»‘: {st('mt_quayso')}", callback_data="tg_mt_quayso"),
         InlineKeyboardButton(f"đŸ¦€ Báº§u Cua: {st('mt_baucua')}", callback_data="tg_mt_baucua")], 
        [InlineKeyboardButton(f"đŸ’³ Náº¡p Tiá»n: {st('mt_nap')}", callback_data="tg_mt_nap"), 
         InlineKeyboardButton(f"đŸ›’ RĂºt Tiá»n: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("âŒ ÄĂ“NG Báº¢NG", callback_data="close_admin")]
    ]
    await update.message.reply_text("đŸ›  **Báº¢NG QUáº¢N LĂ Báº¢O TRĂŒ**\n(Báº¥m Ä‘á»ƒ chuyá»ƒn tráº¡ng thĂ¡i On/Off)", 
                                   reply_markup=InlineKeyboardMarkup(kb))

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        add_money(target_id, amount, f"Admin náº¡p tiá»n")
        await update.message.reply_text(f"âœ… **Náº P TIá»€N THĂ€NH CĂ”NG**\n\nđŸ‘¤ ID: `{target_id}`\nđŸ’° Sá»‘ tiá»n: `+{amount:,}Ä‘`", parse_mode="Markdown")
        bill = (
            f"đŸ’³ **BIáº¾N Äá»˜NG Sá» DÆ¯**\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"TĂ i khoáº£n cá»§a báº¡n vá»«a nháº­n Ä‘Æ°á»£c tiá»n tá»« há»‡ thá»‘ng.\n\n"
            f"đŸ“¥ **Sá»‘ tiá»n:** `+{amount:,}Ä‘`\n"
            f"đŸ“ **Ná»™i dung:** Náº¡p tiá»n há»‡ thá»‘ng\n"
            f"â° **Thá»i gian:** {datetime.now().strftime('%H:%M - %d/%m/%Y')}\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"đŸ’° Sá»‘ dÆ° hiá»‡n táº¡i: `{get_balance(target_id):,}Ä‘`"
        )
        try:
            await ctx.bot.send_message(chat_id=target_id, text=bill, parse_mode="Markdown")
        except: pass
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/nap [ID] [Sá»‘ tiá»n]`")

async def reset_all_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("âœ… XĂC NHáº¬N XĂ“A Táº¤T Cáº¢", callback_data="confirm_reset_all_final")],
        [InlineKeyboardButton("âŒ Há»¦Y THAO TĂC", callback_data="close_admin")]
    ])
    await update.message.reply_text(
        "â ï¸ **Cáº¢NH BĂO NGUY HIá»‚M** â ï¸\n\n"
        "Thao tĂ¡c nĂ y sáº½ xĂ³a sáº¡ch dá»¯ liá»‡u cĂ¡c báº£ng: **Users, History, Codes, Banned**.\n"
        "Má»i thĂ´ng tin sá»‘ dÆ° vĂ  lá»‹ch sá»­ sáº½ biáº¿n máº¥t vÄ©nh viá»…n.\n\n"
        "Báº¡n cĂ³ cháº¯c cháº¯n muá»‘n thá»±c hiá»‡n?", reply_markup=kb, parse_mode="Markdown")

async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=%s", (target_id,))
        await update.message.reply_text(f"âœ… ÄĂ£ reset bank cho ID `{target_id}`. User cĂ³ thá»ƒ dĂ¹ng /lienket láº¡i.")
        await ctx.bot.send_message(chat_id=target_id, text="đŸ”” Admin Ä‘Ă£ reset thĂ´ng tin ngĂ¢n hĂ ng cá»§a báº¡n. Báº¡n cĂ³ thá»ƒ liĂªn káº¿t láº¡i ngay bĂ¢y giá».")
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/resetbank [ID]`")

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        res = query("SELECT balance, refs, bank, stk, name, last_checkin, total_bet FROM users WHERE user_id=%s", (target_id,))
        if not res:
            return await update.message.reply_text("âŒ KhĂ´ng tĂ¬m tháº¥y ngÆ°á»i dĂ¹ng nĂ y.")
        u = res[0]
        msg = (
            f"đŸ“‚ **THĂ”NG TIN CHI TIáº¾T USER `{target_id}`**\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"đŸ’° Sá»‘ dÆ°: `{u[0]:,}Ä‘`\n"
            f"đŸ“ Tá»•ng cÆ°á»£c: `{u[6]:,}Ä‘`\n"
            f"đŸ‘¥ Sá»‘ ngÆ°á»i má»i: `{u[1]}`\n"
            f"đŸ› NgĂ¢n hĂ ng: `{u[2] or 'ChÆ°a cáº­p nháº­t'}`\n"
            f"đŸ’³ Sá»‘ tĂ i khoáº£n: `{u[3] or 'ChÆ°a cáº­p nháº­t'}`\n"
            f"đŸ‘¤ TĂªn chá»§ tháº»: `{u[4] or 'ChÆ°a cáº­p nháº­t'}`\n"
            f"đŸ“… Äiá»ƒm danh gáº§n nháº¥t: `{u[5] or 'ChÆ°a cĂ³'}`\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/info [ID]`")

async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(%s,%s,%s)", (code, reward, uses))
        await update.message.reply_text(f"âœ… **Táº O CODE THĂ€NH CĂ”NG**\n\nđŸ Code: `{code}`\nđŸ’° ThÆ°á»Ÿng: `{reward:,}Ä‘`\nđŸ”„ LÆ°á»£t: `{uses}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/taocode [sá»‘ tiá»n] [lÆ°á»£t dĂ¹ng]`")

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cá»™ng tiá»n")
        await update.message.reply_text(f"âœ… ÄĂ£ cá»™ng `{amt:,}Ä‘` cho ID `{uid}`")
    except: pass

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt, "Admin trá»« tiá»n")
        await update.message.reply_text(f"âœ… ÄĂ£ trá»« `{amt:,}Ä‘` cá»§a ID `{uid}`")
    except: pass

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        query("INSERT INTO banned(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (uid,))
        await update.message.reply_text(f"đŸ« ÄĂ£ cháº·n ngÆ°á»i dĂ¹ng `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"âœ… ÄĂ£ bá» cháº·n ngÆ°á»i dĂ¹ng `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    res = query("SELECT COUNT(*) FROM users")
    total = res[0][0] if res else 0
    await update.message.reply_text(f"đŸ“ **THá»NG KĂ:**\n\nđŸ‘¥ Tá»•ng sá»‘ ngÆ°á»i dĂ¹ng: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page=0):
    if update.effective_user.id not in ADMIN_IDS: return
    limit = 20
    offset = page * limit
    users = query("SELECT user_id, balance FROM users ORDER BY user_id DESC LIMIT %s OFFSET %s", (limit, offset))
    res_total = query("SELECT COUNT(*) FROM users")
    total_users = res_total[0][0] if res_total else 0
    total_pages = (total_users + limit - 1) // limit

    if not users:
        return await update.message.reply_text("ChÆ°a cĂ³ ngÆ°á»i dĂ¹ng nĂ o.")

    kb = []
    for u in users:
        u_id, bal = u[0], u[1]
        status = "đŸ«" if is_banned(u_id) else "đŸŸ¢"
        kb.append([InlineKeyboardButton(f"{status} ID: {u_id} | {bal:,}Ä‘", callback_data=f"adm_manage_{u_id}_{page}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("â¬…ï¸ TrÆ°á»›c", callback_data=f"adm_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"Trang {page+1}/{total_pages}", callback_data="none"))
    if (page + 1) < total_pages:
        nav_buttons.append(InlineKeyboardButton("Sau â¡ï¸", callback_data=f"adm_page_{page+1}"))
    kb.append(nav_buttons)
    kb.append([InlineKeyboardButton("âŒ ÄĂ“NG Báº¢NG", callback_data="close_admin")])

    text = f"đŸ‘¥ **DANH SĂCH NGÆ¯á»œI DĂ™NG** (Tá»•ng: {total_users})\nBáº¥m vĂ o User Ä‘á»ƒ xem chi tiáº¿t:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    data = query("SELECT * FROM history ORDER BY time DESC LIMIT 50") 
    msg = "đŸŒ **Lá»CH Sá»¬ TOĂ€N Há»† THá»NG:**\n\n"
    if data:
        for d in data:
            msg += f"đŸ‘¤ `{d[0]}` | `{d[1]:,}Ä‘` | {d[2]}\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000):
            await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg or "Trá»‘ng", parse_mode="Markdown")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not ctx.args:
        return await update.message.reply_text("âŒ CĂº phĂ¡p: `/send [ná»™i dung]`")
    msg_to_send = " ".join(ctx.args)
    users = query("SELECT user_id FROM users")
    sent, failed = 0, 0
    status_msg = await update.message.reply_text(f"đŸ€ Äang gá»­i tá»›i {len(users)} ngÆ°á»i...")
    for user in users:
        try:
            await ctx.bot.send_message(chat_id=user[0], text=f"đŸ”” **THĂ”NG BĂO Má»I**\n\n{msg_to_send}", parse_mode="Markdown")
            sent += 1
            if sent % 20 == 0: await asyncio.sleep(1)
        except: failed += 1
    await status_msg.edit_text(f"âœ… **HOĂ€N THĂ€NH**\n\nđŸ“ ThĂ nh cĂ´ng: `{sent}`\nâŒ Tháº¥t báº¡i: `{failed}`")

async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"âœ‰ï¸ **PHáº¢N Há»’I Tá»ª ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"âœ… ÄĂ£ gá»­i pháº£n há»“i tá»›i `{uid}`")
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/rep [ID] [Ná»™i dung]`")

async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC", (uid,))
        if not data:
            await update.message.reply_text(f"đŸ“¥ User `{uid}` chÆ°a cĂ³ giao dá»‹ch.")
        else:
            msg = f"đŸ“œ **Lá»CH Sá»¬ USER `{uid}`:**\n\n"
            for d in data:
                msg += f"đŸ’° `{d[0]:,}` | {d[1]} | _{d[2]}_\n" 
            if len(msg) > 4000:
                for x in range(0, len(msg), 4000):
                    await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
            else:
                await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("âŒ CĂº phĂ¡p: `/check [ID]`")

# ===== START & REF SYSTEM =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    get_user(uid)

    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=%s", (uid,))
                if row and row[0][0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=%s", (ref,)):
                        add_money(ref, 500, "Ref bonus") 
                        query("UPDATE users SET refs=refs+1 WHERE user_id=%s", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=%s", (uid,))
        except: pass

    menu = ReplyKeyboardMarkup([
        ["đŸ® Danh sĂ¡ch game", "đŸ‘¤ TĂ i khoáº£n"],
        ["đŸ’³ Náº¡p tiá»n", "đŸ›’ RĂºt tiá»n"],
        ["đŸ Checkin", "đŸ Nháº­n Code Free"],
        ["đŸ“œ Lá»‹ch sá»­", "đŸ“ Há»— trá»£"]
    ], resize_keyboard=True)

    welcome_text = (
        f"đŸ‘‹ **CHĂ€O Má»ªNG {update.effective_user.first_name.upper()} ÄĂƒ THAM GIA!**\n\n"
        f"Há»‡ thá»‘ng trĂ² chÆ¡i minh báº¡ch â€” uy tĂ­n hĂ ng Ä‘áº§u.\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"đŸ’° **MIN RĂT TIá»€N:** `{MIN_WITHDRAW:,}Ä‘`\n" 
        f"đŸ’³ **MIN Náº P TIá»€N:** `20.000Ä‘`\n"
        f"â ï¸ *LÆ°u Ă½: Náº¡p dÆ°á»›i 20k sáº½ khĂ´ng Ä‘Æ°á»£c tá»± Ä‘á»™ng duyá»‡t.*\n\n"
        f"â–ï¸ **CAM Káº¾T MINH Báº CH:**\n"
        f"â€¢ **100%** Káº¿t quáº£ hoĂ n toĂ n ngáº«u nhiĂªn.\n"
        f"â€¢ đŸ”„ **KHĂ”NG** can thiá»‡p káº¿t quáº£ dÆ°á»›i má»i hĂ¬nh thá»©c.\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"đŸ€ ChĂºc báº¡n cĂ³ nhá»¯ng tráº£i nghiá»‡m may máº¯n vĂ  thĂº vá»‹!"
    )
    await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode="Markdown")

async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    res = query("SELECT bank FROM users WHERE user_id=%s", (uid,))
    if res and res[0][0] is not None:
        return await update.message.reply_text("âŒ Báº¡n Ä‘Ă£ liĂªn káº¿t ngĂ¢n hĂ ng rá»“i. Äá»ƒ thay Ä‘á»•i, vui lĂ²ng liĂªn há»‡ Admin!", parse_mode="Markdown")
    if not ctx.args or len(ctx.args) < 3:
        return await update.message.reply_text("â ï¸ **CĂº phĂ¡p liĂªn káº¿t:**\n`/lienket [NgĂ¢n_hĂ ng] [STK] [Chá»§_TK]`\n\nVD: `/lienket MBBANK 0123456 NGUYEN VAN A`", parse_mode="Markdown")
    bank = ctx.args[0].upper()
    stk = ctx.args[1]
    name = " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=%s, stk=%s, name=%s WHERE user_id=%s", (bank, stk, name, uid))
    await update.message.reply_text(f"âœ… **LIĂN Káº¾T THĂ€NH CĂ”NG**\n\nđŸ› NgĂ¢n hĂ ng: {bank}\nđŸ’³ STK: `{stk}`\nđŸ‘¤ Chá»§ TK: {name}\n\nâ ï¸ *ThĂ´ng tin nĂ y Ä‘Ă£ Ä‘Æ°á»£c khĂ³a Ä‘á»ƒ báº£o máº­t.*", parse_mode="Markdown")

async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if check_mt('mt_rut') and uid not in ADMIN_IDS:
        return await update.message.reply_text("â™ï¸ Há»‡ thá»‘ng RĂºt Tiá»n Ä‘ang báº£o trĂ¬, vui lĂ²ng quay láº¡i sau!")
        
    res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
    if not res or not res[0][0] or not res[0][1]:
        return await update.message.reply_text("âŒ Báº¡n chÆ°a liĂªn káº¿t tĂ i khoáº£n ngĂ¢n hĂ ng.\nđŸ‘‰ HĂ£y dĂ¹ng lá»‡nh: `/lienket [NgĂ¢n_hĂ ng] [STK] [TĂªn]`", parse_mode="Markdown")
    u = res[0]
    if not ctx.args:
        return await update.message.reply_text(f"đŸ’° Sá»‘ dÆ°: `{u[3]:,}`Ä‘\nâ ï¸ Nháº­p sá»‘ tiá»n muá»‘n rĂºt: `/rut [sá»‘ tiá»n]`", parse_mode="Markdown")
    try:
        amount = int(ctx.args[0])
        if amount < MIN_WITHDRAW:
            return await update.message.reply_text(f"âŒ Min rĂºt `{MIN_WITHDRAW:,}Ä‘`")
        if sub_money(uid, amount, "RĂºt tiá»n"):
            bank, stk, name = u[0], u[1], u[2]
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("âœ… Duyá»‡t", callback_data=f"ok_{uid}_{amount}"),
                InlineKeyboardButton("âŒ Tá»« chá»‘i", callback_data=f"no_{uid}_{amount}")
            ]])
            await ctx.bot.send_message(ADMIN_IDS[0], f"đŸ”” **YĂU Cáº¦U RĂT TIá»€N**\n\nđŸ‘¤ ID: `{uid}`\nđŸ’° `{amount:,}Ä‘`\nđŸ› `{bank} | {stk} | {name}`", reply_markup=keyboard, parse_mode="Markdown")
            await update.message.reply_text("âœ… Gá»­i yĂªu cáº§u rĂºt tiá»n thĂ nh cĂ´ng! Vui lĂ²ng chá» duyá»‡t.")
        else:
            await update.message.reply_text("âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
    except: 
        await update.message.reply_text("âŒ Sá»‘ tiá»n khĂ´ng há»£p lá»‡.")

async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC LIMIT 20", (uid,))
    if not data:
        await update.message.reply_text("đŸ“¥ Lá»‹ch sá»­ trá»‘ng.")
    else:
        msg = "đŸ“œ **Lá»CH Sá»¬ CHI TIáº¾T:**\n\n"
        for d in data:
            icon = "â•" if d[0] > 0 else "â–"
            msg += f"{icon} `{d[0]:,}Ä‘` | {d[1]} | _{d[2]}_\n"
        if len(msg) > 4000:
            for x in range(0, len(msg), 4000):
                await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

# ===== HANDLE MENU MESSAGES =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    user_reply = update.message
    parts = txt.split()

    if txt == "đŸ‘¤ TĂ i khoáº£n":
        res = query("SELECT balance, bank, stk, name, refs, total_bet FROM users WHERE user_id=%s", (uid,))
        if not res: 
            get_user(uid)
            u = (0, None, None, None, 0, 0)
        else:
            u = res[0]
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("đŸ“¥ Lá»‹ch sá»­ Náº¡p", callback_data="his_deposit"),
             InlineKeyboardButton("đŸ“¤ Lá»‹ch sá»­ RĂºt", callback_data="his_withdraw")]
        ])

        msg = (
            f"đŸ‘¤ **THĂ”NG TIN TĂ€I KHOáº¢N**\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"đŸ†” ID: `{uid}`\n"
            f"đŸ’° Sá»‘ dÆ°: `{u[0]:,}Ä‘`\n"
            f"đŸ“ **Tá»•ng cÆ°á»£c:** `{u[5]:,}Ä‘`\n"
            f"đŸ‘¥ ÄĂ£ má»i: `{u[4]}` ngÆ°á»i\n"
            f"đŸ› NgĂ¢n hĂ ng: `{u[1] or 'ChÆ°a liĂªn káº¿t'}`\n"
            f"đŸ’³ STK: `{u[2] or 'ChÆ°a liĂªn káº¿t'}`\n"
            f"đŸ‘¤ TĂªn: `{u[3] or 'ChÆ°a liĂªn káº¿t'}`\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"đŸ’¡ *Sá»­ dá»¥ng lá»‡nh /lienket Ä‘á»ƒ cáº­p nháº­t thĂ´ng tin rĂºt tiá»n!*"
        )
        return await user_reply.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    if txt == "đŸ Nháº­n Code Free":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("đŸ“º THAM GIA NHĂ“M NHáº¬N CODE", url="https://t.me/zen88cltxtele")],
            [InlineKeyboardButton("đŸ“¢ KĂNH THĂ”NG BĂO", url="https://t.me/hocvienthanbai5")]
        ])
        msg = (
            "đŸ **NHáº¬N GIFTCODE MIá»„N PHĂ**\n\n"
            "Tham gia cĂ¡c nhĂ³m dÆ°á»›i Ä‘Ă¢y Ä‘á»ƒ sÄƒn mĂ£ Code thÆ°á»Ÿng má»—i ngĂ y tá»« Admin!\n\n"
            "đŸ“– **CĂCH NHáº¬P CODE:**\n"
            "GĂµ lá»‡nh: `/code [mĂ£_quĂ _táº·ng]`\n"
            "VĂ­ dá»¥: `/code VUAVIP2024`\n\n"
            "đŸ‘‡ **Tham gia ngay táº¡i Ä‘Ă¢y:**"
        )
        return await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)

    if txt == "đŸ’³ Náº¡p tiá»n":
        if check_mt('mt_nap') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("â™ï¸ Há»‡ thá»‘ng Náº¡p Tiá»n Ä‘ang báº£o trĂ¬!")
        return await user_reply.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")

    if txt == "đŸ® Danh sĂ¡ch game":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("đŸ² TĂ€I Xá»ˆU 3D", callback_data="menu_tx"), InlineKeyboardButton("đŸ’¿ XĂ“C ÄÄ¨A", callback_data="menu_xocdia")],
            [InlineKeyboardButton("đŸï¸ ÄUA XE (RACE)", callback_data="menu_race"), 
             InlineKeyboardButton("đŸ’£ DĂ² MĂ¬n", callback_data="menu_mines")],
            [InlineKeyboardButton("â½ï¸ PENALTY", callback_data="menu_ball"), 
             InlineKeyboardButton("đŸªµ GĂ• MĂ•", callback_data="menu_wooden")],
            [InlineKeyboardButton("đŸ”¢ QUAY Sá» (1-3)", callback_data="menu_qs"),
             InlineKeyboardButton("đŸ¦€ Báº¦U CUA TĂ”M CĂ", callback_data="menu_bc")]
        ])
        return await user_reply.reply_text("đŸ® **DANH SĂCH TRĂ’ CHÆ I**\nVui lĂ²ng chá»n game báº¡n muá»‘n chÆ¡i:", reply_markup=kb, parse_mode="Markdown")

    if txt == "đŸ›’ RĂºt tiá»n":
        if check_mt('mt_rut') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("â™ï¸ Há»‡ thá»‘ng RĂºt Tiá»n Ä‘ang báº£o trĂ¬!")
        res = query("SELECT bank, stk, name FROM users WHERE user_id=%s", (uid,))
        if not res or not res[0][0] or not res[0][1]:
            await user_reply.reply_text("âŒ Báº¡n chÆ°a liĂªn káº¿t bank.\nđŸ‘‰ DĂ¹ng lá»‡nh: `/lienket [Bank] [STK] [TĂªn]`", parse_mode="Markdown")
        else:
            u = res[0]
            await user_reply.reply_text(f"đŸ› **TĂ€I KHOáº¢N RĂT:**\nđŸ› Bank: {u[0]}\nđŸ’³ STK: `{u[1]}`\nđŸ‘¤ TĂªn: {u[2]}\n\nđŸ‘‰ Nháº­p: `/rut [sá»‘ tiá»n]`", parse_mode="Markdown")
        return

    if txt == "đŸ Checkin":
        today = datetime.now().strftime("%d/%m/%Y")
        res = query("SELECT last_checkin FROM users WHERE user_id=%s", (uid,))
        if res and res[0][0] == today:
            await user_reply.reply_text("âŒ HĂ´m nay báº¡n Ä‘Ă£ Ä‘iá»ƒm danh rá»“i!")
            return
        add_money(uid, 300, "Daily Checkin") 
        query("UPDATE users SET last_checkin=%s WHERE user_id=%s", (today, uid))
        return await user_reply.reply_text("đŸ‰ **CHECKIN THĂ€NH CĂ”NG!**\n\nBáº¡n nháº­n Ä‘Æ°á»£c: `+300Ä‘`", parse_mode="Markdown")

    if txt == "đŸ“œ Lá»‹ch sá»­":
        return await history_pro(update, ctx)

    if txt == "đŸ“ Há»— trá»£":
        return await user_reply.reply_text("đŸ“© Gá»­i ná»™i dung cáº§n há»— trá»£ ngay táº¡i Ä‘Ă¢y, Admin sáº½ pháº£n há»“i sá»›m! Hoáº·c NT CHO @cskhzen88uytin")

    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]:
            if check_mt('mt_taixiu') and uid not in ADMIN_IDS:
                return await update.message.reply_text("â™ï¸ Game TĂ i Xá»‰u Ä‘ang báº£o trĂ¬!")
            return await play_dice_animation(update, code, amt)

    if uid not in ADMIN_IDS:
        for aid in ADMIN_IDS:
            try: await ctx.bot.send_message(chat_id=aid, text=f"đŸ“¨ **TIN NHáº®N Há»– TRá»¢**\nđŸ‘¤ ID: `{uid}`\nđŸ“ Ná»™i dung: {txt}", parse_mode="Markdown")
            except: pass
        await user_reply.reply_text("âœ… ÄĂ£ gá»­i yĂªu cáº§u tá»›i Admin!")

# ===== CALLBACK HANDLER (GAMES & WITHDRAW) =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    
    if d == "confirm_reset_all_final":
        if uid not in ADMIN_IDS: return
        query("TRUNCATE users, history, codes, banned RESTART IDENTITY CASCADE")
        return await q.edit_message_text("âœ… **Há»† THá»NG ÄĂƒ ÄÆ¯á»¢C RESET Sáº CH Dá»® LIá»†U!**")

    elif d == "his_deposit":
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s AND amount > 0 ORDER BY time DESC LIMIT 10", (uid,))
        text = "đŸ“¥ **10 GIAO Dá»CH Náº P Gáº¦N NHáº¤T:**\n\n"
        if not data: text += "Trá»‘ng."
        else:
            for row in data: text += f"âœ… `+{row[0]:,}Ä‘` | {row[1]} | _{row[2]}_\n"
        return await ctx.bot.send_message(uid, text, parse_mode="Markdown")

    elif d == "his_withdraw":
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s AND (note ILIKE '%%RĂºt%%' OR amount < 0) ORDER BY time DESC LIMIT 10", (uid,))
        text = "đŸ“¤ **10 GIAO Dá»CH RĂT/CÆ¯á»¢C Gáº¦N NHáº¤T:**\n\n"
        if not data: text += "Trá»‘ng."
        else:
            for row in data: text += f"đŸ”» `{abs(row[0]):,}Ä‘` | {row[1]} | _{row[2]}_\n"
        return await ctx.bot.send_message(uid, text, parse_mode="Markdown")

    if d.startswith("adm_page_"):
        if uid not in ADMIN_IDS: return
        new_page = int(d.split("_")[2])
        await all_user(update, ctx, page=new_page)
        return

    if d.startswith("adm_manage_"):
        if uid not in ADMIN_IDS: return
        parts = d.split("_")
        target_id = int(parts[2])
        current_page = int(parts[3]) if len(parts) > 3 else 0
        
        res = query("SELECT balance, refs, bank, stk, name, last_checkin, total_bet FROM users WHERE user_id=%s", (target_id,))
        if not res: return await q.answer("KhĂ´ng tĂ¬m tháº¥y user!")
        u = res[0]
        
        status_text = "đŸ« ÄANG CHáº¶N" if is_banned(target_id) else "đŸŸ¢ HOáº T Äá»˜NG"
        msg = (
            f"đŸ‘¤ **QUáº¢N LĂ USER:** `{target_id}`\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"đŸ’° Sá»‘ dÆ°: `{u[0]:,}Ä‘`\n"
            f"đŸ“ Tá»•ng cÆ°á»£c: `{u[6]:,}Ä‘`\n"
            f"đŸ› Bank: `{u[2] or 'ChÆ°a'}` | `{u[3] or ''}`\n"
            f"đŸ¦ Tráº¡ng thĂ¡i: **{status_text}**\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”"
        )
        
        kb = [
            [InlineKeyboardButton("đŸ« BAN", callback_data=f"adm_act_ban_{target_id}_{current_page}"), 
             InlineKeyboardButton("âœ… UNBAN", callback_data=f"adm_act_unban_{target_id}_{current_page}")],
            [InlineKeyboardButton("â• 0k", callback_data=f"adm_act_add_{target_id}_0_{current_page}"), 
             InlineKeyboardButton("â– 0k", callback_data=f"adm_act_sub_{target_id}_0_{current_page}")],
            [InlineKeyboardButton("đŸ”™ QUAY Láº I TRANG {0}".format(current_page+1), callback_data=f"adm_page_{current_page}")]
        ]
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("adm_act_"):
        if uid not in ADMIN_IDS: return
        parts = d.split("_")
        act = parts[2]
        tid = int(parts[3])
        page_to_return = int(parts[-1])
        
        if act == "ban": query("INSERT INTO banned VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (tid,))
        elif act == "unban": query("DELETE FROM banned WHERE user_id=%s", (tid,))
        elif act == "add": add_money(tid, int(parts[4]), "Admin cá»™ng tiá»n")
        elif act == "sub": sub_money(tid, int(parts[4]), "Admin trá»« tiá»n")
        
        await q.answer("ThĂ nh cĂ´ng!")
        q.data = f"adm_manage_{tid}_{page_to_return}"
        return await handle_callback(update, ctx)

    if d.startswith("tg_mt_"):
        if uid not in ADMIN_IDS: return
        key = d.replace("tg_", "")
        new_val = 0 if check_mt(key) else 1
        query("UPDATE settings SET value=%s WHERE key=%s", (new_val, key))
        def st(k): return "đŸ”´ OFF" if check_mt(k) else "đŸŸ¢ ON"
        new_kb = [
            [InlineKeyboardButton(f"đŸ² TĂ i Xá»‰u 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
            [InlineKeyboardButton(f"đŸ’¿ XĂ³c ÄÄ©a: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
            [InlineKeyboardButton(f"đŸ Äua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), 
             InlineKeyboardButton(f"đŸ’£ DĂ² MĂ¬n: {st('mt_domin')}", callback_data="tg_mt_domin")],
            [InlineKeyboardButton(f"â½ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty")], 
            [InlineKeyboardButton(f"đŸªµ GĂµ MĂµ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
            [InlineKeyboardButton(f"đŸ”¢ Quay Sá»‘: {st('mt_quayso')}", callback_data="tg_mt_quayso")],
            [InlineKeyboardButton(f"đŸ¦€ Báº§u Cua: {st('mt_baucua')}", callback_data="tg_mt_baucua")],
            [InlineKeyboardButton(f"đŸ’³ Náº¡p Tiá»n: {st('mt_nap')}", callback_data="tg_mt_nap")], 
            [InlineKeyboardButton(f"đŸ›’ RĂºt Tiá»n: {st('mt_rut')}", callback_data="tg_mt_rut")],
            [InlineKeyboardButton("âŒ ÄĂ“NG Báº¢NG", callback_data="close_admin")]
        ]
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
        await q.answer("ÄĂ£ cáº­p nháº­t tráº¡ng thĂ¡i!")
        return

    if d == "close_admin":
        await q.message.delete()
        return

    await q.answer()
    amounts = [1000, 5000, 10000, 50000, 100000, 200000, 500000, 1000000]

    if d.startswith(("ok_", "no_")):
        if uid not in ADMIN_IDS: return
        act, u_id, amt = d.split("_")
        u_id, amt = int(u_id), int(amt)
        if act == "ok":
            await ctx.bot.send_message(u_id, f"âœ… YĂªu cáº§u rĂºt `{amt:,}Ä‘` Ä‘Ă£ Ä‘Æ°á»£c duyá»‡t!")
            await q.edit_message_text(f"âœ… ÄĂƒ DUYá»†T ID {u_id}")
        else:
            add_money(u_id, amt, "HoĂ n tiá»n rĂºt")
            await ctx.bot.send_message(u_id, "âŒ YĂªu cáº§u rĂºt tiá»n bá»‹ tá»« chá»‘i. Tiá»n Ä‘Ă£ Ä‘Æ°á»£c hoĂ n láº¡i.")
            await q.edit_message_text(f"âŒ Tá»ª CHá»I ID {u_id}")

    # ===== GAME Báº¦U CUA =====
    elif d == "menu_bc":
        if check_mt('mt_baucua') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "â™ï¸ Game Báº§u Cua Ä‘ang báº£o trĂ¬!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_bc_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("đŸ¦€ **Báº¦U CUA TĂ”M CĂ**\nChá»n má»©c cÆ°á»£c cá»§a báº¡n:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_bc_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("é¹¿ NAI", callback_data=f"p_bc_0_{amt}"), InlineKeyboardButton("đŸ¦€ CUA", callback_data=f"p_bc_1_{amt}"), InlineKeyboardButton("đŸŸ CĂ", callback_data=f"p_bc_2_{amt}")],
            [InlineKeyboardButton("đŸ¯ Há»”", callback_data=f"p_bc_3_{amt}"), InlineKeyboardButton("đŸ¦ TĂ”M", callback_data=f"p_bc_4_{amt}"), InlineKeyboardButton("đŸ Báº¦U", callback_data=f"p_bc_5_{amt}")],
            [InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_bc")]
        ]
        await q.edit_message_text(f"đŸ¦€ **Báº¦U CUA**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nđŸ‘‡ Chá»n linh váº­t báº¡n Ä‘áº·t cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_bc_"):
        parts = d.split("_")
        choice_idx, amt = int(parts[2]), int(parts[3])
        items = ["é¹¿ NAI", "đŸ¦€ CUA", "đŸŸ CĂ", "đŸ¯ Há»”", "đŸ¦ TĂ”M", "đŸ Báº¦U"]
        
        if not sub_money(uid, amt, f"CÆ°á»£c Báº§u Cua {items[choice_idx]}"):
            return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        
        msg_bc = await ctx.bot.send_message(uid, "đŸ² **ÄANG Láº®C Báº¦U CUA...**")
        
        is_win_bc = check_win_by_id(8, uid) # ID Báº§u Cua
        if is_win_bc:
            res1 = choice_idx
            res2 = random.randint(0, 5)
            res3 = random.randint(0, 5)
        else:
            pool = [i for i in range(6) if i != choice_idx]
            res1, res2, res3 = random.choices(pool, k=3)

        results = [res1, res2, res3]
        random.shuffle(results)
        match_count = results.count(choice_idx)
        
        await asyncio.sleep(2)
        res_str = " | ".join([items[i] for i in results])
        
        if match_count > 0:
            rate = 1 + match_count
            win_amt = int(amt * rate * 0.95) 
            add_money(uid, win_amt, f"Tháº¯ng Báº§u Cua {items[choice_idx]} x{match_count}")
            status = f"đŸ‰ **THáº®NG X{match_count}!**\nđŸ’° Nháº­n: `+{win_amt:,}Ä‘`"
        else:
            status = f"đŸ’€ **THáº¤T Báº I!**\nâŒ KhĂ´ng cĂ³ con **{items[choice_idx]}** nĂ o."

        await msg_bc.edit_text(
            f"đŸ“ **Káº¾T QUáº¢ Báº¦U CUA**\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âœ¨ Káº¿t quáº£: **{res_str}**\n"
            f"đŸ‘‰ Báº¡n chá»n: **{items[choice_idx]}**\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n{status}\n"
            f"đŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", 
            parse_mode="Markdown"
        )
        return

    elif d == "menu_qs":
        if check_mt('mt_quayso') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "â™ï¸ Game Quay Sá»‘ Ä‘ang báº£o trĂ¬!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_qs_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("đŸ”¢ **QUAY Sá» MAY Máº®N (1-3)**\nChá»n sá»‘ vĂ  nháº­n thÆ°á»Ÿng x2.8!\nVui lĂ²ng chá»n má»©c cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_qs_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("1ï¸âƒ£ Sá» 1", callback_data=f"p_qs_1_{amt}"), 
             InlineKeyboardButton("2ï¸âƒ£ Sá» 2", callback_data=f"p_qs_2_{amt}"),
             InlineKeyboardButton("3ï¸âƒ£ Sá» 3", callback_data=f"p_qs_3_{amt}")],
            [InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_qs")]
        ]
        await q.edit_message_text(f"đŸ”¢ **CHá»ŒN CON Sá» MAY Máº®N**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nđŸ“ˆ Há»‡ sá»‘ nhĂ¢n: **x2.8**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_qs_"):
        parts = d.split("_")
        choice, amt = int(parts[2]), int(parts[3])
        if not sub_money(uid, amt, f"CÆ°á»£c Quay Sá»‘ {choice}"):
            return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        
        msg_qs = await ctx.bot.send_message(uid, "đŸŒ€ **ÄANG QUAY Sá»...**")
        await asyncio.sleep(2)
        
        is_win_qs = check_win_by_id(7, uid) # ID Quay Sá»‘
        if is_win_qs:
            result_qs = choice
        else:
            result_qs = random.choice([n for n in [1, 2, 3] if n != choice])
        
        if choice == result_qs:
            win_amt = int(amt * 2.8)
            add_money(uid, win_amt, f"Tháº¯ng Quay Sá»‘ {choice}")
            status = f"đŸ‰ **CHIáº¾N THáº®NG!**\nđŸ’ Káº¿t quáº£ ra sá»‘: **{result_qs}**\nđŸ’° Nháº­n: `+{win_amt:,}Ä‘`"
        else:
            status = f"đŸ’€ **THáº¤T Báº I!**\nâŒ Káº¿t quáº£ ra sá»‘: **{result_qs}**\nđŸ‘‰ Báº¡n Ä‘Ă£ chá»n sá»‘: **{choice}**"
        
        await msg_qs.edit_text(f"đŸ“ **Káº¾T QUáº¢ QUAY Sá»**\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n{status}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", parse_mode="Markdown")
        return

    elif d == "menu_race":
        if check_mt('mt_duaxe') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "â™ï¸ Game Äua Xe Ä‘ang báº£o trĂ¬!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_race_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("đŸï¸ **ÄUA XE SIĂU Cáº¤P**\nVui lĂ²ng chá»n má»©c cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_race_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("đŸï¸ XE A", callback_data=f"start_race_A_{amt}"), 
             InlineKeyboardButton("đŸï¸ XE B", callback_data=f"start_race_B_{amt}")],
            [InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_race")]
        ]
        await q.edit_message_text(f"đŸï¸ **ÄUA XE**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nđŸ‘‡ Chá»n xe báº¡n tin lĂ  sáº½ tháº¯ng:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_race_"):
        parts = d.split("_")
        choice, amt = parts[2], int(parts[3])
        if not sub_money(uid, amt, f"CÆ°á»£c Äua xe {choice}"):
            return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        await q.delete_message()
        await play_car_race(update, ctx, choice, amt)

    elif d == "menu_mines":
        if check_mt('mt_domin') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "â™ï¸ Game DĂ² MĂ¬n Ä‘ang báº£o trĂ¬!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_mines_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("đŸ’£ **DĂ’ MĂŒN (MINES)**\nVui lĂ²ng chá»n má»©c cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_mines_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("đŸ€ Báº®T Äáº¦U CHÆ I", callback_data=f"start_mines_{amt}"), InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_mines")]]
        await q.edit_message_text(f"đŸ’£ **DĂ’ MĂŒN**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nâ ï¸ CĂ³ 3 quáº£ mĂ¬n áº©n trong 15 Ă´. Má»Ÿ Ă´ Ä‘á»ƒ nhĂ¢n tiá»n!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_mines_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "CÆ°á»£c DĂ² MĂ¬n"): return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        
        is_win_game = check_win_by_id(4, uid)
        grid = [0]*12 + [1]*3 
        random.shuffle(grid)
        
        ctx.user_data[f"mine_{uid}"] = {"grid": grid, "bet": amt, "opened": [], "mult": 1.05, "must_lose": not is_win_game}
        kb = []
        row = []
        for i in range(15):
            row.append(InlineKeyboardButton("â“", callback_data=f"play_mine_{i}"))
            if (i+1) % 3 == 0: kb.append(row); row = []
        await q.edit_message_text(f"đŸ’£ **DĂ’ MĂŒN ÄANG DIá»„N RA**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nđŸ“ˆ Há»‡ sá»‘ tiáº¿p theo: `x1.05`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("play_mine_"):
        game = ctx.user_data.get(f"mine_{uid}")
        if not game: return
        idx = int(d.split("_")[2])
        if idx in game["opened"]: return
        
        if game["must_lose"] and len(game["opened"]) >= random.randint(1, 3):
            is_bomb = True
        else:
            is_bomb = (game["grid"][idx] == 1)

        if is_bomb: 
            del ctx.user_data[f"mine_{uid}"]
            await q.edit_message_text(f"đŸ’¥ **BĂ™M!!!**\nBáº¡n Ä‘Ă£ dáº«m pháº£i mĂ¬n rá»“i.\nđŸ’€ Máº¥t: `{game['bet']:,}Ä‘`", parse_mode="Markdown")
        else: 
            game["opened"].append(idx)
            current_win = int(game["bet"] * game["mult"])
            game["mult"] = get_next_multiplier(game["mult"])
            
            kb = []
            row = []
            for i in range(15):
                icon = "đŸ’" if i in game["opened"] else "â“"
                row.append(InlineKeyboardButton(icon, callback_data=f"play_mine_{i}"))
                if (i+1) % 3 == 0: kb.append(row); row = []
            kb.append([InlineKeyboardButton(f"đŸ’° CHá»T Lá»œI: {current_win:,}Ä‘", callback_data=f"claim_mine_{current_win}")])
            await q.edit_message_text(f"đŸ’ **AN TOĂ€N!**\nđŸ’° ThÆ°á»Ÿng hiá»‡n táº¡i: `{current_win:,}Ä‘`\nđŸ“ˆ LÆ°á»£t tá»›i: `x{game['mult']:.2f}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("claim_mine_"):
        amt = int(d.split("_")[2])
        add_money(uid, amt, "Tháº¯ng DĂ² MĂ¬n")
        if f"mine_{uid}" in ctx.user_data: del ctx.user_data[f"mine_{uid}"]
        await q.edit_message_text(f"đŸ‰ **CHĂC Má»ªNG!**\nBáº¡n Ä‘Ă£ chá»‘t lá»i thĂ nh cĂ´ng: `+{amt:,}Ä‘`\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", parse_mode="Markdown")

    elif d == "menu_tx" or d == "menu_ball" or d == "menu_xocdia":
        if "tx" in d: g_type, g_name, mt_key = "tx", "đŸ² TĂ€I Xá»ˆU 3D", "mt_taixiu"
        elif "ball" in d: g_type, g_name, mt_key = "ball", "â½ï¸ BĂ“NG ÄĂ PENALTY", "mt_penalty"
        else: g_type, g_name, mt_key = "xd", "đŸ’¿ XĂ“C ÄÄ¨A VIP", "mt_xocdia"

        if check_mt(mt_key) and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, f"â™ï¸ Game {g_name} Ä‘ang báº£o trĂ¬!")
            
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_{g_type}_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text(f"{g_name}\nđŸ‘‡ Chá»n má»©c tiá»n cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_"):
        _, game, amt = d.split("_")
        if game == "tx":
            kb = [[InlineKeyboardButton("đŸ² TĂ€I", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("đŸ² Xá»ˆU", callback_data=f"p_tx_xiu_{amt}")]]
        elif game == "xd":
            kb = [
                [InlineKeyboardButton("đŸ”´ CHáº´N (x1.95)", callback_data=f"p_xd_chan_{amt}"), InlineKeyboardButton("âªï¸ Láºº (x1.95)", callback_data=f"p_xd_le_{amt}")],
                [InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_xocdia")]
            ]
        else:
            kb = [[InlineKeyboardButton("â¬…ï¸ TRĂI", callback_data=f"p_ba_1_{amt}"), 
                   InlineKeyboardButton("â¬†ï¸ GIá»®A", callback_data=f"p_ba_2_{amt}"), 
                   InlineKeyboardButton("â¡ï¸ PHáº¢I", callback_data=f"p_ba_3_{amt}")]]
        await q.edit_message_text(f"đŸ’° CÆ°á»£c: **{int(amt):,}Ä‘**\nđŸ‘‡ Chá»n hÆ°á»›ng sĂºt/cá»­a Ä‘áº·t:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_"):
        parts = d.split("_")
        game, choice, amt = parts[1], parts[2], int(parts[3])
        if get_balance(uid) < amt: return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        
        if game == "xd":
            sub_money(uid, amt, f"CÆ°á»£c XĂ³c ÄÄ©a {choice.upper()}")
            frames = ["đŸ’¿ [ - - - - ]", "đŸ’¿ [ âªï¸ đŸ”´ âªï¸ đŸ”´ ]", "đŸ’¿ [ đŸ”´ đŸ”´ đŸ”´ đŸ”´ ]", "đŸ’¿ [ đŸ”´ âªï¸ đŸ”´ âªï¸ ]"]
            msg_status = await ctx.bot.send_message(uid, frames[0], parse_mode="Markdown")
            for f in frames[1:]:
                await asyncio.sleep(0.4)
                try: await msg_status.edit_text(f + "\nâ¡ï¸ ÄANG Láº®C...")
                except: pass

            is_win_game = check_win_by_id(2, uid)
            if is_win_game:
                win_sets = {"chan":[[1,1,0,0],[1,1,1,1],[0,0,0,0]], "le":[[1,0,0,0],[1,1,1,0]]}
                results = random.choice(win_sets[choice])
            else:
                all_sets = [[1,1,1,1],[0,0,0,0],[1,1,0,0],[1,1,1,0],[1,0,0,0]]
                def check_win(res, c):
                    r = sum(res)
                    if c=="chan": return r%2==0
                    if c=="le": return r%2!=0
                    return False
                fail_sets = [r for r in all_sets if not check_win(r, choice)]
                results = random.choice(fail_sets)

            random.shuffle(results)
            red_count = sum(results)
            icons = "".join(["đŸ”´" if r == 1 else "âªï¸" for r in results])
            is_chan = (red_count % 2 == 0)
            
            win, rate = False, 1.95
            if choice == "chan" and is_chan: win = True
            elif choice == "le" and not is_chan: win = True

            if win:
                win_amt = int(amt * rate)
                add_money(uid, win_amt, f"Tháº¯ng XĂ³c ÄÄ©a {choice.upper()}")
                status = f"đŸ‰ **THĂ”NG THáº®NG X{rate}**\nđŸ’° Nháº­n: `+{win_amt:,}Ä‘`"
            else: status = f"âŒ **THUA Rá»’I**\nđŸ’€ Káº¿t quáº£ khĂ´ng khá»›p cá»­a Ä‘áº·t."

            final_msg = (f"đŸ“ **Káº¾T QUáº¢ XĂ“C ÄÄ¨A**\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nđŸ’¿ Káº¿t quáº£: **{icons}**\nđŸ“ Loáº¡i: **{'CHáº´N' if is_chan else 'Láºº'}** ({red_count} Äá»)\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n{status}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`")
            await msg_status.edit_text(final_msg, parse_mode="Markdown")
            return

        if game == "ba":
            sub_money(uid, amt, f"CÆ°á»£c Penalty")
            is_win = check_win_by_id(5, uid)
            player_choice = int(choice)
            if is_win:
                goalie_direction = random.choice([d for d in [1, 2, 3] if d != player_choice])
            else:
                goalie_direction = player_choice

            directions_text = {1: "TRĂI", 2: "GIá»®A", 3: "PHáº¢I"}
            msg_ball = await ctx.bot.send_dice(uid, emoji="â½ï¸")
            await asyncio.sleep(3.5)
            
            if player_choice == goalie_direction:
                win = False
                result_detail = f"đŸ§¤ Thá»§ mĂ´n Ä‘Ă£ bay ngÆ°á»i sang **{directions_text[goalie_direction]}** vĂ  báº¯t gá»n bĂ³ng!"
            else:
                win = True
                result_detail = f"đŸ¥… Thá»§ mĂ´n bay sang **{directions_text[goalie_direction]}** nhÆ°ng báº¡n sĂºt vĂ o **{directions_text[player_choice]}**!"
            
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, "Tháº¯ng Penalty")
                status = f"â½ï¸ **VĂ€OOO!!!**\n{result_detail}\nđŸ’° Nháº­n: `+{win_amt:,}Ä‘`"
            else:
                status = f"âŒ **KHĂ”NG VĂ€O!**\n{result_detail}\nđŸ’€ Báº¡n Ä‘Ă£ máº¥t tiá»n cÆ°á»£c."
            await ctx.bot.send_message(uid, f"{status}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`", parse_mode="Markdown")
            return

        if game == "tx":
            sub_money(uid, amt, f"CÆ°á»£c {game}")
            msg_status = await ctx.bot.send_message(uid, "đŸ² **ÄANG Láº®C XĂC Xáº®C...**", parse_mode="Markdown")
            
            d1 = await ctx.bot.send_dice(uid, emoji="đŸ²")
            d2 = await ctx.bot.send_dice(uid, emoji="đŸ²")
            d3 = await ctx.bot.send_dice(uid, emoji="đŸ²")
            
            results = [d1.dice.value, d2.dice.value, d3.dice.value]
            total = sum(results)
            res_type = "tai" if total >= 11 else "xiu"
            is_win_check = check_win_by_id(1, uid)
            
            win = (choice == res_type and is_win_check)

            await asyncio.sleep(4)
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, f"Tháº¯ng TĂ i Xá»‰u {res_type.upper()}")
                status = f"đŸ‰ **THáº®NG** | Nháº­n: `+{win_amt:,}Ä‘`"
            else:
                status = f"âŒ **THUA** | ChĂºc may máº¯n láº§n sau!"
            res_str = "-".join(map(str, results))
            await msg_status.edit_text(
                f"đŸ“ **Káº¾T QUáº¢ TĂ€I Xá»ˆU**\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nđŸ² XĂºc xáº¯c: **{res_str}**\nđŸ† Tá»•ng Ä‘iá»ƒm: **{total}** ({res_type.upper()})\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n{status}\nđŸ’° Sá»‘ dÆ°: `{get_balance(uid):,}Ä‘`"
            , parse_mode="Markdown")

    elif d == "menu_wooden":
        if check_mt('mt_gomo') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "â™ï¸ Game GĂµ MĂµ Ä‘ang báº£o trĂ¬!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_wood_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("đŸªµ **GAME GĂ• MĂ•**\n\n- Há»‡ sá»‘ tÄƒng: 1.05 -> 1.10 -> 1.20... -> 2.0 -> 2.20...\n- Báº¡n pháº£i rĂºt trÆ°á»›c khi mĂµ vá»¡!\n\nChá»n má»©c cÆ°á»£c:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_wood_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("đŸªµ Báº®T Äáº¦U GĂ•", callback_data=f"start_wood_{amt}")],
              [InlineKeyboardButton("đŸ”™ Quay láº¡i", callback_data="menu_wooden")]]
        await q.edit_message_text(f"đŸªµ **GĂ• MĂ•**\nđŸ’° CÆ°á»£c: `{amt:,}Ä‘`\nđŸ‘‡ Nháº¥n nĂºt GĂ• bĂªn dÆ°á»›i Ä‘á»ƒ báº¯t Ä‘áº§u tÄƒng há»‡ sá»‘!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_wood_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "CÆ°á»£c GĂµ MĂµ"): 
            return await ctx.bot.send_message(uid, "âŒ Sá»‘ dÆ° khĂ´ng Ä‘á»§.")
        
        is_win_wood = check_win_by_id(6, uid)
        if is_win_wood:
            break_point = round(random.uniform(3.0, 10.0), 2)
        else:
            break_point = round(random.uniform(1.1, 1.8), 2)

        game_id = f"wd_{uid}_{random.randint(100,999)}"
        ctx.user_data[game_id] = {"status": "playing", "amt": amt, "mult": 1.0, "target": break_point}
        kb = [[InlineKeyboardButton("đŸªµ GĂ• (x1.00)", callback_data=f"hit_wood_{game_id}")],
              [InlineKeyboardButton("đŸ’° RĂT (x1.00)", callback_data=f"clm_wood_{game_id}")]]
        await q.edit_message_text(f"đŸªµ **GĂ• MĂ•... Cá»˜P Cá»˜P!**\nđŸ“ˆ Há»‡ sá»‘ hiá»‡n táº¡i: **x1.00**\nđŸ’° Tiá»n náº¿u rĂºt: `{amt:,}Ä‘`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("hit_wood_"):
        parts = d.split("_")
        game_id = "_".join(parts[2:])
        game = ctx.user_data.get(game_id)
        if not game or game["status"] != "playing": return
        
        game["mult"] = get_next_multiplier(game["mult"])
        
        if game["mult"] >= game["target"]:
            game["status"] = "broken"
            await q.edit_message_text(f"đŸ’¥ **MĂ• ÄĂƒ Vá»  !!!**\n\nHá»‡ sá»‘ nháº£y quĂ¡ cao: **x{game['mult']:.2f}**\nđŸ’€ Máº¥t: `{game['amt']:,}Ä‘`", parse_mode="Markdown")
            del ctx.user_data[game_id]
        else:
            win_now = int(game["amt"] * game["mult"])
            kb = [[InlineKeyboardButton(f"đŸªµ GĂ• TIáº¾P (x{game['mult']:.2f})", callback_data=f"hit_wood_{game_id}")],
                  [InlineKeyboardButton(f"đŸ’° RĂT TIá»€N (x{game['mult']:.2f})", callback_data=f"clm_wood_{game_id}")]]
            await q.edit_message_text(f"đŸªµ **GĂ• MĂ•... Cá»˜P Cá»˜P!**\nđŸ“ˆ Há»‡ sá»‘: **x{game['mult']:.2f}**\nđŸ’° Tiá»n tháº¯ng: `{win_now:,}Ä‘`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clm_wood_"):
        parts = d.split("_")
        game_id = "_".join(parts[2:])
        game = ctx.user_data.get(game_id)
        if game and game["status"] == "playing":
            game["status"] = "claimed"
            win_amt = int(game["amt"] * game["mult"])
            add_money(uid, win_amt, f"Tháº¯ng GĂµ MĂµ x{game['mult']}")
            await q.edit_message_text(f"đŸ‰ **CHĂC Má»ªNG!**\n\nBáº¡n Ä‘Ă£ dá»«ng á»Ÿ **x{game['mult']:.2f}**\nđŸ’° Nháº­n Ä‘Æ°á»£c: `+{win_amt:,}Ä‘`", parse_mode="Markdown")
            del ctx.user_data[game_id]

# ===== KHá»I CHáº Y BOT =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("baotri", baotri_cmd))
app.add_handler(CommandHandler("code", nhap_code))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("tilewin", tilewin_cmd)) 
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("lienket", lien_ket))
app.add_handler(CommandHandler("resetbank", reset_bank))
app.add_handler(CommandHandler("resetall", reset_all_confirm)) 
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("sub", sub))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all", all_user))
app.add_handler(CommandHandler("his", history_pro)) 
app.add_handler(CommandHandler("hisall", history_all_admin))
app.add_handler(CommandHandler("send", broadcast))
app.add_handler(CommandHandler("rep", reply_user))
app.add_handler(CommandHandler("check", check_user_history))
app.add_handler(CommandHandler("info", admin_info)) 
app.add_handler(CommandHandler("nap", nap_tien_admin))
app.add_handler(CommandHandler("soduall", soduall_cmd))
app.add_handler(CommandHandler("tileall", tileall_set_cmd)) # Sá»­ dá»¥ng hĂ m set tá»‰ lá»‡ má»›i
app.add_handler(CommandHandler("resetsdall", resetsdall_cmd)) # Lá»‡nh xĂ³a sá»‘ dÆ°
app.add_handler(CommandHandler("tile1", tile1_user_cmd)) # Tá»‰ lá»‡ riĂªng cho 1 user
app.add_handler(CommandHandler("xoalsall", xoalsall_cmd))
app.add_handler(CommandHandler("xoals", xoals_user_cmd))

app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT ÄĂƒ Sáº´N SĂ€NG!")
app.run_polling()
  
