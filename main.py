from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import asyncio
import random  # thêm

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
        await update.message.reply_text("🚫 Bạn đã bị ban")
        return

    get_user(uid)

    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=?", (uid,)).fetchone()
                if row and row[0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
                        add_money(ref, 2000, "ref")
                        query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except:
            pass

    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    menu = ReplyKeyboardMarkup([
        ["💰 Số dư"],
        ["🎁 Checkin", "📮 Mời bạn"],
        ["🎲 Tài xỉu"],  # thêm
        ["🛒 Rút tiền", "📜 Lịch sử"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)

    await update.message.reply_text("🤖 Bot đã sẵn sàng", reply_markup=menu)

# ===== HANDLE =====
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

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        last = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()[0]

        if last == today:
            await update.message.reply_text("❌ Hôm nay nhận rồi")
            return

        add_money(uid, 1000, "checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await update.message.reply_text("🎉 +1000đ")

    elif txt == "📮 Mời bạn":
        msg = (
            "🎁 KIẾM TIỀN CÙNG BẠN BÈ\n"
            "1F = 4,000đ\n"
            "💸 Mời bạn bè nhận ngay +4,000đ mỗi lượt\n"
            "🏦 Min rút: 20,000đ\n\n"
            f"https://t.me/{BOT_USERNAME}?start={uid}"
        )
        await update.message.reply_text(msg, disable_web_page_preview=False)

    elif txt == "🎲 Tài xỉu":  # thêm
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 Tài", callback_data="tx_tai"),
                InlineKeyboardButton("🎲 Xỉu", callback_data="tx_xiu")
            ]
        ])
        await update.message.reply_text("Chọn cửa (cược mặc định 1000):", reply_markup=keyboard)

    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("Dùng: /rut bank stk ten amount")

    elif txt == "📜 Lịch sử":
        data = query("SELECT * FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (uid,)).fetchall()
        msg = "\n".join([f"{d[1]} | {d[2]}" for d in data])
        await update.message.reply_text(msg or "Không có")

    elif txt == "📞 Hỗ trợ":
        await update.message.reply_text("@RoGarden")

# ===== TÀI XỈU CALLBACK =====
async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()

    uid = query_btn.from_user.id

    if is_banned(uid):
        return await query_btn.message.reply_text("🚫 Bạn bị cấm")

    if not await joined(uid, ctx.bot):
        return await force_join(query_btn)

    choice = query_btn.data.split("_")[1]
    bet = 1000

    if get_balance(uid) < bet:
        return await query_btn.message.reply_text("Không đủ tiền")

    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if total >= 11 else "xiu"

    if choice == result:
        add_money(uid, bet, "taixiu_win")
        msg = "🎉 THẮNG"
    else:
        sub_money(uid, bet)
        msg = "💀 THUA"

    await query_btn.edit_message_text(
        f"🎲 {dice}\n📊 {total} ({result})\n{msg}\n💰 {get_balance(uid)}"
    )

# ===== RÚT =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if len(ctx.args) < 4:
        await update.message.reply_text("Sai cú pháp")
        return

    bank, stk, name = ctx.args[0], ctx.args[1], ctx.args[2]

    try:
        amount = int(ctx.args[3])
    except:
        await update.message.reply_text("Sai số tiền")
        return

    if amount < MIN_WITHDRAW:
        await update.message.reply_text("Min 12k")
        return

    now = datetime.now()
    last = query("SELECT last_withdraw FROM users WHERE user_id=?", (uid,)).fetchone()[0]

    if last:
        if (now - datetime.fromisoformat(last)) < timedelta(seconds=60):
            await update.message.reply_text("Đợi 60s")
            return

    if not sub_money(uid, amount):
        await update.message.reply_text("Không đủ tiền")
        return

    query("UPDATE users SET bank=?, stk=?, name=?, last_withdraw=? WHERE user_id=?",
          (bank, stk, name, now.isoformat(), uid))

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"),
            InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")
        ]
    ])

    await ctx.bot.send_message(
        ADMIN_ID,
        f"💸 Yêu cầu rút tiền\n\n👤 ID: {uid}\n💰 {amount}\n🏦 {bank} | {stk} | {name}",
        reply_markup=keyboard
    )

    await update.message.reply_text("Đã gửi yêu cầu")

# ===== CALLBACK =====
async def handle_withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()

    if query_btn.from_user.id != ADMIN_ID:
        return

    action, uid, amount = query_btn.data.split("_")
    uid = int(uid)
    amount = int(amount)

    if action == "ok":
        await ctx.bot.send_message(uid, f"✅ Rút {amount} thành công")
        await query_btn.edit_message_text("✅ ĐÃ DUYỆT")

    elif action == "no":
        add_money(uid, amount, "refund")
        await ctx.bot.send_message(uid, f"❌ Bị từ chối")
        await query_btn.edit_message_text("❌ ĐÃ TỪ CHỐI")
        # ===== ADMIN COMMANDS (FIX LỖI) =====
async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(ctx.args[0])
        amt = int(ctx.args[1])
        add_money(uid, amt, "admin_add")
        await update.message.reply_text("Đã cộng tiền")
    except:
        await update.message.reply_text("Sai cú pháp /add uid amount")

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(ctx.args[0])
        amt = int(ctx.args[1])
        sub_money(uid, amt)
        await update.message.reply_text("Đã trừ tiền")
    except:
        await update.message.reply_text("Sai cú pháp /sub uid amount")

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text("Đã ban")
    except:
        await update.message.reply_text("Sai cú pháp /ban uid")

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text("Đã unban")
    except:
        await update.message.reply_text("Sai cú pháp /unban uid")

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"Tổng user: {total}")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    users = query("SELECT user_id FROM users").fetchall()
    msg = "\n".join([str(u[0]) for u in users[:50]])
    await update.message.reply_text(msg or "Không có user")

# ===== HISTORY ADMIN FIX =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT * FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (uid,)).fetchall()
    msg = "\n".join([f"{d[1]} | {d[2]}" for d in data])
    await update.message.reply_text(msg or "Không có")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = query("SELECT * FROM history ORDER BY rowid DESC LIMIT 20").fetchall()
    msg = "\n".join([f"{d[0]} | {d[1]} | {d[2]}" for d in data])
    await update.message.reply_text(msg or "Không có")

# ===== CALLBACK HISTORY (TRÁNH LỖI) =====
async def history_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Chưa dùng")

async def history_all_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Chưa dùng")

# ===== RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("rut", rut))

app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("sub", sub))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all", all_user))

app.add_handler(CommandHandler("his", history_pro))
app.add_handler(CommandHandler("hisall", history_all_admin))

app.add_handler(CallbackQueryHandler(handle_withdraw_action, pattern="^(ok_|no_)"))
app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))  # thêm
app.add_handler(CallbackQueryHandler(history_callback, pattern="^his_"))
app.add_handler(CallbackQueryHandler(history_all_callback, pattern="^all_"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT PRO RUNNING...")
app.run_polling()
