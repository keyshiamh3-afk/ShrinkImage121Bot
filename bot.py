import os
import logging
import sys
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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
    
    add_user(user_id, username, first_name)
    
    data = query.data
    
    if data == "welcome":
        log_click(user_id, 'welcome_button')
        
        # Send the welcome message with image
        try:
            # Check if image exists
            image_path = 'rswallet_image.png'
            if os.path.exists(image_path):
                # Send as photo
                with open(image_path, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=InputFile(photo, filename='rswallet_image.png'),
                        caption=WELCOME_MESSAGE,
                        parse_mode='HTML'
                    )
            else:
                # Fallback: send without image
                logger.error("Image file not found at path: " + os.path.abspath(image_path))
                await query.message.reply_text(
                    "⚠️ Image not found. Here's the message:\n\n" + WELCOME_MESSAGE,
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.error(f"Image send error: {e}")
            await query.message.reply_text(WELCOME_MESSAGE, parse_mode='HTML')
        
        # Delete the original message with button
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Delete error: {e}")
    
    elif data == "register":
        log_click(user_id, 'register_button')
        await query.message.reply_text(
            "🔗 **Register Now:**\n\n"
            "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
            "Start earning with RS Wallet today! 💰",
            parse_mode='Markdown'
        )
    
    elif data == "channel":
        log_click(user_id, 'channel_button')
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
    
    add_user(user_id, username, first_name)
    log_click(user_id, 'start_command')
    
    keyboard = [
        [InlineKeyboardButton("🚀 Get Started Now", callback_data="welcome")],
        [InlineKeyboardButton("📢 Join Channel", callback_data="channel")],
        [InlineKeyboardButton("💰 Register", callback_data="register")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
    try:
        image_path = 'rswallet_image.png'
        if os.path.exists(image_path):
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(
                    photo=InputFile(photo, filename='rswallet_image.png'),
                    caption=WELCOME_MESSAGE,
                    parse_mode='HTML'
                )
        else:
            await update.message.reply_text(
                "⚠️ Image file not found. Here's the message:\n\n" + WELCOME_MESSAGE,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Image send error: {e}")
        await update.message.reply_text(WELCOME_MESSAGE, parse_mode='HTML')

async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 **Register Now:**\n\n"
        "https://app-web.rswallet-api.com/regist?code=0ealuckpbosq\n\n"
        "✅ Start earning with RS Wallet today!",
        parse_mode='Markdown'
    )

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📢 **Join our Channel:**\n\n"
        "https://t.me/rswalleto\n\n"
        "Stay updated with the latest news!",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # Check and log image file status
    image_path = 'rswallet_image.png'
    if os.path.exists(image_path):
        file_size = os.path.getsize(image_path)
        logger.info(f"✅ Image file found: {image_path} ({file_size} bytes)")
    else:
        logger.error(f"❌ Image file NOT found at: {os.path.abspath(image_path)}")
        logger.error("Make sure 'rswallet_image.png' is in the same directory as bot.py")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("welcome", welcome_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(button_callback))
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
