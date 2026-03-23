# Technical API Reference - Sectigo Certificate Automation Tool

**For**: Python developers extending or integrating this tool
**Language**: Python 3.13+
**Target**: Programmatic usage (beyond interactive CLI)

---

## Module: sectigo_client.py

### Class: SectigoClient

```python
from sectigo_client import SectigoClient

# Initialize
client = SectigoClient()
# Credentials loaded from os.environ (via .env)
```

#### Methods

##### `authenticate()`
```python
def authenticate(self) -> None
```
**Purpose**: Acquire OAuth2 bearer token with expiration tracking
**Raises**: 
- `ValueError` - Authentication failed or timeout
**Side Effects**: 
- Sets `self.token` (str, bearer token)
- Sets `self.token_expires_at` (float, unix timestamp with 5-min buffer)
**Logging**: 
- DEBUG: Token expiration time
- ERROR: HTTP status, network issues
**Example**:
```python
try:
    client.authenticate()
    print(f"Token valid until: {client.token_expires_at}")
except ValueError as e:
    print(f"Auth failed: {e}")
```

##### `get_organizations()`
```python
def get_organizations(self) -> List[Dict]
```
**Returns**: List of organization dicts
**Dict Keys**: `organizationId`, `organizationName`, etc.
**Rate Limited**: Yes (2 req/sec)
**Retry**: Yes (3x, exponential backoff)
**Timeout**: 30 seconds
**Example**:
```python
orgs = client.get_organizations()
for org in orgs:
    print(f"ID: {org['organizationId']}, Name: {org['organizationName']}")
```

##### `get_profiles()`
```python
def get_profiles(self) -> List[Dict]
```
**Returns**: List of certificate profile dicts
**Dict Keys**: `profileId`, `profileName`, `validity`, etc.
**Rate Limited**: Yes
**Example**:
```python
profiles = client.get_profiles()
profile_id = profiles[0]['profileId']  # Use first profile
```

##### `get_order_status(ssl_id: int) -> Dict | None`
```python
def get_order_status(self, ssl_id: int) -> Optional[Dict]
```
**Parameters**:
- `ssl_id` (int or str): Certificate SSL ID
**Returns**: Order details dict or None on error
**Dict Keys**: `id`, `status`, `commonName`, `issued`, `expires`, etc.
**Status Values**: `pending`, `approved`, `rejected`, `issued`
**Raises**: `ValueError` if ssl_id not numeric
**Example**:
```python
status = client.get_order_status(4567890)
if status:
    print(f"Status: {status['status']}")
    if status['status'] == 'issued':
        cert = client.collect_certificate(4567890)
```

##### `get_all_certificates(position=0, size=100) -> List[Dict]`
```python
def get_all_certificates(self) -> List[Dict]
```
**Returns**: All certificates (paginated, 100 per request)
**Dict Keys**: `id`, `commonName`, `status`, `issued`, `expires`, etc.
**Pagination**: Automatic (handles multiple pages)
**Example**:
```python
all_certs = client.get_all_certificates()
production_certs = [c for c in all_certs if c['status'] == 'issued']
```

##### `submit_order(csr: str, org_id: int, profile_id: int, domain: str, **kwargs) -> Dict | None`
```python
def submit_order(self, csr_content: str, org_id: int, profile_id: int, 
                 domain: str, renewal_id: int = None, term: int = 365, 
                 comments: str = None, external_requester: List = None) -> Optional[Dict]
```
**Parameters**:
- `csr_content` (str): PEM-formatted CSR (-----BEGIN CERTIFICATE REQUEST-----)
- `org_id` (int): Organization ID from get_organizations()
- `profile_id` (int): Profile ID from get_profiles()
- `domain` (str): Domain (wildcard support: *.example.com)
- `renewal_id` (int, optional): If renewing, the original SSL ID
- `term` (int, optional): Validity term in days (default 365)
- `comments` (str, optional): Order comments
- `external_requester` (list, optional): External requester emails
**Returns**: Response dict with key 'id' (SSL ID) or None on error
**Raises**: `ValueError` if required parameters missing
**Example**:
```python
from crypto_utils import generate_key_and_csr
csr_path, key_path = generate_key_and_csr('example.com', '.', 'CompanyName')
with open(csr_path, 'r') as f:
    csr_content = f.read()

order = client.submit_order(csr_content, org_id=12345, profile_id=67890, 
                            domain='example.com')
if order:
    ssl_id = order['id']
    print(f"Order created: SSL ID {ssl_id}")
```

##### `collect_certificate(ssl_id: int) -> str | None`
```python
def collect_certificate(self, ssl_id: int) -> Optional[str]
```
**Parameters**:
- `ssl_id` (int): Certificate SSL ID
**Returns**: PEM-formatted certificate content or None on error
**Format**: PEM (multiple certificates if chain included)
**Example**:
```python
cert_pem = client.collect_certificate(4567890)
if cert_pem:
    with open('downloaded_cert.pem', 'w') as f:
        f.write(cert_pem)
```

##### `list_certificates_by_domain(domain: str) -> List[Dict]`
```python
def list_certificates_by_domain(self, domain: str) -> List[Dict]
```
**Parameters**:
- `domain` (str): FQDN to search (e.g., example.com)
**Returns**: Filtered certificate list for that domain
**Filtering**: Case-insensitive commonName match
**Example**:
```python
certs = client.list_certificates_by_domain('example.com')
for cert in certs:
    print(f"SSL ID: {cert['id']}, Expires: {cert['expires']}")
```

##### `get_domain_status(domain: str) -> Dict | None`
```python
def get_domain_status(self, domain: str) -> Optional[Dict]
```
**Purpose**: Check Domain Control Validation (DCV) status
**Returns**: DCV status dict or None
**Example**:
```python
dcv_status = client.get_domain_status('example.com')
if dcv_status:
    print(f"DCV Status: {dcv_status['status']}")
```

##### `get_latest_order_id(domain: str) -> int | None`
```python
def get_latest_order_id(self, domain: str) -> Optional[int]
```
**Purpose**: Find most recent SSL ID for domain
**Example**:
```python
latest_id = client.get_latest_order_id('example.com')
if latest_id:
    status = client.get_order_status(latest_id)
```

#### Private Methods (Internal)

##### `_validate_ssl_id(ssl_id) -> int`
```python
def _validate_ssl_id(self, ssl_id) -> int
```
**Raises**: `ValueError` if not numeric

##### `_validate_domain(domain) -> str`
```python
def _validate_domain(self, domain) -> str
```
**Raises**: `ValueError` if not valid FQDN format

##### `_check_rate_limit()`
```python
def _check_rate_limit(self) -> None
```
**Effect**: Sleeps if rate limit (2 req/sec) approached

##### `_get_headers() -> Dict`
```python
def _get_headers(self) -> Dict
```
**Returns**: HTTP headers dict with Authorization bearer token

##### `_get_session() -> requests.Session`
```python
def _get_session(self) -> requests.Session
```
**Returns**: Session with retry strategy (3x, exponential backoff)

---

## Module: crypto_utils.py

### Functions

#### `generate_secure_passphrase(length=32) -> str`
```python
from crypto_utils import generate_secure_passphrase

passphrase = generate_secure_passphrase()  # 32 chars, ≥128-bit entropy
```
**Returns**: Random string guaranteed ≥128-bit entropy
**Length**: 32 characters (customizable)
**Guarantees**: 
- Contains uppercase letters (A-Z)
- Contains lowercase letters (a-z)
- Contains digits (0-9)
- Contains special chars (!@#$%^&*-_=+[]{}|:;<>?,.~)
**Example**:
```python
for _ in range(5):
    p = generate_secure_passphrase()
    print(f"Generated: {p} ({len(p)} chars)")
```

#### `calculate_entropy(password: str) -> float`
```python
from crypto_utils import calculate_entropy

entropy = calculate_entropy("MyP@ssw0rd123!")
print(f"Entropy: {entropy:.1f} bits")
```
**Returns**: Entropy in bits (float)
**Formula**: len(password) * log2(charset_size)
**Charset Sizes**:
- Uppercase: 26 chars
- Lowercase: 26 chars
- Digits: 10 chars
- Special: 16 chars (~92 total if all present)

#### `verify_passphrase_strength(password: str) -> Tuple[bool, str]`
```python
from crypto_utils import verify_passphrase_strength

ok, message = verify_passphrase_strength("MyP@ssw0rd123!")
if ok:
    print(f"Strong: {message}")
else:
    print(f"Weak: {message}")
```
**Returns**: (bool, str) - (is_strong, message_with_entropy)
**Minimum**: 128-bit entropy required
**Example Message**: "Entropy: 145.3 bits"

#### `prepare_work_directory(domain: str, base_path="certificates") -> str`
```python
from crypto_utils import prepare_work_directory

work_dir = prepare_work_directory("example.com")
# Returns: "certificates/example.com_20240115_143022"
```
**Returns**: Path to newly created directory
**Format**: domain_YYYYMMDD_HHMMSS
**Effect**: Creates directory with timestamp for unique naming

#### `generate_key_and_csr(domain: str, work_dir: str, org_name="My Organization", ou_name="IT", passphrase=None) -> Tuple[str, str]`
```python
from crypto_utils import generate_key_and_csr

csr_path, key_path = generate_key_and_csr(
    domain="example.com",
    work_dir="certificates/example.com_20240115_143022",
    org_name="My Company",
    ou_name="IT Department"
)
```
**Returns**: (csr_path, key_path) - PEM file paths
**Key Specification**:
- Algorithm: RSA
- Key Size: 2048 bits
- Format: PKCS8
- Encryption: AES-256
- File Permissions: 0o600 (owner only)
**CSR Attributes**:
- CN (Common Name): domain
- O (Organization): org_name
- OU (Organizational Unit): ou_name
- C (Country): US
**Files Created**:
- `{domain}.key` - Encrypted private key
- `{domain}.csr` - Certificate signing request
- `{domain}.txt` - Passphrase file (0o600 permissions)
**Example**:
```python
csr_path, key_path = generate_key_and_csr("*.example.com", ".")
print(f"Key: {key_path}")
print(f"CSR: {csr_path}")
```

#### `verify_key_payload(key_path: str, target_path: str) -> Tuple[bool, str]`
```python
from crypto_utils import verify_key_payload

success, message = verify_key_payload(
    key_path="example.com.key",
    target_path="example.com.crt"
)
if success:
    print(f"Match! {message}")
else:
    print(f"Mismatch: {message}")
```
**Comparison Method**: RSA modulus comparison
**Returns**: (bool, str) - (matched, message)
**Handles**: Encrypted keys (prompts for passphrase or reads .txt file)
**Supports**: 
- CSR files (.csr)
- Certificate files (.crt, .pem)
- Encrypted private keys

#### `extract_certs_from_bundle(pem_data: str) -> Dict[str, str]`
```python
from crypto_utils import extract_certs_from_bundle

with open('cert_bundle.pem', 'r') as f:
    pem_data = f.read()

result = extract_certs_from_bundle(pem_data)
print(result['leaf'])        # Leaf certificate
print(result['root'])        # Root CA certificate
print(result['intermediates']) # Intermediate certs
print(result['full_chain'])  # Complete chain
```
**Returns**: Dict with keys:
- `leaf`: Leaf certificate (PEM)
- `intermediates`: Intermediate certificates (PEM)
- `root`: Root CA certificate (PEM)
- `full_chain`: Complete chain (all certs concatenated)
**Heuristic**: 
- First cert = leaf
- Last self-signed cert = root
- Middle certs = intermediates

#### `create_pfx(key_path: str, cert_pem: str, pfx_path: str, password=None, friendly_name=None) -> bool`
```python
from crypto_utils import create_pfx

success = create_pfx(
    key_path="example.com.key",
    cert_pem=cert_content,
    pfx_path="example.com.pfx",
    password="MyP@ssw0rd",
    friendly_name="My Website"
)
```
**Parameters**:
- `key_path` (str): Path to encrypted private key
- `cert_pem` (str): PEM-formatted certificate (chain supported)
- `pfx_path` (str): Output .pfx file path
- `password` (str, optional): PFX password (defaults to key password)
- `friendly_name` (str, optional): Certificate friendly name
**Returns**: bool - success or failure
**Format**: PKCS12 (.pfx/.p12)
**Includes**: 
- Private key (encrypted)
- Leaf certificate
- Intermediate certificates (if present)

#### `re_encrypt_key(key_path: str, new_password=None) -> bool`
```python
from crypto_utils import re_encrypt_key

success = re_encrypt_key("example.com.key", new_password="NewP@ss123!")
```
**Purpose**: Change encryption password on existing key
**Interactive**: Prompts for current password if not provided
**Returns**: bool - success or failure

#### `create_zip_archive(work_dir: str, output_path=None) -> str | None`
```python
from crypto_utils import create_zip_archive

zip_path = create_zip_archive("certificates/example.com_20240115_143022")
```
**Returns**: Path to created .zip file or None on error
**Contents**: All certificate files from work directory

#### `convert_pkcs7_to_pem(pkcs7_data: str) -> str`
```python
from crypto_utils import convert_pkcs7_to_pem

pem_certs = convert_pkcs7_to_pem(pkcs7_content)
```
**Purpose**: Convert PKCS7 or pass-through if already PEM
**Returns**: PEM-formatted certificate string

---

## Common Workflows

### Workflow 1: Create and Submit Order
```python
from sectigo_client import SectigoClient
from crypto_utils import prepare_work_directory, generate_key_and_csr

# Initialize
client = SectigoClient()

# Get organization and profile
orgs = client.get_organizations()
org_id = orgs[0]['organizationId']

profiles = client.get_profiles()
profile_id = profiles[0]['profileId']

# Generate key and CSR
domain = "example.com"
work_dir = prepare_work_directory(domain)
csr_path, key_path = generate_key_and_csr(domain, work_dir)

# Read CSR
with open(csr_path, 'r') as f:
    csr_content = f.read()

# Submit order
order = client.submit_order(csr_content, org_id, profile_id, domain)
ssl_id = order['id']
print(f"Order created: {ssl_id}")
```

### Workflow 2: Check Status and Download
```python
from sectigo_client import SectigoClient
from crypto_utils import extract_certs_from_bundle, create_pfx

client = SectigoClient()

# Check status
ssl_id = 4567890
status = client.get_order_status(ssl_id)

if status['status'] == 'issued':
    # Download certificate
    cert_pem = client.collect_certificate(ssl_id)
    
    # Extract chain
    chain = extract_certs_from_bundle(cert_pem)
    
    # Create PFX
    create_pfx("example.com.key", cert_pem, "example.com.pfx")
```

### Workflow 3: Validate Key-Certificate Match
```python
from crypto_utils import verify_key_payload

success, message = verify_key_payload(
    "example.com.key",
    "example.com.crt"
)
print(message)  # "✓ Private key matches Certificate" or error message
```

---

## Error Handling Examples

### Handling API Errors
```python
from sectigo_client import SectigoClient
import requests

client = SectigoClient()

try:
    org = client.get_organizations()
except requests.HTTPError as e:
    print(f"HTTP {e.response.status_code}: {e}")
except requests.Timeout:
    print("Request timed out")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Handling Crypto Errors
```python
from crypto_utils import verify_key_payload

success, message = verify_key_payload("key.key", "cert.crt")
if not success:
    print(f"Validation failed: {message}")
    # Possible messages:
    # "Failed to load private key: ..."
    # "✗ Private key does NOT match Certificate"
    # "Error during validation: ..."
```

---

## Logging

All operations are logged to `logs/sectigo.log`:

```
2024-01-15 14:30:22 - sectigo_client - INFO - Retrieved order status for SSL ID: 4567890
2024-01-15 14:30:23 - crypto_utils - DEBUG - Generated encrypted private key: ...
2024-01-15 14:30:24 - crypto_utils - INFO - Key validation successful for example.com.key
```

**Levels**:
- DEBUG: Detailed crypto operations
- INFO: Successful operations
- WARNING: Non-fatal issues (e.g., missing env var)
- ERROR: Operation failures

---

## Dependencies

```python
# Internal
from sectigo_client import SectigoClient
from crypto_utils import (
    generate_secure_passphrase,
    generate_key_and_csr,
    verify_key_payload,
    extract_certs_from_bundle,
    create_pfx
)

# External
import requests          # HTTP library
from cryptography import x509  # Certificate handling
from dotenv import load_dotenv # Environment variables
```

---

## Performance Notes

- **Rate Limiting**: 2 requests/second (enforced, automatic sleep)
- **Request Timeout**: 30 seconds per request
- **Retry Strategy**: 3 total attempts with exponential backoff
- **Key Generation**: ~1-2 seconds for RSA-2048
- **CSR Generation**: <100ms
- **Memory**: ~50MB startup, +10-20MB per operation

---

## Security Notes

🔒 **Never**:
- Log or print `SECTIGO_CLIENT_SECRET`
- Store unencrypted private keys
- Use weak passphrases (<128 bits entropy)
- Ignore SSL certificate verification errors

✅ **Always**:
- Use environment variables for credentials
- Encrypt private key at creation (automatic)
- Validate input (domain FQDN, SSL ID numeric)
- Check return values for errors

---

## Changelog

### v1.0 (Current)
- ✅ Complete OAuth2 integration
- ✅ AES-256 key encryption
- ✅ Rate limiting enforcement
- ✅ Comprehensive error handling
- ✅ Structured logging
- ✅ Input validation (domain, SSL ID)

### Future
- [ ] Certificate renewal automation
- [ ] Batch order submission
- [ ] Multi-account support
- [ ] Webhook integration
