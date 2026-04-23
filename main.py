from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import sqlite3
from datetime import datetime
import asyncio
import os

# ===== CONFIG =====
TOKEN = "8622389687:AAGqQoYBhmmsQI65k5Vqv9uTjTe2YpVasFk"

ADMIN_ID = 8619503816
GROUP_ID = -1003663678808
GROUP_LINK = "https://t.me/thanhall"
BOT_USERNAME = "sunvipuytinbot"

VALID_BANKS = ["mb", "vcb", "acb", "momo", "zalopay"]

# ===== DB =====
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    refs INTEGER DEFAULT 0,
    refed INTEGER DEFAULT 0,
    bank TEXT,
    stk TEXT,
    name TEXT
)
""")

cursor.execute("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, amount INTEGER, note TEXT, time TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")
conn.commit()

# ===== DB FUNC =====
def get_user(uid):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users(user_id) VALUES(?)", (uid,))
        conn.commit()

def is_banned(uid):
    cursor.execute("SELECT 1 FROM banned WHERE user_id=?", (uid,))
    return cursor.fetchone() is not None

def add_money(uid, amt, note):
    get_user(uid)
    cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
    cursor.execute("INSERT INTO history VALUES(?,?,?,?)", (uid, amt, note, str(datetime.now())))
    conn.commit()

def sub_money(uid, amt):
    get_user(uid)
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    bal = cursor.fetchone()[0]

    if bal < amt:
        return False

    cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    cursor.execute("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, "withdraw", str(datetime.now())))
    conn.commit()
    return True

def get_balance(uid):
    get_user(uid)
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    return cursor.fetchone()[0]

# ===== JOIN CHECK =====
async def joined(uid, bot):
    try:
        m = await bot.get_chat_member(GROUP_ID, uid)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

async def force_join(update):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Tham gia", url=GROUP_LINK)]])
    await update.message.reply_text("❌ Bạn cần tham gia nhóm!", reply_markup=kb)

# ===== START =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_banned(uid):
        await update.message.reply_text("🚫 Bạn đã bị ban")
        return

    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    get_user(uid)

    # ref
    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                cursor.execute("SELECT refed FROM users WHERE user_id=?", (uid,))
                if cursor.fetchone()[0] == 0:
                    add_money(ref, 15000, "ref")
                    cursor.execute("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,))
                    cursor.execute("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
                    conn.commit()
        except:
            pass

    menu = ReplyKeyboardMarkup([
        ["💰 Số dư"],
        ["🛒 Rút tiền", "📮 Mời bạn"],
        ["📜 Lịch sử", "📞 Hỗ trợ"]
    ], resize_keyboard=True)

    await update.message.reply_text("🤖 Bot đã sẵn sàng", reply_markup=menu)

# ===== HANDLE =====
support_mode = {}

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text

    if is_banned(uid):
        await update.message.reply_text("🚫 Bạn bị cấm")
        return

    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    if txt == "💰 Số dư":
        await update.message.reply_text(f"{get_balance(uid)} VND")

    elif txt == "📮 Mời bạn":
        await update.message.reply_text(f"https://t.me/{BOT_USERNAME}?start={uid}")

    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("Nhập: /rut 30000")

    elif txt == "📜 Lịch sử":
        cursor.execute("SELECT * FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (uid,))
        data = cursor.fetchall()
        msg = "📜\n"
        for d in data:
            msg += f"{d[3]} | {d[1]} | {d[2]}\n"
        await update.message.reply_text(msg)

    elif txt == "📞 Hỗ trợ":
        support_mode[uid] = True
        await update.message.reply_text("📩 Nhập nội dung:")

    elif uid in support_mode:
        await ctx.bot.send_message(ADMIN_ID, f"📩 {uid}:\n{txt}\n/reply {uid}")
        del support_mode[uid]
        await update.message.reply_text("✅ Đã gửi")

# ===== RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT RUNNING...")
app.run_polRailw
