import os
import logging
import sys
import io
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import Conflict

# Try importing PIL with fallback
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL not available - compression will be basic")

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable not set!")
    sys.exit(1)

ADMIN_IDS = []
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

MAX_FILE_SIZE = 20 * 1024 * 1024

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  images_compressed INTEGER DEFAULT 0,
                  total_saved_mb REAL DEFAULT 0,
                  last_used TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (user_id INTEGER PRIMARY KEY,
                  quality INTEGER DEFAULT 85,
                  resize_width INTEGER DEFAULT 0,
                  resize_height INTEGER DEFAULT 0,
                  auto_optimize INTEGER DEFAULT 1)''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# --- Database Functions ---
def get_user_settings(user_id):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("SELECT quality, resize_width, resize_height, auto_optimize FROM user_settings WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'quality': row[0], 'resize_width': row[1], 'resize_height': row[2], 'auto_optimize': bool(row[3])}
    return None

def update_user_settings(user_id, quality=None, resize_width=None, resize_height=None, auto_optimize=None):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_settings (user_id, quality, resize_width, resize_height, auto_optimize) VALUES (?, ?, ?, ?, ?)",
              (user_id, 85, 0, 0, 1))
    
    updates = []
    params = []
    if quality is not None:
        updates.append("quality=?")
        params.append(quality)
    if resize_width is not None:
        updates.append("resize_width=?")
        params.append(resize_width)
    if resize_height is not None:
        updates.append("resize_height=?")
        params.append(resize_height)
    if auto_optimize is not None:
        updates.append("auto_optimize=?")
        params.append(1 if auto_optimize else 0)
    
    if updates:
        params.append(user_id)
        c.execute(f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id=?", params)
    
    conn.commit()
    conn.close()

def update_user_stats(user_id, username, saved_mb):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, images_compressed, total_saved_mb, last_used) VALUES (?, ?, ?, ?, ?)",
              (user_id, username, 0, 0.0, datetime.now().isoformat()))
    c.execute("UPDATE users SET username=?, images_compressed=images_compressed+1, total_saved_mb=total_saved_mb+?, last_used=? WHERE user_id=?",
              (username, saved_mb, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

# --- Compression Function ---
def compress_image(image_data, quality=85, max_width=None, max_height=None):
    if not PIL_AVAILABLE:
        return image_data, (0, 0)
    
    try:
        img = Image.open(io.BytesIO(image_data))
        original_size = img.size
        
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode not in ['RGB', 'L']:
            img = img.convert('RGB')
        
        if max_width or max_height:
            original_width, original_height = img.size
            ratio = min(
                (max_width / original_width) if max_width else 1,
                (max_height / original_height) if max_height else 1
            )
            if ratio < 1:
                new_size = (int(original_width * ratio), int(original_height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        compressed_data = output.getvalue()
        output.close()
        return compressed_data, img.size
    except Exception as e:
        logger.error(f"Compression error: {e}")
        return None, None

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"🖼️ **Image Compressor Bot**\n\n"
        f"Hi {user.first_name}! Send me an image to compress!\n\n"
        f"**Commands:**\n"
        f"/quality <1-100> - Set quality\n"
        f"/resize <width> <height> - Set dimensions\n"
        f"/settings - View settings\n"
        f"/reset - Reset to defaults\n"
        f"/help - Show help"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🖼️ **Help**\n\n"
        "/quality <1-100> - Set quality\n"
        "/resize <w> <h> - Set dimensions\n"
        "/settings - View settings\n"
        "/reset - Reset defaults\n"
        "Send an image to compress!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /quality <1-100>")
        return
    quality = int(args[0])
    if quality < 1 or quality > 100:
        await update.message.reply_text("Quality must be between 1 and 100!")
        return
    update_user_settings(user_id, quality=quality)
    await update.message.reply_text(f"✅ Quality set to {quality}%")

async def resize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("Usage: /resize <width> <height>")
        return
    width, height = int(args[0]), int(args[1])
    if width < 0 or height < 0:
        await update.message.reply_text("Width and height must be positive!")
        return
    update_user_settings(user_id, resize_width=width, resize_height=height)
    await update.message.reply_text(f"✅ Resize set to {width}x{height}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    if not settings:
        update_user_settings(user_id)
        settings = get_user_settings(user_id)
    
    size_text = f"{settings['resize_width']}x{settings['resize_height']}" if settings['resize_width'] > 0 else "Disabled"
    await update.message.reply_text(
        f"⚙️ **Settings**\n\n"
        f"Quality: {settings['quality']}%\n"
        f"Resize: {size_text}",
        parse_mode='Markdown'
    )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_settings(user_id, quality=85, resize_width=0, resize_height=0)
    await update.message.reply_text("✅ Settings reset to default!")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if update.message.photo:
        photo = update.message.photo[-1]
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
        photo = update.message.document
    else:
        await update.message.reply_text("❌ Please send an image!")
        return
    
    if photo.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ Image too large! Max 20MB.")
        return
    
    processing_msg = await update.message.reply_text("⏳ Compressing...")
    
    try:
        file = await context.bot.get_file(photo.file_id)
        image_data = await file.download_as_bytearray()
        
        settings = get_user_settings(user_id) or {'quality': 85, 'resize_width': 0, 'resize_height': 0}
        quality = settings['quality']
        resize_width = settings['resize_width'] if settings['resize_width'] > 0 else None
        resize_height = settings['resize_height'] if settings['resize_height'] > 0 else None
        
        compressed_data, original_size = compress_image(image_data, quality, resize_width, resize_height)
        
        if compressed_data is None:
            await processing_msg.edit_text("❌ Compression failed. Please try again.")
            return
        
        original_mb = len(image_data) / (1024 * 1024)
        compressed_mb = len(compressed_data) / (1024 * 1024)
        saved_mb = original_mb - compressed_mb
        ratio = (1 - (len(compressed_data) / len(image_data))) * 100
        
        update_user_stats(user_id, username, saved_mb)
        
        compressed_file = io.BytesIO(compressed_data)
        compressed_file.name = 'compressed.jpg'
        
        await update.message.reply_document(
            document=compressed_file,
            caption=(
                f"✅ **Done!**\n\n"
                f"Original: {original_mb:.2f}MB\n"
                f"Compressed: {compressed_mb:.2f}MB\n"
                f"Saved: {saved_mb:.2f}MB ({ratio:.1f}%)"
            ),
            parse_mode='Markdown'
        )
        await processing_msg.delete()
    except Exception as e:
        logger.error(f"Error: {e}")
        await processing_msg.edit_text("❌ Error processing image.")

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# --- Main ---
def main():
    logger.info("🖼️ Starting Image Compressor Bot...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("resize", resize_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_image))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is ready!")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
