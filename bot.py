import os
import logging
import sys
import io
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import Conflict

# Try importing PIL, handle if not available
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL not available, image compression will be limited")

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
    c.execute('''CREATE TABLE IF NOT EXISTS compressed_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  original_size REAL,
                  compressed_size REAL,
                  saved_percent REAL,
                  timestamp TIMESTAMP)''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# --- Database Helper Functions ---
def get_user_stats(user_id):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, images_compressed, total_saved_mb FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'images_compressed': row[2],
            'total_saved_mb': row[3]
        }
    return None

def update_user_stats(user_id, username, saved_mb):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, images_compressed, total_saved_mb, last_used) VALUES (?, ?, ?, ?, ?)",
              (user_id, username, 0, 0.0, datetime.now().isoformat()))
    c.execute("UPDATE users SET username=?, images_compressed=images_compressed+1, total_saved_mb=total_saved_mb+?, last_used=? WHERE user_id=?",
              (username, saved_mb, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def get_user_settings(user_id):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, quality, resize_width, resize_height, auto_optimize FROM user_settings WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'quality': row[1],
            'resize_width': row[2],
            'resize_height': row[3],
            'auto_optimize': bool(row[4])
        }
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

def save_compression_history(user_id, original_size, compressed_size, saved_percent):
    conn = sqlite3.connect('shrinkimage_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO compressed_history (user_id, original_size, compressed_size, saved_percent, timestamp) VALUES (?, ?, ?, ?, ?)",
              (user_id, original_size, compressed_size, saved_percent, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# --- Image Compression Functions ---
def compress_image(image_data, quality=85, max_width=None, max_height=None):
    """Compress image with given quality and dimensions."""
    if not PIL_AVAILABLE:
        return image_data, (0, 0)
    
    try:
        img = Image.open(io.BytesIO(image_data))
        original_size = img.size
        
        # Convert RGBA to RGB
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode not in ['RGB', 'L']:
            img = img.convert('RGB')
        
        # Resize if needed
        if max_width or max_height:
            original_width, original_height = img.size
            ratio = min(
                (max_width / original_width) if max_width else 1,
                (max_height / original_height) if max_height else 1
            )
            if ratio < 1:
                new_size = (int(original_width * ratio), int(original_height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Compress
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        compressed_data = output.getvalue()
        output.close()
        
        return compressed_data, img.size
        
    except Exception as e:
        logger.error(f"Compression error: {e}")
        return None, None

def get_optimal_quality(image_data, target_size_mb=0.5):
    """Find optimal quality for target file size."""
    if not PIL_AVAILABLE:
        return 85
    
    target_bytes = target_size_mb * 1024 * 1024
    
    if len(image_data) <= target_bytes:
        return 95
    
    min_quality = 10
    max_quality = 95
    best_quality = 70
    
    for _ in range(8):
        mid_quality = (min_quality + max_quality) // 2
        compressed, _ = compress_image(image_data, quality=mid_quality)
        
        if compressed is None:
            break
            
        if len(compressed) <= target_bytes:
            best_quality = mid_quality
            min_quality = mid_quality + 1
        else:
            max_quality = mid_quality - 1
    
    return best_quality

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    stats = get_user_stats(user_id)
    if not stats:
        update_user_stats(user_id, username, 0)
    
    welcome_text = (
        f"🖼️ **Image Compressor Bot**\n\n"
        f"Hi {user.first_name}! I compress images to save space.\n\n"
        f"**Features:**\n"
        f"• Compress images up to 20MB\n"
        f"• Custom quality settings\n"
        f"• Resize images\n"
        f"• Auto-optimization\n\n"
        f"**Commands:**\n"
        f"/compress - Open options menu\n"
        f"/quality <1-100> - Set compression quality\n"
        f"/resize <width> <height> - Set dimensions\n"
        f"/auto on/off - Toggle auto-optimization\n"
        f"/settings - View your settings\n"
        f"/stats - View your statistics\n"
        f"/reset - Reset to defaults\n"
        f"/help - Show this message\n\n"
        f"**Quick Start:**\n"
        f"Just send me an image!"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🖼️ **Image Compressor Help**\n\n"
        "**Commands:**\n"
        "/quality <1-100> - Set quality (default: 85)\n"
        "/resize <width> <height> - Set dimensions\n"
        "/auto on/off - Toggle auto-optimization\n"
        "/settings - View settings\n"
        "/stats - View statistics\n"
        "/reset - Reset to defaults\n"
        "/compress - Open options menu\n\n"
        "**Tips:**\n"
        "• Lower quality = smaller file\n"
        "• Higher quality = better image\n"
        "• Auto-optimization finds best quality\n\n"
        "**Examples:**\n"
        "/quality 70\n"
        "/resize 800 600"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "❌ Please provide quality!\n"
            "Usage: /quality <1-100>\n"
            "Example: /quality 85"
        )
        return
    
    quality = int(args[0])
    if quality < 1 or quality > 100:
        await update.message.reply_text("❌ Quality must be between 1 and 100!")
        return
    
    update_user_settings(user_id, quality=quality)
    await update.message.reply_text(f"✅ Quality set to {quality}%")

async def resize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text(
            "❌ Please provide width and height!\n"
            "Usage: /resize <width> <height>\n"
            "Example: /resize 800 600\n"
            "Use /resize 0 0 to disable resizing"
        )
        return
    
    width = int(args[0])
    height = int(args[1])
    
    if width < 0 or height < 0:
        await update.message.reply_text("❌ Width and height must be positive numbers!")
        return
    
    update_user_settings(user_id, resize_width=width, resize_height=height)
    
    if width == 0 and height == 0:
        await update.message.reply_text("✅ Resizing disabled!")
    else:
        await update.message.reply_text(f"✅ Resize set to {width}x{height}")

async def auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args or args[0].lower() not in ['on', 'off']:
        await update.message.reply_text(
            "❌ Please specify on or off!\n"
            "Usage: /auto on\n"
            "   or  /auto off"
        )
        return
    
    status = args[0].lower() == 'on'
    update_user_settings(user_id, auto_optimize=status)
    await update.message.reply_text(f"✅ Auto-optimization {'enabled' if status else 'disabled'}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    settings = get_user_settings(user_id)
    if not settings:
        update_user_settings(user_id)
        settings = get_user_settings(user_id)
    
    size_text = f"{settings['resize_width']}x{settings['resize_height']}" if settings['resize_width'] > 0 and settings['resize_height'] > 0 else "Disabled"
    
    settings_text = (
        f"⚙️ **Your Settings**\n\n"
        f"• Quality: {settings['quality']}%\n"
        f"• Resize: {size_text}\n"
        f"• Auto-Optimization: {'✅ Enabled' if settings['auto_optimize'] else '❌ Disabled'}\n\n"
        f"Send an image to compress!"
    )
    
    await update.message.reply_text(settings_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    stats = get_user_stats(user_id)
    if not stats:
        await update.message.reply_text("❌ No stats found! Compress some images first.")
        return
    
    stats_text = (
        f"📊 **Your Statistics**\n\n"
        f"Username: {username}\n"
        f"Images Compressed: {stats['images_compressed']}\n"
        f"Total Space Saved: {stats['total_saved_mb']:.1f} MB\n\n"
        f"Keep compressing to save more space!"
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_settings(user_id, quality=85, resize_width=0, resize_height=0, auto_optimize=True)
    await update.message.reply_text("✅ Settings reset to default!")

async def compress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📱 Low (50%)", callback_data="quality_50"),
            InlineKeyboardButton("📱 Medium (70%)", callback_data="quality_70"),
            InlineKeyboardButton("📱 High (85%)", callback_data="quality_85"),
        ],
        [
            InlineKeyboardButton("📏 800x600", callback_data="resize_800_600"),
            InlineKeyboardButton("📏 1024x768", callback_data="resize_1024_768"),
            InlineKeyboardButton("📏 1920x1080", callback_data="resize_1920_1080"),
        ],
        [
            InlineKeyboardButton("🔄 Disable Resize", callback_data="resize_0_0"),
            InlineKeyboardButton("🤖 Auto-Optimize", callback_data="auto_toggle"),
        ],
        [
            InlineKeyboardButton("🔄 Reset All", callback_data="reset_all"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🖼️ **Compression Options**\n\n"
        "Choose an option below, then send me an image!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# --- Callback Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith("quality_"):
        quality = int(data.split("_")[1])
        update_user_settings(user_id, quality=quality)
        await query.edit_message_text(
            f"✅ Quality set to {quality}%\n\nNow send me an image!",
            parse_mode='Markdown'
        )
    
    elif data.startswith("resize_"):
        parts = data.split("_")
        width = int(parts[1])
        height = int(parts[2])
        update_user_settings(user_id, resize_width=width, resize_height=height)
        
        if width == 0 and height == 0:
            await query.edit_message_text(
                f"✅ Resizing disabled!\n\nNow send me an image!",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"✅ Resize set to {width}x{height}\n\nNow send me an image!",
                parse_mode='Markdown'
            )
    
    elif data == "auto_toggle":
        settings = get_user_settings(user_id)
        new_status = not settings['auto_optimize'] if settings else True
        update_user_settings(user_id, auto_optimize=new_status)
        await query.edit_message_text(
            f"✅ Auto-optimization {'enabled' if new_status else 'disabled'}\n\nNow send me an image!",
            parse_mode='Markdown'
        )
    
    elif data == "reset_all":
        update_user_settings(user_id, quality=85, resize_width=0, resize_height=0, auto_optimize=True)
        await query.edit_message_text(
            f"✅ All settings reset to default!\n\nNow send me an image!",
            parse_mode='Markdown'
        )

# --- Image Handler ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Please send an image!")
        return
    
    if update.message.photo:
        photo = update.message.photo[-1]
        file_size = photo.file_size
    else:
        document = update.message.document
        mime_type = document.mime_type or ""
        if not mime_type.startswith('image/'):
            await update.message.reply_text("❌ Please send an image file!")
            return
        photo = document
        file_size = document.file_size
    
    if file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ Image too large! Max 20MB.\n"
            f"Size: {file_size / (1024*1024):.1f}MB"
        )
        return
    
    processing_msg = await update.message.reply_text("⏳ Compressing image...")
    
    try:
        file = await context.bot.get_file(photo.file_id)
        image_data = await file.download_as_bytearray()
        
        settings = get_user_settings(user_id)
        if not settings:
            update_user_settings(user_id)
            settings = get_user_settings(user_id)
        
        quality = settings['quality']
        resize_width = settings['resize_width'] if settings['resize_width'] > 0 else None
        resize_height = settings['resize_height'] if settings['resize_height'] > 0 else None
        
        if settings['auto_optimize'] and len(image_data) > 2 * 1024 * 1024:
            quality = get_optimal_quality(image_data, 0.5)
        
        compressed_data, original_size = compress_image(
            image_data,
            quality=quality,
            max_width=resize_width,
            max_height=resize_height
        )
        
        if compressed_data is None:
            await processing_msg.edit_text("❌ Failed to compress image. Please try again.")
            return
        
        original_mb = len(image_data) / (1024 * 1024)
        compressed_mb = len(compressed_data) / (1024 * 1024)
        saved_mb = original_mb - compressed_mb
        ratio = (1 - (len(compressed_data) / len(image_data))) * 100
        
        update_user_stats(user_id, username, saved_mb)
        save_compression_history(user_id, original_mb, compressed_mb, ratio)
        
        compressed_file = io.BytesIO(compressed_data)
        compressed_file.name = 'compressed_image.jpg'
        
        await update.message.reply_document(
            document=compressed_file,
            caption=(
                f"✅ **Compressed Successfully!**\n\n"
                f"📊 **Statistics:**\n"
                f"• Original: {original_mb:.2f}MB\n"
                f"• Compressed: {compressed_mb:.2f}MB\n"
                f"• Saved: {saved_mb:.2f}MB ({ratio:.1f}%)\n"
                f"• Quality: {quality}%\n"
                f"• Dimensions: {original_size[0]}x{original_size[1]}\n\n"
                f"📈 Total Saved: {saved_mb:.2f}MB this image"
            ),
            parse_mode='Markdown'
        )
        
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await processing_msg.edit_text("❌ Error processing image. Please try again.")

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    
    if isinstance(context.error, Conflict):
        logger.warning("Conflict error - another instance running")
    elif update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text("❌ An error occurred. Please try again.")
        except:
            pass

# --- Main Function ---
def main():
    logger.info("🖼️ Starting Image Compressor Bot...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("resize", resize_command))
    application.add_handler(CommandHandler("auto", auto_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("compress", compress_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_image))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is ready!")
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except Conflict as e:
        logger.error(f"Conflict error: {e}")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
