# Quick Start Guide - Sectigo Certificate Automation Tool

**⏱️ Setup Time**: 5 minutes | **First Use**: 10 minutes

---

## 5-Minute Setup

### Step 1: Create Environment File
```bash
cd c:\Users\ChadB\OneDrive\OathKeeper\ChadB\Documents\Scripts\Python\Sectigo

copy .env.example .env
```

### Step 2: Add Your Credentials to .env
```ini
SECTIGO_CLIENT_ID=your_client_id_here
SECTIGO_CLIENT_SECRET=your_client_secret_here
CERT_OUTPUT_DIR=certificates
STAGING_DIR=staging
```

### Step 3: Verify Installation
```bash
python test_auth.py
```

**Expected Output**:
```
[+] Success! Found N organization(s):
    1. Organization Name (ID: 12345)
[+] Authentication test PASSED
```

✅ **If you see this, you're ready to go!**

---

## First Use - Interactive Menu

### Launch Tool
```bash
python main.py
```

### Menu Options

#### Option 1: New Order/Renewal
```
Select option: 1
Enter FQDN (e.g test.example.com): example.com
[Select organization from list]
[Select certificate profile from list]
[Tool generates encrypted key + CSR]
[Order submitted, SSL ID: 123456]
```

#### Option 2: Check Status/Download
```
Select option: 2
Enter SSL ID or domain: 123456
[Status displayed]
[Certificate downloaded if issued]
```

#### Option 3: Validate Passphrase
```
Select option: 3
Path to private key (.key): certificates/example.com_20240115_143022/example.com.key
Path to cert/csr (.crt/.csr): certificates/example.com_20240115_143022/example.com.crt
[Success: Private key matches Certificate]
```

#### Option 4: Generate Passphrase
```
Select option: 4
Generated: aBcD12!@#$%^&*aBcD12!@#$%^&*abcd (32 chars)
Strength: Entropy: 150.5 bits
Save passphrase to file? (y/n): y
Filename: mypassphrase.txt
[Saved with secure permissions]
```

#### Quit
```
Select option: q
Goodbye!
```

---

## Key Directories

```
certificates/          Generated keys, CSRs, and downloaded certificates
├── example.com_20240115_143022/
│   ├── order_info.txt          Order metadata
│   ├── example.com.key         Encrypted private key (AES-256)
│   ├── example.com.csr         Certificate signing request
│   └── example.com.txt         Passphrase (secure permissions)
```

```
logs/
├── sectigo.log                 Application activity log
```

---

## Common Tasks

### I need to check certificate status by SSL ID
```bash
python main.py
> Option 2
> Enter SSL ID: 4567890
```

### I lost a passphrase, can I regenerate one?
```bash
python main.py
> Option 4
> Copy the generated passphrase
> Use to re-encrypt key (if needed)
```

### I need to verify my key matches the certificate
```bash
python main.py
> Option 3
> Provide key path and cert path
> Tool validates they match mathematically
```

### I want a standalone test without the menu
```bash
python check_passphrase.py   # Key/cert validation tool
python test_auth.py           # Quick auth check
```

---

## Troubleshooting Quick Reference

| Problem | Solution |
|---------|----------|
| "Missing environment variables" | Edit .env with SECTIGO_CLIENT_ID and SECTIGO_CLIENT_SECRET |
| "Authentication failed" | Verify credentials in .env, check Sectigo dashboard |
| "Cannot unlock private key" | Check passphrase file (.txt) alongside .key file |
| "Domain validation failed" | Use FQDN format (example.com), not IP address |
| "No organizations found" | Verify Sectigo account permissions |

---

## Security Reminders

🔒 **Never**:
- Commit .env to git (it contains credentials)
- Share private key files (.key)
- Store passphrases in plain text (use file with 0o600 permissions)
- Print/log your SECTIGO_CLIENT_SECRET

✅ **Always**:
- Keep .env in secure location
- Backup encrypted keys and passphrases separately
- Review logs for unusual activity (logs/sectigo.log)
- Rotate API credentials periodically

---

## File Reference

| File | Purpose |
|------|---------|
| main.py | Start here! Interactive menu for all operations |
| test_auth.py | Verify API connectivity with one command |
| check_passphrase.py | Standalone key/cert validation tool |
| .env | Your Sectigo credentials (keep secret!) |
| logs/sectigo.log | Application activity log for troubleshooting |
| README.md | Full documentation with all details |
| PRE_FLIGHT_CHECKLIST.md | Complete verification before production use |

---

## Command Cheat Sheet

```bash
# Start interactive tool
python main.py

# Test authentication
python test_auth.py

# Validate key/certificate
python check_passphrase.py

# Check recent logs
tail -20 logs/sectigo.log

# Generate test passphrase
python -c "from crypto_utils import generate_secure_passphrase; print(generate_secure_passphrase())"

# Verify credentials loaded
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('READY' if os.getenv('SECTIGO_CLIENT_ID') else 'MISSING CREDENTIALS')"
```

---

## Need Help?

1. **Documentation**: See README.md for complete feature guide
2. **Troubleshooting**: See README.md **Troubleshooting** section
3. **Pre-Flight Check**: Run PRE_FLIGHT_CHECKLIST.md before production use
4. **Logs**: Check logs/sectigo.log for detailed error messages
5. **Code**: All functions documented with docstrings

---

## Pro Tips

💡 **Tip 1**: Use Option 4 to generate test passphrases before creating orders
💡 **Tip 2**: Keep a backup of your .env file in a secure location
💡 **Tip 3**: Run test_auth.py periodically to verify connection
💡 **Tip 4**: Review logs/sectigo.log after each operation to verify success
💡 **Tip 5**: For batch operations, review the main.py code for programmatic usage

---

## Production Checklist (1 minute)

Before your first production order:
- [ ] .env configured with correct Sectigo credentials
- [ ] python test_auth.py shows organizations list
- [ ] System time is correct (affects OAuth token validation)
- [ ] Network connectivity to Sectigo API confirmed
- [ ] Output directories exist and are writable (certificates/, staging/, logs/)

✅ **You're ready to go!**

```bash
python main.py
```
