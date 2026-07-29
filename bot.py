import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes
import aiohttp

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found. Please set it in Railway variables.")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# ✏️ CONFIGURATION - EDIT THESE AS NEEDED
# ============================================================

# The welcome message you provided
WELCOME_TEXT = (
    "✅Welcome to RS Wallet. We offer a 4% INR USDT exchange rate (107), "
    "a team commission of 0.3% for Level 1 and 0.1% for Level 2.\n\n"
    "⏩Register here ✅\n"
    "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
    "🔝We also provide team leader salary 0.5% contact us now ⭐️\n"
    "@Alysyas\n\n"
    "Channel link ⏩\n"
    "https://t.me/rswalleto"
)

# The image file name (must be in the same GitHub repository)
WELCOME_IMAGE = "rswallet_image.png"  # Your image file

# Reminder interval in seconds (2 hours = 7200 seconds)
REMINDER_INTERVAL = 7200  # 2 hours

# ============================================================
# BOT COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the welcome image and message when /start is issued."""
    user = update.effective_user
    logger.info(f"User {user.first_name} ({user.id}) started the bot.")

    # Send the image first
    try:
        with open(WELCOME_IMAGE, 'rb') as photo:
            await update.message.reply_photo(
                photo=InputFile(photo),
                caption=WELCOME_TEXT,
                parse_mode="HTML"
            )
    except FileNotFoundError:
        # If image is missing, send just the text
        logger.warning(f"Image file '{WELCOME_IMAGE}' not found. Sending text only.")
        await update.message.reply_text(WELCOME_TEXT)
    except Exception as e:
        logger.error(f"Error sending image: {e}")
        await update.message.reply_text(WELCOME_TEXT)

    # Add user to reminder list if not already present
    if 'users_to_remind' not in context.bot_data:
        context.bot_data['users_to_remind'] = set()
    context.bot_data['users_to_remind'].add(update.effective_user.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message."""
    help_text = (
        "🤖 *RS Wallet Bot Commands*\n\n"
        "/start - Show the welcome message and image\n"
        "/help - Show this help menu\n"
        "/stop_reminders - Stop receiving 2-hour reminders\n"
        "/resume_reminders - Resume receiving reminders\n"
        "/status - Check your reminder status\n\n"
        "⏰ Reminders are sent every 2 hours.\n\n"
        "For support contact: @Alysyas"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def stop_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop sending reminders to the user."""
    user_id = update.effective_user.id
    if 'users_to_remind' in context.bot_data:
        context.bot_data['users_to_remind'].discard(user_id)
        await update.message.reply_text("✅ You will no longer receive 2-hour reminders.")
    else:
        await update.message.reply_text("⚠️ You were not on the reminder list.")

async def resume_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume sending reminders to the user."""
    user_id = update.effective_user.id
    if 'users_to_remind' not in context.bot_data:
        context.bot_data['users_to_remind'] = set()
    context.bot_data['users_to_remind'].add(user_id)
    await update.message.reply_text("✅ You will now receive 2-hour reminders again.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if the user is on the reminder list."""
    user_id = update.effective_user.id
    if 'users_to_remind' in context.bot_data and user_id in context.bot_data['users_to_remind']:
        await update.message.reply_text("⏰ You are currently receiving 2-hour reminders.")
    else:
        await update.message.reply_text("⏸️ You are not receiving reminders. Use /resume_reminders to start.")

# ============================================================
# REMINDER JOB (Runs every 2 hours)
# ============================================================

async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Send a reminder message to all users in the reminder list."""
    if 'users_to_remind' not in context.bot_data:
        return

    reminder_text = (
        "⏰ *2-Hour Reminder*\n\n"
        "✅Welcome to RS Wallet. We offer a 4% INR USDT exchange rate (107), "
        "a team commission of 0.3% for Level 1 and 0.1% for Level 2.\n\n"
        "⏩Register here ✅\n"
        "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
        "🔝We also provide team leader salary 0.5% contact us now ⭐️\n"
        "@Alysyas\n\n"
        "Channel link ⏩\n"
        "https://t.me/rswalleto"
    )

    users_to_remove = []
    for user_id in context.bot_data['users_to_remind']:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=reminder_text,
                parse_mode="Markdown"
            )
            logger.info(f"Reminder sent to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder to {user_id}: {e}")
            users_to_remove.append(user_id)

    # Clean up users who blocked the bot
    for user_id in users_to_remove:
        context.bot_data['users_to_remind'].discard(user_id)

# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop_reminders", stop_reminders))
    application.add_handler(CommandHandler("resume_reminders", resume_reminders))
    application.add_handler(CommandHandler("status", status_command))

    # Schedule the reminder job (every 2 hours)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            send_reminders,
            interval=REMINDER_INTERVAL,
            first=10  # First reminder after 10 seconds (for testing)
        )
        logger.info(f"Reminder job scheduled every {REMINDER_INTERVAL} seconds (2 hours).")
    else:
        logger.warning("Job queue not available. Reminders will not work.")

    # Start the bot
    print("🤖 RS Wallet Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
