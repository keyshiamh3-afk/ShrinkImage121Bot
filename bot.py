import os
import logging
import sys
import sqlite3
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  last_interaction TIMESTAMP,
                  reminder_sent INTEGER DEFAULT 0,
                  joined_date TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS referral_clicks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  click_time TIMESTAMP,
                  source TEXT)''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# --- Database Helper Functions ---
def add_user(user_id, username, first_name):
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date) VALUES (?, ?, ?, ?)",
              (user_id, username, first_name, datetime.now().isoformat()))
    c.execute("UPDATE users SET last_interaction=?, username=?, first_name=? WHERE user_id=?",
              (datetime.now().isoformat(), username, first_name, user_id))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_interaction, reminder_sent FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'last_interaction': row[3],
            'reminder_sent': row[4]
        }
    return None

def update_reminder_status(user_id, sent=True):
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET reminder_sent=? WHERE user_id=?", (1 if sent else 0, user_id))
    conn.commit()
    conn.close()

def log_click(user_id, source='button'):
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO referral_clicks (user_id, click_time, source) VALUES (?, ?, ?)",
              (user_id, datetime.now().isoformat(), source))
    conn.commit()
    conn.close()

def get_user_count():
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

# --- Message Content ---
WELCOME_MESSAGE = """✅Welcome to RS Wallet. We offer a 4% INR USDT exchange rate (107), a team commission of 0.3% for Level 1 and 0.1% for Level 2. 

⏩Register here ✅

https://app-web.rswallet-api.com/regist?code=0ealuckpbosq

🔝We also provide team leader salary 0.5% contact us now ⭐️

@Alysyas

Channel link ⏩

https://t.me/rswalleto"""

# --- Button Callback Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    first_name = query.from_user.first_name
    
    # Add user to database
    add_user(user_id, username, first_name)
    
    data = query.data
    
    if data == "welcome":
        # Log the click
        log_click(user_id, 'welcome_button')
        
        # Send the welcome message with image from local file
        try:
            # Open and send the image file
            with open('rswallet_image.png', 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=WELCOME_MESSAGE,
                    parse_mode='HTML'
                )
        except FileNotFoundError:
            logger.error("Image file not found! Make sure 'rswallet_image.png' is in the bot directory.")
            # Fallback: send without image
            await query.message.reply_text(
                WELCOME_MESSAGE,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Image send error: {e}")
            await query.message.reply_text(
                WELCOME_MESSAGE,
                parse_mode='HTML'
            )
        
        # Delete the original message with button
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Delete error: {e}")
    
    elif data == "register":
        # Log the click
        log_click(user_id, 'register_button')
        
        # Send registration link
        await query.message.reply_text(
            "🔗 **Register Now:**\n\n"
            "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
            "Start earning with RS Wallet today! 💰",
            parse_mode='Markdown'
        )
    
    elif data == "channel":
        # Log the click
        log_click(user_id, 'channel_button')
        
        # Send channel link
        await query.message.reply_text(
            "📢 **Join our Channel:**\n\n"
            "https://t.me/rswalleto\n\n"
            "Stay updated with the latest news! 📰",
            parse_mode='Markdown'
        )

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    first_name = user.first_name
    
    # Add user to database
    add_user(user_id, username, first_name)
    log_click(user_id, 'start_command')
    
    # Create welcome button
    keyboard = [
        [InlineKeyboardButton("🚀 Get Started Now", callback_data="welcome")],
        [InlineKeyboardButton("📢 Join Channel", callback_data="channel")],
        [InlineKeyboardButton("💰 Register", callback_data="register")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Welcome text
    welcome_text = (
        f"👋 **Welcome {first_name}!**\n\n"
        f"💰 **RS Wallet** - Your Gateway to Crypto Earnings!\n\n"
        f"Click the button below to learn how you can:\n"
        f"• Earn 4% on INR deposits\n"
        f"• Get the best USDT rate (107 INR)\n"
        f"• Build your team and earn commissions\n"
        f"• Become a Team Leader with 0.5% salary\n\n"
        f"🚀 Start your journey now!"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 **RS Wallet Bot Help**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/welcome - View welcome message\n"
        "/register - Get registration link\n"
        "/channel - Join our channel\n"
        "/stats - View bot statistics\n"
        "/help - Show this message\n\n"
        "**For support:**\n"
        "Contact @Alysyas"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger the welcome message."""
    try:
        with open('rswallet_image.png', 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=WELCOME_MESSAGE,
                parse_mode='HTML'
            )
    except FileNotFoundError:
        logger.error("Image file not found!")
        await update.message.reply_text(WELCOME_MESSAGE, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Image send error: {e}")
        await update.message.reply_text(WELCOME_MESSAGE, parse_mode='HTML')

async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send registration link."""
    await update.message.reply_text(
        "🔗 **Register Now:**\n\n"
        "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
        "✅ Start earning with RS Wallet today!",
        parse_mode='Markdown'
    )

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send channel link."""
    await update.message.reply_text(
        "📢 **Join our Channel:**\n\n"
        "https://t.me/rswalleto\n\n"
        "Stay updated with the latest news!",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ This command is for admins only!")
        return
    
    user_count = get_user_count()
    
    stats_text = (
        f"📊 **RS Wallet Bot Statistics**\n\n"
        f"👥 Total Users: {user_count}\n"
        f"🟢 Bot Status: Online\n\n"
        f"📈 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# --- Reminder Scheduler ---
async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Send reminders to users who haven't interacted for 2 hours."""
    logger.info("Checking for users to remind...")
    
    conn = sqlite3.connect('rswallet_bot.db')
    c = conn.cursor()
    
    # Get users who haven't interacted in 2 hours and haven't been reminded
    two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    c.execute("""
        SELECT user_id, username, first_name 
        FROM users 
        WHERE last_interaction < ? 
        AND reminder_sent = 0
    """, (two_hours_ago,))
    
    users = c.fetchall()
    conn.close()
    
    for user_id, username, first_name in users:
        try:
            # Send reminder
            reminder_text = (
                f"⏰ **Hey {first_name or 'there'}!**\n\n"
                f"Don't miss out on the amazing opportunities with RS Wallet! 💰\n\n"
                f"• Get 4% on INR deposits\n"
                f"• Best USDT rate (107 INR)\n"
                f"• Build your team and earn\n\n"
                f"Click /start to get started!"
            )
            
            keyboard = [
                [InlineKeyboardButton("🚀 Get Started", callback_data="welcome")],
                [InlineKeyboardButton("💰 Register", callback_data="register")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text=reminder_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # Update reminder status
            update_reminder_status(user_id, sent=True)
            
            logger.info(f"Reminder sent to user {user_id}")
            await asyncio.sleep(0.5)  # Rate limit
            
        except Exception as e:
            logger.error(f"Failed to send reminder to {user_id}: {e}")

# --- Periodic Reminder Setup ---
async def schedule_reminders(application):
    """Schedule the reminder job."""
    job_queue = application.job_queue
    
    if job_queue:
        # Run every 30 minutes
        job_queue.run_repeating(send_reminders, interval=1800, first=60)
        logger.info("Reminder scheduler started!")

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    
    if isinstance(context.error, Conflict):
        logger.warning("Conflict error - another instance running")
    elif update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text("❌ An error occurred. Please try again later.")
        except:
            pass

# --- Main Function ---
def main():
    logger.info("💰 Starting RS Wallet Bot...")
    
    # Check if image file exists
    if not os.path.exists('rswallet_image.png'):
        logger.warning("⚠️ Image file 'rswallet_image.png' not found! The bot will work but without images.")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("welcome", welcome_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is ready!")
    
    # Clear webhook
    application.bot.delete_webhook()
    
    # Schedule reminders
    try:
        asyncio.run(schedule_reminders(application))
    except RuntimeError:
        # If already running in event loop
        pass
    
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
