# -*- coding: utf-8 -*-
"""
🤖 بوت سرداب - إدارة + حماية + رتب + همسات + ألعاب + بنك

المتطلبات:
    pip install "pyTelegramBotAPI>=4.20" flask

متغيرات البيئة - تنحط في ملف .env جنب البوت (محلياً) أو في Environment على Render:
    TOKEN    ← توكن البوت من BotFather (إجباري)
    DEV_ID   ← ايدي صاحب البوت = رتبة "الاساسي" (رقم). أكثر من واحد؟ افصل بفاصلة
    DB_PATH  ← مسار قاعدة البيانات (اختياري، الافتراضي sardab.db)
⚠️ ملف .env سري: ما يترفع على GitHub (موجود في .gitignore). الكود نفسه ما فيه أي سر.

مهم: من BotFather نفّذ  /setprivacy  واختر  Disable
عشان البوت يشوف الرسائل العادية في القروبات (مثل: رتبتي، اهمس، نرد...)
"""
import html
import os
import random
import re
import sqlite3
import threading
import time
from threading import Thread

from telebot import TeleBot, types



def _load_env_file(name=".env"):
    """يقرأ ملف .env (جنب البوت أو من مجلد التشغيل) بدون ما نكتب التوكن داخل الكود."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, name), name):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        except FileNotFoundError:
            continue


_load_env_file()
# التوكن ما يندكتب هنا أبداً: يجي من متغير البيئة TOKEN أو من ملف .env
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise SystemExit("❌ ضع توكن البوت في متغير البيئة TOKEN أو في ملف .env (TOKEN=...)")

# ---- ايدي صاحب البوت (رتبة "الاساسي"): من .env أو متغير البيئة DEV_ID فقط، مو مكتوب بالكود ----
DEV_IDS = {int(x) for x in re.split(r"[,\s]+", os.environ.get("DEV_ID", "") or os.environ.get("OWNER_ID", ""))
           if x.strip().lstrip("-").isdigit()}
if not DEV_IDS:
    print("ℹ️ DEV_ID فاضي: رتبة (الاساسي) ما راح تتفعل لأحد (ضع ايديك في ملف .env)")

bot = TeleBot(TOKEN, parse_mode="HTML")
_me = bot.get_me()
BOT_ID = _me.id
BOT_USERNAME = _me.username
GROUP = ["group", "supergroup"]
ANON_ADMIN_ID = 1087968824  # حساب "المشرف المجهول"

# ---- أزرار رسالة الترحيب في الخاص (اتركها فاضية لو ما تبيها) ----
DEV_NAME = os.environ.get("DEV_NAME", "المطور")
DEV_URL = os.environ.get("DEV_URL", "")          # مثال: https://t.me/your_username
CHANNEL_URL = os.environ.get("CHANNEL_URL", "")  # مثال: https://t.me/your_channel
WELCOME_PRIVATE = (
    "أهلاً بك عزيزي في بوت <b>سرداب</b> 🇦🇪\n\n"
    "• بوت إدارة وحماية وتسلية للمجموعات.\n"
    "• همسات سرية (نص ووسائط)، ألعاب، بنك، رتب، زواج.\n"
    "• أضفني لمجموعتك وارفعني مشرف وأنا أتكفل بالباقي."
)
ALL_TYPES = ["text", "photo", "sticker", "document", "video", "animation",
             "voice", "audio", "video_note"]

# ============ سيرفر وهمي (فقط لو شغّلته كـ Web Service على Render) ============
if os.environ.get("PORT"):
    try:
        from flask import Flask

        _app = Flask(__name__)

        @_app.route("/")
        def _home():
            return "Sardab bot is running 🚀"

        Thread(
            target=lambda: _app.run(host="0.0.0.0", port=int(os.environ["PORT"])),
            daemon=True,
        ).start()
    except ImportError:
        pass

# ============================= قاعدة البيانات =============================
conn = sqlite3.connect(os.environ.get("DB_PATH", "sardab.db"), check_same_thread=False)
conn.row_factory = sqlite3.Row
db_lock = threading.RLock()


def db_exec(sql, params=()):
    with db_lock:
        conn.execute(sql, params)
        conn.commit()


def db_one(sql, params=()):
    with db_lock:
        return conn.execute(sql, params).fetchone()


def db_all(sql, params=()):
    with db_lock:
        return conn.execute(sql, params).fetchall()


def db_insert(sql, params=()):
    """INSERT ويرجع الـ id الجديد (آمن مع الـ threads)."""
    with db_lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
if _cols and not {"user_id", "chat_id", "rank", "balance"} <= _cols:
    # جدول قديم بتركيبة مختلفة: نحتفظ فيه باسم ثاني وننشئ جدول جديد صحيح
    db_exec(f"ALTER TABLE users RENAME TO users_old_{int(time.time())}")
    print("⚠️ لقيت جدول users قديم بتركيبة مختلفة، تم نقله لنسخة احتياطية وإنشاء جدول جديد.")

db_exec("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER, chat_id INTEGER, name TEXT, rank TEXT DEFAULT 'عضو',
    balance INTEGER DEFAULT 0, bank TEXT DEFAULT 'لا يوجد',
    messages INTEGER DEFAULT 0, warns INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, chat_id))""")
for _col in ("username TEXT", "thefts INTEGER DEFAULT 0"):  # ترقية قاعدة قديمة
    try:
        db_exec(f"ALTER TABLE users ADD COLUMN {_col}")
    except sqlite3.OperationalError:
        pass

db_exec("""CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER, key TEXT, value INTEGER, PRIMARY KEY (chat_id, key))""")
db_exec("""CREATE TABLE IF NOT EXISTS cooldowns (
    chat_id INTEGER, user_id INTEGER, key TEXT, ts REAL,
    PRIMARY KEY (chat_id, user_id, key))""")
db_exec("""CREATE TABLE IF NOT EXISTS whispers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
    sender_id INTEGER, sender_name TEXT, target_id INTEGER, target_name TEXT,
    text TEXT, is_read INTEGER DEFAULT 0, ts INTEGER)""")
for _col in ("kind TEXT DEFAULT 'text'", "src_msg INTEGER", "group_msg INTEGER",
             "media_type TEXT", "file_id TEXT", "caption TEXT"):
    try:
        db_exec(f"ALTER TABLE whispers ADD COLUMN {_col}")
    except sqlite3.OperationalError:
        pass
db_exec("""CREATE TABLE IF NOT EXISTS banned (
    chat_id INTEGER, user_id INTEGER, name TEXT, PRIMARY KEY (chat_id, user_id))""")
db_exec("""CREATE TABLE IF NOT EXISTS blocklist (
    chat_id INTEGER, kind TEXT, key TEXT, label TEXT, PRIMARY KEY (chat_id, kind, key))""")
db_exec("""CREATE TABLE IF NOT EXISTS replies (
    chat_id INTEGER, word TEXT, kind TEXT, file_id TEXT, text TEXT, PRIMARY KEY (chat_id, word))""")
db_exec("""CREATE TABLE IF NOT EXISTS vip_replies (
    chat_id INTEGER, word TEXT, kind TEXT, file_id TEXT, text TEXT, PRIMARY KEY (chat_id, word))""")
db_exec("""CREATE TABLE IF NOT EXISTS aliases (
    chat_id INTEGER, new_cmd TEXT, old_cmd TEXT, PRIMARY KEY (chat_id, new_cmd))""")
db_exec("""CREATE TABLE IF NOT EXISTS chat_texts (
    chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (chat_id, key))""")
db_exec("""CREATE TABLE IF NOT EXISTS bots_seen (
    chat_id INTEGER, user_id INTEGER, name TEXT, PRIMARY KEY (chat_id, user_id))""")
db_exec("""CREATE TABLE IF NOT EXISTS fun_ranks (
    chat_id INTEGER, user_id INTEGER, name TEXT, rank TEXT, by_id INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id, rank, by_id))""")
db_exec("""CREATE TABLE IF NOT EXISTS muted (
    chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id))""")
db_exec("""CREATE TABLE IF NOT EXISTS whisper_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
    sender_id INTEGER, sender_name TEXT, target_id INTEGER, target_name TEXT,
    reply_to INTEGER, prompt_id INTEGER, ts INTEGER)""")

# ================================ أدوات عامة ================================
_TASHKEEL = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0640]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def norm(t):
    """توحيد النص العربي: بدون تشكيل، همزات، ى→ي، ة→ه، أرقام عربية→إنجليزية."""
    t = _TASHKEEL.sub("", t or "")
    t = re.sub("[أإآ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").translate(_DIGITS)
    return re.sub(r"\s+", " ", t).strip().lower()


def mention(uid, name):
    return f'<a href="tg://user?id={uid}">{html.escape(name or "عضو")}</a>'


def esc(t):
    return html.escape(t or "")


def btn(text, style=None, **kw):
    """زر inline. style = primary (أزرق) / success (أخضر) / danger (أحمر).
    الألوان تظهر لو مكتبة telebot جديدة، وإلا يطلع الزر بلونه العادي."""
    if style:
        try:
            return types.InlineKeyboardButton(text, style=style, **kw)
        except TypeError:
            pass
    return types.InlineKeyboardButton(text, **kw)


def text_is(*cmds):
    s = {norm(c) for c in cmds}
    return lambda m: bool(m.text) and norm(m.text) in s


def text_starts(*cmds):
    s = {norm(c) for c in cmds}

    def f(m):
        if not m.text:
            return False
        parts = norm(m.text).split()
        return bool(parts) and parts[0] in s

    return f


def on(func):
    """معالج رسائل للقروبات فقط."""
    return bot.message_handler(func=func, chat_types=GROUP)


def split_ref(text):
    """يفصل آخر كلمة لو كانت @معرف أو آيدي رقمي: ('رفع مدير', '@ahmed')."""
    parts = (text or "").split()
    if len(parts) > 1 and (parts[-1].startswith("@") or parts[-1].isdigit()):
        return " ".join(parts[:-1]), parts[-1]
    return " ".join(parts), None


def safe_delete(chat_id, msg_id):
    try:
        bot.delete_message(chat_id, msg_id)
        return True
    except Exception:
        return False


def temp_message(chat_id, text, seconds=8):
    try:
        sent = bot.send_message(chat_id, text)
        threading.Timer(seconds, safe_delete, args=(chat_id, sent.message_id)).start()
    except Exception as e:
        print("temp_message error:", e)


def fmt_time(sec):
    m, s = divmod(int(sec), 60)
    return f"{m} دقيقة و{s} ثانية" if m else f"{s} ثانية"


# ============================ المستخدمون والفلوس ============================
def ensure_user(chat_id, uid, name="عضو", username=None):
    db_exec(
        "INSERT OR IGNORE INTO users (user_id, chat_id, name, username) VALUES (?,?,?,?)",
        (uid, chat_id, name or "عضو", username),
    )


def get_user(chat_id, uid, name="عضو", username=None):
    ensure_user(chat_id, uid, name, username)
    return db_one("SELECT * FROM users WHERE user_id=? AND chat_id=?", (uid, chat_id))


def add_balance(chat_id, uid, amount):
    ensure_user(chat_id, uid)
    db_exec(
        "UPDATE users SET balance = balance + ? WHERE user_id=? AND chat_id=?",
        (amount, uid, chat_id),
    )


def cooldown_left(chat_id, uid, key, seconds):
    """يرجع الثواني المتبقية، أو 0 ويسجّل الاستخدام الحالي."""
    now = time.time()
    row = db_one(
        "SELECT ts FROM cooldowns WHERE chat_id=? AND user_id=? AND key=?",
        (chat_id, uid, key),
    )
    if row and now - row["ts"] < seconds:
        return int(seconds - (now - row["ts"])) + 1
    db_exec("INSERT OR REPLACE INTO cooldowns VALUES (?,?,?,?)", (chat_id, uid, key, now))
    return 0


def acc_number(uid):
    return (uid * 2654435761) % 900000000 + 100000000


# =============================== إعدادات القروب ===============================
DEFAULTS = {"links": 0, "photos": 0, "stickers": 0, "swear": 0,
            "welcome": 1, "replies": 1, "games": 1}
FLAG_LABELS = {
    "links": "🔗 قفل الروابط", "photos": "🖼 قفل الصور",
    "stickers": "🎭 قفل الملصقات", "swear": "🤬 قفل السب",
    "welcome": "👋 الترحيب", "replies": "💬 الردود", "games": "🎮 الألعاب",
}
PROT_FLAGS = ["links", "photos", "stickers", "swear"]

# (الاسم، المفتاح): نعم = مقفول، لا = مفتوح. الصفحة 1 = أول 12، الصفحة 2 = الباقي.
LOCKS = [
    ("الروابط", "links"), ("الكلايش", "lk_kleesh"), ("الكيبورد", "lk_kb"),
    ("الاغاني", "lk_songs"), ("المتحركه", "lk_gif"), ("الملفات", "lk_files"),
    ("الدردشه", "lk_chat"), ("الفيديو", "lk_video"), ("الصور", "photos"),
    ("المعرفات", "lk_mentions"), ("التاك", "lk_tag"), ("البوتات", "lk_bots"),
    ("التوجيه", "lk_fwd"), ("الصوت", "lk_voice"), ("الملصقات", "stickers"),
    ("الجهات", "lk_contact"), ("الدخول", "lk_join"), ("الاضافه", "lk_add"),
    ("بصمه فيديو", "lk_vnote"), ("التثبيت", "lk_pin"), ("الاشعارات", "lk_notif"),
    ("الماركدون", "lk_md"), ("التعديل", "lk_edit"), ("الالعاب", "lk_games"),
    ("التكرار", "lk_flood"),
]
LOCK_PAGES = [LOCKS[:12], LOCKS[12:]]
LOCK_LABEL = {k: l for l, k in LOCKS}
LOCK_BY_NAME = {norm(l): k for l, k in LOCKS}
for _l, _k in LOCKS:
    DEFAULTS.setdefault(_k, 0)


def get_flag(chat_id, key):
    row = db_one("SELECT value FROM chat_settings WHERE chat_id=? AND key=?", (chat_id, key))
    return row["value"] if row else DEFAULTS[key]


def set_flag(chat_id, key, val):
    db_exec("INSERT OR REPLACE INTO chat_settings VALUES (?,?,?)", (chat_id, key, int(val)))


# =================================== الرتب ===================================
# المستوى الأعلى = صلاحية أكبر.
#   منشئ القروب في تيليجرام = مالك اساسي (7) تلقائياً.
#   صاحب البوت (DEV_ID) = الاساسي (8): فوق الكل، في كل القروبات، بكامل الصلاحيات.
RANKS = {"عضو": 0, "مميز": 1, "ادمن": 2, "مدير": 3, "منشئ": 4,
         "مشرف": 5, "مالك": 6, "مالك اساسي": 7, "اساسي": 8}
LEVEL_NAME = {v: k for k, v in RANKS.items()}
TOP_LEVEL = max(RANKS.values())


def rank_label(level):
    """اسم الرتبة بصيغة التعريف للرسائل (عذراً لا تستطيع استخدام الامر على ...)."""
    return {7: "المالك الاساسي", 8: "الاساسي"}.get(level, LEVEL_NAME.get(level, "عضو"))
_member_cache = {}


def tg_status(chat_id, uid):
    key, now = (chat_id, uid), time.time()
    hit = _member_cache.get(key)
    if hit and now - hit[1] < 60:
        return hit[0]
    try:
        status = bot.get_chat_member(chat_id, uid).status
    except Exception:
        status = "member"
    _member_cache[key] = (status, now)
    return status


def rank_name(chat_id, uid):
    """اسم الرتبة للعرض."""
    return LEVEL_NAME[get_level(chat_id, uid)]


def get_level(chat_id, uid):
    if uid in DEV_IDS:  # الاساسي (صاحب البوت): أعلى صلاحية في كل القروبات
        return TOP_LEVEL
    status = tg_status(chat_id, uid)
    if status == "creator":
        return 7
    row = db_one("SELECT rank FROM users WHERE user_id=? AND chat_id=?", (uid, chat_id))
    lvl = RANKS.get(row["rank"], 0) if row else 0
    if status == "administrator":
        lvl = max(lvl, 2)
    return lvl


def canon_rank(s):
    s = norm(s).replace("منشي", "منشئ")
    s = {"المالك الاساسي": "مالك اساسي", "الاساسي": "اساسي", "المالك": "مالك", "المشرف": "مشرف",
         "المدير": "مدير", "المنشئ": "منشئ", "الادمن": "ادمن", "المميز": "مميز"}.get(s, s)
    return s if s in RANKS and s != "عضو" else None


def can_manage(my_level, target_level):
    """الاساسي يتحكم بالكل. مالك اساسي يتحكم بكل رتبة تحته (وزملاءه)، ما عدا الاساسي."""
    return (my_level == TOP_LEVEL or my_level > target_level
            or (my_level >= 7 and target_level <= my_level))


def can_grant(my_level, rank_level):
    """هل أقدر أرفع لهذي الرتبة؟ الاساسي: أي رتبة. مالك اساسي: لين رتبته. غيرهم: تحت رتبتهم."""
    return rank_level < my_level or (my_level >= 7 and rank_level <= my_level)


def require_level(m, min_level):
    lvl = get_level(m.chat.id, m.from_user.id)
    if lvl < min_level:
        bot.reply_to(m, "• عذراً ما عندك رتبة")
        return None
    return lvl


def find_target(m, ref=None):
    """الهدف: من الرد، أو @معرف (لازم تكلم بالقروب قبل)، أو آيدي رقمي."""
    rm = m.reply_to_message
    if rm and rm.from_user:
        return rm.from_user.id, rm.from_user.first_name or "عضو"
    if ref:
        if ref.startswith("@"):
            row = db_one(
                "SELECT user_id, name FROM users WHERE chat_id=? AND lower(username)=?",
                (m.chat.id, ref[1:].lower()),
            )
            if row:
                return row["user_id"], row["name"]
        elif ref.isdigit():
            row = db_one("SELECT name FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, int(ref)))
            return int(ref), (row["name"] if row else "عضو")
    return None


NEED_TARGET = "⚠️ رد على رسالة العضو، أو اكتب المعرف بعد الأمر (مثال: <code>حظر @username</code>)"

# ================================= الحماية =================================
LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.I)
BAD_WORDS = {norm(w) for w in ["كلب", "حمار", "تيس", "منفس", "لعن", "قحبة", "خنيث"]}  # زوّد عليها
VIOLATION_MSG = {
    "photos": "ممنوع إرسال الصور هني طال عمرك 🚫",
    "stickers": "ممنوع إرسال الملصقات هني 🚫",
    "links": "ممنوع نشر الروابط في هذا القروب 🚫",
    "swear": "احترم نفسك، ممنوع السب والكلمات النابية هني 🇦🇪",
}


def has_link(m, text):
    ents = (m.entities or []) + (m.caption_entities or [])
    if any(e.type in ("url", "text_link") for e in ents):
        return True
    return bool(LINK_RE.search(text))


def has_bad_word(text):
    for tok in re.findall(r"[\u0600-\u06FF]+", norm(text)):
        if tok in BAD_WORDS or (tok.startswith("ال") and tok[2:] in BAD_WORDS):
            return True
    return False


def media_key(msg):
    """مفتاح يميز محتوى الرسالة (للمنع بالرد)."""
    ct = msg.content_type
    if ct == "text":
        return ("text", norm(msg.text))
    if ct == "photo":
        return ("photo", msg.photo[-1].file_unique_id)
    obj = getattr(msg, ct, None)
    if obj is not None and hasattr(obj, "file_unique_id"):
        return (ct, obj.file_unique_id)
    return None


FORMAT_ENTS = {"bold", "italic", "underline", "strikethrough", "spoiler",
               "code", "pre", "text_link", "blockquote"}
SIMPLE_LOCKS = {"photo": "photos", "sticker": "stickers", "video": "lk_video",
                "animation": "lk_gif", "document": "lk_files", "audio": "lk_songs",
                "voice": "lk_voice", "video_note": "lk_vnote", "contact": "lk_contact"}
_flood = {}


def is_forwarded(m):
    return bool(getattr(m, "forward_origin", None) or getattr(m, "forward_date", None))


def lock_violation(m, chat_id, text):
    """يرجع مفتاح القفل المخالف أو None."""
    flags = {r["key"]: r["value"] for r in
             db_all("SELECT key, value FROM chat_settings WHERE chat_id=?", (chat_id,))}
    g = lambda k: flags.get(k, DEFAULTS.get(k, 0))
    ct = m.content_type
    ents = (m.entities or []) + (m.caption_entities or [])
    et = {e.type for e in ents}

    key = media_key(m)
    if key and key[1]:
        for r in db_all("SELECT key FROM blocklist WHERE chat_id=? AND kind=?", (chat_id, key[0])):
            if r["key"] == key[1] or (key[0] == "text" and r["key"] and r["key"] in key[1]):
                return "blocked"
    k = SIMPLE_LOCKS.get(ct)
    if k and g(k):
        return k
    if ct == "text" and g("lk_chat"):
        return "lk_chat"
    if g("links") and has_link(m, text):
        return "links"
    if g("lk_kleesh") and len(text) > 250:
        return "lk_kleesh"
    if g("lk_kb") and getattr(m, "reply_markup", None) is not None:
        return "lk_kb"
    if g("lk_mentions") and ("mention" in et or re.search(r"@\w{4,}", text)):
        return "lk_mentions"
    if g("lk_tag") and "hashtag" in et:
        return "lk_tag"
    if g("lk_fwd") and is_forwarded(m):
        return "lk_fwd"
    if g("lk_md") and (et & FORMAT_ENTS):
        return "lk_md"
    if g("lk_flood"):
        now = time.time()
        q = [t for t in _flood.get((chat_id, m.from_user.id), []) if now - t < 6]
        q.append(now)
        _flood[(chat_id, m.from_user.id)] = q
        if len(q) > 5:
            return "lk_flood"
    if (g("swear") and has_bad_word(text)
            and (norm(text).split() or [""])[0] not in ("رفع", "تنزيل", "مسح")):
        return "swear"
    return None


def _shield(m):
    user = m.from_user
    if user and user.is_bot and user.id != BOT_ID:
        db_exec("INSERT OR IGNORE INTO bots_seen VALUES (?,?,?)",
                (m.chat.id, user.id, user.first_name or "بوت"))
    if not user or user.is_bot or user.id == ANON_ADMIN_ID:
        return False
    chat_id = m.chat.id
    name = user.first_name or "عضو"
    ensure_user(chat_id, user.id, name, user.username)
    # المكتوم: أي رسالة يرسلها تنحذف بصمت
    if db_one("SELECT 1 FROM muted WHERE chat_id=? AND user_id=?", (chat_id, user.id)):
        if safe_delete(chat_id, m.message_id):
            return True
    db_exec(
        "UPDATE users SET messages = messages + 1, name=?, username=? WHERE user_id=? AND chat_id=?",
        (name, user.username, user.id, chat_id),
    )
    if get_level(chat_id, user.id) >= 1:  # المميزون وما فوق مستثنون من القفل
        return False

    text = m.text or m.caption or ""
    reason = lock_violation(m, chat_id, text)
    if not reason:
        return False
    if not safe_delete(chat_id, m.message_id):
        return False  # البوت ما عنده صلاحية حذف
    db_exec("UPDATE users SET warns = warns + 1 WHERE user_id=? AND chat_id=?", (user.id, chat_id))
    if reason == "blocked":
        msg = "هذي الرسالة ممنوعة هني 🚫"
    else:
        msg = VIOLATION_MSG.get(reason) or f"{LOCK_LABEL.get(reason, 'هذا')} مقفول هني 🚫"
    if reason != "lk_flood":
        temp_message(chat_id, f"❌ {mention(user.id, name)}، {msg}")
    return True


def apply_alias(m):
    """الأوامر المضافة: يحوّل الكلمة الجديدة لأمرها القديم قبل ما تمر على المعالجات."""
    if not m.text:
        return
    parts = m.text.split(None, 1)
    row = db_one("SELECT old_cmd FROM aliases WHERE chat_id=? AND new_cmd=?",
                 (m.chat.id, norm(parts[0])))
    if row:
        m.text = row["old_cmd"] + (" " + parts[1] if len(parts) > 1 else "")


def shield(m):
    try:
        apply_alias(m)
        return _shield(m)
    except Exception as e:
        print("shield error:", e)
        return False


# ⚠️ لازم يتسجّل أول معالج: يشتغل على كل رسالة (عدّ + حماية) ويكمل للمعالجات الباقية
# إلا لو حذف الرسالة المخالفة. (هذا كان سبب تعطّل الرتب عندك: المعالج القديم كان يبلع كل النصوص)
@bot.message_handler(func=shield, content_types=ALL_TYPES, chat_types=GROUP)
def _shield_consumed(m):
    pass


def get_text(chat_id, key):
    row = db_one("SELECT value FROM chat_texts WHERE chat_id=? AND key=?", (chat_id, key))
    return row["value"] if row else None


def set_text(chat_id, key, value):
    db_exec("INSERT OR REPLACE INTO chat_texts VALUES (?,?,?)", (chat_id, key, value))


def del_text(chat_id, key):
    db_exec("DELETE FROM chat_texts WHERE chat_id=? AND key=?", (chat_id, key))


def content_of(msg):
    """(النوع، file_id، النص) لحفظ رد."""
    ct = msg.content_type
    if ct == "text":
        return ("text", None, msg.text)
    if ct == "photo":
        return ("photo", msg.photo[-1].file_id, msg.caption)
    obj = getattr(msg, ct, None)
    if obj is not None and hasattr(obj, "file_id"):
        return (ct, obj.file_id, getattr(msg, "caption", None))
    return None


# ---- إدخال متعدد الخطوات: اضف رد / اضف امر / ضع الترحيب / ضع رابط / تعيين الايدي ----
pending_input = {}  # (chat_id, user_id) -> {"kind", "step", "data", "until"}


def _pending_filter(m):
    if m.from_user is None:
        return False
    st = pending_input.get((m.chat.id, m.from_user.id))
    if not st:
        return False
    if st["until"] < time.time():
        pending_input.pop((m.chat.id, m.from_user.id), None)
        return False
    return True


@bot.message_handler(func=_pending_filter, content_types=ALL_TYPES, chat_types=GROUP)
def pending_handler(m):
    key = (m.chat.id, m.from_user.id)
    st = pending_input.get(key)
    if not st:
        return
    chat_id, kind = m.chat.id, st["kind"]
    if m.text and norm(m.text) == "الغاء":
        pending_input.pop(key, None)
        bot.reply_to(m, "✅ تم الالغاء.")
        return
    st["until"] = time.time() + 120
    if kind in ("reply", "reply_vip"):
        if st["step"] == 0:
            if not m.text:
                bot.reply_to(m, "• ارسل الكلمة كنص.")
                return
            st["data"]["word"] = norm(m.text)
            st["step"] = 1
            bot.reply_to(m, "• تمام، الحين ارسل الرد (نص / صورة / ملصق / متحركة / فيديو / صوت).")
            return
        c = content_of(m)
        if not c:
            bot.reply_to(m, "• هذا النوع غير مدعوم، ارسل نص أو صورة أو ملصق...")
            return
        table = "vip_replies" if kind == "reply_vip" else "replies"
        db_exec(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?)",
                (chat_id, st["data"]["word"], c[0], c[1], c[2]))
        pending_input.pop(key, None)
        bot.reply_to(m, "• تم حفظ الرد المميز بنجاح ✅\n• يرد فقط على أصحاب الرتب" if kind == "reply_vip"
                     else "• تم حفظ الرد بنجاح ✅")
    elif kind == "cmd":
        if not m.text:
            bot.reply_to(m, "• ارسل نص فقط.")
            return
        if st["step"] == 0:
            st["data"]["old"] = m.text.strip()
            st["step"] = 1
            bot.reply_to(m, "• تمام، الحين ارسل الامر الجديد (كلمة وحدة).")
            return
        new = norm(m.text).split()[0] if norm(m.text) else ""
        if not new:
            bot.reply_to(m, "• ارسل كلمة صحيحة.")
            return
        db_exec("INSERT OR REPLACE INTO aliases VALUES (?,?,?)", (chat_id, new, st["data"]["old"]))
        pending_input.pop(key, None)
        bot.reply_to(m, f"• تم اضافة الامر بنجاح ✅\n• ({esc(new)}) ↢ ({esc(st['data']['old'])})")
    else:  # welcome / link / id
        if not m.text:
            bot.reply_to(m, "• ارسل نص فقط.")
            return
        set_text(chat_id, kind, m.text.strip())
        pending_input.pop(key, None)
        bot.reply_to(m, {"welcome": "• تم حفظ الترحيب بنجاح ✅",
                         "link": "• تم حفظ الرابط بنجاح ✅",
                         "id": "• تم حفظ قالب الايدي بنجاح ✅"}[kind])


# ============================ الترحيب والمساعدة ============================
HELP_TEXT = (
    "🤖 <b>أوامر سرداب</b>\n\n"
    "🛡 <b>الحماية</b> (للمشرفين)\n"
    "• تفعيل الحماية / تعطيل الحماية\n"
    "• الاعدادات ← أزرار تحكم كاملة\n\n"
    "👮 <b>الإدارة</b> (بالرد على العضو أو @المعرف)\n"
    "• حظر / الغاء الحظر / طرد\n"
    "• كتم (تنحذف رسائله) / الغاء الكتم / المكتومين\n"
    "• تقييد (ما يقدر يكتب) / الغاء التقييد / رفع القيود\n\n"
    "🎖 <b>الرتب</b>\n"
    "• رفع [الرتبة] / تنزيل / رتبتي / الرتب / فحص\n"
    "• الرتب: مميز، ادمن، مدير، منشئ، مشرف، مالك، مالك اساسي، اساسي\n"
    "• الاساسي ← مين صاحب رتبة الاساسي (فوق الكل)\n\n"
    "😂 <b>رتب التسلية</b> (بالرد)\n"
    "• رفع / تنزيل: هطف، بثر، حمار، كلب، كلبه، عتوي، عتويه،\n"
    "  لحجي، لحجيه، خروف، خفيفه، خفيف\n"
    "• القوائم: الهطوف، البثرين، الحمير، الكلاب، الكلبات، العتوين، العتويات،\n"
    "  اللحوج، اللحجيات، الخرفان، الخفيفات، الخفيفين\n"
    "• رفع بقلبي / تنزيل من قلبي\n"
    "• مسح [القائمة] مثل: مسح الهطوف\n\n"
    "👑 <b>المالك</b>\n• اكتب: المالك\n\n"
    "📢 <b>منشن</b>\n• @all [رسالة] ← يمنشن الكل (للمشرفين)\n\n"
    "💬 <b>الردود</b>\n• اضف رد / اضف رد مميز (لأصحاب الرتب فقط) / الردود / حذف رد + الكلمة\n\n"
    "🤫 <b>الهمسات</b>\n"
    "• اهمس [النص] ← بالرد على العضو\n"
    "• اهمس @معرف [النص]\n\n"
    "🎮 <b>الألعاب</b>\n"
    "• نرد، سهم، سلة، كورة، بولينج، سلوت\n"
    "• حجرة ورقة مقص\n"
    "• سرعة، حساب، خمن، حزورة (ايقاف لإنهاء اللعبة)\n"
    "• صراحة، لو خيروك، كت\n\n"
    "💍 <b>الزواج</b>\n"
    "• زواج [مهر] بالرد / طلاق / زواجي\n\n"
    "💰 <b>البنك</b>\n"
    "• انشاء حساب بنكي (الامارات / اديب / المشرق)، فلوسي، راتب\n"
    "• رهان [مبلغ]، تحويل [مبلغ]، زرف\n"
    "• توب"
)


@bot.message_handler(commands=["start", "help"])
def start_cmd(m):
    if m.chat.type == "private":
        parts = (m.text or "").split(maxsplit=1)
        if len(parts) > 1 and handle_start_payload(m, parts[1].strip()):
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(btn("➕ اضفني لمجموعتك", style="success",
                   url=f"https://t.me/{BOT_USERNAME}?startgroup=true&admin=delete_messages+restrict_members"))
        if DEV_URL:
            kb.add(btn(DEV_NAME, url=DEV_URL))
        if CHANNEL_URL:
            kb.add(btn("📢 قناة التحديثات", style="success", url=CHANNEL_URL))
        kb.add(btn("📖 الاوامر", callback_data="help_menu"))
        bot.send_message(m.chat.id, WELCOME_PRIVATE, reply_markup=kb)
    else:
        bot.reply_to(m, HELP_TEXT)


MENU_HOME = ("- أهلاً بك عزيزي في قائمة الاوامر 🟣\n————————————\n"
             "◂ م1 : اوامر الادمنيه\n◂ م2 : اوامر الاعدادات\n"
             "◂ م3 : اوامر القفل - الفتح\n◂ م4 : اوامر التسليه\n————————————")
MENU_PAGES = {
    "1": ("- أهلاً بك عزيزي في قائمة اوامر الادمنيه\n————————————\n"
          "- اوامر الرفع والتنزيل :\n\n"
          "• رفع - تنزيل اساسي\n• رفع - تنزيل مالك اساسي\n• رفع - تنزيل مالك\n• رفع - تنزيل مشرف\n"
          "• رفع - تنزيل منشئ\n• رفع - تنزيل مدير\n• رفع - تنزيل ادمن\n• رفع - تنزيل مميز\n"
          "• تنزيل الكل - لازاله جميع الرتب اعلاه\n\n"
          "- اوامر المسح :\n\n"
          "• مسح الكل\n• مسح المنشئين\n• مسح المدراء\n• مسح المالكين\n• مسح الادمنيه\n"
          "• مسح المميزين\n• مسح المحظورين\n• مسح المكتومين\n• مسح قائمه المنع\n"
          "• مسح الردود\n• مسح الاوامر المضافه\n• مسح + عدد\n• مسح بالرد\n"
          "• مسح الايدي\n• مسح الترحيب\n• مسح الرابط\n\n"
          "- اوامر الطرد والحظر :\n\n"
          "• تقييد + الوقت (مثال: تقييد 10 د)\n• حظر\n• طرد\n• كتم\n• تقييد\n"
          "• الغاء الحظر\n• الغاء الكتم\n• الغاء التقييد\n• رفع القيود\n"
          "• منع بالرد\n• الغاء منع بالرد\n• قائمه المنع\n• المحظورين\n• طرد البوتات"),
    "2": ("- أهلاً بك عزيزي في قائمة اوامر الاعدادات\n————————————\n\n"
          "• الاعدادات\n• ضع الترحيب / مسح الترحيب\n• ضع رابط / الرابط / انشاء رابط / مسح الرابط\n"
          "• تعيين الايدي / ايدي / مسح الايدي\n• اضف رد / اضف رد مميز / الردود / حذف رد + الكلمة / مسح الردود\n"
          "• @all ← منشن للكل (للمشرفين)\n"
          "• اضف امر / الاوامر المضافه / مسح الاوامر المضافه\n"
          "• تفعيل الحماية / تعطيل الحماية\n\n"
          "- اثناء الاضافه اكتب (الغاء) لإيقاف العملية"),
    "3": ("- أهلاً بك عزيزي في قائمة اوامر القفل والفتح\n————————————\n\n"
          "• قفل + الاسم  /  فتح + الاسم\n\n- الاسماء :\n\n"
          + "\n".join(f"• {l}" for l, _ in LOCKS)),
    "4": ("- أهلاً بك عزيزي في قائمة اوامر التسليه\n————————————\n\n"
          "• رفع / تنزيل : هطف، بثر، حمار، كلب، كلبه، عتوي، عتويه، لحجي، لحجيه، خروف، خفيفه، خفيف\n"
          "• رفع بقلبي / تنزيل من قلبي\n• المالك\n• اهمس\n• انشاء حساب بنكي، فلوسي، راتب، رهان، تحويل، زرف\n"
          "• نرد، سهم، سلة، كورة، بولينج، سلوت، حجرة ورقة مقص\n"
          "• سرعة، حساب، خمن، حزورة، صراحة، لو خيروك، كت\n• زواج، طلاق، زواجي، توب"),
}


def menu_markup(cur=None):
    kb = types.InlineKeyboardMarkup()

    def b(n):
        if cur == n:
            return types.InlineKeyboardButton(f"({n})", callback_data="mn:" + n)
        return btn(n, style="danger", callback_data="mn:" + n)

    kb.row(b("1"))
    kb.row(b("2"), b("3"), b("4"))
    kb.row(btn("القفل والفتح 🔐", style="primary", callback_data="mn:lock"),
           btn("تفعيل والتعطيل", style="primary", callback_data="mn:toggle"))
    extra = []
    if DEV_URL:
        extra.append(btn(DEV_NAME, style="success", url=DEV_URL))
    if CHANNEL_URL:
        extra.append(btn("تحديثات البوت", style="success", url=CHANNEL_URL))
    if extra:
        kb.row(*extra)
    return kb


@on(text_is("الاوامر", "اوامر", "المساعدة"))
def help_cmd(m):
    bot.reply_to(m, MENU_HOME, reply_markup=menu_markup())


def kick_user(chat_id, uid):
    try:
        bot.ban_chat_member(chat_id, uid)
        bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        return True
    except Exception as e:
        print("kick error:", e)
        return False


def announce_activation(m):
    """رسالة التفعيل التلقائي عند إضافة البوت للقروب."""
    chat_id = m.chat.id
    adder = m.from_user
    admins_count = 0
    try:
        admins_count = sum(1 for a in bot.get_chat_administrators(chat_id) if not a.user.is_bot)
    except Exception:
        pass
    is_admin = False
    try:
        is_admin = bot.get_chat_member(chat_id, BOT_ID).status == "administrator"
    except Exception:
        pass
    txt = ("• المجموعه تم تفعيلها تلقائي\n"
           f"• بواسطة ↢ {mention(adder.id, adder.first_name) if adder else 'غير معروف'}\n"
           f"• عدد الادمنيه ↢ {admins_count}\n")
    if not is_admin:
        txt += "• ⚠️ ارفعني مشرف (حذف الرسائل + تقييد الأعضاء) عشان تشتغل الحماية\n"
    txt += "-"
    kb = types.InlineKeyboardMarkup(row_width=1)
    url = f"https://t.me/{m.chat.username}" if getattr(m.chat, "username", None) else None
    if not url:
        try:
            url = bot.export_chat_invite_link(chat_id)
        except Exception:
            url = None
    if url:
        kb.add(btn(m.chat.title or ".", style="success", url=url))
    kb.add(types.InlineKeyboardButton("⚙️ الاعدادات", callback_data="settings_menu"))
    bot.send_message(chat_id, txt, reply_markup=kb)


@bot.message_handler(content_types=["new_chat_members"])
def on_new_members(m):
    chat_id = m.chat.id
    adder = m.from_user
    for member in m.new_chat_members:
        if member.id == BOT_ID:
            announce_activation(m)
            continue
        adder_lvl = get_level(chat_id, adder.id) if adder else 0
        self_join = adder is None or adder.id == member.id
        if member.is_bot:
            db_exec("INSERT OR IGNORE INTO bots_seen VALUES (?,?,?)",
                    (chat_id, member.id, member.first_name or "بوت"))
            if get_flag(chat_id, "lk_bots") and adder_lvl < 2:
                kick_user(chat_id, member.id)
            continue
        if get_flag(chat_id, "lk_join") and (self_join or adder_lvl < 2):
            kick_user(chat_id, member.id)
            continue
        if get_flag(chat_id, "lk_add") and not self_join and adder_lvl < 2:
            kick_user(chat_id, member.id)
            continue
        ensure_user(chat_id, member.id, member.first_name or "عضو", member.username)
        if get_flag(chat_id, "welcome"):
            custom = get_text(chat_id, "welcome")
            if custom:
                bot.send_message(chat_id, custom.replace("{name}", mention(member.id, member.first_name))
                                 .replace("{group}", esc(m.chat.title)))
            else:
                bot.send_message(chat_id, f"هلا والله {mention(member.id, member.first_name)} "
                                          f"نوّرت {esc(m.chat.title)} 🌟")
    if get_flag(chat_id, "lk_notif"):
        safe_delete(chat_id, m.message_id)


@bot.message_handler(content_types=["left_chat_member", "pinned_message", "new_chat_title",
                                    "new_chat_photo", "delete_chat_photo"])
def service_messages(m):
    try:
        chat_id = m.chat.id
        if m.content_type == "pinned_message" and get_flag(chat_id, "lk_pin"):
            who = m.from_user
            if who and who.id != BOT_ID and get_level(chat_id, who.id) < 6:
                try:
                    bot.unpin_chat_message(chat_id, m.pinned_message.message_id)
                except Exception as e:
                    print("unpin error:", e)
        if get_flag(chat_id, "lk_notif"):
            safe_delete(chat_id, m.message_id)
    except Exception as e:
        print("service error:", e)


@bot.edited_message_handler(func=lambda m: True, content_types=ALL_TYPES, chat_types=GROUP)
def edited_lock(m):
    try:
        u = m.from_user
        if not u or u.is_bot or u.id == ANON_ADMIN_ID:
            return
        if get_flag(m.chat.id, "lk_edit") and get_level(m.chat.id, u.id) < 1:
            safe_delete(m.chat.id, m.message_id)
    except Exception as e:
        print("edit lock error:", e)


# =============================== ردود سرداب ===============================
@on(lambda m: bool(m.text)
    and len(m.text.split()) <= 4
    and {"بوت", "سرداب"} & set(norm(m.text).split()))
def sardab_reply(m):
    if not get_flag(m.chat.id, "replies"):
        return
    n = mention(m.from_user.id, m.from_user.first_name)
    bot.reply_to(m, random.choice([
        f"لبيه يا {n}، أمرني عيون سرداب تحت خدمتك! 🇦🇪✨",
        f"هلا والله ومرحب يا {n}، سرداب يحييك! 🤍",
        f"حيّ الله هالوجه يا {n}، سرداب حاضر وجاهز لأي فزعة! 😎",
        f"أمر طال عمرك يا {n}، سرداب معاك ☕️",
        f"سمعني صوتك يا {n}، سرداب تحت طوعك وتحت أمرك! 🌟",
    ]))


# ============================ تفعيل / تعطيل الحماية ============================
@on(text_is("تفعيل الحماية", "تعطيل الحماية"))
def toggle_protection(m):
    if require_level(m, 2) is None:
        return
    enable = norm(m.text) == norm("تفعيل الحماية")
    for k in PROT_FLAGS:
        set_flag(m.chat.id, k, enable)
    if enable:
        bot.reply_to(m, "🛡 <b>تم تفعيل حماية سرداب الشاملة!</b>\n• قفل: الروابط، الصور، الملصقات، السب")
    else:
        bot.reply_to(m, "⚠️ <b>تم تعطيل الحماية الشاملة للقروب.</b>")


# ================================ الإدارة ================================
MOD_ACTIONS = {
    "حظر": "ban", "الغاء الحظر": "unban", "طرد": "kick",
    "كتم": "mute", "الغاء الكتم": "unmute",
    "تقييد": "restrict", "الغاء التقييد": "unrestrict", "رفع القيود": "free",
}
MOD_NORM = {norm(k): v for k, v in MOD_ACTIONS.items()}
MUTED = types.ChatPermissions(can_send_messages=False)
RESTRICTED = types.ChatPermissions(can_send_messages=True)  # نص فقط
FULL = types.ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True,
)


@on(lambda m: bool(m.text) and norm(split_ref(m.text)[0]) in MOD_NORM)
def moderation(m):
    my = require_level(m, 2)  # لازم ادمن فأعلى (مهم: كانت مفتوحة للجميع!)
    if my is None:
        return
    cmd_text, ref = split_ref(m.text)
    action = MOD_NORM[norm(cmd_text)]
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, NEED_TARGET)
        return
    tid, tname = target
    if tid == BOT_ID or tid == m.from_user.id:
        bot.reply_to(m, "😅 ما يصير يا الغالي.")
        return
    tl = get_level(m.chat.id, tid)
    trow = db_one("SELECT rank FROM users WHERE user_id=? AND chat_id=?", (tid, m.chat.id))
    if action in ("ban", "kick", "mute", "restrict") and trow and trow["rank"] != "عضو":
        # صاحب رتبة محمي من الحظر والكتم والتقييد والطرد، لازم تنزل رتبته أول
        bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {trow['rank']}\n"
                        f"• نزّل رتبته أولاً بأمر (تنزيل)")
        return
    if not can_manage(my, tl):
        bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {rank_label(tl)}")
        return
    chat_id, who = m.chat.id, mention(tid, tname)
    try:
        if action == "ban":
            bot.ban_chat_member(chat_id, tid)
            db_exec("INSERT OR REPLACE INTO banned VALUES (?,?,?)", (chat_id, tid, tname))
            bot.reply_to(m, f"• تم حظره بنجاح\n• المستخدم ↢ {who}")
        elif action == "unban":
            bot.unban_chat_member(chat_id, tid, only_if_banned=True)
            db_exec("DELETE FROM banned WHERE chat_id=? AND user_id=?", (chat_id, tid))
            bot.reply_to(m, f"• تم الغاء حظره بنجاح\n• المستخدم ↢ {who}")
        elif action == "kick":
            bot.ban_chat_member(chat_id, tid)
            bot.unban_chat_member(chat_id, tid, only_if_banned=True)
            bot.reply_to(m, f"• تم طرده بنجاح (يقدر يرجع بالرابط)\n• المستخدم ↢ {who}")
        elif action == "mute":  # كتم: رسائله تنحذف تلقائياً (يحتاج صلاحية حذف الرسائل)
            db_exec("INSERT OR IGNORE INTO muted (chat_id, user_id) VALUES (?,?)", (chat_id, tid))
            bot.reply_to(m, f"• تم كتمه بنجاح\n• المستخدم ↢ {who}")
        elif action == "unmute":
            db_exec("DELETE FROM muted WHERE chat_id=? AND user_id=?", (chat_id, tid))
            bot.reply_to(m, f"• تم الغاء كتمه بنجاح\n• المستخدم ↢ {who}")
        elif action == "restrict":  # تقييد: تيليجرام نفسه يمنعه من الكتابة
            bot.restrict_chat_member(chat_id, tid, permissions=MUTED)
            bot.reply_to(m, f"• تم تقييده بنجاح\n• المستخدم ↢ {who}")
        elif action == "unrestrict":
            bot.restrict_chat_member(chat_id, tid, permissions=FULL)
            bot.reply_to(m, f"• تم الغاء تقييده بنجاح\n• المستخدم ↢ {who}")
        elif action == "free":  # رفع القيود: يشيل الكتم والتقييد مع بعض
            db_exec("DELETE FROM muted WHERE chat_id=? AND user_id=?", (chat_id, tid))
            bot.restrict_chat_member(chat_id, tid, permissions=FULL)
            bot.reply_to(m, f"• تم رفع القيود عنه بنجاح\n• المستخدم ↢ {who}")
    except Exception as e:
        bot.reply_to(m, f"❌ ما قدرت أنفذ (تأكد أن البوت مشرف وعنده الصلاحيات):\n<code>{esc(str(e))}</code>")



# ============================== رتب التسلية (رفع / تنزيل) ==============================
# رتب للتسلية فقط: ما تأثر على الصلاحيات، ولا تمنع الحظر أو الكتم أو التقييد.
FUN_RANKS = {
    "هطف": "الهطوف", "بثر": "البثرين", "حمار": "الحمير",
    "كلب": "الكلاب", "كلبه": "الكلبات",
    "عتوي": "العتوين", "عتويه": "العتويات",
    "لحجي": "اللحوج", "لحجيه": "اللحجيات",
    "خروف": "الخرفان",
    "خفيفه": "الخفيفات", "خفيف": "الخفيفين",
}
FUN_SINGLE = {norm(k): k for k in FUN_RANKS}
FUN_PLURAL = {norm(v): k for k, v in FUN_RANKS.items()}
FUN_FEMALE = {"كلبه", "عتويه", "لحجيه", "خفيفه"}


def _fun_filter(m):
    if not m.text:
        return False
    parts = norm(split_ref(m.text)[0]).split()
    if len(parts) < 2:
        return False
    if parts[0] == "رفع":
        return parts[1] in FUN_SINGLE or parts[1] == "بقلبي"
    if parts[0] == "تنزيل":
        return parts[1] in FUN_SINGLE or parts[1:] == ["من", "قلبي"]
    return False


@on(_fun_filter)
def fun_rank(m):
    cmd_text, ref = split_ref(m.text)
    parts = norm(cmd_text).split()
    action, what = parts[0], " ".join(parts[1:])
    heart = what in ("بقلبي", "من قلبي")
    if not heart and require_level(m, 2) is None:  # رتب التسلية للمشرفين، (بقلبي) للكل
        return
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, NEED_TARGET)
        return
    tid, tname = target
    if tid == BOT_ID:
        bot.reply_to(m, "😎 أنا فوق الرتب يا الغالي.")
        return
    who = mention(tid, tname)
    chat_id = m.chat.id
    if heart:
        me = m.from_user.id
        if action == "رفع":
            if db_one("SELECT 1 FROM fun_ranks WHERE chat_id=? AND user_id=? AND rank='بقلبي' AND by_id=?",
                      (chat_id, tid, me)):
                bot.reply_to(m, f"• تم رفعه بقلبك مسبقاً\n• المستخدم ↢ {who}")
                return
            db_exec("INSERT INTO fun_ranks VALUES (?,?,?,?,?)", (chat_id, tid, tname, "بقلبي", me))
            bot.reply_to(m, f"• تم رفعه بقلبك بنجاح ❤️\n• المستخدم ↢ {who}")
        else:
            db_exec("DELETE FROM fun_ranks WHERE chat_id=? AND user_id=? AND rank='بقلبي' AND by_id=?",
                    (chat_id, tid, me))
            bot.reply_to(m, f"• تم تنزيله من قلبك بنجاح 💔\n• المستخدم ↢ {who}")
        return
    rank = FUN_SINGLE[what]
    he = "ها" if rank in FUN_FEMALE else "ه"
    row = db_one("SELECT 1 FROM fun_ranks WHERE chat_id=? AND user_id=? AND rank=? AND by_id=0",
                 (chat_id, tid, rank))
    if action == "رفع":
        if row:
            bot.reply_to(m, f"• تم رفع{he} {rank} مسبقاً\n• المستخدم ↢ {who}")
            return
        db_exec("INSERT INTO fun_ranks VALUES (?,?,?,?,0)", (chat_id, tid, tname, rank))
        bot.reply_to(m, f"• تم رفع{he} {rank} بنجاح\n• المستخدم ↢ {who}")
    else:
        if not row:
            bot.reply_to(m, f"• تم تنزيل{he} مسبقاً من {rank}\n• المستخدم ↢ {who}")
            return
        db_exec("DELETE FROM fun_ranks WHERE chat_id=? AND user_id=? AND rank=? AND by_id=0",
                (chat_id, tid, rank))
        bot.reply_to(m, f"• تم تنزيل{he} من رتبة {rank}\n• المستخدم ↢ {who}")


def _fun_list_filter(m):
    if not m.text:
        return False
    t = norm(m.text)
    return t in FUN_PLURAL or (t.startswith("مسح ") and t[4:] in FUN_PLURAL)


@on(_fun_list_filter)
def fun_list(m):
    t = norm(m.text)
    if t.startswith("مسح "):
        if require_level(m, 2) is None:
            return
        rank = FUN_PLURAL[t[4:]]
        db_exec("DELETE FROM fun_ranks WHERE chat_id=? AND rank=? AND by_id=0", (m.chat.id, rank))
        bot.reply_to(m, f"• تم مسح {FUN_RANKS[rank]} بنجاح")
        return
    rank = FUN_PLURAL[t]
    rows = db_all("SELECT user_id, name FROM fun_ranks WHERE chat_id=? AND rank=? AND by_id=0",
                  (m.chat.id, rank))
    if not rows:
        bot.reply_to(m, f"📂 ما فيه {FUN_RANKS[rank]} في هذا القروب.")
        return
    bot.reply_to(m, f"📂 <b>{FUN_RANKS[rank]}:</b>\n\n"
                    + "\n".join(f"• {mention(r['user_id'], r['name'])}" for r in rows))


# ================================= المالك =================================
def find_owner(chat_id):
    """مالك القروب في تيليجرام، وإلا أول من رُفع (مالك اساسي) بالبوت."""
    try:
        for a in bot.get_chat_administrators(chat_id):
            if a.status == "creator":
                return a.user.id, a.user.first_name or "المالك", a.user.username
    except Exception as e:
        print("find_owner error:", e)
    row = db_one("SELECT user_id, name, username FROM users WHERE chat_id=? AND rank='مالك اساسي'", (chat_id,))
    if row:
        return row["user_id"], row["name"] or "المالك", row["username"]
    return None


@on(text_is("المالك", "مالك القروب", "مالك المجموعه", "مالك الجروب"))
def show_owner(m):
    owner = find_owner(m.chat.id)
    if not owner:
        bot.reply_to(m, "⚠️ ما قدرت أحدد مالك القروب (تأكد أن البوت مشرف).")
        return
    oid, oname, ouser = owner
    bio = ""
    try:
        bio = (bot.get_chat(oid).bio or "").strip()
    except Exception:
        pass
    caption = (f"• USE ↦ {mention(oid, oname)}"
               + (f" ( @{esc(ouser)} )" if ouser else "")
               + f"\n\n• bio ↦ {esc(bio) if bio else 'لا يوجد'}")
    kb = types.InlineKeyboardMarkup()
    kb.add(btn(oname[:30], url=f"https://t.me/{ouser}" if ouser else f"tg://user?id={oid}"))
    try:
        photos = bot.get_user_profile_photos(oid, limit=1)
        if photos.total_count:
            bot.send_photo(m.chat.id, photos.photos[0][-1].file_id, caption=caption,
                           reply_markup=kb, reply_to_message_id=m.message_id)
            return
    except Exception as e:
        print("owner photo error:", e)
    try:
        bot.reply_to(m, caption, reply_markup=kb)
    except Exception:
        bot.reply_to(m, caption)


# ============================== ردود تلقائية على كلمات ==============================
AUTO_REPLIES = {
    "السلام عليكم": ["وعليكم السلام ورحمة الله وبركاته"],
    "خاص": ["عيب عليكم"],
    "احبك": ["اعشقك", "اموت فيك", "اموت في حبك"],
    "فديتك": ["فداك يابعدي", "فدا خشمك", "مواح"],
    "حييك": ["حيي عينك"],
    "طع": ["طع ويهك"],
    "تحبني": ["لا"],
    "الله يلعنك": ["اللعن حرام"],
}
AUTO_NORM = {norm(k): v for k, v in AUTO_REPLIES.items()}


def _auto_key(m):
    if not m.text:
        return None
    t = norm(m.text)
    if t in AUTO_NORM:
        return t
    # السلام عليكم ورحمة الله وبركاته (وأي إضافة بعدها)
    if t.startswith("السلام عليكم"):
        return norm("السلام عليكم")
    return None


@on(lambda m: _auto_key(m) is not None)
def auto_replies(m):
    if not get_flag(m.chat.id, "replies"):
        return
    bot.reply_to(m, random.choice(AUTO_NORM[_auto_key(m)]))



# ============================ المسح / المنع / الطرد / الاضافات ============================
MASAH_RANKS = {"المنشئين": "منشئ", "المدراء": "مدير", "المالكين": "مالك", "الاساسيين": "اساسي",
               "الادمنيه": "ادمن", "المميزين": "مميز", "المشرفين": "مشرف"}


def mod_guard(m, my, tid):
    if tid == BOT_ID or tid == m.from_user.id:
        bot.reply_to(m, "😅 ما يصير يا الغالي.")
        return False
    tl = get_level(m.chat.id, tid)
    trow = db_one("SELECT rank FROM users WHERE user_id=? AND chat_id=?", (tid, m.chat.id))
    if trow and trow["rank"] != "عضو":
        bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {trow['rank']}\n• نزّل رتبته أولاً بأمر (تنزيل)")
        return False
    if not can_manage(my, tl):
        bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {rank_label(tl)}")
        return False
    return True


# ---- تقييد + الوقت ----
TIME_UNITS = {"د": 60, "دقيقه": 60, "دقايق": 60, "دقائق": 60, "دقيقة": 60,
              "س": 3600, "ساعه": 3600, "ساعات": 3600, "ساعة": 3600,
              "ي": 86400, "يوم": 86400, "ايام": 86400, "أيام": 86400}
TIMED_RE = re.compile(r"^تقييد\s+(\d+)\s*([^\d\s]+)$")


def _timed_filter(m):
    if not m.text:
        return False
    mt = TIMED_RE.match(norm(split_ref(m.text)[0]))
    return bool(mt) and mt.group(2) in {norm(u) for u in TIME_UNITS}


@on(_timed_filter)
def timed_restrict(m):
    my = require_level(m, 2)
    if my is None:
        return
    cmd_text, ref = split_ref(m.text)
    mt = TIMED_RE.match(norm(cmd_text))
    units = {norm(u): v for u, v in TIME_UNITS.items()}
    secs = int(mt.group(1)) * units[mt.group(2)]
    if secs < 60:
        bot.reply_to(m, "⚠️ أقل مدة دقيقة.")
        return
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, NEED_TARGET)
        return
    tid, tname = target
    if not mod_guard(m, my, tid):
        return
    try:
        bot.restrict_chat_member(m.chat.id, tid, permissions=MUTED, until_date=int(time.time()) + secs)
        bot.reply_to(m, f"• تم تقييده بنجاح لمدة {fmt_time(secs) if secs < 3600 else (str(secs // 3600) + ' ساعة' if secs < 86400 else str(secs // 86400) + ' يوم')}\n"
                        f"• المستخدم ↢ {mention(tid, tname)}")
    except Exception as e:
        bot.reply_to(m, f"❌ ما قدرت أنفذ:\n<code>{esc(str(e))}</code>")


# ---- المحظورين / طرد البوتات ----
@on(text_is("المحظورين", "قائمه المحظورين"))
def banned_list(m):
    if require_level(m, 2) is None:
        return
    rows = db_all("SELECT user_id, name FROM banned WHERE chat_id=?", (m.chat.id,))
    if not rows:
        bot.reply_to(m, "📂 ما فيه محظورين في هذا القروب.")
        return
    bot.reply_to(m, "⛔ <b>المحظورين:</b>\n\n" + "\n".join(f"• {mention(r['user_id'], r['name'])}" for r in rows))


@on(text_is("طرد البوتات"))
def kick_bots(m):
    if require_level(m, 2) is None:
        return
    rows = db_all("SELECT user_id FROM bots_seen WHERE chat_id=?", (m.chat.id,))
    n = 0
    for r in rows:
        if r["user_id"] == BOT_ID:
            continue
        if kick_user(m.chat.id, r["user_id"]):
            n += 1
            db_exec("DELETE FROM bots_seen WHERE chat_id=? AND user_id=?", (m.chat.id, r["user_id"]))
    bot.reply_to(m, f"• تم طرد {n} بوت بنجاح" if n else "• ما لقيت بوتات أطردها")


# ---- منع بالرد ----
@on(text_is("منع بالرد", "منع"))
def block_reply(m):
    if require_level(m, 2) is None:
        return
    rm = m.reply_to_message
    key = media_key(rm) if rm else None
    if not key or not key[1]:
        bot.reply_to(m, "⚠️ رد على الرسالة / الصورة / الملصق اللي تبي تمنعه.")
        return
    label = (rm.text or rm.caption or key[0])[:40]
    db_exec("INSERT OR REPLACE INTO blocklist VALUES (?,?,?,?)", (m.chat.id, key[0], key[1], label))
    safe_delete(m.chat.id, rm.message_id)
    bot.reply_to(m, "• تم منعه بنجاح 🚫")


@on(text_is("الغاء منع بالرد", "الغاء المنع"))
def unblock_reply(m):
    if require_level(m, 2) is None:
        return
    rm = m.reply_to_message
    key = media_key(rm) if rm else None
    if not key:
        bot.reply_to(m, "⚠️ رد على الرسالة اللي تبي تلغي منعها.")
        return
    db_exec("DELETE FROM blocklist WHERE chat_id=? AND kind=? AND key=?", (m.chat.id, key[0], key[1]))
    bot.reply_to(m, "• تم الغاء منعه بنجاح")


@on(text_is("قائمه المنع", "قائمة المنع"))
def block_list(m):
    if require_level(m, 2) is None:
        return
    rows = db_all("SELECT kind, label FROM blocklist WHERE chat_id=?", (m.chat.id,))
    if not rows:
        bot.reply_to(m, "📂 قائمة المنع فاضية.")
        return
    bot.reply_to(m, "🚫 <b>قائمة المنع:</b>\n\n"
                    + "\n".join(f"• [{r['kind']}] {esc(r['label'])}" for r in rows[:50]))


# ---- المسح ----
def _masah_filter(m):
    if not m.text:
        return False
    parts = norm(m.text).split(None, 1)
    if len(parts) != 2 or parts[0] != "مسح":
        return False
    arg = parts[1]
    return (arg in MASAH_RANKS or arg.isdigit() or arg in (
        "الكل", "المحظورين", "المكتومين", "قائمه المنع", "الردود", "الاوامر المضافه",
        "بالرد", "الايدي", "الترحيب", "الرابط"))


@on(_masah_filter)
def masah(m):
    arg = norm(m.text).split(None, 1)[1]
    chat_id = m.chat.id
    my = require_level(m, 2)
    if my is None:
        return
    if arg == "الكل":
        lows = [r for r, l in RANKS.items() if r != "عضو" and can_grant(my, l)]
        for r in lows:
            db_exec("UPDATE users SET rank='عضو' WHERE chat_id=? AND rank=?", (chat_id, r))
        bot.reply_to(m, "• تم مسح جميع الرتب بنجاح")
    elif arg in MASAH_RANKS:
        rank = MASAH_RANKS[arg]
        if not can_grant(my, RANKS[rank]):
            bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {rank}")
            return
        db_exec("UPDATE users SET rank='عضو' WHERE chat_id=? AND rank=?", (chat_id, rank))
        bot.reply_to(m, f"• تم مسح {arg} بنجاح")
    elif arg == "المحظورين":
        n = 0
        for r in db_all("SELECT user_id FROM banned WHERE chat_id=?", (chat_id,)):
            try:
                bot.unban_chat_member(chat_id, r["user_id"], only_if_banned=True)
                n += 1
            except Exception:
                pass
        db_exec("DELETE FROM banned WHERE chat_id=?", (chat_id,))
        bot.reply_to(m, f"• تم مسح المحظورين بنجاح ({n})")
    elif arg == "المكتومين":
        db_exec("DELETE FROM muted WHERE chat_id=?", (chat_id,))
        bot.reply_to(m, "• تم مسح المكتومين بنجاح")
    elif arg == "قائمه المنع":
        db_exec("DELETE FROM blocklist WHERE chat_id=?", (chat_id,))
        bot.reply_to(m, "• تم مسح قائمة المنع بنجاح")
    elif arg == "الردود":
        db_exec("DELETE FROM replies WHERE chat_id=?", (chat_id,))
        db_exec("DELETE FROM vip_replies WHERE chat_id=?", (chat_id,))
        bot.reply_to(m, "• تم مسح الردود بنجاح")
    elif arg == "الاوامر المضافه":
        db_exec("DELETE FROM aliases WHERE chat_id=?", (chat_id,))
        bot.reply_to(m, "• تم مسح الاوامر المضافه بنجاح")
    elif arg == "الايدي":
        del_text(chat_id, "id")
        bot.reply_to(m, "• تم مسح قالب الايدي بنجاح")
    elif arg == "الترحيب":
        del_text(chat_id, "welcome")
        bot.reply_to(m, "• تم مسح الترحيب بنجاح")
    elif arg == "الرابط":
        del_text(chat_id, "link")
        bot.reply_to(m, "• تم مسح الرابط بنجاح")
    elif arg == "بالرد":
        if not m.reply_to_message:
            bot.reply_to(m, "⚠️ رد على الرسالة اللي تبي تمسحها.")
            return
        safe_delete(chat_id, m.reply_to_message.message_id)
        safe_delete(chat_id, m.message_id)
    elif arg.isdigit():
        n = min(int(arg), 200)
        ids = list(range(m.message_id - n, m.message_id + 1))
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            try:
                bot.delete_messages(chat_id, chunk)
            except Exception:
                for mid in chunk:
                    safe_delete(chat_id, mid)
        temp_message(chat_id, f"• تم مسح {n} رسالة بنجاح", 4)


# ---- اضف رد / اضف امر / ضع الترحيب / ضع رابط / تعيين الايدي ----
PENDING_CMDS = {
    "اضف رد": ("reply", "• ارسل الكلمة اللي تبي البوت يرد عليها\n• للإلغاء اكتب: الغاء"),
    "اضف رد مميز": ("reply_vip", "• ارسل الكلمة اللي تبي البوت يرد عليها\n"
                                 "• هذا الرد المميز يطلع فقط لأصحاب الرتب (مميز فأعلى)\n• للإلغاء اكتب: الغاء"),
    "اضف امر": ("cmd", "• ارسل الامر القديم (مثال: حظر)\n• للإلغاء اكتب: الغاء"),
    "ضع الترحيب": ("welcome", "• ارسل نص الترحيب\n• {name} = اسم العضو، {group} = اسم القروب\n• للإلغاء اكتب: الغاء"),
    "ضع رابط": ("link", "• ارسل رابط القروب\n• للإلغاء اكتب: الغاء"),
    "تعيين الايدي": ("id", "• ارسل قالب الايدي\n• المتغيرات: {name} {id} {rank} {messages} {username}\n• للإلغاء اكتب: الغاء"),
}
PENDING_NORM = {norm(k): v for k, v in PENDING_CMDS.items()}


@on(lambda m: bool(m.text) and norm(m.text) in PENDING_NORM)
def start_pending(m):
    if require_level(m, 3) is None:
        return
    kind, prompt = PENDING_NORM[norm(m.text)]
    pending_input[(m.chat.id, m.from_user.id)] = {"kind": kind, "step": 0, "data": {},
                                                  "until": time.time() + 120}
    bot.reply_to(m, prompt)


@on(text_is("الردود", "قائمه الردود"))
def replies_list(m):
    if require_level(m, 2) is None:
        return
    rows = db_all("SELECT word, kind, 0 AS vip FROM replies WHERE chat_id=? "
                  "UNION ALL SELECT word, kind, 1 AS vip FROM vip_replies WHERE chat_id=?",
                  (m.chat.id, m.chat.id))
    if not rows:
        bot.reply_to(m, "📂 ما فيه ردود مضافه.")
        return
    bot.reply_to(m, "💬 <b>الردود:</b>\n\n" + "\n".join(
        f"• {esc(r['word'])} ({r['kind']}){' ⭐ مميز' if r['vip'] else ''}" for r in rows[:60]))


@on(text_starts("حذف"))
def delete_reply(m):
    parts = norm(m.text).split(None, 2)
    if len(parts) < 3 or parts[1] != "رد":
        return
    if require_level(m, 3) is None:
        return
    db_exec("DELETE FROM replies WHERE chat_id=? AND word=?", (m.chat.id, parts[2]))
    db_exec("DELETE FROM vip_replies WHERE chat_id=? AND word=?", (m.chat.id, parts[2]))
    bot.reply_to(m, "• تم حذف الرد بنجاح")


@on(text_is("الاوامر المضافه"))
def aliases_list(m):
    if require_level(m, 2) is None:
        return
    rows = db_all("SELECT new_cmd, old_cmd FROM aliases WHERE chat_id=?", (m.chat.id,))
    if not rows:
        bot.reply_to(m, "📂 ما فيه اوامر مضافه.")
        return
    bot.reply_to(m, "➕ <b>الاوامر المضافه:</b>\n\n"
                    + "\n".join(f"• {esc(r['new_cmd'])} ↢ {esc(r['old_cmd'])}" for r in rows))


# ---- الرابط ----
@on(text_is("الرابط", "رابط القروب", "رابط المجموعه"))
def show_link(m):
    link = get_text(m.chat.id, "link")
    if not link:
        try:
            link = bot.export_chat_invite_link(m.chat.id)
        except Exception:
            bot.reply_to(m, "⚠️ ما فيه رابط محفوظ. استخدم (ضع رابط) أو (انشاء رابط).")
            return
    bot.reply_to(m, f"• رابط القروب ↢\n{esc(link)}")


@on(text_is("انشاء رابط"))
def make_link(m):
    if require_level(m, 3) is None:
        return
    try:
        link = bot.export_chat_invite_link(m.chat.id)
    except Exception as e:
        bot.reply_to(m, f"❌ ما قدرت أنشئ الرابط (يحتاج صلاحية دعوة المستخدمين):\n<code>{esc(str(e))}</code>")
        return
    set_text(m.chat.id, "link", link)
    bot.reply_to(m, f"• تم انشاء الرابط بنجاح\n{esc(link)}")


# ---- الايدي ----
ID_DEFAULT = "• الاسم ⇜ {name}\n• الايدي ⇜ <code>{id}</code>\n• الرتبة ⇜ {rank}\n• الرسائل ⇜ {messages}"


@on(text_starts("ايدي", "id"))
def show_id(m):
    parts = norm(m.text).split()
    if len(parts) > 1 and not m.reply_to_message and not parts[1].startswith("@") and not parts[1].isdigit():
        return
    _, ref = split_ref(m.text)
    tid, tname = find_target(m, ref) or (m.from_user.id, m.from_user.first_name or "عضو")
    u = get_user(m.chat.id, tid, tname)
    tmpl = get_text(m.chat.id, "id") or ID_DEFAULT
    txt = (tmpl.replace("{name}", esc(tname)).replace("{id}", str(tid))
           .replace("{rank}", rank_name(m.chat.id, tid))
           .replace("{messages}", str(u["messages"]))
           .replace("{username}", ("@" + u["username"]) if u["username"] else "لا يوجد"))
    try:
        ph = bot.get_user_profile_photos(tid, limit=1)
        if ph.total_count:
            bot.send_photo(m.chat.id, ph.photos[0][-1].file_id, caption=txt,
                           reply_to_message_id=m.message_id)
            return
    except Exception:
        pass
    bot.reply_to(m, txt)


# ================================== الرتب ==================================
@on(text_is("المكتومين", "قائمة المكتومين"))
def muted_list(m):
    if require_level(m, 2) is None:
        return
    rows = db_all(
        "SELECT mu.user_id AS uid, u.name AS name FROM muted mu "
        "LEFT JOIN users u ON u.user_id = mu.user_id AND u.chat_id = mu.chat_id "
        "WHERE mu.chat_id=?", (m.chat.id,))
    if not rows:
        bot.reply_to(m, "📂 ما فيه مكتومين في هذا القروب.")
        return
    bot.reply_to(m, "🔇 <b>المكتومين:</b>\n\n" + "\n".join(f"• {mention(r['uid'], r['name'])}" for r in rows))


@on(text_is("رتبتي"))
def my_rank(m):
    lvl = get_level(m.chat.id, m.from_user.id)
    bot.reply_to(m, f"• رتبتك ⇜ <b>{rank_name(m.chat.id, m.from_user.id)}</b>")


# ---- @all : منشن للكل (للمشرفين) ----
MENTION_ALL_MAX = 150   # أقصى عدد يتمنشن بالمرة الوحدة
MENTION_ALL_CHUNK = 5   # كم واحد بالرسالة الوحدة


def _run_mention_all(chat_id, header, members):
    chunks = [members[i:i + MENTION_ALL_CHUNK] for i in range(0, len(members), MENTION_ALL_CHUNK)]
    for i, chunk in enumerate(chunks):
        text = (header + "\n" if i == 0 else "") + " ".join(mention(uid, name) for uid, name in chunk)
        for attempt in range(2):
            try:
                bot.send_message(chat_id, text)
                break
            except Exception as e:
                print("mention_all error:", e)
                time.sleep(5)
        time.sleep(3)  # عشان ما يضربنا حد تيليجرام للرسائل


@on(text_starts("@all", "@everyone", "@الكل"))
def mention_all(m):
    if require_level(m, 2) is None:
        return
    left = cooldown_left(m.chat.id, 0, "mention_all", 120)
    if left:
        bot.reply_to(m, f"⏳ انتظر {fmt_time(left)} قبل ما تمنشن الكل مرة ثانية.")
        return
    parts = m.text.split(None, 1)
    note = parts[1].strip() if len(parts) > 1 else ""
    members = {}
    for r in db_all("SELECT user_id, name FROM users WHERE chat_id=? ORDER BY messages DESC LIMIT ?",
                    (m.chat.id, MENTION_ALL_MAX)):
        members[r["user_id"]] = r["name"] or "عضو"
    try:
        for a in bot.get_chat_administrators(m.chat.id):
            if not a.user.is_bot:
                members.setdefault(a.user.id, a.user.first_name or "مشرف")
    except Exception:
        pass
    members.pop(BOT_ID, None)
    items = list(members.items())[:MENTION_ALL_MAX]
    if not items:
        bot.reply_to(m, "• ما عندي أحد أمنشنه للحين (أمنشن اللي تكلموا بالقروب).")
        return
    header = "📢 <b>منشن للكل</b>" + (f"\n{esc(note)}" if note else "")
    Thread(target=_run_mention_all, args=(m.chat.id, header, items), daemon=True).start()


@on(text_is("الاساسي", "الاساسيين"))
def show_basic_owner(m):
    names, seen = [], set()
    for did in DEV_IDS:
        row = db_one("SELECT name FROM users WHERE user_id=? AND chat_id=?", (did, m.chat.id))
        name = row["name"] if row and row["name"] else None
        if not name:
            try:
                name = bot.get_chat(did).first_name
            except Exception:
                name = None
        names.append(mention(did, name or "الاساسي"))
        seen.add(did)
    for r in db_all("SELECT user_id, name FROM users WHERE chat_id=? AND rank='اساسي'", (m.chat.id,)):
        if r["user_id"] not in seen:
            names.append(mention(r["user_id"], r["name"]))
    if not names:
        bot.reply_to(m, "• ما فيه احد برتبة الاساسي\n-")
        return
    bot.reply_to(m, f"• رتبة الاساسي لدى ↢ {' ، '.join(names)}\n-")


@on(text_is("الرتب", "قائمة الرتب"))
def ranks_list(m):
    rows = db_all("SELECT user_id, name, rank FROM users WHERE chat_id=? AND rank != 'عضو'", (m.chat.id,))
    if not rows:
        bot.reply_to(m, "📂 ما فيه أحد مرفوع رتبة في هذا القروب.")
        return
    rows = sorted(rows, key=lambda r: RANKS.get(r["rank"], 0), reverse=True)
    lines = [f"• <b>{r['rank']}</b> ⇜ {esc(r['name'])}" for r in rows]
    bot.reply_to(m, "🎖 <b>رتب القروب:</b>\n\n" + "\n".join(lines))


@on(text_starts("رفع"))  # "رفع القيود" يمسكها معالج الإدارة لأنه مسجّل قبل
def promote(m):
    my = require_level(m, 2)
    if my is None:
        return
    cmd_text, ref = split_ref(m.text)
    pieces = cmd_text.split(None, 1)
    rank = canon_rank(pieces[1]) if len(pieces) > 1 else None
    if not rank:
        bot.reply_to(m, "❌ اكتب الرتبة بعد (رفع). المتاحة:\n"
                        + " • ".join(r for r in RANKS if r != "عضو")
                        + "\nمثال: <code>رفع مدير</code> بالرد على العضو")
        return
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, NEED_TARGET)
        return
    tid, tname = target
    if tid == BOT_ID:
        bot.reply_to(m, "😎 أنا فوق الرتب يا الغالي.")
        return
    if tid == m.from_user.id:
        bot.reply_to(m, "😅 ما تقدر ترفع نفسك.")
        return
    if not can_grant(my, RANKS[rank]):
        bot.reply_to(m, f"⛔ رتبتك ({LEVEL_NAME[my]}) ما تسمح لك ترفع لرتبة ({rank}).")
        return
    if not can_manage(my, get_level(m.chat.id, tid)):
        bot.reply_to(m, "⛔ هذا العضو رتبته أعلى منك أو تساويك.")
        return
    cur = get_user(m.chat.id, tid, tname)
    if cur["rank"] == rank:
        bot.reply_to(m, f"• تم رفعه {rank} مسبقاً\n• المستخدم ↢ {mention(tid, tname)}")
        return
    db_exec("UPDATE users SET rank=? WHERE user_id=? AND chat_id=?", (rank, tid, m.chat.id))
    db_exec("DELETE FROM muted WHERE chat_id=? AND user_id=?", (m.chat.id, tid))  # الرتبة تشيل الكتم
    bot.reply_to(m, f"• تم رفعه {rank} بنجاح\n• المستخدم ↢ {mention(tid, tname)}")


@on(text_starts("تنزيل"))
def demote(m):
    my = require_level(m, 2)
    if my is None:
        return
    cmd_text, ref = split_ref(m.text)
    pieces = cmd_text.split(None, 1)
    word = norm(pieces[1]) if len(pieces) > 1 else ""
    all_ranks = word == "الكل"
    want = None if (all_ranks or not word) else canon_rank(word)
    if word and not all_ranks and not want:
        bot.reply_to(m, "❌ رتبة غير معروفة. المتاحة:\n" + " • ".join(r for r in RANKS if r != "عضو")
                     + "\nأو اكتب <code>تنزيل الكل</code> لازالة جميع الرتب")
        return
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, NEED_TARGET)
        return
    tid, tname = target
    if tid == m.from_user.id:
        bot.reply_to(m, "😅 ما تقدر تنزّل نفسك.")
        return
    if not can_manage(my, get_level(m.chat.id, tid)):
        bot.reply_to(m, f"• عذراً لا تستطيع استخدام الامر على {rank_label(get_level(m.chat.id, tid))}")
        return
    cur = get_user(m.chat.id, tid, tname)
    if cur["rank"] == "عضو" or (want and cur["rank"] != want):
        bot.reply_to(m, f"• تم تنزيله مسبقاً\n• المستخدم ↢ {mention(tid, tname)}")
        return
    db_exec("UPDATE users SET rank='عضو' WHERE user_id=? AND chat_id=?", (tid, m.chat.id))
    done = "من جميع الرتب" if all_ranks else f"من رتبة {cur['rank']}"
    bot.reply_to(m, f"• تم تنزيله {done}\n• المستخدم ↢ {mention(tid, tname)}")


@on(text_starts("فحص"))
def check_profile(m):
    _, ref = split_ref(m.text)
    target = find_target(m, ref) or (m.from_user.id, m.from_user.first_name or "عضو")
    tid, tname = target
    u = get_user(m.chat.id, tid, tname)
    warns = u["warns"] or 0
    bot.reply_to(
        m,
        f"• فحص ⇜ {mention(tid, tname)}\n"
        f"• الايدي ⇜ <code>{tid}</code>\n"
        f"• الرتبة ⇜ <b>{rank_name(m.chat.id, tid)}</b>\n"
        f"• الرسائل ⇜ {u['messages']}\n"
        f"• سوابقه ⇜ {'لا توجد سوابق ✅' if warns == 0 else f'{warns} مخالفة ⚠️'}",
    )


# ================================== الهمسات ==================================
@on(text_starts("اهمس", "همسة", "همس"))
def whisper(m):
    parts = m.text.split(None, 1)
    body = parts[1].strip() if len(parts) > 1 else ""
    ref = None
    if not m.reply_to_message and body:
        first, _, rest = body.partition(" ")
        if first.startswith("@") or first.isdigit():
            ref, body = first, rest.strip()

    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, "🤫 رد على رسالة اللي تبي تهمس له، أو اكتب:\n<code>اهمس @username نصك</code>\n"
                        "(المعرف لازم يكون تكلم بالقروب قبل)")
        return
    tid, tname = target
    if tid == m.from_user.id or tid == BOT_ID:
        bot.reply_to(m, "😅 ما يصير تهمس لنفسك ولا للبوت يا الغالي!")
        return
    if not body:
        create_whisper_prompt(m, tid, tname)
        return
    if len(body) > 200:
        bot.reply_to(m, "⚠️ الهمسة طويلة، الحد الأقصى 200 حرف.")
        return

    sender = m.from_user
    wid = db_insert(
        "INSERT INTO whispers (chat_id, sender_id, sender_name, target_id, target_name, text, ts, kind) "
        "VALUES (?,?,?,?,?,?,?,'text')",
        (m.chat.id, sender.id, sender.first_name or "عضو", tid, tname, body, int(time.time())),
    )

    deleted = safe_delete(m.chat.id, m.message_id)  # نخفي نص الهمسة عن الكل
    post_whisper(wid)
    if not deleted:
        temp_message(m.chat.id, "⚠️ اعطني صلاحية حذف الرسائل عشان أخفي نص الهمسة.", 10)


def whisper_text(w):
    """نص إشعار الهمسة في القروب (نفس بوت BEEDO)."""
    return (f"• الهمسه لـ ↢ {mention(w['target_id'], w['target_name'])}\n"
            f"• من ↢ {mention(w['sender_id'], w['sender_name'])}\n-")


def whisper_markup(wid):
    w = db_one("SELECT sender_name FROM whispers WHERE id=?", (wid,))
    name = ((w["sender_name"] if w else None) or "عضو")[:20]
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        btn("رؤية الهمسة", style="primary", callback_data=f"wh:{wid}"),
        btn(f"اهمس لـ {name}", url=f"https://t.me/{BOT_USERNAME}?start=wa_{wid}"),
    )
    return kb


def post_whisper(wid):
    """ينشر إشعار الهمسة في القروب: الهمسه لـ ↢ فلان / من ↢ فلان + الزرين."""
    w = db_one("SELECT * FROM whispers WHERE id=?", (wid,))
    sent = bot.send_message(w["chat_id"], whisper_text(w), reply_markup=whisper_markup(wid))
    db_exec("UPDATE whispers SET group_msg=? WHERE id=?", (sent.message_id, wid))
    return sent


def send_safe(chat_id, text, reply_to=None, **kw):
    """يرسل كرد على رسالة، وإذا الرسالة انحذفت يرسل عادي."""
    try:
        return bot.send_message(chat_id, text, reply_to_message_id=reply_to, **kw)
    except Exception:
        return bot.send_message(chat_id, text, **kw)


def create_whisper_prompt(m, tid, tname):
    """اهمس بدون نص: نفس طريقة البوت الأول (زر همسة نصية / همسة وسائط)."""
    sender = m.from_user
    reply_to = m.reply_to_message.message_id if m.reply_to_message else None
    did = db_insert(
        "INSERT INTO whisper_drafts (chat_id, sender_id, sender_name, target_id, target_name, reply_to, ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (m.chat.id, sender.id, sender.first_name or "عضو", tid, tname, reply_to, int(time.time())),
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        btn("• همسة نصية", style="primary", url=f"https://t.me/{BOT_USERNAME}?start=wt_{did}"),
        btn("• همسة وسائط", style="success", url=f"https://t.me/{BOT_USERNAME}?start=wm_{did}"),
    )
    sent = send_safe(
        m.chat.id,
        f"• تم تحديد الهمسه لـ ↢ {mention(tid, tname)}\n• اضغط الزر لكتابة الهمسة\n-",
        reply_to=m.message_id, reply_markup=kb,
    )
    db_exec("UPDATE whisper_drafts SET prompt_id=? WHERE id=?", (sent.message_id, did))


whisper_pending = {}  # user_id -> {"draft": id, "mode": "text" | "media"}


def handle_start_payload(m, payload):
    """يعالج روابط ?start=... القادمة من أزرار الهمسة. يرجع True إذا عالجها."""
    uid = m.from_user.id
    if payload[:3] in ("wt_", "wm_") and payload[3:].isdigit():
        d = db_one("SELECT * FROM whisper_drafts WHERE id=?", (int(payload[3:]),))
        if not d:
            bot.reply_to(m, "⌛ انتهت صلاحية هذي الهمسة، ارجع للقروب واكتب <b>اهمس</b> من جديد.")
            return True
        if d["sender_id"] != uid:
            bot.reply_to(m, "🤫 هذي الهمسة مو لك!")
            return True
        mode = "text" if payload.startswith("wt_") else "media"
        whisper_pending[uid] = {"draft": d["id"], "mode": mode}
        if mode == "text":
            msg = f"• اكتب همستك لـ {esc(d['target_name'])} ."
        else:
            msg = f"• ارسل الصورة أو الفيديو أو الملصق أو المقطع الصوتي لـ {esc(d['target_name'])} ."
        bot.reply_to(m, msg + "\n• للإلغاء اكتب: <b>الغاء</b>")
        return True
    if payload.startswith("wa_") and payload[3:].isdigit():  # زر "اهمس لـ فلان" (الرد بهمسة)
        w = db_one("SELECT * FROM whispers WHERE id=?", (int(payload[3:]),))
        if not w:
            bot.reply_to(m, "⌛ انتهت صلاحية هذي الهمسة.")
            return True
        if w["target_id"] != uid:
            bot.reply_to(m, "🤫 هذي الهمسة مو لك!")
            return True
        did = db_insert(
            "INSERT INTO whisper_drafts (chat_id, sender_id, sender_name, target_id, target_name, reply_to, ts) "
            "VALUES (?,?,?,?,?,?,?)",
            (w["chat_id"], uid, m.from_user.first_name or "عضو", w["sender_id"], w["sender_name"],
             w["group_msg"], int(time.time())),
        )
        whisper_pending[uid] = {"draft": did, "mode": "text"}
        bot.reply_to(m, f"• اكتب همستك لـ {esc(w['sender_name'])} .\n• للإلغاء اكتب: <b>الغاء</b>")
        return True
    if payload.startswith("wr_") and payload[3:].isdigit():
        deliver_media(m, int(payload[3:]))
        return True
    return False


def mark_read(w, reader_id):
    if reader_id == w["target_id"] and not w["is_read"]:
        db_exec("UPDATE whispers SET is_read=1 WHERE id=?", (w["id"],))
        try:  # إشعار للمرسل داخل البوت
            bot.send_message(
                w["sender_id"],
                f"• تمت قراءة الهمسة .. بنجاح\n• من قبل ↢ {mention(w['target_id'], w['target_name'])}\n-")
        except Exception as e:
            print("read notice error:", e)


def send_whisper_media(chat_id, w):
    """يرسل وسائط الهمسة بالـ file_id (الهمسات القديمة تنسخ من رسالة المرسل)."""
    if w["file_id"] and w["media_type"] in _SEND:
        kw = {}
        if w["caption"] and w["media_type"] not in ("sticker", "video_note"):
            kw["caption"] = w["caption"]
        getattr(bot, _SEND[w["media_type"]])(chat_id, w["file_id"], **kw)
    else:
        bot.copy_message(chat_id, w["sender_id"], w["src_msg"])


def deliver_media(m, wid):
    w = db_one("SELECT * FROM whispers WHERE id=?", (wid,))
    if not w or w["kind"] != "media":
        bot.reply_to(m, "❌ الهمسة انتهت.")
        return
    if m.from_user.id not in (w["target_id"], w["sender_id"]):
        bot.reply_to(m, "🤫 هذي الهمسة مو لك يا فضولي!")
        return
    try:
        send_whisper_media(m.chat.id, w)
    except Exception:
        bot.reply_to(m, "❌ ما قدرت أرسل الوسائط.")
        return
    mark_read(w, m.from_user.id)


PRIVATE_TYPES = ["text", "photo", "video", "voice", "document", "audio",
                 "sticker", "animation", "video_note"]


@bot.message_handler(func=lambda m: m.chat.type == "private" and m.from_user.id in whisper_pending,
                     content_types=PRIVATE_TYPES)
def whisper_private(m):
    uid = m.from_user.id
    st = whisper_pending.get(uid)
    if not st:
        return
    if m.text and norm(m.text) in ("الغاء", "/cancel"):
        whisper_pending.pop(uid, None)
        bot.reply_to(m, "✅ تم إلغاء الهمسة.")
        return
    d = db_one("SELECT * FROM whisper_drafts WHERE id=?", (st["draft"],))
    if not d:
        whisper_pending.pop(uid, None)
        bot.reply_to(m, "⌛ انتهت صلاحية هذي الهمسة، اكتب <b>اهمس</b> بالقروب من جديد.")
        return

    if st["mode"] == "text":
        if m.content_type != "text":
            bot.reply_to(m, "⚠️ أرسل نص فقط، أو اكتب <b>الغاء</b>.")
            return
        if len(m.text) > 200:
            bot.reply_to(m, f"⚠️ الهمسة طويلة ({len(m.text)} حرف)، الحد الأقصى 200 حرف.")
            return
        kind, text, src, label = "text", m.text, None, "نصية"
    else:
        if m.content_type == "text":
            bot.reply_to(m, "⚠️ أرسل صورة أو فيديو أو مقطع صوتي أو ملصق، أو اكتب <b>الغاء</b>.")
            return
        c = content_of(m)
        if not c:
            bot.reply_to(m, "⚠️ هذا النوع غير مدعوم، أرسل صورة أو فيديو أو مقطع صوتي أو ملصق.")
            return
        kind, text, src, label = "media", "", m.message_id, "وسائط"

    wid = db_insert(
        "INSERT INTO whispers (chat_id, sender_id, sender_name, target_id, target_name, text, ts, kind, src_msg,"
        " media_type, file_id, caption) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["chat_id"], d["sender_id"], d["sender_name"], d["target_id"], d["target_name"],
         text, int(time.time()), kind, src,
         c[0] if kind == "media" else None, c[1] if kind == "media" else None,
         c[2] if kind == "media" else None),
    )
    whisper_pending.pop(uid, None)
    try:
        post_whisper(wid)
    except Exception as e:
        bot.reply_to(m, f"❌ ما قدرت أرسل الهمسة للقروب:\n<code>{esc(str(e))}</code>")
        return
    if d["prompt_id"]:
        safe_delete(d["chat_id"], d["prompt_id"])
    db_exec("DELETE FROM whisper_drafts WHERE id=?", (d["id"],))
    bot.send_message(m.chat.id, f"تم ارسال همستك لـ {mention(d['target_id'], d['target_name'])} بنجاح")
    safe_delete(m.chat.id, m.message_id)  # تختفي رسالة الهمسة من الخاص


def read_whisper(call):
    wid = int(call.data.split(":")[1])
    w = db_one("SELECT * FROM whispers WHERE id=?", (wid,))
    if not w:
        bot.answer_callback_query(call.id, "❌ الهمسة انتهت.", show_alert=True)
        return
    if call.from_user.id not in (w["target_id"], w["sender_id"]):
        bot.answer_callback_query(call.id, "🤫 هذي الهمسة مو لك يا فضولي!", show_alert=True)
        return
    if w["kind"] == "media":
        try:  # نرسل الوسائط بالخاص (المستلم لازم يكون فاتح البوت)
            send_whisper_media(call.from_user.id, w)
            bot.answer_callback_query(call.id, "📩 أرسلت لك الوسائط في الخاص.", show_alert=True)
            mark_read(w, call.from_user.id)
        except Exception:
            # ما فتح البوت قبل: نفتح له الخاص ويستلمها بعد الضغط على Start
            bot.answer_callback_query(call.id, url=f"https://t.me/{BOT_USERNAME}?start=wr_{wid}")
        return
    bot.answer_callback_query(call.id, w["text"], show_alert=True)
    mark_read(w, call.from_user.id)


# ============================= الاعدادات والتوب =============================
LOCK_HEADER = ("• اعدادات المجموعه\n• علامة الـ(نعم) تعني مقفول\n• علامة الـ(لا) تعني مفتوح")
TOG_HEADER = ("• التفعيل والتعطيل\n• علامة الـ(نعم) تعني مفعل\n• علامة الـ(لا) تعني معطل")
TOG_ITEMS = [("الترحيب", "welcome"), ("الردود", "replies"), ("منع السب", "swear")]


def _nav_rows(kb):
    kb.row(btn("القائمه الرئيسيه 📋", style="primary", callback_data="mn:main"))
    kb.row(btn("اخفاء الامر 🗑", style="danger", callback_data="hide"))


def lock_markup(chat_id, page=0):
    kb = types.InlineKeyboardMarkup()
    for label, key in LOCK_PAGES[page]:
        on_ = bool(get_flag(chat_id, key))
        kb.row(btn(f"{label} ↢", callback_data="noop"),
               btn("نعم" if on_ else "لا", style="success" if on_ else "primary",
                   callback_data=f"lk:{key}:{page}"))
    if page == 0:
        kb.row(btn("التالي", style="success", callback_data="lkp:1"))
    else:
        kb.row(btn("السابق ↩", style="primary", callback_data="lkp:0"))
    _nav_rows(kb)
    return kb


def settings_markup(chat_id):
    """شاشة التفعيل والتعطيل (الترحيب / الردود / منع السب)."""
    kb = types.InlineKeyboardMarkup()
    for label, key in TOG_ITEMS:
        on_ = bool(get_flag(chat_id, key))
        kb.row(btn(f"{label} ↢", callback_data="noop"),
               btn("نعم" if on_ else "لا", style="success" if on_ else "primary",
                   callback_data=f"tog:{key}"))
    _nav_rows(kb)
    return kb


@on(text_is("الاعدادات", "الحماية", "اوامر التفعيل", "اعدادات المجموعه"))
def settings_menu(m):
    if require_level(m, 2) is None:
        return
    bot.reply_to(m, LOCK_HEADER, reply_markup=lock_markup(m.chat.id, 0))


@on(lambda m: bool(m.text) and norm(m.text).split(None, 1)[0:1] in (["قفل"], ["فتح"])
    and norm(m.text).split(None, 1)[-1] in LOCK_BY_NAME)
def lock_cmd(m):
    if require_level(m, 2) is None:
        return
    verb, name = norm(m.text).split(None, 1)
    key = LOCK_BY_NAME[name]
    set_flag(m.chat.id, key, 1 if verb == "قفل" else 0)
    label = LOCK_LABEL[key]
    bot.reply_to(m, f"• تم {'قفل' if verb == 'قفل' else 'فتح'} {label} بنجاح")


TOPS = {
    "money": ("💰 توب الفلوس", "balance", "درهم"),
    "active": ("💬 توب المتفاعلين", "messages", "رسالة"),
    "thieves": ("🥷 توب الحراميه", "thefts", "عملية"),
}


def top_markup():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 توب الفلوس", callback_data="top:money"),
        types.InlineKeyboardButton("💬 توب المتفاعلين", callback_data="top:active"),
        types.InlineKeyboardButton("🥷 توب الحراميه", callback_data="top:thieves"),
        types.InlineKeyboardButton("💍 توب المتزوجين", callback_data="top:married"),
    )
    return kb


def build_top(chat_id, kind):
    title, col, unit = TOPS[kind]
    rows = db_all(
        f"SELECT name, {col} AS v FROM users WHERE chat_id=? AND {col} > 0 "
        f"ORDER BY {col} DESC LIMIT 10", (chat_id,))
    if not rows:
        return f"{title}\n\n📂 ما فيه بيانات للحين."
    medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    lines = [f"{medals[i]} {esc(r['name'])} ⇜ <b>{r['v']}</b> {unit}" for i, r in enumerate(rows)]
    return f"{title}\n\n" + "\n".join(lines)


@on(text_is("توب"))
def top_menu(m):
    bot.reply_to(m, "- أهلاً بك في قائمة سرداب 🏆\n• اختر نوع التوب من الأزرار", reply_markup=top_markup())


# ================================ البنك والفلوس ================================
BANKS = ["الامارات", "اديب", "المشرق"]  # بنوك للتسلية
BANKS_NORM = {norm(b): b for b in BANKS}


bank_pending = {}  # (chat_id, user_id) -> وقت انتهاء انتظار اسم البنك
BANK_CMD = norm("انشاء حساب بنكي")


def open_account(m, bank):
    u = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    if u["bank"] != "لا يوجد":
        bot.reply_to(m, f"🏦 عندك حساب أصلاً في بنك <b>{u['bank']}</b> يا الغالي.")
        return
    db_exec("UPDATE users SET bank=?, balance=balance+500 WHERE user_id=? AND chat_id=?",
            (bank, m.from_user.id, m.chat.id))
    bot.reply_to(m, f"✅ تم إنشاء حسابك في بنك <b>{bank}</b> بنجاح! (تسلية 🎭)\n"
                    f"💳 رقم حسابك: <code>{acc_number(m.from_user.id)}</code>\n"
                    f"🎁 حصلت على 500 درهم هدية افتتاح الحساب.")


@on(lambda m: bool(m.text) and norm(m.text).startswith(BANK_CMD))
def create_bank(m):
    rest = norm(m.text)[len(BANK_CMD):].strip()
    if rest in BANKS_NORM:  # مثال: انشاء حساب بنكي الامارات
        open_account(m, BANKS_NORM[rest])
        return
    u = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    if u["bank"] != "لا يوجد":
        bot.reply_to(m, f"🏦 عندك حساب أصلاً في بنك <b>{u['bank']}</b> يا الغالي.")
        return
    bank_pending[(m.chat.id, m.from_user.id)] = time.time() + 120
    bot.reply_to(m, "🏦 <b>إنشاء حساب بنكي (تسلية)</b>\n• اختر البنك وأرسل اسمه هنا:\n\n"
                    + "\n".join(f"⇜ <code>{b}</code>" for b in BANKS)
                    + "\n\n- اضغط على اسم البنك للنسخ")


@on(lambda m: bool(m.text) and m.from_user is not None and norm(m.text) in BANKS_NORM
    and bank_pending.get((m.chat.id, m.from_user.id), 0) > time.time())
def set_bank(m):
    bank_pending.pop((m.chat.id, m.from_user.id), None)
    open_account(m, BANKS_NORM[norm(m.text)])


@on(text_is("فلوسي", "رصيدي"))
def my_money(m):
    u = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    if u["bank"] == "لا يوجد":
        bot.reply_to(m, "🏦 ما عندك حساب بنكي. اكتب <b>انشاء حساب بنكي</b> وخذ 500 درهم هدية!")
    elif u["balance"] == 0:
        bot.reply_to(m, "💸 ما عندك فلوس يا طويل العمر، اكتب <b>راتب</b> أو العب وابدأ اجمع دراهمك مع سرداب")
    else:
        bot.reply_to(m, f"💰 رصيدك في بنك ({u['bank']}): <b>{u['balance']}</b> درهم\n"
                        f"💳 حسابك: <code>{acc_number(m.from_user.id)}</code>")


@on(text_is("راتب"))
def salary(m):
    get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    left = cooldown_left(m.chat.id, m.from_user.id, "salary", 900)
    if left:
        bot.reply_to(m, f"⏳ راتبك الجاي بعد {fmt_time(left)} يا الغالي.")
        return
    amount = random.randint(200, 1000)
    add_balance(m.chat.id, m.from_user.id, amount)
    bot.reply_to(m, f"💵 تم إيداع راتبك: <b>{amount}</b> درهم، تستاهل زود!")


def parse_amount(text, balance):
    parts = text.split()
    if len(parts) < 2:
        return None
    arg = norm(parts[1])
    if arg in ("كل", "الكل"):
        return balance
    return int(arg) if arg.isdigit() else None


@on(text_starts("رهان", "مراهنة"))
def bet(m):
    if games_off(m):
        return
    u = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    amount = parse_amount(m.text, u["balance"])
    if not amount or amount <= 0:
        bot.reply_to(m, "🎲 اكتب المبلغ، مثال: <code>رهان 100</code> أو <code>رهان كل</code>")
        return
    if amount > u["balance"]:
        bot.reply_to(m, f"❌ رصيدك ({u['balance']}) ما يكفي.")
        return
    left = cooldown_left(m.chat.id, m.from_user.id, "bet", 10)
    if left:
        bot.reply_to(m, f"⏳ استنى {left} ثانية بين كل رهان.")
        return
    if random.random() < 0.45:
        add_balance(m.chat.id, m.from_user.id, amount)
        bot.reply_to(m, f"🎉 ربحت! +<b>{amount}</b> درهم. الحظ حليفك 🍀")
    else:
        add_balance(m.chat.id, m.from_user.id, -amount)
        bot.reply_to(m, f"😅 خسرت <b>{amount}</b> درهم. الله يعوضك!")


@on(text_starts("تحويل"))
def transfer(m):
    if not m.reply_to_message or not m.reply_to_message.from_user:
        bot.reply_to(m, "⚠️ رد على رسالة الشخص واكتب: <code>تحويل 100</code>")
        return
    target = m.reply_to_message.from_user
    if target.id == m.from_user.id or target.is_bot:
        bot.reply_to(m, "😅 ما يصير يا الغالي.")
        return
    u = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    amount = parse_amount(m.text, u["balance"])
    if not amount or amount <= 0:
        bot.reply_to(m, "⚠️ اكتب المبلغ، مثال: <code>تحويل 100</code>")
        return
    if amount > u["balance"]:
        bot.reply_to(m, f"❌ رصيدك ({u['balance']}) ما يكفي.")
        return
    ensure_user(m.chat.id, target.id, target.first_name, target.username)
    add_balance(m.chat.id, m.from_user.id, -amount)
    add_balance(m.chat.id, target.id, amount)
    bot.reply_to(m, f"✅ تم تحويل <b>{amount}</b> درهم إلى {mention(target.id, target.first_name)}")


@on(text_starts("زرف", "سرقة"))
def steal(m):
    if games_off(m):
        return
    _, ref = split_ref(m.text)
    target = find_target(m, ref)
    if not target:
        bot.reply_to(m, "🥷 رد على رسالة الضحية واكتب <b>زرف</b>")
        return
    tid, tname = target
    if tid == m.from_user.id or tid == BOT_ID:
        bot.reply_to(m, "😅 تسرق نفسك؟ شكلك تعبان!")
        return
    me = get_user(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)
    victim = get_user(m.chat.id, tid, tname)
    if victim["balance"] < 100:
        bot.reply_to(m, "😂 الضحية مفلس، ما فيه شي يستاهل!")
        return
    left = cooldown_left(m.chat.id, m.from_user.id, "steal", 900)
    if left:
        bot.reply_to(m, f"⏳ الشرطة تدور عليك، استنى {fmt_time(left)}.")
        return
    thief, vic = mention(m.from_user.id, m.from_user.first_name), mention(tid, tname)
    if random.random() < 0.4:
        loot = min(1000, max(50, int(victim["balance"] * random.uniform(0.05, 0.25))))
        add_balance(m.chat.id, tid, -loot)
        add_balance(m.chat.id, m.from_user.id, loot)
        db_exec("UPDATE users SET thefts = thefts + 1 WHERE user_id=? AND chat_id=?",
                (m.from_user.id, m.chat.id))
        bot.reply_to(m, f"🥷 {thief} زرف <b>{loot}</b> درهم من {vic} وهرب! 💨")
    else:
        fine = min(me["balance"], random.randint(50, 200))
        add_balance(m.chat.id, m.from_user.id, -fine)
        add_balance(m.chat.id, tid, fine)
        bot.reply_to(m, f"🚓 {thief} انمسك وهو يسرق {vic}! دفع غرامة <b>{fine}</b> درهم.")


# ================================== الألعاب ==================================
games = {}  # chat_id -> حالة اللعبة الجارية


def games_off(m):
    if not get_flag(m.chat.id, "games") or get_flag(m.chat.id, "lk_games"):
        bot.reply_to(m, "🎮 الألعاب مقفولة في هذا القروب. المشرف يفتحها بأمر (فتح الالعاب).")
        return True
    return False


def start_game(m, kind, title, text, answers, reward, seconds=120, extra=None):
    cur = games.get(m.chat.id)
    if cur and cur["until"] > time.time():
        bot.reply_to(m, f"⏳ فيه لعبة شغالة الحين ({cur['title']}). جاوب عليها أو اكتب <b>ايقاف</b>.")
        return
    games[m.chat.id] = dict(kind=kind, title=title, answers=[norm(a) for a in answers],
                            shown=answers[0], reward=reward, until=time.time() + seconds,
                            starter=m.from_user.id, extra=extra)
    bot.send_message(m.chat.id, text)


def win_game(m, g):
    games.pop(m.chat.id, None)
    add_balance(m.chat.id, m.from_user.id, g["reward"])
    bot.reply_to(m, f"🏆 مبروك {mention(m.from_user.id, m.from_user.first_name)}!\n"
                    f"الإجابة: <b>{esc(str(g['shown']))}</b>\n💰 ربحت <b>{g['reward']}</b> درهم")


# ---- النرد والألعاب الجاهزة من تيليجرام ----
DICE = {"نرد": "🎲", "سهم": "🎯", "سلة": "🏀", "كورة": "⚽", "بولينج": "🎳", "سلوت": "🎰"}
DICE_NORM = {norm(k): v for k, v in DICE.items()}


def _slot_payout(chat_id, user, value):
    if value == 64:  # ثلاث سبعات
        add_balance(chat_id, user.id, 1000)
        bot.send_message(chat_id, f"🎰🔥 <b>جاكبوت!</b> {mention(user.id, user.first_name)} ربح 1000 درهم!")


@on(lambda m: bool(m.text) and norm(m.text) in DICE_NORM)
def dice_games(m):
    if games_off(m):
        return
    emoji = DICE_NORM[norm(m.text)]
    if emoji == "🎰":
        left = cooldown_left(m.chat.id, m.from_user.id, "slot", 30)
        if left:
            bot.reply_to(m, f"⏳ استنى {left} ثانية.")
            return
    sent = bot.send_dice(m.chat.id, emoji=emoji, reply_to_message_id=m.message_id)
    if emoji == "🎰":
        threading.Timer(4.5, _slot_payout, args=(m.chat.id, m.from_user, sent.dice.value)).start()


# ---- حجرة ورقة مقص ----
@on(text_is("حجرة ورقة مقص", "حجر ورقة مقص", "مقص"))
def rps(m):
    if games_off(m):
        return
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("🪨 حجرة", callback_data=f"rps:{uid}:r"),
        types.InlineKeyboardButton("📄 ورقة", callback_data=f"rps:{uid}:p"),
        types.InlineKeyboardButton("✂️ مقص", callback_data=f"rps:{uid}:s"),
    )
    bot.reply_to(m, f"{mention(uid, m.from_user.first_name)} اختر يا بطل 👇 (الفوز = 100 درهم)", reply_markup=kb)


def handle_rps(call):
    _, owner, pick = call.data.split(":")
    if call.from_user.id != int(owner):
        bot.answer_callback_query(call.id, "هذي اللعبة مو لك 😉", show_alert=True)
        return
    names = {"r": "🪨 حجرة", "p": "📄 ورقة", "s": "✂️ مقص"}
    beats = {"r": "s", "s": "p", "p": "r"}
    mine = random.choice("rps")
    if pick == mine:
        result = "🤝 تعادل!"
    elif beats[pick] == mine:
        result = "🏆 فزت! +100 درهم"
        add_balance(call.message.chat.id, call.from_user.id, 100)
    else:
        result = "😅 سرداب فاز عليك!"
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"{mention(call.from_user.id, call.from_user.first_name)}: {names[pick]}\n"
        f"سرداب: {names[mine]}\n\n{result}",
        call.message.chat.id, call.message.message_id,
    )


# ---- ألعاب الأسبقية: سرعة / حساب / خمن / حزورة ----
SPEED_PHRASES = ["سرداب بوت الطولة", "الصبر مفتاح الفرج", "دبي مول", "شاهي كرك",
                 "قهوة بالهيل", "ليوا والكثبان", "ابوظبي عاصمة الامارات", "الوقت من ذهب"]


@on(text_is("سرعة"))
def game_speed(m):
    if games_off(m):
        return
    phrase = random.choice(SPEED_PHRASES)
    start_game(m, "speed", "السرعة",
               f"⚡ <b>لعبة السرعة</b>\nأول واحد يكتب العبارة التالية بالضبط يربح 150 درهم:\n\n<b>{phrase}</b>",
               [phrase], 150, 60)


@on(text_is("حساب", "رياضيات"))
def game_math(m):
    if games_off(m):
        return
    op = random.choice(["+", "-", "×"])
    if op == "+":
        a, b = random.randint(10, 99), random.randint(10, 99)
        ans = a + b
    elif op == "-":
        a = random.randint(20, 99)
        b = random.randint(10, a)
        ans = a - b
    else:
        a, b = random.randint(3, 12), random.randint(3, 12)
        ans = a * b
    start_game(m, "math", "الحساب",
               f"🧮 <b>لعبة الحساب</b>\nأول واحد يحل المسألة يربح 200 درهم:\n\n<b>{a} {op} {b} = ؟</b>",
               [str(ans)], 200, 60)


@on(text_is("خمن", "خمن الرقم"))
def game_guess(m):
    if games_off(m):
        return
    number = random.randint(1, 50)
    start_game(m, "guess", "خمن الرقم",
               "🔢 <b>خمن الرقم</b>\nفكرت في رقم من 1 إلى 50، أول واحد يطلعه يربح 300 درهم!\n"
               "اكتبوا أرقامكم وأنا أقول أكبر ولا أصغر 👇",
               [str(number)], 300, 180, extra=number)


RIDDLES = [
    ("شي له أسنان ولا يعض؟", ["المشط", "مشط"]),
    ("شي كل ما زاد نقص؟", ["العمر", "عمر"]),
    ("يمشي بدون أرجل ويبكي بدون عيون؟", ["السحاب", "سحاب", "الغيم", "غيم"]),
    ("له رقبة وما له رأس؟", ["الزجاجة", "زجاجة", "القارورة", "الفاروره"]),
    ("شي يكتب ولا يقرأ؟", ["القلم", "قلم"]),
    ("يسمع بلا أذن ويتكلم بلا لسان؟", ["الصدى", "صدى"]),
    ("بيت ما له أبواب ولا نوافذ؟", ["بيت الشعر", "بيت شعر"]),
    ("يحمل أطنان وما يقدر يحمل مسمار؟", ["البحر", "بحر"]),
    ("كل ما أخذت منه كبر؟", ["الحفرة", "حفرة", "الحفره"]),
    ("شي لك ويستخدمه غيرك أكثر منك؟", ["اسمك", "الاسم", "اسم"]),
]


@on(text_is("حزورة", "لغز", "حزوره"))
def game_riddle(m):
    if games_off(m):
        return
    q, answers = random.choice(RIDDLES)
    start_game(m, "riddle", "الحزورة",
               f"🧩 <b>حزورة</b>\n{q}\n\nأول واحد يجاوب صح يربح 250 درهم 💰",
               answers, 250, 120)


@on(text_is("ايقاف", "ايقاف اللعبة", "انهاء اللعبة"))
def stop_game(m):
    g = games.get(m.chat.id)
    if not g:
        return
    if m.from_user.id != g["starter"] and get_level(m.chat.id, m.from_user.id) < 2:
        bot.reply_to(m, "⛔ بس اللي بدأ اللعبة أو المشرف يوقفها.")
        return
    games.pop(m.chat.id, None)
    bot.reply_to(m, f"🛑 انتهت اللعبة. الإجابة كانت: <b>{esc(str(g['shown']))}</b>")


# ---- أسئلة تسلية (بدون فلوس) ----
FUN = {
    "صراحة": ("🔥 صراحة", [
        "آخر مرة بكيت فيها كانت متى؟ وليش؟",
        "مين أكثر شخص تثق فيه في هالقروب؟",
        "شي تسويه وما تبي أحد يعرف عنه؟",
        "أكبر كذبة قلتها بحياتك؟",
        "لو يعطونك مليون درهم الحين، وش أول شي تسوي فيه؟",
        "أغرب شي أكلته في حياتك؟",
        "وش اللي يعصبك بسرعة؟",
        "وش المكان اللي تحلم تزوره؟",
    ]),
    "لو خيروك": ("🤔 لو خيروك", [
        "تعيش بالصحراء بدون جوال ولا تعيش بمدينة بدون إنترنت؟",
        "ملايين بس بدون أصدقاء ولا فلوس قليلة مع شلة الطولة؟",
        "تسافر للماضي ولا للمستقبل؟",
        "تاكل هريس كل يوم ولا مجبوس كل يوم؟",
        "تفقد جوالك سنة ولا تفقد سيارتك سنة؟",
        "تكون أذكى واحد في الدنيا ولا أغنى واحد؟",
        "الشاهي بدون سكر طول عمرك ولا القهوة بدون هيل؟",
    ]),
    "كت": ("💭 كت تويت", [
        "وش أحلى ذكرى عندك من الطفولة؟",
        "شخص لو يتصل فيك الساعة 3 الفجر ترد عليه؟",
        "وش الأكلة اللي ما تمل منها؟",
        "وش أول شي تسويه إذا صحيت؟",
        "أسوأ هدية جتك في حياتك؟",
        "كلمة تحس أنها تلخص شخصيتك؟",
    ]),
}
FUN_NORM = {norm(k): v for k, v in FUN.items()}
FUN_NORM[norm("كت تويت")] = FUN["كت"]


@on(lambda m: bool(m.text) and norm(m.text) in FUN_NORM)
def fun_questions(m):
    if games_off(m):
        return
    title, items = FUN_NORM[norm(m.text)]
    bot.reply_to(m, f"{title}\n\n{random.choice(items)}")


# ================================== الزواج ==================================
db_exec("""CREATE TABLE IF NOT EXISTS marriages (
    chat_id INTEGER, user1 INTEGER, name1 TEXT, user2 INTEGER, name2 TEXT,
    mahr INTEGER DEFAULT 0, ts INTEGER)""")


def spouse_of(chat_id, uid):
    return db_one("SELECT * FROM marriages WHERE chat_id=? AND (user1=? OR user2=?)",
                  (chat_id, uid, uid))


@on(text_starts("زواج", "تزوج"))
def marry(m):
    if not m.reply_to_message or not m.reply_to_message.from_user:
        bot.reply_to(m, "💍 رد على رسالة اللي تبي تتزوجه واكتب:\n<code>زواج</code> أو <code>زواج 500</code> (المهر)")
        return
    target, me = m.reply_to_message.from_user, m.from_user
    if target.id == me.id or target.is_bot:
        bot.reply_to(m, "😅 ما يصير يا الغالي، دور لك أحد ثاني!")
        return
    if spouse_of(m.chat.id, me.id):
        bot.reply_to(m, "😏 أنت متزوج أصلاً! اكتب <b>طلاق</b> إذا تبي تبدأ من جديد.")
        return
    if spouse_of(m.chat.id, target.id):
        bot.reply_to(m, "💔 للأسف هذا الشخص متزوج.")
        return
    parts = norm(m.text).split()
    mahr = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    u = get_user(m.chat.id, me.id, me.first_name, me.username)
    if mahr > u["balance"]:
        bot.reply_to(m, f"❌ رصيدك ({u['balance']}) ما يكفي للمهر.")
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("💍 موافقة", callback_data=f"mar:y:{me.id}:{target.id}:{mahr}"),
        types.InlineKeyboardButton("💔 رفض", callback_data=f"mar:n:{me.id}:{target.id}:{mahr}"),
    )
    bot.send_message(
        m.chat.id,
        f"💍 {mention(me.id, me.first_name)} يطلب يد {mention(target.id, target.first_name)}\n"
        f"💰 المهر: <b>{mahr}</b> درهم\n\n"
        f"• {esc(target.first_name)} الأمر لك، وافق أو ارفض 👇",
        reply_markup=kb, reply_to_message_id=m.message_id,
    )


def handle_marriage(call):
    _, act, p, t, mahr = call.data.split(":")
    p, t, mahr = int(p), int(t), int(mahr)
    chat_id = call.message.chat.id
    if call.from_user.id != t:
        bot.answer_callback_query(call.id, "🤫 هذا العرض مو لك!", show_alert=True)
        return
    proposer = db_one("SELECT * FROM users WHERE user_id=? AND chat_id=?", (p, chat_id))
    pn = proposer["name"] if proposer else "العريس"
    tn = call.from_user.first_name or "العروس"
    if act == "n":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(f"💔 {mention(t, tn)} رفض عرض {mention(p, pn)}. الله يعوضك!",
                              chat_id, call.message.message_id)
        return
    if spouse_of(chat_id, p) or spouse_of(chat_id, t):
        bot.answer_callback_query(call.id, "⚠️ أحدكم تزوج قبل.", show_alert=True)
        return
    if not proposer or proposer["balance"] < mahr:
        bot.answer_callback_query(call.id, "❌ رصيد العريس ما يكفي للمهر.", show_alert=True)
        return
    if mahr:
        add_balance(chat_id, p, -mahr)
        add_balance(chat_id, t, mahr)
    db_exec("INSERT INTO marriages VALUES (?,?,?,?,?,?,?)", (chat_id, p, pn, t, tn, mahr, int(time.time())))
    bot.answer_callback_query(call.id, "💍 مبروك!")
    bot.edit_message_text(
        f"🎉💍 <b>مبروك الزواج!</b>\n{mention(p, pn)} 💞 {mention(t, tn)}\n"
        f"💰 المهر: {mahr} درهم\nالله يتمم لكم على خير 🤍",
        chat_id, call.message.message_id,
    )


@on(text_is("طلاق"))
def divorce(m):
    row = spouse_of(m.chat.id, m.from_user.id)
    if not row:
        bot.reply_to(m, "😅 أنت مو متزوج أصلاً!")
        return
    db_exec("DELETE FROM marriages WHERE chat_id=? AND user1=? AND user2=?",
            (m.chat.id, row["user1"], row["user2"]))
    bot.reply_to(m, f"💔 تم الطلاق بين {mention(row['user1'], row['name1'])} و{mention(row['user2'], row['name2'])}.")


@on(text_is("زواجي"))
def my_marriage(m):
    row = spouse_of(m.chat.id, m.from_user.id)
    if not row:
        bot.reply_to(m, "💍 أنت أعزب/عزباء. اكتب <b>زواج</b> بالرد على أحد!")
        return
    other = (row["user2"], row["name2"]) if row["user1"] == m.from_user.id else (row["user1"], row["name1"])
    days = (int(time.time()) - row["ts"]) // 86400
    bot.reply_to(m, f"💞 متزوج من {mention(*other)}\n📅 من {days} يوم\n💰 المهر: {row['mahr']} درهم")


def build_married_top(chat_id):
    rows = db_all("SELECT * FROM marriages WHERE chat_id=? ORDER BY ts ASC LIMIT 10", (chat_id,))
    if not rows:
        return "💍 توب المتزوجين\n\n📂 ما فيه متزوجين للحين."
    medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    now = int(time.time())
    lines = [f"{medals[i]} {esc(r['name1'])} 💍 {esc(r['name2'])} ⇜ <b>{(now - r['ts']) // 86400}</b> يوم"
             for i, r in enumerate(rows)]
    return "💍 توب المتزوجين\n\n" + "\n".join(lines)


# ================================ الأزرار ================================
def _callbacks(call):
    data = call.data or ""
    chat_id = call.message.chat.id

    if data.startswith("wh:"):
        return read_whisper(call)
    if data.startswith("rps:"):
        return handle_rps(call)
    if data.startswith("mar:"):
        return handle_marriage(call)
    if data == "help_menu":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, MENU_HOME, reply_markup=menu_markup())
        return
    if data == "noop":
        bot.answer_callback_query(call.id)
        return
    if data.startswith("mn:") and data[3:] in ("main", "1", "2", "3", "4"):
        bot.answer_callback_query(call.id)
        sel = data[3:]
        try:
            if sel == "main":
                bot.edit_message_text(MENU_HOME, chat_id, call.message.message_id,
                                      reply_markup=menu_markup())
            else:
                bot.edit_message_text(MENU_PAGES[sel], chat_id, call.message.message_id,
                                      reply_markup=menu_markup(sel))
        except Exception:
            pass
        return

    if data.startswith("top:"):
        kind = data.split(":")[1]
        if kind in TOPS or kind == "married":
            bot.answer_callback_query(call.id)
            try:
                txt = build_married_top(chat_id) if kind == "married" else build_top(chat_id, kind)
                bot.edit_message_text(txt, chat_id, call.message.message_id,
                                      reply_markup=top_markup())
            except Exception:
                pass
        return

    # ---- أزرار الإدارة: للمشرفين فقط (كانت مفتوحة للجميع!) ----
    if get_level(chat_id, call.from_user.id) < 2:
        bot.answer_callback_query(call.id, "• عذراً ما عندك رتبة", show_alert=True)
        return

    if data == "settings_menu":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, LOCK_HEADER, reply_markup=lock_markup(chat_id, 0))
    elif data == "mn:lock":
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(LOCK_HEADER, chat_id, call.message.message_id,
                                  reply_markup=lock_markup(chat_id, 0))
        except Exception:
            pass
    elif data == "mn:toggle":
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(TOG_HEADER, chat_id, call.message.message_id,
                                  reply_markup=settings_markup(chat_id))
        except Exception:
            pass
    elif data.startswith("lkp:"):
        page = 1 if data.endswith("1") else 0
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                          reply_markup=lock_markup(chat_id, page))
        except Exception:
            pass
    elif data.startswith("lk:"):
        _, key, page = data.split(":")
        if key in LOCK_LABEL:
            set_flag(chat_id, key, 0 if get_flag(chat_id, key) else 1)
            bot.answer_callback_query(call.id, "✅ تم")
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                              reply_markup=lock_markup(chat_id, int(page)))
            except Exception:
                pass
    elif data == "hide":
        bot.answer_callback_query(call.id)
        safe_delete(chat_id, call.message.message_id)
    elif data.startswith("tog:"):
        key = data.split(":")[1]
        if key in DEFAULTS:
            set_flag(chat_id, key, 0 if get_flag(chat_id, key) else 1)
            bot.answer_callback_query(call.id, "✅ تم التبديل")
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                              reply_markup=settings_markup(chat_id))
            except Exception:
                pass
    elif data.startswith("prot:"):
        enable = data.endswith("1")
        for k in PROT_FLAGS:
            set_flag(chat_id, k, enable)
        bot.answer_callback_query(call.id, "🛡 تم تفعيل الحماية الكاملة" if enable else "⚠️ تم تعطيل الحماية")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                          reply_markup=settings_markup(chat_id))
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    try:
        _callbacks(call)
    except Exception as e:
        print("callback error:", e)
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


# ---- الردود المضافة بـ (اضف رد) ----
_SEND = {"photo": "send_photo", "sticker": "send_sticker", "animation": "send_animation",
         "video": "send_video", "voice": "send_voice", "document": "send_document",
         "audio": "send_audio", "video_note": "send_video_note"}


def _custom_reply_row(m):
    if not m.text or not get_flag(m.chat.id, "replies"):
        return None
    word = norm(m.text)
    vip = db_one("SELECT * FROM vip_replies WHERE chat_id=? AND word=?", (m.chat.id, word))
    if vip and m.from_user is not None and get_level(m.chat.id, m.from_user.id) >= 1:
        return vip  # الرد المميز لأصحاب الرتب (يغطي على الرد العادي)
    return db_one("SELECT * FROM replies WHERE chat_id=? AND word=?", (m.chat.id, word))


@on(lambda m: _custom_reply_row(m) is not None)
def custom_reply(m):
    r = _custom_reply_row(m)
    if not r:
        return
    try:
        if r["kind"] == "text":
            bot.reply_to(m, r["text"] or "")
            return
        fn = getattr(bot, _SEND[r["kind"]])
        kw = {"reply_to_message_id": m.message_id}
        if r["text"] and r["kind"] not in ("sticker", "video_note"):
            kw["caption"] = r["text"]
        fn(m.chat.id, r["file_id"], **kw)
    except Exception as e:
        print("custom reply error:", e)


# ======= لازم يكون آخر معالج: يلتقط إجابات الألعاب اللي ما أخذها أي أمر =======
@on(lambda m: bool(m.text) and m.chat.id in games)
def game_answers(m):
    g = games.get(m.chat.id)
    if not g:
        return
    if g["until"] < time.time():
        games.pop(m.chat.id, None)
        return
    t = norm(m.text)
    if g["kind"] == "guess":
        if not t.isdigit():
            return
        n = int(t)
        if n == g["extra"]:
            win_game(m, g)
        else:
            bot.reply_to(m, "⬆️ أكبر" if n < g["extra"] else "⬇️ أصغر")
        return
    if t in g["answers"]:
        win_game(m, g)


# ================================== التشغيل ==================================
print("🔥 بوت سرداب يعمل: حماية + رتب + همسات + ألعاب + بنك")
bot.remove_webhook()
bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
