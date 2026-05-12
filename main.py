import functools
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import psycopg2
from psycopg2 import extras
from datetime import datetime, timedelta
import os
import asyncio
import random
import csv
from io import BytesIO
import matplotlib.pyplot as plt
import pytz

# ===== MÚI GIỜ VIỆT NAM =====
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

def get_vietnam_time():
    return datetime.now(VIETNAM_TZ)

def get_vietnam_date():
    return get_vietnam_time().strftime("%d/%m/%Y")

def get_vietnam_datetime_db():
    return get_vietnam_time().strftime("%H:%M - %d/%m/%Y")

# ===== GROUP DICE GAME MODULE =====
group_games = {}
room_betting_enabled = {}

DEFAULT_BET_AMOUNTS = [1000, 5000, 10000, 50000, 100000, 500000]
DEFAULT_CYCLE_TIME = 60
DEFAULT_REMINDER_INTERVALS = [60, 40, 20, 10, 5, 4, 3, 2, 1]

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [8619503816, 5260138362, 6886009942]
# ===== THÊM ID CÁC NHÓM CỦA BẠN VÀO ĐÂY =====
GROUP_IDS = []  # VD: [-1001234567890, -1009876543210]
BOT_USERNAME = "zen88uytins1bot"
MIN_WITHDRAW = 50000
LOG_GROUP_ID = -1003663678808

BANK_ID = "TCB"
ACCOUNT_NO = "7980118386"
ACCOUNT_NAME = "LE TRUNG HIEU"

def get_deposit_info(user_id):
    qr_url = f"https://img.vietqr.io/image/{BANK_ID}-{ACCOUNT_NO}-qr_only.png?amount=0&addInfo={user_id}&accountName={ACCOUNT_NAME}"
    caption = (
        "**🏦 THÔNG TIN NẠP TIỀN**\n\n"
        f"🏦 Ngân hàng: **TECHCOMBANK**\n"
        f"👤 CTK: **{ACCOUNT_NAME}**\n"
        f"💳 STK: `{ACCOUNT_NO}`\n"
        f"📝 Nội dung: `{user_id}`\n\n"
        "⚠️ *Lưu ý: Quét mã QR để tự động điền nội dung. Hệ thống cộng tiền sau 1-3 phút.*"
    )
    return qr_url, caption

# ===== DATABASE SETUP =====
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def query(q, args=()):
    conn = get_db_connection()
    cur = conn.cursor()
    res = None
    try:
        cur.execute(q, args)
        if cur.description:
            res = cur.fetchall()
        conn.commit()
    except Exception as e:
        print(f"Database Error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    return res

# ===== KHỞI TẠO CÁC BẢNG =====
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
    rate_bonus INTEGER DEFAULT NULL,
    bank_linked INTEGER DEFAULT 0
)
""")
query("CREATE TABLE IF NOT EXISTS game_rates (id INTEGER PRIMARY KEY, name TEXT, rate INTEGER)")
query("CREATE TABLE IF NOT EXISTS banned_games (user_id BIGINT, game_id INTEGER, PRIMARY KEY (user_id, game_id))")
query("CREATE TABLE IF NOT EXISTS banned_features (user_id BIGINT, feature TEXT, PRIMARY KEY (user_id, feature))")
query("CREATE TABLE IF NOT EXISTS banned_admins (admin_id BIGINT PRIMARY KEY, banned_by BIGINT, reason TEXT, banned_at TEXT)")
query("""
CREATE TABLE IF NOT EXISTS user_bonus (
    user_id BIGINT PRIMARY KEY,
    bonus_amount BIGINT DEFAULT 0,
    required_bet BIGINT DEFAULT 0,
    current_bet BIGINT DEFAULT 0,
    created_at TEXT
)
""")
query("""
CREATE TABLE IF NOT EXISTS deposit_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT,
    admin_id BIGINT,
    status TEXT DEFAULT 'pending',
    time TEXT
)
""")
query("""
CREATE TABLE IF NOT EXISTS withdraw_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT,
    status TEXT DEFAULT 'pending',
    time TEXT,
    admin_id BIGINT,
    admin_note TEXT
)
""")
query("""
CREATE TABLE IF NOT EXISTS banned_admin_commands (
    admin_id BIGINT,
    command TEXT,
    banned_by BIGINT,
    reason TEXT,
    banned_at TEXT,
    PRIMARY KEY (admin_id, command)
)
""")
query("""
CREATE TABLE IF NOT EXISTS code_usage (
    user_id BIGINT,
    code TEXT,
    used_date TEXT,
    PRIMARY KEY (user_id, code, used_date)
)
""")
query("""
CREATE TABLE IF NOT EXISTS group_interactions (
    user_id BIGINT,
    group_id BIGINT,
    interaction_count INTEGER DEFAULT 0,
    last_interaction TEXT,
    PRIMARY KEY (user_id, group_id)
)
""")
query("""
CREATE TABLE IF NOT EXISTS daily_top_interactions (
    user_id BIGINT,
    group_id BIGINT,
    interaction_count INTEGER DEFAULT 0,
    date TEXT,
    rank INTEGER,
    reward_amount BIGINT DEFAULT 0,
    rewarded INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, group_id, date)
)
""")

default_game_names = [
    "TÀI XỈU", "XÓC ĐĨA", "ĐUA XE", "DÒ MÌN",
    "PENALTY", "GÕ MÕ", "QUAY SỐ", "BẦU CUA", "XỔ SỐ", "VÒNG QUAY MAY MẮN",
    "CAO THẤP", "RÚT GỖ", "TÔ MÀU"
]
for i, name in enumerate(default_game_names, 1):
    res = query("SELECT 1 FROM game_rates WHERE id=%s", (i,))
    if not res:
        query("INSERT INTO game_rates VALUES(%s, %s, 10)", (i, name))
    else:
        query("UPDATE game_rates SET name=%s WHERE id=%s", (name, i))

try: query("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_bet BIGINT DEFAULT 0")
except: pass
try: query("ALTER TABLE users ADD COLUMN IF NOT EXISTS rate_bonus INTEGER DEFAULT NULL")
except: pass
try: query("ALTER TABLE users ADD COLUMN IF NOT EXISTS bank_linked INTEGER DEFAULT 0")
except: pass

query("CREATE TABLE IF NOT EXISTS history (user_id BIGINT, amount BIGINT, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id BIGINT PRIMARY KEY)")
query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin',
    'mt_penalty', 'mt_gomo', 'mt_nap', 'mt_rut',
    'mt_xocdia', 'mt_quayso', 'mt_baucua', 'mt_xoso', 'mt_vongquay',
    'mt_caothap', 'mt_rutgo', 'mt_tomau'
]
for k in maintenance_keys:
    res = query("SELECT 1 FROM settings WHERE key=%s", (k,))
    if not res:
        query("INSERT INTO settings VALUES(%s, '0')", (k,))

res_name = query("SELECT 1 FROM settings WHERE key='bot_display_name'")
if not res_name:
    query("INSERT INTO settings(key, value) VALUES('bot_display_name', 'Hệ thống Game Uy Tín')")

res_system_mt = query("SELECT 1 FROM settings WHERE key='system_maintenance'")
if not res_system_mt:
    query("INSERT INTO settings VALUES('system_maintenance', '0')")

res_tongbao = query("SELECT 1 FROM settings WHERE key='mt_tongbao'")
if not res_tongbao:
    query("INSERT INTO settings VALUES('mt_tongbao', '0')")

query("""
CREATE TABLE IF NOT EXISTS daily_treasure (
    user_id BIGINT PRIMARY KEY,
    last_claim TEXT,
    streak INTEGER DEFAULT 0,
    last_reward BIGINT DEFAULT 0
)
""")

# ===== HÀM KIỂM TRA BẢO TRÌ =====
def is_system_maintenance():
    res = query("SELECT value FROM settings WHERE key='system_maintenance'")
    return res[0][0] == '1' if res else False

def is_total_maintenance():
    res = query("SELECT value FROM settings WHERE key='mt_tongbao'")
    return res[0][0] == '1' if res else False

def is_admin_banned(admin_id):
    res = query("SELECT 1 FROM banned_admins WHERE admin_id=%s", (admin_id,))
    return len(res) > 0 if res else False

def is_admin_command_banned(admin_id, command):
    res = query("SELECT 1 FROM banned_admin_commands WHERE admin_id=%s AND command=%s", (admin_id, command))
    return len(res) > 0 if res else False

# ===== KIỂM TRA LIÊN KẾT NGÂN HÀNG (chỉ định nghĩa 1 lần) =====
def check_bank_linked(user_id):
    res = query("SELECT bank, stk, bank_linked FROM users WHERE user_id=%s", (user_id,))
    if res and res[0][0] and res[0][1] and res[0][2] == 1:
        return True
    return False

# ===== DECORATOR ADMIN (có functools.wraps để giữ tên hàm) =====
def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if is_system_maintenance() and user_id not in ADMIN_IDS:
            await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ**\n\nVui lòng quay lại sau ít phút!\nCảm ơn bạn đã thông cảm.", parse_mode="Markdown")
            return
        if user_id in ADMIN_IDS and is_admin_banned(user_id):
            await update.message.reply_text("❌ Bạn đã bị cấm sử dụng các lệnh Admin!\nVui lòng liên hệ Admin cấp cao hơn.", parse_mode="Markdown")
            return
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này!")
            return
        return await func(update, ctx, *args, **kwargs)
    return wrapper

# ===== HÀM KIỂM SOÁT TỈ LỆ =====
def get_rate_by_id(game_id, user_id=None):
    if user_id:
        res_user = query("SELECT rate_bonus FROM users WHERE user_id=%s", (user_id,))
        if res_user and res_user[0][0] is not None:
            return res_user[0][0]
    res = query("SELECT rate FROM game_rates WHERE id=%s", (game_id,))
    return res[0][0] if res else 10

def check_win_by_id(game_id, user_id=None):
    rate = get_rate_by_id(game_id, user_id)
    if rate >= 100: return True
    if rate <= 0: return False
    return random.randint(1, 100) <= rate

def check_mt(key):
    res = query("SELECT value FROM settings WHERE key=%s", (key,))
    return res[0][0] == '1' if res else False

def get_bot_name():
    res = query("SELECT value FROM settings WHERE key='bot_display_name'")
    return res[0][0] if res else "Hệ thống Game Uy Tín"

def is_game_banned(uid, gid):
    res = query("SELECT 1 FROM banned_games WHERE user_id=%s AND game_id=%s", (uid, gid))
    return len(res) > 0 if res else False

def is_feature_banned(uid, feature):
    res = query("SELECT 1 FROM banned_features WHERE user_id=%s AND feature=%s", (uid, feature))
    return len(res) > 0 if res else False

def get_vip_info(total_bet):
    if total_bet >= 50000000: return "VIP 5 (Kim Cương)", 5000
    if total_bet >= 20000000: return "VIP 4 (Vàng)", 3000
    if total_bet >= 10000000: return "VIP 3 (Bạc)", 1500
    if total_bet >= 5000000: return "VIP 2 (Đồng)", 800
    if total_bet >= 1000000: return "VIP 1", 500
    return "Thành viên", 300

def get_next_multiplier(current_mult):
    if current_mult < 1.05: return 1.05
    elif current_mult < 1.10: return 1.10
    elif current_mult < 2.0: return round(current_mult + 0.10, 2)
    else: return round(current_mult + 0.20, 2)

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
    now_str = get_vietnam_datetime_db()
    query("UPDATE users SET balance=balance+%s WHERE user_id=%s", (amt, uid))
    query("INSERT INTO history VALUES(%s,%s,%s,%s)", (uid, amt, note, now_str))

def sub_money(uid, amt, note="withdraw"):
    get_user(uid)
    bal = get_balance(uid)
    if bal < amt:
        return False
    now_str = get_vietnam_datetime_db()
    query("UPDATE users SET balance=balance-%s WHERE user_id=%s", (amt, uid))
    query("INSERT INTO history VALUES(%s,%s,%s,%s)", (uid, -amt, note, now_str))
    if note != "Rút tiền" and note != "withdraw" and "Admin" not in note and "Chuyển tiền" not in note:
        query("UPDATE users SET total_bet=total_bet+%s WHERE user_id=%s", (amt, uid))
    return True

def check_bet_requirement(user_id, bet_amount=0):
    bonus_data = query("SELECT required_bet, current_bet FROM user_bonus WHERE user_id=%s", (user_id,))
    if not bonus_data or bonus_data[0][0] == 0:
        return True, 0
    required_bet, current_bet = bonus_data[0]
    if bet_amount > 0:
        new_bet = current_bet + bet_amount
        query("UPDATE user_bonus SET current_bet=%s WHERE user_id=%s", (new_bet, user_id))
        current_bet = new_bet
    if current_bet >= required_bet:
        return True, 0
    return False, required_bet - current_bet

def add_bonus_with_requirement(user_id, bonus_amount, required_multiplier=3):
    required_bet = bonus_amount * required_multiplier
    now_str = get_vietnam_datetime_db()
    query("DELETE FROM user_bonus WHERE user_id=%s", (user_id,))
    query("INSERT INTO user_bonus (user_id, bonus_amount, required_bet, current_bet, created_at) VALUES (%s, %s, %s, %s, %s)",
          (user_id, bonus_amount, required_bet, 0, now_str))
    add_money(user_id, bonus_amount, f"Khuyến mãi nạp +{bonus_amount:,}đ (yêu cầu cược x{required_multiplier})")
    return required_bet

def get_remaining_bet_required(user_id):
    bonus_data = query("SELECT required_bet, current_bet FROM user_bonus WHERE user_id=%s", (user_id,))
    if not bonus_data or bonus_data[0][0] == 0:
        return 0
    required_bet, current_bet = bonus_data[0]
    return max(0, required_bet - current_bet)

def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== PROMOTIONS =====
PROMOTIONS = [
    {"min": 50000, "bonus": 58000, "display": "50,000đ → +58,000đ"},
    {"min": 100000, "bonus": 128000, "display": "100,000đ → +128,000đ"},
    {"min": 200000, "bonus": 208000, "display": "200,000đ → +208,000đ"},
    {"min": 300000, "bonus": 288000, "display": "300,000đ → +288,000đ"},
    {"min": 400000, "bonus": 488000, "display": "400,000đ → +488,000đ"},
    {"min": 500000, "bonus": 588000, "display": "500,000đ → +588,000đ"},
    {"min": 600000, "bonus": 523000, "display": "600,000đ → +523,000đ"},
    {"min": 700000, "bonus": 688000, "display": "700,000đ → +688,000đ"},
    {"min": 800000, "bonus": 788000, "display": "800,000đ → +788,000đ"},
    {"min": 900000, "bonus": 778000, "display": "900,000đ → +778,000đ"},
    {"min": 1000000, "bonus": 888000, "display": "1,000,000đ → +888,000đ"},
]

def get_promotion_bonus(amount):
    for promo in sorted(PROMOTIONS, key=lambda x: x["min"], reverse=True):
        if amount >= promo["min"]:
            return promo["bonus"]
    return 0

def get_promotion_text():
    text = "🎁 **KHUYẾN MÃI NẠP TIỀN** 🎁\n━━━━━━━━━━━━━━━━━━━━━\n"
    for promo in PROMOTIONS:
        text += f"• Nạp {promo['display']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n📌 **LƯU Ý:**\n• ⏰ Mỗi ngày được nhận 1 lần\n• 💰 Tiền khuyến mãi cần cược **x3** vòng để rút\n• 🎮 Khuyến mãi sau khi nạp tự động lên 100%\n━━━━━━━━━━━━━━━━━━━━━\n📞 **CSKH1:** @sakuri0\n📞 **CSKH2:** @RoGarden\n📞 **CSKH3:** @tomm2710"
    return text

# ===== TƯƠNG TÁC NHÓM =====
async def track_interaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    uid = update.effective_user.id
    gid = update.effective_chat.id
    today = get_vietnam_date()
    now_str = get_vietnam_datetime_db()
    query("""
        INSERT INTO group_interactions (user_id, group_id, interaction_count, last_interaction)
        VALUES (%s, %s, 1, %s)
        ON CONFLICT (user_id, group_id) DO UPDATE SET
            interaction_count = group_interactions.interaction_count + 1,
            last_interaction = %s
    """, (uid, gid, now_str, now_str))
    query("""
        INSERT INTO daily_top_interactions (user_id, group_id, interaction_count, date)
        VALUES (%s, %s, 1, %s)
        ON CONFLICT (user_id, group_id, date) DO UPDATE SET
            interaction_count = daily_top_interactions.interaction_count + 1
    """, (uid, gid, today))
    total = query("SELECT interaction_count FROM group_interactions WHERE user_id=%s AND group_id=%s", (uid, gid))
    if total and total[0][0] >= 200:
        rewarded = query("SELECT 1 FROM daily_top_interactions WHERE user_id=%s AND group_id=%s AND rewarded=1 AND interaction_count>=200", (uid, gid))
        if not rewarded:
            query("UPDATE group_interactions SET interaction_count = -200 WHERE user_id=%s AND group_id=%s", (uid, gid))
            try:
                await ctx.bot.send_message(uid, f"🎉 **CHÚC MỪNG!** 🎉\n━━━━━━━━━━━━━━━━━━━━━\n🔥 Bạn đã đạt **200 lượt tương tác** trong nhóm!\n📞 Hãy liên hệ Admin để nhận thưởng hấp dẫn!\n━━━━━━━━━━━━━━━━━━━━━\n📞 **CSKH1:** @sakuri0\n📞 **CSKH2:** @RoGarden\n📞 **CSKH3:** @tomm2710", parse_mode="Markdown")
            except: pass
            query("UPDATE daily_top_interactions SET rewarded=1 WHERE user_id=%s AND group_id=%s", (uid, gid))

async def send_interaction_reward(ctx: ContextTypes.DEFAULT_TYPE):
    today = get_vietnam_date()
    for gid in GROUP_IDS:
        try:
            top_users = query("""
                SELECT user_id, interaction_count
                FROM daily_top_interactions
                WHERE group_id=%s AND date=%s AND rewarded=0
                ORDER BY interaction_count DESC
                LIMIT 5
            """, (gid, today))
            if not top_users or len(top_users) < 5:
                continue
            rewards = {1: 22000, 2: 11000, 3: 5000, 4: 5000, 5: 5000}
            codes = []
            for i, (uid, count) in enumerate(top_users[:5], 1):
                code = gen_code()
                reward = rewards.get(i, 5000)
                query("INSERT INTO codes (code, reward, uses) VALUES(%s, %s, %s)", (code, reward, 1))
                codes.append(f"Top {i} (ID {uid}): `{code}` - {reward:,}đ")
                query("UPDATE daily_top_interactions SET rank=%s, reward_amount=%s, rewarded=1 WHERE user_id=%s AND group_id=%s AND date=%s", (i, reward, uid, gid, today))
            if codes:
                msg = "🎁 **CODE TƯƠNG TÁC NHÓM** 🎁\n━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(codes) + f"\n━━━━━━━━━━━━━━━━━━━━━\n📅 Ngày: {today}\n📌 Dùng lệnh `/code [mã]` để nhận thưởng!"
                await ctx.bot.send_message(gid, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Lỗi gửi code tương tác nhóm {gid}: {e}")

# ===== GROUP DICE GAME =====
async def run_dice_game_cycle(bot, group_id: int, chat_id: int):
    while True:
        try:
            if not room_betting_enabled.get(group_id, True):
                await asyncio.sleep(10)
                continue
            game_state = {"status": "betting", "bets": {}, "message_id": None, "cycle_start": datetime.now()}
            group_games[group_id] = game_state
            start_msg = await bot.send_message(
                chat_id,
                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n⚡ **ĐẶT CƯỢC NGAY!**\n⏱️ Thời gian còn lại: `60s`\n\n🎯 **CÁCH CHƠI:**\n• Tài (11-18 điểm): `t [số_tiền]`\n• Xỉu (3-10 điểm): `x [số_tiền]`\n• Chẵn (tổng điểm chẵn): `c [số_tiền]`\n• Lẻ (tổng điểm lẻ): `l [số_tiền]`\n\n💰 **MỨC CƯỢC HỢP LỆ:** `1k | 5k | 10k | 50k | 100k | 500k`\n✏️ **CƯỢC TỰ DO:** Nhập số tiền bất kỳ (1k-500k)\n🏆 **Tỉ lệ thưởng: x1.95**\n\n📝 **Ví dụ:** `t 10000` (cược Tài 10,000đ), `c 50000` (cược Chẵn 50,000đ)",
                parse_mode="Markdown"
            )
            game_state["message_id"] = start_msg.message_id
            current_second = DEFAULT_CYCLE_TIME
            last_reminder_second = DEFAULT_CYCLE_TIME
            while current_second > 0:
                await asyncio.sleep(1)
                current_second -= 1
                if not room_betting_enabled.get(group_id, True):
                    try:
                        await bot.edit_message_text("🔴 **PHÒNG ĐÃ BỊ KHÓA CƯỢC**\n\nAdmin đã tắt tính năng đặt cược trong nhóm này.\nVui lòng chờ Admin bật lại!", chat_id=chat_id, message_id=game_state["message_id"], parse_mode="Markdown")
                    except: pass
                    group_games.pop(group_id, None)
                    await asyncio.sleep(5)
                    break
                if current_second in DEFAULT_REMINDER_INTERVALS and current_second != last_reminder_second:
                    last_reminder_second = current_second
                    tai_count = sum(1 for b in game_state['bets'].values() if b["choice"] == "tai")
                    xiu_count = sum(1 for b in game_state['bets'].values() if b["choice"] == "xiu")
                    chan_count = sum(1 for b in game_state['bets'].values() if b["choice"] == "chan")
                    le_count = sum(1 for b in game_state['bets'].values() if b["choice"] == "le")
                    total_players = len(game_state['bets'])
                    try:
                        if current_second >= 10:
                            await bot.edit_message_text(
                                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n⚡ **ĐẶT CƯỢC NGAY!**\n⏱️ Thời gian còn lại: `{current_second}s`\n\n💰 **THỐNG KÊ CƯỢC:**\n🎲 TÀI: `{tai_count}` người\n🎲 XỈU: `{xiu_count}` người\n🔴 CHẴN: `{chan_count}` người\n⚪ LẺ: `{le_count}` người\n━━━━━━━━━━━━━━━━━━━━━\n👥 Tổng số người: `{total_players}`\n📝 Lệnh: `t [tiền]` (TÀI), `x [tiền]` (XỈU), `c [tiền]` (CHẴN), `l [tiền]` (LẺ)",
                                chat_id=chat_id, message_id=game_state["message_id"], parse_mode="Markdown"
                            )
                        else:
                            await bot.edit_message_text(
                                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n⚠️ **CHUẨN BỊ ĐÓNG CƯỢC!**\n⏱️ Còn `{current_second}s`...\n\n💰 Đã có `{total_players}` người đặt cược.\n🎲 TÀI:{tai_count} | XỈU:{xiu_count} | CHẴN:{chan_count} | LẺ:{le_count}",
                                chat_id=chat_id, message_id=game_state["message_id"], parse_mode="Markdown"
                            )
                    except: pass
            if not room_betting_enabled.get(group_id, True):
                continue
            if current_second == 0:
                await bot.send_message(chat_id, "🔒 **CHAT ĐÃ BỊ KHÓA!**\n━━━━━━━━━━━━━━━━━━━━━\n⏳ Đang xử lý kết quả...\nVui lòng chờ giây lát!", parse_mode="Markdown")
            game_state["status"] = "rolling"
            player_count = len(game_state['bets'])
            total_bet_before = sum(b["amount"] for b in game_state['bets'].values())
            tai_total = sum(b["amount"] for b in game_state['bets'].values() if b["choice"] == "tai")
            xiu_total = sum(b["amount"] for b in game_state['bets'].values() if b["choice"] == "xiu")
            chan_total = sum(b["amount"] for b in game_state['bets'].values() if b["choice"] == "chan")
            le_total = sum(b["amount"] for b in game_state['bets'].values() if b["choice"] == "le")
            try:
                await bot.edit_message_text(
                    f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n🔒 **ĐÃ KHÓA CƯỢC!**\n👥 Số người chơi: `{player_count}`\n💰 Tổng cược: `{total_bet_before:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n📊 **CHI TIẾT CƯỢC:**\n🎲 TÀI: `{tai_total:,}đ`\n🎲 XỈU: `{xiu_total:,}đ`\n🔴 CHẴN: `{chan_total:,}đ`\n⚪ LẺ: `{le_total:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n🎲 Đang tung xúc sắc...",
                    chat_id=chat_id, message_id=game_state["message_id"], parse_mode="Markdown"
                )
            except: pass
            await asyncio.sleep(2)
            dice1_msg = await bot.send_dice(chat_id, emoji="🎲")
            dice2_msg = await bot.send_dice(chat_id, emoji="🎲")
            dice3_msg = await bot.send_dice(chat_id, emoji="🎲")
            await asyncio.sleep(4)
            dice1 = dice1_msg.dice.value
            dice2 = dice2_msg.dice.value
            dice3 = dice3_msg.dice.value
            total = dice1 + dice2 + dice3
            result_tx = "tai" if total >= 11 else "xiu"
            result_cl = "chan" if total % 2 == 0 else "le"
            result_text_tx = "TÀI" if result_tx == "tai" else "XỈU"
            result_text_cl = "CHẴN" if result_cl == "chan" else "LẺ"
            total_bet_amount = tai_total_amount = xiu_total_amount = chan_total_amount = le_total_amount = 0
            tai_count = xiu_count = chan_count = le_count = 0
            winners = []
            losers = []
            for uid, bet_info in game_state["bets"].items():
                amount = bet_info["amount"]
                choice = bet_info["choice"]
                total_bet_amount += amount
                if choice == "tai": tai_total_amount += amount; tai_count += 1
                elif choice == "xiu": xiu_total_amount += amount; xiu_count += 1
                elif choice == "chan": chan_total_amount += amount; chan_count += 1
                elif choice == "le": le_total_amount += amount; le_count += 1
                is_win = (choice == "tai" and result_tx == "tai") or (choice == "xiu" and result_tx == "xiu") or (choice == "chan" and result_cl == "chan") or (choice == "le" and result_cl == "le")
                if is_win:
                    win_amount = int(amount * 1.95)
                    add_money(uid, win_amount, f"Thắng Tài Xỉu nhóm: {choice.upper()}")
                    winners.append((uid, amount, win_amount, choice))
                else:
                    losers.append((uid, amount, choice))
            try:
                await bot.delete_message(chat_id, game_state["message_id"])
            except: pass
            result_message = (
                f"🎲 **Kết quả Phiên** 🎲\n━━━━━━━━━━━━━━━━━━━━━\n"
                f"**{dice1}  {dice2}  {dice3}**  ({total}) **{result_text_tx} {result_text_cl}**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n📊 **CHI TIẾT CƯỢC THEO CỬA:**\n"
                f"┌─────────────────────────────────┐\n"
                f"│ 🎲 TÀI   : `{tai_total_amount:>12,}đ`  ({tai_count} người) │\n"
                f"│ 🎲 XỈU   : `{xiu_total_amount:>12,}đ`  ({xiu_count} người) │\n"
                f"│ 🔴 CHẴN  : `{chan_total_amount:>12,}đ`  ({chan_count} người) │\n"
                f"│ ⚪ LẺ    : `{le_total_amount:>12,}đ`  ({le_count} người) │\n"
                f"└─────────────────────────────────┘\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n💰 **Tổng cược:** `{total_bet_amount:,}đ`\n"
                f"👥 **Tổng người chơi:** `{len(game_state['bets'])}`\n━━━━━━━━━━━━━━━━━━━━━\n"
            )
            if winners:
                result_message += f"\n🎉 **NGƯỜI THẮNG ({len(winners)}):**\n"
                for uid, bet, win, ch in winners[:10]:
                    result_message += f"  👤 ID `{uid}`: {ch.upper()} +`{win:,}đ`\n"
                if len(winners) > 10:
                    result_message += f"  ... và {len(winners) - 10} người khác\n"
            if losers:
                result_message += f"\n💀 **NGƯỜI THUA ({len(losers)}):**\n"
                for uid, bet, ch in losers[:10]:
                    result_message += f"  👤 ID `{uid}`: {ch.upper()} -`{bet:,}đ`\n"
                if len(losers) > 10:
                    result_message += f"  ... và {len(losers) - 10} người khác\n"
            result_message += f"\n━━━━━━━━━━━━━━━━━━━━━\n⏱️ Ván tiếp theo sau `{DEFAULT_CYCLE_TIME}s`..."
            await bot.send_message(chat_id, result_message, parse_mode="Markdown")
            await bot.send_message(chat_id, "🔓 **CHAT ĐÃ ĐƯỢC MỞ!**\n━━━━━━━━━━━━━━━━━━━━━\n🎲 Ván mới bắt đầu!\nHãy đặt cược ngay!", parse_mode="Markdown")
            group_games.pop(group_id, None)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ Lỗi trong chu kỳ game của nhóm {group_id}: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(10)

async def place_bet_in_group(bot, user_id: int, group_id: int, choice: str, amount: int, username: str = ""):
    if not check_bank_linked(user_id):
        return False, "❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia cá cược.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`"
    if not room_betting_enabled.get(group_id, True):
        return False, "🔴 **PHÒNG ĐÃ BỊ KHÓA CƯỢC!**\n\nAdmin đã tắt tính năng đặt cược trong nhóm này.\nVui lòng chờ Admin bật lại để tiếp tục chơi!"
    game = group_games.get(group_id)
    if not game or game["status"] != "betting":
        return False, "❌ Hiện tại không có phiên cược nào đang mở! Vui lòng chờ ván tiếp theo."
    balance = get_balance(user_id)
    if balance < amount:
        return False, f"❌ Số dư không đủ! Bạn cần `{amount:,}đ` nhưng chỉ có `{balance:,}đ`."
    if not sub_money(user_id, amount, f"Cược {choice.upper()} nhóm - {amount:,}đ"):
        return False, "❌ Có lỗi xảy ra khi trừ tiền, vui lòng thử lại!"
    game["bets"][user_id] = {"amount": amount, "choice": choice, "username": username}
    return True, f"✅ **ĐẶT CƯỢC THÀNH CÔNG!**\n🎲 Cửa: `{choice.upper()}`\n💰 Số tiền: `{amount:,}đ`"

def get_group_game_status(group_id: int):
    game = group_games.get(group_id)
    return game["status"] if game else None

# ===== CƯỢC TỰ DO =====
def get_betting_keyboard(amounts, callback_prefix, custom_bet=True):
    kb = []
    row = []
    for i, a in enumerate(amounts):
        display = f"{a//1000000}M" if a >= 1000000 else f"{a//1000}k"
        row.append(InlineKeyboardButton(display, callback_data=f"{callback_prefix}_{a}"))
        if (i + 1) % 4 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    if custom_bet:
        kb.append([InlineKeyboardButton("✏️ CƯỢC TỰ DO (Nhập số tiền)", callback_data=f"{callback_prefix}_custom")])
    kb.append([InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")])
    return InlineKeyboardMarkup(kb)

async def request_custom_bet(update_or_query, ctx: ContextTypes.DEFAULT_TYPE, game_name, callback_type, game_id=None):
    if hasattr(update_or_query, 'effective_user'):
        uid = update_or_query.effective_user.id
    else:
        uid = update_or_query.from_user.id
    ctx.user_data[f"custom_bet_{uid}"] = {
        "game_name": game_name, "callback_type": callback_type,
        "game_id": game_id, "step": "waiting_for_amount"
    }
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ HỦY CƯỢC TỰ DO", callback_data="cancel_custom_bet")]])
    text = (f"✏️ **CƯỢC TỰ DO - {game_name}** ✏️\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Vui lòng **nhập số tiền** bạn muốn cược:\n\n"
            f"📌 **Quy định:**\n• Tối thiểu: `1,000đ`\n• Tối đa: `10,000,000đ`\n\n"
            f"📝 **Ví dụ:** `50000` (50k) hoặc `1000000` (1 triệu)\n\n⏳ Nhập số tiền ngay bên dưới!")
    if hasattr(update_or_query, 'message') and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    elif hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def handle_custom_bet_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if f"custom_bet_{uid}" not in ctx.user_data:
        return False
    bet_data = ctx.user_data[f"custom_bet_{uid}"]
    if bet_data.get("step") != "waiting_for_amount":
        return False
    try:
        amount = int(text.replace(",", "").replace(".", ""))
        if amount < 1000:
            await update.message.reply_text("❌ Số tiền cược tối thiểu là `1,000đ`!\nVui lòng nhập lại:", parse_mode="Markdown")
            return True
        if amount > 10000000:
            await update.message.reply_text("❌ Số tiền cược tối đa là `10,000,000đ`!\nVui lòng nhập lại:", parse_mode="Markdown")
            return True
    except ValueError:
        await update.message.reply_text("❌ Số tiền không hợp lệ!\nVui lòng nhập số nguyên (VD: 50000):", parse_mode="Markdown")
        return True
    balance = get_balance(uid)
    if balance < amount:
        await update.message.reply_text(f"❌ Số dư không đủ!\n💰 Số dư của bạn: `{balance:,}đ`\n💰 Bạn muốn cược: `{amount:,}đ`\n\nVui lòng nhập số tiền nhỏ hơn:", parse_mode="Markdown")
        return True
    bet_data["amount"] = amount
    bet_data["step"] = "waiting_for_choice"
    game_type = bet_data["callback_type"]
    kb = None
    if game_type in ("tx", "tx_group"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 TÀI (x1.95)", callback_data=f"p_tx_tai_{amount}"),
             InlineKeyboardButton("🎲 XỈU (x1.95)", callback_data=f"p_tx_xiu_{amount}")],
            [InlineKeyboardButton("🔴 CHẴN (x1.95)", callback_data=f"p_tx_chan_{amount}"),
             InlineKeyboardButton("⚪ LẺ (x1.95)", callback_data=f"p_tx_le_{amount}")],
            [InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]
        ])
        await update.message.reply_text(f"✅ **ĐÃ CHỌN CƯỢC TỰ DO**\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số tiền: `{amount:,}đ`\n\n🎲 **Chọn cửa cược:**", reply_markup=kb, parse_mode="Markdown")
        del ctx.user_data[f"custom_bet_{uid}"]
    elif game_type == "hl":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 CAO HƠN", callback_data=f"hl_choice_higher_{amount}"),
             InlineKeyboardButton("📉 THẤP HƠN", callback_data=f"hl_choice_lower_{amount}")],
            [InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]
        ])
        card_names = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}
        first_card = random.randint(1, 13)
        first_name = card_names.get(first_card, str(first_card))
        ctx.user_data[f"hl_{uid}"] = {"first_card": first_card, "bet": amount, "status": "waiting"}
        await update.message.reply_text(f"🃏 **LÁ BÀI ĐẦU TIÊN:** `{first_name}`\n💰 **Cược:** `{amount:,}đ`\n\n🤔 **Bạn dự đoán lá tiếp theo?**", reply_markup=kb, parse_mode="Markdown")
        del ctx.user_data[f"custom_bet_{uid}"]
    elif game_type == "sg":
        ctx.user_data[f"sg_{uid}"] = {"sticks": 15, "bet": amount, "turn": "player", "game_id": random.randint(1000, 9999)}
        kb = [[InlineKeyboardButton("🪵 RÚT 1 QUE", callback_data=f"sg_pull_{uid}_1"),
               InlineKeyboardButton("🪵 RÚT 2 QUE", callback_data=f"sg_pull_{uid}_2"),
               InlineKeyboardButton("🪵 RÚT 3 QUE", callback_data=f"sg_pull_{uid}_3")],
              [InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")]]
        await update.message.reply_text(f"🪵 **RÚT GỖ - BẮT ĐẦU!** 🪵\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Cược:** `{amount:,}đ`\n🪵 **Số que còn lại:** `15`\n━━━━━━━━━━━━━━━━━━━━━\n👉 **Lượt của bạn!** Rút que:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        del ctx.user_data[f"custom_bet_{uid}"]
    elif game_type == "cf":
        ctx.user_data[f"cf_{uid}"] = {"grid": [[0,0,0],[0,0,0],[0,0,0]], "bet": amount, "filled": 0}
        icons = ["⬜", "🟩"]
        display = "🎨 **BẢNG TÔ MÀU** 🎨\n━━━━━━━━━━━━━━━━━━━━━\n│ ⬜⬜⬜ │\n│ ⬜⬜⬜ │\n│ ⬜⬜⬜ │\n━━━━━━━━━━━━━━━━━━━━━\n👉 **Chọn ô để tô màu:**"
        kb = []
        for i in range(3):
            row = [InlineKeyboardButton("⬜", callback_data=f"cf_fill_{i}_{j}") for j in range(3)]
            kb.append(row)
        kb.append([InlineKeyboardButton("💰 CHỐT NHẬN THƯỞNG", callback_data=f"cf_claim_{uid}")])
        kb.append([InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")])
        await update.message.reply_text(display, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        del ctx.user_data[f"custom_bet_{uid}"]
    return True

# ===== GAME: TÀI XỈU PRIVATE =====
async def play_dice_animation(update: Update, choice_code, amount):
    uid = update.effective_user.id
    if is_game_banned(uid, 1):
        return await update.message.reply_text("❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
    if not sub_money(uid, amount, f"Cược {choice_code}"):
        return await update.message.reply_text("❌ Bạn không đủ số dư.")
    msg_status = await update.message.reply_text("🎲 **ĐANG LẮC XÚC XẮC...**", parse_mode="Markdown")
    d1 = await update.message.reply_dice(emoji="🎲")
    d2 = await update.message.reply_dice(emoji="🎲")
    d3 = await update.message.reply_dice(emoji="🎲")
    await asyncio.sleep(4)
    results = [d1.dice.value, d2.dice.value, d3.dice.value]
    total = sum(results)
    c = choice_code.upper()
    is_chan, is_tai = (total % 2 == 0), (total >= 11)
    is_win_flag = check_win_by_id(1, uid)
    win = False
    if is_win_flag:
        if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or (c == "XXX" and not is_tai) or (c == "XXT" and is_tai):
            win = True
    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng {c}")
        status = f"✅ **THẮNG** | Nhận: `+{win_amt:,}đ`"
    else:
        status = f"❌ **THUA**"
    res_str = "-".join(map(str, results))
    await msg_status.edit_text(f"🎲 Kết quả: **{res_str}** => **{total}**\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# ===== GAME: ĐUA XE =====
async def play_car_race(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choice, amt):
    uid = update.effective_user.id
    if is_game_banned(uid, 3):
        return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
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
    win = (choice == target_winner)
    if win:
        win_amt = int(amt * 1.95)
        add_money(uid, win_amt, f"Thắng đua xe {target_winner}")
        res_text = f"🎉 **CHIẾN THẮNG!** Xe **{target_winner}** về nhất!\n💰 Nhận: `+{win_amt:,}đ`"
    else:
        res_text = f"💀 **THẤT BẠI!** Xe **{target_winner}** đã thắng cuộc."
    await ctx.bot.send_message(uid, f"{res_text}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# ===== GAME: CAO THẤP =====
async def play_highlow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not check_bank_linked(uid):
        return await update.message.reply_text("❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia chơi game.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
    if is_game_banned(uid, 11):
        return await update.message.reply_text("❌ Bạn đã bị cấm chơi trò chơi này!")
    if check_mt('mt_caothap') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Game Cao Thấp đang bảo trì!")
    amounts = [1000, 5000, 10000, 50000, 100000]
    kb = get_betting_keyboard(amounts, "hl_bet")
    await update.message.reply_text("🃏 **CAO THẤP - SO SÁNH LÁ BÀI** 🃏\n\n📖 **LUẬT CHƠI:**\n• Bạn sẽ nhận 1 lá bài ngẫu nhiên (A, 2-10, J, Q, K)\n• Đoán lá bài tiếp theo CAO HƠN hoặc THẤP HƠN\n• Nếu đoán đúng: Thưởng x1.95\n• Lá bài bằng nhau: HÒA, hoàn tiền\n\n💰 **Chọn mức cược hoặc nhập số tiền:**", reply_markup=kb, parse_mode="Markdown")

async def highlow_choice_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    choice = parts[2]
    amount = int(parts[3])
    game = ctx.user_data.get(f"hl_{uid}")
    if not game:
        await q.answer("❌ Game đã hết hạn!", show_alert=True)
        return
    if not sub_money(uid, amount, f"Cược Cao Thấp"):
        await q.answer("❌ Số dư không đủ!", show_alert=True)
        ctx.user_data.pop(f"hl_{uid}", None)
        return
    first_card = game["first_card"]
    card_names = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}
    first_name = card_names.get(first_card, str(first_card))
    second_card = random.randint(1, 13)
    second_name = card_names.get(second_card, str(second_card))
    if second_card == first_card:
        add_money(uid, amount, "Hoàn tiền Cao Thấp")
        await q.edit_message_text(f"🃏 **KẾT QUẢ CAO THẤP** 🃏\n━━━━━━━━━━━━━━━━━━━━━\n🃏 **Lá bài đầu:** `{first_name}`\n🃏 **Lá bài sau:** `{second_name}`\n📊 **Kết quả:** HÒA\n━━━━━━━━━━━━━━━━━━━━━\n🔄 **Bạn được hoàn tiền!**\n💰 Hoàn: `+{amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        ctx.user_data.pop(f"hl_{uid}", None)
        return
    is_win = False
    result_text = ""
    if choice == "higher" and second_card > first_card:
        is_win = True; result_text = "CAO HƠN"
    elif choice == "lower" and second_card < first_card:
        is_win = True; result_text = "THẤP HƠN"
    elif choice == "higher":
        result_text = "THẤP HƠN"
    else:
        result_text = "CAO HƠN"
    win_rate = check_win_by_id(11, uid)
    if not win_rate:
        is_win = False
    await q.answer()
    if is_win:
        win_amount = int(amount * 1.95)
        add_money(uid, win_amount, f"Thắng Cao Thấp")
        await q.edit_message_text(f"🃏 **KẾT QUẢ CAO THẤP** 🃏\n━━━━━━━━━━━━━━━━━━━━━\n🃏 **Lá bài đầu:** `{first_name}`\n🃏 **Lá bài sau:** `{second_name}`\n📊 **Kết quả:** {result_text}\n━━━━━━━━━━━━━━━━━━━━━\n🎉 **BẠN THẮNG!**\n💰 Nhận: `+{win_amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
    else:
        await q.edit_message_text(f"🃏 **KẾT QUẢ CAO THẤP** 🃏\n━━━━━━━━━━━━━━━━━━━━━\n🃏 **Lá bài đầu:** `{first_name}`\n🃏 **Lá bài sau:** `{second_name}`\n📊 **Kết quả:** {result_text}\n━━━━━━━━━━━━━━━━━━━━━\n💀 **BẠN THUA!**\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
    ctx.user_data.pop(f"hl_{uid}", None)

# ===== GAME: RÚT GỖ =====
async def play_stick_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not check_bank_linked(uid):
        return await update.message.reply_text("❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia chơi game.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
    if is_game_banned(uid, 12):
        return await update.message.reply_text("❌ Bạn đã bị cấm chơi trò chơi này!")
    if check_mt('mt_rutgo') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Game Rút Gỗ đang bảo trì!")
    amounts = [1000, 5000, 10000, 50000, 100000]
    kb = get_betting_keyboard(amounts, "sg_bet")
    await update.message.reply_text("🪵 **GAME RÚT GỖ** 🪵\n\n📖 **LUẬT CHƠI:**\n• Có 15 que gỗ\n• Mỗi lượt rút 1-3 que\n• Người rút que cuối cùng sẽ THUA\n• Bạn chơi với Bot\n\n💰 **Chọn mức cược hoặc nhập số tiền:**", reply_markup=kb, parse_mode="Markdown")

async def stick_pull_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    pull_amount = int(parts[3])
    game = ctx.user_data.get(f"sg_{uid}")
    if not game or game["turn"] != "player":
        await q.answer("❌ Không phải lượt của bạn!", show_alert=True)
        return
    if not sub_money(uid, game["bet"], f"Cược Rút Gỗ"):
        await q.answer("❌ Số dư không đủ!", show_alert=True)
        ctx.user_data.pop(f"sg_{uid}", None)
        return
    game["sticks"] -= pull_amount
    if game["sticks"] <= 0:
        win_amount = int(game["bet"] * 1.95)
        add_money(uid, win_amount, f"Thắng Rút Gỗ")
        await q.edit_message_text(f"🪵 **KẾT THÚC GAME RÚT GỖ** 🪵\n━━━━━━━━━━━━━━━━━━━━━\n🎉 **BẠN THẮNG!**\n🤖 Bot đã thua!\n💰 Nhận: `+{win_amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        ctx.user_data.pop(f"sg_{uid}", None)
        return
    is_win_match = check_win_by_id(12, uid)
    if is_win_match:
        bot_pull = random.randint(1, min(3, game["sticks"]))
    else:
        if game["sticks"] <= 3: bot_pull = game["sticks"]
        elif game["sticks"] <= 6: bot_pull = random.randint(1, 2)
        else: bot_pull = random.randint(1, 3)
    game["sticks"] -= bot_pull
    if game["sticks"] <= 0:
        await q.edit_message_text(f"🪵 **KẾT THÚC GAME RÚT GỖ** 🪵\n━━━━━━━━━━━━━━━━━━━━━\n💀 **BẠN THUA!**\n🤖 Bot rút `{bot_pull}` que cuối cùng\n💰 Mất: `{game['bet']:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        ctx.user_data.pop(f"sg_{uid}", None)
        return
    game["turn"] = "player"
    kb = [[InlineKeyboardButton("🪵 RÚT 1 QUE", callback_data=f"sg_pull_{uid}_1"),
           InlineKeyboardButton("🪵 RÚT 2 QUE", callback_data=f"sg_pull_{uid}_2"),
           InlineKeyboardButton("🪵 RÚT 3 QUE", callback_data=f"sg_pull_{uid}_3")],
          [InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")]]
    await q.edit_message_text(f"🪵 **RÚT GỖ - TIẾP TỤC** 🪵\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Cược:** `{game['bet']:,}đ`\n🪵 **Số que còn lại:** `{game['sticks']}`\n━━━━━━━━━━━━━━━━━━━━━\n🤖 Bot rút `{bot_pull}` que\n👉 **Lượt của bạn!**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ===== GAME: TÔ MÀU =====
async def play_color_fill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not check_bank_linked(uid):
        return await update.message.reply_text("❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia chơi game.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
    if is_game_banned(uid, 13):
        return await update.message.reply_text("❌ Bạn đã bị cấm chơi trò chơi này!")
    if check_mt('mt_tomau') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Game Tô Màu đang bảo trì!")
    amounts = [5000, 10000, 20000, 50000]
    kb = get_betting_keyboard(amounts, "cf_bet")
    await update.message.reply_text("🎨 **GAME TÔ MÀU** 🎨\n\n📖 **LUẬT CHƠI:**\n• Có 9 ô vuông (3x3)\n• Mỗi lượt chọn 1 ô để tô màu\n• Nếu tạo thành 1 hàng/dọc/chéo sẽ THẮNG\n• Hoàn thành bảng sẽ nhận thưởng lớn hơn!\n\n💰 **Chọn mức cược hoặc nhập số tiền:**", reply_markup=kb, parse_mode="Markdown")

async def update_cf_grid(q, uid, ctx):
    game = ctx.user_data.get(f"cf_{uid}")
    if not game:
        return
    grid = game["grid"]
    icons = ["⬜", "🟩"]
    display = "🎨 **BẢNG TÔ MÀU** 🎨\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i in range(3):
        row_display = "".join(icons[grid[i][j]] for j in range(3))
        display += f"│ {row_display} │\n"
    display += f"━━━━━━━━━━━━━━━━━━━━━\n💰 **Cược:** `{game['bet']:,}đ`\n🎨 **Đã tô:** `{game['filled']}/9` ô\n\n👉 **Chọn ô để tô màu:**"
    kb = []
    for i in range(3):
        row = []
        for j in range(3):
            if grid[i][j] == 0:
                row.append(InlineKeyboardButton("⬜", callback_data=f"cf_fill_{i}_{j}"))
            else:
                row.append(InlineKeyboardButton("🟩", callback_data="cf_filled"))
        kb.append(row)
    kb.append([InlineKeyboardButton("💰 CHỐT NHẬN THƯỞNG", callback_data=f"cf_claim_{uid}")])
    kb.append([InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")])
    await q.edit_message_text(display, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def cf_fill_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data_parts = q.data.split("_")
    i, j = int(data_parts[2]), int(data_parts[3])
    game = ctx.user_data.get(f"cf_{uid}")
    if not game or game["grid"][i][j] == 1:
        await q.answer("❌ Ô này đã được tô rồi!", show_alert=True)
        return
    if not sub_money(uid, game["bet"], f"Cược Tô Màu"):
        await q.answer("❌ Số dư không đủ!", show_alert=True)
        ctx.user_data.pop(f"cf_{uid}", None)
        return
    game["grid"][i][j] = 1
    game["filled"] += 1
    win_rate = check_win_by_id(13, uid)
    is_win = False
    if win_rate:
        for row in range(3):
            if all(game["grid"][row][col] == 1 for col in range(3)):
                is_win = True; break
        if not is_win:
            for col in range(3):
                if all(game["grid"][row][col] == 1 for row in range(3)):
                    is_win = True; break
        if not is_win:
            if all(game["grid"][k][k] == 1 for k in range(3)) or all(game["grid"][k][2-k] == 1 for k in range(3)):
                is_win = True
    if is_win:
        win_amount = int(game["bet"] * 2.5)
        add_money(uid, win_amount, f"Thắng Tô Màu (hoàn thành hàng)")
        await q.edit_message_text(f"🎨 **CHÚC MỪNG!** 🎨\n━━━━━━━━━━━━━━━━━━━━━\n🎉 Bạn đã tạo thành 1 hàng/dòng!\n💰 Nhận: `+{win_amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        ctx.user_data.pop(f"cf_{uid}", None)
        return
    if game["filled"] == 9:
        win_amount = int(game["bet"] * 3.0)
        add_money(uid, win_amount, f"Thắng Tô Màu (hoàn thành bảng)")
        await q.edit_message_text(f"🎨 **SIÊU CHÚC MỪNG!** 🎨\n━━━━━━━━━━━━━━━━━━━━━\n🏆 Bạn đã hoàn thành toàn bộ bảng!\n💰 Nhận: `+{win_amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        ctx.user_data.pop(f"cf_{uid}", None)
        return
    await update_cf_grid(q, uid, ctx)

async def cf_claim_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data_parts = q.data.split("_")
    uid = int(data_parts[2])
    if uid != q.from_user.id:
        await q.answer("❌ Không phải game của bạn!", show_alert=True)
        return
    game = ctx.user_data.get(f"cf_{uid}")
    if not game:
        await q.answer("❌ Game không tồn tại!", show_alert=True)
        return
    claim_amount = int(game["bet"] * (game["filled"] / 9 * 1.5))
    if claim_amount > 0:
        add_money(uid, claim_amount, f"Nhận thưởng Tô Màu")
        await q.edit_message_text(f"🎨 **NHẬN THƯỞNG** 🎨\n━━━━━━━━━━━━━━━━━━━━━\n🖼️ Bạn đã tô `{game['filled']}/9` ô\n💰 Nhận: `+{claim_amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
    else:
        await q.edit_message_text("❌ Chưa có ô nào được tô, không thể nhận thưởng!")
    ctx.user_data.pop(f"cf_{uid}", None)

# ===== LỆNH CƠ BẢN =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_total_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return
    if is_system_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return
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
        ["🎮 DANH SÁCH GAME", "👤 TÀI KHOẢN VIP"],
        ["💳 NẠP TIỀN", "🛒 RÚT TIỀN"],
        ["🎁 CHECKIN", "🎁 CODE TÂN THỦ", "🎁 KHUYẾN MÃI NẠP"],
        ["📜 LỊCH SỬ", "🏆 TOP ĐẠI GIA"],
        ["📞 HỖ TRỢ CSKH1", "📞 HỖ TRỢ CSKH2", "📞 HỖ TRỢ CSKH3"]
    ], resize_keyboard=True)
    welcome_text = (f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()} ĐÃ THAM GIA!**\n\n🛡 **{get_bot_name()}**\nHệ thống trò chơi minh bạch — uy tín hàng đầu.\n━━━━━━━━━━━━━━━━━━━━━\n💰 **MIN RÚT TIỀN:** `50,000đ`\n💳 **MIN NẠP TIỀN:** `10,000đ`\n⚠️ *Lưu ý: Nạp dưới 10k sẽ không được tự động duyệt.*\n\n⚖️ **CAM KẾT MINH BẠCH:**\n• **100%** Kết quả hoàn toàn ngẫu nhiên.\n• 🔄 **KHÔNG** can thiệp kết quả dưới mọi hình thức.\n━━━━━━━━━━━━━━━━━━━━━\n🚀 Chúc bạn có những trải nghiệm may mắn và thú vị!")
    await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode="Markdown")

async def checkin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_total_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 Hệ thống đang bảo trì!", parse_mode="Markdown")
        return
    today = get_vietnam_date()
    res = query("SELECT last_checkin FROM users WHERE user_id=%s", (uid,))
    if not res:
        get_user(uid)
        res = query("SELECT last_checkin FROM users WHERE user_id=%s", (uid,))
    last_checkin = res[0][0] if res else None
    if last_checkin == today:
        await update.message.reply_text(f"✅ **BẠN ĐÃ CHECKIN HÔM NAY RỒI!**\n\n📅 Ngày: `{today}`\n⏰ Quay lại vào ngày mai nhé!", parse_mode="Markdown")
        return
    total_bet = query("SELECT total_bet FROM users WHERE user_id=%s", (uid,))[0][0] or 0
    _, bonus_per_day = get_vip_info(total_bet)
    bonus = bonus_per_day + random.randint(0, 2000)
    add_money(uid, bonus, f"Checkin ngày {today}")
    query("UPDATE users SET last_checkin=%s WHERE user_id=%s", (today, uid))
    await update.message.reply_text(f"🎁 **CHECKIN THÀNH CÔNG!**\n━━━━━━━━━━━━━━━━━━━━━\n📅 Ngày: `{today}`\n💰 Nhận được: `+{bonus:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n⏰ Quay lại ngày mai để nhận tiếp!", parse_mode="Markdown")

async def lien_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_total_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return
    res = query("SELECT bank FROM users WHERE user_id=%s", (uid,))
    if res and res[0][0] is not None:
        return await update.message.reply_text("❌ Bạn đã liên kết ngân hàng rồi. Để thay đổi, vui lòng liên hệ Admin!", parse_mode="Markdown")
    if not ctx.args or len(ctx.args) < 3:
        return await update.message.reply_text("⚠️ **Cú pháp liên kết:**\n`/lienket [Ngân_hàng] [STK] [Chủ_TK]`\n\nVD: `/lienket MBBANK 0123456 NGUYEN VAN A`", parse_mode="Markdown")
    bank = ctx.args[0].upper()
    stk = ctx.args[1]
    name = " ".join(ctx.args[2:]).upper()
    query("UPDATE users SET bank=%s, stk=%s, name=%s, bank_linked=1 WHERE user_id=%s", (bank, stk, name, uid))
    await update.message.reply_text(f"✅ **LIÊN KẾT THÀNH CÔNG**\n\n🏛 Ngân hàng: {bank}\n💳 STK: `{stk}`\n👤 Chủ TK: {name}\n\n🎮 Bạn đã có thể tham gia chơi game!", parse_mode="Markdown")

async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_feature_banned(uid, 'rut'):
        return await update.message.reply_text("❌ Tính năng RÚT TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
    if check_mt('mt_rut') and uid not in ADMIN_IDS:
        return await update.message.reply_text("⚙️ Hệ thống Rút Tiền đang bảo trì, vui lòng quay lại sau!")
    if is_total_maintenance() and uid not in ADMIN_IDS:
        return await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
    res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
    if not res or not res[0][0] or not res[0][1]:
        return await update.message.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`\n\n📌 **MIN RÚT:** `50,000đ`", parse_mode="Markdown")
    u = res[0]
    if not ctx.args:
        return await update.message.reply_text(f"💰 **Số dư:** `{u[3]:,}đ`\n📌 **MIN RÚT:** `50,000đ`\n\n📝 Nhập số tiền muốn rút: `/rut [số_tiền]`", parse_mode="Markdown")
    try:
        amount = int(ctx.args[0])
        if amount < 50000:
            return await update.message.reply_text(f"❌ Số tiền rút tối thiểu là `50,000đ`", parse_mode="Markdown")
        can_withdraw, remaining = check_bet_requirement(uid)
        if not can_withdraw:
            return await update.message.reply_text(f"⚠️ **CHƯA ĐỦ ĐIỀU KIỆN RÚT TIỀN!**\n\n💰 Bạn đang có tiền khuyến mãi cần cược đủ **x3** vòng.\n📊 **Cần cược thêm:** `{remaining:,}đ`\n\n🎮 Hãy tham gia các trò chơi để hoàn thành yêu cầu nhé!", parse_mode="Markdown")
        if sub_money(uid, amount, "Rút tiền"):
            bank, stk, name = u[0], u[1], u[2]
            now_str = get_vietnam_datetime_db()
            query("INSERT INTO withdraw_history (user_id, amount, status, time) VALUES (%s, %s, %s, %s)", (uid, amount, 'pending', now_str))
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"ok_{uid}_{amount}"), InlineKeyboardButton("❌ Từ chối", callback_data=f"no_{uid}_{amount}")]])
            for admin_id in ADMIN_IDS:
                try:
                    await ctx.bot.send_message(admin_id, f"🔔 **YÊU CẦU RÚT TIỀN MỚI** 🔔\n━━━━━━━━━━━━━━━━━━━━━\n👤 **ID Người dùng:** `{uid}`\n💰 **Số tiền:** `{amount:,}đ`\n🏛 **Ngân hàng:** `{bank}`\n💳 **STK:** `{stk}`\n👤 **Chủ TK:** `{name}`\n━━━━━━━━━━━━━━━━━━━━━\n⏰ **Thời gian:** `{now_str}`\n\n👇 **Bấm để xử lý:**", reply_markup=keyboard, parse_mode="Markdown")
                except: pass
            await update.message.reply_text(f"✅ **GỬI YÊU CẦU RÚT THÀNH CÔNG!**\n\n💰 Số tiền: `{amount:,}đ`\n⏳ Vui lòng chờ Admin duyệt (1-5 phút).", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Số dư không đủ.")
    except:
        await update.message.reply_text("❌ Số tiền không hợp lệ.")

async def top_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    text = "🏆 **TOP 10 ĐẠI GIA GIÀU NHẤT**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(users, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} ID: `{u[0]}` — `{u[1]:,}đ`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def history_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_total_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return
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

async def nhap_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập kèm mã. VD: `/code ABC123`")
        return
    today = get_vietnam_date()
    code_count = query("SELECT COUNT(*) FROM code_usage WHERE user_id=%s AND used_date=%s", (uid, today))
    if code_count and code_count[0][0] >= 3:
        await update.message.reply_text("❌ **GIỚI HẠN CODE HÔM NAY!**\n\nBạn chỉ có thể nhập tối đa **3 CODE/ngày**.\n⏰ Quay lại vào ngày mai để nhận thêm quà!", parse_mode="Markdown")
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
    query("INSERT INTO code_usage VALUES(%s, %s, %s)", (uid, code_str, today))
    add_money(uid, reward, f"Code: {code_str}")
    query("UPDATE codes SET uses=uses-1 WHERE code=%s", (code_str,))
    remaining = 3 - (code_count[0][0] + 1)
    await update.message.reply_text(f"🎉 **NHẬN QUÀ THÀNH CÔNG!**\n\n💰 Bạn nhận được: `+{reward:,}đ`\n📊 Hôm nay còn: `{remaining}/3` lượt nhập code.", parse_mode="Markdown")

async def give_money_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if len(ctx.args) < 2:
        return await update.message.reply_text("❌ Cú pháp: `/give [ID_Người_Nhận] [Số_Tiền]`")
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        if amount < 10000: return await update.message.reply_text("❌ Số tiền chuyển tối thiểu là 10.000đ")
        if sub_money(uid, amount, f"Chuyển tiền tới {target_id}"):
            add_money(target_id, amount, f"Nhận tiền từ {uid}")
            await update.message.reply_text(f"✅ Đã chuyển thành công `{amount:,}đ` tới ID `{target_id}`")
            try: await ctx.bot.send_message(target_id, f"🔔 Bạn nhận được `{amount:,}đ` từ ID `{uid}`")
            except: pass
        else:
            await update.message.reply_text("❌ Số dư của bạn không đủ.")
    except:
        await update.message.reply_text("❌ Lỗi định dạng dữ liệu.")

async def anon_msg_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if not ctx.args:
        await update.message.reply_text("✉️ **GỬI LỜI NHẮN ẨN DANH** ✉️\n━━━━━━━━━━━━━━━━━━━━━\n📝 **Cách dùng:** `/anon [nội dung]`\n\n💡 **Ví dụ:** `/anon Bot chạy tốt quá!`\n🔒 Tin nhắn của bạn sẽ được gửi ẩn danh đến Admin.", parse_mode="Markdown")
        return
    message = " ".join(ctx.args)
    sent_count = 0
    for admin_id in ADMIN_IDS:
        try:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Trả lời", callback_data=f"reply_anon_{uid}_{admin_id}"),
                InlineKeyboardButton("🚫 Chặn", callback_data=f"block_anon_{uid}")
            ]])
            await ctx.bot.send_message(admin_id, f"✉️ **LỜI NHẮN ẨN DANH** ✉️\n━━━━━━━━━━━━━━━━━━━━━\n💬 **Nội dung:**\n{message}\n━━━━━━━━━━━━━━━━━━━━━\n👤 **Người gửi:** Ẩn danh (ID: {uid})\n⏰ **Thời gian:** {get_vietnam_datetime_db()}", reply_markup=keyboard, parse_mode="Markdown")
            sent_count += 1
        except: pass
    if sent_count > 0:
        await update.message.reply_text(f"✅ **ĐÃ GỬI LỜI NHẮN ẨN DANH!**\n━━━━━━━━━━━━━━━━━━━━━\n📨 Tin nhắn của bạn đã được gửi đến Admin.\n🙏 Cảm ơn bạn đã đóng góp ý kiến!", parse_mode="Markdown")

# ===== KHO BÁU HÀNG NGÀY (ĐÃ SỬA LỖI STREAK) =====
async def khobau_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    today = get_vietnam_date()
    data = query("SELECT last_claim, streak FROM daily_treasure WHERE user_id=%s", (uid,))
    if data and data[0][0] == today:
        await update.message.reply_text(f"🎁 **KHO BÁU HÀNG NGÀY** 🎁\n━━━━━━━━━━━━━━━━━━━━━\n❌ Bạn đã nhận kho báu hôm nay rồi!\n🔥 Streak hiện tại: `{data[0][1]}` ngày\n\n⏰ Quay lại vào ngày mai để nhận tiếp!", parse_mode="Markdown")
        return
    rewards = [
        {"min": 1000, "max": 5000, "name": "💰 Tiền thưởng"},
        {"min": 5000, "max": 20000, "name": "🎁 Túi quà nhỏ"},
        {"min": 20000, "max": 50000, "name": "🎀 Rương đồng"},
        {"min": 50000, "max": 100000, "name": "💎 Rương bạc"},
        {"min": 100000, "max": 200000, "name": "👑 Rương vàng"}
    ]
    streak = 1
    if data:
        try:
            last_claim = datetime.strptime(data[0][0], "%d/%m/%Y")
            yesterday = get_vietnam_time() - timedelta(days=1)
            if last_claim.date() == yesterday.date():
                streak = min(data[0][1] + 1, 30)
            else:
                streak = 1
        except: streak = 1
    reward_index = min(streak // 5, len(rewards) - 1)
    reward = rewards[reward_index]
    amount = random.randint(reward["min"], reward["max"])
    add_money(uid, amount, f"Kho báu ngày {streak}")
    query("INSERT INTO daily_treasure (user_id, last_claim, streak, last_reward) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET last_claim=%s, streak=%s, last_reward=%s", (uid, today, streak, amount, today, streak, amount))
    special_effect = ""
    # SỬA: kiểm tra streak >= 30 TRƯỚC, sau đó mới >= 7
    if streak >= 30:
        special_effect = "\n👑 **STREAK 30 NGÀY!** Nhận thêm rương đặc biệt!"
        add_money(uid, 100000, f"Thưởng streak {streak} ngày")
        amount += 100000
    elif streak >= 7:
        special_effect = "\n🔥 **STREAK 7 NGÀY!** Nhân đôi phần thưởng!"
        add_money(uid, amount, f"Thưởng streak {streak} ngày")
        amount *= 2
    await update.message.reply_text(f"🎁 **KHO BÁU HÀNG NGÀY** 🎁\n━━━━━━━━━━━━━━━━━━━━━\n🔥 **Streak:** `{streak}` ngày\n📦 **Phần thưởng:** {reward['name']}\n💰 **Nhận được:** `+{amount:,}đ`{special_effect}\n💵 **Số dư:** `{get_balance(uid):,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n⏰ Quay lại ngày mai để nhận tiếp!", parse_mode="Markdown")

# ===== GROUP GAME COMMANDS =====
async def bet_tai_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM game!")
        return
    user_id = update.effective_user.id
    group_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    if is_banned(user_id):
        await update.message.reply_text("❌ Bạn đã bị khóa tài khoản!")
        return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập số tiền cược!\nCú pháp: `t [số_tiền]`", parse_mode="Markdown")
        return
    try:
        amount = int(ctx.args[0])
        if amount < 1000 or amount > 500000:
            await update.message.reply_text("❌ Số tiền cược từ `1,000đ` đến `500,000đ`!", parse_mode="Markdown")
            return
    except:
        await update.message.reply_text("❌ Số tiền không hợp lệ!", parse_mode="Markdown")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "tai", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def bet_xiu_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM game!")
        return
    user_id = update.effective_user.id
    group_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    if is_banned(user_id): return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập số tiền cược!\nCú pháp: `x [số_tiền]`", parse_mode="Markdown")
        return
    try:
        amount = int(ctx.args[0])
        if amount < 1000 or amount > 500000:
            await update.message.reply_text("❌ Số tiền cược từ `1,000đ` đến `500,000đ`!", parse_mode="Markdown")
            return
    except:
        await update.message.reply_text("❌ Số tiền không hợp lệ!", parse_mode="Markdown")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "xiu", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def bet_chan_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM game!")
        return
    user_id = update.effective_user.id
    group_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    if is_banned(user_id): return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập số tiền cược!\nCú pháp: `c [số_tiền]` (cửa CHẴN)", parse_mode="Markdown")
        return
    try:
        amount = int(ctx.args[0])
        if amount < 1000 or amount > 500000:
            await update.message.reply_text("❌ Số tiền cược từ `1,000đ` đến `500,000đ`!", parse_mode="Markdown")
            return
    except:
        await update.message.reply_text("❌ Số tiền không hợp lệ!", parse_mode="Markdown")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "chan", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def bet_le_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM game!")
        return
    user_id = update.effective_user.id
    group_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    if is_banned(user_id): return
    if not ctx.args:
        await update.message.reply_text("❌ Vui lòng nhập số tiền cược!\nCú pháp: `l [số_tiền]` (cửa LẺ)", parse_mode="Markdown")
        return
    try:
        amount = int(ctx.args[0])
        if amount < 1000 or amount > 500000:
            await update.message.reply_text("❌ Số tiền cược từ `1,000đ` đến `500,000đ`!", parse_mode="Markdown")
            return
    except:
        await update.message.reply_text("❌ Số tiền không hợp lệ!", parse_mode="Markdown")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "le", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def group_status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM!")
        return
    group_id = update.effective_chat.id
    status = get_group_game_status(group_id)
    if status == "betting":
        await update.message.reply_text("🎲 **ĐANG MỞ CƯỢC!**\nHãy đặt cược ngay: `t [tiền]` (TÀI), `x [tiền]` (XỈU), `c [tiền]` (CHẴN), `l [tiền]` (LẺ)", parse_mode="Markdown")
    elif status == "rolling":
        await update.message.reply_text("🎲 **ĐANG TUNG XÚC SẮC!**\nVui lòng chờ kết quả...", parse_mode="Markdown")
    else:
        await update.message.reply_text("⏸️ **CHƯA CÓ PHIÊN CƯỢC NÀO**\nVán mới sẽ bắt đầu sau vài giây...", parse_mode="Markdown")

# ===== ADMIN COMMANDS =====
@admin_only
async def dashboard_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = get_vietnam_date()
    this_month = get_vietnam_time().strftime("/%m/%Y")
    nap_today = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note ILIKE '%nạp%' AND time LIKE %s", (f"%{today}%",))[0][0] or 0
    rut_today = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note ILIKE '%Rút%' AND time LIKE %s", (f"%{today}%",))[0][0] or 0
    nap_month = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note ILIKE '%nạp%' AND time LIKE %s", (f"%{this_month}%",))[0][0] or 0
    rut_month = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note ILIKE '%Rút%' AND time LIKE %s", (f"%{this_month}%",))[0][0] or 0
    total_cuoc = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note NOT ILIKE '%Rút%' AND note NOT ILIKE '%trừ tiền%'")[0][0] or 0
    total_thang = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note NOT ILIKE '%nạp%' AND note NOT ILIKE '%Code%' AND note NOT ILIKE '%Checkin%'")[0][0] or 0
    loi_nhuan = abs(total_cuoc) - total_thang
    msg = (f"📊 **BẢNG THỐNG KÊ DOANH THU**\n━━━━━━━━━━━━━━━━━━━━━\n"
           f"📅 **Hôm nay ({today}):**\n  📥 Tổng nạp: `+{nap_today:,}đ`\n  📤 Tổng rút: `{rut_today:,}đ`\n\n"
           f"📅 **Tháng này ({get_vietnam_time().month}):**\n  📥 Tổng nạp: `+{nap_month:,}đ`\n  📤 Tổng rút: `{rut_month:,}đ`\n\n"
           f"📈 **Tổng kết Game (All time):**\n  💰 Lợi nhuận ròng: `{loi_nhuan:,}đ`\n━━━━━━━━━━━━━━━━━━━━━")
    await update.message.reply_text(msg, parse_mode="Markdown")

async def bao_hiem_vip(context: ContextTypes.DEFAULT_TYPE):
    yesterday = (get_vietnam_time() - timedelta(days=1)).strftime("%d/%m/%Y")
    users = query("SELECT user_id, SUM(amount) FROM history WHERE time LIKE %s GROUP BY user_id", (f"%{yesterday}%",))
    if not users: return
    for u_id, total in users:
        if total and total < -1000000:
            res = query("SELECT total_bet FROM users WHERE user_id=%s", (u_id,))
            total_bet = res[0][0] if res else 0
            vip_name, _ = get_vip_info(total_bet)
            if "VIP" in vip_name:
                percent = 2 if "VIP 1" in vip_name else 5
                hoan_tien = int(abs(total) * (percent / 100))
                add_money(u_id, hoan_tien, f"Bảo hiểm VIP {yesterday}")
                try:
                    await context.bot.send_message(u_id, f"🛡 **BẢO HIỂM VIP**\n\nHôm qua bạn đã chưa may mắn. Hệ thống hoàn lại `{percent}%` tiền thua cược: `+{hoan_tien:,}đ`.")
                except: pass

@admin_only
async def tong_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t_nap = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note ILIKE '%nạp%'")[0][0] or 0
    t_rut = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note ILIKE '%Rút%'")[0][0] or 0
    t_cuoc = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note NOT ILIKE '%Rút%' AND note NOT ILIKE '%trừ tiền%'")[0][0] or 0
    t_thang = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note NOT ILIKE '%nạp%' AND note NOT ILIKE '%Code%' AND note NOT ILIKE '%Checkin%'")[0][0] or 0
    loi_nhuan = abs(t_cuoc) - t_thang
    msg = (f"📈 **TỔNG QUAN TÀI CHÍNH HỆ THỐNG**\n━━━━━━━━━━━━━━━━━━━━━\n"
           f"📥 **Tổng Nạp:** `+{t_nap:,}đ`\n📤 **Tổng Rút:** `{t_rut:,}đ`\n💰 **Lợi Nhuận Thực Tế (Game):** `{loi_nhuan:,}đ`\n━━━━━━━━━━━━━━━━━━━━━")
    await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def cam_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2: return await update.message.reply_text("❌ Cú pháp: `/cam [id] [game_id/nap/rut]`")
    uid, target = int(ctx.args[0]), ctx.args[1]
    if target.isdigit():
        query("INSERT INTO banned_games VALUES(%s, %s) ON CONFLICT DO NOTHING", (uid, int(target)))
        await update.message.reply_text(f"🚫 Đã cấm ID `{uid}` chơi game ID `{target}`")
    elif target in ['nap', 'rut']:
        query("INSERT INTO banned_features VALUES(%s, %s) ON CONFLICT DO NOTHING", (uid, target))
        await update.message.reply_text(f"🚫 Đã cấm ID `{uid}` sử dụng tính năng `{target}`")

@admin_only
async def bocam_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2: return await update.message.reply_text("❌ Cú pháp: `/bocam [id] [game_id/nap/rut]`")
    uid, target = int(ctx.args[0]), ctx.args[1]
    if target.isdigit():
        query("DELETE FROM banned_games WHERE user_id=%s AND game_id=%s", (uid, int(target)))
        await update.message.reply_text(f"✅ Đã gỡ cấm game ID `{target}` cho ID `{uid}`")
    elif target in ['nap', 'rut']:
        query("DELETE FROM banned_features WHERE user_id=%s AND feature=%s", (uid, target))
        await update.message.reply_text(f"✅ Đã gỡ cấm tính năng `{target}` cho ID `{uid}`")

@admin_only
async def set_bot_name_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/setname [Tên mới]`")
    new_name = " ".join(ctx.args)
    query("UPDATE settings SET value=%s WHERE key='bot_display_name'", (new_name,))
    await update.message.reply_text(f"✅ Đã đổi tên hiển thị của Bot thành: **{new_name}**", parse_mode="Markdown")

@admin_only
async def resetsdall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query("UPDATE users SET balance = 0")
    await update.message.reply_text("✅ Đã xóa toàn bộ số dư của tất cả người dùng về 0!")

@admin_only
async def tileall_set_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/tileall [số]`")
    try:
        new_rate = int(ctx.args[0])
        query("UPDATE game_rates SET rate = %s", (new_rate,))
        await update.message.reply_text(f"✅ Đã chỉnh tất cả game về tỉ lệ thắng: `{new_rate}%`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Tỉ lệ phải là số nguyên.")

@admin_only
async def tile1_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2: return await update.message.reply_text("❌ Cú pháp: `/tile1 [ID] [Tỉ_lệ]`")
    try:
        uid = int(ctx.args[0])
        rate = int(ctx.args[1])
        query("UPDATE users SET rate_bonus = %s WHERE user_id = %s", (rate, uid))
        await update.message.reply_text(f"✅ Đã áp dụng tỉ lệ thắng `{rate}%` riêng cho người dùng `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Lỗi dữ liệu nhập vào.")

@admin_only
async def soduall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC")
    if not users: return await update.message.reply_text("Hiện không có ai có số dư lớn hơn 0.")
    text = "💰 **DANH SÁCH SỐ DƯ TẤT CẢ ID:**\n"
    for u in users:
        text += f"ID: `{u[0]}` | Số dư: `{u[1]:,}đ`\n"
    if len(text) > 4000:
        for x in range(0, len(text), 4000):
            await update.message.reply_text(text[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

@admin_only
async def tileall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rates = query("SELECT id, name, rate FROM game_rates ORDER BY id ASC")
    text = "📊 **TỈ LỆ THẮNG TẤT CẢ GAME:**\n\n"
    for r in rates:
        text += f"🆔 `{r[0]}` | {r[1]}: `{r[2]}%` thắng\n"
    await update.message.reply_text(text, parse_mode="Markdown")

@admin_only
async def xoalsall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query("DELETE FROM history")
    await update.message.reply_text("✅ Đã xoá toàn bộ lịch sử cược, nạp và rút của hệ thống!")

@admin_only
async def xoals_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/xoals [ID]`")
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM history WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"✅ Đã xoá sạch lịch sử của người dùng: `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ ID không hợp lệ.")

async def cam_admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != 8619503816:
        await update.message.reply_text("❌ Chỉ Admin chính mới có quyền sử dụng lệnh này!")
        return
    if len(ctx.args) < 1:
        await update.message.reply_text("❌ Cú pháp: `/camadmin [ID_admin] [lý do]`", parse_mode="Markdown")
        return
    try:
        target_admin = int(ctx.args[0])
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "Không có lý do"
        if target_admin == user_id: await update.message.reply_text("❌ Bạn không thể tự cấm chính mình!"); return
        if target_admin not in ADMIN_IDS: await update.message.reply_text(f"❌ ID `{target_admin}` không phải là Admin!", parse_mode="Markdown"); return
        now_str = get_vietnam_datetime_db()
        query("INSERT INTO banned_admins VALUES(%s, %s, %s, %s) ON CONFLICT (admin_id) DO UPDATE SET banned_by=%s, reason=%s, banned_at=%s", (target_admin, user_id, reason, now_str, user_id, reason, now_str))
        await update.message.reply_text(f"✅ **ĐÃ CẤM ADMIN**\n\n👤 ID: `{target_admin}`\n📝 Lý do: {reason}\n⏰ Thời gian: {now_str}", parse_mode="Markdown")
        try: await ctx.bot.send_message(target_admin, f"⚠️ Bạn đã bị cấm sử dụng các lệnh Admin.\n📝 Lý do: {reason}")
        except: pass
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def unban_admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != 8619503816: await update.message.reply_text("❌ Chỉ Admin chính mới có quyền!"); return
    if len(ctx.args) < 1: await update.message.reply_text("❌ Cú pháp: `/unbanadmin [ID_admin]`", parse_mode="Markdown"); return
    try:
        target_admin = int(ctx.args[0])
        query("DELETE FROM banned_admins WHERE admin_id=%s", (target_admin,))
        await update.message.reply_text(f"✅ Đã gỡ cấm cho Admin `{target_admin}`", parse_mode="Markdown")
        try: await ctx.bot.send_message(target_admin, "✅ Bạn đã được gỡ cấm và có thể sử dụng lại các lệnh Admin!")
        except: pass
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def camadmin1_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != 8619503816: await update.message.reply_text("❌ Chỉ Admin chính mới có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ Cú pháp: `/camadmin1 [ID_admin] [tên_lệnh]`", parse_mode="Markdown"); return
    try:
        target_admin = int(ctx.args[0])
        banned_command = ctx.args[1].lower()
        now_str = get_vietnam_datetime_db()
        reason = " ".join(ctx.args[2:]) if len(ctx.args) > 2 else "Không có lý do"
        query("INSERT INTO banned_admin_commands VALUES(%s, %s, %s, %s, %s) ON CONFLICT (admin_id, command) DO NOTHING", (target_admin, banned_command, user_id, reason, now_str))
        await update.message.reply_text(f"✅ Đã cấm Admin `{target_admin}` dùng lệnh `/{banned_command}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def uncamadmin1_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != 8619503816: await update.message.reply_text("❌ Chỉ Admin chính mới có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ Cú pháp: `/uncamadmin1 [ID_admin] [tên_lệnh]`", parse_mode="Markdown"); return
    try:
        target_admin = int(ctx.args[0])
        banned_command = ctx.args[1].lower()
        query("DELETE FROM banned_admin_commands WHERE admin_id=%s AND command=%s", (target_admin, banned_command))
        await update.message.reply_text(f"✅ Đã gỡ cấm lệnh `/{banned_command}` cho Admin `{target_admin}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def baotri_hethong_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 1:
        current_status = "🔴 ĐANG BẢO TRÌ" if is_system_maintenance() else "🟢 HOẠT ĐỘNG"
        await update.message.reply_text(f"🛠 **TRẠNG THÁI HỆ THỐNG**\n\n📊 Hiện tại: {current_status}\n\n📝 Cú pháp:\n• Bật bảo trì: `/baotriall on`\n• Tắt bảo trì: `/baotriall off`", parse_mode="Markdown")
        return
    action = ctx.args[0].lower()
    if action == "on":
        query("UPDATE settings SET value='1' WHERE key='system_maintenance'")
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(user[0], "🔧 **THÔNG BÁO BẢO TRÌ**\n\nHệ thống đang được nâng cấp và bảo trì.\n⏰ Vui lòng quay lại sau ít phút!", parse_mode="Markdown")
                sent_count += 1
                await asyncio.sleep(0.5)
            except: pass
        await update.message.reply_text(f"🔧 **ĐÃ BẬT BẢO TRÌ TOÀN HỆ THỐNG**\n\n✅ Đã gửi thông báo đến {sent_count} người dùng.", parse_mode="Markdown")
    elif action == "off":
        query("UPDATE settings SET value='0' WHERE key='system_maintenance'")
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(user[0], "✅ **HỆ THỐNG Đã TRỞ LẠI**\n\nQuá trình bảo trì đã hoàn tất!\n🎮 Chúc bạn chơi game vui vẻ!", parse_mode="Markdown")
                sent_count += 1
                await asyncio.sleep(0.5)
            except: pass
        await update.message.reply_text(f"✅ **ĐÃ TẮT BẢO TRÌ TOÀN HỆ THỐNG**\n\n✅ Đã gửi thông báo đến {sent_count} người dùng.", parse_mode="Markdown")

async def tatroom_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": await update.message.reply_text("❌ Lệnh này chỉ sử dụng được trong NHÓM!"); return
    if len(ctx.args) < 1:
        current_status = "🔴 ĐÃ TẮT" if not room_betting_enabled.get(chat_id, True) else "🟢 ĐANG BẬT"
        await update.message.reply_text(f"🎮 **TRẠNG THÁI CƯỢC TRONG NHÓM**\n\n📊 Hiện tại: {current_status}\n\n📝 Cú pháp:\n• Tắt cược: `/tatroom off`\n• Bật cược: `/tatroom on`", parse_mode="Markdown")
        return
    action = ctx.args[0].lower()
    if action == "off":
        room_betting_enabled[chat_id] = False
        await update.message.reply_text(f"🔴 **ĐÃ TẮT CƯỢC TRONG NHÓM!**\n\n📝 Để bật lại, dùng: `/tatroom on`", parse_mode="Markdown")
    elif action == "on":
        room_betting_enabled[chat_id] = True
        await update.message.reply_text(f"🟢 **ĐÃ BẬT CƯỢC TRONG NHÓM!**\n\n✅ Người dùng có thể đặt cược bình thường.", parse_mode="Markdown")

async def quanlyadmin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    all_admins = ADMIN_IDS.copy()
    banned_admins = query("SELECT admin_id FROM banned_admins")
    banned_ids = [b[0] for b in banned_admins] if banned_admins else []
    kb = [[InlineKeyboardButton("👤 DANH SÁCH ADMIN", callback_data="admin_list_header")]]
    for admin_id in all_admins:
        status = "🚫" if admin_id in banned_ids else "✅"
        btn_text = f"{'👑 ' if admin_id == 8619503816 else ''}{status} ADMIN {admin_id}"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"admin_detail_{admin_id}")])
    kb.append([InlineKeyboardButton("❌ ĐÓNG", callback_data="close_admin")])
    await update.message.reply_text("👑 **BẢNG QUẢN LÝ ADMIN**\n━━━━━━━━━━━━━━━━━━━━━\n🟢 ✅ = Hoạt động | 🔴 🚫 = Bị cấm\n👑 = Admin chính\n━━━━━━━━━━━━━━━━━━━━━\n👇 Bấm vào Admin để quản lý:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def lsnap_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 1: await update.message.reply_text("❌ Cú pháp: `/lsnap [ID]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        data = query("SELECT amount, admin_id, time FROM deposit_history WHERE user_id=%s AND status='success' ORDER BY time DESC LIMIT 20", (target_id,))
        if not data: await update.message.reply_text(f"📋 ID `{target_id}` chưa có lịch sử nạp nào!", parse_mode="Markdown"); return
        msg = f"📥 **LỊCH SỬ NẠP CỦA ID `{target_id}`**\n━━━━━━━━━━━━━━━━━━━━━\n"
        for row in data:
            msg += f"✅ `+{row[0]:,}đ` | Admin: `{row[1]}`\n   ⏰ _{row[2]}_\n━━━━━━━━━━━━━━━━━━━━━\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def lsrut_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 1: await update.message.reply_text("❌ Cú pháp: `/lsrut [ID]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        data = query("SELECT amount, status, admin_id, time FROM withdraw_history WHERE user_id=%s ORDER BY time DESC LIMIT 20", (target_id,))
        if not data: await update.message.reply_text(f"📋 ID `{target_id}` chưa có lịch sử rút nào!", parse_mode="Markdown"); return
        msg = f"📤 **LỊCH SỬ RÚT CỦA ID `{target_id}`**\n━━━━━━━━━━━━━━━━━━━━━\n"
        for row in data:
            status_icon = "✅" if row[1] == "success" else "❌" if row[1] == "rejected" else "⏳"
            status_text = "Thành công" if row[1] == "success" else "Bị từ chối" if row[1] == "rejected" else "Chờ duyệt"
            msg += f"{status_icon} `{row[0]:,}đ` | {status_text}\n"
            if row[2]: msg += f"   👮 Admin: `{row[2]}`\n"
            msg += f"   ⏰ _{row[3]}_\n━━━━━━━━━━━━━━━━━━━━━\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

@admin_only
async def lsnapall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    limit = 20
    if ctx.args and ctx.args[0].isdigit(): limit = min(int(ctx.args[0]), 100)
    data = query("SELECT id, user_id, amount, admin_id, time FROM deposit_history WHERE status='success' ORDER BY time DESC LIMIT %s", (limit,))
    if not data: await update.message.reply_text("📋 Chưa có lịch sử nạp nào!", parse_mode="Markdown"); return
    total_amount = query("SELECT COALESCE(SUM(amount), 0) FROM deposit_history WHERE status='success'")[0][0] or 0
    msg = f"📥 **TẤT CẢ LỊCH SỬ NẠP**\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Tổng nạp:** `{total_amount:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for row in data:
        msg += f"🆔 #{row[0]} | 👤 ID `{row[1]}` | ✅ `+{row[2]:,}đ` | 👮 Admin `{row[3]}`\n   ⏰ _{row[4]}_\n━━━━━━━━━━━━━━━━━━━━━\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000): await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def lsrutall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    limit = 20
    if ctx.args and ctx.args[0].isdigit(): limit = min(int(ctx.args[0]), 100)
    data = query("SELECT id, user_id, amount, status, admin_id, time, admin_note FROM withdraw_history ORDER BY time DESC LIMIT %s", (limit,))
    if not data: await update.message.reply_text("📋 Chưa có lịch sử rút nào!", parse_mode="Markdown"); return
    total_success = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='success'")[0][0] or 0
    total_pending = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='pending'")[0][0] or 0
    total_rejected = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='rejected'")[0][0] or 0
    msg = f"📤 **TẤT CẢ LỊCH SỬ RÚT**\n━━━━━━━━━━━━━━━━━━━━━\n✅ **Thành công:** `{total_success:,}đ`\n⏳ **Chờ duyệt:** `{total_pending:,}đ`\n❌ **Từ chối:** `{total_rejected:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for row in data:
        status_icon = "✅" if row[3] == "success" else "❌" if row[3] == "rejected" else "⏳"
        status_text = "Thành công" if row[3] == "success" else "Bị từ chối" if row[3] == "rejected" else "Chờ duyệt"
        msg += f"🆔 #{row[0]} | 👤 ID `{row[1]}` | {status_icon} `{row[2]:,}đ` | {status_text}\n"
        if row[4]: msg += f"   👮 Admin: `{row[4]}`\n"
        if row[6]: msg += f"   📝 Ghi chú: {row[6]}\n"
        msg += f"   ⏰ _{row[5]}_\n━━━━━━━━━━━━━━━━━━━━━\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000): await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def thongke_nap_rut_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    filter_type = ctx.args[0].lower() if ctx.args else "today"
    now = get_vietnam_time()
    today_str = now.strftime("%d/%m/%Y")
    this_month_str = now.strftime("/%m/%Y")
    this_year_str = now.strftime("/%Y")
    if filter_type in ("today", "ngay"):
        nap_data = query("SELECT COALESCE(SUM(amount), 0) FROM deposit_history WHERE status='success' AND time LIKE %s", (f"%{today_str}%",))
        rut_data = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='success' AND time LIKE %s", (f"%{today_str}%",))
        title = f"📅 HÔM NAY ({today_str})"
    elif filter_type in ("month", "tháng"):
        nap_data = query("SELECT COALESCE(SUM(amount), 0) FROM deposit_history WHERE status='success' AND time LIKE %s", (f"%{this_month_str}%",))
        rut_data = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='success' AND time LIKE %s", (f"%{this_month_str}%",))
        title = f"📅 THÁNG {now.month}/{now.year}"
    else:
        nap_data = query("SELECT COALESCE(SUM(amount), 0) FROM deposit_history WHERE status='success'")
        rut_data = query("SELECT COALESCE(SUM(amount), 0) FROM withdraw_history WHERE status='success'")
        title = "📊 TOÀN THỜI GIAN"
    total_nap = nap_data[0][0] if nap_data else 0
    total_rut = rut_data[0][0] if rut_data else 0
    loi_nhuan = total_nap - total_rut
    msg = f"💰 **THỐNG KÊ NẠP - RÚT** 💰\n━━━━━━━━━━━━━━━━━━━━━\n📌 **{title}**\n━━━━━━━━━━━━━━━━━━━━━\n📥 **TỔNG NẠP:** `{total_nap:,}đ`\n📤 **TỔNG RÚT:** `{total_rut:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n{'📈' if loi_nhuan >= 0 else '📉'} **LỢI NHUẬN RÒNG:** `{loi_nhuan:,}đ`\n━━━━━━━━━━━━━━━━━━━━━\n📅 {now.strftime('%H:%M:%S - %d/%m/%Y')}"
    await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def baotri_tong_cong_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != 8619503816: await update.message.reply_text("❌ Chỉ Admin chính mới có quyền!"); return
    if len(ctx.args) < 1:
        current_status = "🔴 ĐANG BẢO TRÌ TOÀN BỘ" if is_total_maintenance() else "🟢 HOẠT ĐỘNG BÌNH THƯỜNG"
        await update.message.reply_text(f"🛠 **BẢO TRÌ TOÀN BỘ HỆ THỐNG** 🛠\n━━━━━━━━━━━━━━━━━━━━━\n📊 **Trạng thái hiện tại:** {current_status}\n\n📝 **Cú pháp:**\n• Bật bảo trì: `/baotritc on`\n• Tắt bảo trì: `/baotritc off`", parse_mode="Markdown")
        return
    action = ctx.args[0].lower()
    if action == "on":
        query("UPDATE settings SET value='1' WHERE key='mt_tongbao'")
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(user[0], "🔧 **THÔNG BÁO BẢO TRÌ TOÀN BỘ** 🔧\n━━━━━━━━━━━━━━━━━━━━━\n🚨 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ!**\n\n❌ Tất cả các tính năng đều tạm thời ngừng hoạt động.\n⏰ Vui lòng quay lại sau!", parse_mode="Markdown")
                sent_count += 1
                await asyncio.sleep(0.3)
            except: pass
        await update.message.reply_text(f"🔧 **ĐÃ BẬT BẢO TRÌ TOÀN BỘ**\n✅ Đã gửi thông báo đến `{sent_count}` người dùng", parse_mode="Markdown")
    elif action == "off":
        query("UPDATE settings SET value='0' WHERE key='mt_tongbao'")
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(user[0], "✅ **HỆ THỐNG ĐÃ TRỞ LẠI!** ✅\n━━━━━━━━━━━━━━━━━━━━━\n🎉 **Bảo trì hoàn tất!**\n\n🟢 Tất cả tính năng đã hoạt động trở lại.\n🎮 Chúc bạn chơi game vui vẻ!", parse_mode="Markdown")
                sent_count += 1
                await asyncio.sleep(0.3)
            except: pass
        await update.message.reply_text(f"✅ **ĐÃ TẮT BẢO TRÌ TOÀN BỘ**\n✅ Đã gửi thông báo đến `{sent_count}` người dùng", parse_mode="Markdown")

async def tile1all_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/tile1all [id] [tỉ_lệ]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        rate = int(ctx.args[1])
        if rate < 0 or rate > 100: await update.message.reply_text("❌ Tỉ lệ thắng phải từ 0% đến 100%!", parse_mode="Markdown"); return
        query("UPDATE users SET rate_bonus = %s WHERE user_id = %s", (rate, target_id))
        await update.message.reply_text(f"✅ **CẬP NHẬT TỈ LỆ THẮNG THÀNH CÔNG!**\n\n👤 **ID:** `{target_id}`\n📊 **Tỉ lệ thắng mới:** `{rate}%`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID hoặc tỉ lệ không hợp lệ!")

async def taocodeall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/taocodeall [số_tiền] [số_lượng]`", parse_mode="Markdown"); return
    try:
        reward = int(ctx.args[0])
        quantity = int(ctx.args[1])
        if quantity < 1 or quantity > 100: await update.message.reply_text("❌ Số lượng code phải từ 1 đến 100!", parse_mode="Markdown"); return
        if reward < 1000: await update.message.reply_text("❌ Số tiền thưởng tối thiểu là 1,000đ!", parse_mode="Markdown"); return
        codes = []
        for i in range(quantity):
            code = gen_code()
            query("INSERT INTO codes (code, reward, uses) VALUES(%s, %s, %s)", (code, reward, 1))
            codes.append(code)
        msg = f"🎫 **TẠO {quantity} CODE THÀNH CÔNG!**\n━━━━━━━━━━━━━━━━━━━━━\n💰 Mỗi code: `{reward:,}đ`\n\n"
        for i, code in enumerate(codes, 1): msg += f"{i}. `{code}`\n"
        msg += "\n📌 Dùng lệnh `/code [mã]` để nhận thưởng!"
        if len(msg) > 4000:
            buf = BytesIO("\n".join(codes).encode())
            await update.message.reply_document(document=buf, filename="codes.txt", caption=f"🎫 {quantity} code mỗi code {reward:,}đ")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Số tiền hoặc số lượng không hợp lệ!")

async def xoacode_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 1: await update.message.reply_text("❌ **Cú pháp:** `/xoacode [mã_code]`", parse_mode="Markdown"); return
    code_str = ctx.args[0].strip().upper()
    data = query("SELECT reward, uses FROM codes WHERE code=%s", (code_str,))
    if not data: await update.message.reply_text(f"❌ Code `{code_str}` không tồn tại!", parse_mode="Markdown"); return
    reward, uses = data[0]
    query("DELETE FROM codes WHERE code=%s", (code_str,))
    await update.message.reply_text(f"✅ **ĐÃ XÓA CODE THÀNH CÔNG!**\n\n🎫 **Mã:** `{code_str}`\n💰 **Giá trị:** `{reward:,}đ`\n🔄 **Lượt dùng còn lại:** `{uses}`", parse_mode="Markdown")

async def set_xoso_result_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/setxoso [id] [kết_quả_2_số]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        forced_result = ctx.args[1].zfill(2)
        if not forced_result.isdigit() or int(forced_result) < 0 or int(forced_result) > 99: await update.message.reply_text("❌ Kết quả phải là số từ 00 đến 99!", parse_mode="Markdown"); return
        if not hasattr(ctx.bot, 'forced_xoso_results'): ctx.bot.forced_xoso_results = {}
        ctx.bot.forced_xoso_results[target_id] = forced_result
        await update.message.reply_text(f"✅ Đã chỉnh kết quả xổ số cho ID `{target_id}`: `{forced_result}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def set_vongquay_result_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/setvongquay [id] [tiền_thưởng]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        forced_prize = int(ctx.args[1])
        if not hasattr(ctx.bot, 'forced_vongquay_results'): ctx.bot.forced_vongquay_results = {}
        ctx.bot.forced_vongquay_results[target_id] = forced_prize
        await update.message.reply_text(f"✅ Đã chỉnh kết quả vòng quay cho ID `{target_id}`: `{forced_prize:,}đ`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID hoặc số tiền không hợp lệ!")

@admin_only
async def top_thang_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = query("SELECT user_id, SUM(amount) as total_win FROM history WHERE amount > 0 AND note NOT ILIKE '%nạp%' AND note NOT ILIKE '%Code%' AND note NOT ILIKE '%Checkin%' GROUP BY user_id ORDER BY total_win DESC LIMIT 10")
    if not data: await update.message.reply_text("📊 Chưa có dữ liệu thắng cược!"); return
    msg = "🏆 **TOP 10 NGƯỜI THẮNG NHIỀU NHẤT** 🏆\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (uid, total) in enumerate(data, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{medal} ID `{uid}` — `+{total:,}đ`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def gift_all_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 1: await update.message.reply_text("❌ **Cú pháp:** `/giftall [số_tiền] [lý_do]`", parse_mode="Markdown"); return
    try:
        amount = int(ctx.args[0])
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "Quà tặng từ Admin"
        if amount < 1000: await update.message.reply_text("❌ Số tiền tặng tối thiểu là 1,000đ!"); return
        users = query("SELECT user_id FROM users")
        total_users = len(users) if users else 0
        if total_users == 0: await update.message.reply_text("❌ Không có người dùng nào để tặng!"); return
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ XÁC NHẬN", callback_data=f"confirm_giftall_{amount}_{total_users}"),
            InlineKeyboardButton("❌ HỦY", callback_data="close_admin")
        ]])
        await update.message.reply_text(f"🎁 **XÁC NHẬN TẶNG QUÀ** 🎁\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Số tiền:** `{amount:,}đ/người`\n👥 **Số người:** `{total_users}`\n💵 **Tổng chi:** `{amount * total_users:,}đ`\n📝 **Lý do:** {reason}\n━━━━━━━━━━━━━━━━━━━━━\n⚠️ Bạn có chắc chắn?", reply_markup=confirm_kb, parse_mode="Markdown")
        ctx.user_data["giftall_reason"] = reason
    except ValueError:
        await update.message.reply_text("❌ Số tiền không hợp lệ!")

@admin_only
async def lock_game_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 3: await update.message.reply_text("❌ **Cú pháp:** `/lockgame [id] [game_id] [lock/unlock]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        game_id = int(ctx.args[1])
        action = ctx.args[2].lower()
        if action == "lock":
            query("INSERT INTO banned_games VALUES(%s, %s) ON CONFLICT DO NOTHING", (target_id, game_id))
            await update.message.reply_text(f"🔒 Đã khóa game ID `{game_id}` cho ID `{target_id}`", parse_mode="Markdown")
        elif action == "unlock":
            query("DELETE FROM banned_games WHERE user_id=%s AND game_id=%s", (target_id, game_id))
            await update.message.reply_text(f"🔓 Đã mở khóa game ID `{game_id}` cho ID `{target_id}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID hoặc game_id không hợp lệ!")

@admin_only
async def bonus_vip_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, total_bet FROM users")
    if not users: await update.message.reply_text("❌ Không có người dùng nào!"); return
    total_bonus = 0
    vip_count = 0
    for uid, total_bet in users:
        vip_name, bonus = get_vip_info(total_bet or 0)
        if "VIP" in vip_name:
            total_bonus += bonus
            vip_count += 1
    confirm_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ XÁC NHẬN", callback_data="confirm_bonus_vip"),
        InlineKeyboardButton("❌ HỦY", callback_data="close_admin")
    ]])
    await update.message.reply_text(f"👑 **THƯỞNG VIP HÀNG THÁNG** 👑\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Tổng thưởng:** `{total_bonus:,}đ`\n👥 **Số người được thưởng:** `{vip_count}`\n━━━━━━━━━━━━━━━━━━━━━\n⚠️ Bạn có chắc chắn muốn thưởng VIP cho tất cả?", reply_markup=confirm_kb, parse_mode="Markdown")

@admin_only
async def export_db_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, balance, total_bet, refs FROM users ORDER BY balance DESC")
    if not users: await update.message.reply_text("❌ Không có dữ liệu để xuất!"); return
    output = BytesIO()
    output.write(u'\ufeff'.encode('utf-8'))
    writer = csv.writer(output, delimiter=',')
    writer.writerow(['User ID', 'Số dư (VNĐ)', 'Tổng cược (VNĐ)', 'Số người mời'])
    for user in users:
        writer.writerow([user[0], f"{user[1]:,}", f"{user[2]:,}", user[3]])
    output.seek(0)
    await update.message.reply_document(document=output, filename=f"users_export_{get_vietnam_time().strftime('%Y%m%d_%H%M%S')}.csv", caption=f"📊 **DỮ LIỆU NGƯỜI DÙNG**\n📅 Ngày xuất: {get_vietnam_datetime_db()}\n👥 Tổng số user: {len(users)}", parse_mode="Markdown")

@admin_only
async def chinhkq_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rates = query("SELECT id, name, rate FROM game_rates ORDER BY id ASC")
    kb = []
    for game_id, name, rate in rates:
        short_name = name[:15] + ".." if len(name) > 15 else name
        kb.append([InlineKeyboardButton(f"🎮 {short_name} | {rate}%", callback_data=f"rate_show_{game_id}")])
        kb.append([InlineKeyboardButton(f"🔻 -10%", callback_data=f"rate_dec_{game_id}"), InlineKeyboardButton(f"🔺 +10%", callback_data=f"rate_inc_{game_id}")])
    kb.append([InlineKeyboardButton("❌ ĐÓNG", callback_data="close_admin")])
    msg = "📊 **BẢNG CHỈNH TỈ LỆ THẮNG GAME** 📊\n━━━━━━━━━━━━━━━━━━━━━\n"
    for game_id, name, rate in rates:
        msg += f"🆔 `{game_id}` | {name}: **{rate}%**\n"
    msg += "\n👇 **Bấm +10% hoặc -10% để điều chỉnh**"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

@admin_only
async def daban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    banned_users = query("SELECT user_id FROM banned") or []
    banned_games = query("SELECT bg.user_id, u.balance, gr.name, bg.game_id FROM banned_games bg LEFT JOIN game_rates gr ON bg.game_id = gr.id LEFT JOIN users u ON bg.user_id = u.user_id ORDER BY bg.user_id") or []
    banned_features = query("SELECT user_id, feature FROM banned_features ORDER BY user_id") or []
    banned_admins = query("SELECT admin_id, reason, banned_at FROM banned_admins ORDER BY banned_at DESC") or []
    banned_admin_commands = query("SELECT admin_id, command, reason FROM banned_admin_commands ORDER BY admin_id") or []
    msg = f"🚫 **DANH SÁCH BỊ CẤM** 🚫\n━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"👤 Người dùng bị cấm: {len(banned_users)}\n🎮 Lệnh cấm game: {len(banned_games)}\n⚙️ Lệnh cấm tính năng: {len(banned_features)}\n👑 Admin bị cấm: {len(banned_admins)}\n🔧 Admin bị cấm lệnh: {len(banned_admin_commands)}\n━━━━━━━━━━━━━━━━━━━━━\n"
    for uid in banned_users[:10]: msg += f"🔴 User ID: `{uid[0]}`\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 XUẤT CSV", callback_data="export_ban_list"), InlineKeyboardButton("❌ ĐÓNG", callback_data="close_admin")]])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

@admin_only
async def mofull_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    banned_users_count = len(query("SELECT user_id FROM banned") or [])
    banned_games_count = len(query("SELECT 1 FROM banned_games") or [])
    banned_features_count = len(query("SELECT 1 FROM banned_features") or [])
    banned_admins_count = len(query("SELECT 1 FROM banned_admins") or [])
    banned_admin_cmds_count = len(query("SELECT 1 FROM banned_admin_commands") or [])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ XÁC NHẬN MỞ TẤT CẢ", callback_data="confirm_mofull"), InlineKeyboardButton("❌ HỦY", callback_data="close_admin")]])
    msg = f"⚠️ **CẢNH BÁO: MỞ TẤT CẢ NGƯỜI BỊ CẤM** ⚠️\n━━━━━━━━━━━━━━━━━━━━━\n📊 **SẼ XÓA:**\n  • Người dùng bị cấm: `{banned_users_count}`\n  • Lệnh cấm game: `{banned_games_count}`\n  • Lệnh cấm tính năng: `{banned_features_count}`\n  • Admin bị cấm: `{banned_admins_count}`\n  • Admin bị cấm lệnh: `{banned_admin_cmds_count}`\n\n⚠️ **HÀNH ĐỘNG NÀY KHÔNG THỂ HOÀN TÁC!**"
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

@admin_only
async def check_bank_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, bank, stk, name FROM users WHERE bank_linked=0 OR bank_linked IS NULL")
    if not users: await update.message.reply_text("✅ Tất cả người dùng đã liên kết ngân hàng!", parse_mode="Markdown"); return
    msg = "🏦 **DANH SÁCH CHƯA LIÊN KẾT NGÂN HÀNG** 🏦\n━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, bank, stk, name in users:
        msg += f"👤 ID: `{uid}`\n"
        if bank: msg += f"   📝 Đã nhập: {bank} - {stk} - {name}\n"
        else: msg += f"   ❌ Chưa nhập thông tin\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000): await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def check_top_interaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    gid = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not gid: await update.message.reply_text("❌ Lệnh này chỉ dùng trong nhóm!"); return
    top = query("SELECT user_id, interaction_count, last_interaction FROM group_interactions WHERE group_id=%s ORDER BY interaction_count DESC LIMIT 10", (gid,))
    if not top: await update.message.reply_text("📊 Chưa có dữ liệu tương tác trong nhóm!", parse_mode="Markdown"); return
    msg = "🔥 **TOP TƯƠNG TÁC NHÓM** 🔥\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (uid, count, last) in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{medal} ID `{uid}` — `{count}` lượt\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n🎯 **MỐC THƯỞNG:** 200 lượt → Liên hệ Admin nhận quà!"
    await update.message.reply_text(msg, parse_mode="Markdown")

@admin_only
async def chart_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    labels = []
    nap_values = []
    rut_values = []
    for i in range(6, -1, -1):
        date = (get_vietnam_time() - timedelta(days=i)).strftime("%d/%m")
        day_str = (get_vietnam_time() - timedelta(days=i)).strftime("%d/%m/%Y")
        labels.append(date)
        nap = query("SELECT COALESCE(SUM(amount), 0) FROM history WHERE amount > 0 AND note ILIKE '%nạp%' AND time LIKE %s", (f"%{day_str}%",))[0][0] or 0
        rut = query("SELECT COALESCE(SUM(amount), 0) FROM history WHERE amount < 0 AND note ILIKE '%Rút%' AND time LIKE %s", (f"%{day_str}%",))[0][0] or 0
        nap_values.append(nap)
        rut_values.append(abs(rut))
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(labels))
    width = 0.35
    ax.bar([i - width/2 for i in x], nap_values, width, label='Nạp tiền', color='green', alpha=0.7)
    ax.bar([i + width/2 for i in x], rut_values, width, label='Rút tiền', color='red', alpha=0.7)
    ax.set_xlabel('Ngày')
    ax.set_ylabel('Số tiền (VNĐ)')
    ax.set_title(f'Thống kê doanh thu {get_bot_name()}')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    def format_y(val, p):
        if val >= 1_000_000: return f'{val/1_000_000:.1f}M'
        elif val >= 1_000: return f'{val/1_000:.0f}K'
        return f'{int(val):,}'
    ax.yaxis.set_major_formatter(plt.FuncFormatter(format_y))
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    await update.message.reply_photo(photo=buf, caption=f"📊 **BIỂU ĐỒ DOANH THU 7 NGÀY**\n━━━━━━━━━━━━━━━━━━━━━\n📅 Từ {labels[0]} đến {labels[-1]}", parse_mode="Markdown")

@admin_only
async def tilewin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        game_id = int(ctx.args[0])
        new_rate = int(ctx.args[1])
        if not (0 <= new_rate <= 100): return await update.message.reply_text("❌ Tỉ lệ thắng phải từ 0% đến 100%!")
        query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
        res = query("SELECT name FROM game_rates WHERE id=%s", (game_id,))
        game_name = res[0][0] if res else "Không xác định"
        await update.message.reply_text(f"✅ **CẬP NHẬT TỈ LỆ THÀNH CÔNG**\n\n🎮 Game: `{game_id} - {game_name}`\n📈 Tỉ lệ thắng mới: `{new_rate}%`", parse_mode="Markdown")
    except:
        await update.message.reply_text("⚠️ Cú pháp: `/tilewin [Số_ID] [Tỉ_lệ]`\n\n1.TX | 2.XĐ | 3.ĐX | 4.DM | 5.Pen | 6.GM | 7.QS | 8.BC | 9.XS | 10.VQ | 11.CT | 12.RG | 13.TM", parse_mode="Markdown")

@admin_only
async def baotri_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    def st(k): return "🔴 OFF" if check_mt(k) else "🟢 ON"
    kb = [
        [InlineKeyboardButton(f"🎲 Tài Xỉu 3D: {st('mt_taixiu')}", callback_data="tg_mt_taixiu")],
        [InlineKeyboardButton(f"💿 Xóc Đĩa: {st('mt_xocdia')}", callback_data="tg_mt_xocdia")],
        [InlineKeyboardButton(f"🏎 Đua Xe: {st('mt_duaxe')}", callback_data="tg_mt_duaxe"),
         InlineKeyboardButton(f"💣 Dò Mìn: {st('mt_domin')}", callback_data="tg_mt_domin")],
        [InlineKeyboardButton(f"⚽ Penalty: {st('mt_penalty')}", callback_data="tg_mt_penalty"),
         InlineKeyboardButton(f"🪵 Gõ Mõ: {st('mt_gomo')}", callback_data="tg_mt_gomo")],
        [InlineKeyboardButton(f"🔢 Quay Số: {st('mt_quayso')}", callback_data="tg_mt_quayso"),
         InlineKeyboardButton(f"🦀 Bầu Cua: {st('mt_baucua')}", callback_data="tg_mt_baucua")],
        [InlineKeyboardButton(f"📉 Xổ Số: {st('mt_xoso')}", callback_data="tg_mt_xoso"),
         InlineKeyboardButton(f"🎡 Vòng Quay: {st('mt_vongquay')}", callback_data="tg_mt_vongquay")],
        [InlineKeyboardButton(f"🃏 Cao Thấp: {st('mt_caothap')}", callback_data="tg_mt_caothap"),
         InlineKeyboardButton(f"🪵 Rút Gỗ: {st('mt_rutgo')}", callback_data="tg_mt_rutgo")],
        [InlineKeyboardButton(f"🎨 Tô Màu: {st('mt_tomau')}", callback_data="tg_mt_tomau")],
        [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"),
         InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
    ]
    await update.message.reply_text("🛠 **BẢNG QUẢN LÝ BẢO TRÌ**\n(Bấm để chuyển trạng thái On/Off)", reply_markup=InlineKeyboardMarkup(kb))

@admin_only
async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        if amount < 10000: await update.message.reply_text("❌ Số tiền nạp tối thiểu là `10,000đ`!", parse_mode="Markdown"); return
        now_str = get_vietnam_datetime_db()
        query("INSERT INTO deposit_history (user_id, amount, admin_id, status, time) VALUES (%s, %s, %s, %s, %s)", (target_id, amount, update.effective_user.id, 'success', now_str))
        add_money(target_id, amount, f"Nạp tiền +{amount:,}đ")
        try:
            await ctx.bot.send_message(chat_id=LOG_GROUP_ID, text=f"✅ **THÔNG BÁO NẠP TIỀN**\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`\n👮 Admin: `{update.effective_user.id}`\n────────────────\nChúc bạn chơi game vui vẻ!", parse_mode="Markdown")
        except: pass
        # SỬA: dùng get_promotion_bonus() thay vì hard-code
        bonus_amount = get_promotion_bonus(amount)
        if bonus_amount > 0:
            required_bet = bonus_amount * 3
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎁 NHẬN KHUYẾN MÃI", callback_data=f"accept_bonus_{target_id}_{bonus_amount}_{required_bet}"),
                InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"reject_bonus_{target_id}")
            ]])
            await ctx.bot.send_message(target_id, f"✅ **NẠP TIỀN THÀNH CÔNG!**\n\n💰 Số tiền nạp: `+{amount:,}đ`\n🏦 Số dư hiện tại: `{get_balance(target_id):,}đ`\n\n🎁 **BẠN CÓ MUỐN NHẬN THÊM KHUYẾN MÃI?**\n━━━━━━━━━━━━━━━━━━━━━\n✨ **Thưởng nạp:** `+{bonus_amount:,}đ`\n🎯 **Yêu cầu cược:** x3 vòng (`{required_bet:,}đ`)\n━━━━━━━━━━━━━━━━━━━━━\n⚠️ Lưu ý: Tiền khuyến mãi cần cược đủ x3 vòng mới có thể rút!", reply_markup=keyboard, parse_mode="Markdown")
        else:
            bill = f"✅ **NẠP TIỀN THÀNH CÔNG**\n━━━━━━━━━━━━━━━━━━━━━\n📥 **Số tiền:** `+{amount:,}đ`\n⏰ **Thời gian:** {now_str}\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số dư hiện tại: `{get_balance(target_id):,}đ`\n\n🎮 Chúc bạn chơi game vui vẻ!"
            await ctx.bot.send_message(chat_id=target_id, text=bill, parse_mode="Markdown")
        await update.message.reply_text(f"✅ **NẠP TIỀN THÀNH CÔNG**\n\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`{f'  🎁 Khuyến mãi: +{bonus_amount:,}đ (đã hỏi người dùng)' if bonus_amount > 0 else ''}", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Cú pháp: `/nap [ID] [Số tiền]`\n📌 Min nạp: `10,000đ`", parse_mode="Markdown")

@admin_only
async def kmnap_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/kmnap [ID] [số_tiền]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        bonus_amount = int(ctx.args[1])
        if bonus_amount <= 0: await update.message.reply_text("❌ Số tiền khuyến mãi phải lớn hơn 0!"); return
        required_bet = add_bonus_with_requirement(target_id, bonus_amount, 3)
        await update.message.reply_text(f"✅ **KHUYẾN MÃI NẠP THÀNH CÔNG!**\n\n👤 **ID:** `{target_id}`\n💰 **Tiền thưởng:** `+{bonus_amount:,}đ`\n🎯 **Yêu cầu cược:** `{required_bet:,}đ` (x3 vòng)", parse_mode="Markdown")
        await ctx.bot.send_message(target_id, f"🎁 **THÔNG BÁO KHUYẾN MÃI**\n\nBạn vừa nhận được khuyến mãi nạp: `+{bonus_amount:,}đ`\n📌 Cần cược đủ: `{required_bet:,}đ` để rút tiền\n✅ Chúc bạn may mắn!", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID hoặc số tiền không hợp lệ!")

@admin_only
async def kmnapvc_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2: await update.message.reply_text("❌ **Cú pháp:** `/kmnapvc [ID] [số_tiền]`", parse_mode="Markdown"); return
    try:
        target_id = int(ctx.args[0])
        bet_amount = int(ctx.args[1])
        if bet_amount <= 0: await update.message.reply_text("❌ Số tiền phải lớn hơn 0!"); return
        bonus_data = query("SELECT required_bet, current_bet FROM user_bonus WHERE user_id=%s", (target_id,))
        if not bonus_data or bonus_data[0][0] == 0: await update.message.reply_text(f"❌ ID `{target_id}` không có yêu cầu cược nào!", parse_mode="Markdown"); return
        required_bet, current_bet = bonus_data[0]
        new_bet = current_bet + bet_amount
        query("UPDATE user_bonus SET current_bet=%s WHERE user_id=%s", (new_bet, target_id))
        remaining = required_bet - new_bet
        await update.message.reply_text(f"✅ **CẬP NHẬT CƯỢC THÀNH CÔNG!**\n\n👤 **ID:** `{target_id}`\n➕ **Cược thêm:** `+{bet_amount:,}đ`\n📊 **Tổng cược:** `{new_bet:,}đ` / `{required_bet:,}đ`\n📌 **Trạng thái:** {'✅ ĐÃ HOÀN THÀNH!' if remaining <= 0 else f'Còn thiếu `{remaining:,}đ`'}", parse_mode="Markdown")
        await ctx.bot.send_message(target_id, f"📊 **CẬP NHẬT TIẾN ĐỘ CƯỢC**\n\nBạn đã cược thêm: `+{bet_amount:,}đ`\n📈 Tổng cược: `{new_bet:,}đ` / `{required_bet:,}đ`\n{'✅ Bạn đã hoàn thành yêu cầu cược!' if remaining <= 0 else f'⚠️ Cần cược thêm: `{remaining:,}đ`'}\n\n💪 Cố gắng lên nào!", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ID hoặc số tiền không hợp lệ!")

@admin_only
async def reset_all_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ XÁC NHẬN XÓA TẤT CẢ", callback_data="confirm_reset_all_final")], [InlineKeyboardButton("❌ HỦY THAO TÁC", callback_data="close_admin")]])
    await update.message.reply_text("⚠️ **CẢNH BẢO NGUY HIỂM** ⚠️\n\nThao tác này sẽ xóa sạch dữ liệu các bảng: **Users, History, Codes, Banned**.\nMọi thông tin số dư và lịch sử sẽ biến mất vĩnh viễn.\n\nBạn có chắc chắn muốn thực hiện?", reply_markup=kb, parse_mode="Markdown")

@admin_only
async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL, bank_linked=0 WHERE user_id=%s", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`. User có thể dùng /lienket lại.")
        try: await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn. Bạn có thể liên kết lại ngay bây giờ.")
        except: pass
    except:
        await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

@admin_only
async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(ctx.args[0])
        res = query("SELECT balance, refs, bank, stk, name, last_checkin, total_bet FROM users WHERE user_id=%s", (target_id,))
        if not res: return await update.message.reply_text("❌ Không tìm thấy người dùng này.")
        u = res[0]
        msg = (f"📂 **THÔNG TIN CHI TIẾT USER `{target_id}`**\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số dư: `{u[0]:,}đ`\n📊 Tổng cược: `{u[6]:,}đ`\n👥 Số người mời: `{u[1]}`\n🏛 Ngân hàng: `{u[2] or 'Chưa cập nhật'}`\n💳 Số tài khoản: `{u[3] or 'Chưa cập nhật'}`\n👤 Tên chủ thẻ: `{u[4] or 'Chưa cập nhật'}`\n📅 Điểm danh gần nhất: `{u[5] or 'Chưa có'}`\n━━━━━━━━━━━━━━━━━━━━━")
        await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/info [ID]`")

@admin_only
async def tao_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        reward, uses = int(ctx.args[0]), int(ctx.args[1])
        code = gen_code()
        query("INSERT INTO codes (code, reward, uses) VALUES(%s,%s,%s)", (code, reward, uses))
        await update.message.reply_text(f"✅ **TẠO CODE THÀNH CÔNG**\n\n🎁 Code: `{code}`\n💰 Thưởng: `{reward:,}đ`\n🔄 Lượt: `{uses}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/taocode [số tiền] [lượt dùng]`")

@admin_only
async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        add_money(uid, amt, "Admin cộng tiền")
        await update.message.reply_text(f"✅ Đã cộng `{amt:,}đ` cho ID `{uid}`")
    except: pass

@admin_only
async def sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid, amt = int(ctx.args[0]), int(ctx.args[1])
        sub_money(uid, amt, "Admin trừ tiền")
        await update.message.reply_text(f"✅ Đã trừ `{amt:,}đ` của ID `{uid}`")
    except: pass

@admin_only
async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(ctx.args[0])
        query("INSERT INTO banned(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (uid,))
        await update.message.reply_text(f"🚫 Đã chặn người dùng `{uid}`")
    except: pass

@admin_only
async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM banned WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"✅ Đã bỏ chặn người dùng `{uid}`")
    except: pass

@admin_only
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    res = query("SELECT COUNT(*) FROM users")
    total = res[0][0] if res else 0
    await update.message.reply_text(f"📊 **THỐNG KÊ:**\n\n👥 Tổng số người dùng: `{total}`", parse_mode="Markdown")

@admin_only
async def all_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page=0):
    limit = 20
    offset = page * limit
    users = query("SELECT user_id, balance FROM users ORDER BY user_id DESC LIMIT %s OFFSET %s", (limit, offset))
    res_total = query("SELECT COUNT(*) FROM users")
    total_users = res_total[0][0] if res_total else 0
    total_pages = (total_users + limit - 1) // limit
    if not users: return await update.message.reply_text("Chưa có người dùng nào.")
    kb = []
    for u in users:
        u_id, bal = u[0], u[1]
        status = "🚫" if is_banned(u_id) else "🟢"
        kb.append([InlineKeyboardButton(f"{status} ID: {u_id} | {bal:,}đ", callback_data=f"adm_manage_{u_id}_{page}")])
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"adm_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"Trang {page+1}/{total_pages}", callback_data="none"))
    if (page + 1) < total_pages: nav_buttons.append(InlineKeyboardButton("Sau ➡️", callback_data=f"adm_page_{page+1}"))
    kb.append(nav_buttons)
    kb.append([InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")])
    text = f"👥 **DANH SÁCH NGƯỜI DÙNG** (Tổng: {total_users})\nBấm vào User để xem chi tiết:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

@admin_only
async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = query("SELECT * FROM history ORDER BY time DESC LIMIT 50")
    msg = "🌐 **LỊCH SỬ TOÀN HỆ THỐNG:**\n\n"
    if data:
        for d in data:
            msg += f"👤 `{d[0]}` | `{d[1]:,}đ` | {d[2]}\n"
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000): await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg or "Trống", parse_mode="Markdown")

@admin_only
async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❌ Cú pháp: `/send [nội dung]`")
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

@admin_only
async def reply_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(ctx.args[0])
        msg_reply = " ".join(ctx.args[1:])
        await ctx.bot.send_message(chat_id=uid, text=f"✉️ **PHẢN HỒI TỪ ADMIN:**\n\n{msg_reply}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Đã gửi phản hồi tới `{uid}`")
    except:
        await update.message.reply_text("❌ Cú pháp: `/rep [ID] [Nội dung]`")

@admin_only
async def check_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(ctx.args[0])
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s ORDER BY time DESC", (uid,))
        if not data: await update.message.reply_text(f"📥 User `{uid}` chưa có giao dịch.")
        else:
            msg = f"📜 **LỊCH SỬ USER `{uid}`:**\n\n"
            for d in data: msg += f"💰 `{d[0]:,}` | {d[1]} | _{d[2]}_\n"
            if len(msg) > 4000:
                for x in range(0, len(msg), 4000): await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
            else:
                await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Cú pháp: `/check [ID]`")

async def list_banned_admins_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("❌ Bạn không có quyền!"); return
    banned_list = query("SELECT admin_id, banned_by, reason, banned_at FROM banned_admins")
    if not banned_list: await update.message.reply_text("📋 Hiện không có Admin nào bị cấm.", parse_mode="Markdown"); return
    msg = "🚫 **DANH SÁCH ADMIN BỊ CẤM**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for admin_id, banned_by, reason, banned_at in banned_list:
        msg += f"\n👤 ID: `{admin_id}`\n👮 Bởi: `{banned_by}`\n📝 Lý do: {reason}\n⏰ Lúc: {banned_at}\n━━━━━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ===== TẤT CẢ CALLBACK HANDLERS =====

# 1. BẢO TRÌ TOGGLE (ĐÃ SỬA)
async def handle_baotri_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    key = q.data[3:]  # bỏ "tg_" → lấy "mt_taixiu" v.v.
    current = check_mt(key)
    new_val = '0' if current else '1'
    query("UPDATE settings SET value=%s WHERE key=%s", (new_val, key))
    status = "🔴 BẢO TRÌ" if new_val == '1' else "🟢 HOẠT ĐỘNG"
    await q.answer(f"Đã chuyển sang {status}", show_alert=False)
    await baotri_cmd(update, ctx)

# 2. CANCEL CUSTOM BET (MỚI)
async def cancel_custom_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    ctx.user_data.pop(f"custom_bet_{uid}", None)
    ctx.user_data.pop(f"hl_{uid}", None)
    ctx.user_data.pop(f"sg_{uid}", None)
    ctx.user_data.pop(f"cf_{uid}", None)
    try:
        await q.edit_message_text("❌ **ĐÃ THOÁT**\n\nBạn có thể chọn lại game bất cứ lúc nào!\n\n📝 Dùng lệnh `/start` để xem menu chính.", parse_mode="Markdown")
    except: pass
    await q.answer("Đã hủy!")

# 3. CLOSE ADMIN (MỚI)
async def close_admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.delete_message()
    except:
        await q.edit_message_text("✅ Đã đóng bảng quản lý.")
    await q.answer()

# 4. DUYỆT/TỪ CHỐI RÚT TIỀN (MỚI)
async def approve_withdraw_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    admin_id = q.from_user.id
    if admin_id not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    parts = q.data.split("_")
    action = parts[0]  # "ok" or "no"
    user_id = int(parts[1])
    amount = int(parts[2])
    now_str = get_vietnam_datetime_db()
    if action == "ok":
        query("UPDATE withdraw_history SET status='success', admin_id=%s WHERE user_id=%s AND amount=%s AND status='pending'", (admin_id, user_id, amount))
        await q.edit_message_text(f"✅ **ĐÃ DUYỆT RÚT TIỀN**\n\n👤 ID: `{user_id}`\n💰 Số tiền: `{amount:,}đ`\n👮 Admin duyệt: `{admin_id}`\n⏰ Thời gian: `{now_str}`", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(user_id, f"✅ **YÊU CẦU RÚT TIỀN ĐÃ ĐƯỢC DUYỆT!**\n\n💰 Số tiền: `{amount:,}đ`\n⏰ Thời gian: `{now_str}`\n\n🏦 Tiền sẽ được chuyển trong vài phút. Cảm ơn bạn đã sử dụng dịch vụ!", parse_mode="Markdown")
        except: pass
        await q.answer("✅ Đã duyệt!")
    elif action == "no":
        add_money(user_id, amount, f"Hoàn tiền rút bị từ chối")
        query("UPDATE withdraw_history SET status='rejected', admin_id=%s WHERE user_id=%s AND amount=%s AND status='pending'", (admin_id, user_id, amount))
        await q.edit_message_text(f"❌ **ĐÃ TỪ CHỐI YÊU CẦU RÚT TIỀN**\n\n👤 ID: `{user_id}`\n💰 Số tiền: `{amount:,}đ` (đã hoàn lại)\n👮 Admin: `{admin_id}`\n⏰ Thời gian: `{now_str}`", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(user_id, f"❌ **YÊU CẦU RÚT TIỀN BỊ TỪ CHỐI!**\n\n💰 Số tiền: `{amount:,}đ`\n🔄 Tiền đã được hoàn lại vào tài khoản.\n\n📞 Liên hệ CSKH để biết thêm thông tin.", parse_mode="Markdown")
        except: pass
        await q.answer("❌ Đã từ chối!")

# 5. LỊCH SỬ NAP/RUT (MỚI)
async def his_deposit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = query("SELECT amount, admin_id, time FROM deposit_history WHERE user_id=%s AND status='success' ORDER BY time DESC LIMIT 10", (uid,))
    if not data:
        await q.answer("Chưa có lịch sử nạp nào!", show_alert=True)
        return
    msg = "📥 **LỊCH SỬ NẠP TIỀN**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for row in data:
        msg += f"✅ `+{row[0]:,}đ` | ⏰ _{row[2]}_\n"
    await q.answer()
    await ctx.bot.send_message(uid, msg, parse_mode="Markdown")

async def his_withdraw_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = query("SELECT amount, status, time FROM withdraw_history WHERE user_id=%s ORDER BY time DESC LIMIT 10", (uid,))
    if not data:
        await q.answer("Chưa có lịch sử rút nào!", show_alert=True)
        return
    msg = "📤 **LỊCH SỬ RÚT TIỀN**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for row in data:
        status_icon = "✅" if row[1] == "success" else "❌" if row[1] == "rejected" else "⏳"
        status_text = "Thành công" if row[1] == "success" else "Từ chối" if row[1] == "rejected" else "Chờ duyệt"
        msg += f"{status_icon} `{row[0]:,}đ` | {status_text} | ⏰ _{row[2]}_\n"
    await q.answer()
    await ctx.bot.send_message(uid, msg, parse_mode="Markdown")

# 6. XÁC NHẬN CÁC THAO TÁC NGUY HIỂM (MỚI)
async def confirm_callbacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    data = q.data
    if data == "confirm_reset_all_final":
        query("DELETE FROM history")
        query("DELETE FROM codes")
        query("DELETE FROM banned")
        query("UPDATE users SET balance=0, total_bet=0")
        await q.edit_message_text("✅ **ĐÃ XÓA TOÀN BỘ DỮ LIỆU!**\n\n⚠️ Tất cả số dư, lịch sử, code và danh sách cấm đã bị xóa!", parse_mode="Markdown")
        await q.answer("✅ Đã thực hiện!")
    elif data == "confirm_bonus_vip":
        users = query("SELECT user_id, total_bet FROM users")
        count = 0
        for user_id, total_bet in (users or []):
            vip_name, bonus = get_vip_info(total_bet or 0)
            if "VIP" in vip_name and bonus > 0:
                add_money(user_id, bonus, f"Thưởng VIP hàng tháng")
                count += 1
                try: await ctx.bot.send_message(user_id, f"👑 **THƯỞNG VIP HÀNG THÁNG!**\n\n🌟 Cấp: `{vip_name}`\n💰 Thưởng: `+{bonus:,}đ`\n\n🎮 Chúc bạn may mắn!")
                except: pass
        await q.edit_message_text(f"✅ **ĐÃ THƯỞNG VIP THÀNH CÔNG!**\n\n👥 Số người được thưởng: `{count}`", parse_mode="Markdown")
        await q.answer("✅ Đã thực hiện!")
    elif data == "confirm_mofull":
        query("DELETE FROM banned")
        query("DELETE FROM banned_games")
        query("DELETE FROM banned_features")
        query("DELETE FROM banned_admins")
        query("DELETE FROM banned_admin_commands")
        await q.edit_message_text("✅ **ĐÃ MỞ TẤT CẢ NGƯỜI BỊ CẤM!**\n\n✅ Xóa sạch toàn bộ danh sách cấm.", parse_mode="Markdown")
        await q.answer("✅ Đã thực hiện!")
    elif data.startswith("confirm_giftall_"):
        parts = data.split("_")
        amount = int(parts[2])
        total_users = int(parts[3])
        reason = ctx.user_data.get("giftall_reason", "Quà tặng từ Admin")
        users = query("SELECT user_id FROM users")
        count = 0
        for user in (users or []):
            add_money(user[0], amount, reason)
            count += 1
            try: await ctx.bot.send_message(user[0], f"🎁 **QUÀ TẶNG TỪ ADMIN!**\n\n💰 Bạn nhận được: `+{amount:,}đ`\n📝 Lý do: {reason}\n💵 Số dư: `{get_balance(user[0]):,}đ`", parse_mode="Markdown")
            except: pass
        await q.edit_message_text(f"✅ **ĐÃ TẶNG QUÀ THÀNH CÔNG!**\n\n💰 Mỗi người: `{amount:,}đ`\n👥 Số người nhận: `{count}`", parse_mode="Markdown")
        await q.answer("✅ Đã thực hiện!")

# 7. ACCEPT/REJECT BONUS (MỚI)
async def bonus_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    action = parts[0]  # "accept" or "reject"
    user_id = int(parts[2])
    if q.from_user.id != user_id:
        await q.answer("❌ Không phải của bạn!", show_alert=True)
        return
    if action == "accept":
        bonus_amount = int(parts[3])
        required_bet = int(parts[4])
        add_bonus_with_requirement(user_id, bonus_amount, 3)
        await q.edit_message_text(f"✅ **ĐÃ NHẬN KHUYẾN MÃI!**\n\n💰 Khuyến mãi: `+{bonus_amount:,}đ`\n🎯 Cần cược: `{required_bet:,}đ` để rút tiền\n\n💵 Số dư: `{get_balance(user_id):,}đ`", parse_mode="Markdown")
        await q.answer("✅ Đã nhận khuyến mãi!")
    elif action == "reject":
        await q.edit_message_text("✅ **ĐÃ TỪ CHỐI KHUYẾN MÃI**\n\nBạn đã từ chối nhận khuyến mãi. Tiền nạp vẫn được cộng bình thường.", parse_mode="Markdown")
        await q.answer("Đã từ chối!")

# 8. ANONYMOUS MESSAGE REPLY/BLOCK (MỚI)
async def anon_action_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    admin_id = q.from_user.id
    if admin_id not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    parts = q.data.split("_")
    action = parts[0]  # "reply" or "block"
    user_id = int(parts[2])
    if action == "reply":
        ctx.user_data[f"anon_reply_{admin_id}"] = user_id
        await q.answer("Nhập nội dung trả lời vào chat với bot!")
        await ctx.bot.send_message(admin_id, f"✉️ Nhập nội dung trả lời cho người dùng ẩn danh (ID: `{user_id}`):\n\n_(Gửi bất kỳ tin nhắn nào để trả lời)_", parse_mode="Markdown")
    elif action == "block":
        query("INSERT INTO banned(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (user_id,))
        await q.edit_message_text(f"🚫 Đã chặn người dùng ID `{user_id}` khỏi gửi tin nhắn ẩn danh.", parse_mode="Markdown")
        await q.answer("Đã chặn!")

# 9. EXPORT BAN LIST (MỚI)
async def export_ban_list_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    await q.answer("Đang xuất dữ liệu...")
    output = BytesIO()
    output.write(u'\ufeff'.encode('utf-8'))
    writer = csv.writer(output, delimiter=',')
    writer.writerow(['Loại', 'User ID', 'Chi tiết', 'Thời gian/Lý do'])
    banned_users = query("SELECT user_id FROM banned") or []
    for uid in banned_users:
        writer.writerow(['CẤM TOÀN BỘ', uid[0], 'Không thể sử dụng bot', ''])
    banned_games = query("SELECT bg.user_id, gr.name, bg.game_id FROM banned_games bg LEFT JOIN game_rates gr ON bg.game_id = gr.id") or []
    for uid, game_name, gid in banned_games:
        writer.writerow(['CẤM GAME', uid, f'Game {gid}: {game_name}', ''])
    banned_features = query("SELECT user_id, feature FROM banned_features") or []
    for uid, feature in banned_features:
        writer.writerow(['CẤM TÍNH NĂNG', uid, "NẠP TIỀN" if feature == "nap" else "RÚT TIỀN", ''])
    banned_admins = query("SELECT admin_id, reason, banned_at FROM banned_admins") or []
    for aid, reason, banned_at in banned_admins:
        writer.writerow(['CẤM ADMIN', aid, reason, banned_at])
    banned_cmds = query("SELECT admin_id, command, reason FROM banned_admin_commands") or []
    for aid, cmd, reason in banned_cmds:
        writer.writerow(['CẤM LỆNH ADMIN', aid, f'Lệnh /{cmd}', reason])
    output.seek(0)
    await q.message.reply_document(document=output, filename=f"danh_sach_bi_cam_{get_vietnam_time().strftime('%Y%m%d_%H%M%S')}.csv", caption=f"📊 **DANH SÁCH BỊ CẤM**\n📅 Ngày xuất: {get_vietnam_datetime_db()}")

# 10. RATE CALLBACK (ĐÃ CÓ, GIỮ NGUYÊN)
async def handle_rate_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Bạn không có quyền!", show_alert=True)
        return
    data = q.data
    if data.startswith("rate_show_"):
        game_id = int(data.split("_")[2])
        rate_info = query("SELECT id, name, rate FROM game_rates WHERE id=%s", (game_id,))
        if rate_info:
            gid, name, rate = rate_info[0]
            await q.answer(f"🎮 {name}\n📊 Tỉ lệ thắng: {rate}%", show_alert=True)
    elif data.startswith("rate_inc_"):
        game_id = int(data.split("_")[2])
        current = query("SELECT rate FROM game_rates WHERE id=%s", (game_id,))
        if current:
            new_rate = min(100, current[0][0] + 10)
            query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
            await q.answer(f"✅ Đã tăng lên {new_rate}%", show_alert=True)
            await chinhkq_cmd(update, ctx)
    elif data.startswith("rate_dec_"):
        game_id = int(data.split("_")[2])
        current = query("SELECT rate FROM game_rates WHERE id=%s", (game_id,))
        if current:
            new_rate = max(0, current[0][0] - 10)
            query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
            await q.answer(f"✅ Đã giảm xuống {new_rate}%", show_alert=True)
            await chinhkq_cmd(update, ctx)

# 11. GAME MENU CALLBACKS (MỚI)
async def game_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if is_banned(uid):
        await q.answer("❌ Tài khoản của bạn đã bị khóa!", show_alert=True)
        return
    data = q.data
    await q.answer()
    if data == "menu_tx":
        if check_mt('mt_taixiu') and uid not in ADMIN_IDS:
            await q.edit_message_text("⚙️ Game Tài Xỉu đang bảo trì!")
            return
        if not check_bank_linked(uid):
            await q.edit_message_text("❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia chơi game.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
            return
        amounts = [1000, 5000, 10000, 50000, 100000, 500000]
        kb = get_betting_keyboard(amounts, "p_tx_bet")
        await q.edit_message_text("🎲 **TÀI XỈU 3D - RIÊNG TƯ** 🎲\n\n📖 **LUẬT CHƠI:**\n• TÀI (11-18 điểm): x1.95\n• XỈU (3-10 điểm): x1.95\n• CHẴN (tổng chẵn): x1.95\n• LẺ (tổng lẻ): x1.95\n\n💰 **Chọn mức cược hoặc nhập số tiền:**", reply_markup=kb, parse_mode="Markdown")
    elif data == "menu_race":
        if check_mt('mt_duaxe') and uid not in ADMIN_IDS:
            await q.edit_message_text("⚙️ Game Đua Xe đang bảo trì!")
            return
        if not check_bank_linked(uid):
            await q.edit_message_text("❌ **BẮT BUỘC LIÊN KẾT NGÂN HÀNG!**\n\nBạn cần liên kết tài khoản ngân hàng để tham gia chơi game.\n👉 Dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`", parse_mode="Markdown")
            return
        amounts = [1000, 5000, 10000, 50000, 100000]
        kb = []
        row = []
        for i, a in enumerate(amounts):
            display = f"{a//1000}k"
            row.append(InlineKeyboardButton(display, callback_data=f"race_choicea_{a}"))
            if (i + 1) % 3 == 0: kb.append(row); row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")])
        await q.edit_message_text("🏎️ **ĐUA XE SIÊU CẤP** 🏎️\n\n📖 **LUẬT CHƠI:**\n• Chọn xe A hoặc xe B\n• Nếu xe bạn chọn về nhất: x1.95\n\n💰 **Chọn mức cược:**\n(Chọn tiền → chọn xe A hoặc B)", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data == "menu_highlow":
        await q.delete_message()
        class FakeMsg:
            async def reply_text(self, *args, **kwargs): return await ctx.bot.send_message(uid, *args, **kwargs)
            message = None
        class FakeUpdate:
            effective_user = q.from_user
            message = FakeMsg()
        await play_highlow(FakeUpdate(), ctx)
    elif data == "menu_stick":
        await q.delete_message()
        class FakeMsg2:
            async def reply_text(self, *args, **kwargs): return await ctx.bot.send_message(uid, *args, **kwargs)
        class FakeUpdate2:
            effective_user = q.from_user
            message = FakeMsg2()
        await play_stick_game(FakeUpdate2(), ctx)
    elif data == "menu_color":
        await q.delete_message()
        class FakeMsg3:
            async def reply_text(self, *args, **kwargs): return await ctx.bot.send_message(uid, *args, **kwargs)
        class FakeUpdate3:
            effective_user = q.from_user
            message = FakeMsg3()
        await play_color_fill(FakeUpdate3(), ctx)
    elif data == "menu_taixiu_room":
        await q.edit_message_text("🎲 **TÀI XỈU ROOM** 🎲\n\n📖 **CÁCH THAM GIA:**\n• Vào nhóm game của bot\n• Dùng lệnh: `t [tiền]` (TÀI), `x [tiền]` (XỈU)\n• Dùng lệnh: `c [tiền]` (CHẴN), `l [tiền]` (LẺ)\n\n⏱️ Mỗi ván 60 giây\n🏆 Tỉ lệ thưởng: x1.95\n\n📞 Liên hệ CSKH để được thêm vào nhóm game!", parse_mode="Markdown")
    else:
        game_names = {
            "menu_xocdia": "💿 XÓC ĐĨA", "menu_mines": "💣 DÒ MÌN",
            "menu_ball": "⚽ PENALTY", "menu_wooden": "🪵 GÕ MÕ",
            "menu_qs": "🔢 QUAY SỐ", "menu_bc": "🦀 BẦU CUA TÔM CÁ",
            "menu_xoso": "📉 XỔ SỐ MIỀN BẮC", "menu_vq": "🎡 VÒNG QUAY MAY MẮN"
        }
        game_name = game_names.get(data, "Game này")
        await q.edit_message_text(f"🎮 **{game_name}**\n\n⚠️ Dùng lệnh trực tiếp để chơi:\n• Nhập lệnh tương ứng trong chat với bot\n\n📞 Liên hệ CSKH nếu cần hỗ trợ!", parse_mode="Markdown")

# 12. HIGHLOW BET CALLBACK (MỚI)
async def hl_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    amount_str = parts[2]
    if amount_str == "custom":
        await q.answer()
        ctx.user_data[f"custom_bet_{uid}"] = {"game_name": "CAO THẤP", "callback_type": "hl", "step": "waiting_for_amount"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]])
        await q.edit_message_text("✏️ **CƯỢC TỰ DO - CAO THẤP** ✏️\n━━━━━━━━━━━━━━━━━━━━━\n💰 Vui lòng **nhập số tiền** bạn muốn cược:\n📌 Tối thiểu: `1,000đ` | Tối đa: `10,000,000đ`\n\n⏳ Nhập số tiền ngay bên dưới!", reply_markup=kb, parse_mode="Markdown")
        return
    amount = int(amount_str)
    await start_highlow(update, ctx, amount)

async def start_highlow(update: Update, ctx: ContextTypes.DEFAULT_TYPE, amount: int):
    q = update.callback_query
    uid = q.from_user.id
    card_names = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}
    first_card = random.randint(1, 13)
    first_name = card_names.get(first_card, str(first_card))
    ctx.user_data[f"hl_{uid}"] = {"first_card": first_card, "bet": amount, "status": "waiting"}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 CAO HƠN", callback_data=f"hl_choice_higher_{amount}"),
         InlineKeyboardButton("📉 THẤP HƠN", callback_data=f"hl_choice_lower_{amount}")],
        [InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")]
    ])
    await q.edit_message_text(f"🃏 **LÁ BÀI ĐẦU TIÊN:** `{first_name}`\n💰 **Cược:** `{amount:,}đ`\n\n🤔 **Bạn dự đoán lá tiếp theo?**", reply_markup=kb, parse_mode="Markdown")

# 13. STICK BET CALLBACK (MỚI)
async def sg_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    amount_str = parts[2]
    if amount_str == "custom":
        await q.answer()
        ctx.user_data[f"custom_bet_{uid}"] = {"game_name": "RÚT GỖ", "callback_type": "sg", "step": "waiting_for_amount"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]])
        await q.edit_message_text("✏️ **CƯỢC TỰ DO - RÚT GỖ** ✏️\n━━━━━━━━━━━━━━━━━━━━━\n💰 Vui lòng **nhập số tiền** bạn muốn cược:\n📌 Tối thiểu: `1,000đ` | Tối đa: `10,000,000đ`\n\n⏳ Nhập số tiền ngay bên dưới!", reply_markup=kb, parse_mode="Markdown")
        return
    amount = int(amount_str)
    ctx.user_data[f"sg_{uid}"] = {"sticks": 15, "bet": amount, "turn": "player", "game_id": random.randint(1000, 9999)}
    kb = [[InlineKeyboardButton("🪵 RÚT 1 QUE", callback_data=f"sg_pull_{uid}_1"),
           InlineKeyboardButton("🪵 RÚT 2 QUE", callback_data=f"sg_pull_{uid}_2"),
           InlineKeyboardButton("🪵 RÚT 3 QUE", callback_data=f"sg_pull_{uid}_3")],
          [InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")]]
    await q.edit_message_text(f"🪵 **RÚT GỖ - BẮT ĐẦU!** 🪵\n━━━━━━━━━━━━━━━━━━━━━\n💰 **Cược:** `{amount:,}đ`\n🪵 **Số que còn lại:** `15`\n━━━━━━━━━━━━━━━━━━━━━\n👉 **Lượt của bạn!** Rút que:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# 14. COLOR FILL BET CALLBACK (MỚI)
async def cf_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    amount_str = parts[2]
    if amount_str == "custom":
        await q.answer()
        ctx.user_data[f"custom_bet_{uid}"] = {"game_name": "TÔ MÀU", "callback_type": "cf", "step": "waiting_for_amount"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]])
        await q.edit_message_text("✏️ **CƯỢC TỰ DO - TÔ MÀU** ✏️\n━━━━━━━━━━━━━━━━━━━━━\n💰 Vui lòng **nhập số tiền** bạn muốn cược:\n📌 Tối thiểu: `1,000đ` | Tối đa: `10,000,000đ`\n\n⏳ Nhập số tiền ngay bên dưới!", reply_markup=kb, parse_mode="Markdown")
        return
    amount = int(amount_str)
    ctx.user_data[f"cf_{uid}"] = {"grid": [[0,0,0],[0,0,0],[0,0,0]], "bet": amount, "filled": 0}
    await update_cf_grid(q, uid, ctx)

# 15. TAIXIU PRIVATE BET CALLBACK (MỚI)
async def p_tx_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    amount_str = parts[3]
    if amount_str == "custom":
        await q.answer()
        ctx.user_data[f"custom_bet_{uid}"] = {"game_name": "TÀI XỈU", "callback_type": "tx", "step": "waiting_for_amount"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ HỦY", callback_data="cancel_custom_bet")]])
        await q.edit_message_text("✏️ **CƯỢC TỰ DO - TÀI XỈU** ✏️\n━━━━━━━━━━━━━━━━━━━━━\n💰 Vui lòng **nhập số tiền** bạn muốn cược:\n📌 Tối thiểu: `1,000đ` | Tối đa: `10,000,000đ`\n\n⏳ Nhập số tiền ngay bên dưới!", reply_markup=kb, parse_mode="Markdown")
        return
    amount = int(amount_str)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 TÀI (x1.95)", callback_data=f"p_tx_tai_{amount}"),
         InlineKeyboardButton("🎲 XỈU (x1.95)", callback_data=f"p_tx_xiu_{amount}")],
        [InlineKeyboardButton("🔴 CHẴN (x1.95)", callback_data=f"p_tx_chan_{amount}"),
         InlineKeyboardButton("⚪ LẺ (x1.95)", callback_data=f"p_tx_le_{amount}")],
        [InlineKeyboardButton("❌ THOÁT", callback_data="cancel_custom_bet")]
    ])
    await q.edit_message_text(f"🎲 **TÀI XỈU 3D**\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số tiền cược: `{amount:,}đ`\n\n🎯 **Chọn cửa cược:**", reply_markup=kb, parse_mode="Markdown")

async def p_tx_choice_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    choice_map = {"tai": "XXT", "xiu": "XXX", "chan": "XXC", "le": "XXL"}
    choice = parts[2]
    amount = int(parts[3])
    if is_game_banned(uid, 1):
        await q.answer("❌ Bạn đã bị cấm chơi game này!", show_alert=True)
        return
    if not sub_money(uid, amount, f"Cược Tài Xỉu {choice.upper()}"):
        await q.answer("❌ Số dư không đủ!", show_alert=True)
        return
    await q.answer()
    await q.edit_message_text(f"🎲 **ĐANG LẮC XÚC XẮC...**\nCửa cược: **{choice.upper()}** | Số tiền: `{amount:,}đ`", parse_mode="Markdown")
    d1 = await ctx.bot.send_dice(uid, emoji="🎲")
    d2 = await ctx.bot.send_dice(uid, emoji="🎲")
    d3 = await ctx.bot.send_dice(uid, emoji="🎲")
    await asyncio.sleep(4)
    results = [d1.dice.value, d2.dice.value, d3.dice.value]
    total = sum(results)
    is_chan = (total % 2 == 0)
    is_tai = (total >= 11)
    c = choice_map.get(choice, "XXX")
    is_win_flag = check_win_by_id(1, uid)
    win = False
    if is_win_flag:
        if (c == "XXC" and is_chan) or (c == "XXL" and not is_chan) or (c == "XXX" and not is_tai) or (c == "XXT" and is_tai):
            win = True
    res_str = "-".join(map(str, results))
    result_text_tx = "TÀI" if is_tai else "XỈU"
    result_text_cl = "CHẴN" if is_chan else "LẺ"
    if win:
        win_amt = int(amount * 1.95)
        add_money(uid, win_amt, f"Thắng Tài Xỉu {choice.upper()}")
        await ctx.bot.send_message(uid, f"🎲 **Kết quả: {res_str} = {total} ({result_text_tx} {result_text_cl})**\n✅ **THẮNG!** Nhận: `+{win_amt:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
    else:
        await ctx.bot.send_message(uid, f"🎲 **Kết quả: {res_str} = {total} ({result_text_tx} {result_text_cl})**\n❌ **THUA!** Mất: `{amount:,}đ`\n💵 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

# 16. RACE CALLBACKS (MỚI)
async def race_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    parts = q.data.split("_")
    choice = "A" if parts[1] == "choicea" else "B"
    amount = int(parts[2])
    if not sub_money(uid, amount, f"Cược Đua Xe {choice}"):
        await q.answer("❌ Số dư không đủ!", show_alert=True)
        return
    await q.answer()
    await q.delete_message()
    await play_car_race(update, ctx, choice, amount)

# 17. ADMIN MANAGE CALLBACKS (ĐÃ SỬA LOGIC)
async def admin_manage_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    data = q.data
    if data == "admin_list_header":
        await q.answer("Danh sách admin trong hệ thống.", show_alert=True)
    elif data == "admin_back":
        await quanlyadmin_cmd(update, ctx)
    elif data.startswith("admin_detail_"):
        target_admin = int(data.split("_")[2])
        is_banned_admin = is_admin_banned(target_admin)
        banned_cmds = query("SELECT command FROM banned_admin_commands WHERE admin_id=%s", (target_admin,)) or []
        banned_cmds_list = [b[0] for b in banned_cmds]
        kb = []
        if target_admin != 8619503816 and uid == 8619503816:
            if is_banned_admin:
                kb.append([InlineKeyboardButton("✅ GỠ CẤM ADMIN", callback_data=f"admin_unban_{target_admin}")])
            else:
                kb.append([InlineKeyboardButton("🚫 CẤM ADMIN", callback_data=f"admin_ban_{target_admin}")])
            kb.append([InlineKeyboardButton("📋 QUẢN LÝ LỆNH", callback_data=f"admin_cmds_{target_admin}")])
        kb.append([InlineKeyboardButton("🔙 QUAY LẠI", callback_data="admin_back")])
        status_text = "🚫 BỊ CẤM" if is_banned_admin else "✅ HOẠT ĐỘNG"
        msg = f"👤 **THÔNG TIN ADMIN `{target_admin}`**\n━━━━━━━━━━━━━━━━━━━━━\n📊 Trạng thái: {status_text}\n"
        if banned_cmds_list:
            msg += f"🚫 Lệnh bị cấm: {', '.join(['/' + c for c in banned_cmds_list])}\n"
        else:
            msg += "✅ Không bị cấm lệnh nào\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━"
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data.startswith("admin_ban_"):
        target_admin = int(data.split("_")[2])
        now_str = get_vietnam_datetime_db()
        query("INSERT INTO banned_admins VALUES(%s, %s, %s, %s) ON CONFLICT (admin_id) DO UPDATE SET banned_by=%s, reason=%s, banned_at=%s", (target_admin, uid, "Quản lý qua bảng", now_str, uid, "Quản lý qua bảng", now_str))
        await q.answer(f"✅ Đã cấm Admin {target_admin}!", show_alert=True)
        try: await ctx.bot.send_message(target_admin, "⚠️ Bạn đã bị cấm sử dụng các lệnh Admin!")
        except: pass
        await quanlyadmin_cmd(update, ctx)
    elif data.startswith("admin_unban_"):
        target_admin = int(data.split("_")[2])
        query("DELETE FROM banned_admins WHERE admin_id=%s", (target_admin,))
        await q.answer(f"✅ Đã gỡ cấm Admin {target_admin}!", show_alert=True)
        try: await ctx.bot.send_message(target_admin, "✅ Bạn đã được gỡ cấm và có thể sử dụng lại các lệnh Admin!")
        except: pass
        await quanlyadmin_cmd(update, ctx)
    elif data.startswith("admin_cmds_"):
        target_admin = int(data.split("_")[2])
        admin_commands = ["tile1", "tileall", "resetsdall", "xoalsall", "soduall", "tong", "thongke", "baotri", "cam", "bocam", "add", "sub", "ban", "unban", "nap", "kmnap", "kmnapvc", "taocode", "setname", "xoals", "check", "info", "resetbank", "send", "rep", "tatroom", "baotriall"]
        kb = []
        for cmd in admin_commands:
            is_cmd_banned = is_admin_command_banned(target_admin, cmd)
            status = "❌ CẤM" if is_cmd_banned else "✅ MỞ"
            kb.append([InlineKeyboardButton(f"{status} /{cmd}", callback_data=f"admin_toggle_{target_admin}_{cmd}")])
        kb.append([InlineKeyboardButton("🔙 QUAY LẠI", callback_data=f"admin_detail_{target_admin}")])
        await q.edit_message_text(f"📋 **QUẢN LÝ LỆNH CHO ADMIN `{target_admin}`**\n━━━━━━━━━━━━━━━━━━━━━\n✅ MỞ: Admin được dùng | ❌ CẤM: Admin không được dùng\n\n👇 Bấm vào lệnh để chuyển trạng thái:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data.startswith("admin_toggle_"):
        parts = data.split("_")
        target_admin = int(parts[2])
        cmd_name = "_".join(parts[3:])
        if is_admin_command_banned(target_admin, cmd_name):
            query("DELETE FROM banned_admin_commands WHERE admin_id=%s AND command=%s", (target_admin, cmd_name))
            await q.answer(f"✅ Đã MỞ lệnh /{cmd_name}", show_alert=True)
        else:
            now_str = get_vietnam_datetime_db()
            query("INSERT INTO banned_admin_commands VALUES(%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (target_admin, cmd_name, uid, "Quản lý qua bảng", now_str))
            await q.answer(f"❌ Đã CẤM lệnh /{cmd_name}", show_alert=True)
        # Refresh
        fake_data = f"admin_cmds_{target_admin}"
        q.data = fake_data
        await admin_manage_callback(update, ctx)
    elif data == "admin_manage_commands":
        await q.answer("Hãy chọn một Admin cụ thể để quản lý lệnh!", show_alert=True)

# 18. ADM_PAGE và ADM_MANAGE CALLBACKS (MỚI)
async def adm_page_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    page = int(q.data.split("_")[2])
    await all_user(update, ctx, page=page)

async def adm_manage_user_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    parts = q.data.split("_")
    target_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    res = query("SELECT balance, bank, stk, name, total_bet FROM users WHERE user_id=%s", (target_id,))
    if not res:
        await q.answer("Không tìm thấy người dùng!", show_alert=True)
        return
    u = res[0]
    vip_name, _ = get_vip_info(u[4] or 0)
    banned_status = "🚫 BỊ CẤM" if is_banned(target_id) else "✅ Bình thường"
    msg = f"👤 **QUẢN LÝ USER `{target_id}`**\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số dư: `{u[0]:,}đ`\n📊 Tổng cược: `{u[4]:,}đ`\n🌟 VIP: `{vip_name}`\n🏛 Ngân hàng: `{u[1] or 'Chưa liên kết'}`\n📊 Trạng thái: {banned_status}\n━━━━━━━━━━━━━━━━━━━━━"
    kb = []
    if is_banned(target_id):
        kb.append([InlineKeyboardButton("✅ Bỏ cấm", callback_data=f"adm_unban_{target_id}_{page}")])
    else:
        kb.append([InlineKeyboardButton("🚫 Cấm", callback_data=f"adm_ban_{target_id}_{page}")])
    kb.append([InlineKeyboardButton("🔙 Quay lại", callback_data=f"adm_page_{page}")])
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def adm_ban_unban_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if uid not in ADMIN_IDS:
        await q.answer("❌ Không có quyền!", show_alert=True)
        return
    parts = q.data.split("_")
    action = parts[1]  # "ban" or "unban"
    target_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    if action == "ban":
        query("INSERT INTO banned(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (target_id,))
        await q.answer(f"🚫 Đã cấm ID {target_id}!", show_alert=True)
    elif action == "unban":
        query("DELETE FROM banned WHERE user_id=%s", (target_id,))
        await q.answer(f"✅ Đã bỏ cấm ID {target_id}!", show_alert=True)
    # Refresh user info
    q.data = f"adm_manage_{target_id}_{page}"
    await adm_manage_user_callback(update, ctx)

# 19. NONE CALLBACK (MỚI)
async def none_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ===== HANDLE MESSAGE (MENU + CUSTOM BET) =====
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    if not txt or is_banned(uid): return
    if is_total_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ TOÀN BỘ**\n━━━━━━━━━━━━━━━━━━━━━\n🚨 Tất cả các tính năng đều tạm thời ngừng hoạt động!\n\n⏰ Vui lòng quay lại sau ít phút!\nCảm ơn bạn đã thông cảm! 🙏", parse_mode="Markdown")
        return
    if is_system_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return

    # Kiểm tra cược tự do trước
    if await handle_custom_bet_amount(update, ctx):
        return

    user_reply = update.message

    if txt == "👤 TÀI KHOẢN VIP":
        res = query("SELECT balance, bank, stk, name, refs, total_bet FROM users WHERE user_id=%s", (uid,))
        if not res:
            get_user(uid)
            u = (0, None, None, None, 0, 0)
        else:
            u = res[0]
        vip_name, _ = get_vip_info(u[5] or 0)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Lịch sử Nạp", callback_data="his_deposit"), InlineKeyboardButton("📤 Lịch sử Rút", callback_data="his_withdraw")]])
        msg = (f"👤 **THÔNG TIN TÀI KHOẢN**\n━━━━━━━━━━━━━━━━━━━━━\n🆔 ID: `{uid}`\n🌟 **Cấp VIP:** `{vip_name}`\n💰 Số dư: `{u[0]:,}đ`\n📊 **Tổng cược:** `{u[5]:,}đ`\n👥 Đã mời: `{u[4]}` người\n🏛 Ngân hàng: `{u[1] or 'Chưa liên kết'}`\n💳 STK: `{u[2] or 'Chưa liên kết'}`\n👤 Tên: `{u[3] or 'Chưa liên kết'}`\n━━━━━━━━━━━━━━━━━━━━━\n💡 *Sử dụng lệnh /lienket để cập nhật thông tin rút tiền!*")
        return await user_reply.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    if txt == "🏆 TOP ĐẠI GIA":
        return await top_cmd(update, ctx)

    if txt == "🎁 CODE TÂN THỦ":
        msg = ("🎁 **CODE TÂN THỦ** 🎁\n\n✨ **CHÀO MỪNG THÀNH VIÊN MỚI!** ✨\n\n📌 **HƯỚNG DẪN NHẬN CODE:**\n• Liên hệ CSKH để được cấp CODE TÂN THỦ\n• CODE có giá trị: `20,000đ`\n• Mỗi tài khoản chỉ nhận được 1 lần\n\n━━━━━━━━━━━━━━━━━━━━━\n📞 **CSKH1:** @sakuri0\n📞 **CSKH2:** @RoGarden\n📞 **CSKH3:** @tomm2710\n━━━━━━━━━━━━━━━━━━━━━\n\n💡 Sau khi nhận CODE, dùng lệnh: `/code [MÃ_CODE]`")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 CSKH1", url="https://t.me/sakuri0"), InlineKeyboardButton("📞 CSKH2", url="https://t.me/RoGarden"), InlineKeyboardButton("📞 CSKH3", url="https://t.me/tomm2710")]])
        return await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    if txt == "🎁 KHUYẾN MÃI NẠP":
        promo_text = get_promotion_text()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 CSKH1", url="https://t.me/sakuri0"), InlineKeyboardButton("📞 CSKH2", url="https://t.me/RoGarden"), InlineKeyboardButton("📞 CSKH3", url="https://t.me/tomm2710")]])
        return await update.message.reply_text(promo_text, reply_markup=kb, parse_mode="Markdown")

    if txt == "💳 NẠP TIỀN":
        if is_feature_banned(uid, 'nap'):
            return await user_reply.reply_text("❌ Tính năng NẠP TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
        if check_mt('mt_nap') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("⚙️ Hệ thống Nạp Tiền đang bảo trì!")
        qr_link, qr_text = get_deposit_info(uid)
        return await user_reply.reply_photo(photo=qr_link, caption=qr_text, parse_mode="Markdown")

    if txt == "🎮 DANH SÁCH GAME":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx"), InlineKeyboardButton("💿 XÓC ĐĨA", callback_data="menu_xocdia")],
            [InlineKeyboardButton("🏎️ ĐUA XE (RACE)", callback_data="menu_race"), InlineKeyboardButton("💣 Dò Mìn", callback_data="menu_mines")],
            [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")],
            [InlineKeyboardButton("🔢 QUAY SỐ (1-3)", callback_data="menu_qs"), InlineKeyboardButton("🦀 BẦU CUA TÔM CÁ", callback_data="menu_bc")],
            [InlineKeyboardButton("📉 XỔ SỐ MIỀN BẮC", callback_data="menu_xoso"), InlineKeyboardButton("🎡 VÒNG QUAY MAY MẮN", callback_data="menu_vq")],
            [InlineKeyboardButton("🎲 TÀI XỈU ROOM", callback_data="menu_taixiu_room")],
            [InlineKeyboardButton("🃏 CAO THẤP", callback_data="menu_highlow"), InlineKeyboardButton("🪵 RÚT GỖ", callback_data="menu_stick")],
            [InlineKeyboardButton("🎨 TÔ MÀU", callback_data="menu_color")]
        ])
        return await user_reply.reply_text("🎮 **DANH SÁCH TRÒ CHƠI**\nVui lòng chọn game bạn muốn chơi:", reply_markup=kb, parse_mode="Markdown")

    if txt == "🛒 RÚT TIỀN":
        if is_feature_banned(uid, 'rut'):
            return await user_reply.reply_text("❌ Tính năng RÚT TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
        res = query("SELECT bank, stk, name, balance FROM users WHERE user_id=%s", (uid,))
        if not res or not res[0][0]:
            return await user_reply.reply_text("❌ Bạn chưa liên kết tài khoản ngân hàng.\n👉 Hãy dùng lệnh: `/lienket [Ngân_hàng] [STK] [Tên]`\n📌 **MIN RÚT:** `50,000đ`", parse_mode="Markdown")
        u = res[0]
        return await user_reply.reply_text(f"💰 **Số dư:** `{u[3]:,}đ`\n📌 **MIN RÚT:** `50,000đ`\n\n📝 Nhập số tiền muốn rút: `/rut [số_tiền]`", parse_mode="Markdown")

    if txt == "📜 LỊCH SỬ":
        return await history_pro(update, ctx)

    if txt == "🎁 CHECKIN":
        return await checkin_cmd(update, ctx)

    if txt in ["📞 HỖ TRỢ CSKH1", "📞 HỖ TRỢ CSKH2", "📞 HỖ TRỢ CSKH3"]:
        contacts = {
            "📞 HỖ TRỢ CSKH1": ("CSKH1", "https://t.me/sakuri0", "@sakuri0"),
            "📞 HỖ TRỢ CSKH2": ("CSKH2", "https://t.me/RoGarden", "@RoGarden"),
            "📞 HỖ TRỢ CSKH3": ("CSKH3", "https://t.me/tomm2710", "@tomm2710"),
        }
        name, url, handle_str = contacts[txt]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"💬 Chat với {name}", url=url)]])
        return await user_reply.reply_text(f"📞 **{name}**\n\n👤 Telegram: {handle_str}\n\n💬 Bấm nút bên dưới để liên hệ hỗ trợ!", reply_markup=kb, parse_mode="Markdown")

# ===== MAIN FUNCTION =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # COMMAND HANDLERS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("checkin", checkin_cmd))
    app.add_handler(CommandHandler("lienket", lien_ket))
    app.add_handler(CommandHandler("rut", rut))
    app.add_handler(CommandHandler("code", nhap_code))
    app.add_handler(CommandHandler("history", history_pro))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("give", give_money_cmd))
    app.add_handler(CommandHandler("anon", anon_msg_cmd))
    app.add_handler(CommandHandler("khobau", khobau_cmd))
    app.add_handler(CommandHandler("caothap", play_highlow))
    app.add_handler(CommandHandler("rutgo", play_stick_game))
    app.add_handler(CommandHandler("tomau", play_color_fill))
    app.add_handler(CommandHandler("status", group_status_cmd))
    # Group bet commands
    app.add_handler(CommandHandler("t", bet_tai_group))
    app.add_handler(CommandHandler("x", bet_xiu_group))
    app.add_handler(CommandHandler("c", bet_chan_group))
    app.add_handler(CommandHandler("l", bet_le_group))

    # ADMIN COMMANDS
    app.add_handler(CommandHandler("dashboard", dashboard_cmd))
    app.add_handler(CommandHandler("tong", tong_cmd))
    app.add_handler(CommandHandler("cam", cam_cmd))
    app.add_handler(CommandHandler("bocam", bocam_cmd))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("sub", sub))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("allusers", all_user))
    app.add_handler(CommandHandler("historyall", history_all_admin))
    app.add_handler(CommandHandler("send", broadcast))
    app.add_handler(CommandHandler("rep", reply_user))
    app.add_handler(CommandHandler("check", check_user_history))
    app.add_handler(CommandHandler("info", admin_info))
    app.add_handler(CommandHandler("nap", nap_tien_admin))
    app.add_handler(CommandHandler("taocode", tao_code))
    app.add_handler(CommandHandler("setname", set_bot_name_cmd))
    app.add_handler(CommandHandler("tilewin", tilewin_cmd))
    app.add_handler(CommandHandler("tile1", tile1_user_cmd))
    app.add_handler(CommandHandler("tile1all", tile1all_cmd))
    app.add_handler(CommandHandler("tileall", tileall_cmd))
    app.add_handler(CommandHandler("tileallset", tileall_set_cmd))
    app.add_handler(CommandHandler("soduall", soduall_cmd))
    app.add_handler(CommandHandler("baotri", baotri_cmd))
    app.add_handler(CommandHandler("baotriall", baotri_hethong_cmd))
    app.add_handler(CommandHandler("baotritc", baotri_tong_cong_cmd))
    app.add_handler(CommandHandler("tatroom", tatroom_cmd))
    app.add_handler(CommandHandler("resetsdall", resetsdall_cmd))
    app.add_handler(CommandHandler("resetall", reset_all_confirm))
    app.add_handler(CommandHandler("resetbank", reset_bank))
    app.add_handler(CommandHandler("xoals", xoals_user_cmd))
    app.add_handler(CommandHandler("xoalsall", xoalsall_cmd))
    app.add_handler(CommandHandler("kmnap", kmnap_cmd))
    app.add_handler(CommandHandler("kmnapvc", kmnapvc_cmd))
    app.add_handler(CommandHandler("lsnap", lsnap_cmd))
    app.add_handler(CommandHandler("lsrut", lsrut_cmd))
    app.add_handler(CommandHandler("lsnapall", lsnapall_cmd))
    app.add_handler(CommandHandler("lsrutall", lsrutall_cmd))
    app.add_handler(CommandHandler("thongke", thongke_nap_rut_cmd))
    app.add_handler(CommandHandler("camadmin", cam_admin_cmd))
    app.add_handler(CommandHandler("unbanadmin", unban_admin_cmd))
    app.add_handler(CommandHandler("listbannedadmins", list_banned_admins_cmd))
    app.add_handler(CommandHandler("camadmin1", camadmin1_cmd))
    app.add_handler(CommandHandler("uncamadmin1", uncamadmin1_cmd))
    app.add_handler(CommandHandler("quanlyadmin", quanlyadmin_cmd))
    app.add_handler(CommandHandler("topthang", top_thang_cmd))
    app.add_handler(CommandHandler("giftall", gift_all_cmd))
    app.add_handler(CommandHandler("lockgame", lock_game_cmd))
    app.add_handler(CommandHandler("bonusvip", bonus_vip_cmd))
    app.add_handler(CommandHandler("exportdb", export_db_cmd))
    app.add_handler(CommandHandler("chinhkq", chinhkq_cmd))
    app.add_handler(CommandHandler("daban", daban_cmd))
    app.add_handler(CommandHandler("mofull", mofull_cmd))
    app.add_handler(CommandHandler("checkbank", check_bank_cmd))
    app.add_handler(CommandHandler("checktt", check_top_interaction))
    app.add_handler(CommandHandler("chart", chart_cmd))
    app.add_handler(CommandHandler("setxoso", set_xoso_result_cmd))
    app.add_handler(CommandHandler("setvongquay", set_vongquay_result_cmd))
    app.add_handler(CommandHandler("taocodeall", taocodeall_cmd))
    app.add_handler(CommandHandler("xoacode", xoacode_cmd))

    # CALLBACK HANDLERS - thứ tự từ cụ thể đến tổng quát
    app.add_handler(CallbackQueryHandler(handle_baotri_toggle, pattern="^tg_mt_"))
    app.add_handler(CallbackQueryHandler(cancel_custom_bet_callback, pattern="^cancel_custom_bet$"))
    app.add_handler(CallbackQueryHandler(close_admin_callback, pattern="^close_admin$"))
    app.add_handler(CallbackQueryHandler(none_callback, pattern="^none$"))
    app.add_handler(CallbackQueryHandler(approve_withdraw_callback, pattern="^(ok|no)_"))
    app.add_handler(CallbackQueryHandler(his_deposit_callback, pattern="^his_deposit$"))
    app.add_handler(CallbackQueryHandler(his_withdraw_callback, pattern="^his_withdraw$"))
    app.add_handler(CallbackQueryHandler(confirm_callbacks, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(bonus_callback, pattern="^(accept|reject)_bonus_"))
    app.add_handler(CallbackQueryHandler(anon_action_callback, pattern="^(reply|block)_anon_"))
    app.add_handler(CallbackQueryHandler(export_ban_list_callback, pattern="^export_ban_list$"))
    app.add_handler(CallbackQueryHandler(handle_rate_callback, pattern="^rate_(show|inc|dec)_"))
    app.add_handler(CallbackQueryHandler(game_menu_callback, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(hl_bet_callback, pattern="^hl_bet_"))
    app.add_handler(CallbackQueryHandler(highlow_choice_callback, pattern="^hl_choice_"))
    app.add_handler(CallbackQueryHandler(sg_bet_callback, pattern="^sg_bet_"))
    app.add_handler(CallbackQueryHandler(stick_pull_callback, pattern="^sg_pull_"))
    app.add_handler(CallbackQueryHandler(cf_bet_callback, pattern="^cf_bet_"))
    app.add_handler(CallbackQueryHandler(cf_fill_callback, pattern="^cf_fill_"))
    app.add_handler(CallbackQueryHandler(cf_claim_callback, pattern="^cf_claim_"))
    app.add_handler(CallbackQueryHandler(none_callback, pattern="^cf_filled$"))
    app.add_handler(CallbackQueryHandler(p_tx_bet_callback, pattern="^p_tx_bet_"))
    app.add_handler(CallbackQueryHandler(p_tx_choice_callback, pattern="^p_tx_(tai|xiu|chan|le)_"))
    app.add_handler(CallbackQueryHandler(race_callback, pattern="^race_choice"))
    app.add_handler(CallbackQueryHandler(admin_manage_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(adm_page_callback, pattern="^adm_page_"))
    app.add_handler(CallbackQueryHandler(adm_manage_user_callback, pattern="^adm_manage_"))
    app.add_handler(CallbackQueryHandler(adm_ban_unban_callback, pattern="^adm_(ban|unban)_"))

    # MESSAGE HANDLERS
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, track_interaction), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    # JOBS
    jq = app.job_queue
    jq.run_daily(bao_hiem_vip, time=__import__('datetime').time(hour=8, minute=0, tzinfo=VIETNAM_TZ))
    jq.run_daily(send_interaction_reward, time=__import__('datetime').time(hour=23, minute=59, tzinfo=VIETNAM_TZ))

    print("✅ Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
 
