import os
import logging
import sys
import io
from datetime import datetime
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import Conflict

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable not set!")
    sys.exit(1)

ADMIN_IDS = []
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

# Maximum file size (20MB - Telegram limit)
MAX_FILE_SIZE = 20 * 1024 * 1024

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- User Session Storage ---
user_sessions = {}

# --- Image Compression Functions ---
def compress_image(image_data, quality=85, max_width=None, max_height=None):
    """
    Compress image with given quality and dimensions.
    Returns compressed image as bytes.
    """
    try:
        # Open image
        img = Image.open(io.BytesIO(image_data))
        
        # Convert RGBA to RGB if necessary
        if img.mode == 'RGBA':
            # Create a white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
            img = background
        elif img.mode not in ['RGB', 'L']:
            img = img.convert('RGB')
        
        # Resize if max dimensions provided
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

def get_optimal_quality(image_data, target_size_mb=1.0):
    """
    Find optimal quality to achieve target file size.
    """
    min_quality = 10
    max_quality = 95
    target_bytes = target_size_mb * 1024 * 1024
    
    # Quick check if image is already small enough
    if len(image_data) <= target_bytes:
        return 95  # Use high quality
    
    # Binary search for optimal quality
    best_quality = 70
    best_size = len(image_data)
    
    for _ in range(10):  # 10 iterations
        mid_quality = (min_quality + max_quality) // 2
        compressed, _ = compress_image(image_data, quality=mid_quality)
        
        if compressed is None:
            break
            
        compressed_size = len(compressed)
        
        if compressed_size <= target_bytes:
            best_quality = mid_quality
            best_size = compressed_size
            min_quality = mid_quality + 1
        else:
            max_quality = mid_quality - 1
    
    return best_quality

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    
    welcome_text = (
        f"🖼️ **Image Compressor Bot**\n\n"
        f"Hi {user.first_name}! I can compress your images to save space.\n\n"
        f"**Features:**\n"
        f"• Compress images up to 20MB\n"
        f"• Choose compression quality\n"
        f"• Resize images\n"
        f"• Batch processing\n\n"
        f"**How to use:**\n"
        f"1. Send me an image\n"
        f"2. Choose compression options\n"
        f"3. Get your compressed image\n\n"
        f"**Commands:**\n"
        f"/compress - Compress with options\n"
        f"/quality <1-100> - Set quality (default: 85)\n"
        f"/resize <width> <height> - Set dimensions\n"
        f"/help - Show this message"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🖼️ **Image Compressor Bot Help**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/quality <1-100> - Set compression quality\n"
        "/resize <width> <height> - Resize image\n"
        "/compress - Compress with options\n"
        "/settings - View current settings\n"
        "/reset - Reset to default settings\n\n"
        "**Tips:**\n"
        "• Lower quality = smaller file size\n"
        "• Higher quality = better image quality\n"
        "• You can send multiple images at once"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set compression quality."""
    user_id = update.effective_user.id
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "❌ Please provide a quality value!\n"
            "Usage: /quality <1-100>\n"
            "Example: /quality 85"
        )
        return
    
    quality = int(args[0])
    if quality < 1 or quality > 100:
        await update.message.reply_text("❌ Quality must be between 1 and 100!")
        return
    
    # Store user preference
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]['quality'] = quality
    
    await update.message.reply_text(f"✅ Quality set to {quality}%")

async def resize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set resize dimensions."""
    user_id = update.effective_user.id
    
    args = context.args
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text(
            "❌ Please provide width and height!\n"
            "Usage: /resize <width> <height>\n"
            "Example: /resize 800 600"
        )
        return
    
    width = int(args[0])
    height = int(args[1])
    
    if width < 1 or height < 1:
        await update.message.reply_text("❌ Width and height must be positive numbers!")
        return
    
    # Store user preference
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]['resize'] = (width, height)
    
    await update.message.reply_text(f"✅ Resize set to {width}x{height}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current settings."""
    user_id = update.effective_user.id
    
    settings = user_sessions.get(user_id, {})
    quality = settings.get('quality', 85)
    resize = settings.get('resize', None)
    
    settings_text = (
        f"⚙️ **Your Settings**\n\n"
        f"• Quality: {quality}%\n"
        f"• Resize: {resize[0]}x{resize[1] if resize else 'Disabled'}\n\n"
        f"Send an image to compress!"
    )
    
    await update.message.reply_text(settings_text, parse_mode='Markdown')

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset settings to default."""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        user_sessions[user_id] = {}
    
    await update.message.reply_text("✅ Settings reset to default!")

async def compress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual compress command with options."""
    user_id = update.effective_user.id
    
    keyboard = [
        [
            InlineKeyboardButton("📱 Low (50%)", callback_data="quality_50"),
            InlineKeyboardButton("📱 Medium (70%)", callback_data="quality_70"),
            InlineKeyboardButton("📱 High (85%)", callback_data="quality_85"),
        ],
        [
            InlineKeyboardButton("📏 Resize 800x600", callback_data="resize_800_600"),
            InlineKeyboardButton("📏 Resize 1024x768", callback_data="resize_1024_768"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Settings", callback_data="reset_settings"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🖼️ **Choose compression options:**\n\n"
        "Then send me an image to compress!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# --- Callback Query Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    
    if data.startswith("quality_"):
        quality = int(data.split("_")[1])
        user_sessions[user_id]['quality'] = quality
        await query.edit_message_text(
            f"✅ Quality set to {quality}%\n\n"
            f"Now send me an image to compress!",
            parse_mode='Markdown'
        )
    
    elif data.startswith("resize_"):
        parts = data.split("_")
        width = int(parts[1])
        height = int(parts[2])
        user_sessions[user_id]['resize'] = (width, height)
        await query.edit_message_text(
            f"✅ Resize set to {width}x{height}\n\n"
            f"Now send me an image to compress!",
            parse_mode='Markdown'
        )
    
    elif data == "reset_settings":
        if user_id in user_sessions:
            user_sessions[user_id] = {}
        await query.edit_message_text(
            f"✅ Settings reset to default!\n\n"
            f"Send me an image to compress.",
            parse_mode='Markdown'
        )

# --- Message Handler ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image messages."""
    user_id = update.effective_user.id
    
    # Get photo
    if not update.message.photo:
        await update.message.reply_text("❌ Please send an image!")
        return
    
    # Get the largest photo
    photo = update.message.photo[-1]
    file_size = photo.file_size
    
    if file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ Image is too large! Maximum size is 20MB.\n"
            f"Current size: {file_size / (1024*1024):.1f}MB"
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("⏳ Compressing image...")
    
    try:
        # Download image
        file = await context.bot.get_file(photo.file_id)
        image_data = await file.download_as_bytearray()
        
        # Get user settings
        settings = user_sessions.get(user_id, {})
        quality = settings.get('quality', 85)
        resize = settings.get('resize', None)
        
        # Find optimal quality if image needs more compression
        if len(image_data) > 5 * 1024 * 1024:  # If > 5MB
            quality = get_optimal_quality(image_data, 1.0)  # Target 1MB
        
        # Compress image
        max_width = resize[0] if resize else None
        max_height = resize[1] if resize else None
        
        compressed_data, original_size = compress_image(
            image_data, 
            quality=quality,
            max_width=max_width,
            max_height=max_height
        )
        
        if compressed_data is None:
            await processing_msg.edit_text("❌ Failed to compress image. Please try again.")
            return
        
        # Calculate compression ratio
        original_size_mb = len(image_data) / (1024 * 1024)
        compressed_size_mb = len(compressed_data) / (1024 * 1024)
        ratio = (1 - (len(compressed_data) / len(image_data))) * 100
        
        # Send compressed image
        compressed_file = io.BytesIO(compressed_data)
        compressed_file.name = 'compressed_image.jpg'
        
        await update.message.reply_document(
            document=compressed_file,
            caption=(
                f"✅ **Compressed Successfully!**\n\n"
                f"📊 **Statistics:**\n"
                f"• Original Size: {original_size_mb:.2f}MB\n"
                f"• Compressed Size: {compressed_size_mb:.2f}MB\n"
                f"• Reduced: {ratio:.1f}%\n"
                f"• Quality: {quality}%\n"
                f"• Dimensions: {original_size[0]}x{original_size[1]}"
            ),
            parse_mode='Markdown'
        )
        
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        await processing_msg.edit_text(
            "❌ Error processing image. Please try again with a different image."
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document messages (images)."""
    if not update.message.document:
        return
    
    document = update.message.document
    
    # Check if it's an image
    mime_type = document.mime_type or ""
    if not mime_type.startswith('image/'):
        await update.message.reply_text("❌ Please send an image file!")
        return
    
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ File is too large! Maximum size is 20MB.\n"
            f"Current size: {document.file_size / (1024*1024):.1f}MB"
        )
        return
    
    # Process like image
    await handle_image(update, context)

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Error: {context.error}")
    
    if isinstance(context.error, Conflict):
        logger.warning("Conflict error - another instance running")
    elif update and update.message:
        await update.message.reply_text(
            "❌ An error occurred. Please try again later."
        )

# --- Main Function ---
def main():
    """Start the bot."""
    logger.info("🖼️ Starting Image Compressor Bot...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("resize", resize_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("compress", compress_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is ready!")
    
    # Clear webhook
    application.bot.delete_webhook()
    
    # Start polling
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
