import os
import re
import time
import html
import sqlite3
import threading

import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from flask import Flask, request

# ============================================================
# الإعدادات
# ============================================================
MAIN_TOKEN = os.environ.get("MAIN_TOKEN")
RENDER_URL = os.environ.get("RENDER_URL", "https://my-bot-maker-1.onrender.com").rstrip("/")
PORT = int(os.environ.get("PORT", 8080))
MY_ADMIN_ID = int(os.environ.get("MY_ADMIN_ID", "9050871827"))

# مجلد حفظ قواعد البيانات. على Render اربط Disk على المسار /data
# وضع DATA_DIR=/data في متغيرات البيئة حتى لا تضيع البيانات عند إعادة التشغيل.
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

ALL_CONTENT = ["text", "photo", "video", "document", "voice", "sticker", "audio", "video_note", "animation"]

main_bot = telebot.TeleBot(MAIN_TOKEN, threaded=False)
app = Flask(__name__)


# ============================================================
# طبقة قاعدة بيانات آمنة مع تعدد الخيوط
# ============================================================
class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()

    def run(self, sql, params=(), fetch=None):
        """fetch: None / 'one' / 'all'"""
        with self.lock:
            cur = self.conn.execute(sql, params)
            result = None
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            self.conn.commit()
            return result


main_db = DB(os.path.join(DATA_DIR, "bot_maker.db"))
main_db.run("CREATE TABLE IF NOT EXISTS bots (token TEXT PRIMARY KEY, admin_id INTEGER, bot_username TEXT)")
main_db.run("CREATE TABLE IF NOT EXISTS main_users (user_id INTEGER PRIMARY KEY)")
main_db.run("CREATE TABLE IF NOT EXISTS main_state (user_id INTEGER PRIMARY KEY, action TEXT)")

sub_bots_cache = {}
cache_lock = threading.Lock()


# ============================================================
# البوتات الفرعية
# ============================================================
def setup_sub_bot_handlers(sub_bot, admin_id, db):
    def get_setting(key, default=None):
        row = db.run("SELECT value FROM settings WHERE key = ?", (key,), "one")
        return row[0] if row else default

    def set_setting(key, value):
        db.run("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    def get_state():
        row = db.run("SELECT action FROM state WHERE user_id = ?", (admin_id,), "one")
        return row[0] if row else None

    def set_state(action):
        db.run("INSERT OR REPLACE INTO state (user_id, action) VALUES (?, ?)", (admin_id, action))

    def clear_state():
        db.run("DELETE FROM state WHERE user_id = ?", (admin_id,))

    # القيم الافتراضية
    if get_setting("welcome_msg") is None:
        set_setting("welcome_msg", "أهلاً بك. أرسل رسالتك وسنرد قريباً")
    if get_setting("reply_msg") is None:
        set_setting("reply_msg", "✅ تم إرسال رسالتك بنجاح.")
    if get_setting("show_identity") is None:
        set_setting("show_identity", "ON")

    def admin_panel_kb():
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        status = "مفعل ✅" if get_setting("show_identity", "ON") == "ON" else "معطل ❌"
        kb.add(KeyboardButton("⚙️ تغيير الترحيب"), KeyboardButton("📩 تغيير الاستلام"))
        kb.add(KeyboardButton(f"👤 الهوية: {status}"))
        kb.add(KeyboardButton("📢 إذاعة"), KeyboardButton("🚫 المحظورين"))
        kb.add(KeyboardButton("📊 الإحصائيات"))
        return kb

    def is_admin_msg(m):
        return m.from_user is not None and m.from_user.id == admin_id and m.chat.type == "private"

    def is_user_msg(m):
        return m.from_user is not None and m.from_user.id != admin_id and m.chat.type == "private"

    ADMIN_BUTTONS = ["⚙️ تغيير الترحيب", "📩 تغيير الاستلام", "📢 إذاعة", "🚫 المحظورين", "📊 الإحصائيات"]

    # ---------------- /start ----------------
    @sub_bot.message_handler(commands=["start"], func=lambda m: m.chat.type == "private")
    def sub_start(message):
        user_id = message.from_user.id
        if user_id == admin_id:
            clear_state()
            sub_bot.send_message(message.chat.id, "💎 أهلاً بك يا مالك البوت.", reply_markup=admin_panel_kb())
            return

        if db.run("SELECT 1 FROM banned WHERE user_id = ?", (user_id,), "one"):
            sub_bot.send_message(message.chat.id, "❌ تم حظرك.")
            return

        db.run("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        sub_bot.send_message(message.chat.id, get_setting("welcome_msg", "أهلاً بك، أرسل رسالتك."))

    # ---------------- أزرار لوحة المالك ----------------
    @sub_bot.message_handler(
        func=lambda m: is_admin_msg(m) and bool(m.text) and (m.text in ADMIN_BUTTONS or m.text.startswith("👤 الهوية"))
    )
    def admin_controls(message):
        text = message.text
        clear_state()

        if "تغيير الترحيب" in text:
            set_state("welcome")
            sub_bot.send_message(message.chat.id, "أرسل الترحيب الجديد:")

        elif "تغيير الاستلام" in text:
            set_state("reply")
            sub_bot.send_message(message.chat.id, "أرسل رسالة الاستلام الجديدة:")

        elif "الهوية" in text:
            new_val = "OFF" if get_setting("show_identity", "ON") == "ON" else "ON"
            set_setting("show_identity", new_val)
            sub_bot.send_message(
                message.chat.id,
                f"✅ الحالة: {'مفعل ✅' if new_val == 'ON' else 'معطل ❌'}",
                reply_markup=admin_panel_kb(),
            )

        elif "إذاعة" in text:
            set_state("broadcast")
            sub_bot.send_message(message.chat.id, "📢 أرسل رسالة الإذاعة:")

        elif "المحظورين" in text:
            banned = db.run("SELECT user_id FROM banned", fetch="all")
            if not banned:
                sub_bot.send_message(message.chat.id, "📂 قائمة المحظورين فارغة.")
            else:
                markup = InlineKeyboardMarkup()
                for b in banned:
                    markup.add(InlineKeyboardButton(f"🔓 رفع الحظر ({b[0]})", callback_data=f"unban_{b[0]}"))
                sub_bot.send_message(message.chat.id, "🚫 قائمة المحظورين:", reply_markup=markup)

        elif "الإحصائيات" in text:
            u_count = db.run("SELECT COUNT(*) FROM users", fetch="one")[0]
            b_count = db.run("SELECT COUNT(*) FROM banned", fetch="one")[0]
            sub_bot.send_message(message.chat.id, f"📊 الإحصائيات:\n\n👥 المشتركين: {u_count}\n🚫 المحظورين: {b_count}")

    # ---------------- حالات الإدخال (محفوظة في القاعدة) ----------------
    @sub_bot.message_handler(func=lambda m: is_admin_msg(m) and get_state() is not None, content_types=ALL_CONTENT)
    def admin_state_handler(message):
        action = get_state()

        if action in ("welcome", "reply"):
            if not message.text:
                sub_bot.send_message(message.chat.id, "⚠️ أرسل نصاً فقط.")
                return
            set_setting("welcome_msg" if action == "welcome" else "reply_msg", message.text)
            clear_state()
            sub_bot.send_message(message.chat.id, "✅ تم الحفظ.", reply_markup=admin_panel_kb())

        elif action == "broadcast":
            clear_state()
            users = db.run("SELECT user_id FROM users", fetch="all")
            status_msg = sub_bot.send_message(message.chat.id, "⏳ جاري الإذاعة...")
            success, failed = 0, 0
            for u in users:
                try:
                    sub_bot.copy_message(u[0], message.chat.id, message.message_id)
                    success += 1
                except Exception:
                    failed += 1
                time.sleep(0.05)  # تجنب حدود تيليجرام
            try:
                sub_bot.edit_message_text(
                    f"📢 تمت الإذاعة:\n\n✅ نجاح: {success}\n❌ فشل: {failed}",
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                )
            except Exception:
                pass
            sub_bot.send_message(message.chat.id, "✅ انتهت الإذاعة.", reply_markup=admin_panel_kb())

    # ---------------- رد المالك على المستخدم (Reply) ----------------
    @sub_bot.message_handler(
        func=lambda m: is_admin_msg(m) and m.reply_to_message is not None,
        content_types=ALL_CONTENT,
    )
    def admin_reply(message):
        row = db.run(
            "SELECT user_id FROM forwarded WHERE msg_id = ?",
            (message.reply_to_message.message_id,),
            "one",
        )
        if not row:
            sub_bot.send_message(message.chat.id, "⚠️ اعمل Reply على رسالة المستخدم (أو على الرسالة اللي فيها بياناته).")
            return
        try:
            sub_bot.copy_message(row[0], message.chat.id, message.message_id)
            sub_bot.send_message(message.chat.id, "✅ تم إرسال ردك.", reply_to_message_id=message.message_id)
        except Exception as e:
            sub_bot.send_message(message.chat.id, f"❌ تعذر الإرسال (ربما المستخدم حظر البوت):\n{e}")

    # ---------------- رسائل المستخدمين ----------------
    @sub_bot.message_handler(func=is_user_msg, content_types=ALL_CONTENT)
    def handle_user_msg(message):
        user_id = message.from_user.id
        if db.run("SELECT 1 FROM banned WHERE user_id = ?", (user_id,), "one"):
            return

        db.run("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))

        name = html.escape(message.from_user.first_name or "")
        username = f"@{message.from_user.username}" if message.from_user.username else "بدون"
        username = html.escape(username)

        if get_setting("show_identity", "ON") == "ON":
            header = f"📩 رسالة:\n👤 {name}\n🔗 {username}\n🆔 <code>{user_id}</code>"
        else:
            header = f"📩 رسالة (هوية مخفية):\n🆔 <code>{user_id}</code>"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚫 حظر", callback_data=f"ban_{user_id}"))

        try:
            sent_header = sub_bot.send_message(admin_id, header, parse_mode="HTML", reply_markup=markup)
            copied = sub_bot.copy_message(admin_id, message.chat.id, message.message_id)
            # نحفظ الربط لنقدر نرد على المستخدم
            db.run("INSERT OR REPLACE INTO forwarded (msg_id, user_id) VALUES (?, ?)", (sent_header.message_id, user_id))
            db.run("INSERT OR REPLACE INTO forwarded (msg_id, user_id) VALUES (?, ?)", (copied.message_id, user_id))
        except Exception as e:
            print(f"[sub-bot] failed to deliver to admin: {e}")
            return

        sub_bot.send_message(message.chat.id, get_setting("reply_msg", "✅ تم الإرسال."), reply_to_message_id=message.message_id)

    # ---------------- أزرار Inline ----------------
    @sub_bot.callback_query_handler(func=lambda call: True)
    def sub_callbacks(call):
        if call.from_user.id != admin_id:
            sub_bot.answer_callback_query(call.id, "⚠️ غير مسموح.")
            return

        data = call.data or ""
        try:
            if data.startswith("ban_"):
                target = int(data.split("_", 1)[1])
                db.run("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (target,))
                sub_bot.answer_callback_query(call.id, f"🚫 تم الحظر {target}", show_alert=True)
                try:
                    sub_bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                except Exception:
                    pass

            elif data.startswith("unban_"):
                target = int(data.split("_", 1)[1])
                db.run("DELETE FROM banned WHERE user_id = ?", (target,))
                sub_bot.answer_callback_query(call.id, f"✅ تم رفع الحظر {target}", show_alert=True)
                try:
                    sub_bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
        except Exception as e:
            print(f"[sub-bot] callback error: {e}")


def get_or_create_sub_bot(token, admin_id):
    with cache_lock:
        if token in sub_bots_cache:
            return sub_bots_cache[token]

        sub_bot = telebot.TeleBot(token, threaded=False)

        # قاعدة بيانات مستقلة لكل بوت
        bot_id = token.split(":")[0]
        db = DB(os.path.join(DATA_DIR, f"sub_{bot_id}.db"))
        db.run("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        db.run("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        db.run("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")
        db.run("CREATE TABLE IF NOT EXISTS state (user_id INTEGER PRIMARY KEY, action TEXT)")
        db.run("CREATE TABLE IF NOT EXISTS forwarded (msg_id INTEGER PRIMARY KEY, user_id INTEGER)")

        setup_sub_bot_handlers(sub_bot, admin_id, db)
        sub_bots_cache[token] = sub_bot
        return sub_bot


def set_sub_webhook(token, admin_id):
    sub_bot = get_or_create_sub_bot(token, admin_id)
    sub_bot.remove_webhook()
    sub_bot.set_webhook(url=f"{RENDER_URL}/webhook/{token}")


def restore_all_sub_bots():
    rows = main_db.run("SELECT token, admin_id FROM bots", fetch="all")
    for token, admin_id in rows:
        try:
            set_sub_webhook(token, admin_id)
            print(f"[restore] webhook OK for bot {token.split(':')[0]}")
        except Exception as e:
            print(f"[restore] error for bot {token.split(':')[0]}: {e}")
        time.sleep(0.2)


# ============================================================
# البوت الرئيسي (الصانع)
# ============================================================
def main_state_get(user_id):
    row = main_db.run("SELECT action FROM main_state WHERE user_id = ?", (user_id,), "one")
    return row[0] if row else None


def main_state_set(user_id, action):
    main_db.run("INSERT OR REPLACE INTO main_state (user_id, action) VALUES (?, ?)", (user_id, action))


def main_state_clear(user_id):
    main_db.run("DELETE FROM main_state WHERE user_id = ?", (user_id,))


def get_main_keyboard(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ صنع بوت جديد"), KeyboardButton("📋 بوتاتك"))
    if is_admin:
        kb.add(KeyboardButton("📢 إذاعة عامة"))
    return kb


@main_bot.message_handler(commands=["start"])
def main_start(message):
    main_state_clear(message.from_user.id)
    main_db.run("INSERT OR IGNORE INTO main_users (user_id) VALUES (?)", (message.from_user.id,))
    is_adm = message.from_user.id == MY_ADMIN_ID
    main_bot.send_message(message.chat.id, "أهلاً بك في صانع البوتات 🛠️", reply_markup=get_main_keyboard(is_adm))


@main_bot.message_handler(func=lambda m: m.text in ["➕ صنع بوت جديد", "📋 بوتاتك", "📢 إذاعة عامة"])
def main_menu_handler(message):
    uid = message.from_user.id
    main_state_clear(uid)

    if message.text == "➕ صنع بوت جديد":
        main_state_set(uid, "new_token")
        main_bot.send_message(message.chat.id, "أرسل توكن البوت من @BotFather:")

    elif message.text == "📋 بوتاتك":
        bots = main_db.run("SELECT bot_username FROM bots WHERE admin_id = ?", (uid,), "all")
        if not bots:
            main_bot.send_message(message.chat.id, "⚠️ ليس لديك بوتات.")
        else:
            main_bot.send_message(message.chat.id, "📋 بوتاتك:\n\n" + "\n".join(f"🤖 @{b[0]}" for b in bots))

    elif message.text == "📢 إذاعة عامة":
        if uid == MY_ADMIN_ID:
            main_state_set(uid, "main_broadcast")
            main_bot.send_message(message.chat.id, "📢 أرسل الإذاعة العامة (روابط، أخبار، إعلانات):")
        else:
            main_bot.send_message(message.chat.id, "⚠️ هذا الأمر مخصص للمطور فقط.")


@main_bot.message_handler(
    func=lambda m: main_state_get(m.from_user.id) is not None,
    content_types=ALL_CONTENT,
)
def main_state_handler(message):
    uid = message.from_user.id
    action = main_state_get(uid)

    if action == "new_token":
        if not message.text:
            main_bot.send_message(message.chat.id, "⚠️ أرسل التوكن كنص.")
            return
        main_state_clear(uid)
        process_new_token(message)

    elif action == "main_broadcast":
        main_state_clear(uid)
        if uid == MY_ADMIN_ID:
            process_main_broadcast(message)


def process_main_broadcast(message):
    users = main_db.run("SELECT user_id FROM main_users", fetch="all")
    status_msg = main_bot.send_message(message.chat.id, "⏳ جاري إرسال الإذاعة العامة...")
    success, failed = 0, 0
    for u in users:
        try:
            main_bot.copy_message(u[0], message.chat.id, message.message_id)
            success += 1
        except Exception:
            failed += 1
        time.sleep(0.05)
    main_bot.edit_message_text(
        f"📢 تمت الإذاعة العامة:\n\n✅ نجاح: {success}\n❌ فشل: {failed}",
        chat_id=status_msg.chat.id,
        message_id=status_msg.message_id,
    )


@main_bot.callback_query_handler(func=lambda call: True)
def main_callbacks(call):
    if call.data == "how_token":
        main_bot.answer_callback_query(call.id, "اذهب إلى @BotFather وأرسل /newbot", show_alert=True)
    elif call.data == "what_token":
        main_bot.answer_callback_query(call.id, "التوكن هو الرقم السري للبوت.", show_alert=True)


TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


def process_new_token(message):
    token = message.text.strip()
    admin_id = message.from_user.id

    if not TOKEN_RE.match(token):
        main_bot.send_message(message.chat.id, "❌ صيغة التوكن غير صحيحة. انسخه من @BotFather كما هو.")
        return

    if token == MAIN_TOKEN:
        main_bot.send_message(message.chat.id, "⚠️ لا يمكن استخدام توكن البوت الصانع.")
        return

    if main_db.run("SELECT 1 FROM bots WHERE token = ?", (token,), "one"):
        main_bot.send_message(message.chat.id, "⚠️ هذا البوت مسجل مسبقاً!")
        return

    msg_wait = main_bot.send_message(message.chat.id, "⏳ جاري تفعيل البوت...")
    try:
        bot_username = telebot.TeleBot(token).get_me().username
        main_db.run("INSERT INTO bots (token, admin_id, bot_username) VALUES (?, ?, ?)", (token, admin_id, bot_username))

        try:
            set_sub_webhook(token, admin_id)
        except Exception:
            # فشل الويب هوك: نحذف التسجيل حتى لا يبقى بوت ميت
            main_db.run("DELETE FROM bots WHERE token = ?", (token,))
            with cache_lock:
                sub_bots_cache.pop(token, None)
            raise

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 افتح البوت", url=f"https://t.me/{bot_username}"))
        main_bot.edit_message_text(
            f"🎉 تم تفعيل البوت بنجاح!\n\n🤖 @{bot_username}\n\nأرسل له /start لتظهر لك لوحة التحكم.",
            chat_id=msg_wait.chat.id,
            message_id=msg_wait.message_id,
            reply_markup=markup,
        )
    except Exception as e:
        main_bot.edit_message_text(
            f"❌ خطأ:\n{e}",
            chat_id=msg_wait.chat.id,
            message_id=msg_wait.message_id,
        )


# ============================================================
# مسارات Flask
# ============================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    try:
        main_bot.process_new_updates([update])
    except Exception as e:
        print(f"[main webhook] error: {e}")
    return "!", 200


@app.route("/webhook/<token>", methods=["POST"])
def sub_webhook(token):
    row = main_db.run("SELECT admin_id FROM bots WHERE token = ?", (token,), "one")
    if not row:
        return "Bot not found", 404

    sub_bot = get_or_create_sub_bo
