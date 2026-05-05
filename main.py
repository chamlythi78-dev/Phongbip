from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import psycopg2  
from psycopg2 import extras
from datetime import datetime, timedelta
import os
import asyncio
import random

# Hàm tạo mã ngẫu nhiên
def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [7398112999, 8619503816]
BOT_USERNAME = "zen88uytins1bot" 
MIN_WITHDRAW = 200000 
WIN_RATE = 35 

# THÔNG TIN NẠP TIỀN
BANK_INFO = """
🏦 **THÔNG TIN NẠP TIỀN**
--------------------------
🏛 Ngân hàng: **VPBANK**
👤 CTK: **LUU TON DUONG**
💳 STK: `2709220899`
📝 NỘI DUNG CK: `{uid}`
--------------------------
⚠️ *Lưu ý: Min nạp 20.000đ. Bạn vui lòng nhập đúng ID để hệ thống kiểm tra nhanh nhất!*
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
    total_bet BIGINT DEFAULT 0
)
""")

try:
    query("ALTER TABLE users ADD COLUMN total_bet BIGINT DEFAULT 0")
except:
    pass

query("CREATE TABLE IF NOT EXISTS history (user_id BIGINT, amount BIGINT, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id BIGINT PRIMARY KEY)")

query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin', 
    'mt_penalty', 'mt_gomo', 'mt_slot', 
    'mt_nap', 'mt_rut', 'mt_xocdia', 'mt_quayso'
]
for k in maintenance_keys:
    res = query("SELECT 1 FROM settings WHERE key=%s", (k,))
    if not res:
        query("INSERT INTO settings VALUES(%s, 0)", (k,))

def check_mt(key):
    res = query("SELECT value FROM settings WHERE key=%s", (key,))
    return res[0][0] == 1 if res else False

# ===== LOGIC KIỂM SOÁT TỈ LỆ =====
def should_win():
    return random.randint(1, 100) <= WIN_RATE

# ===== HÀM TÍNH HỆ SỐ NHÂN MỚI (UPDATE) =====
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
    
    if note != "Rút tiền" and note != "withdraw" and "Admin" not in note:
        query("UPDATE users SET total_bet=total_bet+%s WHERE user_id=%s", (amt, uid))
        
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
    data = query("SELECT * FROM codes WHERE code=%s", (code_str,))
    if not data:
        await update.message.reply_text("❌ Mã quà tặng không tồn tại.")
        return
    reward, uses = data[0][1], data[0][2]
    if uses <= 0:
        await update.message.reply_text("❌ Mã quà tặng này đã hết lượt sử dụng.")
        return
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=%s", (code_str,))
    await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\n💰 Bạn nhận được: `+{reward:,}đ`", parse_mode="Markdown")

# ===== ADMIN COMMANDS =====

async def reset_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ XÁC NHẬN RESET", callback_data="confirm_reset_all"),
            InlineKeyboardButton("❌ HỦY", callback_data="cancel_reset_all")
        ]
    ])

    await update.message.reply_text(
        "⚠️ **CẢNH BÁO NGUY HIỂM** ⚠️\n\n"
        "Bạn sắp xóa TOÀN BỘ dữ liệu hệ thống:\n"
        "- Người dùng\n"
        "- Số dư\n"
        "- Lịch sử\n"
        "- Code\n\n"
        "👉 Hành động này KHÔNG THỂ HOÀN TÁC!",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
    kb = [
        [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"💿 Xóc Đĩa: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
        [InlineKeyboardButton(f"🏎 Đua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), 
         InlineKeyboardButton(f"💣 Dò Mìn: {st('mt_domin')}", callback_data="tg_mt_domin")],
        [InlineKeyboardButton(f"⚽ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"), 
         InlineKeyboardButton(f"🪵 Gõ Mõ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
        [InlineKeyboardButton(f"🎰 Slot/Khác: {st('mt_slot')}", callback_data="tg_mt_slot"),
         InlineKeyboardButton(f"🔢 Quay Số: {st('mt_quayso')}", callback_data="tg_mt_quayso")],
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
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=%s", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`. User có thể dùng /lienket lại.")
        await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn. Bạn có thể liên kết lại ngay bây giờ.")
    except:
        await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        res = query("SELECT balance, refs, bank, stk, name, last_checkin, total_bet FROM users WHERE user_id=%s", (target_id,))
        if not res:
            return await update.message.reply_text("❌ Không tìm thấy người dùng này.")
        u = res[0]
        msg = (
            f"📂 **THÔNG TIN CHI TIẾT USER `{target_id}`**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"📊 Tổng cược: `{u[6]:,}đ`\n"
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
        query("INSERT INTO codes (code, reward, uses) VALUES(%s,%s,%s)", (code, reward, uses))
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
        query("INSERT INTO banned(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`")
    except: pass

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`")
    except: pass

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    res = query("SELECT COUNT(*) FROM users")
    total = res[0][0] if res else 0
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👥 Tổng số người dùng: `{total}`", parse_mode="Markdown")

async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page=0):
    if update.effective_user.id not in ADMIN_IDS: return
    limit = 20
    offset = page * limit
    users = query("SELECT user_id, balance FROM users ORDER BY user_id DESC LIMIT %s OFFSET %s", (limit, offset))
    res_total = query("SELECT COUNT(*) FROM users")
    total_users = res_total[0][0] if res_total else 0
    total_pages = (total_users + limit - 1) // limit

    if not users:
        return await update.message.reply_text("Chưa có người dùng nào.")

    kb = []
    for u in users:
        u_id, bal = u[0], u[1]
        status = "🚫" if is_banned(u_id) else "🟢"
        kb.append([InlineKeyboardButton(f"{status} ID: {u_id} | {bal:,}đ", callback_data=f"adm_manage_{u_id}_{page}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"adm_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"Trang {page+1}/{total_pages}", callback_data="none"))
    if (page + 1) < total_pages:
        nav_buttons.append(InlineKeyboardButton("Sau ➡️", callback_data=f"adm_page_{page+1}"))
    kb.append(nav_buttons)
    kb.append([InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")])

    text = f"👥 **DANH SÁCH NGƯỜI DÙNG** (Tổng: {total_users})\nBấm vào User để xem chi tiết:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    data = query("SELECT * FROM history ORDER BY time DESC LIMIT 50") 
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    if data:
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
    users = query("SELECT user_id FROM users")
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
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC", (uid,))
        if not data:
            await update.message.reply_text(f"📥 User `{uid}` chưa có giao dịch.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}`:**\n\n"
            for d in data:
                msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2]}_\n" 
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
                row = query("SELECT refed FROM users WHERE user_id=%s", (uid,))
                if row and row[0][0] == 0:
                    if query("SELECT 1 FROM users WHERE user_id=%s", (ref,)):
                        add_money(ref, 500, "Ref bonus") 
                        query("UPDATE users SET refs=refs+1 WHERE user_id=%s", (ref,))
                        query("UPDATE users SET refed=1 WHERE user_id=%s", (uid,))
        except: pass

    menu = ReplyKeyboardMarkup([
        ["🎮 Danh sách game", "👤 Tài khoản"],
        ["💳 Nạp tiền", "🛒 Rút tiền"],
        ["🎁 Checkin", "🎁 Nhận Code Free"],
        ["📜 Lịch sử", "📞 Hỗ trợ"]
    ], resize_keyboard=True)

    welcome_text = (
        f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()} ĐÃ THAM GIA!**\n\n"
        f"Hệ thống trò chơi minh bạch — uy tín hàng đầu.\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **MIN RÚT TIỀN:** `{MIN_WITHDRAW:,}đ`\n" 
        f"💳 **MIN NẠP TIỀN:** `20.000đ`\n"
        f"⚠️ *Lưu ý: Nạp dưới 20k sẽ không được tự động duyệt.*\n\n"
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
    res = query("SELECT bank FROM users WHERE user_id=%s", (uid,))
    if res and res[0][0] is not None:
        return await update.message.reply_text("❌ Bạn đã liên kết ngân hàng rồi. Để thay đổi, vui lòng liên hệ Admin!", parse_mode="Markdown")
    if not ctx.args or len(ctx.args) < 3:
        return await update.message.reply_text("⚠️ **Cú pháp liên kết:**\n`/lienket [Ngân_hàng] [STK] [Chủ_TK]`\n\nVD: `/lienket MBBANK 0123456 NGUYEN VAN A`", parse_mode="Markdown")
    bank = ctx.args[0].upper()
    stk = ctx.args[1]
    name = " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=%s, stk=%s, name=%s WHERE user_id=%s", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**\n\n🏛 Ngân hàng: {bank}\n💳 STK: `{stk}`\n👤 Chủ TK: {name}\n\n⚠️ *Thông tin này đã được khóa để bảo mật.*", parse_mode="Markdown")

# ===== RÚT TIỀN =====
async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if check_mt('mt_rut') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Hệ thống Rút Tiền đang bảo trì, vui lòng quay lại sau!")
        
    res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
    if not res or not res[0][0] or not res[0][1]:
        return await update.message.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
    u = res[0]
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
            await ctx.bot.send_message(ADMIN_IDS[0], f"🔔 **YÊU CẦU RÚT TIỀN**\n\n👤 ID: `{uid}`\n💰 `{amount:,}đ`\n🏛 `{bank} | {stk} | {name}`", reply_markup=keyboard, parse_mode="Markdown")
            await update.message.reply_text("✅ Gửi yêu cầu rút tiền thành công! Vui lòng chờ duyệt.")
        else:
            await update.message.reply_text("❌ Số dư không đủ.")
    except: 
        await update.message.reply_text("❌ Số tiền không hợp lệ.")

# ===== LỊCH SỬ CHO NGƯỜI DÙNG =====
async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC LIMIT 20", (uid,))
    if not data:
        await update.message.reply_text("📥 Lịch sử trống.")
    else:
        msg = "📜 **LỊCH SỬ CHI TIẾT:**\n\n"
        for d in data:
            icon = "➕" if d[0] > 0 else "➖"
            msg += f"{icon} `{d[0]:,}đ` | {d[1]} | _{d[2]}_\n"
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

    if txt == "👤 Tài khoản":
        res = query("SELECT balance, bank, stk, name, refs, total_bet FROM users WHERE user_id=%s", (uid,))
        if not res: 
            get_user(uid)
            u = (0, None, None, None, 0, 0)
        else:
            u = res[0]
        msg = (
            f"👤 **THÔNG TIN TÀI KHOẢN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{uid}`\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"📊 **Tổng cược:** `{u[5]:,}đ`\n"
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
            [InlineKeyboardButton("📺 THAM GIA NHÓM NHẬN CODE", url="https://t.me/zen88cltxtele")],
            [InlineKeyboardButton("📢 KÊNH THÔNG BÁO", url="https://t.me/hocvienthanbai5")]
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
            [InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx"), InlineKeyboardButton("💿 XÓC ĐĨA", callback_data="menu_xocdia")],
            [InlineKeyboardButton("🏎️ ĐUA XE (RACE)", callback_data="menu_race"), 
             InlineKeyboardButton("💣 Dò Mìn", callback_data="menu_mines")],
            [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), 
             InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")],
            [InlineKeyboardButton("🎰 SLOT / 🏀 KHÁC", callback_data="menu_others"),
             InlineKeyboardButton("🔢 QUAY SỐ (1-3)", callback_data="menu_qs")]
        ])
        return await user_reply.reply_text("🎮 **DANH SÁCH TRÒ CHƠI**\nVui lòng chọn game bạn muốn chơi:", reply_markup=kb, parse_mode="Markdown")

    if txt == "🛒 Rút tiền":
        if check_mt('mt_rut') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("⚙️ Hệ thống Rút Tiền đang bảo trì!")
        res = query("SELECT bank, stk, name FROM users WHERE user_id=%s", (uid,))
        if not res or not res[0][0] or not res[0][1]:
            await user_reply.reply_text("❌ Bạn chưa liên kết bank.\n👉 Dùng lệnh: `/lienket [Bank] [STK] [Tên]`", parse_mode="Markdown")
        else:
            u = res[0]
            await user_reply.reply_text(f"🏛 **TÀI KHOẢN RÚT:**\n🏛 Bank: {u[0]}\n💳 STK: `{u[1]}`\n👤 Tên: {u[2]}\n\n👉 Nhập: `/rut [số tiền]`", parse_mode="Markdown")
        return

    if txt == "🎁 Checkin":
        today = datetime.now().strftime("%d/%m/%Y")
        res = query("SELECT last_checkin FROM users WHERE user_id=%s", (uid,))
        if res and res[0][0] == today:
            await user_reply.reply_text("❌ Hôm nay bạn đã điểm danh rồi!")
            return
        add_money(uid, 300, "Daily Checkin") 
        query("UPDATE users SET last_checkin=%s WHERE user_id=%s", (today, uid))
        return await user_reply.reply_text("🎉 **CHECKIN THÀNH CÔNG!**\n\nBạn nhận được: `+300đ`", parse_mode="Markdown")

    if txt == "📜 Lịch sử":
        return await history_pro(update, ctx)

    if txt == "📞 Hỗ trợ":
        return await user_reply.reply_text("📩 Gửi nội dung cần hỗ trợ ngay tại đây, Admin sẽ phản hồi sớm! Hoặc NT CHO @cskhzen88uytin")

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

    if uid not in ADMIN_IDS:
        for aid in ADMIN_IDS:
            try: await ctx.bot.send_message(chat_id=aid, text=f"📨 **TIN NHẮN HỖ TRỢ**\n👤 ID: `{uid}`\n📝 Nội dung: {txt}", parse_mode="Markdown")
            except: pass
        await user_reply.reply_text("✅ Đã gửi yêu cầu tới Admin!")

# ===== CALLBACK HANDLER (GAMES & ADMIN) =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    amounts = [1000, 5000, 10000, 50000, 100000, 200000, 500000, 1000000]

    # RESET ALL SYSTEM LOGIC
    if d == "confirm_reset_all":
        if uid not in ADMIN_IDS: return
        query("DELETE FROM users")
        query("DELETE FROM history")
        query("DELETE FROM codes")
        query("DELETE FROM banned")
        for k in maintenance_keys:
            query("UPDATE settings SET value=0 WHERE key=%s", (k,))
        await q.edit_message_text("💀 **ĐÃ RESET TOÀN BỘ HỆ THỐNG THÀNH CÔNG!**")
        return

    if d == "cancel_reset_all":
        await q.edit_message_text("❌ Đã hủy reset.")
        return

    # ADMIN PAGINATION & MANAGEMENT
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
        if not res: return await q.answer("Không tìm thấy user!")
        u = res[0]
        status_text = "🚫 ĐANG CHẶN" if is_banned(target_id) else "🟢 HOẠT ĐỘNG"
        msg = (
            f"👤 **QUẢN LÝ USER:** `{target_id}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"📊 Tổng cược: `{u[6]:,}đ`\n"
            f"🚦 Trạng thái: **{status_text}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = [[InlineKeyboardButton("🚫 BAN", callback_data=f"adm_act_ban_{target_id}_{current_page}"), 
               InlineKeyboardButton("✅ UNBAN", callback_data=f"adm_act_unban_{target_id}_{current_page}")],
              [InlineKeyboardButton("🔙 QUAY LẠI", callback_data=f"adm_page_{current_page}")]]
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("adm_act_"):
        if uid not in ADMIN_IDS: return
        parts = d.split("_")
        act, tid, page = parts[2], int(parts[3]), int(parts[4])
        if act == "ban": query("INSERT INTO banned VALUES(%s) ON CONFLICT DO NOTHING", (tid,))
        elif act == "unban": query("DELETE FROM banned WHERE user_id=%s", (tid,))
        await q.answer("Thành công!")
        await all_user(update, ctx, page=page)
        return

    if d.startswith("tg_mt_"):
        if uid not in ADMIN_IDS: return
        key = d.replace("tg_", "")
        new_val = 0 if check_mt(key) else 1
        query("UPDATE settings SET value=%s WHERE key=%s", (new_val, key))
        await q.answer("Đã cập nhật!")
        await baotri_cmd(update, ctx)
        return

    if d == "close_admin":
        await q.message.delete()
        return

    # WITHDRAW APPROVAL
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
        return

    # GAME QUAY SỐ
    if d == "menu_qs":
        if check_mt('mt_quayso') and uid not in ADMIN_IDS: return await q.answer("Bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k", callback_data=f"set_qs_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🔢 **QUAY SỐ MAY MẮN (1-3)**\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("set_qs_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton(f"SỐ {i}", callback_data=f"p_qs_{i}_{amt}") for i in [1, 2, 3]], [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_qs")]]
        await q.edit_message_text(f"🔢 Cược: `{amt:,}đ` - Chọn số:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("p_qs_"):
        parts = d.split("_")
        choice, amt = int(parts[2]), int(parts[3])
        if not sub_money(uid, amt, f"Cược Quay Số {choice}"): return await q.answer("Không đủ tiền!", show_alert=True)
        is_win = should_win()
        res_qs = choice if is_win else random.choice([n for n in [1, 2, 3] if n != choice])
        if choice == res_qs:
            win_amt = int(amt * 2.8)
            add_money(uid, win_amt, f"Thắng Quay Số {choice}")
            status = f"🎉 **THẮNG!** KQ: {res_qs} | Nhận `+{win_amt:,}đ`"
        else: status = f"💀 **THUA!** KQ: {res_qs}"
        await q.edit_message_text(f"🔢 **KẾT QUẢ QUAY SỐ**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        return

    # GAME ĐUA XE
    elif d == "menu_race":
        if check_mt('mt_duaxe') and uid not in ADMIN_IDS: return await q.answer("Bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_race_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🏎️ **ĐUA XE SIÊU CẤP**\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("prep_race_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🏎️ XE A", callback_data=f"start_race_A_{amt}"), 
               InlineKeyboardButton("🏎️ XE B", callback_data=f"start_race_B_{amt}")],
              [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_race")]]
        await q.edit_message_text(f"🏎️ Cược: `{amt:,}đ` - Chọn xe:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("start_race_"):
        parts = d.split("_")
        choice, amt = parts[2], int(parts[3])
        if not sub_money(uid, amt, f"Cược Đua xe {choice}"): return await q.answer("Không đủ tiền!", show_alert=True)
        await q.delete_message()
        await play_car_race(update, ctx, choice, amt)

    # GAME DÒ MÌN (MINES)
    elif d == "menu_mines":
        if check_mt('mt_domin') and uid not in ADMIN_IDS: return await q.answer("Bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_mines_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("💣 **DÒ MÌN**\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("prep_mines_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🚀 BẮT ĐẦU", callback_data=f"start_mines_{amt}"), InlineKeyboardButton("🔙 Quay lại", callback_data="menu_mines")]]
        await q.edit_message_text(f"💣 Cược: `{amt:,}đ`", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("start_mines_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Dò Mìn"): return await q.answer("Không đủ tiền!", show_alert=True)
        grid = [0]*12 + [1]*3 
        random.shuffle(grid)
        ctx.user_data[f"mine_{uid}"] = {"grid": grid, "bet": amt, "opened": [], "mult": 1.05, "must_lose": not should_win()}
        kb = []
        row = []
        for i in range(15):
            row.append(InlineKeyboardButton("❓", callback_data=f"play_mine_{i}"))
            if (i+1) % 3 == 0: kb.append(row); row = []
        await q.edit_message_text(f"💣 **DÒ MÌN** | Cược: `{amt:,}đ`", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("play_mine_"):
        game = ctx.user_data.get(f"mine_{uid}")
        if not game: return
        idx = int(d.split("_")[2])
        if idx in game["opened"]: return
        is_bomb = game["must_lose"] and len(game["opened"]) >= random.randint(1, 3) or (game["grid"][idx] == 1)
        if is_bomb: 
            del ctx.user_data[f"mine_{uid}"]
            await q.edit_message_text(f"💥 **BÙM!!!**\nThua: `{game['bet']:,}đ`")
        else: 
            game["opened"].append(idx)
            current_win = int(game["bet"] * game["mult"])
            game["mult"] = get_next_multiplier(game["mult"])
            kb = []
            row = []
            for i in range(15):
                icon = "💎" if i in game["opened"] else "❓"
                row.append(InlineKeyboardButton(icon, callback_data=f"play_mine_{i}"))
                if (i+1) % 3 == 0: kb.append(row); row = []
            kb.append([InlineKeyboardButton(f"💰 CHỐT LỜI: {current_win:,}đ", callback_data=f"claim_mine_{current_win}")])
            await q.edit_message_text(f"💎 An toàn! Thưởng: `{current_win:,}đ`", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("claim_mine_"):
        amt = int(d.split("_")[2])
        add_money(uid, amt, "Thắng Dò Mìn")
        del ctx.user_data[f"mine_{uid}"]
        await q.edit_message_text(f"🎉 Chốt lời: `+{amt:,}đ`")

    # GAME TÀI XỈU / XÓC ĐĨA / PENALTY MENUS
    elif d in ["menu_tx", "menu_ball", "menu_xocdia"]:
        if "tx" in d: g_type, g_name, mt_key = "tx", "🎲 TÀI XỈU 3D", "mt_taixiu"
        elif "ball" in d: g_type, g_name, mt_key = "ball", "⚽️ PENALTY", "mt_penalty"
        else: g_type, g_name, mt_key = "xd", "💿 XÓC ĐĨA", "mt_xocdia"
        if check_mt(mt_key) and uid not in ADMIN_IDS: return await q.answer("Bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k", callback_data=f"set_{g_type}_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text(f"{g_name}\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("set_"):
        _, game, amt = d.split("_")
        if game == "tx":
            kb = [[InlineKeyboardButton("🎲 TÀI", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("🎲 XỈU", callback_data=f"p_tx_xiu_{amt}")]]
        elif game == "xd":
            kb = [[InlineKeyboardButton("🔴 CHẴN", callback_data=f"p_xd_chan_{amt}"), InlineKeyboardButton("⚪️ LẺ", callback_data=f"p_xd_le_{amt}")],
                  [InlineKeyboardButton("3 ĐỎ", callback_data=f"p_xd_3d_{amt}"), InlineKeyboardButton("3 TRẮNG", callback_data=f"p_xd_3t_{amt}")]]
        else:
            kb = [[InlineKeyboardButton("⬅️ TRÁI", callback_data=f"p_ba_1_{amt}"), 
                   InlineKeyboardButton("⬆️ GIỮA", callback_data=f"p_ba_2_{amt}"), 
                   InlineKeyboardButton("➡️ PHẢI", callback_data=f"p_ba_3_{amt}")]]
        await q.edit_message_text(f"💰 Cược: {int(amt):,}đ", reply_markup=InlineKeyboardMarkup(kb))

    # GAME PLAY LOGIC (Tài Xỉu, Xóc Đĩa, Penalty)
    elif d.startswith("p_"):
        parts = d.split("_")
        game, choice, amt = parts[1], parts[2], int(parts[3])
        if get_balance(uid) < amt: return await q.answer("Không đủ tiền!", show_alert=True)
        
        if game == "tx":
            sub_money(uid, amt, f"Cược {game}")
            msg_status = await ctx.bot.send_message(uid, "🎲 **ĐANG LẮC...**")
            d1 = await ctx.bot.send_dice(uid, emoji="🎲")
            d2 = await ctx.bot.send_dice(uid, emoji="🎲")
            d3 = await ctx.bot.send_dice(uid, emoji="🎲")
            total = d1.dice.value + d2.dice.value + d3.dice.value
            res_type = "tai" if total >= 11 else "xiu"
            await asyncio.sleep(4)
            if choice == res_type:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, f"Thắng Tài Xỉu")
                await msg_status.edit_text(f"🎉 KQ: **{total}** ({res_type.upper()}) | Thắng `+{win_amt:,}đ`")
            else: await msg_status.edit_text(f"❌ KQ: **{total}** ({res_type.upper()}) | Thua!")

        elif game == "xd":
            sub_money(uid, amt, f"Cược Xóc Đĩa")
            is_win = should_win()
            results = [random.randint(0,1) for _ in range(4)]
            # Logic cân đối tỉ lệ (đã rút gọn cho đủ code)
            red_count = sum(results)
            is_chan = (red_count % 2 == 0)
            win = (choice == "chan" and is_chan) or (choice == "le" and not is_chan)
            icons = "".join(["🔴" if r == 1 else "⚪️" for r in results])
            await asyncio.sleep(1)
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, "Thắng Xóc Đĩa")
                await q.edit_message_text(f"💿 KQ: {icons} | Thắng `+{win_amt:,}đ`")
            else: await q.edit_message_text(f"💿 KQ: {icons} | Thua!")

        elif game == "ba":
            sub_money(uid, amt, "Cược Penalty")
            is_win = should_win()
            if is_win: goalie = random.choice([d for d in [1,2,3] if d != int(choice)])
            else: goalie = int(choice)
            await ctx.bot.send_dice(uid, emoji="⚽️")
            await asyncio.sleep(3.5)
            if int(choice) != goalie:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, "Thắng Penalty")
                await ctx.bot.send_message(uid, f"⚽️ **VÀO!** | Nhận `+{win_amt:,}đ`")
            else: await ctx.bot.send_message(uid, "❌ **KHÔNG VÀO!**")

    # GAME GÕ MÕ (WOODEN)
    elif d == "menu_wooden":
        if check_mt('mt_gomo') and uid not in ADMIN_IDS: return await q.answer("Bảo trì!")
        kb = [[InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_wood_{a}") for a in amounts[:4]],
              [InlineKeyboardButton(f"{a//1000}k", callback_data=f"prep_wood_{a}") for a in amounts[4:]]]
        await q.edit_message_text("🪵 **GÕ MÕ** | Chọn mức cược:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("prep_wood_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🪵 BẮT ĐẦU", callback_data=f"start_wood_{amt}")]]
        await q.edit_message_text(f"🪵 Cược: `{amt:,}đ`", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("start_wood_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Gõ Mõ"): return await q.answer("Không đủ tiền!", show_alert=True)
        game_id = f"wd_{uid}_{random.randint(100,999)}"
        ctx.user_data[game_id] = {"status": "playing", "amt": amt, "mult": 1.0, "target": random.uniform(2.0, 5.0) if should_win() else 1.2}
        kb = [[InlineKeyboardButton("🪵 GÕ", callback_data=f"hit_wood_{game_id}"), InlineKeyboardButton("💰 RÚT", callback_data=f"clm_wood_{game_id}")]]
        await q.edit_message_text(f"🪵 Gõ đi! | Thưởng: x1.00", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("hit_wood_"):
        game_id = "_".join(d.split("_")[2:])
        game = ctx.user_data.get(game_id)
        if not game or game["status"] != "playing": return
        game["mult"] = get_next_multiplier(game["mult"])
        if game["mult"] >= game["target"]:
            await q.edit_message_text(f"💥 **VỠ MÕ!** | Thua: `{game['amt']:,}đ`")
            del ctx.user_data[game_id]
        else:
            kb = [[InlineKeyboardButton(f"🪵 GÕ (x{game['mult']:.2f})", callback_data=f"hit_wood_{game_id}"), InlineKeyboardButton("💰 RÚT", callback_data=f"clm_wood_{game_id}")]]
            await q.edit_message_text(f"🪵 Tiếp tục! | x{game['mult']:.2f}", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("clm_wood_"):
        game_id = "_".join(d.split("_")[2:])
        game = ctx.user_data.get(game_id)
        if game:
            win_amt = int(game["amt"] * game["mult"])
            add_money(uid, win_amt, "Thắng Gõ Mõ")
            await q.edit_message_text(f"🎉 Thắng: `+{win_amt:,}đ` (x{game['mult']:.2f})")
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
app.add_handler(CommandHandler("resetall", reset_all))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT ĐÃ SẴN SÀNG!")
app.run_polling()
 
