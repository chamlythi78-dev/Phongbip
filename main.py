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

# Khởi tạo bảng
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

# ===== HÀM BỔ TRỢ (UTILITIES) =====
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
    await update.message.reply_text("❌ Bạn chưa tham gia nhóm! Hãy tham gia để tiếp tục sử dụng bot:", 
                                   reply_markup=InlineKeyboardMarkup(buttons))

# ===== LỆNH ADMIN =====
async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward = int(ctx.args[0])
        uses = int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"🎁 Code: {code}\n💰 Thưởng: {reward:,}đ\n🔁 Lượt: {uses}")
    except:
        await update.message.reply_text("Cú pháp: /taocode [số tiền] [số lượt]")

# ===== LỆNH START =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid):
        await update.message.reply_text("🚫 Bạn đã bị cấm khỏi hệ thống.")
        return

    get_user(uid)

    # Xử lý giới thiệu (Ref)
    if ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != uid:
                row = query("SELECT refed FROM users WHERE user_id=?", (uid,)).fetchone()
                if row and row[0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
                        add_money(ref, 2000, f"Mời bạn {uid}")
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

    await update.message.reply_text("🤖 Chào mừng bạn đến với hệ thống kiếm tiền!", reply_markup=menu)

# ===== XỬ LÝ TIN NHẮN CHÍNH (FIXED LỖI TẠI ĐÂY) =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    if not txt: return

    if is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    if txt == "💰 Số dư":
        await update.message.reply_text(f"💳 Số dư khả dụng: {get_balance(uid):,} VND")

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        last = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        if last == today:
            return await update.message.reply_text("❌ Hôm nay bạn đã nhận thưởng rồi!")
        add_money(uid, 10000, "checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await update.message.reply_text("🎉 Chúc mừng! +10,000đ vào tài khoản.")

    elif txt == "📮 Mời bạn":
        msg = (
            "🎁 KIẾM TIỀN CÙNG BẠN BÈ\n"
            "💰 Mỗi lượt mời thành công: +2,000đ\n"
            "🏦 Min rút: 37,000đ\n\n"
            f"🔗 Link của bạn: https://t.me/{BOT_USERNAME}?start={uid}"
        )
        await update.message.reply_text(msg)

    elif txt == "🎲 Tài xỉu":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎲 Tài", callback_data="tx_tai"),
            InlineKeyboardButton("🎲 Xỉu", callback_data="tx_xiu")
        ]])
        await update.message.reply_text("Chọn cửa (Cược mặc định: 10,000đ):", reply_markup=keyboard)

    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("📝 Cú pháp rút tiền:\n`/rut [ngân_hàng] [stk] [tên_chủ_thẻ] [số_tiền]`", parse_mode="Markdown")

    elif txt == "📜 Lịch sử":
        data = query("SELECT amount, note FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (uid,)).fetchall()
        msg = "📜 5 GIAO DỊCH GẦN NHẤT:\n" + "\n".join([f"{'✅' if d[0]>0 else '❌'} {d[0]:,}đ | {d[1]}" for d in data])
        await update.message.reply_text(msg if data else "Bạn chưa có lịch sử giao dịch.")

    elif txt == "📞 Hỗ trợ":
        await update.message.reply_text("Mọi thắc mắc liên hệ Admin: @RoGarden")

    elif txt.startswith("/code"):
        try:
            parts = txt.split(" ")
            if len(parts) < 2:
                return await update.message.reply_text("❌ Cú pháp: /code ABC123")
            
            code_input = parts[1].strip().upper()
            data = query("SELECT * FROM codes WHERE code=?", (code_input,)).fetchone()

            if not data:
                return await update.message.reply_text("❌ Code không chính xác.")

            reward, uses = data[1], data[2]
            if uses <= 0:
                return await update.message.reply_text("❌ Code đã hết lượt sử dụng.")

            add_money(uid, reward, f"Sử dụng code {code_input}")
            query("UPDATE codes SET uses=uses-1 WHERE code=?", (code_input,))
            await update.message.reply_text(f"🎉 Thành công! Bạn đã nhận được {reward:,}đ")
        except Exception as e:
            await update.message.reply_text("❌ Lỗi hệ thống khi nhập code.")

# ===== MINI GAME TÀI XỈU =====
async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    uid = query_btn.from_user.id
    if is_banned(uid): return
    
    await query_btn.answer()
    choice = query_btn.data.split("_")[1]
    bet = 10000

    if get_balance(uid) < bet:
        return await query_btn.message.reply_text("❌ Bạn không đủ 10,000đ để chơi.")

    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if total >= 11 else "xiu"

    if choice == result:
        add_money(uid, bet, "Thắng Tài Xỉu")
        msg = f"🎉 KẾT QUẢ: {total} ({result.upper()}) - BẠN THẮNG!"
    else:
        sub_money(uid, bet)
        msg = f"💀 KẾT QUẢ: {total} ({result.upper()}) - BẠN THUA!"

    await query_btn.edit_message_text(f"🎲 Xúc xắc: {dice}\n{msg}\n💰 Số dư: {get_balance(uid):,}đ")

# ===== XỬ LÝ RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(ctx.args) < 4:
        return await update.message.reply_text("❌ Sai cú pháp! /rut [bank] [stk] [tên] [tiền]")

    bank, stk, name, amount_str = ctx.args[0], ctx.args[1], ctx.args[2], ctx.args[3]
    try:
        amount = int(amount_str)
    except:
        return await update.message.reply_text("❌ Số tiền phải là con số.")

    if amount < MIN_WITHDRAW:
        return await update.message.reply_text(f"❌ Số tiền rút tối thiểu là {MIN_WITHDRAW:,}đ")

    if not sub_money(uid, amount):
        return await update.message.reply_text("❌ Số dư không đủ.")

    now = datetime.now()
    query("UPDATE users SET bank=?, stk=?, name=?, last_withdraw=? WHERE user_id=?",
          (bank, stk, name, now.isoformat(), uid))

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")
    ]])

    await ctx.bot.send_message(ADMIN_ID, f"💸 YÊU CẦU RÚT TIỀN\n👤 ID: {uid}\n💰: {amount:,}đ\n🏦: {bank} | {stk} | {name}", reply_markup=keyboard)
    await update.message.reply_text("✅ Yêu cầu đã được gửi tới Admin. Vui lòng chờ duyệt!")

async def handle_withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    if query_btn.from_user.id != ADMIN_ID: return
    
    action, uid, amount = query_btn.data.split("_")
    uid, amount = int(uid), int(amount)

    if action == "ok":
        await ctx.bot.send_message(uid, f"✅ Yêu cầu rút {amount:,}đ của bạn đã được duyệt!")
        await query_btn.edit_message_text(f"✅ ĐÃ DUYỆT RÚT {amount:,}đ")
    else:
        add_money(uid, amount, "Hoàn tiền rút")
        await ctx.bot.send_message(uid, f"❌ Yêu cầu rút {amount:,}đ của bạn bị từ chối. Tiền đã được hoàn lại.")
        await query_btn.edit_message_text(f"❌ ĐÃ TỪ CHỐI RÚT {amount:,}đ")

# ===== ADMIN TOOLS =====
async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uid = int(ctx.args[0])
    query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
    await update.message.reply_text("Đã ban.")

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 Tổng số người dùng: {total}")

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("stats", stats))

app.add_handler(CallbackQueryHandler(handle_withdraw_action, pattern="^(ok_|no_)"))
app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("--- BOT ĐANG CHẠY ---")
app.run_polling()
