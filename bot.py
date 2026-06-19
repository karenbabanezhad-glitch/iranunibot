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

# تنظیمات لاگ سرور برای دیدن جزییات در رندر
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

# دریافت متغیرهای محیطی از پنل رندر
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPERVISOR_IDS = [int(x) for x in os.environ.get("SUPERVISOR_IDS", "").split(",") if x.strip()]
SUPPORT_IDS = [int(x) for x in os.environ.get("SUPPORT_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

# ── سرور مینیاتوری هلث‌چک رندر (جلوگیری از ریستارت اجباری رندر) ─────────────────
class RenderHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("ربات زنده است!".encode("utf-8"))
    def log_message(self, format, *args): return

def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), RenderHealthHandler)
        logger.info(f"✅ سرور مینیاتوری هلث‌چک روی پورت {PORT} روشن شد.")
        server.serve_forever()
    except Exception as e: 
        logger.error(f"خطا در استارت سرور مینیاتوری: {e}")

# ── ردیاب جهانی خطاها (مچ‌گیری کرش‌های مخفی) ─────────────────────
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"❌ یک خطای داخلی رخ داد! جزئیات: {context.error}")

# ── منطق اصلی دستور استارت ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    # ایمن‌سازی دیتابیس برای جلوگیری از فریز شدن ربات هنگام قفل دیتابیس
    try:
        db.ensure_user(user_id, username)
    except Exception as db_err:
        logger.error(f"⚠️ خطا در ثبت کاربر در دیتابیس: {db_err}")

    # ۱. بررسی خودکار وضعیت ناظر کل از روی پنل رندر
    if user_id in SUPERVISOR_IDS:
        try: db.set_role(user_id, "supervisor")
        except: pass
        await update.message.reply_text(
            "👁️ <b>ناظر کل</b> خوش اومدی!\n\n"
            "برای دیدن همه تکالیف از /all_homeworks استفاده کن.\n\n"
            "💡 <i>نکته تست:</i> چون شما ناظر هستید، برای تست ارسال تکلیف حتماً باید از یک اکانت تلگرام دیگر (بدون آیدی ناظر) استفاده کنید.", 
            parse_mode="HTML"
        )
        return

    # ۲. بررسی خودکار وضعیت پشتیبان از روی پنل رندر
    if user_id in SUPPORT_IDS:
        try: db.set_role(user_id, "support")
        except: pass
        await update.message.reply_text(
            "✅ شما به عنوان <b>پشتیبان سیستم</b> شناسایی شدید!\n\n"
            "📥 تکالیف شاگردانتان اینجا ارسال می‌شوند.\n"
            "برای دیدن تکالیف: /my_homeworks", 
            parse_mode="HTML"
        )
        return

    # ۳. بررسی وضعیت کاربران قدیمی از روی دیتابیس
    role = None
    try: role = db.get_role(user_id)
    except: pass

    if role == "student":
        try:
            support_id = db.get_student_support(user_id)
            if support_id:
                support_info = db.get_user(support_id)
                support_name = support_info['username'] if support_info else f"پشتیبان کد {support_id}"
                await update.message.reply_text(
                    f"✏️ خوش آمدید! پشتیبان شما <b>{support_name}</b> است.\n\n"
                    f"لطفاً تکلیف خود را مستقیماً بفرستید:", 
                    parse_mode="HTML"
                )
                return
        except: pass

    # ۴. انتخاب نقش برای کاربران جدید
    keyboard = [
        [InlineKeyboardButton("🎓 دانش‌آموز", callback_data="role_student")],
        [InlineKeyboardButton("👨‍🏫 پشتیبان رسمی", callback_data="role_support")],
    ]
    await update.message.reply_text(f"سلام {username}! 👋\nلطفاً نقش خودت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))


# ── پردازش دکمه‌های انتخاب نقش ─────────────────────────────────────
async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = query.data.split("_")[1]
    
    try: db.set_role(user_id, role)
    except: pass

    if role == "support":
        await query.edit_message_text("✅ ثبت شدی به عنوان <b>پشتیبان</b>!\nبرای دیدن تکالیف: /my_homeworks", parse_mode="HTML")
    else:
        # دریافت پشتیبان‌های فعال در دیتابیس
        supports = []
        try: supports = db.get_all_supports()
        except: pass
        
        keyboard = []
        for s in supports:
            keyboard.append([InlineKeyboardButton(f"👨‍🏫 {s['username']}", callback_data=f"pick_{s['user_id']}")])
            
        # راهکار هوشمند: اگر دیتابیس ریست شده بود، از لیست SUPPORT_IDS رندر کمک بگیر
        if not keyboard and SUPPORT_IDS:
            for s_id in SUPPORT_IDS:
                keyboard.append([InlineKeyboardButton("👨‍🏫 پشتیبان رسمی سیستم", callback_data=f"pick_{s_id}")])

        if not keyboard:
            await query.edit_message_text("⚠️ هنوز هیچ پشتیبانی در سیستم تعریف نشده است.")
            return
        
        await query.edit_message_text("پشتیبانت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))


# ── پردازش انتخاب پشتیبان توسط دانش‌آموز ───────────────────────────
async def pick_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    
    try:
        db.set_student_support(user_id, support_id)
        support = db.get_user(support_id)
        name = support['username'] if support else "پشتیبان سیستم"
    except:
        name = "پشتیبان سیستم"
        
    await query.edit_message_text(f"✅ پشتیبانت <b>{name}</b> انتخاب شد!\n\n📝 حالا هر تکلیفی بفرستی مستقیم براش ارسال میشه.", parse_mode="HTML")


# ── دریافت، ذخیره و هدایت تکالیف ───────────────────────────────────
async def receive_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    msg = update.message
    if not msg: return

    # اگر مدیر یا پشتیبان به ربات مسیج معمولی بفرستند، فقط پیام زنده بودن می‌گیرند
    if user_id in SUPERVISOR_IDS or user_id in SUPPORT_IDS:
        await msg.reply_text(
            f"🤖 <b>ارتباط زنده است! پیام تست شما دریافت شد.</b>\n\n"
            f"⚠️ چون شما جزو مدیریت/پشتیبانان هستید، پیام به عنوان تکلیف ذخیره نمی‌شود. "
            f"برای تست کامل ارسال تکلیف، باید با یک اکانت تلگرام معمولی (دانش‌آموز) پیام بفرستید.", 
            parse_mode="HTML"
        )
        return 

    try: role = db.get_role(user_id)
    except: role = "student"

    try: support_id = db.get_student_support(user_id)
    except: support_id = SUPPORT_IDS[0] if SUPPORT_IDS else None

    if not support_id:
        await msg.reply_text("⚠️ پشتیبانی یافت نشد. ابتدا /start بزنید.")
        return

    # ذخیره تکلیف در دیتابیس
    try:
        hw_id = db.save_homework(student_id=user_id, support_id=support_id, message_id=msg.message_id, chat_id=msg.chat_id, caption=msg.caption or msg.text or "")
    except:
        hw_id = "تست"

    # ارسال تکلیف برای پشتیبان مربوطه
    try:
        await context.bot.forward_message(chat_id=support_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        await context.bot.send_message(chat_id=support_id, text=f"📬 تکلیف جدید از <b>{username}</b>\n🔢 شماره: <code>{hw_id}</code>\nبرای جواب: <code>/reply {hw_id} [جوابت]</code>", parse_mode="HTML")
    except Exception as e: 
        logger.error(f"Forward error: {e}")

    # ارسال یک نسخه برای ناظرین کل سیستم
    for sv_id in SUPERVISOR_IDS:
        try: await context.bot.forward_message(chat_id=sv_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        except: pass

    await msg.reply_text("✅ تکلیفت ارسال شد!")


# ── هسته مرکزی اجرای ربات ──────────────────────────────────────────
def main():
    if not BOT_TOKEN: 
        raise ValueError("BOT_TOKEN تنظیم نشده!")
        
    # روشن کردن سرور هلث‌چک در یک رشته مجزا
    threading.Thread(target=start_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ثبت دستورات و هندلرهای ربات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(choose_role, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(pick_support, pattern="^pick_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, receive_homework))
    
    # ثبت مچ‌گیر جهانی خطاها
    app.add_error_handler(global_error_handler)
    
    logger.info("Bot is starting polling mode...")
    
    # اجرای ربات با تنظیم عدم تداخل در چرخه‌های متوالی رندر
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
