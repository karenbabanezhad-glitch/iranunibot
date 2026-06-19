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
SUPPORT_IDS = [int(x) for x in os.environ.get("SUPPORT_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

# ── سرور مینیاتوری هلث‌چک رندر ─────────────────────────────────
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
    except Exception as e: logger.error(f"خطا در استارت سرور مینیاتوری: {e}")

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"❌ یک خطای داخلی رخ داد! جزئیات: {context.error}")

# ── سیستم پاسخگویی پیشرفته پشتیبان (پشتیبانی کامل از عکس و رسانه) ─────────────────
async def reply_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    if not msg: return
    
    # بررسی دسترسی
    if user_id not in SUPPORT_IDS and user_id not in SUPERVISOR_IDS:
        await msg.reply_text("⛔ شما دسترسی ارسال پاسخ را ندارید.")
        return

    # استخراج متن چه از پیام متنی معمولی و چه از کپشنِ عکس/رسانه
    full_text = msg.text or msg.caption or ""
    parts = full_text.split()

    if len(parts) < 2:
        await msg.reply_text(
            "❌ <b>روش استفاده اشتباه است!</b>\n\n"
            "طرز استفاده متنی: <code>/reply [شماره] [متن]</code>\n"
            "طرز استفاده با عکس: دستور <code>/reply [شماره] [متن]</code> را روی عکس خود کپشن (Caption) کنید.", 
            parse_mode="HTML"
        )
        return

    try:
        hw_id = int(parts[1])
        reply_text = " ".join(parts[2:])
    except ValueError:
        await msg.reply_text("❌ شماره تکلیف باید یک عدد باشد!")
        return

    # پیدا کردن اطلاعات تکلیف
    hw = db.get_homework(hw_id)
    if not hw:
        await msg.reply_text("❌ تکلیفی با این شماره در سیستم پیدا نشد!")
        return

    student_id = hw['student_id']
    sender_name = msg.from_user.username or msg.from_user.first_name
    
    # قالب پیام خروجی برای شاگرد
    caption_text = f"📩 <b>پاسخ پشتیبان به تکلیف شماره {hw_id}:</b>\n\n{reply_text}"

    try:
        # تشخیص نوع رسانه و ارسال هوشمند آن به شاگرد
        if msg.photo:
            await context.bot.send_photo(chat_id=student_id, photo=msg.photo[-1].file_id, caption=caption_text, parse_mode="HTML")
        elif msg.voice:
            await context.bot.send_voice(chat_id=student_id, voice=msg.voice.file_id, caption=caption_text, parse_mode="HTML")
        elif msg.document:
            await context.bot.send_document(chat_id=student_id, document=msg.document.file_id, caption=caption_text, parse_mode="HTML")
        elif msg.video:
            await context.bot.send_video(chat_id=student_id, video=msg.video.file_id, caption=caption_text, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=student_id, text=caption_text, parse_mode="HTML")

        # ذخیره وضعیت در دیتابیس
        db.save_reply(hw_id, reply_text if reply_text else "[ارسال رسانه]")
        await msg.reply_text("✅ پاسخ شما با موفقیت برای شاگرد ارسال شد.")
    except Exception as e:
        await msg.reply_text(f"❌ خطا در ارسال پیام به شاگرد! احتمالاً ربات را بلاک کرده است. جزئیات: {e}")
        return

    # ۳. ارسال هم‌زمان رونوشت پاسخ (همراه رسانه) برای ناظرین کل سیستم
    for sv_id in SUPERVISOR_IDS:
        if sv_id != user_id:  # اگر خود ناظر جواب نداده بود
            try:
                if msg.photo:
                    await context.bot.send_photo(chat_id=sv_id, photo=msg.photo[-1].file_id, caption=f"📣 <b>گزارش پاسخ (عکس) از {sender_name}:</b>\n\n{caption_text}", parse_mode="HTML")
                elif msg.voice:
                    await context.bot.send_voice(chat_id=sv_id, voice=msg.voice.file_id, caption=f"📣 <b>گزارش پاسخ (ویس) از {sender_name}:</b>\n\n{caption_text}", parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=sv_id, text=f"📣 <b>گزارش پاسخ از {sender_name}:</b>\n\n{caption_text}", parse_mode="HTML")
            except:
                pass


# ── منطق اصلی دستور استارت ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    try: db.ensure_user(user_id, username)
    except Exception as db_err: logger.error(f"⚠️ خطا در دیتابیس: {db_err}")

    if user_id in SUPERVISOR_IDS:
        try: db.set_role(user_id, "supervisor")
        except: pass
        
        keyboard = [[InlineKeyboardButton("📊 لیست پشتیبان‌ها و شاگردان", callback_data="sv_view_supports")]]
        await update.message.reply_text(
            "👁️ <b>ناظر کل</b> خوش اومدی!\n\n"
            "از دکمه زیر می‌تونی وضعیت کل پشتیبان‌ها و شاگردان رو مدیریت کنی:", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    if user_id in SUPPORT_IDS:
        try: db.set_role(user_id, "support")
        except: pass
        
        keyboard = [[InlineKeyboardButton("📋 لیست شاگردان من", callback_data=f"support_students:{user_id}")]]
        await update.message.reply_text(
            f"سلام <b>{username}</b> عزیز! به تیم پشتیبانی خوش آمدید 👨‍🏫✨\n\n"
            f"✅ حساب شما فعال است. برای مدیریت شاگردانتان از دکمه زیر استفاده کنید:", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

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

    keyboard = [
        [InlineKeyboardButton("🎓 دانش‌آموز", callback_data="role_student")],
        [InlineKeyboardButton("👨‍🏫 پشتیبان رسمی", callback_data="role_support")],
    ]
    await update.message.reply_text(f"سلام {username}! 👋\nلطفاً نقش خودت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))


# ── پردازش دکمه‌های منو و ناوبری هوشمند ─────────────────────────────────────
async def handle_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "sv_view_supports":
        supports = []
        try: supports = db.get_all_supports()
        except: pass
        
        keyboard = []
        for s in supports:
            keyboard.append([InlineKeyboardButton(f"👨‍🏫 پشتیبان: {s['username']}", callback_data=f"sv_show_subs:{s['user_id']}")])
        
        if not keyboard:
            await query.edit_message_text("⚠️ هیچ پشتیبان فعالی در دیتابیس ثبت نشده است.")
            return
            
        await query.edit_message_text("📊 لیست پشتیبان‌های سیستم:\nیکی را برای مشاهده شاگردانش انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("sv_show_subs:"):
        support_id = int(data.split(":")[1])
        students = []
        try: students = db.get_support_students(support_id)
        except: pass
        
        keyboard = []
        for st in students:
            keyboard.append([InlineKeyboardButton(f"🎓 شاگرد: {st['username']}", callback_data=f"view_hw:{st['user_id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به لیست پشتیبان‌ها", callback_data="sv_view_supports")])
        await query.edit_message_text(f"👥 لیست شاگردان این پشتیبان:\nبرای دیدن تکالیف هر کدام، روی اسمش کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("support_students:"):
        support_id = int(data.split(":")[1])
        students = []
        try: students = db.get_support_students(support_id)
        except: pass
        
        keyboard = []
        for st in students:
            keyboard.append([InlineKeyboardButton(f"🎓 شاگرد: {st['username']}", callback_data=f"view_hw:{st['user_id']}")])
            
        if not keyboard:
            await query.edit_message_text("🤷‍♂️ شما هنوز هیچ شاگردی در سیستم ندارید (کسی شما را انتخاب نکرده است).")
            return
            
        await query.edit_message_text("📋 شاگردان شما:\nبرای دیدن و فوروارد مجدد تکالیف روی اسم شاگرد کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("view_hw:"):
        student_id = int(data.split(":")[1])
        homeworks = []
        try: homeworks = db.get_student_homeworks(student_id)
        except: pass
        
        if not homeworks:
            await context.bot.send_message(chat_id=query.from_user.id, text="ℹ️ این شاگرد هنوز هیچ تکلیفی ارسال نکرده است.")
            return
            
        await context.bot.send_message(chat_id=query.from_user.id, text=f"📥 در حال بازیابی تکالیف شاگرد ({len(homeworks)} تکلیف)...")
        
        for hw in homeworks:
            try:
                await context.bot.forward_message(
                    chat_id=query.from_user.id,
                    from_chat_id=hw['chat_id'],
                    message_id=hw['message_id']
                )
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"🔢 شناسه تکلیف: <code>{hw['id']}</code>\n📝 توضیحات: {hw['caption']}\n\nپاسخ با: <code>/reply {hw['id']} [متن]</code>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"خطا در بازنشانی تکلیف: {e}")


async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = query.data.split("_")[1]
    
    try: db.set_role(user_id, role)
    except: pass

    if role == "support":
        await query.edit_message_text("✅ ثبت شدی به عنوان <b>پشتیبان</b>!\nربات را مجدد /start کنید.", parse_mode="HTML")
    else:
        supports = []
        try: supports = db.get_all_supports()
        except: pass
        
        keyboard = []
        for s in supports:
            keyboard.append([InlineKeyboardButton(f"👨‍🏫 {s['username']}", callback_data=f"pick_{s['user_id']}")])
            
        if not keyboard and SUPPORT_IDS:
            for s_id in SUPPORT_IDS:
                keyboard.append([InlineKeyboardButton("👨‍🏫 پشتیبان رسمی سیستم", callback_data=f"pick_{s_id}")])

        if not keyboard:
            await query.edit_message_text("⚠️ هنوز هیچ پشتیبانی در سیستم تعریف نشده است.")
            return
        
        await query.edit_message_text("پشتیبانت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def pick_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    
    try:
        db.set_student_support(user_id, support_id)
        support = db.get_user(support_id)
        name = support['username'] if support else "پشتیبان سیستم"
    except: name = "پشتیبان سیستم"
        
    await query.edit_message_text(f"✅ پشتیبانت <b>{name}</b> انتخاب شد!\n\n📝 حالا هر تکلیفی بفرستی مستقیم براش ارسال میشه.", parse_mode="HTML")

async def receive_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    msg = update.message
    if not msg: return

    if user_id in SUPERVISOR_IDS or user_id in SUPPORT_IDS:
        await msg.reply_text(
            f"🤖 <b>راهنمای سیستم پیام‌رسانی:</b>\n\n"
            f"پیام شما به عنوان تکلیف ذخیره نشد. برای پاسخ دادن به تکالیف شاگردان، باید دستور ریپلای را بنویسید (یا روی عکس کپشن کنید):\n"
            f"<code>/reply [شماره تکلیف] [متن پاسخ]</code>", 
            parse_mode="HTML"
        )
        return 

    try: support_id = db.get_student_support(user_id)
    except: support_id = SUPPORT_IDS[0] if SUPPORT_IDS else None

    if not support_id:
        await msg.reply_text("⚠️ پشتیبانی یافت نشد. ابتدا /start بزنید.")
        return

    try: hw_id = db.save_homework(student_id=user_id, support_id=support_id, message_id=msg.message_id, chat_id=msg.chat_id, caption=msg.caption or msg.text or "")
    except: hw_id = "تست"

    try:
        await context.bot.forward_message(chat_id=support_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        await context.bot.send_message(chat_id=support_id, text=f"📬 تکلیف جدید از <b>{username}</b>\n🔢 شماره: <code>{hw_id}</code>\nبرای جواب: <code>/reply {hw_id} [جوابت]</code>", parse_mode="HTML")
    except Exception as e: logger.error(f"Forward error: {e}")

    for sv_id in SUPERVISOR_IDS:
        try: await context.bot.forward_message(chat_id=sv_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        except: pass

    await msg.reply_text("✅ تکلیفت ارسال شد!")

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN تنظیم نشده!")
    threading.Thread(target=start_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply_homework))
    app.add_handler(CallbackQueryHandler(handle_menus, pattern="^(sv_|support_students:|view_hw:)"))
    app.add_handler(CallbackQueryHandler(choose_role, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(pick_support, pattern="^pick_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, receive_homework))
    app.add_error_handler(global_error_handler)
    
    logger.info("Bot is starting polling mode...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
