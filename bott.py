import os
import sqlite3
import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from flask import Flask, request

MAIN_TOKEN = os.environ.get("MAIN_TOKEN")
main_bot = telebot.TeleBot(MAIN_TOKEN)
app = Flask(__name__)

RENDER_URL = "https://my-bot-maker-1.onrender.com"
PORT = int(os.environ.get("PORT", 8080))

sub_bots_cache = {}

# اتصال قاعدة البيانات الرئيسية مع السماح بتعدد الخيوط
conn_main = sqlite3.connect("bot_maker.db", check_same_thread=False)

with conn_main:
    conn_main.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            token TEXT PRIMARY KEY, 
            admin_id INTEGER, 
            bot_username TEXT
        )
    """)
    conn_main.execute("""
        CREATE TABLE IF NOT EXISTS main_users (
            user_id INTEGER PRIMARY KEY
        )
    """)

# إعداد معالجات الأحداث للبوت الفرعي
def setup_sub_bot_handlers(sub_bot, admin_id, conn_sub):
    def get_setting(key, default):
        cur = conn_sub.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        res = cur.fetchone()
        return res[0] if res else default

    def set_setting(key, value):
        cur = conn_sub.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn_sub.commit()

    if not get_setting("welcome_msg", None):
        set_setting("welcome_msg", "أهلاً بك. أرسل رسالتك وسنرد قريباً")
    if not get_setting("reply_msg", None):
        set_setting("reply_msg", "✅ تم إرسال رسالتك بنجاح.")
    if not get_setting("show_identity", None):
        set_setting("show_identity", "ON")

    def admin_panel_kb():
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        status_id = "مفعل ✅" if get_setting("show_identity", "ON") == "ON" else "معطل ❌"
        kb.add(KeyboardButton("⚙️ تغيير الترحيب"), KeyboardButton("📩 تغيير الاستلام"))
        kb.add(KeyboardButton(f"👤 الهوية: {status_id}"))
        kb.add(KeyboardButton("📢 إذاعة"), KeyboardButton("🚫 المحظورين"))
        kb.add(KeyboardButton("📊 الإحصائيات"))
        return kb

    @sub_bot.message_handler(commands=["start"])
    def sub_start(message):
        user_id = message.from_user.id
        cur = conn_sub.cursor()
        if user_id == admin_id:
            sub_bot.send_message(message.chat.id, "💎 أهلاً بك يا مالك البوت.", reply_markup=admin_panel_kb())
        else:
            cur.execute("SELECT * FROM banned WHERE user_id = ?", (user_id,))
            if cur.fetchone():
                sub_bot.reply_to(message, "❌ تم حظرك.")
                return
            cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            conn_sub.commit()
            welcome_text = get_setting("welcome_msg", "أهلاً بك، أرسل رسالتك.")
            sub_bot.reply_to(message, welcome_text)

    @sub_bot.message_handler(
        func=lambda m: m.chat.id == admin_id and m.text in [
            "⚙️ تغيير الترحيب", "📩 تغيير الاستلام", "📢 إذاعة", "🚫 المحظورين", "📊 الإحصائيات"
        ] or (m.chat.id == admin_id and "الهوية" in m.text)
    )
    def admin_controls(message):
        cur = conn_sub.cursor()
        if "تغيير الترحيب" in message.text:
            msg = sub_bot.reply_to(message, "أرسل الترحيب الجديد:")
            sub_bot.register_next_step_handler(msg, save_welcome)
        elif "تغيير الاستلام" in message.text:
            msg = sub_bot.reply_to(message, "أرسل رسالة الاستلام الجديدة:")
            sub_bot.register_next_step_handler(msg, save_reply_msg)
        elif "الهوية" in message.text:
            current = get_setting("show_identity", "ON")
            new_val = "OFF" if current == "ON" else "ON"
            set_setting("show_identity", new_val)
            sub_bot.reply_to(
                message,
                f"✅ الحالة: {'مفعل ✅' if new_val=='ON' else 'معطل ❌'}",
                reply_markup=admin_panel_kb(),
            )
        elif "إذاعة" in message.text:
            msg = sub_bot.reply_to(message, "📢 أرسل رسالة الإذاعة:")
            sub_bot.register_next_step_handler(msg, process_broadcast)
        elif "المحظورين" in message.text:
            cur.execute("SELECT user_id FROM banned")
            banned_users = cur.fetchall()
            if not banned_users:
                sub_bot.reply_to(message, "📂 قائمة المحظورين فارغة.")
            else:
                markup = InlineKeyboardMarkup()
                for b in banned_users:
                    markup.add(InlineKeyboardButton(f"🔓 رفع الحظر ({b[0]})", callback_data=f"unban_{b[0]}"))
                sub_bot.reply_to(message, "🚫 قائمة المحظورين:", reply_markup=markup)
        elif "الإحصائيات" in message.text:
            cur.execute("SELECT COUNT(*) FROM users")
            u_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM banned")
            b_count = cur.fetchone()[0]
            sub_bot.reply_to(message, f"📊 الإحصائيات:\n\n👥 المشتركين: {u_count}\n🚫 المحظورين: {b_count}")

    def save_welcome(message):
        set_setting("welcome_msg", message.text)
        sub_bot.reply_to(message, "✅ تم الحفظ.", reply_markup=admin_panel_kb())

    def save_reply_msg(message):
        set_setting("reply_msg", message.text)
        sub_bot.reply_to(message, "✅ تم الحفظ.", reply_markup=admin_panel_kb())

    def process_broadcast(message):
        cur = conn_sub.cursor()
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
        success, failed = 0, 0
        status_msg = sub_bot.reply_to(message, "⏳ جاري الإذاعة...")
        for u in users:
            try:
                sub_bot.copy_message(chat_id=u[0], from_chat_id=message.chat.id, message_id=message.message_id)
                success += 1
            except:
                failed += 1
        sub_bot.edit_message_text(
            f"📢 تمت الإذاعة:\n\n✅ نجاح: {success}\n❌ فشل: {failed}",
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            reply_markup=admin_panel_kb(),
        )

    @sub_bot.message_handler(
        func=lambda m: m.chat.id != admin_id,
        content_types=["text", "photo", "video", "document", "voice", "sticker", "audio"],
    )
    def handle_user_msg(message):
        user_id = message.from_user.id
        cur = conn_sub.cursor()
        cur.execute("SELECT * FROM banned WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            return

        cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn_sub.commit()

        name = message.from_user.first_name
        username = f"@{message.from_user.username}" if message.from_user.username else "بدون"
        show_id = get_setting("show_identity", "ON")

        header = f"📩 رسالة:\n👤 {name}\n🔗 {username}\n🆔 `{user_id}`" if show_id == "ON" else f"📩 رسالة (هوية مخفية):\n🆔 `{user_id}`"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚫 حظر", callback_data=f"ban_{user_id}"))

        sub_bot.send_message(admin_id, header, parse_mode="Markdown", reply_markup=markup)
        sub_bot.copy_message(admin_id, message.chat.id, message.message_id)
        sub_bot.reply_to(message, get_setting("reply_msg", "✅ تم الإرسال."))

    @sub_bot.callback_query_handler(func=lambda call: True)
    def sub_callbacks(call):
        data = call.data
        cur = conn_sub.cursor()
        if data.startswith("ban_"):
            target_id = int(data.split("_")[1])
            cur.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (target_id,))
            conn_sub.commit()
            sub_bot.answer_callback_query(call.id, f"🚫 تم الحظر {target_id}", show_alert=True)
            try:
                sub_bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            except:
                pass
        elif data.startswith("unban_"):
            target_id = int(data.split("_")[1])
            cur.execute("DELETE FROM banned WHERE user_id = ?", (target_id,))
            conn_sub.commit()
            sub_bot.answer_callback_query(call.id, f"✅ تم رفع الحظر {target_id}", show_alert=True)
            try:
                sub_bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
            except:
                pass

def get_or_create_sub_bot(token, admin_id):
    if token in sub_bots_cache:
        return sub_bots_cache[token]
    
    sub_bot = telebot.TeleBot(token)
    conn_sub = sqlite3.connect("bot_maker.db", check_same_thread=False)
    with conn_sub:
        conn_sub.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT, value TEXT)")
        conn_sub.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        conn_sub.execute("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")

    setup_sub_bot_handlers(sub_bot, admin_id, conn_sub)
    sub_bots_cache[token] = sub_bot
    return sub_bot

def restore_all_sub_bots():
    cur = conn_main.cursor()
    cur.execute("SELECT token, admin_id FROM bots")
    for token, admin_id in cur.fetchall():
        try:
            sub_bot = get_or_create_sub_bot(token, admin_id)
            sub_bot.remove_webhook()
            sub_bot.set_webhook(url=f"{RENDER_URL}/webhook/{token}")
        except Exception as e:
            print(f"Error setting webhook for {token}: {e}")

def get_main_keyboard(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ صنع بوت جديد"), KeyboardButton("📋 بوتاتك"))
    if is_admin:
        kb.add(KeyboardButton("📢 إذاعة عامة"))
    return kb

MY_ADMIN_ID = 9050871827

@main_bot.message_handler(commands=["start"])
def main_start(message):
    cur = conn_main.cursor()
    cur.execute("INSERT OR IGNORE INTO main_users (user_id) VALUES (?)", (message.from_user.id,))
    conn_main.commit()
    is_adm = message.from_user.id == MY_ADMIN_ID
    main_bot.send_message(message.chat.id, "أهلاً بك في صانع البوتات 🛠️", reply_markup=get_main_keyboard(is_adm))

@main_bot.message_handler(func=lambda m: m.text in ["➕ صنع بوت جديد", "📋 بوتاتك", "📢 إذاعة عامة"])
def main_menu_handler(message):
    cur = conn_main.cursor()
    if message.text == "➕ صنع بوت جديد":
        msg = main_bot.reply_to(message, "أرسل توكن البوت من @BotFather:")
        main_bot.register_next_step_handler(msg, process_new_token)
    elif message.text == "📋 بوتاتك":
        cur.execute("SELECT bot_username FROM bots WHERE admin_id = ?", (message.from_user.id,))
        bots = cur.fetchall()
        if not bots:
            main_bot.reply_to(message, "⚠️ ليس لديك بوتات.")
        else:
            main_bot.reply_to(message, "📋 بوتاتك:\n\n" + "\n".join([f"🤖 @{b[0]}" for b in bots]))
    elif message.text == "📢 إذاعة عامة":
        if message.from_user.id == MY_ADMIN_ID:
            msg = main_bot.reply_to(message, "📢 أرسل الإذاعة العامة (روابط، أخبار، إعلانات):")
            main_bot.register_next_step_handler(msg, process_main_broadcast)
        else:
            main_bot.reply_to(message, "⚠️ هذا الأمر مخصص للمطور فقط.")

def process_main_broadcast(message):
    cur = conn_main.cursor()
    cur.execute("SELECT user_id FROM main_users")
    users = cur.fetchall()
    success, failed = 0, 0
    status_msg = main_bot.reply_to(message, "⏳ جاري إرسال الإذاعة العامة...")
    for u in users:
        try:
            main_bot.copy_message(chat_id=u[0], from_chat_id=message.chat.id, message_id=message.message_id)
            success += 1
        except:
            failed += 1
    main_bot.edit_message_text(
        f"📢 تمت الإذاعة العامة بنجاح:\n\n✅ نجاح: {success}\n❌ فشل: {failed}",
        chat_id=status_msg.chat.id,
        message_id=status_msg.message_id,
    )

@main_bot.callback_query_handler(func=lambda call: True)
def main_callbacks(call):
    if call.data == "how_token":
        main_bot.answer_callback_query(call.id, "اذهب إلى @BotFather وأرسل /newbot", show_alert=True)
    elif call.data == "what_token":
        main_bot.answer_callback_query(call.id, "التوكن هو الرقم السري للبوت.", show_alert=True)

def process_new_token(message):
    token = message.text.strip()
    admin_id = message.from_user.id
    cur = conn_main.cursor()

    cur.execute("SELECT * FROM bots WHERE token = ?", (token,))
    if cur.fetchone():
        main_bot.reply_to(message, "⚠️ هذا البوت مسجل مسبقاً!")
        return

    msg_wait = main_bot.reply_to(message, "⏳ جاري تفعيل البوت بالويب هوك السريع...")
    try:
        temp_bot = telebot.TeleBot(token)
        bot_username = temp_bot.get_me().username
        cur.execute("INSERT INTO bots (token, admin_id, bot_username) VALUES (?, ?, ?)", (token, admin_id, bot_username))
        conn_main.commit()

        sub_bot = get_or_create_sub_bot(token, admin_id)
        sub_bot.remove_webhook()
        sub_bot.set_webhook(url=f"{RENDER_URL}/webhook/{token}")

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 افتح البوت", url=f"https://t.me/{bot_username}"))
        main_bot.edit_message_text(
            f"🎉 تم تفعيل البوت بنجاح وبدون تعليق!\n\n🤖 @{bot_username}",
            chat_id=msg_wait.chat.id,
            message_id=msg_wait.message_id,
            reply_markup=markup,
        )
    except Exception as e:
        main_bot.edit_message_text(
            f"❌ خطأ في التوكن:\n{e}",
            chat_id=msg_wait.chat.id,
            message_id=msg_wait.message_id,
        )

@app.route('/webhook', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    main_bot.process_new_updates([update])
    return "!", 200

@app.route('/webhook/<token>', methods=['POST'])
def sub_webhook(token):
    cur = conn_main.cursor()
    cur.execute("SELECT admin_id FROM bots WHERE token = ?", (token,))
    res = cur.fetchone()
    if not res:
        return "Bot not found", 404
    
    admin_id = res[0]
    sub_bot = get_or_create_sub_bot(token, admin_id)
    
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    sub_bot.process_new_updates([update])
    return "!", 200

@app.route('/')
def home():
    restore_all_sub_bots()
    return "Bot Maker Server is Live and All Webhooks Active!", 200

restore_all_sub_bots()
main_bot.remove_webhook()
main_bot.set_webhook(url=f"{RENDER_URL}/webhook")

if __name__ == "__main__":
    print("البوت الصانع وبوتات المستخدمين تعمل بنظام الويب هوك الفوري 🚀")
    app.run(host="0.0.0.0", port=PORT)
        
