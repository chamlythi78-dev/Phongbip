from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import psycopg2  
from psycopg2 import extras
from datetime import datetime, timedelta
import os
import asyncio
import random

# ===== GROUP DICE GAME MODULE (TÍCH HỢP TRỰC TIẾP) =====
# Dictionary lưu trạng thái game theo group_id
group_games = {}  # {group_id: {"status": "betting" or "rolling", "bets": {}, "message_id": int}}

# Cấu hình mặc định cho game nhóm
DEFAULT_BET_AMOUNTS = [1000, 5000, 10000, 50000, 100000, 500000]
DEFAULT_CYCLE_TIME = 60  # 60 giây cho 1 chu kỳ
DEFAULT_REMINDER_INTERVALS = [60, 40, 20, 10, 5, 4, 3, 2, 1]  # Các mốc thời gian nhắc

# ===== HÀM KIỂM TRA BẢO TRÌ HỆ THỐNG VÀ ADMIN BỊ CẤM =====
def is_system_maintenance():
    """Kiểm tra xem hệ thống có đang bảo trì không"""
    res = query("SELECT value FROM settings WHERE key='system_maintenance'")
    return res[0][0] == '1' if res else False

def is_admin_banned(admin_id):
    """Kiểm tra admin có bị cấm sử dụng lệnh không"""
    res = query("SELECT 1 FROM banned_admins WHERE admin_id=%s", (admin_id,))
    return len(res) > 0 if res else False

# Decorator kiểm tra quyền admin và bảo trì
def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Kiểm tra bảo trì hệ thống
        if is_system_maintenance() and user_id not in ADMIN_IDS:
            await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ**\n\nVui lòng quay lại sau ít phút!\nCảm ơn bạn đã thông cảm.", parse_mode="Markdown")
            return
        
        # Kiểm tra nếu là admin bị cấm
        if user_id in ADMIN_IDS and is_admin_banned(user_id):
            await update.message.reply_text("❌ Bạn đã bị cấm sử dụng các lệnh Admin!\nVui lòng liên hệ Admin cấp cao hơn.", parse_mode="Markdown")
            return
        
        # Kiểm tra nếu không phải admin
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này!")
            return
        
        return await func(update, ctx, *args, **kwargs)
    return wrapper

async def run_dice_game_cycle(bot, group_id: int, chat_id: int):
    """Chạy một chu kỳ game trong nhóm - ĐÃ SỬA: TUNG XÚC SẮC THẬT BẰNG TELEGRAM DICE"""
    while True:
        try:
            # Khởi tạo trạng thái game mới
            game_state = {
                "status": "betting",
                "bets": {},
                "message_id": None,
                "cycle_start": datetime.now()
            }
            group_games[group_id] = game_state

            # 1. Gửi tin nhắn mở cược
            bet_options_text = "\n".join([f"• {amount:,}đ - t {amount} hoặc x {amount}" for amount in DEFAULT_BET_AMOUNTS])
            start_msg = await bot.send_message(
                chat_id,
                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n"
                f"⚡ **ĐẶT CƯỢC NGAY!**\n"
                f"⏱️ Thời gian còn lại: `60s`\n\n"
                f"🎯 **CÁCH CHƠI:**\n"
                f"• Tài (11-18 điểm): `t [số_tiền]`\n"
                f"• Xỉu (3-10 điểm): `x [số_tiền]`\n\n"
                f"💰 **MỨC CƯỢC:**\n{bet_options_text}\n\n"
                f"🏆 **Tỉ lệ thưởng: x1.95**",
                parse_mode="Markdown"
            )
            game_state["message_id"] = start_msg.message_id

            # 2. Vòng lặp đếm ngược và nhắc nhở
            current_second = DEFAULT_CYCLE_TIME
            last_reminder_second = DEFAULT_CYCLE_TIME

            while current_second > 0:
                await asyncio.sleep(1)
                current_second -= 1

                if current_second in DEFAULT_REMINDER_INTERVALS and current_second != last_reminder_second:
                    last_reminder_second = current_second
                    try:
                        if current_second >= 10:
                            await bot.edit_message_text(
                                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n"
                                f"⚡ **ĐẶT CƯỢC NGAY!**\n"
                                f"⏱️ Thời gian còn lại: `{current_second}s`\n\n"
                                f"💰 Đã có `{len(game_state['bets'])}` người tham gia đặt cược.\n"
                                f"📝 Lệnh: `t [tiền]` cho TÀI, `x [tiền]` cho XỈU",
                                chat_id=chat_id,
                                message_id=game_state["message_id"],
                                parse_mode="Markdown"
                            )
                        else:
                            await bot.edit_message_text(
                                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n"
                                f"⚠️ **CHUẨN BỊ ĐÓNG CƯỢC!**\n"
                                f"⏱️ Còn `{current_second}s`...\n\n"
                                f"💰 Đã có `{len(game_state['bets'])}` người đặt cược.",
                                chat_id=chat_id,
                                message_id=game_state["message_id"],
                                parse_mode="Markdown"
                            )
                    except Exception:
                        pass

            # 3. Kết thúc đặt cược - Chuyển sang trạng thái tung xúc sắc
            game_state["status"] = "rolling"
            
            # Lưu số người chơi và tổng cược để hiển thị
            player_count = len(game_state['bets'])
            total_bet_before = sum(b["amount"] for b in game_state['bets'].values())
            
            await bot.edit_message_text(
                f"🎲 **{get_bot_name()} - TÀI XỈU 3D** 🎲\n\n"
                f"🔒 **ĐÃ KHÓA CƯỢC!**\n"
                f"👥 Số người chơi: `{player_count}`\n"
                f"💰 Tổng cược: `{total_bet_before:,}đ`\n\n"
                f"🎲 Đang tung xúc sắc...",
                chat_id=chat_id,
                message_id=game_state["message_id"],
                parse_mode="Markdown"
            )

            await asyncio.sleep(2)

            # ===== 4. TUNG XÚC SẮC THẬT BẰNG TELEGRAM DICE =====
            # Gửi 3 viên xúc sắc và lấy kết quả thật
            dice1_msg = await bot.send_dice(chat_id, emoji="🎲")
            dice2_msg = await bot.send_dice(chat_id, emoji="🎲")
            dice3_msg = await bot.send_dice(chat_id, emoji="🎲")
            
            # Đợi animation kết thúc (khoảng 4 giây)
            await asyncio.sleep(4)
            
            # Lấy kết quả thật từ dice
            dice1 = dice1_msg.dice.value
            dice2 = dice2_msg.dice.value
            dice3 = dice3_msg.dice.value
            total = dice1 + dice2 + dice3
            result = "tai" if total >= 11 else "xiu"
            result_text = "TÀI" if result == "tai" else "XỈU"

            print(f"🎲 Kết quả thật: {dice1}-{dice2}-{dice3} = {total} ({result_text})")
            print(f"👥 Số cược trong game: {len(game_state['bets'])}")

            # 5. Tính toán kết quả và cập nhật tiền
            winners = []
            losers = []
            total_bet_amount = 0

            for uid, bet_info in game_state["bets"].items():
                total_bet_amount += bet_info["amount"]
                if bet_info["choice"] == result:
                    # THẮNG: Cộng tiền thưởng (x1.95)
                    win_amount = int(bet_info["amount"] * 1.95)
                    add_money(uid, win_amount, f"Thắng Tài Xỉu nhóm: {result_text}")
                    winners.append((uid, bet_info["amount"], win_amount))
                else:
                    # THUA: Đã trừ tiền lúc đặt cược
                    losers.append((uid, bet_info["amount"]))

            # 6. Gửi kết quả cuối cùng
            result_message = (
                f"🎲 **KẾT QUẢ TÀI XỈU** 🎲\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎲 **XÚC SẮC:** `{dice1}` - `{dice2}` - `{dice3}`\n"
                f"📊 **TỔNG:** `{total}` điểm\n"
                f"🏆 **KẾT QUẢ:** **{result_text}**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 **THỐNG KÊ CƯỢC:**\n"
                f"👥 Người chơi: `{len(game_state['bets'])}`\n"
                f"💰 Tổng cược: `{total_bet_amount:,}đ`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )

            if winners:
                result_message += f"🎉 **NGƯỜI THẮNG ({len(winners)}):**\n"
                for uid, bet, win in winners[:10]:
                    result_message += f"  👤 ID `{uid}`: cược `{bet:,}đ` → nhận `{win:,}đ`\n"
                if len(winners) > 10:
                    result_message += f"  ... và {len(winners) - 10} người khác\n"

            if losers:
                result_message += f"\n💀 **NGƯỜI THUA ({len(losers)}):**\n"
                for uid, bet in losers[:10]:
                    result_message += f"  👤 ID `{uid}`: thua `{bet:,}đ`\n"
                if len(losers) > 10:
                    result_message += f"  ... và {len(losers) - 10} người khác\n"

            result_message += f"\n⏱️ Ván tiếp theo sau `{DEFAULT_CYCLE_TIME}s`..."
            
            await bot.edit_message_text(
                result_message,
                chat_id=chat_id,
                message_id=game_state["message_id"],
                parse_mode="Markdown"
            )

            # 7. Reset game state và chờ chu kỳ tiếp theo
            group_games.pop(group_id, None)
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ Lỗi trong chu kỳ game của nhóm {group_id}: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(10)

async def place_bet_in_group(bot, user_id: int, group_id: int, choice: str, amount: int, username: str = ""):
    """Xử lý đặt cược của người dùng trong game nhóm"""
    game = group_games.get(group_id)
    if not game or game["status"] != "betting":
        return False, "❌ Hiện tại không có phiên cược nào đang mở! Vui lòng chờ ván tiếp theo."

    balance = get_balance(user_id)
    if balance < amount:
        return False, f"❌ Số dư không đủ! Bạn cần `{amount:,}đ` nhưng chỉ có `{balance:,}đ`."

    if user_id in game["bets"]:
        return False, "❌ Bạn đã đặt cược trong ván này rồi! Hãy chờ ván tiếp theo."

    # Trừ tiền ngay lập tức
    note = f"Cược {choice.upper()} nhóm - {amount:,}đ"
    if not sub_money(user_id, amount, note):
        return False, "❌ Có lỗi xảy ra khi trừ tiền, vui lòng thử lại!"

    game["bets"][user_id] = {
        "amount": amount,
        "choice": choice,
        "username": username
    }

    return True, f"✅ **ĐẶT CƯỢC THÀNH CÔNG!**\n🎲 Cửa: `{choice.upper()}`\n💰 Số tiền: `{amount:,}đ`"

def get_group_game_status(group_id: int):
    """Lấy trạng thái game hiện tại của nhóm"""
    game = group_games.get(group_id)
    if not game:
        return None
    return game["status"]

# ===== HÀM TẠO MÃ NGẪU NHIÊN =====
def gen_code():
    return ''.join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [8619503816,5260138362]
BOT_USERNAME = "zen88uytins1bot" 
MIN_WITHDRAW = 200000 
LOG_GROUP_ID = -1003663678808

# THÔNG TIN NẠP TIỀN
BANK_ID = "MB"
ACCOUNT_NO = "0003456712345"
ACCOUNT_NAME = "LY THI CHAM"

def get_deposit_info(user_id):
    qr_url = f"https://img.vietqr.io/image/{BANK_ID}-{ACCOUNT_NO}-qr_only.png?amount=0&addInfo={user_id}&accountName={ACCOUNT_NAME}"
    caption = (
        "**🏦 THÔNG TIN NẠP TIỀN**\n\n"
        f"🏦 Ngân hàng: **MBBANK**\n"
        f"👤 CTK: **{ACCOUNT_NAME}**\n"
        f"💳 STK: `{ACCOUNT_NO}`\n"
        f"📝 Nội dung: `{user_id}`\n\n"
        "⚠️ *Lưu ý: Quét mã QR để tự động điền nội dung. Hệ thống cộng tiền sau 1-3 phút.*"
    )
    return qr_url, caption
    
# ===== DATABASE SETUP (POSTGRESQL) =====
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
query("CREATE TABLE IF NOT EXISTS banned_games (user_id BIGINT, game_id INTEGER, PRIMARY KEY (user_id, game_id))")
query("CREATE TABLE IF NOT EXISTS banned_features (user_id BIGINT, feature TEXT, PRIMARY KEY (user_id, feature))")

# Thêm bảng lưu admin bị cấm
query("CREATE TABLE IF NOT EXISTS banned_admins (admin_id BIGINT PRIMARY KEY, banned_by BIGINT, reason TEXT, banned_at TEXT)")

# Sửa lại danh sách game chuẩn ID 1-10
default_game_names = [
    "TÀI XỈU", "XÓC ĐĨA", "ĐUA XE", "DÒ MÌN", 
    "PENALTY", "GÕ MÕ", "QUAY SỐ", "BẦU CUA", "XỔ SỐ", "VÒNG QUAY MAY MẮN"
]

for i, name in enumerate(default_game_names, 1):
    res = query("SELECT 1 FROM game_rates WHERE id=%s", (i,))
    if not res:
        query("INSERT INTO game_rates VALUES(%s, %s, 10)", (i, name))
    else:
        query("UPDATE game_rates SET name=%s WHERE id=%s", (name, i))

try: query("ALTER TABLE users ADD COLUMN total_bet BIGINT DEFAULT 0")
except: pass
try: query("ALTER TABLE users ADD COLUMN rate_bonus INTEGER DEFAULT NULL")
except: pass

query("CREATE TABLE IF NOT EXISTS history (user_id BIGINT, amount BIGINT, note TEXT, time TEXT)")
query("CREATE TABLE IF NOT EXISTS banned (user_id BIGINT PRIMARY KEY)")
query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

maintenance_keys = [
    'mt_taixiu', 'mt_duaxe', 'mt_domin', 
    'mt_penalty', 'mt_gomo', 'mt_nap', 'mt_rut', 
    'mt_xocdia', 'mt_quayso', 'mt_baucua', 'mt_xoso', 'mt_vongquay'
]
for k in maintenance_keys:
    res = query("SELECT 1 FROM settings WHERE key=%s", (k,))
    if not res:
        query("INSERT INTO settings VALUES(%s, '0')", (k,))

res_name = query("SELECT 1 FROM settings WHERE key='bot_display_name'")
if not res_name:
    query("INSERT INTO settings VALUES('bot_display_name', 'Hệ thống Game Uy Tín')")

# Thêm setting bảo trì toàn hệ thống
res_system_mt = query("SELECT 1 FROM settings WHERE key='system_maintenance'")
if not res_system_mt:
    query("INSERT INTO settings VALUES('system_maintenance', '0')")

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
    if note != "Rút tiền" and note != "withdraw" and "Admin" not in note and "Chuyển tiền" not in note:
        query("UPDATE users SET total_bet=total_bet+%s WHERE user_id=%s", (amt, uid))
    return True

# ===== ADMIN COMMANDS =====
@admin_only
async def dashboard_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%d/%m/%Y")
    this_month = datetime.now().strftime("/%m/%Y")
    
    nap_today = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note ILIKE '%nạp%' AND time LIKE %s", (f"%{today}%",))[0][0] or 0
    rut_today = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note ILIKE '%Rút%' AND time LIKE %s", (f"%{today}%",))[0][0] or 0
    nap_month = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note ILIKE '%nạp%' AND time LIKE %s", (f"%{this_month}%",))[0][0] or 0
    rut_month = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note ILIKE '%Rút%' AND time LIKE %s", (f"%{this_month}%",))[0][0] or 0
    total_cuoc = query("SELECT SUM(amount) FROM history WHERE amount < 0 AND note NOT ILIKE '%Rút%' AND note NOT ILIKE '%trừ tiền%'")[0][0] or 0
    total_thang = query("SELECT SUM(amount) FROM history WHERE amount > 0 AND note NOT ILIKE '%nạp%' AND note NOT ILIKE '%Code%' AND note NOT ILIKE '%Checkin%'")[0][0] or 0
    loi_nhuan = abs(total_cuoc) - total_thang
    
    msg = (f"📊 **BẢNG THỐNG KÊ DOANH THU**\n━━━━━━━━━━━━━━━━━━━━━\n"
           f"📅 **Hôm nay ({today}):**\n  📥 Tổng nạp: `+{nap_today:,}đ`\n  📤 Tổng rút: `{rut_today:,}đ`\n\n"
           f"📅 **Tháng này ({datetime.now().month}):**\n  📥 Tổng nạp: `+{nap_month:,}đ`\n  📤 Tổng rút: `{rut_month:,}đ`\n\n"
           f"📈 **Tổng kết Game (All time):**\n  💰 Lợi nhuận ròng: `{loi_nhuan:,}đ`\n━━━━━━━━━━━━━━━━━━━━━")
    await update.message.reply_text(msg, parse_mode="Markdown")

async def bao_hiem_vip(context: ContextTypes.DEFAULT_TYPE):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    users = query("SELECT user_id, SUM(amount) FROM history WHERE time LIKE %s GROUP BY user_id", (f"%{yesterday}%",))
    for u_id, total in users:
        if total < -1000000:
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
    msg = (f"📈 **TỔNG QUAN TÀI CHÍNH HỆ THỐNG**\n"
           f"━━━━━━━━━━━━━━━━━━━━━\n"
           f"📥 **Tổng Nạp:** `+{t_nap:,}đ`\n"
           f"📤 **Tổng Rút:** `{t_rut:,}đ`\n"
           f"💰 **Lợi Nhuận Thực Tế (Game):** `{loi_nhuan:,}đ`\n"
           f"━━━━━━━━━━━━━━━━━━━━━")
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

async def top_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = query("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    text = "🏆 **TOP 10 ĐẠI GIA GIÀU NHẤT**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(users, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        text += f"{medal} ID: `{u[0]}` — `{u[1]:,}đ`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

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
    if not ctx.args:
        return await update.message.reply_text("❌ Cú pháp: `/tileall [số]`")
    try:
        new_rate = int(ctx.args[0])
        query("UPDATE game_rates SET rate = %s", (new_rate,))
        await update.message.reply_text(f"✅ Đã chỉnh tất cả game về tỉ lệ thắng: `{new_rate}%`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Tỉ lệ phải là số nguyên.")

@admin_only
async def tile1_user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.message.reply_text("❌ Cú pháp: `/tile1 [ID] [Tỉ_lệ]`\nVD: `/tile1 123456 10` (Chỉnh ID 123456 thắng 10%)")
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
    if not users:
        return await update.message.reply_text("Hiện không có ai có số dư lớn hơn 0.")
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
    if not ctx.args:
        return await update.message.reply_text("❌ Cú pháp: `/xoals [ID]`")
    try:
        uid = int(ctx.args[0])
        query("DELETE FROM history WHERE user_id=%s", (uid,))
        await update.message.reply_text(f"✅ Đã xoá sạch lịch sử của người dùng: `{uid}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ ID không hợp lệ.")

# ===== QUẢN LÝ ADMIN =====
async def cam_admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cấm admin khác sử dụng lệnh - /camadmin [id] [lý do]"""
    user_id = update.effective_user.id
    
    # Chỉ admin đầu tiên (8619503816) mới có quyền cấm admin khác
    if user_id != 8619503816:
        await update.message.reply_text("❌ Chỉ Admin chính (ID: 8619503816) mới có quyền sử dụng lệnh này!")
        return
    
    if len(ctx.args) < 1:
        await update.message.reply_text("❌ Cú pháp: `/camadmin [ID_admin] [lý do]`\nVD: `/camadmin 5260138362 Lạm dụng quyền hạn`", parse_mode="Markdown")
        return
    
    try:
        target_admin = int(ctx.args[0])
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "Không có lý do"
        
        if target_admin == user_id:
            await update.message.reply_text("❌ Bạn không thể tự cấm chính mình!")
            return
        
        if target_admin not in ADMIN_IDS:
            await update.message.reply_text(f"❌ ID `{target_admin}` không phải là Admin của bot!", parse_mode="Markdown")
            return
        
        now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
        query("INSERT INTO banned_admins VALUES(%s, %s, %s, %s) ON CONFLICT (admin_id) DO UPDATE SET banned_by=%s, reason=%s, banned_at=%s", 
              (target_admin, user_id, reason, now_str, user_id, reason, now_str))
        
        await update.message.reply_text(
            f"✅ **ĐÃ CẤM ADMIN**\n\n"
            f"👤 ID: `{target_admin}`\n"
            f"📝 Lý do: {reason}\n"
            f"⏰ Thời gian: {now_str}\n\n"
            f"Admin này sẽ không thể sử dụng bất kỳ lệnh Admin nào!",
            parse_mode="Markdown"
        )
        
        # Gửi thông báo cho admin bị cấm
        try:
            await ctx.bot.send_message(
                target_admin,
                f"⚠️ **THÔNG BÁO**\n\n"
                f"Bạn đã bị cấm sử dụng các lệnh Admin.\n"
                f"📝 Lý do: {reason}\n"
                f"🕐 Thời gian: {now_str}\n\n"
                f"Liên hệ Admin chính để được gỡ cấm."
            )
        except:
            pass
            
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def unban_admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gỡ cấm admin - /unbanadmin [id]"""
    user_id = update.effective_user.id
    
    if user_id != 8619503816:
        await update.message.reply_text("❌ Chỉ Admin chính (ID: 8619503816) mới có quyền sử dụng lệnh này!")
        return
    
    if len(ctx.args) < 1:
        await update.message.reply_text("❌ Cú pháp: `/unbanadmin [ID_admin]`", parse_mode="Markdown")
        return
    
    try:
        target_admin = int(ctx.args[0])
        
        if not is_admin_banned(target_admin):
            await update.message.reply_text(f"❌ Admin `{target_admin}` không bị cấm!", parse_mode="Markdown")
            return
        
        query("DELETE FROM banned_admins WHERE admin_id=%s", (target_admin,))
        await update.message.reply_text(f"✅ Đã gỡ cấm cho Admin `{target_admin}`", parse_mode="Markdown")
        
        try:
            await ctx.bot.send_message(target_admin, "✅ Bạn đã được gỡ cấm và có thể sử dụng lại các lệnh Admin!")
        except:
            pass
            
    except ValueError:
        await update.message.reply_text("❌ ID không hợp lệ!")

async def list_banned_admins_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Danh sách admin bị cấm - /listbannedadmins"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này!")
        return
    
    banned_list = query("SELECT admin_id, banned_by, reason, banned_at FROM banned_admins")
    
    if not banned_list:
        await update.message.reply_text("📋 Hiện không có Admin nào bị cấm.", parse_mode="Markdown")
        return
    
    msg = "🚫 **DANH SÁCH ADMIN BỊ CẤM**\n━━━━━━━━━━━━━━━━━━━━━\n"
    for admin_id, banned_by, reason, banned_at in banned_list:
        msg += f"\n👤 ID: `{admin_id}`\n"
        msg += f"👮 Bởi: `{banned_by}`\n"
        msg += f"📝 Lý do: {reason}\n"
        msg += f"⏰ Lúc: {banned_at}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# ===== BẢO TRÌ TOÀN HỆ THỐNG =====
async def baotri_hethong_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bảo trì toàn bộ bot - /baotrihethong [on/off]"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này!")
        return
    
    if len(ctx.args) < 1:
        current_status = "🔴 ĐANG BẢO TRÌ" if is_system_maintenance() else "🟢 HOẠT ĐỘNG"
        await update.message.reply_text(
            f"🛠 **TRẠNG THÁI HỆ THỐNG**\n\n"
            f"📊 Hiện tại: {current_status}\n\n"
            f"📝 Cú pháp:\n"
            f"• Bật bảo trì: `/baotrihethong on`\n"
            f"• Tắt bảo trì: `/baotrihethong off`",
            parse_mode="Markdown"
        )
        return
    
    action = ctx.args[0].lower()
    
    if action == "on":
        query("UPDATE settings SET value='1' WHERE key='system_maintenance'")
        
        # Gửi thông báo cho tất cả người dùng
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(
                    user[0],
                    "🔧 **THÔNG BÁO BẢO TRÌ**\n\n"
                    "Hệ thống đang được nâng cấp và bảo trì.\n"
                    "Bot sẽ tạm thời ngừng hoạt động.\n\n"
                    "⏰ Vui lòng quay lại sau ít phút!\n"
                    "Cảm ơn bạn đã thông cảm.",
                    parse_mode="Markdown"
                )
                sent_count += 1
                await asyncio.sleep(0.5)
            except:
                pass
        
        await update.message.reply_text(
            f"🔧 **ĐÃ BẬT BẢO TRÌ TOÀN HỆ THỐNG**\n\n"
            f"✅ Đã gửi thông báo đến {sent_count} người dùng.\n"
            f"⚠️ Bot sẽ từ chối mọi yêu cầu cho đến khi tắt bảo trì.",
            parse_mode="Markdown"
        )
        
    elif action == "off":
        query("UPDATE settings SET value='0' WHERE key='system_maintenance'")
        
        # Gửi thông báo cho tất cả người dùng
        users = query("SELECT user_id FROM users")
        sent_count = 0
        for user in users:
            try:
                await ctx.bot.send_message(
                    user[0],
                    "✅ **HỆ THỐNG ĐÃ TRỞ LẠI**\n\n"
                    "Quá trình bảo trì đã hoàn tất!\n"
                    "Bot đã sẵn sàng hoạt động trở lại.\n\n"
                    "🎮 Chúc bạn chơi game vui vẻ!",
                    parse_mode="Markdown"
                )
                sent_count += 1
                await asyncio.sleep(0.5)
            except:
                pass
        
        await update.message.reply_text(
            f"✅ **ĐÃ TẮT BẢO TRÌ TOÀN HỆ THỐNG**\n\n"
            f"✅ Đã gửi thông báo đến {sent_count} người dùng.\n"
            f"🎮 Bot đã hoạt động trở lại.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Sai cú pháp! Dùng `on` hoặc `off`", parse_mode="Markdown")

# ===== LOGIC GAMES ANIMATION =====
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
    is_win = check_win_by_id(1, uid)
    win = False
    if is_win:
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

@admin_only
async def tilewin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        game_id = int(ctx.args[0])
        new_rate = int(ctx.args[1])
        if not (0 <= new_rate <= 100):
            return await update.message.reply_text("❌ Tỉ lệ thắng phải từ 0% đến 100%!")
        query("UPDATE game_rates SET rate=%s WHERE id=%s", (new_rate, game_id))
        res = query("SELECT name FROM game_rates WHERE id=%s", (game_id,))
        game_name = res[0][0] if res else "Không xác định"
        await update.message.reply_text(
            f"✅ **CẬP NHẬT TỈ LỆ THÀNH CÔNG**\n\n"
            f"🎮 Game: `{game_id} - {game_name}`\n"
            f"📈 Tỉ lệ thắng mới: `{new_rate}%`", 
            parse_mode="Markdown"
        )
    except:
        msg = (
            "⚠️ **HƯỚNG DẪN CHỈNH TỈ LỆ**\n"
            "Cú pháp: `/tilewin [Số_ID] [Tỉ_lệ]`\n\n"
            "1. TÀI XỈU | 2. XÓC ĐĨA | 3. ĐUA XE | 4. DÒ MÌN\n"
            "5. PENALTY | 6. GÕ MÕ | 7. QUAY SỐ | 8. BẦU CUA\n"
            "9. XỔ SỐ | 10. VÒNG QUAY MAY MẮN\n\n"
            "VD: `/tilewin 1 50` (Chỉnh Tài Xỉu thắng 50%)"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

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
        [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"), 
         InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
        [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
    ]
    await update.message.reply_text("🛠 **BẢNG QUẢN LÝ BẢO TRÌ**\n(Bấm để chuyển trạng thái On/Off)", 
                                   reply_markup=InlineKeyboardMarkup(kb))

@admin_only
async def nap_tien_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        add_money(target_id, amount, f"Admin nạp tiền")
        await ctx.bot.send_message(chat_id=LOG_GROUP_ID, text=f"✅ **THÔNG BÁO NẠP TIỀN**\n👤 ID: `{target_id}`\n💰 Số tiền: `+{amount:,}đ`\n────────────────\nChúc bạn chơi game vui vẻ!")
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

@admin_only
async def reset_all_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ XÁC NHẬN XÓA TẤT CẢ", callback_data="confirm_reset_all_final")],
        [InlineKeyboardButton("❌ HỦY THAO TÁC", callback_data="close_admin")]
    ])
    await update.message.reply_text(
        "⚠️ **CẢNH BẢO NGUY HIỂM** ⚠️\n\n"
        "Thao tác này sẽ xóa sạch dữ liệu các bảng: **Users, History, Codes, Banned**.\n"
        "Mọi thông tin số dư và lịch sử sẽ biến mất vĩnh viễn.\n\n"
        "Bạn có chắc chắn muốn thực hiện?", reply_markup=kb, parse_mode="Markdown")

@admin_only
async def reset_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(ctx.args[0])
        query("UPDATE users SET bank=NULL, stk=NULL, name=NULL WHERE user_id=%s", (target_id,))
        await update.message.reply_text(f"✅ Đã reset bank cho ID `{target_id}`. User có thể dùng /lienket lại.")
        await ctx.bot.send_message(chat_id=target_id, text="🔔 Admin đã reset thông tin ngân hàng của bạn. Bạn có thể liên kết lại ngay bây giờ.")
    except:
        await update.message.reply_text("❌ Cú pháp: `/resetbank [ID]`")

@admin_only
async def admin_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

@admin_only
async def history_all_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

@admin_only
async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

# ===== GROUP GAME COMMANDS (LỆNH MỚI CHO NHÓM) =====
async def bet_tai_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Đặt cược TÀI trong nhóm - lệnh /t [số_tiền]"""
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
        await update.message.reply_text(
            f"❌ Vui lòng nhập số tiền cược!\n"
            f"Cú pháp: `t [số_tiền]`\n"
            f"Các mức cược hợp lệ: {', '.join([str(a) for a in DEFAULT_BET_AMOUNTS])}đ",
            parse_mode="Markdown"
        )
        return
    try:
        amount = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Số tiền không hợp lệ!")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "tai", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def bet_xiu_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Đặt cược XỈU trong nhóm - lệnh /x [số_tiền]"""
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
        await update.message.reply_text(
            f"❌ Vui lòng nhập số tiền cược!\n"
            f"Cú pháp: `x [số_tiền]`\n"
            f"Các mức cược hợp lệ: {', '.join([str(a) for a in DEFAULT_BET_AMOUNTS])}đ",
            parse_mode="Markdown"
        )
        return
    try:
        amount = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Số tiền không hợp lệ!")
        return
    success, message = await place_bet_in_group(ctx.bot, user_id, group_id, "xiu", amount, username)
    await update.message.reply_text(message, parse_mode="Markdown")

async def group_status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Kiểm tra trạng thái game trong nhóm"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Lệnh này chỉ sử dụng được trong NHÓM!")
        return
    group_id = update.effective_chat.id
    status = get_group_game_status(group_id)
    if status == "betting":
        await update.message.reply_text("🎲 **ĐANG MỞ CƯỢC!**\nHãy đặt cược ngay: `t [tiền]` cho TÀI, `x [tiền]` cho XỈU", parse_mode="Markdown")
    elif status == "rolling":
        await update.message.reply_text("🎲 **ĐANG TUNG XÚC SẮC!**\nVui lòng chờ kết quả...", parse_mode="Markdown")
    else:
        await update.message.reply_text("⏸️ **CHƯA CÓ PHIÊN CƯỢC NÀO**\nVán mới sẽ bắt đầu sau vài giây...", parse_mode="Markdown")

# ===== START & REF SYSTEM =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    
    # Kiểm tra bảo trì hệ thống
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
        ["🎮 Danh sách game", "👤 Tài khoản"],
        ["💳 Nạp tiền", "🛒 Rút tiền"],
        ["🎁 Checkin", "🎁 Nhận Code Free"],
        ["📜 Lịch sử", "🏆 Top Đại Gia"],
        ["📞 Hỗ trợ"]
    ], resize_keyboard=True)
    welcome_text = (
        f"👋 **CHÀO MỪNG {update.effective_user.first_name.upper()} ĐÃ THAM GIA!**\n\n"
        f"🛡 **{get_bot_name()}**\n"
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

async def rut(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if is_feature_banned(uid, 'rut'):
        return await update.message.reply_text("❌ Tính năng RÚT TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
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
    
    # Kiểm tra bảo trì hệ thống
    if is_system_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 **HỆ THỐNG ĐANG BẢO TRÌ**\n\nVui lòng quay lại sau ít phút!", parse_mode="Markdown")
        return
    
    user_reply = update.message
    parts = txt.split()

    if txt == "👤 Tài khoản":
        res = query("SELECT balance, bank, stk, name, refs, total_bet FROM users WHERE user_id=%s", (uid,))
        if not res: 
            get_user(uid)
            u = (0, None, None, None, 0, 0)
        else:
            u = res[0]
        vip_name, _ = get_vip_info(u[5])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Lịch sử Nạp", callback_data="his_deposit"),
             InlineKeyboardButton("📤 Lịch sử Rút", callback_data="his_withdraw")]
        ])
        msg = (
            f"👤 **THÔNG TIN TÀI KHOẢN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{uid}`\n"
            f"🌟 **Cấp VIP:** `{vip_name}`\n"
            f"💰 Số dư: `{u[0]:,}đ`\n"
            f"📊 **Tổng cược:** `{u[5]:,}đ`\n"
            f"👥 Đã mời: `{u[4]}` người\n"
            f"🏛 Ngân hàng: `{u[1] or 'Chưa liên kết'}`\n"
            f"💳 STK: `{u[2] or 'Chưa liên kết'}`\n"
            f"👤 Tên: `{u[3] or 'Chưa liên kết'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Sử dụng lệnh /lienket để cập nhật thông tin rút tiền!*"
        )
        return await user_reply.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    if txt == "🏆 Top Đại Gia":
        return await top_cmd(update, ctx)

    if txt == "🎁 Nhận Code Free":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 THAM GIA NHÓM NHẬN CODE", url="https://t.me/sunwin988")],
            [InlineKeyboardButton("📢 KÊNH THÔNG BÁO", url="https://t.me/sunwin988")]
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
        if is_feature_banned(uid, 'nap'):
            return await user_reply.reply_text("❌ Tính năng NẠP TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
        if check_mt('mt_nap') and uid not in ADMIN_IDS:
            return await user_reply.reply_text("⚙️ Hệ thống Nạp Tiền đang bảo trì!")
        qr_link, qr_text = get_deposit_info(uid)    
        return await user_reply.reply_photo(photo=qr_link, caption=qr_text, parse_mode="Markdown")

    if txt == "🎮 Danh sách game":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 TÀI XỈU 3D", callback_data="menu_tx"), InlineKeyboardButton("💿 XÓC ĐĨA", callback_data="menu_xocdia")],
            [InlineKeyboardButton("🏎️ ĐUA XE (RACE)", callback_data="menu_race"), 
             InlineKeyboardButton("💣 Dò Mìn", callback_data="menu_mines")],
            [InlineKeyboardButton("⚽️ PENALTY", callback_data="menu_ball"), 
             InlineKeyboardButton("🪵 GÕ MÕ", callback_data="menu_wooden")],
            [InlineKeyboardButton("🔢 QUAY SỐ (1-3)", callback_data="menu_qs"),
             InlineKeyboardButton("🦀 BẦU CUA TÔM CÁ", callback_data="menu_bc")],
            [InlineKeyboardButton("📉 XỔ SỐ MIỀN BẮC", callback_data="menu_xoso"),
             InlineKeyboardButton("🎡 VÒNG QUAY MAY MẮN", callback_data="menu_vq")]
        ])
        return await user_reply.reply_text("🎮 **DANH SÁCH TRÒ CHƠI**\nVui lòng chọn game bạn muốn chơi:", reply_markup=kb, parse_mode="Markdown")

    if txt == "🛒 Rút tiền":
        if is_feature_banned(uid, 'rut'):
            return await user_reply.reply_text("❌ Tính năng RÚT TIỀN của bạn đã bị khóa. Vui lòng liên hệ Admin!")
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
        res = query("SELECT last_checkin, total_bet FROM users WHERE user_id=%s", (uid,))
        if res and res[0][0] == today:
            await user_reply.reply_text("❌ Hôm nay bạn đã điểm danh rồi!")
            return
        _, bonus = get_vip_info(res[0][1] if res else 0)
        add_money(uid, bonus, "Daily Checkin") 
        query("UPDATE users SET last_checkin=%s WHERE user_id=%s", (today, uid))
        return await user_reply.reply_text(f"🎉 **CHECKIN THÀNH CÔNG!**\n\nBạn nhận được: `+{bonus:,}đ` (Theo cấp VIP)", parse_mode="Markdown")

    if txt == "📜 Lịch sử":
        return await history_pro(update, ctx)

    if txt == "📞 Hỗ trợ":
        return await user_reply.reply_text("HỖ TRỢ NHANH @RoGarden")


    if len(parts) == 2 and parts[1].isdigit():
        code, amt = parts[0].upper(), int(parts[1])
        if code in ["XXC", "XXL", "XXX", "XXT"]:
            if check_mt('mt_taixiu') and uid not in ADMIN_IDS:
                return await update.message.reply_text("⚙️ Game Tài Xỉu đang bảo trì!")
            return await play_dice_animation(update, code, amt)

    if uid not in ADMIN_IDS:
        for aid in ADMIN_IDS:
            try: await ctx.bot.send_message(chat_id=aid, text=f"📨 **TIN NHẮN HỖ TRỢ**\n👤 ID: `{uid}`\n📝 Nội dung: {txt}", parse_mode="Markdown")
            except: pass
        await user_reply.reply_text("✅ Đã gửi yêu cầu tới Admin!")

# ===== XỬ LÝ TIN NHẮN NHÓM (LỆNH KHÔNG DẤU /) =====
async def handle_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý tin nhắn trong nhóm để bắt lệnh không dấu / như 't 10000'"""
    # Chỉ xử lý trong nhóm
    if update.effective_chat.type == "private":
        await main_handler(update, ctx)
        return
    
    text = update.message.text
    if not text:
        return
    
    parts = text.strip().split()
    if not parts:
        return
    
    command = parts[0].lower()
    
    # Xử lý lệnh t (Tài)
    if command == "t" and len(parts) >= 2:
        try:
            amount = int(parts[1])
            # Tạo args giả lập
            class FakeArgs:
                def __init__(self, args_list):
                    self.args = args_list
            fake_ctx = type('obj', (object,), {
                'bot': ctx.bot, 
                'args': [str(amount)],
                'user_data': ctx.user_data,
                'chat_data': ctx.chat_data
            })()
            await bet_tai_group(update, fake_ctx)
        except ValueError:
            await update.message.reply_text("❌ Số tiền không hợp lệ!")
        return
    
    # Xử lý lệnh x (Xỉu)
    if command == "x" and len(parts) >= 2:
        try:
            amount = int(parts[1])
            fake_ctx = type('obj', (object,), {
                'bot': ctx.bot, 
                'args': [str(amount)],
                'user_data': ctx.user_data,
                'chat_data': ctx.chat_data
            })()
            await bet_xiu_group(update, fake_ctx)
        except ValueError:
            await update.message.reply_text("❌ Số tiền không hợp lệ!")
        return
    
    # Không phải lệnh t/x thì xử lý bình thường
    await main_handler(update, ctx)

# ===== CALLBACK HANDLER =====
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id
    
    if d == "confirm_reset_all_final":
        if uid not in ADMIN_IDS: return
        query("TRUNCATE users, history, codes, banned RESTART IDENTITY CASCADE")
        return await q.edit_message_text("✅ **HỆ THỐNG ĐÃ ĐƯỢC RESET SẠCH DỮ LIỆU!**")

    elif d == "his_deposit":
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s AND amount > 0 ORDER BY time DESC LIMIT 10", (uid,))
        text = "📥 **10 GIAO DỊCH NẠP GẦN NHẤT:**\n\n"
        if not data: text += "Trống."
        else:
            for row in data: text += f"✅ `+{row[0]:,}đ` | {row[1]} | _{row[2]}_\n"
        return await ctx.bot.send_message(uid, text, parse_mode="Markdown")

    elif d == "his_withdraw":
        data = query("SELECT amount, note, time FROM history WHERE user_id=%s AND (note ILIKE '%%Rút%%' OR amount < 0) ORDER BY time DESC LIMIT 10", (uid,))
        text = "📤 **10 GIAO DỊCH RÚT/CƯỢC GẦN NHẤT:**\n\n"
        if not data: text += "Trống."
        else:
            for row in data: text += f"🔻 `{abs(row[0]):,}đ` | {row[1]} | _{row[2]}_\n"
        return await ctx.bot.send_message(uid, text, parse_mode="Markdown")

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
            f"🏛 Bank: `{u[2] or 'Chưa'}` | `{u[3] or ''}`\n"
            f"🚦 Trạng thái: **{status_text}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = [
            [InlineKeyboardButton("🚫 BAN", callback_data=f"adm_act_ban_{target_id}_{current_page}"), 
             InlineKeyboardButton("✅ UNBAN", callback_data=f"adm_act_unban_{target_id}_{current_page}")],
            [InlineKeyboardButton("➕ 0k", callback_data=f"adm_act_add_{target_id}_0_{current_page}"), 
             InlineKeyboardButton("➖ 0k", callback_data=f"adm_act_sub_{target_id}_0_{current_page}")],
            [InlineKeyboardButton("🔙 QUAY LẠI TRANG {0}".format(current_page+1), callback_data=f"adm_page_{current_page}")]
        ]
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("adm_act_"):
        if uid not in ADMIN_IDS: return
        parts = d.split("_")
        act = parts[2]
        tid = int(parts[3])
        page_to_return = int(parts[-1])
        if act == "ban": query("INSERT INTO banned VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (tid,))
        elif act == "unban": query("DELETE FROM banned WHERE user_id=%s", (tid,))
        elif act == "add": add_money(tid, int(parts[4]), "Admin cộng tiền")
        elif act == "sub": sub_money(tid, int(parts[4]), "Admin trừ tiền")
        await q.answer("Thành công!")
        res = query("SELECT balance, refs, bank, stk, name, last_checkin, total_bet FROM users WHERE user_id=%s", (tid,))
        u = res[0]
        status_text = "🚫 ĐANG CHẶN" if is_banned(tid) else "🟢 HOẠT ĐỘNG"
        msg = (f"👤 **QUẢN LÝ USER:** `{tid}`\n━━━━━━━━━━━━━━━━━━━━━\n💰 Số dư: `{u[0]:,}đ`\n📊 Tổng cược: `{u[6]:,}đ`\n🏛 Bank: `{u[2] or 'Chưa'}` | `{u[3] or ''}`\n🚦 Trạng thái: **{status_text}**\n━━━━━━━━━━━━━━━━━━━━━")
        kb = [[InlineKeyboardButton("🚫 BAN", callback_data=f"adm_act_ban_{tid}_{page_to_return}"), InlineKeyboardButton("✅ UNBAN", callback_data=f"adm_act_unban_{tid}_{page_to_return}")],
              [InlineKeyboardButton("➕ 0k", callback_data=f"adm_act_add_{tid}_0_{page_to_return}"), InlineKeyboardButton("➖ 0k", callback_data=f"adm_act_sub_{tid}_0_{page_to_return}")],
              [InlineKeyboardButton("🔙 QUAY LẠI TRANG {0}".format(page_to_return+1), callback_data=f"adm_page_{page_to_return}")]]
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("tg_mt_"):
        if uid not in ADMIN_IDS:
            await q.answer("Bạn không có quyền!")
            return
        key = d.replace("tg_", "")
        new_val = "0" if check_mt(key) else "1"
        query("UPDATE settings SET value=%s WHERE key=%s", (new_val, key))
        await q.answer("✅ Đã cập nhật trạng thái!")
        # Refresh lại menu
        def st(k): 
            return "🔴 OFF" if check_mt(k) else "🟢 ON"
        new_kb = [
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
            [InlineKeyboardButton(f"💳 Nạp Tiền: {st('mt_nap')}", callback_data="tg_mt_nap"), 
             InlineKeyboardButton(f"🛒 Rút Tiền: {st('mt_rut')}", callback_data="tg_mt_rut")],
            [InlineKeyboardButton("❌ ĐÓNG BẢNG", callback_data="close_admin")]
        ]
        try:
            await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
        except:
            pass
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
            await ctx.bot.send_message(chat_id=LOG_GROUP_ID, text=f"📤 **THÔNG BÁO RÚT TIỀN**\n👤 ID: `{u_id}`\n💰 Số tiền: `{amt:,}đ`\n────────────────\n✅ Giao dịch đã được duyệt thành công!")
            await ctx.bot.send_message(u_id, f"✅ Yêu cầu rút `{amt:,}đ` đã được duyệt!")
            await q.edit_message_text(f"✅ ĐÃ DUYỆT ID {u_id}")
        else:
            add_money(u_id, amt, "Hoàn tiền rút")
            await ctx.bot.send_message(u_id, "❌ Yêu cầu rút tiền bị từ chối. Tiền đã được hoàn lại.")
            await q.edit_message_text(f"❌ TỪ CHỐI ID {u_id}")

    # ===== GAME XỔ SỐ =====
    elif d == "menu_xoso":
        if is_game_banned(uid, 9):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
        if check_mt('mt_xoso') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Xổ Số đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_xs_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("📉 **XỔ SỐ MIỀN BẮC (X80)**\nChọn mức cược của bạn:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_xs_"):
        amt = int(d.split("_")[2])
        ctx.user_data[f"xs_{uid}"] = amt
        await q.edit_message_text(f"🔢 **XỔ SỐ**\n💰 Cược: `{amt:,}đ`\n👇 Nhập con số bạn muốn đánh (00-99):", parse_mode="Markdown")
        ctx.user_data[f"awaiting_xs_{uid}"] = True

    elif d == "menu_vq":
        if is_game_banned(uid, 10):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
        if check_mt('mt_vongquay') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Vòng Quay đang bảo trì!")
        kb = [[InlineKeyboardButton("🎡 QUAY NGAY (5.000đ)", callback_data="spin_vq")],
              [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_game")]]
        await q.edit_message_text("🎡 **VÒNG QUAY MAY MẮN**\n\nMỗi lượt quay tốn **5.000đ**. Cơ hội nhận lên đến 100k!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d == "spin_vq":
        if not sub_money(uid, 5000, "Vòng quay may mắn"):
            return await ctx.bot.send_message(uid, "❌ Bạn không đủ 5.000đ")
        is_win_vq = check_win_by_id(10, uid)
        prizes = [0, 1000, 2000, 5000, 10000, 20000, 50000, 100000]
        if is_win_vq:
            prize = random.choice([p for p in prizes if p > 0])
        else:
            prize = 0
        msg_vq = await ctx.bot.send_message(uid, "🌀 **ĐANG QUAY...**")
        await asyncio.sleep(2)
        if prize > 0:
            add_money(uid, prize, "Thắng Vòng Quay")
            await msg_vq.edit_text(f"🎁 **CHÚC MỪNG!**\nBạn đã quay vào ô: `+{prize:,}đ`\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        else:
            await msg_vq.edit_text("💀 **MẤT LƯỢT!**\nChúc bạn may mắn lần sau.", parse_mode="Markdown")

    # ===== GAME BẦU CUA =====
    elif d == "menu_bc":
        if is_game_banned(uid, 8):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
        if check_mt('mt_baucua') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Bầu Cua đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_bc_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🦀 **BẦU CUA TÔM CÁ**\nChọn mức cược của bạn:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_bc_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("nai NAI", callback_data=f"p_bc_0_{amt}"), InlineKeyboardButton("cua CUA", callback_data=f"p_bc_1_{amt}"), InlineKeyboardButton("ca CA", callback_data=f"p_bc_2_{amt}")],
            [InlineKeyboardButton("ho HO", callback_data=f"p_bc_3_{amt}"), InlineKeyboardButton("tom TOM", callback_data=f"p_bc_4_{amt}"), InlineKeyboardButton("bau BAU", callback_data=f"p_bc_5_{amt}")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_bc")]
        ]
        await q.edit_message_text(f"🦀 **BẦU CUA**\n💰 Cược: `{amt:,}đ`\n👇 Chọn linh vật bạn đặt cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_bc_"):
        parts = d.split("_")
        choice_idx, amt = int(parts[2]), int(parts[3])
        items = ["鹿 NAI", "🦀 CUA", "🐟 CÁ", "🐯 HỔ", "🦐 TÔM", "🍐 BẦU"]
        if not sub_money(uid, amt, f"Cược Bầu Cua {items[choice_idx]}"):
            return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        msg_bc = await ctx.bot.send_message(uid, "🎲 **ĐANG LẮC BẦU CUA...**")
        is_win_bc = check_win_by_id(8, uid)
        if is_win_bc:
            res1 = choice_idx
            res2 = random.randint(0, 5)
            res3 = random.randint(0, 5)
        else:
            pool = [i for i in range(6) if i != choice_idx]
            res1, res2, res3 = random.choices(pool, k=3)
        results = [res1, res2, res3]
        random.shuffle(results)
        match_count = results.count(choice_idx)
        await asyncio.sleep(2)
        res_str = " | ".join([items[i] for i in results])
        if match_count > 0:
            rate = 1 + match_count
            win_amt = int(amt * rate * 0.95) 
            add_money(uid, win_amt, f"Thắng Bầu Cua {items[choice_idx]} x{match_count}")
            status = f"🎉 **THẮNG X{match_count}!**\n💰 Nhận: `+{win_amt:,}đ`"
        else:
            status = f"💀 **THẤT BẠI!**\n❌ Không có con **{items[choice_idx]}** nào."
        await msg_bc.edit_text(f"📊 **KẾT QUẢ BẦU CUA**\n━━━━━━━━━━━━━━━━━━━━━\n✨ Kết quả: **{res_str}**\n👉 Bạn chọn: **{items[choice_idx]}**\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        return

    # ===== GAME QUAY SỐ =====
    elif d == "menu_qs":
        if is_game_banned(uid, 7):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
        if check_mt('mt_quayso') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Quay Số đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_qs_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🔢 **QUAY SỐ MAY MẮN (1-3)**\nChọn số và nhận thưởng x2.8!\nVui lòng chọn mức cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_qs_"):
        amt = int(d.split("_")[2])
        kb = [
            [InlineKeyboardButton("1️⃣ SỐ 1", callback_data=f"p_qs_1_{amt}"), 
             InlineKeyboardButton("2️⃣ SỐ 2", callback_data=f"p_qs_2_{amt}"),
             InlineKeyboardButton("3️⃣ SỐ 3", callback_data=f"p_qs_3_{amt}")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_qs")]
        ]
        await q.edit_message_text(f"🔢 **CHỌN CON SỐ MAY MẮN**\n💰 Cược: `{amt:,}đ`\n📈 Hệ số nhân: **x2.8**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_qs_"):
        parts = d.split("_")
        choice, amt = int(parts[2]), int(parts[3])
        if not sub_money(uid, amt, f"Cược Quay Số {choice}"):
            return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        msg_qs = await ctx.bot.send_message(uid, "🌀 **ĐANG QUAY SỐ...**")
        await asyncio.sleep(2)
        is_win_qs = check_win_by_id(7, uid)
        if is_win_qs:
            result_qs = choice
        else:
            result_qs = random.choice([n for n in [1, 2, 3] if n != choice])
        if choice == result_qs:
            win_amt = int(amt * 2.8)
            add_money(uid, win_amt, f"Thắng Quay Số {choice}")
            status = f"🎉 **CHIẾN THẮNG!**\n💎 Kết quả ra số: **{result_qs}**\n💰 Nhận: `+{win_amt:,}đ`"
        else:
            status = f"💀 **THẤT BẠI!**\n❌ Kết quả ra số: **{result_qs}**\n👉 Bạn đã chọn số: **{choice}**"
        await msg_qs.edit_text(f"📊 **KẾT QUẢ QUAY SỐ**\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")
        return

    # ===== GAME ĐUA XE =====
    elif d == "menu_race":
        if is_game_banned(uid, 3):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
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

    # ===== GAME DÒ MÌN =====
    elif d == "menu_mines":
        if is_game_banned(uid, 4):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
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
        is_win_game = check_win_by_id(4, uid)
        grid = [0]*12 + [1]*3 
        random.shuffle(grid)
        ctx.user_data[f"mine_{uid}"] = {"grid": grid, "bet": amt, "opened": [], "mult": 1.05, "must_lose": not is_win_game}
        kb = []
        row = []
        for i in range(15):
            row.append(InlineKeyboardButton("❓", callback_data=f"play_mine_{i}"))
            if (i+1) % 3 == 0: kb.append(row); row = []
        await q.edit_message_text(f"💣 **DÒ MÌN ĐANG DIỄN RA**\n💰 Cược: `{amt:,}đ`\n📈 Hệ số tiếp theo: `x1.05`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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
            game["mult"] = get_next_multiplier(game["mult"])
            kb = []
            row = []
            for i in range(15):
                icon = "💎" if i in game["opened"] else "❓"
                row.append(InlineKeyboardButton(icon, callback_data=f"play_mine_{i}"))
                if (i+1) % 3 == 0: kb.append(row); row = []
            kb.append([InlineKeyboardButton(f"💰 CHỐT LỜI: {current_win:,}đ", callback_data=f"claim_mine_{current_win}")])
            await q.edit_message_text(f"💎 **AN TOÀN!**\n💰 Thưởng hiện tại: `{current_win:,}đ`\n📈 Lượt tới: `x{game['mult']:.2f}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("claim_mine_"):
        amt = int(d.split("_")[2])
        add_money(uid, amt, "Thắng Dò Mìn")
        if f"mine_{uid}" in ctx.user_data: del ctx.user_data[f"mine_{uid}"]
        await q.edit_message_text(f"🎉 **CHÚC MỪNG!**\nBạn đã chốt lời thành công: `+{amt:,}đ`\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

    # ===== GAME TÀI XỈU, PENALTY, XÓC ĐĨA =====
    elif d == "menu_tx" or d == "menu_ball" or d == "menu_xocdia":
        if "tx" in d: g_type, g_name, mt_key, gid = "tx", "🎲 TÀI XỈU 3D", "mt_taixiu", 1
        elif "ball" in d: g_type, g_name, mt_key, gid = "ball", "⚽️ BÓNG ĐÁ PENALTY", "mt_penalty", 5
        else: g_type, g_name, mt_key, gid = "xd", "💿 XÓC ĐĨA VIP", "mt_xocdia", 2
        if is_game_banned(uid, gid):
            return await ctx.bot.send_message(uid, f"❌ Bạn đã bị cấm chơi trò {g_name}. Vui lòng liên hệ Admin!")
        if check_mt(mt_key) and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, f"⚙️ Game {g_name} đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"set_{g_type}_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text(f"{g_name}\n👇 Chọn mức tiền cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("set_"):
        parts = d.split("_")
        game, amt = parts[1], parts[2]
        if game == "tx":
            kb = [[InlineKeyboardButton("🎲 TÀI", callback_data=f"p_tx_tai_{amt}"), InlineKeyboardButton("🎲 XỈU", callback_data=f"p_tx_xiu_{amt}")]]
        elif game == "xd":
            kb = [
                [InlineKeyboardButton("🔴 CHẴN (x1.95)", callback_data=f"p_xd_chan_{amt}"), InlineKeyboardButton("⚪️ LẺ (x1.95)", callback_data=f"p_xd_le_{amt}")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_xocdia")]
            ]
        else:
            kb = [[InlineKeyboardButton("⬅️ TRÁI", callback_data=f"p_ba_1_{amt}"), 
                   InlineKeyboardButton("⬆️ GIỮA", callback_data=f"p_ba_2_{amt}"), 
                   InlineKeyboardButton("➡️ PHẢI", callback_data=f"p_ba_3_{amt}")]]
        await q.edit_message_text(f"💰 Cược: **{int(amt):,}đ**\n👇 Chọn hướng sút/cửa đặt:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("p_"):
        parts = d.split("_")
        game, choice, amt = parts[1], parts[2], int(parts[3])
        if get_balance(uid) < amt: return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        if game == "xd":
            sub_money(uid, amt, f"Cược Xóc Đĩa {choice.upper()}")
            frames = ["💿 [ - - - - ]", "💿 [ ⚪️ 🔴 ⚪️ 🔴 ]", "💿 [ 🔴 🔴 🔴 🔴 ]", "💿 [ 🔴 ⚪️ 🔴 ⚪️ ]"]
            msg_status = await ctx.bot.send_message(uid, frames[0], parse_mode="Markdown")
            for f in frames[1:]:
                await asyncio.sleep(0.4)
                try: await msg_status.edit_text(f + "\n⚡️ ĐANG LẮC...")
                except: pass
            is_win_game = check_win_by_id(2, uid)
            if is_win_game:
                win_sets = {"chan":[[1,1,0,0],[1,1,1,1],[0,0,0,0]], "le":[[1,0,0,0],[1,1,1,0]]}
                results = random.choice(win_sets[choice])
            else:
                all_sets = [[1,1,1,1],[0,0,0,0],[1,1,0,0],[1,1,1,0],[1,0,0,0]]
                def check_fail(res, c):
                    r = sum(res)
                    if c=="chan": return r%2!=0
                    return r%2==0
                fail_sets = [r for r in all_sets if check_fail(r, choice)]
                results = random.choice(fail_sets)
            random.shuffle(results)
            red_count = sum(results)
            icons = "".join(["🔴" if r == 1 else "⚪️" for r in results])
            is_chan = (red_count % 2 == 0)
            win, rate = False, 1.95
            if choice == "chan" and is_chan: win = True
            elif choice == "le" and not is_chan: win = True
            if win:
                win_amt = int(amt * rate)
                add_money(uid, win_amt, f"Thắng Xóc Đĩa {choice.upper()}")
                status = f"🎉 **THÔNG THẮNG X{rate}**\n💰 Nhận: `+{win_amt:,}đ`"
            else: status = f"❌ **THUA RỒI**\n💀 Kết quả không khớp cửa đặt."
            final_msg = (f"📊 **KẾT QUẢ XÓC ĐĨA**\n━━━━━━━━━━━━━━━━━━━━━\n💿 Kết quả: **{icons}**\n📝 Loại: **{'CHẴN' if is_chan else 'LẺ'}** ({red_count} Đỏ)\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`")
            await msg_status.edit_text(final_msg, parse_mode="Markdown")
            return
        if game == "ba":
            sub_money(uid, amt, f"Cược Penalty")
            is_win = check_win_by_id(5, uid)
            player_choice = int(choice)
            if is_win:
                goalie_direction = random.choice([d for d in [1, 2, 3] if d != player_choice])
            else:
                goalie_direction = player_choice
            directions_text = {1: "TRÁI", 2: "GIỮA", 3: "PHẢI"}
            await ctx.bot.send_dice(uid, emoji="⚽️")
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
            await asyncio.sleep(4)
            results = [d1.dice.value, d2.dice.value, d3.dice.value]
            total = sum(results)
            res_type = "tai" if total >= 11 else "xiu"
            is_win_check = check_win_by_id(1, uid)
            win = (choice == res_type and is_win_check)
            if win:
                win_amt = int(amt * 1.95)
                add_money(uid, win_amt, f"Thắng Tài Xỉu {res_type.upper()}")
                status = f"🎉 **THẮNG** | Nhận: `+{win_amt:,}đ`"
            else:
                status = f"❌ **THUA** | Chúc may mắn lần sau!"
            res_str = "-".join(map(str, results))
            await msg_status.edit_text(f"📊 **KẾT QUẢ TÀI XỈU**\n━━━━━━━━━━━━━━━━━━━━━\n🎲 Xúc xắc: **{res_str}**\n🏆 Tổng điểm: **{total}** ({res_type.upper()})\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

    # ===== GAME GÕ MÕ =====
    elif d == "menu_wooden":
        if is_game_banned(uid, 6):
            return await ctx.bot.send_message(uid, "❌ Bạn đã bị cấm chơi trò chơi này. Vui lòng liên hệ Admin!")
        if check_mt('mt_gomo') and uid not in ADMIN_IDS:
            return await ctx.bot.send_message(uid, "⚙️ Game Gõ Mõ đang bảo trì!")
        kb = []
        row = []
        for i, a in enumerate(amounts):
            row.append(InlineKeyboardButton(f"{a//1000}k" if a < 1000000 else "1M", callback_data=f"prep_wood_{a}"))
            if (i + 1) % 4 == 0: kb.append(row); row = []
        await q.edit_message_text("🪵 **GAME GÕ MÕ**\n\n- Hệ số tăng: 1.05 -> 1.10 -> 1.20... -> 2.0 -> 2.20...\n- Bạn phải rút trước khi mõ vỡ!\n\nChọn mức cược:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("prep_wood_"):
        amt = int(d.split("_")[2])
        kb = [[InlineKeyboardButton("🪵 BẮT ĐẦU GÕ", callback_data=f"start_wood_{amt}")],
              [InlineKeyboardButton("🔙 Quay lại", callback_data="menu_wooden")]]
        await q.edit_message_text(f"🪵 **GÕ MÕ**\n💰 Cược: `{amt:,}đ`\n👇 Nhấn nút GÕ bên dưới để bắt đầu tăng hệ số!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("start_wood_"):
        amt = int(d.split("_")[2])
        if not sub_money(uid, amt, "Cược Gõ Mõ"): 
            return await ctx.bot.send_message(uid, "❌ Số dư không đủ.")
        is_win_wood = check_win_by_id(6, uid)
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
        game_id = "_".join(parts[2:])
        game = ctx.user_data.get(game_id)
        if not game or game["status"] != "playing": return
        game["mult"] = get_next_multiplier(game["mult"])
        if game["mult"] >= game["target"]:
            game["status"] = "broken"
            await q.edit_message_text(f"💥 **MÕ ĐÃ VỠ !!!**\n\nHệ số nhảy quá cao: **x{game['mult']:.2f}**\n💀 Mất: `{game['amt']:,}đ`", parse_mode="Markdown")
            if game_id in ctx.user_data: del ctx.user_data[game_id]
        else:
            win_now = int(game["amt"] * game["mult"])
            kb = [[InlineKeyboardButton(f"🪵 GÕ TIẾP (x{game['mult']:.2f})", callback_data=f"hit_wood_{game_id}")],
                  [InlineKeyboardButton(f"💰 RÚT TIỀN (x{game['mult']:.2f})", callback_data=f"clm_wood_{game_id}")]]
            await q.edit_message_text(f"🪵 **GÕ MÕ... CỘP CỘP!**\n📈 Hệ số: **x{game['mult']:.2f}**\n💰 Tiền thắng: `{win_now:,}đ`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clm_wood_"):
        parts = d.split("_")
        game_id = "_".join(parts[2:])
        game = ctx.user_data.get(game_id)
        if game and game["status"] == "playing":
            game["status"] = "claimed"
            win_amt = int(game["amt"] * game["mult"])
            add_money(uid, win_amt, f"Thắng Gõ Mõ x{game['mult']}")
            await q.edit_message_text(f"🎉 **CHÚC MỪNG!**\n\nBạn đã dừng ở **x{game['mult']:.2f}**\n💰 Nhận được: `+{win_amt:,}đ`", parse_mode="Markdown")
            if game_id in ctx.user_data: del ctx.user_data[game_id]

# Xử lý tin nhắn riêng cho Xổ Số
async def handle_xs_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if f"awaiting_xs_{uid}" in ctx.user_data:
        num_str = update.message.text
        if not num_str.isdigit() or len(num_str) != 2:
            return await update.message.reply_text("❌ Vui lòng nhập đúng 2 chữ số (00-99).")
        amt = ctx.user_data.get(f"xs_{uid}", 0)
        if f"awaiting_xs_{uid}" in ctx.user_data: del ctx.user_data[f"awaiting_xs_{uid}"]
        if not sub_money(uid, amt, f"Đánh đề số {num_str}"):
            return await update.message.reply_text("❌ Số dư không đủ.")
        msg = await update.message.reply_text(f"⏳ Đang gửi số **{num_str}** lên hệ thống xổ số...")
        await asyncio.sleep(2)
        is_win_xs = check_win_by_id(9, uid)
        if is_win_xs: result_xs = num_str
        else: result_xs = str(random.randint(0, 99)).zfill(2)
        if num_str == result_xs:
            win_amt = amt * 80
            add_money(uid, win_amt, f"Trúng đề số {num_str}")
            status = f"🎉 **TRÚNG ĐỀ RỒI!**\n💎 Giải đặc biệt ra số: **{result_xs}**\n💰 Nhận x80: `+{win_amt:,}đ`"
        else:
            status = f"💀 **TRƯỢT LÔ!**\n❌ Kết quả ra số: **{result_xs}**\n👉 Bạn đánh số: **{num_str}**"
        await msg.edit_text(f"📊 **KẾT QUẢ XỔ SỐ**\n━━━━━━━━━━━━━━━━━━━━━\n{status}\n💰 Số dư: `{get_balance(uid):,}đ`", parse_mode="Markdown")

async def main_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ctx.user_data.get(f"awaiting_xs_{uid}"):
        await handle_xs_input(update, ctx)
    else:
        await handle(update, ctx)

# ===== KHỞI CHẠY BOT =====
application = ApplicationBuilder().token(TOKEN).build()

# Các handler hiện có
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("baotri", baotri_cmd))
application.add_handler(CommandHandler("code", nhap_code))
application.add_handler(CommandHandler("taocode", tao_code))
application.add_handler(CommandHandler("tilewin", tilewin_cmd)) 
application.add_handler(CommandHandler("rut", rut))
application.add_handler(CommandHandler("lienket", lien_ket))
application.add_handler(CommandHandler("resetbank", reset_bank))
application.add_handler(CommandHandler("resetall", reset_all_confirm)) 
application.add_handler(CommandHandler("add", add))
application.add_handler(CommandHandler("sub", sub))
application.add_handler(CommandHandler("ban", ban))
application.add_handler(CommandHandler("unban", unban))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(CommandHandler("all", all_user))
application.add_handler(CommandHandler("his", history_pro)) 
application.add_handler(CommandHandler("hisall", history_all_admin))
application.add_handler(CommandHandler("send", broadcast))
application.add_handler(CommandHandler("rep", reply_user))
application.add_handler(CommandHandler("check", check_user_history))
application.add_handler(CommandHandler("info", admin_info)) 
application.add_handler(CommandHandler("nap", nap_tien_admin))
application.add_handler(CommandHandler("soduall", soduall_cmd))
application.add_handler(CommandHandler("tileall", tileall_set_cmd))
application.add_handler(CommandHandler("resetsdall", resetsdall_cmd))
application.add_handler(CommandHandler("tile1", tile1_user_cmd))
application.add_handler(CommandHandler("xoalsall", xoalsall_cmd))
application.add_handler(CommandHandler("xoals", xoals_user_cmd))
application.add_handler(CommandHandler("give", give_money_cmd))
application.add_handler(CommandHandler("top", top_cmd))
application.add_handler(CommandHandler("setname", set_bot_name_cmd))
application.add_handler(CommandHandler("thongke", dashboard_cmd))
application.add_handler(CommandHandler("tong", tong_cmd))
application.add_handler(CommandHandler("cam", cam_cmd))
application.add_handler(CommandHandler("bocam", bocam_cmd))

# Handler quản lý admin mới
application.add_handler(CommandHandler("camadmin", cam_admin_cmd))
application.add_handler(CommandHandler("unbanadmin", unban_admin_cmd))
application.add_handler(CommandHandler("listbannedadmins", list_banned_admins_cmd))

# Handler bảo trì toàn hệ thống
application.add_handler(CommandHandler("baotrihethong", baotri_hethong_cmd))

# Handler mới cho game trong nhóm
application.add_handler(CommandHandler("t", bet_tai_group))
application.add_handler(CommandHandler("x", bet_xiu_group))
application.add_handler(CommandHandler("group_status", group_status_cmd))

# Job tự động bảo hiểm VIP
if application.job_queue:
    application.job_queue.run_daily(bao_hiem_vip, time=datetime.strptime("00:00:01", "%H:%M:%S").time())

application.add_handler(CallbackQueryHandler(handle_callback))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

# ===== KHỞI ĐỘNG GAME CHO NHÓM =====
GROUP_IDS = [-1003663678808]  # ID nhóm của bạn

async def main():
    # Khởi tạo bot
    await application.initialize()
    await application.start()

    # Khởi động game cho từng nhóm
    for gid in GROUP_IDS:
        try:
            asyncio.create_task(run_dice_game_cycle(application.bot, gid, gid))
            print(f"✅ Đã khởi động game cho nhóm {gid}")
        except Exception as e:
            print(f"Lỗi nhóm {gid}: {e}")

    # Bắt đầu nhận tin nhắn
    await application.updater.start_polling(drop_pending_updates=True)
    print("🤖 BOT ĐÃ ONLINE VÀ ĐANG CHẠY...")
    
    # Giữ bot chạy
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot đã dừng lại.")
    except Exception as e:
        print(f"❌ Lỗi khởi động: {e}") 
