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
# Cập nhật danh sách Admin
ADMIN_IDS = [7398112999, 8619503816]
BOT_USERNAME = "vuavipluxurybot" 
MIN_WITHDRAW = 100000
WIN_RATE = 30 # Tỉ lệ thắng 30%

# THÔNG TIN NẠP TIỀN
BANK_INFO = """
🏦 **THÔNG TIN NẠP TIỀN**
--------------------------
🏛 Ngân hàng: **VPBANK**
👤 CTK: **TRAN DAI THANG **
💳 STK: `0343044321 `
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
    bank TEXT DEFAULT NULL,
    stk TEXT DEFAULT NULL,
    name TEXT DEFAULT NULL,
    last_checkin TEXT,
    last_withdraw TEXT
)
""")
query("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, amount INTEGER, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")

# BẢNG CÀI ĐẶT BẢO TRÌ
query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin', 
    'mt_penalty', 'mt_gomo', 'mt_slot', 
    'mt_nap', 'mt_rut'
]
for k in maintenance_keys:
    if not query("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone():
        query("INSERT INTO settings VALUES(?, 0)", (k,))

# Hàm kiểm tra trạng thái bảo trì
def check_mt(key):
    res = query("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return res[0] == 1 if res else False

# ===== LOGIC KIỂM SOÁT TỈ LỆ =====
def should_win():
    return random.randint(1, 100) <= WIN_RATE

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

# ===== LOGIC GAMES ANIMATION =====

async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    track_length = 12
    pos_a, pos_b = 0, 0
    finish_line = "🏁"
    
    msg = await ctx.bot.send_message(uid, "🚦 **SẴN SÀNG...**")
    await asyncio.sleep(1)
    await msg.edit_text("🏎💨 **XUẤT PHÁT!!!**")

    # Quyết định thắng thua trước khi chạy animation
    is_win = should_win()
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

        line_a = "—" * pos_a + "🏎️" + " " * (track_length - pos_a) + finish_line + " **(A)**"
        line_b = "—" * pos_b + "🏎️" + " " * (track_length - pos_b) + finish_line + " **(B)**"
        
        try:
            await msg.edit_text(f"🏎️ **ĐUA XE SIÊU CẤP**\n\n`{line_a}`\n`{line_b}`", parse_mode="Markdown")
            await asyncio.sleep(0.8)
        except: pass

    winner = target_winner
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
    
    d1 = await update.message.reply_dice(emoji="🎲")
    d2 = await update.message.reply_dice(emoji="🎲")
    d3 = await update.message.reply_dice(emoji="🎲")
    
    results = [d1.dice.value, d2.dice.value, d3.dice.value]
    total = sum(results)
    
    c = choice_code.upper()
    is_chan, is_tai = (total % 2 == 0), (total >= 11)
    
    win = False
    if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or \
       (c == "XXX" and not is_tai) or (c == "XXT" and is_tai):
        win = True

    await asyncio.sleep(4)

    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: 
        status = f"❌ **THUA**"
    
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_emoji_game(update: Update, game_type, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {game_type}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")

    is_win = should_win()
    emojis = {"SLOT": "🎰", "BALL": "⚽️", "RO": "🏀"}
    msg_game = await update.message.reply_dice(emoji=emojis[game_type])
    
    if is_win:
        if game_type == "SLOT": value = 64
        elif game_type == "BALL": value = 5
        elif game_type == "RO": value = 5
    else:
        if game_type == "SLOT": value = 2
        elif game_type == "BALL": value = 1
        elif game_type == "RO": value = 1
    
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
    await update.message.reply_text(f"🕹 KQ: {value}\n{res}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# ===== LỆNH NHẬP CODE =====
async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
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

async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
    kb = [
        [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"🏎 Đua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), 
         InlineKeyboardButton(f"💣 Dò Mìn: {st('mt_domin')}", callback_data="tg_mt_domin")],
        [InlineKeyboardButton(f"⚽ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"), 
         InlineKeyboardButton(f"🪵 Gõ Mõ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
        [InlineKeyboardButton(f"🎰 Slot/Khác: {st('mt_slot')}", callback_data="tg_mt_slot")],
        [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"), 
         InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
    ]
    await update.message.reply_text("🛠 **BẢNG QUẢN LÝ BẢO TRÌ**\n(Bấm để chuyển trạng thái On/Off)", 
                                   reply_markup=InlineKeyboardMarkup(kb))

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await update.message.reply_text(f"✅ **NẠP TIỀN THÀNH CÔNG**\n\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`", parse_mode="Markdown")
        bill = (
            f"💳 **BIẾN ĐỘNG SỐ DƯ**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Tài khoản của bạn vừa nhận được tiền từ hệ thống.\n\n"
            f"📥 **Số tiền:** `+{amount:,}đ`\n"
            f"📝 **Nội dung:** Nạp tiền hệ thống\n"
            f"⏰ **Thời gian:** {datetime.now().strftime('%H:%M - %d/%m/%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Số dư hiện tại: `{get_balance(target_id):,}đ`"
        )
        try:
            await ctx.bot.send_message(chat_id=target_id, text=bill, parse_mode="Markdown")
        except: pass
    except:
        await update.message.reply_text("❌ Cú pháp: `/nap [ID] [Số tiền]`")

async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=?", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`. User có thể dùng /lienket lại.")
        await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn. Bạn có thể liên kết lại ngay bây giờ.")
    except:
        await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
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
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(?,?,?)", (code, reward, uses))
        await update.message.reply_text(f"✅ **TẠO CODE THÀNH CÔNG**\n\n🎁 Code: `{code}`\n💰 Thưởng: `{reward:,}đ`\n🔄 Lượt: `{uses}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/taocode [số tiền] [lượt dùng]`")

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng tiền")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho ID `{uid}`")
    except: pass

async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt, "Admin trừ tiền")
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của ID `{uid}`")
    except: pass

async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        query("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    total = query("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👥 Tổng số người dùng: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    users = query("SELECT user_id FROM users ORDER BY rowid DESC LIMIT 50").fetchall()
    msg = "👥 **DANH SÁCH USER (50 gần nhất):**\n\n" + "\n".join([f"`{u[0]}`" for u in users])
    await update.message.reply_text(msg or "Chưa có user nào.", parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    data = query("SELECT * FROM history ORDER BY rowid DESC").fetchall()
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    for d in data:
        msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000):
            await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
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
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"✉️ **PHẢN HỒI TỪ ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã gửi phản hồi tới `{uid}`")
    except:
        await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")

async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
        if not data:
            await update.message.reply_text(f"📥 User `{uid}` chưa có giao dịch.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}`:**\n\n"
            for d in data:
                msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2][:16]}_\n"
            if len(msg) > 4000:
                for x in range(0, len(msg), 4000):
                    await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
            else:
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
                        add_money(ref, 3000, "Ref bonus")
                        query("UPDATE users SET refs=refs+1 WHERE user_id=?", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=?", (uid,))
        except: pass

    # THÊM NÚT "🎁 Nhận Code Free" VÀO MENU CHÍNH
    menu = ReplyKeyboardMarkup([
        ["🎮 Danh sách game", "👤 Tài khoản"],
        ["💳 Nạp tiền", "🛒 Rút tiền"],
        ["🎁 Checkin", "🎁 Nhận Code Free"],
        ["📜 Lịch sử", "📧 Mời bạn"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)

    welcome_text = (
        f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()} ĐÃ THAM GIA!**\n\n"
        f"Hệ thống trò chơi minh bạch — uy tín hàng đầu.\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **MIN RÚT TIỀN:** `100.000đ`\n"
        f"💳 **MIN NẠP TIỀN:** `10.000đ`\n"
        f"⚠️ *Lưu ý: Nạp dưới 10k sẽ không được tự động duyệt.*\n\n"
        f"⚖️ **CAM KẾT MINH BẠCH:**\n"
        f"• **100%** Kết quả hoàn toàn ngẫu nhiên.\n"
        f"• 🔄 **KHÔNG** can thiệp kết quả dưới mọi hình thức.\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Chúc bạn có những trải nghiệm may mắn và thú vị!"
    )
    await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode="Markdown")

# ===== LỆNH LIÊN KẾT =====
async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    u_bank = query("SELECT bank FROM users WHERE user_id=?", (uid,)).fetchone()
    if u_bank and u_bank[0] is not None:
        return await update.message.reply_text("❌ Bạn đã liên kết ngân hàng rồi. Để thay đổi, vui lòng liên hệ Admin!", parse_mode="Markdown")
    if not ctx.args or len(ctx.args) < 3:
        return await update.message.reply_text("⚠️ **Cú pháp liên kết:**\n`/lienket [Ngân_hàng] [STK] [Chủ_TK]`\n\nVD: `/lienket MBBANK 0123456 NGUYEN VAN A`", parse_mode="Markdown")
    bank = ctx.args[0].upper()
    stk = ctx.args[1]
    name = " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=?, stk=?, name=? WHERE user_id=?", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**\n\n🏛 Ngân hàng: {bank}\n💳 STK: `{stk}`\n👤 Chủ TK: {name}\n\n⚠️ *Thông tin này đã được khóa để bảo mật.*", parse_mode="Markdown")

# ===== RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if check_mt('mt_rut') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Hệ thống Rút Tiền đang bảo trì, vui lòng quay lại sau!")
        
    u = query("SELECT bank, stk, name, balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u or not u[0] or not u[1]:
        return await update.message.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
    if not ctx.args:
        return await update.message.reply_text(f"💰 Số dư: `{u[3]:,}`đ\n⚠️ Nhập số tiền muốn rút: `/rut [số tiền]`", parse_mode="Markdown")
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
            # Gửi yêu cầu cho Admin chính đầu tiên
            await ctx.bot.send_message(ADMIN_IDS[0], f"🔔 **YÊU CẦU RÚT TIỀN**\n\n👤 ID: `{uid}`\n💰 `{amount:,}đ`\n🏛 `{bank} | {stk} | {name}`", reply_markup=keyboard, parse_mode="Markdown")
            await update.message.reply_text("✅ Gửi yêu cầu rút tiền thành công! Vui lòng chờ duyệt.")
        else:
            await update.message.reply_text("❌ Số dư không đủ.")
    except: 
        await update.message.reply_text("❌ Số tiền không hợp lệ.")

# ===== LỊCH SỬ CHO NGƯỜI DÙNG =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=? ORDER BY rowid DESC", (uid,)).fetchall()
    if not data:
        await update.message.reply_text("📥 Lịch sử trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT:**\n\n"
        for d in data:
            icon = "➕" if d[0] > 0 else "➖"
            msg += f"{icon} `{d[0]:,}đ` | {d[1]}\n"
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

    # --- ƯU TIÊN KIỂM TRA CÁC NÚT MENU TRƯỚC ---
    if txt == "👤 Tài khoản":
        u = query("SELECT balance, bank, stk, name, refs FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u: # Đảm bảo user tồn tại trong DB
            get_user(uid)
            u = (0, None, None, None, 0)
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
        return await user_reply.reply_text(msg, parse_mode="Markdown")

    if txt == "🎁 Nhận Code Free":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 THAM GIA NHÓM NHẬN CODE", url="https://t.me/vuatelevision")],
            [InlineKeyboardButton("📢 KÊNH THÔNG BÁO", url="https://t.me/thanhall")]
        ])
        msg = (
            "🎁 **NHẬN GIFTCODE MIỄN PHÍ**\n\n"
            "Tham gia các nhóm dưới đây để săn mã Code thưởng mỗi ngày từ Admin!\n\n"
            "📖 **CÁCH NHẬP CODE:**\n"
            "Gõ lệnh: `/code [mã_quà_tặng]`\n"
            "Ví dụ: `/code VUAVIP2024`\n\n"
            "👇 **Tham gia ngay tại đây:**"
        )
        return await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)

    if txt == "💳 Nạp tiền":
        if check_mt('mt_nap') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("⚙️ Hệ thống Nạp Tiền đang bảo trì!")
        return await user_reply.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")

    if txt == "🎮 Danh sách game":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx")],
            [InlineKeyboardButton("🏎️ ĐUA XE (RACE)", callback_data="menu_race"), 
             InlineKeyboardButton("💣 DÒ MÌN", callback_data="menu_mines")],
            [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), 
             InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")],
            [InlineKeyboardButton("🎰 SLOT / 🏀 KHÁC", callback_data="menu_others")]
        ])
        return await user_reply.reply_text("🎮 **DANH SÁCH TRÒ CHƠI**\nVui lòng chọn game bạn muốn chơi:", reply_markup=kb, parse_mode="Markdown")

    if txt == "🛒 Rút tiền":
        if check_mt('mt_rut') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("⚙️ Hệ thống Rút Tiền đang bảo trì!")
        u = query("SELECT bank, stk, name FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u or not u[0] or not u[1]:
            await user_reply.reply_text("❌ Bạn chưa liên kết bank.\n👉 Dùng lệnh: `/lienket [Bank] [STK] [Tên]`", parse_mode="Markdown")
        else:
            await user_reply.reply_text(f"🏛 **TÀI KHOẢN RÚT:**\n🏛 Bank: {u[0]}\n💳 STK: `{u[1]}`\n👤 Tên: {u[2]}\n\n👉 Nhập: `/rut [số tiền]`", parse_mode="Markdown")
        return

    if txt == "🎁 Checkin":
        today = str(datetime.now().date())
        res = query("SELECT last_checkin FROM users WHERE user_id=?", (uid,)).fetchone()
        if res and res[0] == today:
            await user_reply.reply_text("❌ Hôm nay bạn đã điểm danh rồi!")
            return
        add_money(uid,3000, "Daily Checkin")
        query("UPDATE users SET last_checkin=? WHERE user_id=?", (today, uid))
        return await user_reply.reply_text("🎉 **CHECKIN THÀNH CÔNG!**\n\nBạn nhận được: `+3000đ`", parse_mode="Markdown")

    if txt == "📧 Mời bạn":
        msg = (
            "🚀 **KIẾM TIỀN TỪ LƯỢT MỜI**\n\n"
            "💵 1F = `2,000đ`\n"
            f"🔗 **Link của bạn:**\n`https://t.me/{BOT_USERNAME}?start={uid}`"
        )
        return await user_reply.reply_text(msg, parse_mode="Markdown")

    if txt == "📜 Lịch sử":
        return await history_pro(update, ctx)

    if txt == "📞 Hỗ trợ":
        return await user_reply.reply_text("📩 Gửi nội dung cần hỗ trợ ngay tại đây, Admin sẽ phản hồi sớm! Hoặc NT CHO @cskhzen88uytin")

    # --- LOGIC CƯỢC NHANH ---
    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]:
            if check_mt('mt_taixiu') and uid not in ADMIN_IDS:
                return await update.message.reply_text("⚙️ Game Tài Xỉu đang bảo trì!")
            return await play_dice_animation(update, code, amt)
        if code in ["SLOT", "BALL", "RÔ"]:
            if check_mt('mt_slot') and uid not in ADMIN_IDS:
                return await update.message.reply_text("⚙️ Game này đang bảo trì!")
            if code == "SLOT": return await play_emoji_game(update, "SLOT", amt)
            if code == "BALL": return await play_emoji_game(update, "BALL", amt)
            if code == "RÔ": return await play_emoji_game(update, "RO", amt)

    # --- CHẾ ĐỘ NHẬN TIN NHẮN HỖ TRỢ ---
    if uid not in ADMIN_IDS:
        for aid in ADMIN_IDS:
            try: await ctx.bot.send_message(chat_id=aid, text=f"📨 **TIN NHẮN HỖ TRỢ**\n👤 ID: `{uid}`\n📝 Nội dung: {txt}", parse_mode="Markdown")
            except: pass
        await user_reply.reply_text("✅ Đã gửi yêu cầu tới Admin!")

# ===== CALLBACK HANDLER (GAMES & WITHDRAW) =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    
    if d.startswith("tg_mt_"):
        if uid not in ADMIN_IDS: return
        key = d.replace("tg_", "")
        new_val = 0 if check_mt(key) else 1
        query("UPDATE settings SET value=? WHERE key=?", (new_val, key))
        def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
        new_kb = [
            [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
            [InlineKeyboardButton(f"🏎 Đua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), 
             InlineKeyboardButton(f"💣 Dò Mìn: {st('mt_domin')}", callback_data="tg_mt_domin")],
            [InlineKeyboardButton(f"⚽ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"), 
             InlineKeyboardButton(f"🪵 Gõ Mõ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
            [InlineKeyboardButton(f"🎰 Slot/Khác: {st('mt_slot')}", callback_data="tg_mt_slot")],
            [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"), 
             InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
            [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
        ]
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
        await q.answer("Đã cập nhật trạng thái!")
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
            await ctx.bot.send_message(u_id, f"✅ Yêu cầu rút `{amt:,}đ` đã được duyệt!")
            await q.edit_message_text(f"✅ ĐÃ DUYỆT ID {u_id}")
        else:
            add_money(u_id, amt, "Hoàn tiền rút")
            await ctx.bot.send_message(u_id, "❌ Yêu cầu rút tiền bị từ chối. Tiền đã được hoàn lại.")
            await q.edit_message_text(f"❌ TỪ CHỐI ID {u_id}")

    elif d == "menu_race":
        if check_mt('mt_duaxe') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Đua Xe đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_race_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🏎️ **ĐUA XE SIÊU CẤP**\nVui lòng chọn mức cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_race_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("🏎️ XE A", callback_data=f"start_race_A_{amt}"), 
             InlineKeyboardButton("🏎️ XE B", callback_data=f"start_race_B_{amt}")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_race")]
        ]
        await q.edit_message_text(f"🏎️ **ĐUA XE**\n💰 Cược: `{amt:,}đ`\n👇 Chọn xe bạn tin là sẽ thắng:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_race_"):
        parts = d.split("_")
        choice, amt = parts[2], int(parts[3])
        if not sub_money(uid, amt, f"Cược Đua xe {choice}"):
            return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        await q.delete_message()
        await play_car_race(update, ctx, choice, amt)

    elif d == "menu_mines":
        if check_mt('mt_domin') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Dò Mìn đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_mines_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("💣 **DÒ MÌN (MINES)**\nVui lòng chọn mức cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_mines_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🚀 BẮT ĐẦU CHƠI", callback_data=f"start_mines_{amt}"), InlineKeyboardButton("🔙 Quay lại", callback_data="menu_mines")]]
        await q.edit_message_text(f"💣 **DÒ MÌN**\n💰 Cược: `{amt:,}đ`\n⚠️ Có 3 quả mìn ẩn trong 15 ô. Mở ô để nhân tiền!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_mines_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Dò Mìn"): return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        
        is_win_game = should_win()
        grid = [0]*12 + [1]*3 
        random.shuffle(grid)
        
        ctx.user_data[f"mine_{uid}"] = {"grid": grid, "bet": amt, "opened": [], "mult": 1.4, "must_lose": not is_win_game}
        kb = []
        row = []
        for i in range(15):
            row.append(InlineKeyboardButton("❓", callback_data=f"play_mine_{i}"))
            if (i+1) % 3 == 0: kb.append(row); row = []
        await q.edit_message_text(f"💣 **DÒ MÌN ĐANG DIỄN RA**\n💰 Cược: `{amt:,}đ`\n📈 Hệ số tiếp theo: `x1.4`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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
            await q.edit_message_text(f"💥 **BÙM!!!**\nBạn đã dẫm phải mìn rồi.\n💀 Mất: `{game['bet']:,}đ`", parse_mode="Markdown")
        else: 
            game["opened"].append(idx)
            current_win = int(game["bet"] * game["mult"])
            game["mult"] += 0.4
            kb = []
            row = []
            for i in range(15):
                icon = "💎" if i in game["opened"] else "❓"
                row.append(InlineKeyboardButton(icon, callback_data=f"play_mine_{i}"))
                if (i+1) % 3 == 0: kb.append(row); row = []
            kb.append([InlineKeyboardButton(f"💰 CHỐT LỜI: {current_win:,}đ", callback_data=f"claim_mine_{current_win}")])
            await q.edit_message_text(f"💎 **AN TOÀN!**\n💰 Thưởng hiện tại: `{current_win:,}đ`\n📈 Lượt tới: `x{game['mult']:.1f}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("claim_mine_"):
        amt = int(d.split("_")[2])
        add_money(uid, amt, "Thắng Dò Mìn")
        if f"mine_{uid}" in ctx.user_data: del ctx.user_data[f"mine_{uid}"]
        await q.edit_message_text(f"🎉 **CHÚC MỪNG!**\nBạn đã chốt lời thành công: `+{amt:,}đ`\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

    elif d == "menu_tx" or d == "menu_ball":
        g_type = "tx" if "tx" in d else "ball"
        if g_type == "ball" and check_mt('mt_penalty') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Penalty đang bảo trì!")
        if g_type == "tx" and check_mt('mt_taixiu') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Tài Xỉu đang bảo trì!")
            
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_{g_type}_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        msg = "🎲 **TÀI XỈU 3D**" if g_type == "tx" else "⚽️ **BÓNG ĐÁ PENALTY**"
        await q.edit_message_text(f"{msg}\n👇 Chọn mức tiền cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d == "menu_others":
        if check_mt('mt_slot') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Các trò chơi này đang bảo trì!")
        await q.edit_message_text("🎮 **TRÒ CHƠI KHÁC**\nNhập cú pháp tay để chơi:\n- `SLOT [Tiền]`\n- `RÔ [Tiền]`\n- `BALL [Tiền]`", parse_mode="Markdown")

    elif d.startswith("set_"):
        _, game, amt = d.split("_")
        if game == "tx":
            kb = [[InlineKeyboardButton("🎲 TÀI", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("🎲 XỈU", callback_data=f"p_tx_xiu_{amt}")]]
        else:
            kb = [[InlineKeyboardButton("⬅️ TRÁI", callback_data=f"p_ba_1_{amt}"), 
                   InlineKeyboardButton("⬆️ GIỮA", callback_data=f"p_ba_2_{amt}"), 
                   InlineKeyboardButton("➡️ PHẢI", callback_data=f"p_ba_3_{amt}")]]
        await q.edit_message_text(f"💰 Cược: **{int(amt):,}đ**\n👇 Chọn hướng sút/cửa đặt:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_"):
        _, game, choice, amt = d.split("_")
        amt = int(amt)
        if get_balance(uid) < amt: return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        
        if game == "ba":
            sub_money(uid, amt, f"Cược Penalty")
            is_win = should_win()
            player_choice = int(choice)
            if is_win:
                goalie_direction = random.choice([d for d in [1, 2, 3] if d != player_choice])
            else:
                goalie_direction = player_choice

            directions_text = {1: "TRÁI", 2: "GIỮA", 3: "PHẢI"}
            msg_ball = await ctx.bot.send_dice(uid, emoji="⚽️")
            await asyncio.sleep(3.5)
            
            if player_choice == goalie_direction:
                win = False
                result_detail = f"🧤 Thủ môn đã bay người sang **{directions_text[goalie_direction]}** và bắt gọn bóng!"
            else:
                win = True
                result_detail = f"🥅 Thủ môn bay sang **{directions_text[goalie_direction]}** nhưng bạn sút vào **{directions_text[player_choice]}**!"
            
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, "Thắng Penalty")
                status = f"⚽️ **VÀOOO!!!**\n{result_detail}\n💰 Nhận: `+{win_amt:,}đ`"
            else:
                status = f"❌ **KHÔNG VÀO!**\n{result_detail}\n💀 Bạn đã mất tiền cược."
            await ctx.bot.send_message(uid, f"{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
            return

        if game == "tx":
            sub_money(uid, amt, f"Cược {game}")
            msg_status = await ctx.bot.send_message(uid, "🎲 **ĐANG LẮC XÚC XẮC...**", parse_mode="Markdown")
            
            d1 = await ctx.bot.send_dice(uid, emoji="🎲")
            d2 = await ctx.bot.send_dice(uid, emoji="🎲")
            d3 = await ctx.bot.send_dice(uid, emoji="🎲")
            
            results = [d1.dice.value, d2.dice.value, d3.dice.value]
            total = sum(results)
            res_type = "tai" if total >= 11 else "xiu"
            
            win = (choice == res_type)

            await asyncio.sleep(4)
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, f"Thắng Tài Xỉu {res_type.upper()}")
                status = f"🎉 **THẮNG** | Nhận: `+{win_amt:,}đ`"
            else:
                status = f"❌ **THUA** | Chúc may mắn lần sau!"
            res_str = "-".join(map(str, results))
            await msg_status.edit_text(
                f"📊 **KẾT QUẢ TÀI XỈU**\n━━━━━━━━━━━━━━━━━━━━━\n🎲 Xúc xắc: **{res_str}**\n🏆 Tổng điểm: **{total}** ({res_type.upper()})\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`"
            , parse_mode="Markdown")

    elif d == "menu_wooden":
        if check_mt('mt_gomo') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Gõ Mõ đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_wood_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🪵 **GAME GÕ MÕ**\n\n- Mỗi lần gõ hệ số tăng **x0.3**.\n- Bạn phải rút trước khi mõ vỡ!\n\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_wood_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🪵 BẮT ĐẦU GÕ", callback_data=f"start_wood_{amt}")],
              [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_wooden")]]
        await q.edit_message_text(f"🪵 **GÕ MÕ**\n💰 Cược: `{amt:,}đ`\n👇 Nhấn nút GÕ bên dưới để bắt đầu tăng hệ số!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_wood_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Gõ Mõ"): 
            return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        
        is_win_wood = should_win()
        if is_win_wood:
            break_point = round(random.uniform(3.0, 10.0), 2)
        else:
            break_point = round(random.uniform(1.1, 1.8), 2)

        game_id = f"wd_{uid}_{random.randint(100,999)}"
        ctx.user_data[game_id] = {"status": "playing", "amt": amt, "mult": 1.0, "target": break_point}
        kb = [[InlineKeyboardButton("🪵 GÕ (x1.00)", callback_data=f"hit_wood_{game_id}")],
              [InlineKeyboardButton("💰 RÚT (x1.00)", callback_data=f"clm_wood_{game_id}")]]
        await q.edit_message_text(f"🪵 **GÕ MÕ... CỘP CỘP!**\n📈 Hệ số hiện tại: **x1.00**\n💰 Tiền nếu rút: `{amt:,}đ`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("hit_wood_"):
        parts = d.split("_")
        game_id = f"{parts[2]}_{parts[3]}_{parts[4]}"
        game = ctx.user_data.get(game_id)
        if not game or game["status"] != "playing": return
        game["mult"] = round(game["mult"] + 0.3, 2)
        if game["mult"] >= game["target"]:
            game["status"] = "broken"
            await q.edit_message_text(f"💥 **MÕ ĐÃ VỠ !!!**\n\nHệ số nhảy quá cao: **x{game['mult']}**\n💀 Mất: `{game['amt']:,}đ`", parse_mode="Markdown")
            del ctx.user_data[game_id]
        else:
            win_now = int(game["amt"] * game["mult"])
            kb = [[InlineKeyboardButton(f"🪵 GÕ TIẾP (x{game['mult']:.2f})", callback_data=f"hit_wood_{game_id}")],
                  [InlineKeyboardButton(f"💰 RÚT TIỀN (x{game['mult']:.2f})", callback_data=f"clm_wood_{game_id}")]]
            await q.edit_message_text(f"🪵 **GÕ MÕ... CỘP CỘP!**\n📈 Hệ số: **x{game['mult']:.2f}**\n💰 Tiền thắng: `{win_now:,}đ`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clm_wood_"):
        parts = d.split("_")
        game_id = f"{parts[2]}_{parts[3]}_{parts[4]}"
        game = ctx.user_data.get(game_id)
        if game and game["status"] == "playing":
            game["status"] = "claimed"
            win_amt = int(game["amt"] * game["mult"])
            add_money(uid, win_amt, f"Thắng Gõ Mõ x{game['mult']}")
            await q.edit_message_text(f"🎉 **CHÚC MỪNG!**\n\nBạn đã dừng ở **x{game['mult']:.2f}**\n💰 Nhận được: `+{win_amt:,}đ`", parse_mode="Markdown")
            del ctx.user_data[game_id]

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("baotri", baotri_cmd))
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

print("BOT ĐÃ SẴN SÀNG - KHÔNG CÒN YÊU CẦU THAM GIA NHÓM!")
app.run_polling()
 
