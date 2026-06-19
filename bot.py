import os
import sys
sys.path.insert(0, "./libs")

import logging
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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 10000))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    db.ensure_user(user_id, username)

    # ۱. بررسی وضعیت ناظر کل
    if user_id in SUPERVISOR_IDS:
        db.set_role(user_id, "supervisor")
        await update.message.reply_text("👁️ *ناظر کل* خوش اومدی!\n\nبرای دیدن همه تکالیف از /all_homeworks استفاده کن.", parse_mode="Markdown")
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
        keyboard =
