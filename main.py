from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import asyncio
import random

# ===== CONFIG =====
TOKEN = "8622389687:AAGqQoYBhmmsQI65k5Vqv9uTjTe2YpVasFk"
ADMIN_ID = 8619503816

GROUP_IDS = [-1003663678808]
GROUP_LINKS = ["https://t.me/thanhall"]

BOT_USERNAME = "loclastk2026bot"
MIN_WITHDRAW = 12000

# ===== DB =====
conn = sqlite3.connect("bot.db", check_same_thread=False)

def query(q, args=()):
    cur = conn.cursor()
    cur.execute(q, args)
    conn.commit()
    return cur

query("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    refs INTEGER DEFAULT 0,
    refed INTEGER DEFAULT 0,
    bank TEXT,
    stk TEXT,
    name TEXT,
    last_checkin TEXT,
    last_withdraw TEXT
)
""")

query("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, amount INTEGER, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")

# ===== GAME DATA =====
user_bets = {}

# ===== USER =====
def get_user(uid):
    if not query("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        query("INSERT INTO users(user_id) VALUES(?)", (uid,))

def is_banned(uid):
    return query("SELECT 1 FROM banned WHERE user_id=?", (uid,)).fetchone() is not None

def add_money(uid, amt, note):
    get_user(uid)
    query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, amt, note, str(datetime.now())))

def sub_money(uid, amt):
    get_user(uid)
    bal = query("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    if bal < amt:
        return False
    query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, "withdraw", str(datetime.now())))
    return True

def get_balance(uid):
    get_user(uid)
    return query("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]

# ===== JOIN =====
async def joined(uid, bot):
    for gid in GROUP_IDS:
        try:
            m = await bot.get_chat_member(gid, uid)
            if m.status not in ["left", "kicked"]:
                return True
        except:
            pass
    return False

async def force_join(update):
    buttons = [[InlineKeyboardButton(f"📢 Nhóm {i+1}", url=link)] for i, link in enumerate(GROUP_LINKS)]
    await update.message.reply_text("❌ Tham gia nhóm để dùng bot!", reply_markup=InlineKeyboardMarkup(buttons))

# ===== START =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_banned(uid):
        return await update.message.reply_text("🚫 Bạn đã bị ban")

    get_user(uid)

    if not await joined(uid, ctx.bot):
        return await force_join(update)

    menu = ReplyKeyboardMarkup([
        ["💰 Số dư"],
        ["🎁 Checkin", "📮 Mời bạn"],
        ["🎲 Tài xỉu"],
        ["🛒 Rút tiền", "📜 Lịch sử"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)

    await update.message.reply_text("🤖 Bot đã sẵn sàng", reply_markup=menu)

# ===== HANDLE =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text

    if is_banned(uid):
        return await update.message.reply_text("🚫 Bạn bị cấm")

    if not await joined(uid, ctx.bot):
        return await force_join(update)

    if txt == "💰 Số dư":
        await update.message.reply_text(f"{get_balance(uid)} VND")

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        last = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()[0]

        if last == today:
            return await update.message.reply_text("❌ Hôm nay nhận rồi")

        add_money(uid, 1000, "checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await update.message.reply_text("🎉 +1000đ")

    elif txt == "🎲 Tài xỉu":
        user_bets[uid] = {}
        await update.message.reply_text("💰 Nhập số tiền cược:")

    elif uid in user_bets and "amount" not in user_bets[uid]:
        try:
            bet = int(txt)
            if bet <= 0:
                return await update.message.reply_text("Số tiền không hợp lệ")

            if get_balance(uid) < bet:
                return await update.message.reply_text("Không đủ tiền")

            user_bets[uid]["amount"] = bet

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎲 Tài", callback_data="tx_tai"),
                    InlineKeyboardButton("🎲 Xỉu", callback_data="tx_xiu")
                ]
            ])
            await update.message.reply_text(f"Đặt {bet}đ - chọn cửa:", reply_markup=keyboard)
        except:
            await update.message.reply_text("Nhập số hợp lệ")

    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("Dùng: /rut bank stk ten amount")

# ===== TÀI XỈU =====
async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    if uid not in user_bets:
        return await q.message.reply_text("Chưa cược")

    bet = user_bets[uid]["amount"]
    choice = q.data.split("_")[1]

    # 🎯 nhà cái win 65%
    if random.random() < 0.65:
        result = "xiu" if choice == "tai" else "tai"
    else:
        result = choice

    while True:
        dice = [random.randint(1, 6) for _ in range(3)]
        total = sum(dice)
        real = "tai" if total >= 11 else "xiu"
        if real == result:
            break

    if choice == result:
        add_money(uid, bet, "win")
        msg = "🎉 THẮNG"
    else:
        sub_money(uid, bet)
        msg = "💀 THUA"

    del user_bets[uid]

    await q.edit_message_text(
        f"🎲 {dice}\n📊 {total} ({result})\n{msg}\n💰 {get_balance(uid)}"
    )

# ===== RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("rut", rut))

app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT PRO RUNNING...")
app.run_polling()
