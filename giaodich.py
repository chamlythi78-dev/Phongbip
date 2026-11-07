"""GIAO DỊCH TIỀN BẨN - web đăng nhập / đăng ký / nạp tiền VietQR.
Chỉ 1 file, chỉ dùng thư viện có sẵn của Python (không cần cài thêm gì).

Biến môi trường (đặt trên Railway):
  SECRET_KEY  chuỗi ngẫu nhiên dài (bắt buộc, nếu thiếu thì mỗi lần restart sẽ bị đăng xuất)
  DATA_DIR    /data  (gắn Volume vào đường dẫn này để không mất dữ liệu)
"""
import base64, hashlib, hmac, json, math, os, re, secrets, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

# ===== Cấu hình =====
BANK = {"id": "MB", "name": "MB Bank", "account": "0003456712345", "holder": "LY THI CHAM"}
QUICK_AMOUNTS = [20000, 50000, 100000, 200000, 500000, 1000000]
MIN_AMOUNT, MAX_AMOUNT = 10000, 50000000
SECRET = (os.environ.get("SECRET_KEY") or secrets.token_hex(32)).encode()
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
PORT = int(os.environ.get("PORT", 3000))
SECURE = bool(os.environ.get("RAILWAY_ENVIRONMENT"))
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

if not os.environ.get("SECRET_KEY"):
    print("Chưa đặt SECRET_KEY: đăng nhập sẽ bị reset mỗi lần restart.")

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")


def db():
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


with db() as c:
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS topups (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL,
      code TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)


# ===== Bảo mật =====
def hash_pw(pw):
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()


def check_pw(pw, stored):
    try:
        salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


def b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(uid):
    body = b64(json.dumps({"id": uid, "exp": int(time.time()) + 7 * 86400}).encode())
    return body + "." + b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())


def read_token(tok):
    try:
        body, sig = tok.split(".")
        good = b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return data["id"] if data["exp"] > time.time() else None
    except Exception:
        return None


HITS = {}


def too_many(ip):
    now = time.time()
    arr = [t for t in HITS.get(ip, []) if now - t < 60]
    arr.append(now)
    HITS[ip] = arr
    if len(HITS) > 5000:
        HITS.clear()
    return len(arr) > 10


def qr_url(amount, code):
    q = urlencode({"amount": amount, "addInfo": code, "accountName": BANK["holder"]})
    return f"https://img.vietqr.io/image/{BANK['id']}-{BANK['account']}-compact2.png?{q}"


# ===== Máy chủ =====
class H(BaseHTTPRequestHandler):
    server_version = "GD"

    def log_message(self, *a):
        pass

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def send(self, status, body, ctype, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def js(self, status, obj, extra=()):
        self.send(status, json.dumps(obj).encode(), "application/json; charset=utf-8", extra)

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 10000)) or b"{}") if n else {}
        except Exception:
            return {}

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def set_cookie(self, val, age):
        s = f"token={val}; HttpOnly; SameSite=Lax; Path=/; Max-Age={age}" + ("; Secure" if SECURE else "")
        return [("Set-Cookie", s)]

    def user(self):
        uid = read_token(self.cookie("token"))
        if not uid:
            return None
        with db() as c:
            r = c.execute("SELECT id, username, balance FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self.send(200, INDEX.encode(), "text/html; charset=utf-8")
        if p in ("/api/me", "/api/topups"):
            u = self.user()
            if not u:
                return self.js(401, {"error": "Bạn cần đăng nhập."})
            if p == "/api/me":
                return self.js(200, {"user": u, "bank": BANK, "quickAmounts": QUICK_AMOUNTS, "min": MIN_AMOUNT, "max": MAX_AMOUNT})
            with db() as c:
                rows = c.execute("SELECT amount,code,status,created_at FROM topups WHERE user_id=? ORDER BY id DESC LIMIT 10", (u["id"],)).fetchall()
            return self.js(200, [dict(r) for r in rows])
        self.js(404, {"error": "Không tìm thấy."})

    def do_POST(self):
        p = self.path.split("?")[0]
        d = self.body()

        if p in ("/api/register", "/api/login"):
            if too_many(self.ip()):
                return self.js(429, {"error": "Thử quá nhiều lần, đợi một phút rồi thử lại."})
            name = str(d.get("username", "")).strip().lower()
            pw = str(d.get("password", ""))
            if p == "/api/register":
                if not re.fullmatch(r"[a-z0-9_]{3,20}", name):
                    return self.js(400, {"error": "Tên đăng nhập 3-20 ký tự, chỉ gồm chữ thường, số và dấu gạch dưới."})
                if len(pw) < 6:
                    return self.js(400, {"error": "Mật khẩu cần ít nhất 6 ký tự."})
                try:
                    with db() as c:
                        uid = c.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (name, hash_pw(pw))).lastrowid
                except sqlite3.IntegrityError:
                    return self.js(409, {"error": "Tên đăng nhập đã có người dùng."})
                return self.js(200, {"ok": True}, self.set_cookie(make_token(uid), 7 * 86400))
            with db() as c:
                r = c.execute("SELECT id,password_hash FROM users WHERE username=?", (name,)).fetchone()
            if not r or not check_pw(pw, r["password_hash"]):
                return self.js(401, {"error": "Sai tên đăng nhập hoặc mật khẩu."})
            return self.js(200, {"ok": True}, self.set_cookie(make_token(r["id"]), 7 * 86400))

        if p == "/api/logout":
            return self.js(200, {"ok": True}, self.set_cookie("", 0))

        if p == "/api/topup":
            u = self.user()
            if not u:
                return self.js(401, {"error": "Bạn cần đăng nhập."})
            try:
                amount = round(float(d.get("amount")))
                assert math.isfinite(amount) and MIN_AMOUNT <= amount <= MAX_AMOUNT
            except Exception:
                return self.js(400, {"error": f"Số tiền nạp từ {MIN_AMOUNT:,}đ đến {MAX_AMOUNT:,}đ.".replace(",", ".")})
            for _ in range(20):
                code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
                try:
                    with db() as c:
                        c.execute("INSERT INTO topups(user_id,amount,code) VALUES(?,?,?)", (u["id"], amount, code))
                    break
                except sqlite3.IntegrityError:
                    continue
            return self.js(200, {"amount": amount, "code": code, "qr": qr_url(amount, code), "bank": BANK})

        self.js(404, {"error": "Không tìm thấy."})


INDEX = r'''<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GIAO DỊCH TIỀN BẨN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;800&display=swap" rel="stylesheet">
<style>
:root{--ink:#15203b;--ink2:#26345c;--paper:#eef1f8;--card:#fff;--line:#dde3f0;--muted:#6a7694;--gold:#f5a524;--blue:#3b4bdb;--ok:#0e9f6e;--err:#d6336c}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;font-family:'Be Vietnam Pro',system-ui,sans-serif;color:var(--ink);background:var(--paper);min-height:100vh;
background-image:radial-gradient(900px 500px at 85% -10%,#d8defa 0,transparent 60%),radial-gradient(700px 400px at -10% 110%,#fde9c4 0,transparent 55%);background-attachment:fixed}
button,input{font:inherit}
.hidden{display:none!important}
.wrap{max-width:960px;margin:0 auto;padding:20px 16px 60px}
:focus-visible{outline:3px solid var(--blue);outline-offset:2px}

/* Đăng nhập */
.auth{min-height:100vh;display:grid;place-items:center;padding:20px}
.auth-box{width:100%;max-width:400px}
.brand{font-weight:800;font-size:clamp(22px,7vw,28px);letter-spacing:0;margin:0 0 4px}
.brand b{color:var(--gold)}
.tag{color:var(--muted);margin:0 0 24px}
.panel{background:var(--card);border-radius:20px;padding:24px;box-shadow:0 10px 40px -12px rgba(21,32,59,.25)}
.tabs{display:grid;grid-template-columns:1fr 1fr;background:var(--paper);border-radius:12px;padding:4px;margin-bottom:20px}
.tabs button{border:0;background:none;padding:10px;border-radius:9px;font-weight:600;color:var(--muted);cursor:pointer}
.tabs button.on{background:#fff;color:var(--ink);box-shadow:0 2px 8px rgba(21,32,59,.12)}
label{display:block;font-size:14px;font-weight:600;margin:14px 0 6px}
input{width:100%;padding:13px 14px;border:1.5px solid var(--line);border-radius:12px;background:#fff;color:var(--ink)}
input:focus{border-color:var(--blue);outline:none;box-shadow:0 0 0 3px rgba(59,75,219,.15)}
.btn{width:100%;margin-top:20px;border:0;border-radius:12px;padding:14px;font-weight:600;background:var(--ink);color:#fff;cursor:pointer}
.btn:hover{background:var(--ink2)}
.btn:disabled{opacity:.6;cursor:wait}
.msg{min-height:20px;margin:12px 0 0;font-size:14px;color:var(--err)}

/* Trang chính */
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.top .brand{font-size:clamp(15px,4.6vw,20px);margin:0}
.who{display:flex;align-items:center;gap:12px;font-weight:600}
.out{border:1.5px solid var(--line);background:#fff;border-radius:10px;padding:8px 14px;cursor:pointer;font-weight:600}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
@media(min-width:800px){.grid{grid-template-columns:5fr 7fr;align-items:start}}
.balance{background:var(--ink);color:#fff;border-radius:24px;padding:28px;position:relative;overflow:hidden}
.balance::after{content:"";position:absolute;right:-60px;top:-60px;width:200px;height:200px;border-radius:50%;border:34px solid rgba(245,165,36,.18)}
.balance small{color:#aab4d6;font-size:14px}
.balance .num{font-size:clamp(34px,8vw,46px);font-weight:800;letter-spacing:-1px;color:var(--gold);margin:6px 0 0}
.balance .num span{font-size:.5em;margin-left:4px;color:#fff;font-weight:600}
h2{font-size:18px;margin:0 0 14px}
.chips{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.chip{border:1.5px solid var(--line);background:#fff;border-radius:12px;padding:14px 6px;font-weight:600;cursor:pointer;color:var(--ink)}
.chip:hover,.chip.on{border-color:var(--blue);background:#f1f3ff}
.custom{display:flex;gap:10px;margin-top:12px}
.custom .btn{width:auto;margin:0;padding:0 20px;background:var(--blue)}
.qr{margin-top:20px;border-top:1.5px dashed var(--line);padding-top:20px;text-align:center}
.qr img{width:100%;max-width:300px;border-radius:16px;border:1.5px solid var(--line);background:#fff}
.info{text-align:left;margin-top:16px;display:grid;gap:8px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--paper);border-radius:12px;padding:10px 14px;font-size:14px}
.row span{color:var(--muted)}
.row b{word-break:break-all;text-align:right}
.copy{border:0;background:#fff;border-radius:8px;padding:4px 10px;font-size:12px;font-weight:600;cursor:pointer;margin-left:8px}
.note{font-size:13px;color:var(--muted);margin:12px 0 0;line-height:1.5}
.hist{list-style:none;margin:0;padding:0}
.hist li{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--line);font-size:14px}
.hist li:last-child{border:0}
.st{font-weight:600}.st.done{color:var(--ok)}.st.pending{color:var(--gold)}
.shop{margin-top:16px;text-align:center;padding:36px 16px}
.shop p{color:var(--muted);margin:6px 0 0}
.card+.card{margin-top:16px}
.card{background:var(--card);border-radius:20px;padding:22px;box-shadow:0 10px 40px -16px rgba(21,32,59,.3)}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:#fff;padding:10px 18px;border-radius:999px;font-size:14px}
@media(prefers-reduced-motion:no-preference){.balance .num{transition:color .3s}}
</style>
</head>
<body>

<div id="auth" class="auth">
  <div class="auth-box">
    <h1 class="brand">GIAO DỊCH <b>TIỀN BẨN</b></h1>
    <p class="tag">Đăng nhập để xem số dư và nạp tiền.</p>
    <div class="panel">
      <div class="tabs" role="tablist">
        <button id="tLogin" class="on" type="button">Đăng nhập</button>
        <button id="tReg" type="button">Đăng ký</button>
      </div>
      <form id="authForm">
        <label for="u">Tên đăng nhập</label>
        <input id="u" autocomplete="username" required>
        <label for="p">Mật khẩu</label>
        <input id="p" type="password" autocomplete="current-password" required>
        <div id="confWrap" class="hidden">
          <label for="p2">Nhập lại mật khẩu</label>
          <input id="p2" type="password" autocomplete="new-password">
        </div>
        <p id="authMsg" class="msg" role="alert"></p>
        <button id="authBtn" class="btn" type="submit">Đăng nhập</button>
      </form>
    </div>
  </div>
</div>

<div id="app" class="wrap hidden">
  <div class="top">
    <h1 class="brand">GIAO DỊCH <b>TIỀN BẨN</b></h1>
    <div class="who"><span id="uname"></span><button id="logout" class="out" type="button">Thoát</button></div>
  </div>

  <div class="grid">
    <div>
      <div class="balance">
        <small>Số dư tài khoản</small>
        <div class="num"><span id="bal">0</span><span>đ</span></div>
      </div>
      <div class="card" style="margin-top:16px">
        <h2>Lịch sử nạp tiền</h2>
        <ul id="hist" class="hist"></ul>
      </div>
    </div>

    <div>
      <div class="card">
        <h2>Nạp tiền vào tài khoản</h2>
        <div id="chips" class="chips"></div>
        <div class="custom">
          <input id="custom" type="number" inputmode="numeric" placeholder="Nhập số tiền khác" aria-label="Số tiền khác">
          <button id="customGo" class="btn" type="button">Tạo mã</button>
        </div>
        <p id="topMsg" class="msg" role="alert"></p>

        <div id="qr" class="qr hidden">
          <img id="qrImg" alt="Mã QR chuyển khoản">
          <div class="info">
            <div class="row"><span>Ngân hàng</span><b id="bBank"></b></div>
            <div class="row"><span>Số tài khoản</span><b><span id="bAcc" style="color:inherit"></span><button class="copy" data-c="bAcc" type="button">Sao chép</button></b></div>
            <div class="row"><span>Chủ tài khoản</span><b id="bName"></b></div>
            <div class="row"><span>Số tiền</span><b id="bAmt"></b></div>
            <div class="row"><span>Nội dung</span><b><span id="bCode" style="color:inherit"></span><button class="copy" data-c="bCode" type="button">Sao chép</button></b></div>
          </div>
          <p class="note">Quét mã bằng app ngân hàng, giữ nguyên số tiền và nội dung chuyển khoản. Số dư sẽ cập nhật sau khi hệ thống xác nhận đã nhận tiền.</p>
        </div>
      </div>
    </div>
  </div>

  <div class="card shop">
    <h2>Sản phẩm</h2>
    <p>Chưa có sản phẩm nào. Mục này sẽ được thêm sau.</p>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const fmt = n => Number(n).toLocaleString('vi-VN');
let mode = 'login', poll = null;

async function api(url, body) {
  const r = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || 'Có lỗi xảy ra.'), { status: r.status });
  return d;
}
function toast(t) { const e = document.createElement('div'); e.className = 'toast'; e.textContent = t; document.body.appendChild(e); setTimeout(() => e.remove(), 1800); }

function setMode(m) {
  mode = m;
  $('tLogin').classList.toggle('on', m === 'login');
  $('tReg').classList.toggle('on', m === 'reg');
  $('confWrap').classList.toggle('hidden', m === 'login');
  $('authBtn').textContent = m === 'login' ? 'Đăng nhập' : 'Tạo tài khoản';
  $('p').autocomplete = m === 'login' ? 'current-password' : 'new-password';
  $('authMsg').textContent = '';
}
$('tLogin').onclick = () => setMode('login');
$('tReg').onclick = () => setMode('reg');

$('authForm').onsubmit = async e => {
  e.preventDefault();
  $('authMsg').textContent = '';
  if (mode === 'reg' && $('p').value !== $('p2').value) { $('authMsg').textContent = 'Hai mật khẩu chưa giống nhau.'; return; }
  $('authBtn').disabled = true;
  try {
    await api(mode === 'login' ? '/api/login' : '/api/register', { username: $('u').value, password: $('p').value });
    $('p').value = $('p2').value = '';
    await load();
  } catch (err) { $('authMsg').textContent = err.message; }
  $('authBtn').disabled = false;
};

$('logout').onclick = async () => { await api('/api/logout', {}); clearInterval(poll); $('qr').classList.add('hidden'); show(false); };

function show(loggedIn) {
  $('auth').classList.toggle('hidden', loggedIn);
  $('app').classList.toggle('hidden', !loggedIn);
}

async function refresh() {
  const d = await api('/api/me');
  $('uname').textContent = d.user.username;
  $('bal').textContent = fmt(d.user.balance);
  const h = await api('/api/topups');
  const ul = $('hist'); ul.replaceChildren();
  if (!h.length) { const li = document.createElement('li'); li.textContent = 'Chưa có lần nạp nào.'; ul.appendChild(li); }
  h.forEach(t => {
    const li = document.createElement('li');
    const a = document.createElement('span'); a.textContent = fmt(t.amount) + 'đ · ' + t.code;
    const s = document.createElement('span'); s.className = 'st ' + t.status; s.textContent = t.status === 'done' ? 'Đã nhận' : 'Đang chờ';
    li.append(a, s); ul.appendChild(li);
  });
  return d;
}

async function load() {
  try {
    const d = await refresh();
    show(true);
    const box = $('chips');
    if (!box.children.length) {
      d.quickAmounts.forEach(a => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'chip'; b.textContent = fmt(a) + 'đ';
        b.onclick = () => { document.querySelectorAll('.chip').forEach(c => c.classList.remove('on')); b.classList.add('on'); createTopup(a); };
        box.appendChild(b);
      });
    }
    clearInterval(poll);
    poll = setInterval(() => refresh().catch(() => {}), 8000);
  } catch { show(false); }
}

async function createTopup(amount) {
  $('topMsg').textContent = '';
  try {
    const d = await api('/api/topup', { amount });
    $('qrImg').src = d.qr;
    $('bBank').textContent = d.bank.name;
    $('bAcc').textContent = d.bank.account;
    $('bName').textContent = d.bank.holder;
    $('bAmt').textContent = fmt(d.amount) + 'đ';
    $('bCode').textContent = d.code;
    $('qr').classList.remove('hidden');
    $('qr').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    refresh();
  } catch (err) { $('topMsg').textContent = err.message; }
}
$('customGo').onclick = () => { document.querySelectorAll('.chip').forEach(c => c.classList.remove('on')); createTopup($('custom').value); };
document.addEventListener('click', e => {
  const c = e.target.dataset && e.target.dataset.c;
  if (c) navigator.clipboard.writeText($(c).textContent).then(() => toast('Đã sao chép'));
});

load();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    print("Server chạy tại cổng", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
