import os
import sys
sys.path.insert(0, "./libs")

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from database import Database

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPERVISOR_IDS = [int(x) for x in os.environ.get("SUPERVISOR_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

# ── سرور مینیاتوری برای زنده نگه داشتن پورت رندر ───────────────────
class RenderHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("ربات با موفقیت در حال اجراست!".encode("utf-8"))
        
    def log_message(self, format, *args):
        # غیرفعال کردن لاگ‌های اضافی سرور برای خلوت ماندن کنسول
        return

def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), RenderHealthHandler)
        logger.info(f"✅ سرور مینیاتوری هلث‌چک روی پورت {PORT} روشن شد.")
        server.serve_forever()
    except Exception as e:
        logger.error(f"خطا در استارت سرور مینیاتوری: {e}")

# ── منطق اصلی ربات تلگرام ──────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    db.ensure_user(user_id, username)

    # ۱. بررسی وضعیت ناظر کل
    if user_id in SUPERVISOR_IDS:
        db.set_role(user_id, "supervisor")
        await update.message.reply_text("👁️ *ناظر کل* خوش اومدی!\n\nبرای دیدن همه تکالیف از /all_homeworks استفاده کن.\n\n💡 _نکته تست:_ چون شما ناظر هستید، برای تست ارسال تکلیف حتماً باید از یک اکانت تلگرام دیگر (بدون آیدی ناظر) استفاده کنید.", parse_mode="Markdown")
        return

    # ۲. بررسی هوشمند وضعیت کاربر از روی دیتابیس
    role = db.get_role(user_id)
    if role == "support":
        await update.message.reply_text("✅ شما به عنوان *پشتیبان* ثبت شده‌اید!\n\n📥 تکالیف شاگردانتان اینجا ارسال می‌شوند.\nبرای دیدن تکالیف: /my_homeworks", parse_mode="Markdown")
        return
    elif role == "student":
        support_id = db.get_student_support(user_id)
        if support_id:
            support_info = db.get_user(support_id)
            support_name = support_info['username'] if support_info else "پشتیبان شما"
            await update.message.reply_text(f"✏️ خوش آمدید! پشتیبان شما *{support_name}* است.\n\nلطفاً تکلیف خود را (متن، عکس، ویس، فیلم یا فایل) مستقیماً بفرستید تا برای ایشان ارسال شود:", parse_mode="Markdown")
            return

    # ۳. اگر کاربر جدید است و نقشی ندارد
    keyboard = [
        [InlineKeyboardButton("🎓 دانش‌آموز", callback_data="role_student")],
        [InlineKeyboardButton("👨‍🏫 پشتیبان", callback_data="role_support")],
    ]
    await update.message.reply_text(f"سلام {username}! 👋\nلطفاً نقش خودت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))


async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = query.data.split("_")[1]
    db.set_role(user_id, role)

    if role == "support":
        await query.edit_message_text("✅ ثبت شدی به عنوان *پشتیبان*!\n\n📥 تکالیف شاگردات اینجا میان.\nبرای دیدن تکالیف: /my_homeworks", parse_mode="Markdown")
    else:
        supports = db.get_all_supports()
        if not supports:
            await query.edit_message_text("⚠️ هنوز هیچ پشتیبانی در ربات ثبت نام نکرده است.\nکمی بعد دوباره /start بزن.")
            return
        
        keyboard = []
        for s in supports:
            button = InlineKeyboardButton(f"👨‍🏫 {s['username']}", callback_data=f"pick_{s['user_id']}")
            keyboard.append([button])
            
        await query.edit_message_text("پشتیبانت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))


async def pick_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    support = db.get_user(support_id)
    db.set_student_support(user_id, support_id)
    
    await query.edit_message_text(f"✅ پشتیبانت *{support['username']}* انتخاب شد!\n\n📝 از این به بعد هر زمان عکسی، متن یا ویسی بفرستی مستقیم براش ارسال میشه.", parse_mode="Markdown")


async def receive_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    msg = update.message
    
    if not msg:
        return

    role = db.get_role(user_id)
    
    # راهنمای ادمین/پشتیبان مایل به تست ربات
    if role in ["support", "supervisor"] or user_id in SUPERVISOR_IDS:
        await msg.reply_text(f"🤖 *ارتباط زنده است! پیام تست شما با موفقیت دریافت شد.*\nوضعیت شما در دیتابیس: `{role or 'ناظر کل'}`\n\n⚠️ چون شما جزو تیم مدیریت/پشتیبانی هستید، پیام شما به عنوان تکلیف ذخیره نمی‌شود. برای تست چرخه ارسال تکلیف، باید با یک اکانت تلگرام دیگر که نقش *دانش‌آموز* دارد پیام بفرستید.", parse_mode="Markdown")
        return 

    if role != "student":
        await msg.reply_text("⚠️ لطفا ابتدا دستور /start رو بزنید و نقش خودتون رو به عنوان *دانش‌آموز* انتخاب کنید.")
        return

    support_id = db.get_student_support(user_id)
    if not support_id:
        await msg.reply_text("⚠️ اول دستور /start رو بزن و پشتیبانت رو انتخاب کن.")
        return

    hw_id = db.save_homework(student_id=user_id, support_id=support_id, message_id=msg.message_id, chat_id=msg.chat_id, caption=msg.caption or msg.text or "")

    try:
        await context.bot.forward_message(chat_id=support_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        await context.bot.send_message(chat_id=support_id, text=f"📬 تکلیف جدید از *{username}*\n🔢 شماره: `{hw_id}`\nبرای جواب: `/reply {hw_id} [جوابت]`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Forward error: {e}")

    for sv_id in SUPERVISOR_IDS:
        try:
            await context.bot.forward_message(chat_id=sv_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
            support_info = db.get_user(support_id)
            await context.bot.send_message(chat_id=sv_id, text=f"👁️ تکلیف جدید\n👤 {username} | 👨‍🏫 {support_info['username'] if support_info else 'نامشخص'}\n🔢 شماره: `{hw_id}`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Supervisor error: {e}")

    await msg.reply_text("✅ تکلیفت ارسال شد! منتظر جواب پشتیبانت باش.")


async def reply_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_role(user_id)
    
    if role not in ["support", "supervisor"] and user_id not in SUPERVISOR_IDS:
        await update.message.reply_text("❌ فقط پشتیبان‌ها و ناظران کل می‌تونن جواب بدن.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📌 فرمت: `/reply [شماره] [جواب]`", parse_mode="Markdown")
        return
    try:
        hw_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ شماره تکلیف باید عدد باشه.")
        return
        
    reply_text = " ".join(args[1:])
    hw = db.get_homework(hw_id)
    if not hw:
        await update.message.reply_text("❌ تکلیف پیدا نشد.")
        return
        
    if role != "supervisor" and user_id not in SUPERVISOR_IDS:
        if hw["support_id"] != user_id:
            await update.message.reply_text("❌ این تکلیف متعلق به شاگرد شما نیست.")
            return

    db.save_reply(hw_id, reply_text)
    try:
        await context.bot.send_message(chat_id=hw["student_id"], text=f"📩 پاسخ به تکلیف شماره `{hw_id}`:\n\n{reply_text}")
        await update.message.reply_text("✅ جوابت ارسال شد!")
    except Exception as e:
        logger.error(f"Reply error: {e}")
        await update.message.reply_text(f"❌ خطا در ارسال پیام به دانش‌آموز: {e}")


async def my_homeworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_role(user_id) != "support":
        await update.message.reply_text("❌ این دستور فقط برای پشتیبان‌هاست.")
        return
    homeworks = db.get_homeworks_for_support(user_id)
    if not homeworks:
        await update.message.reply_text("📭 هنوز هیچ تکلیفی نداری.")
        return
    text = "📋 *تکالیف دریافتی:*\n\n"
    for hw in homeworks:
        status = "✅ جواب داده" if hw["replied"] else "⏳ منتظر جواب"
        text += f"🔢 `{hw['id']}` | 👤 {hw['student_name']} | {status}\n📝 {hw['caption'][:80] or '(رسانه/فایل)'}\n─────\n"
    text += "\nبرای جواب: `/reply [شماره] [جواب]`"
    await update.message.reply_text(text, parse_mode="Markdown")


async def all_homeworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in SUPERVISOR_IDS:
        await update.message.reply_text("❌ دسترسی ندارید.")
        return
    homeworks = db.get_all_homeworks()
    if not homeworks:
        await update.message.reply_text("📭 هیچ تکلیفی ثبت نشده.")
        return
    text = "👁️ *همه تکالیف:*\n\n"
    for hw in homeworks[:20]:
        status = "✅" if hw["replied"] else "⏳"
        text += f"{status} `{hw['id']}` | 👤 {hw['student_name']} | 👨‍🏫 {hw['support_name']}\n"
    total = db.count_homeworks()
    replied = db.count_replied()
    text += f"\n📊 مجموع: {total} | جواب داده: {replied} | بی‌جواب: {total - replied}"
    await update.message.reply_text(text, parse_mode="Markdown")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده!")
        
    # ۱. راه‌اندازی سرور پس‌زمینه برای تایید سلامت رندر
    threading.Thread(target=start_health_server, daemon=True).start()
    
    # ۲. بیلد کردن ربات تلگرام
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(choose_role, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(pick_support, pattern="^pick_"))
    app.add_handler(CommandHandler("reply", reply_homework))
    app.add_handler(CommandHandler("my_homeworks", my_homeworks))
    app.add_handler(CommandHandler("all_homeworks", all_homeworks))
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, receive_homework))
    
    # ۳. اجرای پولینگ قطعی و پاک کردن وبهوک‌های خراب قدیمی تلگرام
    logger.info("Bot is starting polling mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
