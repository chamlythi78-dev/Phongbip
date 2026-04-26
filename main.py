herefrom telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
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
BOT_USERNAME = "mbbankstk2026bot" # Đã xóa khoảng trắng thừa
MIN_WITHDRAW = 37000

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

# ===== LOGIC GAMES ANIMATION =====
async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {choice_code}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")

    msg_dice = await update.message.reply_dice(emoji="🎲")
    value = msg_dice.dice.value
    await asyncio.sleep(3.5)

    is_chan, is_tai = (value % 2 == 0), (value >= 4)
    win = False
    c = choice_code.upper()
    if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or \
       (c == "XXX" and not is_tai) or (c == "XXT" and is_tai): win = True

    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: status = f"❌ **THUA**"
    await update.message.reply_text(f"🎲 Kết quả: **{value}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_emoji_game(update: Update, game_type, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {game_type}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")

    emojis = {"SLOT": "🎰", "BALL": "⚽️", "RO": "🏀"}
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
async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(ctx.args[0])
        u = query("SELECT balance, refs, bank, stk, name, last_checkin FROM users WHERE user_id=?", (target_id,)).fetchone()
        if not u:
            return await update.message.reply_text("❌ Không tìm thấy người dùng này.")
        
        msg = (
            f"📂 **THÔNG TIN CHI TIẾT USER `{target_id}`**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"👥 Số người mời: `{u[1]}`\n"
            f"🏛 Ngân hàng: `{u[2] or 'Chưa cập nhật'}`\n"
            f"💳 Số tài khoản: `{u[3] or 'Chưa cập nhật'}`\n"
            f"👤 Tên chủ thẻ: `{u[4] or 'Chưa cập nhật'}`\n"
            f"📅 Điểm danh gần nhất: `{u[5] or 'Chưa có'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/info [ID]`")

async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ **TẠO CODE THÀNH CÔNG**\n\n🎁 Code: `{code}`\n💰 Thưởng: `{reward:,}đ`\n🔁 Lượt: `{uses}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/taocode [số tiền] [lượt dùng]`")

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
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👥 Tổng số người dùng: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = query("SELECT user_id FROM users ORDER BY rowid DESC LIMIT 50").fetchall()
    msg = "👥 **DANH SÁCH USER (50 gần nhất):**\n\n" + "\n".join([f"`{u[0]}`" for u in users])
    await update.message.reply_text(msg or "Chưa có user nào.", parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = query("SELECT * FROM history ORDER BY rowid DESC LIMIT 20").fetchall()
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    for d in data:
        msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not ctx.args:
        return await update.message.reply_text("❌ Cú pháp: `/send [nội dung]`")
    msg_to_send = " ".join(ctx.args)
    users = query("SELECT user_id FROM users").fetchall()
    sent, failed = 0, 0
    status_msg = await update.message.reply_text(f"🚀 Đang gửi tới {len(users)} người...")
    for user in users:
        try:
            await ctx.bot.send_message(chat_id=user[0], text=f"🔔 **THÔNG BÁO MỚI**\n\n{msg_to_send}", parse_mode="Markdown")
            sent += 1
            if sent % 20 == 0: await asyncio.sleep(1)
        except: failed += 1
    await status_msg.edit_text(f"✅ **HOÀN THÀNH**\n\n📊 Thành công: `{sent}`\n❌ Thất bại: `{failed}`")

async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"✉️ **PHẢN HỒI TỪ ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã gửi phản hồi tới `{uid}`")
    except:
        await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")

async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(ctx.args[0])
        data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 15", (uid,)).fetchall()
        if not data:
            await update.message.reply_text(f"📭 User `{uid}` chưa có giao dịch.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}` (15 dòng):**\n\n"
            for d in data:
                msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2][:16]}_\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/check [ID]`")

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
                        add_money(ref, 2000, "Ref bonus")
                        query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except: pass

    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    menu = ReplyKeyboardMarkup([
        ["🎮 Danh sách game", "👤 Tài khoản"],
        ["💳 Nạp tiền", "🛒 Rút tiền"],
        ["🎁 Checkin", "📮 Mời bạn"],
        ["🎲 Tài xỉu", "📜 Lịch sử"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)

    await update.message.reply_text(f"👋 Chào mừng **{update.effective_user.first_name}**!", reply_markup=menu, parse_mode="Markdown")

# ===== LỆNH LIÊN KẾT (MỚI) =====
async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args or len(ctx.args) < 3:
        return await update.message.reply_text("⚠️ **Cú pháp liên kết:**\n`/lienket [Ngân_hàng] [STK] [Chủ_TK]`\n\nVD: `/lienket MBBANK 0123456 NGUYEN VAN A`", parse_mode="Markdown")
    
    bank = ctx.args[0].upper()
    stk = ctx.args[1]
    name = " ".join(ctx.args[2:]).upper()
    
    query("UPDATE users SET bank=?, stk=?, name=? WHERE user_id=?", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**\n\n🏦 Ngân hàng: {bank}\n💳 STK: `{stk}`\n👤 Chủ TK: {name}", parse_mode="Markdown")

# ===== RÚT TIỀN (CẢI TIẾN) =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    
    u = query("SELECT bank, stk, name, balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u or not u[0] or not u[1]:
        return await update.message.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`\nVD: `/lienket MB 0367203858 LY THI CHAM`", parse_mode="Markdown")

    if not ctx.args:
        return await update.message.reply_text(f"💰 Số dư: `{u[3]:,}`đ\n⚠️ Nhập số tiền muốn rút: `/rut [số tiền]`\nVD: `/rut 50000`", parse_mode="Markdown")

    try:
        amount = int(ctx.args[0])
        if amount < MIN_WITHDRAW:
            return await update.message.reply_text(f"❌ Min rút `{MIN_WITHDRAW:,}đ`")
        
        if sub_money(uid, amount, "Rút tiền"):
            bank, stk, name = u[0], u[1], u[2]
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")
            ]])
            await ctx.bot.send_message(ADMIN_ID, f"🔔 **YÊU CẦU RÚT TIỀN**\n\n👤 ID: `{uid}`\n💰 `{amount:,}đ`\n🏦 `{bank} | {stk} | {name}`", reply_markup=keyboard, parse_mode="Markdown")
            await update.message.reply_text("✅ Gửi yêu cầu rút tiền thành công! Vui lòng chờ duyệt.")
        else:
            await update.message.reply_text("❌ Số dư không đủ.")
    except: 
        await update.message.reply_text("❌ Số tiền không hợp lệ.")

# ===== LỊCH SỬ CHO NGƯỜI DÙNG =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (uid,)).fetchall()
    if not data:
        await update.message.reply_text("📭 Lịch sử trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT (10 giao dịch):**\n\n"
        for d in data:
            icon = "➕" if d[0] > 0 else "➖"
            msg += f"{icon} `{d[0]:,}đ` | {d[1]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

# ===== HANDLE MENU MESSAGES =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    if not await joined(uid, ctx.bot):
        await force_join(update)
        return

    user_reply = update.message
    parts = txt.split()

    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]: return await play_dice_animation(update, code, amt)
        if code == "SLOT": return await play_emoji_game(update, "SLOT", amt)
        if code == "BALL": return await play_emoji_game(update, "BALL", amt)
        if code == "RÔ": return await play_emoji_game(update, "RO", amt)

    if txt == "💰 Số dư":
        bal = get_balance(uid)
        await user_reply.reply_text(f"💳 **SỐ DƯ CỦA BẠN:**\n\n💰 `{bal:,} VND`", parse_mode="Markdown")

    elif txt == "👤 Tài khoản":
        u = query("SELECT balance, bank, stk, name, refs FROM users WHERE user_id=?", (uid,)).fetchone()
        msg = (
            f"👤 **THÔNG TIN TÀI KHOẢN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{uid}`\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"👥 Đã mời: `{u[4]}` người\n"
            f"🏛 Ngân hàng: `{u[1] or 'Chưa liên kết'}`\n"
            f"💳 STK: `{u[2] or 'Chưa liên kết'}`\n"
            f"👤 Tên: `{u[3] or 'Chưa liên kết'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Sử dụng lệnh /lienket để cập nhật thông tin rút tiền!*"
        )
        await user_reply.reply_text(msg, parse_mode="Markdown")

    elif txt == "💳 Nạp tiền":
        await user_reply.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")

    elif txt == "🎮 Danh sách game":
        guide = (
            "🎮 **DANH SÁCH TRÒ CHƠI**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🎲 **XÚC XẮC (Tài Xỉu/Chẵn Lẻ)**\n"
            "Cú pháp: `[Mã] [Tiền]`\n"
            "• `XXC` (Chẵn) | `XXL` (Lẻ)\n"
            "• `XXX` (Xỉu) | `XXT` (Tài)\n\n"
            "🎰 **NỔ HŨ:** `SLOT [Tiền]`\n"
            "⚽️ **ĐÁ BÓNG:** `BALL [Tiền]`\n"
            "🏀 **BÓNG RỔ:** `RÔ [Tiền]`\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "👉 Ví dụ: `XXT 10000` hoặc `SLOT 5000`"
        )
        await user_reply.reply_text(guide, parse_mode="Markdown")

    elif txt == "🛒 Rút tiền":
        u = query("SELECT bank, stk, name FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u or not u[0] or not u[1]:
            await user_reply.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Bank] [STK] [Tên]`\nVD: `/lienket MB 0367203858 LY THI CHAM`", parse_mode="Markdown")
        else:
            await user_reply.reply_text(f"🏦 **TÀI KHOẢN HIỆN TẠI:**\n🏛 Bank: {u[0]}\n💳 STK: `{u[1]}`\n👤 Tên: {u[2]}\n\n👉 Để rút tiền, nhập: `/rut [số tiền]`", parse_mode="Markdown")

    elif txt == "🎁 Checkin":
        today = str(datetime.now().date())
        res = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        if res and res[0] == today:
            await user_reply.reply_text("❌ Hôm nay bạn đã điểm danh rồi!")
            return
        add_money(uid, 10000, "Daily Checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        await user_reply.reply_text("🎉 **CHECKIN THÀNH CÔNG!**\n\nBạn nhận được: `+10,000đ`", parse_mode="Markdown")

    elif txt == "📮 Mời bạn":
        msg = (
            "🚀 **KIẾM TIỀN TỪ LƯỢT MỜI**\n\n"
            "💵 1F = `3,000đ`\n"
            f"🔗 **Link của bạn:**\n`https://t.me/{BOT_USERNAME}?start={uid}`"
        )
        await user_reply.reply_text(msg, parse_mode="Markdown")

    elif txt == "🎲 Tài xỉu":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎲 TÀI", callback_data="tx_tai"),
            InlineKeyboardButton("🎲 XỈU", callback_data="tx_xiu")
        ]])
        msg = (
            "🎲 **TRÒ CHƠI TÀI XỈU**\n\n"
            "1️⃣ **Cược nhanh (10,000đ):** Chọn nút bên dưới.\n"
            "2️⃣ **Cược tự do:** Nhập: `[Mã] [Số tiền]`\n"
            "   VD: `XXT 50000`"
        )
        await user_reply.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

    elif txt == "📜 Lịch sử":
        await history_pro(update, ctx)

    elif txt == "📞 Hỗ trợ":
        await user_reply.reply_text("📩 Gửi nội dung cần hỗ trợ ngay tại đây, Admin sẽ phản hồi sớm!")

    else:
        if uid != ADMIN_ID:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📨 **TIN NHẮN HỖ TRỢ**\n👤 ID: `{uid}`\n📝 Nội dung: {txt}",
                parse_mode="Markdown"
     2see       )
            await user_reply.reply_text("✅ Đã gửi yêu cầu tới Admin!")

# ===== TÀI XỈU CALLBACK & RÚT TIỀN ACTION =====
async def handle_withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()
    if query_btn.from_user.id != ADMIN_ID: return
    try:
        action, uid, amount = query_btn.data.split("_")
        uid, amount = int(uid), int(amount)
        if action == "ok":
            await ctx.bot.send_message(uid, f"✅ Yêu cầu rút `{amount:,}đ` đã được duyệt!")
            await query_btn.edit_message_text(f"✅ ĐÃ DUYỆT ID {uid}")
        else:
            add_money(uid, amount, "Refund Withdraw")
            await ctx.bot.send_message(uid, "❌ Yêu cầu rút tiền bị từ chối. Tiền đã được hoàn lại.")
            await query_btn.edit_message_text(f"❌ TỪ CHỐI ID {uid}")
    except: pass

async def taixiu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_btn = update.callback_query
    await query_btn.answer()
    uid = query_btn.from_user.id
    if is_banned(uid) or get_balance(uid) < 10000:
        return await query_btn.message.reply_text("❌ Không đủ 10,000đ.")

    choice = query_btn.data.split("_")[1]
    msg_dice = await query_btn.message.reply_dice(emoji="🎲")
    value = msg_dice.dice.value
    await asyncio.sleep(3.5)

    result = "tai" if value >= 4 else "xiu"
    if choice == result:
        add_money(uid, 10000, "Thắng Tài Xỉu (Nút)")
        msg = "🎉 **BẠN ĐÃ THẮNG!**"
    else:
        sub_money(uid, 10000, "Thua Tài Xỉu (Nút)")
        msg = "💀 **BẠN ĐÃ THUA!**"

    await query_btn.message.reply_text(
        f"🎲 Kết quả: **{value}** ({result.upper()})\n\n{msg}\n💰 Số dư: `{get_balance(uid):,}đ`",
        parse_mode="Markdown"
    )

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("code", nhap_code))
app.add_handler(CommandHandler("taocode", tao_code))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("lienket", lien_ket))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("sub", sub))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all", all_user))
app.add_handler(CommandHandler("his", history_pro)) # Đã kết nối đúng
app.add_handler(CommandHandler("hisall", history_all_admin))
app.add_handler(CommandHandler("send", broadcast))
app.add_handler(CommandHandler("rep", reply_user))
app.add_handler(CommandHandler("check", check_user_history))
app.add_handler(CommandHandler("info", admin_info)) 

app.add_handler(CallbackQueryHandler(handle_withdraw_action, pattern="^(ok_|no_)"))
app.add_handler(CallbackQueryHandler(taixiu_button, pattern="^tx_"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT ĐÃ SẴN SÀNG!")
app.run_polling()
