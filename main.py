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
GROUP_GAME_ID = -1003937183875 # THAY ID NHÓM CỦA BẠN VÀO ĐÂY ĐỂ BOT TỰ TUNG XÚC SẮC

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

# --- KHỞI TẠO CÁC BẢNG ---
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
    total_bet BIGINT DEFAULT 0,
    rate_bonus INTEGER DEFAULT NULL
)
""")

query("CREATE TABLE IF NOT EXISTS game_rates (id INTEGER PRIMARY KEY, name TEXT, rate INTEGER)")

default_game_names = [
    "TÀI XỈU", "XÓC ĐĨA", "ĐUA XE", "DÒ MÌN", 
    "PENALTY", "GÕ MÕ", "QUAY SỐ", "BẦU CUA"
]
for i, name in enumerate(default_game_names, 1):
    res = query("SELECT 1 FROM game_rates WHERE id=%s", (i,))
    if not res:
        query("INSERT INTO game_rates VALUES(%s, %s, 10)", (i, name))

# Đảm bảo các cột tồn tại
try:
    query("ALTER TABLE users ADD COLUMN total_bet BIGINT DEFAULT 0")
except: pass
try:
    query("ALTER TABLE users ADD COLUMN rate_bonus INTEGER DEFAULT NULL")
except: pass

query("CREATE TABLE IF NOT EXISTS history (user_id BIGINT, amount BIGINT, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id BIGINT PRIMARY KEY)")

query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin', 
    'mt_penalty', 'mt_gomo', 'mt_nap', 'mt_rut', 
    'mt_xocdia', 'mt_quayso', 'mt_baucua'
]
for k in maintenance_keys:
    res = query("SELECT 1 FROM settings WHERE key=%s", (k,))
    if not res:
        query("INSERT INTO settings VALUES(%s, 0)", (k,))

# ===== HÀM KIỂM SOÁT TỈ LỆ MỚI =====
def get_rate_by_id(game_id, user_id=None):
    if user_id:
        res_user = query("SELECT rate_bonus FROM users WHERE user_id=%s", (user_id,))
        if res_user and res_user[0][0] is not None:
            return res_user[0][0]
    res = query("SELECT rate FROM game_rates WHERE id=%s", (game_id,))
    return res[0][0] if res else 10

def check_win_by_id(game_id, user_id=None):
    rate = get_rate_by_id(game_id, user_id)
    return random.randint(1, 100) <= rate

def check_mt(key):
    res = query("SELECT value FROM settings WHERE key=%s", (key,))
    return res[0][0] == 1 if res else False

def get_next_multiplier(current_mult):
    if current_mult < 1.05: return 1.05
    elif current_mult < 1.10: return 1.10
    elif current_mult < 2.0: return round(current_mult + 0.10, 2)
    else: return round(current_mult + 0.20, 2)

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

# ===== LOGIC TÀI XỈU PHIÊN TỰ ĐỘNG (NEW) =====
current_bets = {} # {user_id: [choice, amount]}
game_history = [] # Lưu lịch sử 10 phiên gần nhất

async def auto_dice_loop(app):
    global current_bets, game_history
    phien_id = random.randint(100000, 999999)
    
    while True:
        # Thời gian chờ đặt cược
        await asyncio.sleep(45)
        
        # Bắt đầu tung xúc sắc
        dices = []
        # Tung 3 xúc sắc telegram
        for _ in range(3):
            d_msg = await app.bot.send_dice(GROUP_GAME_ID, emoji="🎲")
            dices.append(d_msg.dice.value)
            await asyncio.sleep(0.5)
        
        total = sum(dices)
        is_tai = 11 <= total <= 18
        res_text = "TÀI" if is_tai else "XỈU"
        dot = "🔴" if is_tai else "⚪️"
        game_history.append(dot)
        if len(game_history) > 12: game_history.pop(0)
        
        history_str = " ".join(game_history)
        
        # Tính thưởng
        total_win = 0
        for uid, data in current_bets.items():
            choice, amt = data[0], data[1]
            win = (choice == 't' and is_tai) or (choice == 'x' and not is_tai)
            if win:
                reward = int(amt * 1.95)
                total_win += reward
                add_money(uid, reward, f"Thắng phiên TX #{phien_id}")
                try: await app.bot.send_message(uid, f"🎉 Chúc mừng! Bạn thắng `{reward:,}đ` ở phiên #{phien_id}")
                except: pass

        # Gửi thông báo tổng kết
        summary = (
            f"🎰 **KẾT QUẢ PHIÊN: #{phien_id}**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎲 Xúc xắc: `{dices[0]} - {dices[1]} - {dices[2]}`\n"
            f"👉 Tổng điểm: **{total}** — **{res_text}**\n"
            f"📈 Lịch sử: {history_str}\n"
            f"💰 Tổng trả thưởng: `{total_win:,}đ`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 Phiên mới sẽ bắt đầu sau 15 giây!"
        )
        await app.bot.send_message(GROUP_GAME_ID, summary, parse_mode="Markdown")
        
        # Reset phiên
        current_bets.clear()
        phien_id += 1
        await asyncio.sleep(15)

# ===== GIỮ NGUYÊN TOÀN BỘ COMMANDS CŨ =====
async def resetsdall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    query("UPDATE users SET balance = 0")
    await update.message.reply_text("✅ Đã xóa toàn bộ số dư của tất cả người dùng về 0!")

async def tileall_set_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/tileall [số]`")
    try:
        new_rate = int(ctx.args[0])
        query("UPDATE game_rates SET rate = %s", (new_rate,))
        await update.message.reply_text(f"✅ Đã chỉnh tất cả game về tỉ lệ thắng: `{new_rate}%`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Tỉ lệ phải là số nguyên.")

async def tile1_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(ctx.args) < 2: return await update.message.reply_text("❌ Cú pháp: `/tile1 [ID] [Tỉ_lệ]`")
    try:
        uid, rate = int(ctx.args[0]), int(ctx.args[1])
        query("UPDATE users SET rate_bonus = %s WHERE user_id = %s", (rate, uid))
        await update.message.reply_text(f"✅ Đã áp dụng tỉ lệ thắng `{rate}%` cho `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Lỗi dữ liệu.")

async def soduall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    users = query("SELECT user_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC")
    if not users: return await update.message.reply_text("Trống.")
    text = "💰 **DANH SÁCH SỐ DƯ:**\n"
    for u in users: text += f"ID: `{u[0]}` | `{u[1]:,}đ`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def tileall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    rates = query("SELECT id, name, rate FROM game_rates ORDER BY id ASC")
    text = "📊 **TỈ LỆ THẮNG:**\n"
    for r in rates: text += f"🆔 `{r[0]}` | {r[1]}: `{r[2]}%` thắng\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def xoalsall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    query("DELETE FROM history")
    await update.message.reply_text("✅ Đã xoá lịch sử hệ thống!")

async def xoals_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/xoals [ID]`")
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM history WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"✅ Đã xoá sạch lịch sử của `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ ID lỗi.")

async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    track_length = 12
    pos_a, pos_b = 0, 0
    finish_line = "🏁"
    msg = await ctx.bot.send_message(uid, "🚦 **SẴN SÀNG...**")
    await asyncio.sleep(1)
    await msg.edit_text("🏎💨 **XUẤT PHÁT!!!**")
    is_win = check_win_by_id(3, uid)
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
    else: res_text = f"💀 **THẤT BẠI!** Xe **{winner}** đã thắng cuộc."
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
    is_win = check_win_by_id(1, uid)
    win = False
    if is_win:
        if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or (c == "XXX" and not is_tai) or (c == "XXT" and is_tai):
            win = True
    else: win = False 
    await asyncio.sleep(4)
    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: status = f"❌ **THUA**"
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args: return await update.message.reply_text("❌ Vui lòng nhập kèm mã.")
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=%s", (code_str,))
    if not data: return await update.message.reply_text("❌ Mã không tồn tại.")
    reward, uses = data[0][1], data[0][2]
    if uses <= 0: return await update.message.reply_text("❌ Mã đã hết lượt.")
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=%s", (code_str,))
    await update.message.reply_text(f"🎉 Nhận: `+{reward:,}đ`", parse_mode="Markdown")

async def tilewin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        game_id, new_rate = int(ctx.args[0]), int(ctx.args[1])
        query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
        await update.message.reply_text(f"✅ Chỉnh game {game_id} thành {new_rate}%", parse_mode="Markdown")
    except: pass

async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
    kb = [
        [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"💿 Xóc Đĩa: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
        [InlineKeyboardButton(f"💳 Nạp: {st('mt_nap')}", callback_data="tg_mt_nap"), InlineKeyboardButton(f"🛒 Rút: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("❌ ĐÓNG", callback_data="close_admin")]
    ]
    await update.message.reply_text("🛠 QUẢN LÝ BẢO TRÌ", reply_markup=InlineKeyboardMarkup(kb))

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id, amount = int(ctx.args[0]), int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await update.message.reply_text(f"✅ Nạp `{amount:,}đ` cho `{target_id}`")
    except: pass

async def reset_all_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ XÁC NHẬN", callback_data="confirm_reset_all_final")]])
    await update.message.reply_text("⚠️ XÓA TOÀN BỘ DỮ LIỆU?", reply_markup=kb)

async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(ctx.args[0])
        res = query("SELECT balance, total_bet FROM users WHERE user_id=%s", (target_id,))
        await update.message.reply_text(f"ID: {target_id}\nSố dư: {res[0][0]:,}đ\nTổng cược: {res[0][1]:,}đ")
    except: pass

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    get_user(uid)
    menu = ReplyKeyboardMarkup([["🎮 Danh sách game", "👤 Tài khoản"], ["💳 Nạp tiền", "🛒 Rút tiền"], ["🎁 Checkin", "🎁 Nhận Code Free"]], resize_keyboard=True)
    await update.message.reply_text("👋 Chào mừng bạn!", reply_markup=menu)

async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid) or (check_mt('mt_rut') and uid not in ADMIN_IDS): return
    res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
    if not res[0][0]: return await update.message.reply_text("Chưa liên kết /lienket")
    try:
        amount = int(ctx.args[0])
        if amount >= MIN_WITHDRAW and sub_money(uid, amount, "Rút tiền"):
            await update.message.reply_text("✅ Đã gửi yêu cầu rút!")
            await ctx.bot.send_message(ADMIN_IDS[0], f"Yêu cầu rút: {uid} - {amount:,}đ")
    except: pass

async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args or len(ctx.args) < 3: return
    query("UPDATE users SET bank=%s, stk=%s, name=%s WHERE user_id=%s", (ctx.args[0], ctx.args[1], ctx.args[2], uid))
    await update.message.reply_text("✅ Đã liên kết!")

# ===== XỬ LÝ ĐẶT CƯỢC TRỰC TIẾP T SỐ TIỀN (NEW) =====
async def handle_text_bet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text.lower()
    if is_banned(uid): return
    
    parts = txt.split()
    if len(parts) == 2 and parts[0] in ['t', 'x'] and parts[1].isdigit():
        if check_mt('mt_taixiu') and uid not in ADMIN_IDS:
            return await update.message.reply_text("⚙️ Hệ thống đang bảo trì!")
            
        choice = parts[0] # 't' hoặc 'x'
        amount = int(parts[1])
        
        if amount < 1000:
            return await update.message.reply_text("❌ Tối thiểu cược 1.000đ")
            
        if sub_money(uid, amount, f"Cược {choice.upper()} phiên"):
            current_bets[uid] = [choice, amount]
            c_name = "TÀI" if choice == 't' else "XỈU"
            await update.message.reply_text(f"✅ Đã đặt **{c_name}** `{amount:,}đ` thành công!")
        else:
            await update.message.reply_text("❌ Số dư không đủ!")
        return True
    return False

# ===== HANDLE MAIN MENU =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    
    # Kiểm tra nếu là tin nhắn đặt cược t/x
    if await handle_text_bet(update, ctx): return

    if txt == "👤 Tài khoản":
        u = query("SELECT balance, total_bet FROM users WHERE user_id=%s", (uid,))[0]
        return await update.message.reply_text(f"🆔 ID: `{uid}`\n💰 Số dư: `{u[0]:,}đ`\n📊 Tổng cược: `{u[1]:,}đ`", parse_mode="Markdown")
    
    if txt == "🎮 Danh sách game":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx"), InlineKeyboardButton("💿 XÓC ĐĨA", callback_data="menu_xocdia")]])
        return await update.message.reply_text("🎮 Chọn game:", reply_markup=kb)

    if txt == "💳 Nạp tiền": return await update.message.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")
    
    if txt == "🎁 Checkin":
        add_money(uid, 300, "Daily Checkin")
        return await update.message.reply_text("🎉 +300đ")

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    
    if d == "confirm_reset_all_final":
        query("TRUNCATE users, history, codes, banned RESTART IDENTITY CASCADE")
        return await q.edit_message_text("✅ ĐÃ RESET")
        
    if d == "menu_tx":
        kb = [[InlineKeyboardButton("10k", callback_data="set_tx_10000"), InlineKeyboardButton("50k", callback_data="set_tx_50000")]]
        await q.edit_message_text("🎲 MỨC CƯỢC TÀI XỈU:", reply_markup=InlineKeyboardMarkup(kb))

    if d.startswith("set_tx_"):
        amt = d.split("_")[2]
        kb = [[InlineKeyboardButton("TÀI", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("XỈU", callback_data=f"p_tx_xiu_{amt}")]]
        await q.edit_message_text(f"Cược {amt}đ vào:", reply_markup=InlineKeyboardMarkup(kb))

    if d.startswith("p_tx_"):
        _, _, choice, amt = d.split("_")
        amt = int(amt)
        if sub_money(uid, amt, f"Cược {choice}"):
            # Logic xúc sắc 3D cũ của bạn
            d1 = await ctx.bot.send_dice(uid, emoji="🎲")
            d2 = await ctx.bot.send_dice(uid, emoji="🎲")
            d3 = await ctx.bot.send_dice(uid, emoji="🎲")
            res = [d1.dice.value, d2.dice.value, d3.dice.value]
            total = sum(res)
            win = (choice == "tai" and total >= 11) or (choice == "xiu" and total < 11)
            await asyncio.sleep(4)
            if win:
                add_money(uid, int(amt*1.95), "Thắng TX")
                await ctx.bot.send_message(uid, f"✅ Thắng! Tổng {total}")
            else: await ctx.bot.send_message(uid, f"❌ Thua! Tổng {total}")
        else: await q.answer("Số dư không đủ")

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()

# Đăng ký các handler
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("lienket", lien_ket))
app.add_handler(CommandHandler("nap", nap_tien_admin))
app.add_handler(CommandHandler("tileall", tileall_set_cmd))
app.add_handler(CommandHandler("tile1", tile1_user_cmd))
app.add_handler(CommandHandler("resetsdall", resetsdall_cmd))
app.add_handler(CommandHandler("baotri", baotri_cmd))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

# Chạy vòng lặp Tài Xỉu tự động chạy ngầm
loop = asyncio.get_event_loop()
loop.create_task(auto_dice_loop(app))

print("BOT ĐÃ SẴN SÀNG VỚI HỆ THỐNG PHIÊN TỰ ĐỘNG!")
app.run_polling()
 
