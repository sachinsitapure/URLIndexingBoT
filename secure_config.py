"""
Secure Configuration Manager with Encryption
This replaces storing API keys in plain text
"""

import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import base64

# Load environment variables from .env file
load_dotenv()

class SecureConfig:
    """Secure configuration manager with encryption"""
    
    def __init__(self):
        # Generate or load encryption key
        self.key = self._get_or_create_key()
        self.cipher = Fernet(self.key)
    
    def _get_or_create_key(self):
        """Get existing encryption key or create new one"""
        key_file = '.encryption_key'
        
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            
            # Set file permissions (read-write for owner only)
            os.chmod(key_file, 0o600)
            print("🔐 New encryption key generated and saved to .encryption_key")
            return key
    
    def encrypt(self, plain_text):
        """Encrypt sensitive data"""
        if isinstance(plain_text, str):
            plain_text = plain_text.encode()
        return self.cipher.encrypt(plain_text).decode()
    
    def decrypt(self, encrypted_text):
        """Decrypt sensitive data"""
        if isinstance(encrypted_text, str):
            encrypted_text = encrypted_text.encode()
        return self.cipher.decrypt(encrypted_text).decode()
    
    def get_env(self, key, default=None, encrypted=False):
        """Get configuration value from environment"""
        value = os.getenv(key, default)
        if value and encrypted:
            try:
                return self.decrypt(value)
            except:
                # If decryption fails, return as-is (for backward compatibility)
                return value
        return value

# Initialize secure config
secure_config = SecureConfig()

# ==================== CONFIGURATION ====================

# Telegram Bot Token (from environment variable)
#API_TOKEN = secure_config.get_env('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_BOT_TOKEN='8217579466:AAEq0V9-0TtWqaphRbbBKj8_Suk-MVAy1no'
BOT_TOKEN='8217579466:AAEq0V9-0TtWqaphRbbBKj8_Suk-MVAy1no'
#API_TOKEN = secure_config.get_env('TELEGRAM_BOT_TOKEN', '')
API_TOKEN = secure_config.get_env('BOT_TOKEN', '')
# Database Configuration
DB_CONFIG = {
    'host': secure_config.get_env('DB_HOST', 'localhost'),
    'database': secure_config.get_env('DB_NAME', 'url_indexing'),
    'user': secure_config.get_env('DB_USER', 'postgres'),
    'password': secure_config.get_env('DB_PASSWORD', encrypted=True),
    'port': int(secure_config.get_env('DB_PORT', '5432'))
}

# Admin Configuration
ADMIN_USER_IDS_STR = secure_config.get_env('ADMIN_USER_IDS', '5888590867')
ADMIN_USER_IDS = [int(x.strip()) for x in ADMIN_USER_IDS_STR.split(',')]

# Third-Party API
RAPID_API_KEY = secure_config.get_env('RAPID_API_KEY', '', encrypted=True)
INDEXING_PROVIDER = secure_config.get_env('INDEXING_PROVIDER', 'google')

# Admin Panel Configuration
ADMIN_PANEL_PORT = int(secure_config.get_env('ADMIN_PANEL_PORT', '5000'))
ADMIN_PANEL_SECRET_KEY = secure_config.get_env('ADMIN_PANEL_SECRET_KEY', encrypted=True)
ADMIN_PANEL_USERNAME = secure_config.get_env('ADMIN_PANEL_USERNAME', 'admin')
ADMIN_PANEL_PASSWORD = secure_config.get_env('ADMIN_PANEL_PASSWORD', encrypted=True)

# Application Settings
FREE_CREDITS = int(secure_config.get_env('FREE_CREDITS', '5'))
MAX_URLS_PER_FILE = int(secure_config.get_env('MAX_URLS_PER_FILE', '1000'))
MAX_FILES_PER_HOUR = int(secure_config.get_env('MAX_FILES_PER_HOUR', '10'))

# Service Account File
SERVICE_ACCOUNT_FILE = secure_config.get_env('SERVICE_ACCOUNT_FILE', 'service-account.json')

# ==================== HELPER FUNCTIONS ====================

def encrypt_value(value):
    """Helper to encrypt a value for .env file"""
    return secure_config.encrypt(value)

def setup_env_file():
    """Interactive setup to create .env file with encrypted values"""
    print("=" * 60)
    print("🔐 SECURE CONFIGURATION SETUP")
    print("=" * 60)
    
    env_content = []
    
    # Telegram Bot Token
    print("\n1. Telegram Bot Token:")
    bot_token = input("   Enter your bot token (from @BotFather): ").strip()
    #env_content.append(f"TELEGRAM_BOT_TOKEN={bot_token}")
    bot_token='8217579466:AAEqOV9-0TtWqaphRbbBKj8_Suk-MVAy1no'
    env_content.append(f"TELEGRAM_BOT_TOKEN='8217579466:AAEqOV9-0TtWqaphRbbBKj8_Suk-MVAy1no'")
    
    # Database Configuration
    print("\n2. Database Configuration:")
    db_host = input("   Database host [localhost]: ").strip() or 'localhost'
    db_name = input("   Database name [url_indexing]: ").strip() or 'url_indexing'
    db_user = input("   Database user [postgres]: ").strip() or 'postgres'
    db_password = input("   Database password: ").strip()
    db_port = input("   Database port [5432]: ").strip() or '5432'
    
    env_content.append(f"DB_HOST={db_host}")
    env_content.append(f"DB_NAME={db_name}")
    env_content.append(f"DB_USER={db_user}")
    env_content.append(f"DB_PASSWORD={encrypt_value(db_password)}")
    env_content.append(f"DB_PORT={db_port}")
    
    # Admin User IDs
    print("\n3. Admin Configuration:")
    admin_ids = input("   Admin User IDs (comma-separated) [5888590867]: ").strip() or '5888590867'
    env_content.append(f"ADMIN_USER_IDS={admin_ids}")
    
    # Admin Panel
    print("\n4. Admin Panel Configuration:")
    panel_username = input("   Admin panel username [admin]: ").strip() or 'admin'
    panel_password = input("   Admin panel password: ").strip()
    panel_secret = input("   Secret key (press Enter to auto-generate): ").strip()
    
    if not panel_secret:
        import secrets
        panel_secret = secrets.token_urlsafe(32)
        print(f"   Generated secret key: {panel_secret}")
    
    env_content.append(f"ADMIN_PANEL_USERNAME={panel_username}")
    env_content.append(f"ADMIN_PANEL_PASSWORD={encrypt_value(panel_password)}")
    env_content.append(f"ADMIN_PANEL_SECRET_KEY={encrypt_value(panel_secret)}")
    env_content.append(f"ADMIN_PANEL_PORT=5000")
    
    # Optional: Rapid API
    print("\n5. Third-Party API (Optional):")
    use_rapid = input("   Use Rapid URL Indexer? (y/n) [n]: ").strip().lower()
    if use_rapid == 'y':
        rapid_key = input("   Rapid API Key: ").strip()
        env_content.append(f"RAPID_API_KEY={encrypt_value(rapid_key)}")
        env_content.append(f"INDEXING_PROVIDER=hybrid")
    else:
        env_content.append(f"RAPID_API_KEY=")
        env_content.append(f"INDEXING_PROVIDER=google")
    
    # Additional settings
    env_content.append(f"FREE_CREDITS=5")
    env_content.append(f"MAX_URLS_PER_FILE=1000")
    env_content.append(f"MAX_FILES_PER_HOUR=10")
    env_content.append(f"SERVICE_ACCOUNT_FILE=service-account.json")
    
    # Write to .env file
    with open('.env', 'w') as f:
        f.write('\n'.join(env_content))
    
    # Set file permissions
    os.chmod('.env', 0o600)
    
    print("\n" + "=" * 60)
    print("✅ Configuration saved to .env file (encrypted)")
    print("=" * 60)
    print("\n⚠️  IMPORTANT:")
    print("   1. Keep .env and .encryption_key files secure")
    print("   2. Add them to .gitignore")
    print("   3. Backup .encryption_key - you can't decrypt without it!")
    print("   4. Never commit these files to version control")
    print("=" * 60)

if __name__ == "__main__":
    # Run setup if executed directly
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        setup_env_file()
    elif len(sys.argv) > 1 and sys.argv[1] == 'encrypt':
        if len(sys.argv) < 3:
            print("Usage: python secure_config.py encrypt <value>")
        else:
            value = sys.argv[2]
            encrypted = encrypt_value(value)
            print(f"Encrypted value: {encrypted}")
    else:
        print("Usage:")
        print("  python secure_config.py setup          - Interactive setup")
        print("  python secure_config.py encrypt <val>  - Encrypt a value")