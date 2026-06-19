import os
import sys
sys.path.insert(0, "./libs")

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

# مراحل جدید گفتگو (دکمه انتخاب نقش کاملاً حذف شد)
GETTING_NAME = 1
CHOOSING_SUPPORT = 2
STUDENT_SENDING_HOMEWORK = 3

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPERVISOR_IDS = [int(x) for x in os.environ.get("SUPERVISOR_IDS", "").split(",") if x.strip()]
SUPPORT_IDS = [int(x) for x in os.environ.get("SUPPORT_IDS", "").split(",") if x.strip()]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 10000))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # ۱. شناسایی خودکار ناظر کل
    if user_id in SUPERVISOR_IDS:
        db.ensure_user(user_id, user.full_name)
        db.set_role(user_id, "supervisor")
        await update.message.reply_text("👁️ *ناظر کل* خوش اومدی!\n\nشما تمام تکالیف ارسالی و پاسخ‌های پشتیبان‌ها را دریافت خواهید کرد.", parse_mode="Markdown")
        return ConversationHandler.END

    # ۲. شناسایی خودکار پشتیبان‌های رسمی (بدون دسترسی عمومی)
    if user_id in SUPPORT_IDS:
        db.ensure_user(user_id, user.full_name)
        db.set_role(user_id, "support")
        await update.message.reply_text("✅ شما به عنوان *پشتیبان رسمی* شناسایی شدید!\n\n📥 تکالیف زبان‌آموزانی که شما را انتخاب کنند برایتان ارسال می‌شود.\nبرای مشاهده لیست تکالیف: /my_homeworks", parse_mode="Markdown")
        return ConversationHandler.END

    # ۳. بخش زبان‌آموز (اگر قبلاً ثبت‌نام کرده، مستقیم برود مرحله ارسال تکلیف)
    support_id = db.get_student_support(user_id)
    if support_id:
        await update.message.reply_text("✏️ خوش آمدید! لطفاً تکلیف جدید خود را ارسال کنید:")
        return STUDENT_SENDING_HOMEWORK

    # درخواست نام و فامیلی در اولین ورود زبان‌آموز
    await update.message.reply_text("سلام! به ربات ارسال تکالیف خوش آمدید. 👋\n\nلطفاً **نام و نام خانوادگی** خود را وارد کنید:")
    return GETTING_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    full_name = update.message.text

    if not full_name or len(full_name.strip()) < 3:
        await update.message.reply_text("❌ لطفاً نام و نام خانوادگی خود را به صورت کامل وارد کنید:")
        return GETTING_NAME

    # ثبت نام واقعی زبان‌آموز در دیتابیس
    db.ensure_user(user_id, full_name.strip())
    db.set_role(user_id, "student")

    supports = db.get_all_supports()
    if not supports:
        await update.message.reply_text("⚠️ هنوز هیچ پشتیبانی در ربات فعال نشده است. (پشتیبان‌ها باید ابتدا حداقل یکبار ربات را /start کنند)")
        return ConversationHandler.END

    # نمایش لیست پشتیبان‌های فعال به زبان‌آموز
    keyboard = [[InlineKeyboardButton(f"👨‍🏫 {s['username']}", callback_data=f"pick_{s['user_id']}")] for s in supports]
    await update.message.reply_text(f"✅ نام شما به عنوان «{full_name.strip()}» ثبت شد.\n\nحالا لطفاً **پشتیبان** خود را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_SUPPORT


async def pick_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_id = int(query.data.split("_")[1])
    user_id = query.from_user.id

    support = db.get_user(support_id)
    db.set_student_support(user_id, support_id)

    await query.edit_message_text(f"🎉 ثبت‌نام شما تکمیل شد!\n👨‍🏫 پشتیبان تخصصی شما: *{support['username']}*\n\n📝 از این به بعد می‌توانید تکالیف خود را (متن، عکس، ویس، فایل یا ویدیو) بفرستید تا مستقیماً به پشتیبانتان برسد.", parse_mode="Markdown")
    return STUDENT_SENDING_HOMEWORK


async def receive_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    
    support_id = db.get_student_support(user_id)
    if not support_id:
        await msg.reply_text("⚠️ لطفا ابتدا دستور /start را بزنید تا ثبت‌نام شما کامل شود.")
        return GETTING_NAME

    user_info = db.get_user(user_id)
    display_name = user_info["username"] if user_info else (update.effective_user.full_name)

    hw_id = db.save_homework(student_id=user_id, support_id=support_id, message_id=msg.message_id, chat_id=msg.chat_id, caption=msg.caption or msg.text or "")

    # ارسال تکلیف فقط برای پشتیبان اختصاصی زبان‌آموز
    try:
        await context.bot.forward_message(chat_id=support_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        await context.bot.send_message(chat_id=support_id, text=f"📬 تکلیف جدید از *{display_name}*\n🔢 شماره تکلیف: `{hw_id}`\nبرای پاسخ: `/reply {hw_id} [متن جواب]`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Forward to support error: {e}")

    # ارسال کپی تکلیف برای ناظر کل جهت بررسی و نظارت
    for sv_id in SUPERVISOR_IDS:
        try:
            await context.bot.forward_message(chat_id=sv_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
            support_info = db.get_user(support_id)
            await context.bot.send_message(chat_id=sv_id, text=f"👁️ *رصد ناظر* | تکلیف جدید بارگذاری شد\n👤 زبان‌آموز: {display_name}\n👨‍🏫 پشتیبان هدف: {support_info['username']}\n🔢 شماره تکلیف: `{hw_id}`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Forward to supervisor error: {e}")

    await msg.reply_text("✅ تکلیف شما با موفقیت ارسال شد! منتظر پاسخ پشتیبان بمانید.")
    return STUDENT_SENDING_HOMEWORK


async def reply_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    support_name = update.effective_user.full_name
    
    if db.get_role(user_id) != "support":
        await update.message.reply_text("❌ این دستور مخصوص پشتیبان‌ها است.")
        return
        
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📌 فرمت صحیح پاسخ: `/reply [شماره تکلیف] [متن پاسخ]`", parse_mode="Markdown")
        return
        
    try:
        hw_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ شماره تکلیف باید عدد باشد.")
        return
        
    reply_text = " ".join(args[1:])
    hw = db.get_homework(hw_id)
    
    if not hw:
        await update.message.reply_text("❌ تکلیفی با این شماره پیدا نشد.")
        return
    if hw["support_id"] != user_id:
        await update.message.reply_text("❌ شما پشتیبان این زبان‌آموز نیستید و نمی‌توانید به این تکلیف پاسخ دهید.")
        return
        
    db.save_reply(hw_id, reply_text)
    
    # ۱. ارسال پاسخ برای زبان‌آموز
    try:
        await context.bot.send_message(chat_id=hw["student_id"], text=f"📩 پشتیبانتان به تکلیف شماره `{hw_id}` پاسخ داد:\n\n{reply_text}", parse_mode="Markdown")
        await update.message.reply_text("✅ پاسخ شما با موفقیت برای زبان‌آموز ارسال شد.")
    except Exception as e:
        logger.error(f"Send reply to student error: {e}")
        
    # ۲. ارسال کپی پاسخ پشتیبان برای ناظر کل (حل مشکل دیده شدن جواب‌ها توسط ناظر)
    student_info = db.get_user(hw["student_id"])
    student_name = student_info["username"] if student_info else "ناشناس"
    for sv_id in SUPERVISOR_IDS:
        try:
            await context.bot.send_message(
                chat_id=sv_id,
                text=f"👁️ *رصد ناظر* | پاسخ پشتیبان ثبت شد\n👨‍🏫 پشتیبان: {support_name}\n👤 به زبان‌آموز: {student_name}\n🔢 شماره تکلیف: `{hw_id}`\n\n💬 *متن پاسخ پشتیبان:*\n{reply_text}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Send reply log to supervisor error: {e}")


async def my_homeworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_role(user_id) != "support":
        await update.message.reply_text("❌ این دستور فقط برای پشتیبان‌هاست.")
        return
    homeworks = db.get_homeworks_for_support(user_id)
    if not homeworks:
        await update.message.reply_text("📭 هنوز هیچ تکلیفی برای شما ارسال نشده است.")
        return
    text = "📋 *تکالیف اختصاصی شما:*\n\n"
    for hw in homeworks:
        status = "✅ جواب داده شده" if hw["replied"] else "⏳ منتظر جواب"
        text += f"🔢 `{hw['id']}` | 👤 {hw['student_name']} | {status}\n📝 {hw['caption'][:80] or '(بدون متن)'}\n─────\n"
    text += "\nبرای پاسخ دادن: `/reply [شماره] [متن]`"
    await update.message.reply_text(text, parse_mode="Markdown")


async def all_homeworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in SUPERVISOR_IDS:
        await update.message.reply_text("❌ شما دسترسی ناظر ندارید.")
        return
    homeworks = db.get_all_homeworks()
    if not homeworks:
        await update.message.reply_text("📭 هیچ تکلیفی در سیستم ثبت نشده است.")
        return
    text = "👁️ *لیست کل تکالیف سیستم (مخصوص ناظر):*\n\n"
    for hw in homeworks[:20]:
        status = "✅" if hw["replied"] else "⏳"
        text += f"{status} `{hw['id']}` | 👤 {hw['student_name']} | 👨‍🏫 {hw['support_name']}\n"
    total = db.count_homeworks()
    replied = db.count_replied()
    text += f"\n📊 آمار کل سیستم:\nمجموع تکالیف: {total}\nپاسخ داده شده: {replied}\nبدون پاسخ: {total - replied}"
    await update.message.reply_text(text, parse_mode="Markdown")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده است!")
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GETTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            CHOOSING_SUPPORT: [CallbackQueryHandler(pick_support, pattern="^pick_")],
            STUDENT_SENDING_HOMEWORK: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.AUDIO | filters.VOICE, receive_homework)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("reply", reply_homework))
    app.add_handler(CommandHandler("my_homeworks", my_homeworks))
    app.add_handler(CommandHandler("all_homeworks", all_homeworks))
    
    logger.info("Bot started successfully...")
    if WEBHOOK_URL:
        webhook_url_clean = WEBHOOK_URL.rstrip('/')
        logger.info(f"Starting webhook on port {PORT} with URL {webhook_url_clean}/webhook")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=f"{webhook_url_clean}/webhook", url_path="webhook")
    else:
        logger.info("Starting polling...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
