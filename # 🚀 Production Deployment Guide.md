# 🚀 Production Deployment Guide

## Complete Production-Ready URL Indexing Bot

This guide covers deploying the fully-featured, production-ready URL indexing bot with all security and scalability features.

---

## 📋 **Prerequisites**

### **Required:**
- Ubuntu Server 20.04+ or Debian 11+
- Root/sudo access
- Domain name (for SSL)
- Minimum 2GB RAM, 20GB storage
- PostgreSQL 14+
- Redis 6+
- Python 3.10+

### **Accounts Needed:**
- Telegram Bot Token (from @BotFather)
- Google Cloud Service Account
- (Optional) Rapid URL Indexer API Key

---

## 🔐 **STEP 1: Secure Configuration Setup**

### **1.1 Install Dependencies**

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3.10 python3.10-venv python3-pip \
    postgresql-14 postgresql-contrib redis-server nginx supervisor \
    git curl build-essential libpq-dev
```

### **1.2 Clone/Upload Project**

```bash
# Create project directory
sudo mkdir -p /opt/url-indexing-bot
cd /opt/url-indexing-bot

# Upload all your project files here
# Or clone from git:
# git clone <your-repo-url> .
```

### **1.3 Setup Python Environment**

```bash
# Create virtual environment
python3.10 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements_production.txt
```

### **1.4 Configure Secure Environment**

```bash
# Run interactive setup
python secure_config.py setup
```

This will create:
- `.env` file with encrypted credentials
- `.encryption_key` file (BACKUP THIS!)

**IMPORTANT:** Add to `.gitignore`:
```bash
echo ".env" >> .gitignore
echo ".encryption_key" >> .gitignore
echo "service-account.json" >> .gitignore
```

---

## 🗄️ **STEP 2: Database Setup**

### **2.1 Create PostgreSQL Database**

```bash
# Switch to postgres user
sudo -u postgres psql

# Run these SQL commands:
CREATE DATABASE url_indexing;
CREATE USER indexbot WITH PASSWORD 'YOUR_SECURE_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE url_indexing TO indexbot;
\q
```

### **2.2 Update `.env` with Database Credentials**

```bash
DB_HOST=localhost
DB_NAME=url_indexing
DB_USER=indexbot
DB_PASSWORD=<encrypted_password>  # Will be encrypted automatically
DB_PORT=5432
```

### **2.3 Initialize Database Tables**

```bash
python3 <<EOF
from bot_integrated import init_database
from rate_limiter import init_rate_limit_tables
from domain_verifier import init_verification_tables
from secure_config import DB_CONFIG

init_database()
init_rate_limit_tables(DB_CONFIG)
init_verification_tables(DB_CONFIG)
print("✅ All tables initialized!")
EOF
```

---

## 🔑 **STEP 3: Google API Setup**

### **3.1 Create Service Account**

1. Go to: https://console.cloud.google.com
2. Create new project: "url-indexing-bot"
3. Enable APIs:
   - Web Search Indexing API
   - Search Console API
4. Create Service Account:
   - **APIs & Services** → **Credentials**
   - **Create Credentials** → **Service Account**
   - Name: `url-indexing-service`
   - Role: **Owner**
5. Create JSON key → Download as `service-account.json`

### **3.2 Add to Search Console**

```bash
# 1. Open service-account.json and copy the "client_email"
cat service-account.json | grep client_email

# 2. Go to: https://search.google.com/search-console
# 3. Select your property
# 4. Settings → Users and permissions
# 5. Add User → Paste email → Set as "Owner"
```

---

## ⚡ **STEP 4: Redis Setup**

```bash
# Start Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test connection
redis-cli ping
# Should output: PONG
```

---

## 🚀 **STEP 5: Deploy with Automation**

### **5.1 Run Deployment Script**

```bash
# Make script executable
chmod +x deploy.sh

# Run deployment
sudo ./deploy.sh production
```

This script will:
- ✅ Install all system dependencies
- ✅ Setup Python environment
- ✅ Configure PostgreSQL
- ✅ Setup Redis
- ✅ Create systemd services
- ✅ Configure Nginx
- ✅ Setup log rotation
- ✅ Configure automated backups
- ✅ Setup firewall

### **5.2 Verify Services**

```bash
# Check all services
systemctl status url-bot
systemctl status url-admin
systemctl status url-worker
systemctl status url-beat

# View logs
journalctl -u url-bot -f
journalctl -u url-admin -f
```

---

## 🔒 **STEP 6: SSL Certificate (Recommended)**

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is configured automatically
```

---

## 📊 **STEP 7: Monitoring Setup**

### **7.1 Celery Flower (Task Monitoring)**

```bash
# Start Flower
celery -A celery_worker flower --port=5555

# Access at: http://your-domain.com:5555
```

### **7.2 Log Monitoring**

```bash
# Install log viewer
sudo apt install lnav

# View all logs
sudo lnav /var/log/url-indexing-bot/
```

---

## ✅ **STEP 8: Testing**

### **8.1 Test Bot**

```bash
# 1. Open Telegram
# 2. Search for your bot
# 3. Send: /start
# 4. Upload a test file
# 5. Type: index
```

### **8.2 Test Admin Panel**

```bash
# 1. Open: https://your-domain.com
# 2. Login with credentials from .env
# 3. Add credits to yourself
# 4. Test all features
```

### **8.3 Test Rate Limiting**

```bash
# Send 11 files quickly (limit is 10/hour)
# Should get rate limit error on 11th
```

### **8.4 Test Domain Verification**

```bash
# Upload file with unverified domain
# Should warn about unverified domains
```

---

## 🔧 **STEP 9: Configuration**

### **9.1 Customize Rate Limits**

Edit `.env`:
```bash
MAX_FILES_PER_HOUR=10
MAX_URLS_PER_FILE=1000
MAX_URLS_PER_DAY=1000
```

### **9.2 Set Admin Users**

Edit `.env`:
```bash
ADMIN_USER_IDS=123456789,987654321
```

### **9.3 Configure Third-Party API**

If using Rapid URL Indexer:
```bash
RAPID_API_KEY=<encrypted_key>
INDEXING_PROVIDER=hybrid  # or "rapid" or "google"
```

---

## 📦 **STEP 10: Backups**

### **10.1 Automated Backups**

Backups run daily at midnight automatically.

Location: `/var/backups/url-indexing-bot/`

### **10.2 Manual Backup**

```bash
# Backup database
pg_dump -U indexbot url_indexing | gzip > backup_$(date +%Y%m%d).sql.gz

# Backup configuration
cp .env .env.backup
cp .encryption_key .encryption_key.backup

# Backup to remote location
scp backup_*.sql.gz user@remote:/backups/
```

### **10.3 Restore from Backup**

```bash
# Restore database
gunzip < backup_20240101.sql.gz | psql -U indexbot url_indexing

# Restore configuration
cp .env.backup .env
cp .encryption_key.backup .encryption_key

# Restart services
sudo systemctl restart url-bot url-admin url-worker url-beat
```

---

## 🔍 **STEP 11: Troubleshooting**

### **Common Issues:**

#### **Bot not responding:**
```bash
# Check if running
systemctl status url-bot

# View logs
journalctl -u url-bot -f

# Restart
sudo systemctl restart url-bot
```

#### **Database connection error:**
```bash
# Test connection
psql -h localhost -U indexbot -d url_indexing

# Check credentials in .env
cat .env | grep DB_
```

#### **Redis connection error:**
```bash
# Check Redis status
systemctl status redis-server

# Test connection
redis-cli ping
```

#### **Celery not processing:**
```bash
# Check worker status
systemctl status url-worker

# View active tasks
celery -A celery_worker inspect active
```

#### **Domain verification failing:**
```bash
# Check service account
python3 <<EOF
from domain_verifier import DomainVerifier
verifier = DomainVerifier('service-account.json')
domains = verifier.get_verified_domains()
print(f"Verified domains: {domains}")
EOF
```

---

## 📈 **STEP 12: Performance Optimization**

### **12.1 Database Optimization**

```sql
-- Run monthly
VACUUM ANALYZE;

-- Create additional indexes if needed
CREATE INDEX idx_indexing_requests_date ON indexing_requests(submitted_at);
```

### **12.2 Redis Memory Optimization**

Edit `/etc/redis/redis.conf`:
```bash
maxmemory 512mb
maxmemory-policy allkeys-lru
```

### **12.3 Celery Worker Scaling**

```bash
# Edit /etc/systemd/system/url-worker.service
# Change to 4 workers:
ExecStart=/path/to/venv/bin/celery -A celery_worker worker -c 4 --loglevel=info
```

---

## 🛡️ **STEP 13: Security Hardening**

### **13.1 Firewall**

```bash
# Allow only necessary ports
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable
```

### **13.2 Fail2Ban (Prevent Brute Force)**

```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
```

### **13.3 Regular Updates**

```bash
# Setup automatic security updates
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 📊 **STEP 14: Monitoring & Alerts**

### **14.1 Setup Health Checks**

Create `/usr/local/bin/health-check.sh`:
```bash
#!/bin/bash
systemctl is-active --quiet url-bot || systemctl restart url-bot
systemctl is-active --quiet url-admin || systemctl restart url-admin
systemctl is-active --quiet url-worker || systemctl restart url-worker
```

Add to cron:
```bash
*/5 * * * * /usr/local/bin/health-check.sh
```

### **14.2 Disk Space Monitoring**

```bash
# Add to cron
0 2 * * * df -h | mail -s "Disk Space Report" admin@example.com
```

---

## 🎯 **STEP 15: Production Checklist**

Before going live:

- [ ] `.env` configured with all credentials
- [ ] `.encryption_key` backed up securely
- [ ] Database initialized and accessible
- [ ] Redis running
- [ ] All 4 systemd services running
- [ ] Nginx configured with SSL
- [ ] Admin panel accessible
- [ ] Bot responds to /start
- [ ] File upload works
- [ ] Indexing works
- [ ] Rate limiting tested
- [ ] Domain verification tested
- [ ] Backups configured
- [ ] Monitoring setup
- [ ] Firewall configured
- [ ] Logs rotating properly

---

## 🔄 **STEP 16: Maintenance**

### **Weekly:**
- Check disk space
- Review error logs
- Verify backups are working

### **Monthly:**
- Update system packages
- Vacuum database
- Review and archive old logs

### **Quarterly:**
- Security audit
- Performance review
- Update dependencies

---

## 📞 **Support Commands**

```bash
# Restart all services
sudo systemctl restart url-bot url-admin url-worker url-beat

# View all logs
sudo lnav /var/log/url-indexing-bot/

# Check service status
sudo systemctl status url-*

# Database backup
sudo -u postgres pg_dump url_indexing | gzip > backup.sql.gz

# Clear Redis cache
redis-cli FLUSHALL

# Check Celery queue
celery -A celery_worker inspect active
```

---

## 🎉 **You're Live!**

Your production-ready URL indexing bot is now:
- ✅ Fully encrypted and secure
- ✅ Rate-limited to prevent abuse
- ✅ Domain-verified for Google API
- ✅ Scalable with Celery queues
- ✅ Monitored and backed up
- ✅ Ready for commercial use

**Access Points:**
- **Bot:** https://t.me/your_bot_username
- **Admin Panel:** https://your-domain.com
- **Celery Monitor:** https://your-domain.com:5555

---

## 📚 **Additional Resources**

- [Google Indexing API Docs](https://developers.google.com/search/apis/indexing-api)
- [Celery Documentation](https://docs.celeryproject.org/)
- [Flask Security Guide](https://flask.palletsprojects.com/en/2.3.x/security/)
- [PostgreSQL Best Practices](https://www.postgresql.org/docs/current/performance-tips.html)

---

**🎯 Your bot is production-ready and commercially viable!**