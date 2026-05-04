from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import psycopg2  
from psycopg2 import extras
from datetime import datetime, timedelta
import os
import asyncio
import random
import logging

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

# --- BIẾN TOÀN CỤC CHO GAME PHIÊN ---
game_data = {
    "session_id": 50281,
    "is_betting_open": True,
    "current_bets": [], # Lưu: {"user_id":..., "choice":..., "amount":...}
    "history_dots": ["🔴", "🔵", "🔵", "🔵", "🔴", "🔵", "🔴", "🔴", "🔴", "🔴", "🔵", "🔴"],
    "history_cl": ["⚫", "⚪", "⚫", "⚫", "⚫", "⚫", "⚪", "⚫", "⚫", "⚫", "⚪", "⚫"],
    "jackpot": 850000
}

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

# Khởi tạo các bảng (Giữ nguyên gốc)
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
    if bal < amt: return False
    now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
    query("UPDATE users SET balance=balance-%s WHERE user_id=%s", (amt, uid))
    query("INSERT INTO history VALUES(%s,%s,%s,%s)", (uid, -amt, note, now_str))
    if note not in ["Rút tiền", "withdraw"] and "Admin" not in note:
        query("UPDATE users SET total_bet=total_bet+%s WHERE user_id=%s", (amt, uid))
    return True

# --- HÀM CHẠY VÒNG LẶP PHIÊN TÀI XỈU TỰ ĐỘNG ---
async def auto_session_loop(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    while True:
        # Bắt đầu phiên
        game_data["is_betting_open"] = True
        game_data["current_bets"] = []
        game_data["session_id"] += 1
        
        # Chờ đặt cược 45 giây
        await asyncio.sleep(45)

        # Đóng cược và kết quả
        game_data["is_betting_open"] = False
        d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2 + d3
        tx_res = "TÀI" if 11 <= total <= 18 else "XỈU"
        cl_res = "CHẴN" if total % 2 == 0 else "LẺ"
        
        win_total, loss_total = 0, 0
        
        # Trả thưởng
        for bet in game_data["current_bets"]:
            is_win = False
            c = bet["choice"]
            if (c == "T" and tx_res == "TÀI") or (c == "X" and tx_res == "XỈU") or \
               (c == "C" and cl_res == "CHẴN") or (c == "L" and cl_res == "LẺ"):
                is_win = True
            
            if is_win:
                win_amt = int(bet["amount"] * 1.95)
                win_total += win_amt
                add_money(bet["user_id"], win_amt, f"Thắng Phiên #{game_data['session_id']}")
            else:
                loss_total += bet["amount"]

        # Cập nhật lịch sử chấm tròn
        game_data["history_dots"].append("🔴" if tx_res == "TÀI" else "🔵")
        game_data["history_cl"].append("⚫" if cl_res == "LẺ" else "⚪")
        if len(game_data["history_dots"]) > 20: game_data["history_dots"].pop(0)

        # Gửi thông báo kết quả vào nhóm
        msg = (
            f"**Kết quả phiên #{game_data['session_id']}**\n"
            f"┌───────────────────┐\n"
            f"  **{d1}  {d2}  {d3}** 👉 **{tx_res} {cl_res}** 🔴⚫\n"
            f"  🎡 Giải vòng quay: {random.randint(1, 9)}\n"
            f"  \n"
            f"  Tổng thắng: **{win_total:,}**\n"
            f"  Tổng thua: **{loss_total:,}**\n"
            f"  Hũ hiện tại: **{game_data['jackpot']:,}**\n"
            f"└───────────────────┘\n\n"
            f"Thống kê: {''.join(game_data['history_dots'])}"
        )
        try: await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        except: pass
        
        await asyncio.sleep(15) # Nghỉ trước khi qua phiên mới

# --- (GIỮ NGUYÊN TOÀN BỘ CÁC HÀM GAME CŨ: play_car_race, play_dice_animation, v.v.) ---
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
        boost_a, boost_b = random.randint(1, 3), random.randint(1, 3)
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
    if choice == winner:
        win_amt = int(amt * 1.95); add_money(uid, win_amt, f"Thắng đua xe {winner}")
        res_text = f"🎉 **CHIẾN THẮNG!** Xe **{winner}** về nhất!\n💰 Nhận: `+{win_amt:,}đ`"
    else: res_text = f"💀 **THẤT BẠI!** Xe **{winner}** đã thắng cuộc."
    await ctx.bot.send_message(uid, f"{res_text}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {choice_code}"): return await update.message.reply_text("❌ Bạn không đủ số dư.")
    msg_status = await update.message.reply_text("🎲 **ĐANG LẮC XÚC XẮC...**", parse_mode="Markdown")
    d1 = await update.message.reply_dice(emoji="🎲"); d2 = await update.message.reply_dice(emoji="🎲"); d3 = await update.message.reply_dice(emoji="🎲")
    results = [d1.dice.value, d2.dice.value, d3.dice.value]; total = sum(results)
    c = choice_code.upper(); is_chan, is_tai = (total % 2 == 0), (total >= 11)
    win = False
    if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or (c == "XXX" and not is_tai) or (c == "XXT" and is_tai): win = True
    await asyncio.sleep(4)
    if win:
        win_amt = int(amount * 1.95); add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: status = f"❌ **THUA**"
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def play_emoji_game(update: Update, game_type, amount):
    uid = update.effective_user.id
    if not sub_money(uid, amount, f"Cược {game_type}"): return await update.message.reply_text("❌ Bạn không đủ số dư.")
    is_win = should_win()
    emojis = {"SLOT": "🎰", "BALL": "⚽️", "RO": "🏀"}
    msg_game = await update.message.reply_dice(emoji=emojis[game_type])
    if is_win:
        if game_type == "SLOT": value = 64
        else: value = 5
    else:
        if game_type == "SLOT": value = 2
        else: value = 1
    await asyncio.sleep(4)
    win, rate = False, 1.95
    if game_type == "SLOT" and value in [1, 22, 43, 64]: win, rate = True, 10.0
    elif game_type == "BALL" and value in [3, 4, 5]: win = True
    elif game_type == "RO" and value in [4, 5]: win = True
    if win:
        win_amt = int(amount * rate); add_money(uid, win_amt, f"Thắng {game_type}")
        res = f"🎉 **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else: res = "💀 **THUA RỒI!**"
    await update.message.reply_text(f"🕹 KQ: {value}\n{res}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# --- (GIỮ NGUYÊN ADMIN COMMANDS: nhap_code, baotri_cmd, nap_tien_admin, v.v.) ---
async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args: return await update.message.reply_text("❌ Vui lòng nhập kèm mã. VD: `/code ABC123`")
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT * FROM codes WHERE code=%s", (code_str,))
    if not data: return await update.message.reply_text("❌ Mã quà tặng không tồn tại.")
    reward, uses = data[0][1], data[0][2]
    if uses <= 0: return await update.message.reply_text("❌ Mã quà tặng này đã hết lượt sử dụng.")
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=%s", (code_str,))
    await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\n💰 Bạn nhận được: `+{reward:,}đ`", parse_mode="Markdown")

async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
    kb = [
        [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"💿 Xóc Đĩa: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
        [InlineKeyboardButton(f"🏎 Đua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"), InlineKeyboardButton(f"💣 Dò Mìn: {st('mt_domin')}", callback_data="tg_mt_domin")],
        [InlineKeyboardButton(f"⚽ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"), InlineKeyboardButton(f"🪵 Gõ Mõ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
        [InlineKeyboardButton(f"🎰 Slot/Khác: {st('mt_slot')}", callback_data="tg_mt_slot"), InlineKeyboardButton(f"🔢 Quay Số: {st('mt_quayso')}", callback_data="tg_mt_quayso")],
        [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"), InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
    ]
    await update.message.reply_text("🛠 **BẢNG QUẢN LÝ BẢO TRÌ**", reply_markup=InlineKeyboardMarkup(kb))

async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id, amount = int(ctx.args[0]), int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await update.message.reply_text(f"✅ **NẠP TIỀN THÀNH CÔNG**")
        try: await ctx.bot.send_message(chat_id=target_id, text=f"💳 **BIẾN ĐỘNG SỐ DƯ**\n+ {amount:,}đ", parse_mode="Markdown")
        except: pass
    except: await update.message.reply_text("❌ Cú pháp: `/nap [ID] [Số tiền]`")

# --- (START & MESSAGE HANDLER - TÍCH HỢP PHIÊN) ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    get_user(uid)

    # Kích hoạt vòng lặp Phiên khi Admin /start trong nhóm
    chat_id = update.effective_chat.id
    if update.effective_chat.type in ['group', 'supergroup']:
        if not ctx.job_queue.get_jobs_by_name(f"loop_{chat_id}"):
            ctx.job_queue.run_once(auto_session_loop, when=0, chat_id=chat_id, name=f"loop_{chat_id}")

    menu = ReplyKeyboardMarkup([
        ["🎮 Danh sách game", "👤 Tài khoản"],
        ["💳 Nạp tiền", "🛒 Rút tiền"],
        ["🎁 Checkin", "🎁 Nhận Code Free"],
        ["📜 Lịch sử", "📞 Hỗ trợ"]
    ], resize_keyboard=True)
    await update.message.reply_text(f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()}!**", reply_markup=menu, parse_mode="Markdown")

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, txt = update.effective_user.id, update.message.text
    if not txt or is_banned(uid): return
    parts = txt.split()

    # --- XỬ LÝ CƯỢC PHIÊN NHANH ---
    if len(parts) == 2 and parts[0].upper() in ["T", "X", "C", "L"] and parts[1].isdigit():
        if not game_data["is_betting_open"]: return await update.message.reply_text("🚫 Phiên đang tổng kết!")
        amt = int(parts[1])
        if sub_money(uid, amt, f"Cược Phiên #{game_data['session_id']} {parts[0].upper()}"):
            game_data["current_bets"].append({"user_id": uid, "choice": parts[0].upper(), "amount": amt})
            return await update.message.reply_text(f"✅ Đã nhận cược: **{parts[0].upper()}** | `{amt:,}đ`", parse_mode="Markdown")
        else: return await update.message.reply_text("❌ Số dư không đủ!")

    # --- CÁC MENU CŨ ---
    if txt == "👤 Tài khoản":
        res = query("SELECT balance, bank, stk, name, refs, total_bet FROM users WHERE user_id=%s", (uid,))
        u = res[0] if res else (0, None, None, None, 0, 0)
        return await update.message.reply_text(f"🆔 ID: `{uid}`\n💰 Số dư: `{u[0]:,}đ`\n📊 Tổng cược: `{u[5]:,}đ`", parse_mode="Markdown")

    if txt == "🎮 Danh sách game":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx"), InlineKeyboardButton("💿 XÓC ĐĨA", callback_data="menu_xocdia")],
            [InlineKeyboardButton("🏎️ ĐUA XE (RACE)", callback_data="menu_race"), InlineKeyboardButton("💣 Dò Mìn", callback_data="menu_mines")],
            [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")],
            [InlineKeyboardButton("🎰 SLOT / 🏀 KHÁC", callback_data="menu_others"), InlineKeyboardButton("🔢 QUAY SỐ (1-3)", callback_data="menu_qs")]
        ])
        return await update.message.reply_text("🎮 **DANH SÁCH TRÒ CHƠI**", reply_markup=kb, parse_mode="Markdown")

    if txt == "💳 Nạp tiền":
        if check_mt('mt_nap') and uid not in ADMIN_IDS: return await update.message.reply_text("⚙️ Bảo trì!")
        return await update.message.reply_text(BANK_INFO.format(uid=uid), parse_mode="Markdown")

    if txt == "🛒 Rút tiền":
        res = query("SELECT bank, stk, name FROM users WHERE user_id=%s", (uid,))
        if not res or not res[0][0]: return await update.message.reply_text("❌ Chưa liên kết /lienket")
        return await update.message.reply_text(f"🏛 Bank: {res[0][0]}\n👉 Nhập: `/rut [số tiền]`", parse_mode="Markdown")

    if txt == "🎁 Checkin":
        today = datetime.now().strftime("%d/%m/%Y")
        res = query("SELECT last_checkin FROM users WHERE user_id=%s", (uid,))
        if res and res[0][0] == today: return await update.message.reply_text("❌ Đã điểm danh!")
        add_money(uid, 300, "Daily Checkin"); query("UPDATE users SET last_checkin=%s WHERE user_id=%s", (today, uid))
        return await update.message.reply_text("🎉 +300đ", parse_mode="Markdown")

    if txt == "📜 Lịch sử": return await history_pro(update, ctx)
    if txt == "📞 Hỗ trợ": return await update.message.reply_text("Liên hệ: @cskhzen88uytin")

    # Xử lý cược 3D cũ (XXT, XXX...)
    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]:
            if check_mt('mt_taixiu') and uid not in ADMIN_IDS: return await update.message.reply_text("⚙️ Bảo trì!")
            return await play_dice_animation(update, code, amt)
        if code in ["SLOT", "BALL", "RÔ"]:
            if code == "RÔ": code = "RO"
            return await play_emoji_game(update, code, amt)

    if uid not in ADMIN_IDS:
        for aid in ADMIN_IDS:
            try: await ctx.bot.send_message(chat_id=aid, text=f"📨 **TIN NHẮN HỖ TRỢ**\n👤 ID: `{uid}`\n📝: {txt}", parse_mode="Markdown")
            except: pass
        await update.message.reply_text("✅ Đã gửi yêu cầu tới Admin!")

# --- (GIỮ NGUYÊN TOÀN BỘ PHẦN CALLBACK_HANDLER VÀ CÁC COMMAND KHÁC CỦA BẠN) ---
# ... (Phần code handle_callback, lien_ket, rut, v.v. được giữ nguyên như file gốc bạn gửi) ...
# Lưu ý: Do giới hạn độ dài, tôi chỉ hiển thị các phần thay đổi chính. Bạn hãy ghép phần handle_callback cũ vào đây.

async def reset_bank(update, ctx):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(ctx.args[0]); query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=%s", (tid,))
        await update.message.reply_text("✅ Đã reset bank")
    except: pass

async def lien_ket(update, ctx):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args or len(ctx.args) < 3: return await update.message.reply_text("`/lienket [Bank] [STK] [Tên]`")
    query("UPDATE users SET bank=%s, stk=%s, name=%s WHERE user_id=%s", (ctx.args[0].upper(), ctx.args[1], " ".join(ctx.args[2:]).upper(), uid))
    await update.message.reply_text("✅ Thành công")

async def rut(update, ctx):
    uid = update.effective_user.id
    if is_banned(uid) or (check_mt('mt_rut') and uid not in ADMIN_IDS): return
    res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
    if not res or not res[0][0]: return await update.message.reply_text("Chưa /lienket")
    try:
        amt = int(ctx.args[0])
        if amt >= MIN_WITHDRAW and sub_money(uid, amt, "Rút tiền"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amt}"), InlineKeyboardButton("❌ No", callback_data=f"no_{uid}_{amt}")]])
            await ctx.bot.send_message(ADMIN_IDS[0], f"🔔 Rút: {uid} | {amt:,}đ", reply_markup=kb)
            await update.message.reply_text("✅ Đang chờ duyệt")
        else: await update.message.reply_text("Số dư ko đủ hoặc lỗi min rút")
    except: pass

async def history_pro(update, ctx):
    uid = update.effective_user.id
    data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC LIMIT 15", (uid,))
    msg = "📜 **LỊCH SỬ:**\n\n"
    for d in data: msg += f"{'➕' if d[0]>0 else '➖'} {abs(d[0]):,} | {d[1]}\n"
    await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    # (Tại đây bạn copy toàn bộ nội dung hàm handle_callback gốc của bạn vào)
    # ... nội dung cũ ...
    await q.answer()
    # (Kết thúc nội dung cũ)

# ===== KHỞI CHẠY BOT =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("baotri", baotri_cmd))
app.add_handler(CommandHandler("code", nhap_code))
app.add_handler(CommandHandler("rut", rut))
app.add_handler(CommandHandler("lienket", lien_ket))
app.add_handler(CommandHandler("resetbank", reset_bank))
app.add_handler(CommandHandler("nap", nap_tien_admin))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("BOT ĐÃ SẴN SÀNG VỚI PHIÊN TÀI XỈU!")
app.run_polling()
 
