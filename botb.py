import os
import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
import sqlite3
import html
import time

# ==================== جلب البيانات من Environment Variables ====================
TOKEN = os.environ.get("TOKEN")
ADMIN_ID_STR = os.environ.get("ADMIN_ID")

# فحص سريع للتأكد من إدخال المتغيرات في رندر
if not TOKEN or not ADMIN_ID_STR:
    print(
        "❌ خطأ: يرجى إضافة TOKEN و ADMIN_ID في متغيرات البيئة (Environment Variables) على موقع Render!"
    )
    exit(1)

ADMIN_ID = int(ADMIN_ID_STR)
CHANNEL_USER = "t7x_i"  # معرف قناتك
# ==============================================================================

bot = telebot.TeleBot(TOKEN, threaded=False)

# إعداد قاعدة البيانات
conn = sqlite3.connect("contact_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
cursor.execute(
    "CREATE TABLE IF NOT EXISTS forwarded (msg_id INTEGER PRIMARY KEY, user_id INTEGER)"
)
cursor.execute(
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
)
cursor.execute(
    "CREATE TABLE IF NOT EXISTS states (user_id INTEGER PRIMARY KEY, state TEXT)"
)
conn.commit()


def get_setting(key, default):
    row = cursor.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


# واجهة الترحيب الاحترافية المشابهة لصارحني
default_welcome = (
    "✉️ **مرحباً بك في بوت التواصل المباشر**\n\n"
    "💎 ماذا يمكن لهذا البوت أن يفعله؟\n"
    "🔹 أرسل رسالتك وسنقوم بتوصيلها إلى الإدارة مباشرة.\n"
    "🔹 يمكنك إرسال النصوص، الصور، الفيديوهات، والملصقات بكل سهولة.\n"
    "🔹 نضمن لك سرية تامة وسرعة في الرد.\n\n"
    f"📢 قناتنا: @{CHANNEL_USER}\n"
    "👇 **الآن، قم بكتابة رسالتك وأرسلها هنا:**"
)

if not get_setting("welcome_msg", None):
    set_setting("welcome_msg", default_welcome)
if not get_setting("reply_msg", None):
    set_setting(
        "reply_msg", "✅ تم إرسال رسالتك إلى الإدارة بنجاح، شكراً لتواصلك معنا."
    )
if not get_setting("allow_media", None):
    set_setting("allow_media", "ON")


def get_state(user_id):
    row = cursor.execute(
        "SELECT state FROM states WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row[0] if row else None


def set_state(user_id, state):
    cursor.execute(
        "INSERT OR REPLACE INTO states (user_id, state) VALUES (?, ?)", (user_id, state)
    )
    conn.commit()


def clear_state(user_id):
    cursor.execute("DELETE FROM states WHERE user_id = ?", (user_id,))
    conn.commit()


def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    media_status = (
        "مفعل ✅" if get_setting("allow_media", "ON") == "ON" else "معطل ❌"
    )
    kb.add(KeyboardButton("⚙️ تعديل الترحيب"), KeyboardButton("📩 تعديل الاستلام"))
    kb.add(KeyboardButton(f"📥 استقبال الوسائط: {media_status}"))
    kb.add(KeyboardButton("📢 إذاعة عامة"), KeyboardButton("👥 الإحصائيات"))
    kb.add(KeyboardButton("🚫 المحظورين"))
    return kb


@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    clear_state(user_id)

    if user_id == ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "💎 أهلاً بك يا مالك البوت، إليك لوحة التحكم:",
            reply_markup=admin_keyboard(),
        )
    else:
        if cursor.execute(
            "SELECT 1 FROM banned WHERE user_id = ?", (user_id,)
        ).fetchone():
            bot.reply_to(message, "❌ عذراً، لقد تم حظرك من استخدام هذا البوت.")
            return

        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        bot.reply_to(
            message,
            get_setting("welcome_msg", default_welcome),
            parse_mode="Markdown",
        )


@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID
    and (
        m.text
        in [
            "⚙️ تعديل الترحيب",
            "📩 تعديل الاستلام",
            "📢 إذاعة عامة",
            "👥 الإحصائيات",
            "🚫 المحظورين",
        ]
        or "استقبال الوسائط" in m.text
    )
)
def admin_menu_clicks(message):
    text = message.text
    user_id = message.from_user.id

    if "تعديل الترحيب" in text:
        set_state(user_id, "set_welcome")
        bot.send_message(
            message.chat.id,
            "أرسل نص رسالة الترحيب الجديد الآن (يمكنك استخدام التنسيق):",
        )
    elif "تعديل الاستلام" in text:
        set_state(user_id, "set_reply")
        bot.send_message(message.chat.id, "أرسل نص رسالة الاستلام الجديدة:")
    elif "استقبال الوسائط" in text:
        current = get_setting("allow_media", "ON")
        new_val = "OFF" if current == "ON" else "ON"
        set_setting("allow_media", new_val)
        status_text = (
            "مفعل ✅ (يمكنهم إرسال صور وفيديوهات وملصقات)"
            if new_val == "ON"
            else "معطل ❌ (مسموح النصوص فقط)"
        )
        bot.send_message(
            message.chat.id,
            f"📥 تم تغيير حالة استقبال الوسائط إلى:\n{status_text}",
            reply_markup=admin_keyboard(),
        )
    elif "إذاعة" in text:
        set_state(user_id, "broadcast")
        bot.send_message(message.chat.id, "📢 أرسل رسالة الإذاعة:")
    elif "الإحصائيات" in text:
        u_count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        b_count = cursor.execute("SELECT COUNT(*) FROM banned").fetchone()[0]
        bot.send_message(
            message.chat.id,
            f"📊 الإحصائيات:\n\n👥 عدد المشتركين: {u_count}\n🚫 عدد المحظورين: {b_count}",
            reply_markup=admin_keyboard(),
        )
    elif "المحظورين" in text:
        banned_users = cursor.execute("SELECT user_id FROM banned").fetchall()
        if not banned_users:
            bot.send_message(
                message.chat.id, "📂 قائمة المحظورين فارغة.", reply_markup=admin_keyboard()
            )
        else:
            markup = InlineKeyboardMarkup()
            for b in banned_users:
                markup.add(
                    InlineKeyboardButton(
                        f"🔓 إلغاء حظر ({b[0]})", callback_data=f"unban_{b[0]}"
                    )
                )
            bot.send_message(
                message.chat.id,
                "🚫 قائمة المحظورين (اضغط على الزر لرفع الحظر):",
                reply_markup=markup,
            )


@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and get_state(m.from_user.id) is not None,
    content_types=["text", "photo", "video", "document", "voice", "audio"],
)
def handle_admin_states(message):
    user_id = message.from_user.id
    state = get_state(user_id)

    if state == "set_welcome":
        if not message.text:
            bot.send_message(message.chat.id, "⚠️ الرجاء إرسال نص فقط للترحيب.")
            return
        set_setting("welcome_msg", message.text)
        clear_state(user_id)
        bot.send_message(
            message.chat.id, "✅ تم حفظ الترحيب.", reply_markup=admin_keyboard()
        )

    elif state == "set_reply":
        if not message.text:
            bot.send_message(message.chat.id, "⚠️ الرجاء إرسال نص فقط.")
            return
        set_setting("reply_msg", message.text)
        clear_state(user_id)
        bot.send_message(
            message.chat.id, "✅ تم حفظ الاستلام.", reply_markup=admin_keyboard()
        )

    elif state == "broadcast":
        clear_state(user_id)
        users = cursor.execute("SELECT user_id FROM users").fetchall()
        status_msg = bot.send_message(message.chat.id, "⏳ جاري بدء الإذاعة...")
        success, failed = 0, 0
        for u in users:
            try:
                bot.copy_message(u[0], message.chat.id, message.message_id)
                success += 1
            except:
                failed += 1
            time.sleep(0.04)
        bot.send_message(
            message.chat.id,
            f"📢 انتهت الإذاعة:\n\n✅ نجاح: {success}\n❌ فشل: {failed}",
            reply_markup=admin_keyboard(),
        )


# رد المالك على المستخدمين
@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and m.reply_to_message is not None,
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "voice",
        "sticker",
        "audio",
    ],
)
def reply_to_user(message):
    row = cursor.execute(
        "SELECT user_id FROM forwarded WHERE msg_id = ?",
        (message.reply_to_message.message_id,),
    ).fetchone()
    if not row:
        bot.send_message(
            message.chat.id,
            "⚠️ يرجى عمل (رد / Reply) بالتليجرام على رسالة المستخدم نفسها.",
        )
        return

    target_user_id = row[0]
    try:
        bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        bot.send_message(message.chat.id, "✅ تم إرسال الرد للمستخدم.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ تعذر الإرسال:\n{e}")


# استقبال رسائل المستخدمين
@bot.message_handler(
    func=lambda m: m.from_user.id != ADMIN_ID and m.chat.type == "private",
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "voice",
        "sticker",
        "audio",
        "video_note",
        "animation",
    ],
)
def handle_user_message(message):
    user_id = message.from_user.id

    if cursor.execute(
        "SELECT 1 FROM banned WHERE user_id = ?", (user_id,)
    ).fetchone():
        bot.reply_to(
            message,
            "❌ عذراً، لقد تم حظرك من استخدام هذا البوت ولا يمكنك مراسلة الإدارة.",
        )
        return

    allow_media = get_setting("allow_media", "ON")
    if allow_media == "OFF" and message.content_type != "text":
        bot.reply_to(
            message,
            "⚠️ عذراً، استقبال الوسائط معطل حالياً من قِبل الإدارة. مسموح بإرسال النصوص فقط.",
        )
        return

    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    name = html.escape(message.from_user.first_name or "")
    username = (
        f"@{message.from_user.username}" if message.from_user.username else "بدون"
    )

    header = f"📩 رسالة جديدة ({message.content_type}):\n👤 الاسم: {name}\n🔗 المعرف: {username}\n🆔 الآيدي: <code>{user_id}</code>"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🚫 حظر المستخدم", callback_data=f"ban_{user_id}")
    )

    try:
        sent_msg = bot.send_message(
            ADMIN_ID, header, parse_mode="HTML", reply_markup=markup
        )
        copied_msg = bot.copy_message(
            ADMIN_ID, message.chat.id, message.message_id
        )

        cursor.execute(
            "INSERT OR REPLACE INTO forwarded (msg_id, user_id) VALUES (?, ?)",
            (sent_msg.message_id, user_id),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO forwarded (msg_id, user_id) VALUES (?, ?)",
            (copied_msg.message_id, user_id),
        )
        conn.commit()
    except Exception as e:
        print(f"Error forwarding: {e}")
        return

    bot.reply_to(message, get_setting("reply_msg", "✅ تم إرسال رسالتك بنجاح."))


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    data = call.data
    user_id = call.from_user.id

    if user_id != ADMIN_ID:
        return

    if data.startswith("ban_"):
        target_id = int(data.split("_")[1])
        cursor.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (target_id,))
        conn.commit()
        bot.answer_callback_query(
            call.id, f"🚫 تم الحظر {target_id}", show_alert=True
        )
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=None
            )
        except:
            pass
    elif data.startswith("unban_"):
        target_id = int(data.split("_")[1])
        cursor.execute("DELETE FROM banned WHERE user_id = ?", (target_id,))
        conn.commit()
        bot.answer_callback_query(
            call.id, f"✅ تم رفع الحظر عن المستخدم {target_id}", show_alert=True
        )
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass


print("بوت التواصل يعمل بكفاءة تامة 🚀")
bot.infinity_polling(skip_pending=True)
