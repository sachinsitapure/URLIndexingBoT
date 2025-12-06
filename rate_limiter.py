"""
Rate Limiter - Prevent Abuse and Control API Usage
Implements multiple rate limiting strategies
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
import psycopg2

class RateLimiter:
    """Advanced rate limiter with multiple strategies"""
    
    def __init__(self, db_config):
        self.db_config = db_config
        # In-memory storage for rate limiting
        self.user_requests = defaultdict(lambda: deque(maxlen=100))
        self.user_file_uploads = defaultdict(lambda: deque(maxlen=50))
        self.user_api_calls = defaultdict(lambda: deque(maxlen=500))
        
        # Rate limit configurations
        self.limits = {
            'files_per_hour': 10,      # Max file uploads per hour
            'urls_per_day': 1000,       # Max URLs per day
            'api_calls_per_minute': 20, # Max API calls per minute
            'commands_per_minute': 30   # Max bot commands per minute
        }
    
    def _clean_old_entries(self, queue, time_window):
        """Remove entries older than time_window seconds"""
        cutoff_time = time.time() - time_window
        while queue and queue[0] < cutoff_time:
            queue.popleft()
    
    def check_file_upload_limit(self, user_id):
        """
        Check if user can upload a file
        Limit: 10 files per hour
        """
        current_time = time.time()
        queue = self.user_file_uploads[user_id]
        
        # Clean old entries (older than 1 hour)
        self._clean_old_entries(queue, 3600)
        
        # Check limit
        if len(queue) >= self.limits['files_per_hour']:
            # Calculate when user can upload again
            oldest_upload = queue[0]
            wait_time = int(3600 - (current_time - oldest_upload))
            return False, wait_time
        
        # Add current upload
        queue.append(current_time)
        return True, 0
    
    def check_url_limit(self, user_id, url_count):
        """
        Check if user can process this many URLs today
        Limit: 1000 URLs per day
        """
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        # Count URLs processed today
        cursor.execute("""
            SELECT COALESCE(SUM(indexable_urls), 0)
            FROM batch_uploads
            WHERE user_id = %s 
            AND DATE(uploaded_at) = CURRENT_DATE
        """, (user_id,))
        
        today_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        
        # Check if adding new URLs would exceed limit
        if today_count + url_count > self.limits['urls_per_day']:
            remaining = self.limits['urls_per_day'] - today_count
            return False, remaining
        
        return True, self.limits['urls_per_day'] - (today_count + url_count)
    
    def check_api_call_limit(self, user_id):
        """
        Check if user can make API calls
        Limit: 20 calls per minute
        """
        current_time = time.time()
        queue = self.user_api_calls[user_id]
        
        # Clean old entries (older than 1 minute)
        self._clean_old_entries(queue, 60)
        
        # Check limit
        if len(queue) >= self.limits['api_calls_per_minute']:
            wait_time = int(60 - (current_time - queue[0]))
            return False, wait_time
        
        # Add current call
        queue.append(current_time)
        return True, 0
    
    def check_command_limit(self, user_id):
        """
        Check if user can send commands
        Limit: 30 commands per minute
        """
        current_time = time.time()
        queue = self.user_requests[user_id]
        
        # Clean old entries (older than 1 minute)
        self._clean_old_entries(queue, 60)
        
        # Check limit
        if len(queue) >= self.limits['commands_per_minute']:
            wait_time = int(60 - (current_time - queue[0]))
            return False, wait_time
        
        # Add current command
        queue.append(current_time)
        return True, 0
    
    def log_rate_limit_violation(self, user_id, limit_type, db_config):
        """Log rate limit violations for monitoring"""
        try:
            conn = psycopg2.connect(**db_config)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO rate_limit_violations 
                (user_id, violation_type, violated_at)
                VALUES (%s, %s, %s)
            """, (user_id, limit_type, datetime.now()))
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error logging rate limit violation: {e}")

# ==================== DECORATORS ====================

def rate_limit_decorator(limiter, limit_type='command'):
    """Decorator to apply rate limiting to bot handlers"""
    def decorator(func):
        @wraps(func)
        def wrapper(message, *args, **kwargs):
            user_id = message.from_user.id
            
            # Check appropriate limit based on type
            if limit_type == 'command':
                allowed, wait_time = limiter.check_command_limit(user_id)
            elif limit_type == 'file':
                allowed, wait_time = limiter.check_file_upload_limit(user_id)
            elif limit_type == 'api':
                allowed, wait_time = limiter.check_api_call_limit(user_id)
            else:
                allowed, wait_time = True, 0
            
            if not allowed:
                from telebot import TeleBot
                bot = TeleBot(token=message.bot.token)
                
                if limit_type == 'file':
                    response = f"""
⚠️ **Rate Limit Exceeded**

You've reached the maximum of {limiter.limits['files_per_hour']} file uploads per hour.

⏰ Try again in: **{wait_time // 60} minutes {wait_time % 60} seconds**

💡 Tip: Combine multiple URLs into one file to save uploads!
"""
                else:
                    response = f"""
⚠️ **Slow Down!**

You're sending commands too quickly.
Please wait **{wait_time} seconds** before trying again.
"""
                
                bot.reply_to(message, response, parse_mode='Markdown')
                
                # Log violation
                limiter.log_rate_limit_violation(user_id, limit_type, limiter.db_config)
                return
            
            # Execute original function
            return func(message, *args, **kwargs)
        
        return wrapper
    return decorator

# ==================== DATABASE SCHEMA ====================

def init_rate_limit_tables(db_config):
    """Initialize rate limiting tables"""
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Create rate limit violations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_violations (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            violation_type VARCHAR(50),
            violated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes separately
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_violations_user ON rate_limit_violations(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_violations_date ON rate_limit_violations(violated_at)
    """)
    
    # Create rate limit configuration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_config (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            files_per_hour INTEGER DEFAULT 10,
            urls_per_day INTEGER DEFAULT 1000,
            api_calls_per_minute INTEGER DEFAULT 20,
            is_premium BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Rate limiting tables initialized")

# ==================== ADMIN FUNCTIONS ====================

def set_custom_limits(user_id, db_config, **limits):
    """Set custom rate limits for a user (e.g., premium users)"""
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Build update query
    fields = []
    values = []
    
    if 'files_per_hour' in limits:
        fields.append('files_per_hour = %s')
        values.append(limits['files_per_hour'])
    
    if 'urls_per_day' in limits:
        fields.append('urls_per_day = %s')
        values.append(limits['urls_per_day'])
    
    if 'api_calls_per_minute' in limits:
        fields.append('api_calls_per_minute = %s')
        values.append(limits['api_calls_per_minute'])
    
    if 'is_premium' in limits:
        fields.append('is_premium = %s')
        values.append(limits['is_premium'])
    
    values.append(datetime.now())
    values.append(user_id)
    
    cursor.execute(f"""
        INSERT INTO rate_limit_config 
        (user_id, {', '.join([f.split('=')[0].strip() for f in fields])}, updated_at)
        VALUES (%s, {', '.join(['%s'] * len(fields))}, %s)
        ON CONFLICT (user_id) 
        DO UPDATE SET {', '.join(fields)}, updated_at = %s
    """, [user_id] + values + [datetime.now()])
    
    conn.commit()
    cursor.close()
    conn.close()

def get_rate_limit_stats(user_id, db_config):
    """Get rate limit statistics for a user"""
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Get today's usage
    cursor.execute("""
        SELECT 
            COUNT(*) as uploads_today,
            COALESCE(SUM(indexable_urls), 0) as urls_today
        FROM batch_uploads
        WHERE user_id = %s 
        AND DATE(uploaded_at) = CURRENT_DATE
    """, (user_id,))
    
    today_stats = cursor.fetchone()
    
    # Get violations
    cursor.execute("""
        SELECT COUNT(*) 
        FROM rate_limit_violations
        WHERE user_id = %s 
        AND DATE(violated_at) = CURRENT_DATE
    """, (user_id,))
    
    violations_today = cursor.fetchone()[0]
    
    # Get custom limits if any
    cursor.execute("""
        SELECT files_per_hour, urls_per_day, is_premium
        FROM rate_limit_config
        WHERE user_id = %s
    """, (user_id,))
    
    custom_limits = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return {
        'uploads_today': today_stats[0],
        'urls_today': today_stats[1],
        'violations_today': violations_today,
        'custom_limits': custom_limits
    }

# ==================== USAGE EXAMPLE ====================

if __name__ == "__main__":
    # Example configuration
    DB_CONFIG = {
        'host': 'localhost',
        'database': 'url_indexing',
        'user': 'postgres',
        'password': 'postgres',
        'port': 5432
    }
    
    # Initialize tables
    print("Initializing rate limiting system...")
    init_rate_limit_tables(DB_CONFIG)
    
    # Create rate limiter
    limiter = RateLimiter(DB_CONFIG)
    
    # Example: Check if user can upload
    user_id = 123456789
    allowed, wait_time = limiter.check_file_upload_limit(user_id)
    
    if allowed:
        print(f"✅ User {user_id} can upload")
    else:
        print(f"❌ User {user_id} must wait {wait_time} seconds")
    
    # Example: Set premium limits
    set_custom_limits(
        user_id,
        DB_CONFIG,
        files_per_hour=50,
        urls_per_day=10000,
        is_premium=True
    )
    print(f"✅ Premium limits set for user {user_id}")
    
    # Example: Get stats
    stats = get_rate_limit_stats(user_id, DB_CONFIG)
    print(f"📊 Stats for user {user_id}:")
    print(f"   Uploads today: {stats['uploads_today']}")
    print(f"   URLs today: {stats['urls_today']}")
    print(f"   Violations: {stats['violations_today']}")