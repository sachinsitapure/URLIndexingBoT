from bot_integrated import init_database
from rate_limiter import init_rate_limit_tables
from domain_verifier import init_verification_tables
from secure_config import DB_CONFIG

print("🔧 Initializing database tables...")

print("1. Creating main tables...")
init_database()

print("2. Creating rate limiter tables...")
init_rate_limit_tables(DB_CONFIG)

print("3. Creating verification tables...")
init_verification_tables(DB_CONFIG)

print("✅ All tables initialized successfully!")