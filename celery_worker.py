"""
Celery Worker for Background URL Processing
Handles indexing tasks asynchronously for better scalability
"""

from celery import Celery, Task
from celery.schedules import crontab
import redis
import time
from datetime import datetime
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import psycopg2
from secure_config import DB_CONFIG, SERVICE_ACCOUNT_FILE, RAPID_API_KEY

# ==================== CELERY CONFIGURATION ====================

# Redis as message broker
REDIS_URL = 'redis://localhost:6379/0'

app = Celery(
    'url_indexing_worker',
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
)

# ==================== DATABASE HELPER ====================

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG)

# ==================== INDEXING FUNCTIONS ====================

def get_indexing_service():
    """Initialize Google Indexing API"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/indexing"]
        )
        return build('indexing', 'v3', credentials=credentials)
    except Exception as e:
        print(f"Error initializing Google API: {e}")
        return None

def submit_single_url_to_google(url):
    """Submit a single URL to Google Indexing API"""
    service = get_indexing_service()
    if not service:
        return False, "Google API not configured"
    
    try:
        body = {"url": url, "type": "URL_UPDATED"}
        response = service.urlNotifications().publish(body=body).execute()
        return True, str(response)
    except Exception as e:
        return False, str(e)

def submit_single_url_to_rapid(url, api_key):
    """Submit a single URL to Rapid URL Indexer"""
    if not api_key:
        return False, "Rapid API key not configured"
    
    try:
        endpoint = "https://api.rapidurlindexer.com/v1/submit"
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        payload = {"urls": [url], "notify": False}
        
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return True, "Success"
        else:
            return False, f"API Error: {response.status_code}"
    except Exception as e:
        return False, str(e)

# ==================== CELERY TASKS ====================

@app.task(bind=True, name='index_single_url', max_retries=3)
def index_single_url(self, url_id, url, user_id, provider='google'):
    """
    Background task to index a single URL
    Retries up to 3 times on failure
    """
    print(f"📤 Processing URL {url_id}: {url}")
    
    try:
        # Submit to appropriate provider
        if provider == 'google':
            success, response = submit_single_url_to_google(url)
            time.sleep(0.5)  # Rate limiting
        elif provider == 'rapid':
            success, response = submit_single_url_to_rapid(url, RAPID_API_KEY)
            time.sleep(0.2)
        else:
            # Hybrid: Try Google first, then Rapid
            success, response = submit_single_url_to_google(url)
            if not success:
                success, response = submit_single_url_to_rapid(url, RAPID_API_KEY)
                provider = 'rapid'
            else:
                provider = 'google'
        
        # Save result to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        status = 'success' if success else 'failed'
        
        cursor.execute("""
            INSERT INTO indexing_requests 
            (url_id, user_id, status, indexing_provider, google_response, error_message, indexed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            url_id,
            user_id,
            status,
            provider,
            response if success else None,
            None if success else response,
            datetime.now() if success else None
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {'success': success, 'url': url, 'provider': provider}
        
    except Exception as e:
        print(f"❌ Error indexing URL {url}: {e}")
        
        # Retry with exponential backoff
        retry_delay = 2 ** self.request.retries  # 2, 4, 8 seconds
        raise self.retry(exc=e, countdown=retry_delay)

@app.task(name='index_url_batch')
def index_url_batch(urls_data, user_id, provider='google'):
    """
    Queue multiple URLs for indexing
    urls_data: List of tuples [(url_id, url), ...]
    """
    print(f"📦 Queueing {len(urls_data)} URLs for user {user_id}")
    
    # Create subtasks for each URL
    job = [
        index_single_url.s(url_id, url, user_id, provider)
        for url_id, url in urls_data
    ]
    
    # Execute tasks in parallel
    from celery import group
    result = group(job)()
    
    return {
        'total': len(urls_data),
        'user_id': user_id,
        'task_id': result.id
    }

@app.task(name='send_completion_notification')
def send_completion_notification(user_id, total_urls, successful, failed):
    """
    Send notification to user when batch processing completes
    """
    try:
        from telebot import TeleBot
        from secure_config import API_TOKEN
        
        bot = TeleBot(API_TOKEN)
        
        message = f"""
✅ **Batch Indexing Complete!**

📊 Results:
• Total URLs: {total_urls}
• Successful: {successful}
• Failed: {failed}

{'🔄 Failed URLs have been refunded.' if failed > 0 else ''}

Use /stats to view your history!
"""
        
        bot.send_message(user_id, message, parse_mode='Markdown')
        return True
        
    except Exception as e:
        print(f"Error sending notification: {e}")
        return False

@app.task(name='process_url_batch_with_notification')
def process_url_batch_with_notification(urls_data, user_id, provider='google'):
    """
    Process batch and send notification when complete
    """
    # Start indexing
    result = index_url_batch(urls_data, user_id, provider)
    
    # Wait for all tasks to complete (with timeout)
    from celery.result import GroupResult
    group_result = GroupResult.restore(result['task_id'])
    
    if group_result:
        # Wait max 1 hour
        results = group_result.get(timeout=3600)
        
        # Count successes and failures
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        
        # Refund failed URLs
        if failed > 0:
            refund_credits(user_id, failed, f"Refund for {failed} failed URLs")
        
        # Send notification
        send_completion_notification.delay(user_id, len(urls_data), successful, failed)
        
        return {
            'completed': True,
            'successful': successful,
            'failed': failed
        }
    
    return {'completed': False}

# ==================== PERIODIC TASKS ====================

@app.task(name='cleanup_old_tasks')
def cleanup_old_tasks():
    """Clean up old task results (run daily)"""
    try:
        # Delete task results older than 7 days
        from celery.result import AsyncResult
        # Implementation depends on backend
        print("🧹 Cleaning up old task results...")
        return True
    except Exception as e:
        print(f"Error cleaning up tasks: {e}")
        return False

@app.task(name='generate_daily_report')
def generate_daily_report():
    """Generate daily statistics report"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get yesterday's stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as active_users,
                COUNT(*) as total_requests,
                COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
            FROM indexing_requests
            WHERE DATE(submitted_at) = CURRENT_DATE - INTERVAL '1 day'
        """)
        
        stats = cursor.fetchone()
        cursor.close()
        conn.close()
        
        print(f"""
📊 Daily Report ({datetime.now().strftime('%Y-%m-%d')}):
   Active Users: {stats[0]}
   Total Requests: {stats[1]}
   Successful: {stats[2]}
   Failed: {stats[3]}
        """)
        
        return stats
        
    except Exception as e:
        print(f"Error generating report: {e}")
        return None

# ==================== PERIODIC TASK SCHEDULE ====================

app.conf.beat_schedule = {
    'cleanup-old-tasks-daily': {
        'task': 'cleanup_old_tasks',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
    },
    'generate-daily-report': {
        'task': 'generate_daily_report',
        'schedule': crontab(hour=1, minute=0),  # 1 AM daily
    },
}

# ==================== HELPER FUNCTION ====================

def refund_credits(user_id, amount, description):
    """Refund credits to user"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT credits FROM user_credits WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        balance_before = result[0] if result else 0
        balance_after = balance_before + amount
        
        cursor.execute("""
            UPDATE user_credits 
            SET credits = credits + %s, updated_at = %s
            WHERE user_id = %s
        """, (amount, datetime.now(), user_id))
        
        cursor.execute("""
            INSERT INTO credit_transactions 
            (user_id, transaction_type, amount, balance_before, balance_after, description)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, 'refund', amount, balance_before, balance_after, description))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error refunding credits: {e}")
        return False

# ==================== MONITORING ====================

@app.task(name='get_queue_stats')
def get_queue_stats():
    """Get current queue statistics"""
    try:
        inspect = app.control.inspect()
        
        stats = {
            'active': inspect.active(),
            'scheduled': inspect.scheduled(),
            'reserved': inspect.reserved(),
        }
        
        return stats
    except Exception as e:
        print(f"Error getting queue stats: {e}")
        return None

# ==================== STARTUP INFO ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Celery Worker for URL Indexing")
    print("=" * 60)
    print("\nTo start the worker:")
    print("  celery -A celery_worker worker --loglevel=info")
    print("\nTo start the scheduler (for periodic tasks):")
    print("  celery -A celery_worker beat --loglevel=info")
    print("\nTo monitor tasks:")
    print("  celery -A celery_worker flower")
    print("=" * 60)