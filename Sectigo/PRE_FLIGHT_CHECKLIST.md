# Pre-Flight Checklist - Sectigo Certificate Automation Tool

## Purpose
This checklist verifies the tool is production-ready before connecting with live Sectigo API credentials.

**Estimated Time**: 10-15 minutes

---

## Phase 1: Environment Setup ✓

- [ ] **Install Python 3.13+**
  ```bash
  python --version  # Should show 3.13.x or higher
  ```

- [ ] **Clone/Extract Project**
  ```bash
  # All files present in project directory
  ls *.py              # main.py, sectigo_client.py, crypto_utils.py, etc.
  ls *.txt             # requirements.txt, .env.example
  ```

- [ ] **Create Virtual Environment**
  ```bash
  python -m venv .venv
  .venv\Scripts\activate  # Windows
  ```

- [ ] **Install Dependencies**
  ```bash
  pip install -r requirements.txt --upgrade
  ```

---

## Phase 2: Configuration ✓

- [ ] **Create .env File**
  ```bash
  cp .env.example .env
  ```

- [ ] **Populate Sectigo Credentials**
  - [ ] SECTIGO_CLIENT_ID: `______________________`
  - [ ] SECTIGO_CLIENT_SECRET: `______________________`
  - [ ] CERT_OUTPUT_DIR: `certificates` (or custom path)
  - [ ] STAGING_DIR: `staging` (or custom path)

- [ ] **Verify .env Readable**
  ```bash
  cat .env | grep SECTIGO_CLIENT_ID  # Should show value (not empty)
  ```

- [ ] **Verify .gitignore Configured**
  ```bash
  # .gitignore must contain:
  .env
  *.key
  *.pfx
  *.pem
  *.csr
  *.crt
  *.txt
  logs/
  ```

---

## Phase 3: Module Validation ✓

- [ ] **Test sectigo_client.py**
  ```bash
  python -c "from sectigo_client import SectigoClient; print('PASS')"
  # Should print: PASS (no errors)
  ```

- [ ] **Test crypto_utils.py**
  ```bash
  python -c "from crypto_utils import generate_secure_passphrase; p = generate_secure_passphrase(); print(f'PASS: {len(p)} chars, entropy check...')"
  # Should print: PASS: 32 chars, entropy check...
  ```

- [ ] **Test crypto_utils Functions**
  ```bash
  python -c "from crypto_utils import verify_passphrase_strength; ok, msg = verify_passphrase_strength(generate_secure_passphrase()); print(f'PASS: {msg}')"
  # Should print: PASS: Entropy: XXX.X bits
  ```

---

## Phase 4: Authentication Test ✓

- [ ] **Run Authentication Test**
  ```bash
  python test_auth.py
  ```
  Expected output:
  ```
  [*] Initializing Sectigo client...
  [+] Client initialized
  [*] Attempting to fetch organizations...
  [+] Success! Found N organization(s):
      1. Organization Name (ID: 123456)
  [+] Authentication test PASSED
  ```

  **If FAILED**: 
  - [ ] Check SECTIGO_CLIENT_ID and SECTIGO_CLIENT_SECRET in .env
  - [ ] Verify credentials are valid (not expired)
  - [ ] Check network connectivity (ping auth.sso.sectigo.com)
  - [ ] Review logs/sectigo.log for detailed error

---

## Phase 5: Crypto Security Validation ✓

- [ ] **Verify Passphrase Strength**
  ```bash
  python
  >>> from crypto_utils import generate_secure_passphrase, verify_passphrase_strength
  >>> p = generate_secure_passphrase()
  >>> ok, msg = verify_passphrase_strength(p)
  >>> print(f"Pass: {p}, OK: {ok}, {msg}")
  # Expected: Pass: [32-char string], OK: True, Entropy: 128+ bits
  ```
  - [ ] Passphrase is 32 characters long
  - [ ] Contains uppercase letters (YES / NO)
  - [ ] Contains lowercase letters (YES / NO)
  - [ ] Contains digits (YES / NO)
  - [ ] Contains special characters (YES / NO)
  - [ ] Entropy ≥ 128 bits (YES / NO)

- [ ] **Test Key Generation**
  ```bash
  python -c "
  from crypto_utils import generate_key_and_csr, prepare_work_directory
  work_dir = prepare_work_directory('test.example.com')
  csr_path, key_path = generate_key_and_csr('test.example.com', work_dir)
  print(f'CSR: {csr_path}')
  print(f'KEY: {key_path}')
  "
  ```
  - [ ] No errors (should print paths)
  - [ ] Files created in certificates/ subdirectory
  - [ ] Key file starts with: `-----BEGIN ENCRYPTED PRIVATE KEY-----`
  - [ ] CSR file starts with: `-----BEGIN CERTIFICATE REQUEST-----`
  - [ ] Verify key file permissions: `-rw-------` (0o600)

---

## Phase 6: Directory Structure ✓

- [ ] **Verify Directories Created**
  ```bash
  ls -la | grep -E "logs|certificates|staging"
  ```
  Should show:
  ```
  drwxr-xr-x logs/
  drwxr-xr-x certificates/
  drwxr-xr-x staging/
  ```

- [ ] **Verify Log File**
  ```bash
  ls -la logs/sectigo.log
  # File should exist and be readable
  ```

- [ ] **Check Log Content (No Credentials)**
  ```bash
  cat logs/sectigo.log
  # Should NOT contain: SECTIGO_CLIENT_ID, SECTIGO_CLIENT_SECRET, or any passwords
  # Should contain: INFO, DEBUG, ERROR messages with timestamps
  ```

---

## Phase 7: Tool Functionality ✓

- [ ] **Run Main Menu**
  ```bash
  python main.py
  ```
  Expected output:
  ```
  [Banner displayed]
  Sectigo client initialized successfully
  
  ==================================================
  MAIN MENU
  ==================================================
  1) New Order/Renewal
  2) Check Status/Download
  3) Validate Passphrase + Key
  4) Generate Secure Passphrase
  q) Quit
  ==================================================
  Select option:
  ```
  - [ ] Menu displays without errors
  - [ ] All options listed (1, 2, 3, 4, q)
  - [ ] Colors display correctly (if supported)

- [ ] **Test Passphrase Generation from Menu** (Option 4)
  ```
  Select option: 4
  [*] GENERATE SECURE PASSPHRASE
  Generated: [32-char string] (32 chars)
  Strength: Entropy: XXX.X bits
  Save passphrase to file? (y/n): n
  ```
  - [ ] Passphrase generated (32 characters)
  - [ ] Entropy reported (120+ bits)
  - [ ] Menu returns without error (press q to quit)

- [ ] **Test Key/Cert Validation from Menu** (Option 3)
  ```
  Select option: 3
  [*] VALIDATE PASSPHRASE + KEY
  Path to private key (.key): [leave blank]
  Path to cert/csr (.crt/.csr): [leave blank]
  ```
  - [ ] Prompts for file paths
  - [ ] Handles missing files gracefully (no crash)
  - [ ] Menu returns without error

---

## Phase 8: Security Audit ✓

- [ ] **No Hardcoded Credentials**
  ```bash
  grep -r "SECTIGO_CLIENT_ID\|SECTIGO_CLIENT_SECRET" *.py
  # Should return ZERO results
  ```

- [ ] **No Unencrypted Keys Stored**
  ```bash
  grep -r "BEGIN RSA PRIVATE KEY\|BEGIN PRIVATE KEY" . --exclude-dir=.venv
  # Should return ZERO results (all keys should be ENCRYPTED)
  ```

- [ ] **Credentials Only in .env**
  ```bash
  grep -l "SECTIGO_CLIENT_ID\|SECTIGO_CLIENT_SECRET" .* | grep -v ".env"
  # Should return ZERO results
  ```

- [ ] **.env Protected**
  ```bash
  ls -la .env
  # Should show: -rw-r--r-- (world-readable warning - change to -rw------- for extra security)
  # Optional but recommended: chmod 600 .env
  ```

- [ ] **No Secrets in Logs**
  ```bash
  cat logs/sectigo.log | grep -i "password\|secret\|token\|key"
  # Should only show framework/model names, NOT actual credentials
  ```

---

## Phase 9: Production Readiness ✓

- [ ] **All Tests Pass**
  - [ ] test_auth.py: ✓ PASS
  - [ ] test_verify.py: Can run without error (✓)
  - [ ] check_passphrase.py: Can run without error (✓)
  - [ ] main.py menu: ✓ PASS

- [ ] **Backup Credentials**
  - [ ] SECTIGO_CLIENT_ID saved securely (password manager / secure note)
  - [ ] SECTIGO_CLIENT_SECRET saved securely (password manager / secure note)
  - [ ] Note: These will be invalidated after initial setup, can be regenerated

- [ ] **Documentation Review**
  - [ ] README.md read and understood
  - [ ] All endpoints documented
  - [ ] Error handling procedures known
  - [ ] Troubleshooting guide reviewed

---

## Phase 10: Go/No-Go Decision ✓

**Go/No-Go**: ________________ (Check one)
- [ ] **GO** - All checks passed (32/32). Ready for production use.
- [ ] **NO-GO** - Some checks failed. Review errors above and retest.

**Failed Items** (if any):
```
1. ___________________________
2. ___________________________
3. ___________________________
```

**Sign-Off**:
- Date: _______________
- Operator: _______________
- Notes: _______________

---

## Quick Reference: Common Commands

```bash
# Start virtual environment
.venv\Scripts\activate

# Run authentication test
python test_auth.py

# Start interactive tool
python main.py

# Check logs
tail -f logs/sectigo.log

# Generate test passphrase
python -c "from crypto_utils import generate_secure_passphrase, verify_passphrase_strength; p = generate_secure_passphrase(); ok, msg = verify_passphrase_strength(p); print(f'{p} - {msg}')"

# View environment variables
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('CLIENT_ID:', 'SET' if os.getenv('SECTIGO_CLIENT_ID') else 'MISSING')"
```

---

## Post-Deployment Checklist

After first successful test:
- [ ] Credentials rotated in Sectigo dashboard (for security)
- [ ] Backup of .env file created (secure location)
- [ ] Project added to version control (.gitignore verified)
- [ ] Scheduled backup of certificates/ directory setup
- [ ] Log monitoring configured (if applicable)
- [ ] Team trained on usage procedure
