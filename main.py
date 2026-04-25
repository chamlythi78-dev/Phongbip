from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
import os
import asyncio
import random

def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = "8622389687:AAGqQoYBhmmsQI65k5Vqv9uTjTe2YpVasFk"
ADMIN_ID = 8619503816
GROUP_IDS = [-1003663678808]
GROUP_LINKS = ["https://t.me/thanhall"]
BOT_USERNAME = "loclastk2026bot"
MIN_WITHDRAW = 37000

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
    bank TEXT,
    stk TEXT,
    name TEXT,
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

def sub_money(uid, amt):
    get_user(uid)
    bal = get_balance(uid)
    if bal < amt:
        return False
    query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, uid))
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, "withdraw", str(datetime.now())))
    return True

# ===== JOIN CHECK =====
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
    buttons = [[InlineKeyboardButton(f"📢 Tham Gia Nhóm {i+1}", url=link)] for i, link in enumerate(GROUP_LINKS)]
    await update.message.reply_text(
        "⚠️ **BẠN CHƯA THAM GIA NHÓM**\n\nVui lòng tham gia các nhóm dưới đây để kích hoạt tính năng của Bot!",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ===== ADMIN TAO CODE =====
async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward = int(ctx.args[0])
        uses = int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ **TẠO CODE THÀNH CÔNG**\n\n🎁 Code: `{code}`\n💰 Thưởng: `{reward:,}đ`\n🔁 Lượt: `{uses}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Sai cú pháp: `/taocode [số tiền] [lượt dùng]`", parse_mode="Markdown")

# ===== START =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid):
        await update.message.reply_text("🚫 Tài khoản của bạn đã bị cấm.")
        return

    get_user(uid)

    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=?", (uid,)).fetchone()
                if row and row[0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
                        add_money(ref, 2000, "Ref bonus")
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
        ["🎲 Tài xỉu"],
        ["🛒 Rút tiền", "📜 Lịch sử"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)

    await update.message.reply_text(
        f"👋 Chào mừng **{update.effective_user.first_name}**!\nBot đã sẵn sàng phục vụ bạn. Chọn một tính năng bên dưới để bắt đầu.",
        reply_markup=menu,
        parse_mode="Markdown"
    )

# ===== HANDLE MESSAGES =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    if not txt: return

    if is_banned(uid):
        await update.message.reply_text("🚫 Bạn đã bị cấm.")
        return

    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    if txt == "💰 Số dư":
        bal = get_balance(uid)
        await update.message.reply_text(f"💳 **SỐ DƯ CỦA BẠN:**\n\n💰 `{bal:,} VND`", parse_mode="Markdown")

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        res = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        last = res[0] if res else None

        if last == today:
            await update.message.reply_text("❌ Hôm nay bạn đã điểm danh rồi. Hẹn gặp lại vào ngày mai!")
            return

        add_money(uid, 10000, "Daily Checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await update.message.reply_text("🎉 **CHECKIN THÀNH CÔNG!**\n\nBạn nhận được: `+10,000đ`", parse_mode="Markdown")

    elif txt == "📮 Mời bạn":
        msg = (
            "🚀 **KIẾM TIỀN TỪ LƯỢT MỜI**\n\n"
            "💵 1F = `3,000đ`\n"
            "💸 Thưởng thêm: `+4,000đ` cho mỗi lượt mời thành công.\n"
            "🏦 Ngưỡng rút tiền tối thiểu: `37,000đ`\n\n"
            f"🔗 **Link giới thiệu của bạn:**\n`https://t.me/{BOT_USERNAME}?start={uid}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif txt == "🎲 Tài xỉu":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎲 TÀI", callback_data="tx_tai"),
            InlineKeyboardButton("🎲 XỈU", callback_data="tx_xiu")
        ]])
        await update.message.reply_text("🎮 **MINI GAME TÀI XỈU**\n\nChọn cửa bạn dự đoán (Cược mặc định: `10,000đ`)", reply_markup=keyboard, parse_mode="Markdown")

    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("🏦 **HƯỚNG DẪN RÚT TIỀN**\n\nCú pháp: `/rut [Ngân_hàng] [STK] [Tên_chủ_thẻ] [Số_tiền]`\n\nVí dụ: `/rut MBBank 0123456789 NGUYEN_VAN_A 50000`", parse_mode="Markdown")

    elif txt == "📜 Lịch sử":
        data = query("SELECT amount, note FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (uid,)).fetchall()
        if not data:
            await update.message.reply_text("📭 Bạn chưa có giao dịch nào.")
        else:
            msg = "📜 **LỊCH SỬ GIAO DỊCH GẦN NHẤT:**\n\n"
            for d in data:
                icon = "➕" if d[0] > 0 else "➖"
                msg += f"{icon} `{d[0]:,}đ` | {d[1]}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")

    elif txt == "📞 Hỗ trợ":
        await update.message.reply_text("📩 Mọi vấn đề cần giải đáp vui lòng liên hệ Admin: @RoGarden")
        
    elif txt.startswith("/code"):
        try:
            parts = txt.split(" ")
            if len(parts) < 2: return await update.message.reply_text("❌ Vui lòng nhập mã code. VD: `/code ABC123`", parse_mode="Markdown")
            
            code_str = parts[1].strip().upper()
            data = query("SELECT * FROM codes WHERE code=?", (code_str,)).fetchone()

            if not data:
                return await update.message.reply_text("❌ Mã quà tặng không tồn tại hoặc đã hết hạn.")

            reward, uses = data[1], data[2]
            if uses <= 0:
                return await update.message.reply_text("❌ Mã quà tặng này đã hết lượt sử dụng.")

            add_money(uid, reward, f"Code: {code_str}")
            query("UPDATE codes SET uses=uses-1 WHERE code=?", (code_str,))
            await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\nSố dư đã được cộng: `+{reward:,}đ`", parse_mode="Markdown")
        except:
            await update.message.reply_text("❌ Lỗi hệ thống. Thử lại sau!")

# ===== MINIGAME CALLBACK =====
async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()
    uid = query_btn.from_user.id
    if is_banned(uid): return

    choice = query_btn.data.split("_")[1]
    bet = 10000
    if get_balance(uid) < bet:
        return await query_btn.message.reply_text("❌ Bạn không đủ số dư (10,000đ) để chơi.")

    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if total >= 11 else "xiu"

    if choice == result:
        add_money(uid, bet, "Thắng Tài Xỉu")
        msg = "🎉 **BẠN ĐÃ THẮNG!**"
    else:
        sub_money(uid, bet)
        msg = "💀 **BẠN ĐÃ THUA!**"

    await query_btn.edit_message_text(
        f"🎲 Kết quả: `{dice[0]}` - `{dice[1]}` - `{dice[2]}`\n📊 Tổng điểm: `{total}` ({result.upper()})\n\n{msg}\n💰 Số dư hiện tại: `{get_balance(uid):,}đ`",
        parse_mode="Markdown"
    )

# ===== WITHDRAW =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(ctx.args) < 4:
        return await update.message.reply_text("❌ Sai cú pháp! Hãy gõ: `/rut [Ngân_hàng] [STK] [Tên] [Số_tiền]`", parse_mode="Markdown")

    bank, stk, name = ctx.args[0], ctx.args[1], ctx.args[2]
    try:
        amount = int(ctx.args[3])
    except:
        return await update.message.reply_text("❌ Số tiền phải là một con số hợp lệ.")

    if amount < MIN_WITHDRAW:
        return await update.message.reply_text(f"❌ Số tiền rút tối thiểu là `{MIN_WITHDRAW:,}đ`", parse_mode="Markdown")

    now = datetime.now()
    res = query("SELECT last_withdraw FROM users WHERE user_id=?", (uid,)).fetchone()
    last = res[0] if res else None
    if last and (now - datetime.fromisoformat(last)) < timedelta(seconds=60):
        return await update.message.reply_text("⏳ Thao tác quá nhanh! Vui lòng đợi 60 giây giữa mỗi yêu cầu rút tiền.")

    if not sub_money(uid, amount):
        return await update.message.reply_text("❌ Số dư tài khoản không đủ để thực hiện giao dịch này.")

    query("UPDATE users SET bank=?, stk=?, name=?, last_withdraw=? WHERE user_id=?", (bank, stk, name, now.isoformat(), uid))

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")
    ]])

    await ctx.bot.send_message(ADMIN_ID, f"🔔 **YÊU CẦU RÚT TIỀN MỚI**\n\n👤 ID: `{uid}`\n💰 Số tiền: `{amount:,}đ`\n🏦 Bank: `{bank}` | `{stk}` | `{name}`", reply_markup=keyboard, parse_mode="Markdown")
    await update.message.reply_text("✅ Yêu cầu rút tiền của bạn đã được gửi. Admin sẽ kiểm tra và duyệt sớm nhất!")

async def handle_withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()
    if query_btn.from_user.id != ADMIN_ID: return

    action, uid, amount = query_btn.data.split("_")
    uid, amount = int(uid), int(amount)

    if action == "ok":
        await ctx.bot.send_message(uid, f"✅ Chúc mừng! Yêu cầu rút `{amount:,}đ` của bạn đã được duyệt thành công.", parse_mode="Markdown")
        await query_btn.edit_message_text(f"✅ ĐÃ DUYỆT RÚT: `{amount:,}đ` cho ID `{uid}`", parse_mode="Markdown")
    elif action == "no":
        add_money(uid, amount, "Refund Withdraw")
        await ctx.bot.send_message(uid, f"❌ Rất tiếc, yêu cầu rút `{amount:,}đ` đã bị từ chối. Tiền đã được hoàn lại vào ví.", parse_mode="Markdown")
        await query_btn.edit_message_text(f"❌ ĐÃ TỪ CHỐI RÚT: `{amount:,}đ` cho ID `{uid}`", parse_mode="Markdown")

# ===== FULL ADMIN COMMANDS =====
async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng tiền")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho ID `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("Cú pháp: /add [uid] [amount]")

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt)
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của ID `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("Cú pháp: /sub [uid] [amount]")

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("Cú pháp: /ban [uid]")

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("Cú pháp: /unban [uid]")

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 **THỐNG KÊ HỆ THỐNG**\n\n👥 Tổng số người dùng: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = query("SELECT user_id FROM users").fetchall()
    msg = "👥 **DANH SÁCH USER (50 gần nhất):**\n\n" + "\n".join([f"`{u[0]}`" for u in users[:50]])
    await update.message.reply_text(msg or "Chưa có user nào.", parse_mode="Markdown")

async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (uid,)).fetchall()
    if not data:
        await update.message.reply_text("📭 Trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT:**\n\n"
        for d in data:
            msg += f"💰 `{d[0]:,}đ` | {d[1]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = query("SELECT * FROM history ORDER BY rowid DESC LIMIT 20").fetchall()
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    for d in data:
        msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def history_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Tính năng đang hoàn thiện")

async def history_all_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Tính năng đang hoàn thiện")

# ===== APP RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("sub", sub))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all", all_user))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("his", history_pro))
app.add_handler(CommandHandler("hisall", history_all_admin))

app.add_handler(CallbackQueryHandler(handle_withdraw_action, pattern="^(ok_|no_)"))
app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))
app.add_handler(CallbackQueryHandler(history_callback, pattern="^his_"))
app.add_handler(CallbackQueryHandler(history_all_callback, pattern="^all_"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT PRO RUNNING...")
app.run_polling()
