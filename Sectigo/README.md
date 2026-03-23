# Sectigo Certificate Automation Tool

A comprehensive Python application for automating SSL/TLS certificate lifecycle management through the Sectigo Enterprise API.

## Features

✓ **Interactive CLI Menu** - User-friendly interface for all operations
✓ **OAuth2 Authentication** - Secure credential-based API access with token management
✓ **Domain Validation** - FQDN validation with wildcard support
✓ **Key Generation** - AES-256 encrypted RSA-2048 private keys with secure passphrases
✓ **Passphrase Security** - Minimum 128-bit entropy with multi-category validation (upper/lower/digit/special)
✓ **Rate Limiting** - 2 requests/second enforcement with automatic sleep
✓ **Error Handling** - Comprehensive exception handling with retry logic (3 retries, exponential backoff)
✓ **Logging** - Structured logging to file and console with atomic rotation
✓ **Certificate Workflows** - New orders, renewals, status checks, downloads
✓ **Key-Cert Validation** - Mathematical verification of key-certificate pairs

## Project Structure

```
.
├── main.py                    # Interactive CLI entry point with all workflows
├── sectigo_client.py          # Sectigo API client with OAuth2 and rate limiting
├── crypto_utils.py            # Key generation, encryption, certificate processing
├── check_passphrase.py        # Standalone passphrase/key-cert validation tool
├── test_auth.py               # Quick authentication test
├── test_verify.py             # Certificate verification test
├── requirements.txt           # Python package dependencies (pinned versions)
├── .env.example               # Environment variable template
├── .gitignore                 # Prevents credential/key commits
├── logs/                      # Application logs (auto-created)
│   └── sectigo.log           # Main application log with rotation
├── certificates/              # Output directory for certs/keys (auto-created)
├── staging/                   # Temporary processing directory (auto-created)
└── README.md                  # This file
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your Sectigo credentials:
```ini
SECTIGO_CLIENT_ID=your_client_id
SECTIGO_CLIENT_SECRET=your_client_secret
CERT_OUTPUT_DIR=certificates
STAGING_DIR=staging
```

### 3. Verify Installation

```bash
python test_auth.py          # Test API connectivity
python -c "from crypto_utils import generate_secure_passphrase; print(generate_secure_passphrase())"
```

## Usage

### Launch Interactive Menu

```bash
python main.py
```

### Menu Options

1. **New Order/Renewal**
   - Select organization and certificate profile
   - Choose domain (wildcard support)
   - Auto-generates encrypted RSA-2048 key with secure passphrase
   - Generates CSR and submits order
   - Saves SSL ID and metadata to work directory

2. **Check Status/Download**
   - Query certificate status by domain or SSL ID
   - Download issued certificates
   - Supports PEM, DER, and P7B formats

3. **Validate Passphrase + Key**
   - Verify private key matches certificate/CSR
   - Supports encrypted keys (prompts for passphrase)
   - Mathematical modulus validation

4. **Generate Secure Passphrase**
   - Creates 32-character passphrase with ≥128-bit entropy
   - Optional file save with 0o600 permissions
   - Multi-category composition ("PassW0rd!@#$")

### Standalone Scripts

```bash
# Validate certificate/key matching
python check_passphrase.py

# Test API authentication
python test_auth.py

# Verify key-certificate pairs
python test_verify.py
```

## Security Architecture

### Private Key Encryption
- **Algorithm**: AES-256 with PKCS8 format
- **Passphrase**: 32+ characters, ≥128 bits entropy
- **File Permissions**: 0o600 (owner read/write only)
- **Storage**: Never stored unencrypted

### API Credentials
- **Method**: Environment variables via .env
- **Never Logged**: Credentials excluded from all logs
- **Sanitization**: API errors sanitized (no credentials in messages)

### Rate Limiting
- **Threshold**: 2 requests/second max
- **Enforcement**: Request history tracking with automatic sleep
- **Timeout**: 30 seconds per request with 3 retries

### Logging
- **File Location**: logs/sectigo.log
- **Format**: Timestamp | Level | Message
- **Rotation**: Automatic at file size/date boundaries
- **Sanitization**: No secrets logged

## API Integration

### Endpoints Used

```
Authentication:
  POST https://auth.sso.sectigo.com/auth/realms/apiclients/protocol/openid-connect/token

Certificate Operations:
  GET  https://admin.enterprise.sectigo.com/api/ssl/v1                    # List certificates
  GET  https://admin.enterprise.sectigo.com/api/ssl/v1/{id}               # Status
  GET  https://admin.enterprise.sectigo.com/api/ssl/v1/{id}/certificate   # Download
  POST https://admin.enterprise.sectigo.com/api/ssl/v1                    # Submit order

Organization/Profile:
  GET  https://admin.enterprise.sectigo.com/api/organization/v1             # Organizations
  GET  https://admin.enterprise.sectigo.com/api/ssl/v1/types               # Profiles
  GET  https://admin.enterprise.sectigo.com/api/dcv/v1/domain/{domain}     # Domain status
```

## Output Directory Structure

```
certificates/
└── example.com_20240115_143022/
    ├── order_info.txt           # Order metadata (domain, SSL ID, org, profile)
    ├── wildcard.example.com.key # Encrypted private key (AES-256)
    ├── wildcard.example.com.csr # Certificate signing request
    ├── wildcard.example.com.txt # Passphrase (permissions: 0o600)
    └── [certificates downloaded here]
```

## Error Handling

### Connection Errors
- Automatic retry with exponential backoff (0.3s initial, 3 retries max)
- Timeout: 30 seconds per request
- Handles 429 (rate limit), 500, 502, 503, 504 status codes

### Validation Errors
- Domain FQDN regex validation (RFC 1123 compliance)
- SSL ID numeric validation
- Certificate chain verification
- Private key encryption status checks

### Security Errors
- Passphrase entropy validation (≥128 bits)
- Multi-category composition enforcement
- Key-certificate pair verification via modulus comparison
- File permission enforcement (0o600)

## Requirements

```
Python 3.13.5+
cryptography>=40.0.0,<42.0.0   # Encryption & certificate handling
requests>=2.28.0,<3.0.0        # HTTP requests with retry logic
python-dotenv>=0.20.0          # Environment variable management
urllib3>=1.26.0,<2.0.0         # Dependency for requests
colorama>=0.4.0                # Colored terminal output
```

## Pre-API Checklist

- [ ] `.env` configured with Sectigo Client ID/Secret
- [ ] `requirements.txt` packages installed: `pip install -r requirements.txt`
- [ ] Authentication tested: `python test_auth.py`
- [ ] Passphrase generation working: `generate_secure_passphrase()` returns 32+ char string with ≥128 entropy
- [ ] Key encryption working: New keys generated with AES-256 PKCS8 format
- [ ] Logging configured: logs/sectigo.log created and populated
- [ ] Output directories exist: certificates/, staging/, logs/
- [ ] Credentials not in any Python files or logs
- [ ] .gitignore prevents .env, *.key, *.pfx, *.pem, *.csr, *.crt, *.txt (passphrases) commits

## Troubleshooting

### "SECTIGO_CLIENT_ID and SECTIGO_CLIENT_SECRET must be set"
- Verify .env file exists in project root
- Confirm environment variables are loaded: `python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('SECTIGO_CLIENT_ID'))"`

### "Cannot unlock private key" 
- Verify passphrase matches the one used during key generation
- Check for .txt file alongside key file with stored passphrase
- Ensure key file permissions are 0o600

### "Domain validation failed"
- Use fully qualified domain name (FQDN): example.com or *.example.com
- No IP addresses; domains must be DNS-resolvable names
- Wildcard format: exactly one asterisk at leftmost position

### "No organizations found"
- Verify Sectigo account has organizations configured
- Check API permissions for organization access
- Confirm OAuth2 token obtained successfully

## License

Internal use only - Sectigo certificate automation specific to this organization.

## Support

For issues or questions:
1. Check latest logs: tail -f logs/sectigo.log
2. Review error messages in console output
3. Validate environment configuration
4. Test connectivity: python test_auth.py
