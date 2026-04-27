from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import asyncio
import random

# Hàm tạo mã ngẫu nhiên
def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8619503816
GROUP_IDS = [-1003663678808]
GROUP_LINKS = ["https://t.me/thanhall"]
BOT_USERNAME = "vuavipluxurybot" 
MIN_WITHDRAW = 100000

# THÔNG TIN NẠP TIỀN
BANK_INFO = """
🏦 **THÔNG TIN NẠP TIỀN**
--------------------------
🏛 Ngân hàng: **MBBANK**
👤 CTK: **LY THI CHAM**
💳 STK: `0367203858`
📝 NỘI DUNG CK: `{uid}`
--------------------------
⚠️ *Lưu ý: Bạn vui lòng nhập đúng ID để hệ thống kiểm tra nhanh nhất!*
"""

# ===== DATABASE SETUP =====
conn = sqlite3.connect("bot.db", check_same_thread=False)

def query(q, args=()):
    cur = conn.cursor()
    cur.execute(q, args)
    conn.commit()
    return cur

query("CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, reward INTEGER, uses INTEGER)")
query("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    refs INTEGER DEFAULT 0,
    refed INTEGER DEFAULT 0,
    bank TEXT DEFAULT NULL,
    stk TEXT DEFAULT NULL,
    name TEXT DEFAULT NULL,
    last_checkin TEXT,
    last_withdraw TEXT
)
""")
query("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, amount INTEGER, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")

# ===== USER UTILS =====
def get_user(uid):
    if not query("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        query("INSERT INTO users(user_id) VALUES(?)", (uid,))

def get_balance(uid):
    get_user(uid)
    res = query("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return res[0] if res else 0

def is_banned(uid):
    return query("SELECT 1 FROM banned WHERE user_id=?", (uid,)).fetchone() is not None

def add_money(uid, amt, note):
    get_user(uid)
    query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, amt, note, str(datetime.now())))

def sub_money(uid, amt, note="withdraw"):
    get_user(uid)
    bal = get_balance(uid)
    if bal < amt:
        return False
    query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, note, str(datetime.now())))
    return True

# ===== JOIN CHECK =====
async def joined(uid, bot):
    for gid in GROUP_IDS:
        try:
            m = await bot.get_chat_member(gid, uid)
            if m.status not in ["left", "kicked"]:
                return True
        except: pass
    return False

async def force_join(update):
    buttons = [[InlineKeyboardButton(f"📢 Tham Gia Nhóm {i+1}", url=link)] for i, link in enumerate(GROUP_LINKS)]
    await update.message.reply_text(
        "⚠️ **BẠN CHƯA THAM GIA NHÓM**\n\nVui lòng tham gia các nhóm dưới đây để kích hoạt tính năng của Bot!",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ===== GAMES ANIMATION =====

async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    track_length = 12
    pos_a, pos_b = 0, 0
    finish_line = "🏁"
    
    msg = await ctx.bot.send_message(uid, "🚦 **SẴN SÀNG...**")
    await asyncio.sleep(1)
    await msg.edit_text("🏎💨 **XUẤT PHÁT!!!**")

    while pos_a < track_length and pos_b < track_length:
        pos_a = min(pos_a + random.randint(1, 3), track_length)
        pos_b = min(pos_b + random.randint(1, 3), track_length)
        line_a = "—" * pos_a + "🏎️" + " " * (track_length - pos_a) + finish_line + " **(A)**"
        line_b = "—" * pos_b + "🏎️" + " " * (track_length - pos_b) + finish_line + " **(B)**"
        try:
            await msg.edit_text(f"🏎️ **ĐUA XE SIÊU CẤP**\n\n`{line_a}`\n`{line_b}`", parse_mode="Markdown")
            await asyncio.sleep(0.8)
        except: pass

    winner = "A" if pos_a >= track_length else "B"
    win = (choice == winner)
    if win:
        win_amt = int(amt * 1.95)
        add_money(uid, win_amt, f"Thắng đua xe {winner}")
        res_text = f"🎉 **CHIẾN THẮNG!** Xe **{winner}** về nhất!\n💰 Nhận: `+{win_amt:,}đ`"
    else:
        res_text = f"💀 **THẤT BẠI!** Xe **{winner}** đã thắng cuộc."
    await ctx.bot.send_message(uid, f"{res_text}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {choice_code}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")
    msg_status = await update.message.reply_text("🎲 **ĐANG LẮC XÚC XẮC...**", parse_mode="Markdown")
    tasks = [update.message.reply_dice(emoji="🎲") for _ in range(3)]
    dice_messages = await asyncio.gather(*tasks)
    results = [m.dice.value for m in dice_messages]
    total = sum(results)
    await asyncio.sleep(4)
    is_chan, is_tai = (total % 2 == 0), (total >= 11)
    win = False
    c = choice_code.upper()
    if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or \
       (c == "XXX" and not is_tai) or (c == "XXT" and is_tai): win = True
    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: status = f"❌ **THUA**"
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_emoji_game(update: Update, game_type, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {game_type}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")
    emojis = {"SLOT": "🎰", "BALL": "⚽️", "RO": "🎰"}
    msg_game = await update.message.reply_dice(emoji=emojis[game_type])
    value = msg_game.dice.value
    await asyncio.sleep(4)
    win, rate = False, 1.95
    if game_type == "SLOT" and value in [1, 22, 43, 64]: win, rate = True, 10.0
    elif game_type == "BALL" and value in [3, 4, 5]: win = True
    elif game_type == "RO" and value in [4, 5]: win = True
    if win:
        win_amt = int(amount * rate)
        add_money(uid, win_amt, f"Thắng {game_type}")
        res = f"🎉 **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: res = "💀 **THUA RỒI!**"
    await update.message.reply_text(f"🎮 KQ: {value}\n{res}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# ===== LỆNH NHẬP CODE =====
async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập kèm mã. VD: `/code ABC123`")
        return
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=?", (code_str,)).fetchone()
    if not data:
        await update.message.reply_text("❌ Mã quà tặng không tồn tại.")
        return
    reward, uses = data[1], data[2]
    if uses <= 0:
        await update.message.reply_text("❌ Mã quà tặng này đã hết lượt sử dụng.")
        return
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=?", (code_str,))
    await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\n💰 Bạn nhận được: `+{reward:,}đ`", parse_mode="Markdown")

# ===== ADMIN COMMANDS =====

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await update.message.reply_text(f"✅ **NẠP TIỀN THÀNH CÔNG**\n\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`", parse_mode="Markdown")
        bill = (f"💳 **BIẾN ĐỘNG SỐ DƯ**\n━━━━━━━━━━━━━\nSố tiền: `+{amount:,}đ`\nNội dung: Nạp tiền hệ thống\n💰 Số dư hiện tại: `{get_balance(target_id):,}đ`")
        try: await ctx.bot.send_message(chat_id=target_id, text=bill, parse_mode="Markdown")
        except: pass
    except: await update.message.reply_text("❌ Cú pháp: `/nap [ID] [Số tiền]`")

async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=?", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`")
        await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn.")
    except: await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        u = query("SELECT balance, refs, bank, stk, name, last_checkin FROM users WHERE user_id=?", (target_id,)).fetchone()
        if not u: return await update.message.reply_text("❌ Không tìm thấy user.")
        msg = (f"📁 **THÔNG TIN USER `{target_id}`**\n━━━━━━━━━━━━━\n💰 Số dư: `{u[0]:,}`\n🏦 Bank: `{u[2]} | {u[3]} | {u[4]}`")
        await update.message.reply_text(msg, parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/info [ID]`")

async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ Code: `{code}` | Thưởng: `{reward:,}` | Lượt: `{uses}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/taocode [tiền] [lượt]`")

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng tiền")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho ID `{uid}`")
    except: pass

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt, "Admin trừ tiền")
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của ID `{uid}`")
    except: pass

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👤 Tổng user: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = query("SELECT user_id FROM users ORDER BY rowid DESC").fetchall()
    msg = "👥 **DANH SÁCH USER:**\n\n" + "\n".join([f"`{u[0]}`" for u in users])
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = query("SELECT * FROM history ORDER BY rowid DESC").fetchall()
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    for d in data: msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/send [nội dung]`")
    msg_to_send = " ".join(ctx.args)
    users = query("SELECT user_id FROM users").fetchall()
    for user in users:
        try: await ctx.bot.send_message(chat_id=user[0], text=f"🔔 **THÔNG BÁO MỚI**\n\n{msg_to_send}", parse_mode="Markdown")
        except: pass
    await update.message.reply_text("✅ Đã gửi xong.")

async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0]); msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"✉️ **PHẢN HỒI TỪ ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã phản hồi tới `{uid}`")
    except: await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")

async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import asyncio
import random

# Hàm tạo mã ngẫu nhiên
def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8619503816
GROUP_IDS = [-1003663678808]
GROUP_LINKS = ["https://t.me/thanhall"]
BOT_USERNAME = "vuavipluxurybot" 
MIN_WITHDRAW = 100000

# THÔNG TIN NẠP TIỀN
BANK_INFO = """
🏦 **THÔNG TIN NẠP TIỀN**
--------------------------
🏛 Ngân hàng: **MBBANK**
👤 CTK: **LY THI CHAM**
💳 STK: `0367203858`
📝 NỘI DUNG CK: `{uid}`
--------------------------
⚠️ *Lưu ý: Bạn vui lòng nhập đúng ID để hệ thống kiểm tra nhanh nhất!*
"""

# ===== DATABASE SETUP =====
conn = sqlite3.connect("bot.db", check_same_thread=False)

def query(q, args=()):
    cur = conn.cursor()
    cur.execute(q, args)
    conn.commit()
    return cur

query("CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, reward INTEGER, uses INTEGER)")
query("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    refs INTEGER DEFAULT 0,
    refed INTEGER DEFAULT 0,
    bank TEXT DEFAULT NULL,
    stk TEXT DEFAULT NULL,
    name TEXT DEFAULT NULL,
    last_checkin TEXT,
    last_withdraw TEXT
)
""")
query("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, amount INTEGER, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")

# ===== USER UTILS =====
def get_user(uid):
    if not query("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        query("INSERT INTO users(user_id) VALUES(?)", (uid,))

def get_balance(uid):
    get_user(uid)
    res = query("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return res[0] if res else 0

def is_banned(uid):
    return query("SELECT 1 FROM banned WHERE user_id=?", (uid,)).fetchone() is not None

def add_money(uid, amt, note):
    get_user(uid)
    query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, amt, note, str(datetime.now())))

def sub_money(uid, amt, note="withdraw"):
    get_user(uid)
    bal = get_balance(uid)
    if bal < amt:
        return False
    query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, note, str(datetime.now())))
    return True

# ===== JOIN CHECK =====
async def joined(uid, bot):
    for gid in GROUP_IDS:
        try:
            m = await bot.get_chat_member(gid, uid)
            if m.status not in ["left", "kicked"]:
                return True
        except: pass
    return False

async def force_join(update):
    buttons = [[InlineKeyboardButton(f"📢 Tham Gia Nhóm {i+1}", url=link)] for i, link in enumerate(GROUP_LINKS)]
    await update.message.reply_text(
        "⚠️ **BẠN CHƯA THAM GIA NHÓM**\n\nVui lòng tham gia các nhóm dưới đây để kích hoạt tính năng của Bot!",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ===== GAMES ANIMATION =====

async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    track_length = 12
    pos_a, pos_b = 0, 0
    finish_line = "🏁"
    
    msg = await ctx.bot.send_message(uid, "🚦 **SẴN SÀNG...**")
    await asyncio.sleep(1)
    await msg.edit_text("🏎💨 **XUẤT PHÁT!!!**")

    while pos_a < track_length and pos_b < track_length:
        pos_a = min(pos_a + random.randint(1, 3), track_length)
        pos_b = min(pos_b + random.randint(1, 3), track_length)
        line_a = "—" * pos_a + "🏎️" + " " * (track_length - pos_a) + finish_line + " **(A)**"
        line_b = "—" * pos_b + "🏎️" + " " * (track_length - pos_b) + finish_line + " **(B)**"
        try:
            await msg.edit_text(f"🏎️ **ĐUA XE SIÊU CẤP**\n\n`{line_a}`\n`{line_b}`", parse_mode="Markdown")
            await asyncio.sleep(0.8)
        except: pass

    winner = "A" if pos_a >= track_length else "B"
    win = (choice == winner)
    if win:
        win_amt = int(amt * 1.95)
        add_money(uid, win_amt, f"Thắng đua xe {winner}")
        res_text = f"🎉 **CHIẾN THẮNG!** Xe **{winner}** về nhất!\n💰 Nhận: `+{win_amt:,}đ`"
    else:
        res_text = f"💀 **THẤT BẠI!** Xe **{winner}** đã thắng cuộc."
    await ctx.bot.send_message(uid, f"{res_text}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {choice_code}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")
    msg_status = await update.message.reply_text("🎲 **ĐANG LẮC XÚC XẮC...**", parse_mode="Markdown")
    tasks = [update.message.reply_dice(emoji="🎲") for _ in range(3)]
    dice_messages = await asyncio.gather(*tasks)
    results = [m.dice.value for m in dice_messages]
    total = sum(results)
    await asyncio.sleep(4)
    is_chan, is_tai = (total % 2 == 0), (total >= 11)
    win = False
    c = choice_code.upper()
    if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or \
       (c == "XXX" and not is_tai) or (c == "XXT" and is_tai): win = True
    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: status = f"❌ **THUA**"
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_emoji_game(update: Update, game_type, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {game_type}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")
    emojis = {"SLOT": "🎰", "BALL": "⚽️", "RO": "🎰"}
    msg_game = await update.message.reply_dice(emoji=emojis[game_type])
    value = msg_game.dice.value
    await asyncio.sleep(4)
    win, rate = False, 1.95
    if game_type == "SLOT" and value in [1, 22, 43, 64]: win, rate = True, 10.0
    elif game_type == "BALL" and value in [3, 4, 5]: win = True
    elif game_type == "RO" and value in [4, 5]: win = True
    if win:
        win_amt = int(amount * rate)
        add_money(uid, win_amt, f"Thắng {game_type}")
        res = f"🎉 **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: res = "💀 **THUA RỒI!**"
    await update.message.reply_text(f"🎮 KQ: {value}\n{res}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# ===== LỆNH NHẬP CODE =====
async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập kèm mã. VD: `/code ABC123`")
        return
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=?", (code_str,)).fetchone()
    if not data:
        await update.message.reply_text("❌ Mã quà tặng không tồn tại.")
        return
    reward, uses = data[1], data[2]
    if uses <= 0:
        await update.message.reply_text("❌ Mã quà tặng này đã hết lượt sử dụng.")
        return
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=?", (code_str,))
    await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\n💰 Bạn nhận được: `+{reward:,}đ`", parse_mode="Markdown")

# ===== ADMIN COMMANDS =====

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await update.message.reply_text(f"✅ **NẠP TIỀN THÀNH CÔNG**\n\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`", parse_mode="Markdown")
        bill = (f"💳 **BIẾN ĐỘNG SỐ DƯ**\n━━━━━━━━━━━━━\nSố tiền: `+{amount:,}đ`\nNội dung: Nạp tiền hệ thống\n💰 Số dư hiện tại: `{get_balance(target_id):,}đ`")
        try: await ctx.bot.send_message(chat_id=target_id, text=bill, parse_mode="Markdown")
        except: pass
    except: await update.message.reply_text("❌ Cú pháp: `/nap [ID] [Số tiền]`")

async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=?", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`")
        await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn.")
    except: await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        u = query("SELECT balance, refs, bank, stk, name, last_checkin FROM users WHERE user_id=?", (target_id,)).fetchone()
        if not u: return await update.message.reply_text("❌ Không tìm thấy user.")
        msg = (f"📁 **THÔNG TIN USER `{target_id}`**\n━━━━━━━━━━━━━\n💰 Số dư: `{u[0]:,}`\n🏦 Bank: `{u[2]} | {u[3]} | {u[4]}`")
        await update.message.reply_text(msg, parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/info [ID]`")

async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ Code: `{code}` | Thưởng: `{reward:,}` | Lượt: `{uses}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/taocode [tiền] [lượt]`")

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng tiền")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho ID `{uid}`")
    except: pass

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt, "Admin trừ tiền")
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của ID `{uid}`")
    except: pass

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👤 Tổng user: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = query("SELECT user_id FROM users ORDER BY rowid DESC").fetchall()
    msg = "👥 **DANH SÁCH USER:**\n\n" + "\n".join([f"`{u[0]}`" for u in users])
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = query("SELECT * FROM history ORDER BY rowid DESC").fetchall()
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    for d in data: msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/send [nội dung]`")
    msg_to_send = " ".join(ctx.args)
    users = query("SELECT user_id FROM users").fetchall()
    for user in users:
        try: await ctx.bot.send_message(chat_id=user[0], text=f"🔔 **THÔNG BÁO MỚI**\n\n{msg_to_send}", parse_mode="Markdown")
        except: pass
    await update.message.reply_text("✅ Đã gửi xong.")

async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0]); msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"✉️ **PHẢN HỒI TỪ ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã phản hồi tới `{uid}`")
    except: await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")

async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
        if not data: await update.message.reply_text("Trống.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}`:**\n\n"
            for d in data: msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2][:16]}_\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/check [ID]`")

# ===== START & REF SYSTEM =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    get_user(uid)
    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=?", (uid,)).fetchone()
                if row and row[0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
                        add_money(ref, 3000, "Ref bonus"); query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,)); query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except: pass
    if not await joined(uid, ctx.bot): await force_join(update); return
    menu = ReplyKeyboardMarkup([["🎮 Danh sách game", "👤 Tài khoản"], ["💳 Nạp tiền", "🛍 Rút tiền"], ["🎁 Checkin", "📧 Mời bạn"], ["📜 Lịch sử", "📞 Hỗ trợ"]], resize_keyboard=True)
    welcome_text = (f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()}!**\n\n"
                    f"💰 **MIN RÚT:** `100.000đ` | 💳 **MIN NẠP:** `10.000đ`")
    await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode="Markdown")

# ===== LỆNH LIÊN KẾT =====
async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    u_bank = query("SELECT bank FROM users WHERE user_id=?", (uid,)).fetchone()
    if u_bank and u_bank[0] is not None: return await update.message.reply_text("❌ Đã liên kết rồi.")
    if not ctx.args or len(ctx.args) < 3: return await update.message.reply_text("`/lienket [Bank] [STK] [Tên]`")
    bank, stk, name = ctx.args[0].upper(), ctx.args[1], " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=?, stk=?, name=? WHERE user_id=?", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**", parse_mode="Markdown")

# ===== RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    u = query("SELECT bank, stk, name, balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u or not u[0]: return await update.message.reply_text("❌ Dùng /lienket trước.")
    if not ctx.args: return await update.message.reply_text(f"💰 Dư: `{u[3]:,}` | Rút: `/rut [số tiền]`")
    try:
        amount = int(ctx.args[0])
        if amount < MIN_WITHDRAW: return await update.message.reply_text(f"❌ Min {MIN_WITHDRAW:,}")
        if sub_money(uid, amount, "Rút tiền"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"), InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")]])
            await ctx.bot.send_message(ADMIN_ID, f"🔔 **YÊU CẦU RÚT**\nID: `{uid}` | {amount:,}đ\n{u[0]} | {u[1]} | {u[2]}", reply_markup=kb, parse_mode="Markdown")
            await update.message.reply_text("✅ Đã gửi yêu cầu.")
        else: await update.message.reply_text("❌ Không đủ tiền.")
    except: await update.message.reply_text("❌ Lỗi.")

# ===== LỊCH SỬ KHÔNG GIỚI HẠN CHO USER =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
    if not data: await update.message.reply_text("📂 Trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT:**\n\n"
        for d in data: icon = "➕" if d[0] > 0 else "➖"; msg += f"{icon} `{d[0]:,}đ` | {d[1]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

# ===== HANDLE MENU MESSAGES =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    if not await joined(uid, ctx.bot): await force_join(update); return
    parts = txt.split()
    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]: return await play_dice_animation(update, code, amt)
        if code == "SLOT": return await play_emoji_game(update, "SLOT", amt)
        if code == "BALL": return await play_emoji_game(update, "BALL", amt)
        if code == "RÔ": return await play_emoji_game(update, "RO", amt)
    if txt == "👤 Tài khoản":
        u = query("SELECT balance, bank, stk, name, refs FROM users WHERE user_id=?", (uid,)).fetchone()
        await update.message.reply_text(f"👤 ID: `{uid}` | 💰 Dư: `{u[0]:,}đ`\n🏦 Bank: {u[1] or 'Chưa'}", parse_mode="Markdown")
    elif txt == "💳 Nạp tiền": await update.message.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")
    elif txt == "🎮 Danh sách game":
        # XOÁ NÚT MÁY BAY
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx")], [InlineKeyboardButton("🏎️ ĐUA XE", callback_data="menu_race"), InlineKeyboardButton("💣 DÒ MÌN", callback_data="menu_mines")], [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")], [InlineKeyboardButton("🎰 SLOT / KHÁC", callback_data="menu_others")]])
        await update.message.reply_text("🎮 **TRÒ CHƠI:**", reply_markup=kb, parse_mode="Markdown")
    elif txt == "📜 Lịch sử": await history_pro(update, ctx)
    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        res = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        if res and res[0] == today: return await update.message.reply_text("❌ Rồi!")
        add_money(uid, 3000, "Daily Checkin"); query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid)); await update.message.reply_text("🎁 +3000đ")
    elif txt == "📧 Mời bạn": await update.message.reply_text(f"🚀 Link: `t.me/{BOT_USERNAME}?start={uid}`", parse_mode="Markdown")
    elif txt == "📞 Hỗ trợ": await update.message.reply_text("📩 Liên hệ @RoGarden")

# ===== CALLBACK HANDLER (GAMES & WITHDRAW) - XOÁ GAME MÁY BAY =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data; uid = q.from_user.id; await q.answer()
    amounts = [1000, 5000, 10000, 50000, 100000, 200000, 500000, 1000000]
    if d.startswith(("ok_", "no_")):
        if uid != ADMIN_ID: return
        act, u_id, amt = d.split("_"); u_id, amt = int(u_id), int(amt)
        if act == "ok": await ctx.bot.send_message(u_id, f"✅ Đã duyệt {amt:,}đ"); await q.edit_message_text(f"✅ DUYỆT ID {u_id}")
        else: add_money(u_id, amt, "Hoàn tiền"); await ctx.bot.send_message(u_id, "❌ Từ chối"); await q.edit_message_text(f"❌ TỪ CHỐI ID {u_id}")
    elif d == "menu_race":
        kb = [amounts[i:i+4] for i in range(0, 8, 4)]
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_race_{a}") for a in r] for r in kb]
        await q.edit_message_text("🏎️ **CƯỢC ĐUA XE:**", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("prep_race_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("XE A", callback_data=f"start_race_A_{amt}"), InlineKeyboardButton("XE B", callback_data=f"start_race_B_{amt}")]]
        await q.edit_message_text(f"💰 Cược: {amt:,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("start_race_"):
        parts = d.split("_"); choice, amt = parts[2], int(parts[3])
        if not sub_money(uid, amt, f"Cược Đua xe {choice}"): return await ctx.bot.send_message(uid, "❌ Thiếu tiền.")
        await q.delete_message(); await play_car_race(update, ctx, choice, amt)
    elif d == "menu_mines":
        kb = [amounts[i:i+4] for i in range(0, 8, 4)]
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_mines_{a}") for a in r] for r in kb]
        await q.edit_message_text("💣 **DÒ MÌN:**", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("prep_mines_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🚀 CHƠI", callback_data=f"start_mines_{amt}")]]
        await q.edit_message_text(f"💰 Cược: {amt:,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("start_mines_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Dò Mìn"): return await ctx.bot.send_message(uid, "❌")
        grid = [0]*12 + [1]*3; random.shuffle(grid); ctx.user_data[f"mine_{uid}"] = {"grid": grid, "bet": amt, "opened": [], "mult": 1.4}
        kb = [[InlineKeyboardButton("❓", callback_data=f"play_mine_{i}") for i in range(j, j+3)] for j in range(0, 15, 3)]
        await q.edit_message_text(f"💣 **MÌN:** {amt:,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("play_mine_"):
        game = ctx.user_data.get(f"mine_{uid}"); idx = int(d.split("_")[2])
        if not game or idx in game["opened"]: return
        if game["grid"][idx] == 1: del ctx.user_data[f"mine_{uid}"]; await q.edit_message_text(f"💥 THUA! Mất {game['bet']:,}đ")
        else:
            game["opened"].append(idx); current_win = int(game["bet"] * game["mult"]); game["mult"] += 0.4
            kb = [[InlineKeyboardButton("💎" if i in game["opened"] else "❓", callback_data=f"play_mine_{i}") for i in range(j, j+3)] for j in range(0, 15, 3)]
            kb.append([InlineKeyboardButton(f"💰 CHỐT: {current_win:,}đ", callback_data=f"claim_mine_{current_win}")])
            await q.edit_message_text(f"💎 +{current_win:,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("claim_mine_"):
        amt = int(d.split("_")[2]); add_money(uid, amt, "Thắng Mìn"); del ctx.user_data[f"mine_{uid}"]; await q.edit_message_text(f"🎉 +{amt:,}đ")
    elif d == "menu_tx" or d == "menu_ball":
        g = "tx" if "tx" in d else "ball"
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"set_{g}_{a}") for a in r] for r in [amounts[i:i+4] for i in range(0, 8, 4)]]
        await q.edit_message_text("💰 Cược:", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("set_"):
        _, game, amt = d.split("_")
        if game == "tx": kb = [[InlineKeyboardButton("TÀI", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("XỈU", callback_data=f"p_tx_xiu_{amt}")]]
        else: kb = [[InlineKeyboardButton("TRÁI", callback_data=f"p_ba_1_{amt}"), InlineKeyboardButton("GIỮA", callback_data=f"p_ba_2_{amt}"), InlineKeyboardButton("PHẢI", callback_data=f"p_ba_3_{amt}")]]
        await q.edit_message_text(f"💰 {int(amt):,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("p_"):
        _, game, choice, amt = d.split("_"); amt = int(amt)
        if get_balance(uid) < amt: return await ctx.bot.send_message(uid, "❌")
        if game == "ba":
            sub_money(uid, amt, f"Penalty"); goalie = random.randint(1, 3); player = int(choice); await ctx.bot.send_dice(uid, emoji="⚽️"); await asyncio.sleep(3.5)
            if player == goalie: await ctx.bot.send_message(uid, "❌ THUA!")
            else: win = int(amt*1.95); add_money(uid, win, "Thắng Penalty"); await ctx.bot.send_message(uid, f"🎉 +{win:,}đ")
        elif game == "tx":
            sub_money(uid, amt, f"Tài Xỉu"); msg = await ctx.bot.send_message(uid, "🎲..."); tasks = [ctx.bot.send_dice(uid, emoji="🎲") for _ in range(3)]; dice = await asyncio.gather(*tasks); res = [m.dice.value for m in dice]; total = sum(res); await asyncio.sleep(4)
            res_type = "tai" if total >= 11 else "xiu"
            if choice == res_type: win = int(amt*1.95); add_money(uid, win, f"Thắng TX"); status = f"🎉 +{win:,}đ"
            else: status = "❌ THUA"
            await msg.edit_text(f"🎲 {res} = {total} ({res_type.upper()})\n{status}")
    elif d == "menu_others": await q.edit_message_text("Cú pháp:\n- `SLOT [Tiền]`\n- `RÔ [Tiền]`\n- `BALL [Tiền]`")
    elif d == "menu_wooden":
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_wood_{a}") for a in r] for r in [amounts[i:i+4] for i in range(0, 8, 4)]]
        await q.edit_message_text("🪵 **GÕ MÕ:**", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("prep_wood_"):
        amt = int(d.split("_")[2]); kb = [[InlineKeyboardButton("🪵 GÕ", callback_data=f"start_wood_{amt}")]]
        await q.edit_message_text(f"💰 {amt:,}đ", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("start_wood_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Gõ Mõ"): return await ctx.bot.send_message(uid, "❌")
        break_p = round(random.uniform(1.5, 15.0), 2); g_id = f"wd_{uid}_{random.randint(100,999)}"; ctx.user_data[g_id] = {"status": "playing", "amt": amt, "mult": 1.0, "target": break_p}
        kb = [[InlineKeyboardButton("🪵 GÕ (x1.0)", callback_data=f"hit_wood_{g_id}")], [InlineKeyboardButton("💰 RÚT", callback_data=f"clm_wood_{g_id}")]]
        await q.edit_message_text(f"🪵 GÕ ĐI! x1.0", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("hit_wood_"):
        g_id = d.replace("hit_wood_", ""); game = ctx.user_data.get(g_id)
        if not game or game["status"] != "playing": return
        game["mult"] = round(game["mult"] + 0.3, 2)
        if game["mult"] >= game["target"]: await q.edit_message_text(f"💥 VỠ! Mất {game['amt']:,}đ"); del ctx.user_data[g_id]
        else:
            win = int(game["amt"] * game["mult"]); kb = [[InlineKeyboardButton(f"🪵 GÕ (x{game['mult']})", callback_data=f"hit_wood_{g_id}")], [InlineKeyboardButton(f"💰 RÚT: {win:,}đ", callback_data=f"clm_wood_{g_id}")]]
            await q.edit_message_text(f"📈 x{game['mult']}", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("clm_wood_"):
        g_id = d.replace("clm_wood_", ""); game = ctx.user_data.get(g_id)
        if game and game["status"] == "playing": win = int(game["amt"] * game["mult"]); add_money(uid, win, f"Thắng Gõ"); await q.edit_message_text(f"🎉 +{win:,}đ"); del ctx.user_data[g_id]

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("code", nhap_code))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("lienket", lien_ket))
app.add_handler(CommandHandler("resetbank", reset_bank))
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
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT ĐÃ SẴN SÀNG - KHÔNG CÒN MÁY BAY - LỊCH SỬ KHÔNG GIỚI HẠN!")
app.run_polling()
￼Enter  data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
        if not data: await update.message.reply_text("Trống.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}`:**\n\n"
            for d in data: msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2][:16]}_\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/check [ID]`")

# ===== START & REF SYSTEM =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    get_user(uid)
    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=?", (uid,)).fetchone()
                if row and row[0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
                        add_money(ref, 3000, "Ref bonus"); query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,)); query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except: pass
    if not await joined(uid, ctx.bot): await force_join(update); return
    menu = ReplyKeyboardMarkup([["🎮 Danh sách game", "👤 Tài khoản"], ["💳 Nạp tiền", "🛍 Rút tiền"], ["🎁 Checkin", "📧 Mời bạn"], ["📜 Lịch sử", "📞 Hỗ trợ"]], resize_keyboard=True)
    welcome_text = (f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()}!**\n\n"
                    f"💰 **MIN RÚT:** `100.000đ` | 💳 **MIN NẠP:** `10.000đ`")
    await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode="Markdown")

# ===== LỆNH LIÊN KẾT =====
async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    u_bank = query("SELECT bank FROM users WHERE user_id=?", (uid,)).fetchone()
    if u_bank and u_bank[0] is not None: return await update.message.reply_text("❌ Đã liên kết rồi.")
    if not ctx.args or len(ctx.args) < 3: return await update.message.reply_text("`/lienket [Bank] [STK] [Tên]`")
    bank, stk, name = ctx.args[0].upper(), ctx.args[1], " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=?, stk=?, name=? WHERE user_id=?", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**", parse_mode="Markdown")

# ===== RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    u = query("SELECT bank, stk, name, balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u or not u[0]: return await update.message.reply_text("❌ Dùng /lienket trước.")
    if not ctx.args: return await update.message.reply_text(f"💰 Dư: `{u[3]:,}` | Rút: `/rut [số tiền]`")
    try:
        amount = int(ctx.args[0])
        if amount < MIN_WITHDRAW: return await update.message.reply_text(f"❌ Min {MIN_WITHDRAW:,}")
        if sub_money(uid, amount, "Rút tiền"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"), InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")]])
            await ctx.bot.send_message(ADMIN_ID, f"🔔 **YÊU CẦU RÚT**\nID: `{uid}` | {amount:,}đ\n{u[0]} | {u[1]} | {u[2]}", reply_markup=kb, parse_mode="Markdown")
            await update.message.reply_text("✅ Đã gửi yêu cầu.")
        else: await update.message.reply_text("❌ Không đủ tiền.")
    except: await update.message.reply_text("❌ Lỗi.")

# ===== LỊCH SỬ KHÔNG GIỚI HẠN CHO USER =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
    if not data: await update.message.reply_text("📂 Trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT:**\n\n"
        for d in data: icon = "➕" if d[0] > 0 else "➖"; msg += f"{icon} `{d[0]:,}đ` | {d[1]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

# ===== HANDLE MENU MESSAGES =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    if not await joined(uid, ctx.bot): await force_join(update); return
    parts = txt.split()
    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]: return await play_dice_animation(update, code, amt)
        if code == "SLOT": return await play_emoji_game(update, "SLOT", amt)
        if code == "BALL": return await play_emoji_game(update, "BALL", amt)
        if code == "RÔ": return await play_emoji_game(update, "RO", amt)
    if txt == "👤 Tài khoản":
        u = query("SELECT balance, bank, stk, name, refs FROM users WHERE user_id=?", (uid,)).fetchone()
        await update.message.reply_text(f"👤 ID: `{uid}` | 💰 Dư: `{u[0]:,}đ`\n🏦 Bank: {u[1] or 'Chưa'}", parse_mode="Markdown")
    elif txt == "💳 Nạp tiền": await update.message.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")
    elif txt == "🎮 Danh sách game":
        # XOÁ NÚT MÁY BAY
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx")], [InlineKeyboardButton("🏎️ ĐUA XE", callback_data="menu_race"), InlineKeyboardButton("💣 DÒ MÌN", callback_data="menu_mines")], [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")], [InlineKeyboardButton("🎰 SLOT / KHÁC", callback_data="menu_others")]])
        await update.message.reply_text("🎮 **TRÒ CHƠI:**", reply_markup=kb, parse_mode="Markdown")
    elif txt == "📜 Lịch sử": await history_pro(update, ctx)
    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        res = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        if res and res[0] == today: return await update.message.reply_text("❌ Rồi!")
        add_money(uid, 3000, "Daily Checkin"); query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid)); await update.message.reply_text("🎁 +3000đ")
    elif txt == "📧 Mời bạn": await update.message.reply_text(f"🚀 Link: `t.me/{BOT_USERNAME}?start={uid}`", parse_mode="Markdown")
    elif txt == "📞 Hỗ trợ": await update.message.reply_text("📩 Liên hệ @RoGarden")

# ===== CALLBACK HANDLER (GAMES & WITHDRAW) - XOÁ GAME MÁY BAY =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data; uid = q.from_user.id; await q.answer()
    amounts = [1000, 5000, 10000, 50000, 100000, 200000, 500000, 1000000]
    if d.startswith(("ok_", "no_")):
        if uid != ADMIN_ID: return
        act, u_id, amt = d.split("_"); u_id, amt = int(u_id), int(amt)
        if act == "ok": await ctx.bot.send_message(u_id, f"✅ Đã duyệt {amt:,}đ"); await q.edit_message_text(f"✅ DUYỆT ID {u_id}")
        else: add_money(u_id, amt, "Hoàn tiền"); await ctx.bot.send_message(u_id, "❌ Từ chối"); await q.edit_message_text(f"❌ TỪ CHỐI ID {u_id}")
    elif d == "menu_race":
        kb = [amounts[i:i+4] for i in range(0, 8, 4)]
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_race_{a}") for a in r] for r in kb]
