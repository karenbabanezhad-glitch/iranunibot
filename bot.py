import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
from database import Database

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

CHOOSING_ROLE = 1
STUDENT_CHOOSING_SUPPORT = 2
STUDENT_SENDING_HOMEWORK = 3

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPERVISOR_IDS = [int(x) for x in os.environ.get("SUPERVISOR_IDS", "").split(",") if x.strip()]
# تنظیم آدرس رندر اختصاصی شما به عنوان وب‌هوک پیش‌فرض
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://iranunibot.onrender.com")
PORT = int(os.environ.get("PORT", 10000))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    db.ensure_user(user_id, username)

    if user_id in SUPERVISOR_IDS:
        db.set_role(user_id, "supervisor")
        await update.message.reply_text("👁️ *ناظر کل* خوش اومدی!\n\nبرای دیدن همه تکالیف از /all_homeworks استفاده کن.", parse_mode="Markdown")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🎓 دانش‌آموز", callback_data="role_student")],
        [InlineKeyboardButton("👨‍🏫 پشتیبان", callback_data="role_support")],
    ]
    await update.message.reply_text(f"سلام {username}! 👋\nلطفاً نقش خودت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_ROLE


async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = query.data.split("_")[1]
    db.set_role(user_id, role)

    if role == "support":
        await query.edit_message_text("✅ ثبت شدی به عنوان *پشتیبان*!\n\n📥 تکالیف شاگردات اینجا میان.\nبرای دیدن تکالیف: /my_homeworks", parse_mode="Markdown")
        return ConversationHandler.END
    else:
        supports = db.get_all_supports()
        if not supports:
            await query.edit_message_text("⚠️ هنوز هیچ پشتیبانی ثبت نشده.\nکمی بعد دوباره /start بزن.")
            return ConversationHandler.END
        keyboard = [[InlineKeyboardButton(f"👨‍🏫 {s['username']}", callback_data=f"pick_{s['user_id']}")] for s in supports]
        await query.edit_message_text("پشتیبانت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))
        return STUDENT_CHOOSING_SUPPORT


async def pick_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    support = db.get_user(support_id)
    db.set_student_support(user_id, support_id)
    context.user_data["support_id"] = support_id
    await query.edit_message_text(f"✅ پشتیبانت *{support['username']}* انتخاب شد!\n\n📝 حالا تکلیفت رو بفرست:", parse_mode="Markdown")
    return STUDENT_SENDING_HOMEWORK


async def receive_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    msg = update.message
    support_id = context.user_data.get("support_id") or db.get_student_support(user_id)
    if not support_id:
        await msg.reply_text("⚠️ اول /start بزن و پشتیبانت رو انتخاب کن.")
        return STUDENT_SENDING_HOMEWORK

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
            await context.bot.send_message(chat_id=sv_id, text=f"👁️ تکلیف جدید\n👤 {username} | 👨‍🏫 {support_info['username']}\n🔢 شماره: `{hw_id}`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Supervisor error: {e}")

    await msg.reply_text("✅ تکلیفت ارسال شد! منتظر جواب پشتیبانت باش.")
    return STUDENT_SENDING_HOMEWORK


async def reply_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_role(user_id) != "support":
        await update.message.reply_text("❌ فقط پشتیبان‌ها می‌تونن جواب بدن.")
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
    if hw["support_id"] != user_id:
        await update.message.reply_text("❌ این تکلیف متعلق به شاگرد شما نیست.")
        return
    db.save_reply(hw_id, reply_text)
    try:
        await context.bot.send_message(chat_id=hw["student_id"], text=f"📩 پشتیبانت جواب داد:\n\n{reply_text}")
        await update.message.reply_text("✅ جوابت ارسال شد!")
    except Exception as e:
        logger.error(f"Reply error: {e}")


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
        text += f"🔢 `{hw['id']}` | 👤 {hw['student_name']} | {status}\n📝 {hw['caption'][:80] or '(فایل)'}\n─────\n"
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
    app = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_ROLE: [CallbackQueryHandler(choose_role, pattern="^role_")],
            STUDENT_CHOOSING_SUPPORT: [CallbackQueryHandler(pick_support, pattern="^pick_")],
            STUDENT_SENDING_HOMEWORK: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.AUDIO | filters.VOICE, receive_homework)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("reply", reply_homework))
    app.add_handler(CommandHandler("my_homeworks", my_homeworks))
    app.add_handler(CommandHandler("all_homeworks", all_homeworks))
    logger.info("Bot started...")
    if WEBHOOK_URL:
        webhook_url_clean = WEBHOOK_URL.rstrip('/')
        logger.info(f"Starting webhook on port {PORT} with URL {webhook_url_clean}/webhook")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=f"{webhook_url_clean}/webhook", url_path="webhook")
    else:
        logger.info("Starting polling...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
