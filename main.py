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
TOKEN = os.getenv("TOKEN")
ADMIN_ID = 8619503816
GROUP_IDS = [-1003663678808]
GROUP_LINKS = ["https://t.me/thanhall"]
BOT_USERNAME = "mbbankstk2026bot "
MIN_WITHDRAW = 37000


# ===== DATABASE SETUP =====
conn = sqlite3.connect("bot.db", check_same_thread=False)

def query(q, args=()):
    cur = conn.cursor()
    cur.execute(q, args)
    conn.commit()
    return cur

# Khởi tạo toàn bộ các bảng
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
    query("INSERT INTO history VALUES(?,?,?,?)", (uid, -amt, "system", str(datetime.now())))
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

# ===== LỆNH NHẬP CODE =====
async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return
    
    if not ctx.args:
        await update.message.reply_text("❌ Cú pháp: `/code [Mã]`")
        return

    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=?", (code_str,)).fetchone()

    if not data:
        await update.message.reply_text("❌ Mã không tồn tại.")
        return

    reward, uses = data[1], data[2]
    if uses <= 0:
        await update.message.reply_text("❌ Mã đã hết lượt dùng.")
        return

    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=?", (code_str,))
    await update.message.reply_text(f"🎉 **THÀNH CÔNG!**\n\n💰 Nhận được: `+{reward:,}đ`", parse_mode="Markdown")

# ===== ADMIN COMMANDS =====
async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tính năng Reply: /rep [ID] [Nội dung]"""
    if update.effective_user.id != ADMIN_ID: return
    if len(ctx.args) < 2:
        return await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")
    
    try:
        target_id = int(ctx.args[0])
        text = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=target_id, text=f"🔔 **PHẢN HỒI TỪ ADMIN:**\n\n📩 {text}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã gửi phản hồi tới `{target_id}`")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")

async def send_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = " ".join(ctx.args)
    if not msg: return await update.message.reply_text("❌ Cú pháp: `/send [Nội dung]`")
    users = query("SELECT user_id FROM users").fetchall()
    s, f = 0, 0
    status = await update.message.reply_text(f"🚀 Đang gửi tới {len(users)} người...")
    for u in users:
        try:
            await ctx.bot.send_message(chat_id=u[0], text=msg, parse_mode="Markdown")
            s += 1
            await asyncio.sleep(0.05)
        except: f += 1
    await status.edit_text(f"✅ Hoàn tất!\n🟢 Thành công: {s}\n🔴 Thất bại: {f}")

async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ **CODE:** `{code}`\n💰 Thưởng: `{reward:,}đ`\n🔁 Lượt: `{uses}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Cú pháp: `/taocode [tiền] [lượt]`")

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho `{uid}`")
    except: pass

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt)
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của `{uid}`")
    except: pass

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text(f"🚫 Chặn `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ Mở chặn `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 Tổng user: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = query("SELECT user_id FROM users ORDER BY rowid DESC LIMIT 50").fetchall()
    msg = "👥 **DANH SÁCH USER:**\n\n" + "\n".join([f"`{u[0]}`" for u in users])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = query("SELECT * FROM history ORDER BY rowid DESC LIMIT 20").fetchall()
    msg = "🌐 **LỊCH SỬ HỆ THỐNG:**\n\n"
    for d in data: msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ===== START & REF =====
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
                        add_money(ref, 3000, "Ref bonus")
                        query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except: pass
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return
    menu = ReplyKeyboardMarkup([["💰 Số dư"], ["🎁 Checkin", "📮 Mời bạn"], ["🎲 Tài xỉu"], ["🛒 Rút tiền", "📜 Lịch sử"], ["📞 Hỗ trợ"]], resize_keyboard=True)
    await update.message.reply_text(f"👋 Chào mừng **{update.effective_user.first_name}**!", reply_markup=menu, parse_mode="Markdown")

# ===== HANDLE MENU & GAME =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

        if txt == "💰 Số dư":
        await update.message.reply_text(f"💳 **SỐ DƯ:** `{get_balance(uid):,}` VNĐ", parse_mode="Markdown")

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        row = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        last = row[0] if row else None
        
        if last == today:
            return await update.message.reply_text("❌ Hôm nay bạn đã điểm danh rồi!")
        
        add_money(uid, 10000, "Daily Checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await update.message.reply_text("🎉 **CHECKIN:** `+10,000đ`", parse_mode="Markdown")

    elif txt == "📮 Mời bạn":
        await update.message.reply_text(
            f"🚀 **LINK MỜI:**\n`https://t.me/{BOT_USERNAME}?start={uid}`\n\n"
            f"💰 **Mời 1f = 3.000đ**\n"
            f"💳 **Min Rút Tiền = 37.000đ**",
            parse_mode="Markdown")


    elif txt == "🎲 Tài xỉu":
        await update.message.reply_text("🎮 Nhập số tiền muốn cược:", parse_mode="Markdown")
        ctx.user_data['waiting_bet'] = True
    elif txt.isdigit() and ctx.user_data.get('waiting_bet'):
        amt = int(txt)
        if amt < 1000 or get_balance(uid) < amt:
            return await update.message.reply_text("❌ Số dư không đủ hoặc cược quá thấp!")
        ctx.user_data['waiting_bet'] = False
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 TÀI", callback_data=f"tx_tai_{amt}"), InlineKeyboardButton("🎲 XỈU", callback_data=f"tx_xiu_{amt}")]])
        await update.message.reply_text(f"💰 Cược: `{amt:,}đ`. Chọn cửa:", reply_markup=kb, parse_mode="Markdown")
    elif txt == "🛒 Rút tiền":
        await update.message.reply_text("🏦 Cú pháp: `/rut [Bank] [STK] [Tên] [Tiền]`", parse_mode="Markdown")
    elif txt == "📜 Lịch sử":
        data = query("SELECT amount, note FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (uid,)).fetchall()
        msg = "📜 **LỊCH SỬ:**\n\n" + "\n".join([f"{'➕' if d[0]>0 else '➖'} `{d[0]:,}đ` | {d[1]}" for d in data])
        await update.message.reply_text(msg or "Trống", parse_mode="Markdown")
    elif txt == "📞 Hỗ trợ":
        await update.message.reply_text("📩 Admin: @RoGarden")

# ===== TÀI XỈU CALLBACK =====
async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if is_banned(uid): return
    _, choice, amt = q.data.split("_")
    amt = int(amt)
    if get_balance(uid) < amt: return
    dice = [random.randint(1, 6) for _ in range(3)]
    res = "tai" if sum(dice) >= 11 else "xiu"
    if choice == res:
        add_money(uid, amt, f"Thắng TX {amt}")
        msg = "🎉 **THẮNG!**"
    else:
        sub_money(uid, amt)
        msg = "💀 **THUA!**"
    await q.edit_message_text(f"🎲 Kết quả: `{dice}` ({sum(dice)} - {res.upper()})\n💰 Cược: `{amt:,}đ`\n{msg}", parse_mode="Markdown")

# ===== RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(ctx.args) < 4: return await update.message.reply_text("❌ Thiếu thông tin!")
    try:
        b, s, n, a = ctx.args[0], ctx.args[1], ctx.args[2], int(ctx.args[3])
        if a >= MIN_WITHDRAW and sub_money(uid, a):
            query("UPDATE users SET bank=?, stk=?, name=?, last_withdraw=? WHERE user_id=?", (b,s,n,datetime.now().isoformat(),uid))
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{a}"), InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{a}")]])
            await ctx.bot.send_message(ADMIN_ID, f"🔔 **RÚT TIỀN:** `{uid}`\n💰 `{a:,}đ`\n🏦 `{b}|{s}|{n}`", reply_markup=kb, parse_mode="Markdown")
            await update.message.reply_text("✅ Đã gửi yêu cầu!")
        else: await update.message.reply_text("❌ Không đủ tiền hoặc sai min rút!")
    except: pass

async def handle_withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID: return
    act, uid, amt = q.data.split("_")
    uid, amt = int(uid), int(amt)
    if act == "ok":
        await ctx.bot.send_message(uid, f"✅ Rút `{amt:,}đ` thành công!")
        await q.edit_message_text(f"✅ DUYỆT ID {uid}")
    else:
        add_money(uid, amt, "Hoàn rút")
        await ctx.bot.send_message(uid, "❌ Rút tiền bị từ chối!")
        await q.edit_message_text(f"❌ TỪ CHỐI ID {uid}")

# ===== LỊCH SỬ /his =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (uid,)).fetchall()
    msg = "📜 **CHI TIẾT:**\n\n" + "\n".join([f"`{d[0]:,}đ` | {d[1]}" for d in data])
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

# ===== KHỞI CHẠY =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("code", nhap_code))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("sub", sub))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all", all_user))
app.add_handler(CommandHandler("his", history_pro))
app.add_handler(CommandHandler("hisall", history_all_admin))
app.add_handler(CommandHandler("send", send_all))
app.add_handler(CommandHandler("rep", reply_user)) # Lệnh reply mới

app.add_handler(CallbackQueryHandler(handle_withdraw_action, pattern="^(ok_|no_)"))
app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
print("BOT ĐÃ SẴN SÀNG!")
app.run_polling()
