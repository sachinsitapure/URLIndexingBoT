"""
Admin Web Panel for URL Indexing Bot
Run with: python admin_panel.py
Access at: http://localhost:5000
"""

from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from config import DB_CONFIG, ADMIN_PANEL_PORT, ADMIN_PANEL_SECRET_KEY, ADMIN_PANEL_USERNAME, ADMIN_PANEL_PASSWORD
import psycopg2
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = ADMIN_PANEL_SECRET_KEY

# ==================== DATABASE FUNCTIONS ====================

def get_db_connection():
    """Create database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Database error: {e}")
        return None

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== ROUTES ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_PANEL_USERNAME and password == ADMIN_PANEL_PASSWORD:
            session['logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!', 'error')
    
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    """Main dashboard"""
    conn = get_db_connection()
    if not conn:
        return "Database connection failed"
    
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute("""
        SELECT 
            COUNT(*) as total_users,
            SUM(credits) as total_credits,
            SUM(total_used) as total_used,
            COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_users
        FROM user_credits
    """)
    stats = cursor.fetchone()
    
    # Get recent users
    cursor.execute("""
        SELECT user_id, username, credits, total_used, is_active, created_at
        FROM user_credits
        ORDER BY created_at DESC
        LIMIT 10
    """)
    recent_users = cursor.fetchall()
    
    # Get recent transactions
    cursor.execute("""
        SELECT ct.user_id, uc.username, ct.transaction_type, ct.amount, ct.description, ct.created_at
        FROM credit_transactions ct
        LEFT JOIN user_credits uc ON ct.user_id = uc.user_id
        ORDER BY ct.created_at DESC
        LIMIT 10
    """)
    recent_transactions = cursor.fetchall()
    
    # Get indexing stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_requests,
            COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
        FROM indexing_requests
    """)
    indexing_stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        stats=stats,
        recent_users=recent_users,
        recent_transactions=recent_transactions,
        indexing_stats=indexing_stats
    )

@app.route('/users')
@login_required
def users():
    """List all users"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT user_id, username, credits, total_purchased, total_used, plan_type, is_active, created_at
        FROM user_credits
        ORDER BY created_at DESC
    """)
    all_users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template_string(USERS_TEMPLATE, users=all_users)

@app.route('/user/<int:user_id>')
@login_required
def user_detail(user_id):
    """View user details"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user info
    cursor.execute("""
        SELECT user_id, username, credits, total_purchased, total_used, plan_type, is_active, created_at
        FROM user_credits
        WHERE user_id = %s
    """, (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        flash('User not found!', 'error')
        return redirect(url_for('users'))
    
    # Get transactions
    cursor.execute("""
        SELECT transaction_type, amount, balance_before, balance_after, description, created_at
        FROM credit_transactions
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    transactions = cursor.fetchall()
    
    # Get batch uploads
    cursor.execute("""
        SELECT file_name, total_urls, valid_urls, indexable_urls, credits_charged, uploaded_at
        FROM batch_uploads
        WHERE user_id = %s
        ORDER BY uploaded_at DESC
        LIMIT 10
    """, (user_id,))
    batches = cursor.fetchall()
    
    # Get indexing requests
    cursor.execute("""
        SELECT ir.status, ir.indexing_provider, ir.submitted_at, u.url
        FROM indexing_requests ir
        LEFT JOIN urls u ON ir.url_id = u.id
        WHERE ir.user_id = %s
        ORDER BY ir.submitted_at DESC
        LIMIT 10
    """, (user_id,))
    requests = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template_string(
        USER_DETAIL_TEMPLATE,
        user=user,
        transactions=transactions,
        batches=batches,
        requests=requests
    )

@app.route('/add_credits', methods=['GET', 'POST'])
@login_required
def add_credits():
    """Add credits to user"""
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        amount = request.form.get('amount')
        description = request.form.get('description', 'Admin credit addition')
        
        try:
            user_id = int(user_id)
            amount = int(amount)
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get current balance
            cursor.execute("SELECT credits FROM user_credits WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if not result:
                flash(f'User {user_id} not found!', 'error')
                return redirect(url_for('add_credits'))
            
            balance_before = result[0]
            balance_after = balance_before + amount
            
            # Update credits
            cursor.execute("""
                UPDATE user_credits 
                SET credits = credits + %s,
                    total_purchased = total_purchased + %s,
                    updated_at = %s
                WHERE user_id = %s
            """, (amount, amount, datetime.now(), user_id))
            
            # Log transaction
            cursor.execute("""
                INSERT INTO credit_transactions 
                (user_id, transaction_type, amount, balance_before, balance_after, description)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, 'purchase', amount, balance_before, balance_after, description))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash(f'Successfully added {amount} credits to user {user_id}!', 'success')
            return redirect(url_for('user_detail', user_id=user_id))
            
        except ValueError:
            flash('Invalid user ID or amount!', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template_string(ADD_CREDITS_TEMPLATE)

@app.route('/toggle_user/<int:user_id>')
@login_required
def toggle_user(user_id):
    """Enable/disable user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current status
    cursor.execute("SELECT is_active FROM user_credits WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        flash('User not found!', 'error')
        return redirect(url_for('users'))
    
    new_status = not result[0]
    
    # Update status
    cursor.execute("""
        UPDATE user_credits 
        SET is_active = %s, updated_at = %s
        WHERE user_id = %s
    """, (new_status, datetime.now(), user_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    status_text = 'enabled' if new_status else 'disabled'
    flash(f'User {user_id} {status_text}!', 'success')
    return redirect(url_for('user_detail', user_id=user_id))

@app.route('/transactions')
@login_required
def transactions():
    """View all transactions"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT ct.id, ct.user_id, uc.username, ct.transaction_type, ct.amount, 
               ct.balance_before, ct.balance_after, ct.description, ct.created_at
        FROM credit_transactions ct
        LEFT JOIN user_credits uc ON ct.user_id = uc.user_id
        ORDER BY ct.created_at DESC
        LIMIT 100
    """)
    all_transactions = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template_string(TRANSACTIONS_TEMPLATE, transactions=all_transactions)

@app.route('/stats')
@login_required
def stats():
    """View system statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Overall stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_users,
            SUM(credits) as available_credits,
            SUM(total_purchased) as total_purchased,
            SUM(total_used) as total_used,
            COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_users
        FROM user_credits
    """)
    overall = cursor.fetchone()
    
    # Indexing stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_requests,
            COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
            COUNT(CASE WHEN indexing_provider = 'google' THEN 1 END) as google_requests,
            COUNT(CASE WHEN indexing_provider = 'rapid' THEN 1 END) as rapid_requests
        FROM indexing_requests
    """)
    indexing = cursor.fetchone()
    
    # Today's stats
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT user_id) as active_today,
            COUNT(*) as transactions_today,
            SUM(CASE WHEN transaction_type = 'purchase' THEN amount ELSE 0 END) as credits_added_today,
            SUM(CASE WHEN transaction_type = 'deduction' THEN ABS(amount) ELSE 0 END) as credits_used_today
        FROM credit_transactions
        WHERE DATE(created_at) = CURRENT_DATE
    """)
    today = cursor.fetchone()
    
    # Top users
    cursor.execute("""
        SELECT user_id, username, total_used, credits
        FROM user_credits
        ORDER BY total_used DESC
        LIMIT 10
    """)
    top_users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template_string(
        STATS_TEMPLATE,
        overall=overall,
        indexing=indexing,
        today=today,
        top_users=top_users
    )

# ==================== HTML TEMPLATES ====================

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <style>
        body { font-family: Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); margin: 0; padding: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-container { max-width: 400px; width: 90%; background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
        h2 { text-align: center; color: #333; margin-bottom: 30px; font-size: 28px; }
        input { width: 100%; padding: 15px; margin: 10px 0; border: 2px solid #e0e0e0; border-radius: 8px; box-sizing: border-box; font-size: 14px; transition: border 0.3s; }
        input:focus { outline: none; border-color: #667eea; }
        button { width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; margin-top: 10px; transition: transform 0.2s; }
        button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4); }
        .flash { padding: 12px; margin: 10px 0; border-radius: 8px; font-size: 14px; }
        .flash.error { background: #fee; color: #c33; border: 1px solid #fcc; }
        .flash.success { background: #efe; color: #3c3; border: 1px solid #cfc; }
        .logo { text-align: center; font-size: 50px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">🔐</div>
        <h2>Admin Login</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required autofocus>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
'''

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .navbar h1 { font-size: 24px; font-weight: 600; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; font-size: 14px; transition: opacity 0.2s; }
        .navbar a:hover { opacity: 0.8; text-decoration: underline; }
        .container { max-width: 1400px; margin: 30px auto; padding: 0 20px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); transition: transform 0.2s; }
        .stat-card:hover { transform: translateY(-4px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
        .stat-card h3 { color: #666; font-size: 13px; font-weight: 500; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-card .number { font-size: 36px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .section h2 { margin-bottom: 20px; color: #333; font-size: 20px; font-weight: 600; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 14px 12px; text-align: left; border-bottom: 1px solid #e8e8e8; }
        th { background: #f9fafb; font-weight: 600; color: #333; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }
        tr:hover { background: #f9fafb; }
        td { font-size: 14px; color: #555; }
        .badge { padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
        .badge.success { background: #d4edda; color: #155724; }
        .badge.error { background: #f8d7da; color: #721c24; }
        .badge.active { background: #d1ecf1; color: #0c5460; }
        .badge.purchase { background: #d4edda; color: #155724; }
        .badge.deduction { background: #f8d7da; color: #721c24; }
        .flash { padding: 16px 20px; margin-bottom: 20px; border-radius: 8px; font-size: 14px; }
        .flash.success { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
        a { color: #667eea; text-decoration: none; font-weight: 500; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>🎛️ Admin Dashboard</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('add_credits') }}">Add Credits</a>
            <a href="{{ url_for('transactions') }}">Transactions</a>
            <a href="{{ url_for('stats') }}">Statistics</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Users</h3>
                <div class="number">{{ stats[0] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Active Users</h3>
                <div class="number">{{ stats[3] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Available Credits</h3>
                <div class="number">{{ stats[1] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Credits Used</h3>
                <div class="number">{{ stats[2] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Total Requests</h3>
                <div class="number">{{ indexing_stats[0] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Successful</h3>
                <div class="number" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">{{ indexing_stats[1] or 0 }}</div>
            </div>
        </div>
        
        <div class="section">
            <h2>Recent Users</h2>
            <table>
                <tr>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Credits</th>
                    <th>Used</th>
                    <th>Status</th>
                    <th>Joined</th>
                    <th>Actions</th>
                </tr>
                {% for user in recent_users %}
                <tr>
                    <td><strong>{{ user[0] }}</strong></td>
                    <td>@{{ user[1] or 'N/A' }}</td>
                    <td><strong>{{ user[2] }}</strong></td>
                    <td>{{ user[3] }}</td>
                    <td>
                        {% if user[4] %}
                            <span class="badge success">Active</span>
                        {% else %}
                            <span class="badge error">Disabled</span>
                        {% endif %}
                    </td>
                    <td>{{ user[5].strftime('%Y-%m-%d %H:%M') }}</td>
                    <td><a href="{{ url_for('user_detail', user_id=user[0]) }}">View</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2>Recent Transactions</h2>
            <table>
                <tr>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Description</th>
                    <th>Date</th>
                </tr>
                {% for trans in recent_transactions %}
                <tr>
                    <td>{{ trans[0] }}</td>
                    <td>@{{ trans[1] or 'N/A' }}</td>
                    <td><span class="badge {{ trans[2] }}">{{ trans[2] }}</span></td>
                    <td><strong>{{ trans[3] }}</strong></td>
                    <td>{{ trans[4][:50] }}...</td>
                    <td>{{ trans[5].strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

USERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>All Users</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .navbar h1 { font-size: 24px; font-weight: 600; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; font-size: 14px; }
        .container { max-width: 1400px; margin: 30px auto; padding: 0 20px; }
        .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 14px 12px; text-align: left; border-bottom: 1px solid #e8e8e8; font-size: 14px; }
        th { background: #f9fafb; font-weight: 600; color: #333; }
        tr:hover { background: #f9fafb; }
        .badge { padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; }
        .badge.success { background: #d4edda; color: #155724; }
        .badge.error { background: #f8d7da; color: #721c24; }
        a { color: #667eea; text-decoration: none; font-weight: 500; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>👥 All Users</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('add_credits') }}">Add Credits</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <div class="section">
            <h2 style="margin-bottom: 20px; color: #333;">Total Users: {{ users|length }}</h2>
            <table>
                <tr>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Credits</th>
                    <th>Purchased</th>
                    <th>Used</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th>Joined</th>
                    <th>Actions</th>
                </tr>
                {% for user in users %}
                <tr>
                    <td><strong>{{ user[0] }}</strong></td>
                    <td>@{{ user[1] or 'N/A' }}</td>
                    <td><strong style="color: #667eea;">{{ user[2] }}</strong></td>
                    <td>{{ user[3] }}</td>
                    <td>{{ user[4] }}</td>
                    <td>{{ user[5] }}</td>
                    <td>
                        {% if user[6] %}
                            <span class="badge success">Active</span>
                        {% else %}
                            <span class="badge error">Disabled</span>
                        {% endif %}
                    </td>
                    <td>{{ user[7].strftime('%Y-%m-%d') }}</td>
                    <td><a href="{{ url_for('user_detail', user_id=user[0]) }}">View Details</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

USER_DETAIL_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>User Details</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }
        .navbar h1 { font-size: 24px; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; }
        .container { max-width: 1400px; margin: 30px auto; padding: 0 20px; }
        .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .section h2 { margin-bottom: 20px; color: #333; font-size: 20px; }
        .user-info { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .info-item { padding: 15px; background: #f9fafb; border-radius: 8px; }
        .info-item label { font-size: 11px; color: #666; display: block; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px; }
        .info-item .value { font-size: 20px; font-weight: bold; color: #667eea; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e8e8e8; font-size: 13px; }
        th { background: #f9fafb; font-weight: 600; }
        .btn { display: inline-block; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 6px; margin-right: 10px; font-size: 14px; font-weight: 500; transition: background 0.2s; }
        .btn:hover { background: #5568d3; }
        .btn-danger { background: #dc3545; }
        .btn-danger:hover { background: #c82333; }
        .btn-success { background: #28a745; }
        .btn-success:hover { background: #218838; }
        .badge { padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; }
        .badge.success { background: #d4edda; color: #155724; }
        .badge.error { background: #f8d7da; color: #721c24; }
        .flash { padding: 15px; margin-bottom: 20px; border-radius: 8px; }
        .flash.success { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>👤 User Details</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('add_credits') }}">Add Credits</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="section">
            <h2>User Information</h2>
            <div class="user-info">
                <div class="info-item">
                    <label>User ID</label>
                    <div class="value">{{ user[0] }}</div>
                </div>
                <div class="info-item">
                    <label>Username</label>
                    <div class="value" style="font-size: 16px;">@{{ user[1] or 'N/A' }}</div>
                </div>
                <div class="info-item">
                    <label>Current Credits</label>
                    <div class="value">{{ user[2] }}</div>
                </div>
                <div class="info-item">
                    <label>Total Purchased</label>
                    <div class="value">{{ user[3] }}</div>
                </div>
                <div class="info-item">
                    <label>Total Used</label>
                    <div class="value">{{ user[4] }}</div>
                </div>
                <div class="info-item">
                    <label>Plan Type</label>
                    <div class="value" style="font-size: 16px;">{{ user[5] }}</div>
                </div>
                <div class="info-item">
                    <label>Status</label>
                    <div class="value" style="font-size: 14px;">
                        {% if user[6] %}
                            <span class="badge success">Active</span>
                        {% else %}
                            <span class="badge error">Disabled</span>
                        {% endif %}
                    </div>
                </div>
                <div class="info-item">
                    <label>Joined</label>
                    <div class="value" style="font-size: 14px;">{{ user[7].strftime('%Y-%m-%d %H:%M') }}</div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <a href="{{ url_for('add_credits') }}?user_id={{ user[0] }}" class="btn">Add Credits</a>
                {% if user[6] %}
                    <a href="{{ url_for('toggle_user', user_id=user[0]) }}" class="btn btn-danger">Disable User</a>
                {% else %}
                    <a href="{{ url_for('toggle_user', user_id=user[0]) }}" class="btn btn-success">Enable User</a>
                {% endif %}
            </div>
        </div>
        
        <div class="section">
            <h2>Recent Transactions</h2>
            <table>
                <tr>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Before</th>
                    <th>After</th>
                    <th>Description</th>
                    <th>Date</th>
                </tr>
                {% for trans in transactions %}
                <tr>
                    <td><span class="badge {{ 'success' if trans[0] == 'purchase' or trans[0] == 'refund' else 'error' }}">{{ trans[0] }}</span></td>
                    <td><strong>{{ trans[1] }}</strong></td>
                    <td>{{ trans[2] }}</td>
                    <td>{{ trans[3] }}</td>
                    <td>{{ trans[4] }}</td>
                    <td>{{ trans[5].strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="6" style="text-align: center; color: #999;">No transactions yet</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2>Batch Uploads</h2>
            <table>
                <tr>
                    <th>File Name</th>
                    <th>Total URLs</th>
                    <th>Valid</th>
                    <th>Indexable</th>
                    <th>Credits Charged</th>
                    <th>Date</th>
                </tr>
                {% for batch in batches %}
                <tr>
                    <td>{{ batch[0] }}</td>
                    <td>{{ batch[1] }}</td>
                    <td>{{ batch[2] }}</td>
                    <td>{{ batch[3] }}</td>
                    <td><strong>{{ batch[4] }}</strong></td>
                    <td>{{ batch[5].strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="6" style="text-align: center; color: #999;">No uploads yet</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2>Recent Indexing Requests</h2>
            <table>
                <tr>
                    <th>Status</th>
                    <th>Provider</th>
                    <th>URL</th>
                    <th>Submitted</th>
                </tr>
                {% for req in requests %}
                <tr>
                    <td><span class="badge {{ 'success' if req[0] == 'success' else 'error' }}">{{ req[0] }}</span></td>
                    <td>{{ req[1] }}</td>
                    <td style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ req[3] }}</td>
                    <td>{{ req[2].strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="4" style="text-align: center; color: #999;">No indexing requests yet</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

ADD_CREDITS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Add Credits</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }
        .navbar h1 { font-size: 24px; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; }
        .container { max-width: 600px; margin: 50px auto; padding: 0 20px; }
        .section { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .section h2 { margin-bottom: 25px; color: #333; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 8px; color: #333; font-weight: 600; font-size: 14px; }
        .form-group input, .form-group textarea { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 14px; transition: border 0.2s; }
        .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #667eea; }
        .form-group textarea { resize: vertical; min-height: 80px; font-family: inherit; }
        .btn { padding: 14px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; width: 100%; font-weight: 600; transition: transform 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); }
        .flash { padding: 15px; margin-bottom: 20px; border-radius: 8px; }
        .flash.success { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
        .flash.error { background: #f8d7da; color: #721c24; border-left: 4px solid #dc3545; }
        .info-box { background: #e7f3ff; border-left: 4px solid #667eea; padding: 15px; margin-bottom: 20px; border-radius: 8px; }
        .info-box h4 { margin-bottom: 10px; color: #667eea; font-size: 14px; }
        .info-box p { margin: 5px 0; color: #333; font-size: 13px; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>💳 Add Credits</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('add_credits') }}">Add Credits</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="section">
            <h2>Add Credits to User</h2>
            
            <div class="info-box">
                <h4>ℹ️ How to get User ID:</h4>
                <p>1. User sends /start to the bot</p>
                <p>2. Use /checkuser command in Telegram</p>
                <p>3. Check admin dashboard for user list</p>
                <p>4. User can find their ID in bot's welcome message</p>
            </div>
            
            <form method="POST">
                <div class="form-group">
                    <label>User ID *</label>
                    <input type="number" name="user_id" placeholder="e.g., 123456789" required 
                           value="{{ request.args.get('user_id', '') }}">
                </div>
                
                <div class="form-group">
                    <label>Amount of Credits *</label>
                    <input type="number" name="amount" placeholder="e.g., 100" required min="1" value="100">
                </div>
                
                <div class="form-group">
                    <label>Description (Optional)</label>
                    <textarea name="description" placeholder="e.g., Payment received via PayPal - Transaction ID: ABC123">Admin credit addition</textarea>
                </div>
                
                <button type="submit" class="btn">Add Credits</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

TRANSACTIONS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>All Transactions</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }
        .navbar h1 { font-size: 24px; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; }
        .container { max-width: 1400px; margin: 30px auto; padding: 0 20px; }
        .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .section h2 { margin-bottom: 20px; color: #333; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e8e8e8; }
        th { background: #f9fafb; font-weight: 600; }
        tr:hover { background: #f9fafb; }
        .badge { padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
        .badge.purchase { background: #d4edda; color: #155724; }
        .badge.deduction { background: #f8d7da; color: #721c24; }
        .badge.refund { background: #fff3cd; color: #856404; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>💰 All Transactions</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('add_credits') }}">Add Credits</a>
            <a href="{{ url_for('transactions') }}">Transactions</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <div class="section">
            <h2>Transaction History (Last 100)</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Before</th>
                    <th>After</th>
                    <th>Description</th>
                    <th>Date</th>
                </tr>
                {% for trans in transactions %}
                <tr>
                    <td>{{ trans[0] }}</td>
                    <td><strong>{{ trans[1] }}</strong></td>
                    <td>@{{ trans[2] or 'N/A' }}</td>
                    <td><span class="badge {{ trans[3] }}">{{ trans[3] }}</span></td>
                    <td><strong>{{ trans[4] }}</strong></td>
                    <td>{{ trans[5] }}</td>
                    <td>{{ trans[6] }}</td>
                    <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">{{ trans[7] }}</td>
                    <td>{{ trans[8].strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

STATS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>System Statistics</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }
        .navbar h1 { font-size: 24px; }
        .navbar a { color: white; text-decoration: none; margin-left: 25px; }
        .container { max-width: 1400px; margin: 30px auto; padding: 0 20px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .stat-card h3 { color: #666; font-size: 13px; margin-bottom: 10px; text-transform: uppercase; }
        .stat-card .number { font-size: 36px; font-weight: bold; color: #667eea; }
        .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .section h2 { margin-bottom: 20px; color: #333; font-size: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 14px 12px; text-align: left; border-bottom: 1px solid #e8e8e8; }
        th { background: #f9fafb; font-weight: 600; }
        tr:hover { background: #f9fafb; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>📊 System Statistics</h1>
        <div>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('users') }}">Users</a>
            <a href="{{ url_for('stats') }}">Statistics</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <h2 style="margin-bottom: 20px; color: #333;">Overall Statistics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Users</h3>
                <div class="number">{{ overall[0] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Active Users</h3>
                <div class="number">{{ overall[4] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Available Credits</h3>
                <div class="number">{{ overall[1] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Total Purchased</h3>
                <div class="number">{{ overall[2] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Total Used</h3>
                <div class="number">{{ overall[3] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Revenue Potential</h3>
                <div class="number" style="font-size: 24px;">${{ ((overall[3] or 0) * 0.10)|round(2) }}</div>
            </div>
        </div>
        
        <h2 style="margin: 30px 0 20px 0; color: #333;">Indexing Statistics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Requests</h3>
                <div class="number">{{ indexing[0] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Successful</h3>
                <div class="number" style="color: #28a745;">{{ indexing[1] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Failed</h3>
                <div class="number" style="color: #dc3545;">{{ indexing[2] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Google API</h3>
                <div class="number">{{ indexing[3] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Rapid API</h3>
                <div class="number">{{ indexing[4] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Success Rate</h3>
                <div class="number" style="font-size: 28px;">
                    {% if indexing[0] and indexing[0] > 0 %}
                        {{ ((indexing[1] / indexing[0]) * 100)|round(1) }}%
                    {% else %}
                        0%
                    {% endif %}
                </div>
            </div>
        </div>
        
        <h2 style="margin: 30px 0 20px 0; color: #333;">Today's Activity</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Active Users Today</h3>
                <div class="number">{{ today[0] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Transactions Today</h3>
                <div class="number">{{ today[1] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Credits Added</h3>
                <div class="number" style="color: #28a745;">{{ today[2] or 0 }}</div>
            </div>
            <div class="stat-card">
                <h3>Credits Used</h3>
                <div class="number" style="color: #dc3545;">{{ today[3] or 0 }}</div>
            </div>
        </div>
        
        <div class="section">
            <h2>Top Users by Usage</h2>
            <table>
                <tr>
                    <th>Rank</th>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Total Credits Used</th>
                    <th>Current Balance</th>
                </tr>
                {% for user in top_users %}
                <tr>
                    <td><strong>#{{ loop.index }}</strong></td>
                    <td>{{ user[0] }}</td>
                    <td>@{{ user[1] or 'N/A' }}</td>
                    <td><strong style="color: #667eea;">{{ user[2] }}</strong></td>
                    <td>{{ user[3] }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    print("=" * 50)
    print("🎛️  Admin Panel Starting...")
    print("=" * 50)
    print(f"📍 URL: http://localhost:{ADMIN_PANEL_PORT}")
    print(f"👤 Username: {ADMIN_PANEL_USERNAME}")
    print(f"🔑 Password: {ADMIN_PANEL_PASSWORD}")
    print("=" * 50)
    print("⚠️  IMPORTANT: Change default password in config.py!")
    print("=" * 50)
    
    app.run(
        host='0.0.0.0',
        port=ADMIN_PANEL_PORT,
        debug=True
    )