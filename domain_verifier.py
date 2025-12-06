"""
Domain Verification Checker
Verifies if domains are registered in Google Search Console
before attempting to index URLs
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
from urllib.parse import urlparse
import psycopg2
from datetime import datetime, timedelta
from secure_config import DB_CONFIG, SERVICE_ACCOUNT_FILE

class DomainVerifier:
    """Check and cache domain verification status"""
    
    def __init__(self, service_account_file):
        self.service_account_file = service_account_file
        self.search_console_service = None
        self._init_search_console()
    
    def _init_search_console(self):
        """Initialize Google Search Console API"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=['https://www.googleapis.com/auth/webmasters.readonly']
            )
            self.search_console_service = build(
                'searchconsole', 
                'v1', 
                credentials=credentials
            )
        except Exception as e:
            print(f"❌ Error initializing Search Console API: {e}")
            self.search_console_service = None
    
    def get_verified_domains(self):
        """Get list of all verified domains from Search Console"""
        if not self.search_console_service:
            return []
        
        try:
            sites = self.search_console_service.sites().list().execute()
            
            verified_domains = []
            if 'siteEntry' in sites:
                for site in sites['siteEntry']:
                    # Extract domain from siteUrl
                    site_url = site['siteUrl']
                    
                    # Handle both domain properties and URL properties
                    if site_url.startswith('sc-domain:'):
                        domain = site_url.replace('sc-domain:', '')
                    else:
                        parsed = urlparse(site_url)
                        domain = parsed.netloc
                    
                    verified_domains.append({
                        'domain': domain,
                        'site_url': site_url,
                        'permission_level': site.get('permissionLevel', 'unknown')
                    })
            
            return verified_domains
            
        except Exception as e:
            print(f"❌ Error fetching verified domains: {e}")
            return []
    
    def is_domain_verified(self, url):
        """Check if a URL's domain is verified in Search Console"""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Check cache first
        cached = self._get_cached_verification(domain)
        if cached is not None:
            return cached
        
        # Get verified domains
        verified_domains = self.get_verified_domains()
        
        # Check if domain is in verified list
        is_verified = any(
            domain == vd['domain'] or domain.endswith('.' + vd['domain'])
            for vd in verified_domains
        )
        
        # Cache result
        self._cache_verification(domain, is_verified)
        
        return is_verified
    
    def _get_cached_verification(self, domain):
        """Get cached verification status"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            # Check if we have a recent cache entry (less than 24 hours old)
            cursor.execute("""
                SELECT is_verified 
                FROM domain_verification_cache
                WHERE domain = %s 
                AND checked_at > NOW() - INTERVAL '24 hours'
                ORDER BY checked_at DESC
                LIMIT 1
            """, (domain,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            return result[0] if result else None
            
        except Exception as e:
            print(f"Error checking verification cache: {e}")
            return None
    
    def _cache_verification(self, domain, is_verified):
        """Cache verification status"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO domain_verification_cache 
                (domain, is_verified, checked_at)
                VALUES (%s, %s, %s)
            """, (domain, is_verified, datetime.now()))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Error caching verification: {e}")
    
    def check_batch_verification(self, urls):
        """Check verification for a batch of URLs"""
        results = {}
        domains_to_check = set()
        
        # Extract unique domains
        for url in urls:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain:
                domains_to_check.add(domain)
        
        # Get all verified domains once
        verified_domains = self.get_verified_domains()
        verified_set = set(vd['domain'] for vd in verified_domains)
        
        # Check each domain
        for domain in domains_to_check:
            is_verified = (
                domain in verified_set or 
                any(domain.endswith('.' + vd) for vd in verified_set)
            )
            results[domain] = is_verified
            
            # Cache the result
            self._cache_verification(domain, is_verified)
        
        return results
    
    def get_verification_instructions(self, domain):
        """Get instructions for verifying a domain"""
        return f"""
📋 **Domain Verification Instructions for: {domain}**

To verify your domain in Google Search Console:

**Method 1: HTML File Upload**
1. Go to: https://search.google.com/search-console
2. Click "Add Property"
3. Choose "URL prefix" and enter: https://{domain}
4. Select "HTML file" verification method
5. Download the verification file
6. Upload it to your website root: https://{domain}/google-verification-file.html
7. Click "Verify"

**Method 2: DNS Verification**
1. Go to: https://search.google.com/search-console
2. Click "Add Property"
3. Choose "Domain" and enter: {domain}
4. Copy the TXT record provided
5. Add it to your DNS settings
6. Wait for DNS propagation (can take up to 48 hours)
7. Click "Verify"

**Method 3: Service Account (Recommended for API)**
1. Your service account email is in: service-account.json
2. Copy the "client_email" value
3. Go to Search Console: https://search.google.com/search-console
4. Select your property
5. Go to Settings → Users and permissions
6. Add the service account email as "Owner"
7. Domain will be automatically verified for API access

**Need Help?**
Visit: https://support.google.com/webmasters/answer/9008080
"""

# ==================== DATABASE SCHEMA ====================

def init_verification_tables(db_config):
    """Initialize domain verification tables"""
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Create verification cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_verification_cache (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(255) NOT NULL,
            is_verified BOOLEAN NOT NULL,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes separately
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_domain_cache ON domain_verification_cache(domain)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_checked_at ON domain_verification_cache(checked_at)
    """)
    
    # Create verification failures table (for reporting)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_failures (
            id SERIAL PRIMARY KEY,
            url TEXT NOT NULL,
            domain VARCHAR(255) NOT NULL,
            user_id BIGINT NOT NULL,
            failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified BOOLEAN DEFAULT FALSE
        )
    """)
    
    # Create indexes separately
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_verification_failures_user ON verification_failures(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_verification_failures_domain ON verification_failures(domain)
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Domain verification tables initialized")
# ==================== HELPER FUNCTIONS ====================

def check_url_verification(url, service_account_file=SERVICE_ACCOUNT_FILE):
    """Quick check if a single URL's domain is verified"""
    verifier = DomainVerifier(service_account_file)
    return verifier.is_domain_verified(url)

def filter_verified_urls(urls, service_account_file=SERVICE_ACCOUNT_FILE):
    """
    Filter URLs to only include verified domains
    Returns: (verified_urls, unverified_urls)
    """
    verifier = DomainVerifier(service_account_file)
    
    # Get verification status for all domains
    domain_status = verifier.check_batch_verification(urls)
    
    verified = []
    unverified = []
    
    for url in urls:
        parsed = urlparse(url)
        domain = parsed.netloc
        
        if domain_status.get(domain, False):
            verified.append(url)
        else:
            unverified.append(url)
    
    return verified, unverified

def log_verification_failure(url, user_id, db_config=DB_CONFIG):
    """Log when a URL fails verification check"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO verification_failures 
            (url, domain, user_id, failed_at)
            VALUES (%s, %s, %s, %s)
        """, (url, domain, user_id, datetime.now()))
        
        conn.commit()
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error logging verification failure: {e}")

def get_unverified_domains_report(user_id, db_config=DB_CONFIG):
    """Get report of unverified domains for a user"""
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                domain,
                COUNT(*) as failure_count,
                MIN(failed_at) as first_failure,
                MAX(failed_at) as last_failure
            FROM verification_failures
            WHERE user_id = %s
            AND notified = FALSE
            GROUP BY domain
            ORDER BY failure_count DESC
        """, (user_id,))
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return results
        
    except Exception as e:
        print(f"Error getting unverified domains report: {e}")
        return []

def mark_verification_failures_notified(user_id, domain, db_config=DB_CONFIG):
    """Mark verification failures as notified"""
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE verification_failures 
            SET notified = TRUE
            WHERE user_id = %s AND domain = %s
        """, (user_id, domain))
        
        conn.commit()
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error marking failures as notified: {e}")

def get_verification_instructions(domain):
    """Get verification instructions for a domain (standalone function)"""
    verifier = DomainVerifier(SERVICE_ACCOUNT_FILE)
    return verifier.get_verification_instructions(domain)


# ==================== USAGE EXAMPLE ====================

if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("🔍 Domain Verification Checker")
    print("=" * 60)
    
    # Initialize tables
    print("\n📦 Initializing database tables...")
    init_verification_tables(DB_CONFIG)
    
    # Create verifier
    print("\n🔧 Creating domain verifier...")
    verifier = DomainVerifier(SERVICE_ACCOUNT_FILE)
    
    # Get verified domains
    print("\n✅ Fetching verified domains from Search Console...")
    verified_domains = verifier.get_verified_domains()
    
    if verified_domains:
        print(f"\n📋 Found {len(verified_domains)} verified domains:")
        for vd in verified_domains:
            print(f"   • {vd['domain']} ({vd['permission_level']})")
    else:
        print("\n⚠️  No verified domains found!")
        print("   Make sure your service account is added to Search Console")
    
    # Test a URL if provided
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        print(f"\n🧪 Testing URL: {test_url}")
        
        is_verified = verifier.is_domain_verified(test_url)
        
        if is_verified:
            print(f"   ✅ Domain is verified!")
        else:
            print(f"   ❌ Domain is NOT verified")
            
            parsed = urlparse(test_url)
            domain = parsed.netloc
            print(f"\n{verifier.get_verification_instructions(domain)}")
    
    print("\n" + "=" * 60)