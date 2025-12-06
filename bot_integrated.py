"""
Production-Ready Telegram Bot with Complete Security & Scalability
Integrates: Encryption, Rate Limiting, Domain Verification, Celery Queue
"""

from secure_config import *
from rate_limiter import RateLimiter, rate_limit_decorator
from domain_verifier import DomainVerifier, filter_verified_urls, get_verification_instructions
import telebot
import re
import requests
from urllib.parse import urlparse
import time
import psycopg2
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import os
from telebot import apihelper

'''# Configure proxy (SOCKS5 example)
apihelper.proxy = {
    'https': 'socks5://username:password@proxy-server:port'
}

# Or HTTP proxy
apihelper.proxy = {
    'https': 'http://proxy-server:port'
}'''

# Then initialize bot
#bot = telebot.TeleBot(token=API_TOKEN)

print(f"🔍 Bot Token Length: {len(BOT_TOKEN)}")
print(f"🔍 Token Preview: {BOT_TOKEN[:10]}...{BOT_TOKEN[-10:]}")
if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
    print("❌ ERROR: Bot token not configured!")
    exit(1)

#bot = telebot.TeleBot(token=API_TOKEN)
API_TOKEN='8217579466:AAEq0V9-0TtWqaphRbbBKj8_Suk-MVAy1no'
bot = telebot.TeleBot(token=API_TOKEN)

# Initialize components
rate_limiter = RateLimiter(DB_CONFIG)
domain_verifier = DomainVerifier(SERVICE_ACCOUNT_FILE)

# Google Indexing API Configuration
SCOPES = ["https://www.googleapis.com/auth/indexing"]

# ==================== EXISTING FUNCTIONS ====================
# (Keep all your existing database and indexing functions)

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def init_database():
    """Initialize all database tables"""
    try:
        conn = get_db_connection()
        if not conn:
            print("❌ Cannot connect to database!")
            return False
        
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                credits INTEGER DEFAULT 0,
                plan_type VARCHAR(50) DEFAULT 'free',
                is_active BOOLEAN DEFAULT TRUE,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index for users
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
        """)
        
        # URLs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                url TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                indexed_at TIMESTAMP,
                error_message TEXT
            )
        """)
        
        # Create indexes for URLs
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_urls_user_id ON urls(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_urls_status ON urls(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_urls_url ON urls(url)
        """)
        
        # Transactions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                amount INTEGER NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index for transactions
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)
        """)
        
        # Batch uploads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batch_uploads (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                filename VARCHAR(255),
                total_urls INTEGER,
                valid_urls INTEGER,
                indexed_urls INTEGER,
                credits_charged INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index for batch uploads
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_batch_uploads_user_id ON batch_uploads(user_id)
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Main database tables initialized successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        return False

    
        
# User data storage (in-memory)
user_data = {}

# Configuration constants (add these at the top after imports if not present)
FREE_CREDITS = 10  # Free credits for new users
MAX_URLS_PER_FILE = 1000  # Maximum URLs per file upload

def initialize_user(user_id, username, initial_credits=FREE_CREDITS):
    """Initialize a new user in the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO users (user_id, username, credits, plan_type, is_active)
            VALUES (%s, %s, %s, 'free', TRUE)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id, username, initial_credits))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error initializing user: {e}")
        return False

def get_user_credits(user_id):
    """Get user credit information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT credits, plan_type, is_active
            FROM users
            WHERE user_id = %s
        """, (user_id,))
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            return {
                'credits': result[0],
                'plan_type': result[1],
                'is_active': result[2]
            }
        return None
    except Exception as e:
        print(f"Error getting user credits: {e}")
        return None

def deduct_credits(user_id, amount, description=""):
    """Deduct credits from user account"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check current credits
        cursor.execute("SELECT credits FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        
        if not result:
            return False, 0, "User not found"
        
        current_credits = result[0]
        
        if current_credits < amount:
            cursor.close()
            conn.close()
            return False, current_credits, f"Insufficient credits. You have {current_credits}, need {amount}"
        
        # Deduct credits
        cursor.execute("""
            UPDATE users
            SET credits = credits - %s,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = %s
        """, (amount, user_id))
        
        # Log transaction
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, transaction_type, description)
            VALUES (%s, %s, 'debit', %s)
        """, (user_id, -amount, description))
        
        new_balance = current_credits - amount
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True, new_balance, "Success"
    except Exception as e:
        print(f"Error deducting credits: {e}")
        return False, 0, str(e)

def refund_credits(user_id, amount, description=""):
    """Refund credits to user account"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users
            SET credits = credits + %s
            WHERE user_id = %s
        """, (amount, user_id))
        
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, transaction_type, description)
            VALUES (%s, %s, 'credit', %s)
        """, (user_id, amount, description))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error refunding credits: {e}")
        return False

def extract_urls_from_text(text):
    """Extract URLs from text"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return urls

def check_url_batch(urls, chat_id, message_id, user_id):
    """Validate a batch of URLs"""
    valid_urls = []
    indexable_urls = []
    
    for url in urls:
        try:
            parsed = urlparse(url)
            if parsed.scheme in ['http', 'https'] and parsed.netloc:
                valid_urls.append(url)
                indexable_urls.append(url)
        except:
            pass
    
    return valid_urls, indexable_urls

def save_batch_upload(user_id, filename, total_urls, valid_urls, indexed_urls, credits_charged):
    """Save batch upload information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO batch_uploads 
            (user_id, filename, total_urls, valid_urls, indexed_urls, credits_charged)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, filename, total_urls, valid_urls, indexed_urls, credits_charged))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving batch upload: {e}")
        return False

def submit_urls_to_google(urls, chat_id, message_id, user_id):
    """Submit URLs to Google Indexing API"""
    successful = []
    failed = []
    
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        
        service = build('indexing', 'v3', credentials=credentials)
        
        for i, url in enumerate(urls):
            try:
                body = {
                    'url': url,
                    'type': 'URL_UPDATED'
                }
                
                response = service.urlNotifications().publish(body=body).execute()
                successful.append(url)
                
                # Update database
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE urls
                    SET status = 'indexed', indexed_at = CURRENT_TIMESTAMP
                    WHERE url = %s AND user_id = %s
                """, (url, user_id))
                conn.commit()
                cursor.close()
                conn.close()
                
            except Exception as e:
                failed.append((url, str(e)))
                print(f"Failed to index {url}: {e}")
            
            time.sleep(0.5)  # Rate limiting
    
    except Exception as e:
        print(f"Error in submit_urls_to_google: {e}")
    
    return successful, failed    
# ... (all other existing functions from your original bot.py)

# ==================== ENHANCED COMMANDS WITH RATE LIMITING ====================

@bot.message_handler(commands=['start'])
@rate_limit_decorator(rate_limiter, limit_type='command')
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    # Initialize user
    initialize_user(user_id, username, initial_credits=FREE_CREDITS)
    user_info = get_user_credits(user_id)
    
    if not user_info:
        bot.reply_to(message, "❌ Error initializing user. Please try again.")
        return
    
    response = f"""
🎉 **Welcome to URL Indexing Bot!**

👤 User: @{username}
🆔 Your ID: `{user_id}`
💳 Credits: **{user_info['credits']}**
📊 Plan: **{user_info['plan_type'].title()}**
🔄 Status: **{'✅ Active' if user_info['is_active'] else '❌ Disabled'}**

**How it works:**
1️⃣ Upload .txt file with URLs
2️⃣ Bot validates and counts URLs
3️⃣ Type `index` to submit
4️⃣ **1 Credit = 1 URL indexed**

**Commands:**
/balance - Check your credits
/stats - View your statistics
/help - Get help
/buy - Purchase credits

📝 Upload your .txt file to begin!

🔒 **Security:** Your data is encrypted and secure.
"""
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['balance'])
@rate_limit_decorator(rate_limiter, limit_type='command')
def balance_command(message):
    user_id = message.from_user.id
    user_info = get_user_credits(user_id)
    
    if not user_info:
        bot.reply_to(message, "❌ User not found. Use /start to register.")
        return
    
    # Get rate limit stats
    from rate_limiter import get_rate_limit_stats
    stats = get_rate_limit_stats(user_id, DB_CONFIG)
    
    response = f"""
💳 **Your Credit Balance**

Available: **{user_info['credits']} credits**
Plan: **{user_info['plan_type'].title()}**
Status: **{'✅ Active' if user_info['is_active'] else '❌ Disabled'}**

📊 **Today's Usage:**
• Files uploaded: {stats['uploads_today']}/{rate_limiter.limits['files_per_hour']}
• URLs processed: {stats['urls_today']}/{rate_limiter.limits['urls_per_day']}

💡 Need more credits? Use /buy
"""
    
    bot.reply_to(message, response, parse_mode='Markdown')

# ==================== ENHANCED FILE UPLOAD WITH VERIFICATION ====================

@bot.message_handler(content_types=['document'])
@rate_limit_decorator(rate_limiter, limit_type='file')
def handle_document(message):
    user_id = message.from_user.id
    
    # Check if user exists and is active
    user_info = get_user_credits(user_id)
    if not user_info:
        bot.reply_to(message, "❌ Please use /start first to register.")
        return
    
    if not user_info['is_active']:
        bot.reply_to(message, "❌ Your account is disabled. Contact admin.")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        
        if not file_name.endswith('.txt'):
            bot.reply_to(message, "❌ Please send a .txt file only!")
            return
        
        downloaded_file = bot.download_file(file_info.file_path)
        file_content = downloaded_file.decode('utf-8')
        
        all_urls = extract_urls_from_text(file_content)
        
        if not all_urls:
            bot.send_message(message.chat.id, "❌ No URLs found in file!")
            return
        
        # Check file size limit
        unique_urls = list(set(all_urls))
        if len(unique_urls) > MAX_URLS_PER_FILE:
            bot.reply_to(message, 
                f"❌ Too many URLs! Maximum allowed: {MAX_URLS_PER_FILE}\n"
                f"Your file contains: {len(unique_urls)} URLs\n\n"
                f"Please split into multiple files."
            )
            return
        
        # Check URL limit
        allowed, remaining = rate_limiter.check_url_limit(user_id, len(unique_urls))
        if not allowed:
            bot.reply_to(message,
                f"⚠️ **Daily URL Limit Reached**\n\n"
                f"You can process {remaining} more URLs today.\n"
                f"Daily limit: {rate_limiter.limits['urls_per_day']} URLs\n\n"
                f"Limit resets at midnight UTC."
            )
            return
        
        progress_msg = bot.send_message(
            message.chat.id, 
            f"⏳ Found {len(unique_urls)} unique URLs. Validating & checking domain verification..."
        )
        
        # Validate URLs
        valid_urls, indexable_urls = check_url_batch(
            unique_urls, 
            message.chat.id, 
            progress_msg.message_id,
            user_id
        )
        
        # Check domain verification
        bot.edit_message_text(
            "🔍 Checking domain verification in Google Search Console...",
            chat_id=message.chat.id,
            message_id=progress_msg.message_id
        )
        
        verified_urls, unverified_urls = filter_verified_urls(indexable_urls, SERVICE_ACCOUNT_FILE)
        
        # Save batch upload info
        save_batch_upload(
            user_id,
            file_name,
            len(all_urls),
            len(valid_urls),
            len(verified_urls),
            credits_charged=0
        )
        
        try:
            bot.delete_message(message.chat.id, progress_msg.message_id)
        except:
            pass
        
        # Store in memory for indexing
        user_data[message.chat.id] = {
            'indexable_urls': verified_urls,
            'unverified_urls': unverified_urls,
            'valid_urls': valid_urls
        }
        
        verified_count = len(verified_urls)
        unverified_count = len(unverified_urls)
        user_credits = user_info['credits']
        
        # Build response
        response = f"""
📊 **Analysis Complete!**

📝 Total URLs: **{len(all_urls)}**
🔗 Unique URLs: **{len(unique_urls)}**
✅ Valid URLs: **{len(valid_urls)}**
🔍 Indexable: **{verified_count + unverified_count}**

"""
        
        if verified_count > 0:
            response += f"""
**Domain Verification:**
✅ Verified domains: **{verified_count} URLs**
"""
            
            if unverified_count > 0:
                response += f"⚠️ Unverified domains: **{unverified_count} URLs**\n"
            
            response += f"""
💳 Your Credits: **{user_credits}**
✔️ Cost: **{verified_count} credits**
💰 After: **{user_credits - verified_count} credits**

✨ Reply with `index` to proceed!
"""
            
            if unverified_count > 0:
                # Get unique unverified domains
                unverified_domains = set(urlparse(url).netloc for url in unverified_urls)
                response += f"\n⚠️ **Note:** {unverified_count} URLs from unverified domains will be skipped.\n"
                response += f"Unverified domains: {', '.join(list(unverified_domains)[:3])}"
                if len(unverified_domains) > 3:
                    response += f" and {len(unverified_domains) - 3} more"
                response += f"\n\nUse /verify to learn how to verify your domains."
        else:
            response += f"""
❌ **No Verified Domains Found!**

All {len(indexable_urls)} indexable URLs are from unverified domains.

You need to verify your domains in Google Search Console first.
Use /verify for instructions.
"""
        
        bot.send_message(message.chat.id, response, parse_mode='Markdown')
        
        # Send files
        if verified_urls:
            content = '\n'.join(verified_urls)
            bot.send_document(
                message.chat.id,
                ('verified_indexable_urls.txt', content.encode('utf-8')),
                caption=f"✅ {len(verified_urls)} URLs ready for indexing"
            )
        
        if unverified_urls:
            content = '\n'.join(unverified_urls)
            bot.send_document(
                message.chat.id,
                ('unverified_urls.txt', content.encode('utf-8')),
                caption=f"⚠️ {len(unverified_urls)} URLs from unverified domains"
            )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
        print(f"Error: {e}")

# ==================== NEW COMMAND: DOMAIN VERIFICATION ====================

@bot.message_handler(commands=['verify'])
def verify_command(message):
    """Show domain verification instructions"""
    # Get user's recent unverified domains
    from domain_verifier import get_unverified_domains_report
    
    user_id = message.from_user.id
    unverified = get_unverified_domains_report(user_id, DB_CONFIG)
    
    response = """
🔍 **Domain Verification Guide**

To use Google Indexing API, your domains must be verified in Google Search Console.

**Quick Steps:**
1. Go to: https://search.google.com/search-console
2. Click "Add Property"
3. Add your service account email as Owner
4. Service account email is in your `service-account.json` file

"""
    
    if unverified:
        response += "**Your Unverified Domains:**\n"
        for domain, count, first, last in unverified[:5]:
            response += f"• `{domain}` ({count} URLs blocked)\n"
        
        response += f"\nUse `/verifyhelp {unverified[0][0]}` for detailed instructions."
    else:
        response += "✅ No unverified domains found in recent uploads!"
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['verifyhelp'])
def verify_help_command(message):
    """Show detailed verification instructions for a domain"""
    parts = message.text.split()
    
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /verifyhelp <domain>\nExample: /verifyhelp example.com")
        return
    
    domain = parts[1]
    instructions = domain_verifier.get_verification_instructions(domain)
    
    bot.reply_to(message, instructions, parse_mode='Markdown')

# ==================== ENHANCED INDEXING WITH CELERY QUEUE ====================

@bot.message_handler(func=lambda message: message.text and message.text.lower() == 'index')
@rate_limit_decorator(rate_limiter, limit_type='api')
def handle_index_command(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Check if URLs are ready
    if chat_id not in user_data or not user_data[chat_id].get('indexable_urls'):
        bot.reply_to(message, "❌ No URLs to index. Upload a file first!")
        return
    
    indexable_urls = user_data[chat_id]['indexable_urls']
    url_count = len(indexable_urls)
    
    if url_count == 0:
        bot.reply_to(message, "❌ No verified URLs to index!")
        return
    
    # DEDUCT CREDITS FIRST
    success, remaining, error_msg = deduct_credits(
        user_id, 
        url_count, 
        f"Indexing {url_count} URLs"
    )
    
    if not success:
        bot.reply_to(message, f"❌ {error_msg}\n\nUse /buy to purchase credits.")
        return
    
    # Notify user
    bot.send_message(
        chat_id,
        f"✅ **{url_count} credits deducted**\n"
        f"💰 Remaining: **{remaining} credits**\n\n"
        f"📤 Queue submitted! You'll be notified when complete.",
        parse_mode='Markdown'
    )
    
    try:
        # Use Celery for async processing
        from celery_worker import process_url_batch_with_notification
        
        # Prepare URLs with database IDs
        conn = get_db_connection()
        cursor = conn.cursor()
        
        urls_data = []
        for url in indexable_urls:
            cursor.execute("SELECT id FROM urls WHERE url = %s", (url,))
            result = cursor.fetchone()
            if result:
                urls_data.append((result[0], url))
        
        cursor.close()
        conn.close()
        
        # Submit to Celery queue
        task = process_url_batch_with_notification.delay(
            urls_data,
            user_id,
            INDEXING_PROVIDER
        )
        
        bot.send_message(
            chat_id,
            f"📋 Task ID: `{task.id}`\n\n"
            f"Your URLs are being processed in the background.\n"
            f"You'll receive a notification when complete!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Celery not available, using direct processing: {e}")
        
        # Fallback to direct processing if Celery is not available
        progress_msg = bot.send_message(
            chat_id,
            f"⏳ Submitting {url_count} URLs to Google..."
        )
        
        successful, failed = submit_urls_to_google(
            indexable_urls,
            chat_id,
            progress_msg.message_id,
            user_id
        )
        
        # Refund failed URLs
        failed_count = len(failed)
        if failed_count > 0:
            refund_credits(user_id, failed_count, f"Refund for {failed_count} failed URLs")
            remaining += failed_count
        
        try:
            bot.delete_message(chat_id, progress_msg.message_id)
        except:
            pass
        
        # Final report
        response = f"""
✅ **Indexing Complete!**

📤 Successfully Indexed: **{len(successful)}**
❌ Failed: **{failed_count}**
{'🔄 Refunded: **' + str(failed_count) + ' credits**' if failed_count > 0 else ''}
💰 Remaining Credits: **{remaining}**

⏰ URLs will appear in Google within 30 seconds to 24 hours.
Use /balance to check your credits.
"""
        
        bot.send_message(chat_id, response, parse_mode='Markdown')
    
    # Clear user data
    if chat_id in user_data:
        del user_data[chat_id]

# ==================== ADMIN COMMANDS ====================
# (Keep all your existing admin commands with rate limiting)

@bot.message_handler(commands=['addcredits'])
@rate_limit_decorator(rate_limiter, limit_type='command')
def admin_add_credits(message):
    # ... (existing code)
    pass

# ==================== STARTUP ====================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting Production URL Indexing Bot")
    print("=" * 60)
    
    # Initialize database
    print("🔧 Initializing database...")
    if init_database():
        print("✅ Main database ready!")
    
    # Initialize rate limiter
    from rate_limiter import init_rate_limit_tables
    print("🔧 Initializing rate limiter...")
    init_rate_limit_tables(DB_CONFIG)
    print("✅ Rate limiter ready!")
    
    # Initialize domain verifier
    from domain_verifier import init_verification_tables
    print("🔧 Initializing domain verifier...")
    init_verification_tables(DB_CONFIG)
    print("✅ Domain verifier ready!")
    
    # Verify Google API
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        print("✅ Google API service account file found")
    else:
        print("⚠️  WARNING: service-account.json not found!")
    
    # Check admin configuration
    if ADMIN_USER_IDS:
        print(f"✅ Admin users configured: {ADMIN_USER_IDS}")
    else:
        print("⚠️  WARNING: No admin users configured!")
    
    # Check encryption
    if os.path.exists('.env') and os.path.exists('.encryption_key'):
        print("✅ Secure configuration loaded")
    else:
        print("⚠️  WARNING: Run 'python secure_config.py setup' first!")
    
    print("=" * 60)
    print("✅ Bot is running with full production features:")
    print("   • Encrypted configuration")
    print("   • Rate limiting")
    print("   • Domain verification")
    print("   • Celery task queue (if available)")
    print("=" * 60)
    
    bot.polling(none_stop=True, interval=1)