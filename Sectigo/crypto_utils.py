import os
import re
import math
import shutil
import secrets
import string
import requests
import logging
from datetime import datetime
from colorama import Fore, Style
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12

logger = logging.getLogger(__name__)

def generate_secure_passphrase(length=32):
    """Generate a secure passphrase with minimum 128 bits entropy from multiple character categories."""
    charset_upper = string.ascii_uppercase
    charset_lower = string.ascii_lowercase
    charset_digits = string.digits
    charset_special = "!@#$%^&*-_=+[]{}|:;<>?,.~"
    
    while True:
        # Ensure at least one character from each category
        passphrase = (
            secrets.choice(charset_upper) +
            secrets.choice(charset_lower) +
            secrets.choice(charset_digits) +
            secrets.choice(charset_special) +
            ''.join(secrets.choice(charset_upper + charset_lower + charset_digits + charset_special) 
                    for _ in range(length - 4))
        )
        
        # Shuffle to avoid predictable pattern
        pass_list = list(passphrase)
        for i in range(len(pass_list)):
            j = secrets.randbelow(len(pass_list))
            pass_list[i], pass_list[j] = pass_list[j], pass_list[i]
        
        passphrase = ''.join(pass_list)
        
        # Verify entropy requirement
        has_upper = any(c.isupper() for c in passphrase)
        has_lower = any(c.islower() for c in passphrase)
        has_digit = any(c.isdigit() for c in passphrase)
        has_special = any(c in "!@#$%^&*-_=+[]{}|:;<>?,.~" for c in passphrase)
        
        if all([has_upper, has_lower, has_digit, has_special]):
            entropy = calculate_entropy(passphrase)
            if entropy >= 128:  # Minimum 128 bits entropy
                return passphrase

def calculate_entropy(password):
    """Calculate entropy bits in a password."""
    charset_size = 0
    if any(c.isupper() for c in password): charset_size += 26
    if any(c.islower() for c in password): charset_size += 26
    if any(c.isdigit() for c in password): charset_size += 10
    if any(c in "!@#$%^&*-_=+[]{}|:;<>?,.~" for c in password): charset_size += 16
    
    entropy = len(password) * math.log2(charset_size) if charset_size > 0 else 0
    return entropy

def verify_passphrase_strength(password):
    """Verify passphrase meets minimum strength requirements."""
    MIN_ENTROPY = 128  # bits
    entropy = calculate_entropy(password)
    
    if entropy < MIN_ENTROPY:
        return False, f"Insufficient entropy: {entropy:.1f} bits (need {MIN_ENTROPY})"
    return True, f"Entropy: {entropy:.1f} bits"

def prepare_work_directory(domain, base_path="certificates"):
    """Prepare a work directory for certificate operations."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{domain}_{timestamp}"
    target_dir = os.path.join(base_path, folder_name)
    
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        logger.info(f"Created work directory: {target_dir}")
    
    return target_dir

def generate_key_and_csr(domain, work_dir, org_name="My Organization", ou_name="IT", passphrase=None):
    """Generate an encrypted RSA private key and corresponding CSR."""
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)

    # Sanitize the domain for file paths (dots are valid on Windows)
    safe_domain = domain.replace("*", "wildcard")

    key_path = os.path.join(work_dir, f"{safe_domain}.key")
    csr_path = os.path.join(work_dir, f"{safe_domain}.csr")
    
    # Generate passphrase if not provided
    if passphrase is None:
        passphrase = generate_secure_passphrase()
    
    # Generate RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Save encrypted private key
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode('utf-8'))
        ))
    os.chmod(key_path, 0o600)
    
    logger.info(f"Generated encrypted private key: {key_path}")

    # Generate CSR
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou_name),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    ])).sign(private_key, hashes.SHA256(), default_backend())

    with open(csr_path, "wb") as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))
    os.chmod(csr_path, 0o600)
    
    logger.info(f"Generated CSR: {csr_path}")
    
    print(f"{Fore.GREEN}[+] Key/CSR Generation Complete{Style.RESET_ALL}")
    print(f"    Domain:    {domain}")
    print(f"    Key:       {key_path}")
    print(f"    CSR:       {csr_path}")
    print(f"    Passphrase: {passphrase} (128+ bit entropy)")
    
    return csr_path, key_path

def verify_key_payload(key_path, target_path):
    """Verify private key matches certificate or CSR."""
    try:
        # Try to read the private key (assuming it's encrypted)
        passphrase_file = os.path.splitext(key_path)[0] + ".txt"
        password = None
        
        if os.path.exists(passphrase_file):
            with open(passphrase_file, 'r') as f:
                password = f.read().strip().encode('utf-8')
        else:
            password = input("Private key passphrase: ").encode('utf-8')
        
        with open(key_path, 'rb') as f:
            key_data = f.read()
        
        try:
            private_key = serialization.load_pem_private_key(key_data, password=password, backend=default_backend())
        except Exception as e:
            return False, f"Failed to load private key: {e}"
        
        # Load the target (CSR or certificate)
        with open(target_path, 'rb') as f:
            target_data = f.read()
        
        try:
            # Try as CSR first
            csr_obj = x509.load_pem_x509_csr(target_data, backend=default_backend())
            target_key = csr_obj.public_key()
            target_type = "CSR"
        except:
            try:
                # Try as certificate
                cert_obj = x509.load_pem_x509_certificate(target_data, backend=default_backend())
                target_key = cert_obj.public_key()
                target_type = "Certificate"
            except Exception as e:
                return False, f"Could not load CSR or Certificate: {e}"
        
        # Compare moduli for RSA keys
        private_modulus = private_key.public_key().public_numbers().n
        target_modulus = target_key.public_numbers().n
        
        if private_modulus == target_modulus:
            return True, f"✓ Private key matches {target_type}"
        else:
            return False, f"✗ Private key does NOT match {target_type}"
    
    except Exception as e:
        return False, f"Error during validation: {e}"

def extract_certs_from_bundle(pem_data):
    """Extract individual certificates from a PEM bundle."""
    pattern = re.compile(r'(-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----)')
    matches = pattern.findall(pem_data)
    
    if not matches:
        logger.warning("No certificates found in bundle")
        return {"leaf": "", "intermediates": "", "root": "", "full_chain": ""}
    
    all_certs = [x509.load_pem_x509_certificate(m.encode(), default_backend()) for m in matches]
    
    # Simple heuristic: first is leaf, last is root (if self-signed), rest are intermediates
    leaf_obj = all_certs[0]
    intermediates = []
    root_obj = None

    if len(all_certs) > 1:
        remaining = all_certs[1:]
        last_cert = remaining[-1]
        
        # Check if last cert is self-signed (root)
        if last_cert.issuer == last_cert.subject:
            root_obj = last_cert
            intermediates = remaining[:-1]
        else:
            # No root in bundle, just intermediates
            intermediates = remaining

    def to_pem(cert_obj):
        return cert_obj.public_bytes(serialization.Encoding.PEM).decode('utf-8')

    leaf_str = to_pem(leaf_obj) if leaf_obj else ""
    root_str = to_pem(root_obj) if root_obj else ""
    inter_strs = [to_pem(c) for c in intermediates]
    inter_str = "\n".join(inter_strs)
    
    full_chain_list = [leaf_str] + inter_strs + ([root_str] if root_str else [])
    full_chain_str = "\n".join(full_chain_list).strip()

    return {
        "leaf": leaf_str,
        "intermediates": inter_str,
        "root": root_str,
        "full_chain": full_chain_str
    }

def create_pfx(key_path, cert_pem, pfx_path, password=None, friendly_name=None):
    """Create a PKCS12 (PFX) file from key and certificates."""
    try:
        # Load password if available
        key_password = None
        if password:
            key_password = password.encode('utf-8')
        else:
            passphrase_file = os.path.splitext(key_path)[0] + ".txt"
            if os.path.exists(passphrase_file):
                with open(passphrase_file, 'r') as f:
                    key_password = f.read().strip().encode('utf-8')
        
        # Load private key
        with open(key_path, "rb") as f:
            key_data = f.read()
        
        private_key = serialization.load_pem_private_key(
            key_data, 
            password=key_password, 
            backend=default_backend()
        )
        
        # Parse certificates from PEM
        pattern = re.compile(r'(-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----)')
        matches = pattern.findall(cert_pem)
        if not matches:
            logger.error("No certificates found in PEM data")
            return False

        leaf_cert = x509.load_pem_x509_certificate(matches[0].encode(), default_backend())
        cas = [x509.load_pem_x509_certificate(m.encode(), default_backend()) for m in matches[1:]]

        # Create PKCS12
        pfx_data = pkcs12.serialize_key_and_certificates(
            name=friendly_name.encode('utf-8') if friendly_name else None,
            key=private_key,
            cert=leaf_cert,
            cas=cas if cas else None,
            encryption_algorithm=serialization.BestAvailableEncryption(key_password) if key_password else serialization.NoEncryption()
        )

        with open(pfx_path, "wb") as f:
            f.write(pfx_data)
        os.chmod(pfx_path, 0o600)
        
        logger.info(f"Generated PFX: {pfx_path}")
        print(f"{Fore.GREEN}[+] Generated PFX: {pfx_path}{Style.RESET_ALL}")
        return True

    except Exception as e:
        logger.error(f"PFX Generation Failed: {e}")
        print(f"{Fore.RED}[-] PFX Generation Failed: {e}{Style.RESET_ALL}")
        return False

def re_encrypt_key(key_path, new_password=None):
    """Re-encrypt a private key with a new password."""
    try:
        old_password = input("Current key password: ").encode('utf-8')
        
        with open(key_path, "rb") as f:
            key_data = f.read()
        
        private_key = serialization.load_pem_private_key(
            key_data,
            password=old_password,
            backend=default_backend()
        )
        
        if new_password is None:
            new_password = generate_secure_passphrase()
        
        # Re-encrypt with new password
        new_key_data = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(new_password.encode('utf-8'))
        )
        
        with open(key_path, "wb") as f:
            f.write(new_key_data)
        os.chmod(key_path, 0o600)
        
        logger.info(f"Key re-encrypted: {key_path}")
        return True
    
    except Exception as e:
        logger.error(f"Key re-encryption failed: {e}")
        return False

def create_zip_archive(work_dir, output_path=None):
    """Create a ZIP archive of certificate files."""
    try:
        if output_path is None:
            output_path = work_dir + ".zip"
        
        shutil.make_archive(output_path.replace('.zip', ''), 'zip', work_dir)
        logger.info(f"Created archive: {output_path}")
        print(f"{Fore.GREEN}[+] Certificate archive: {output_path}{Style.RESET_ALL}")
        return output_path
    
    except Exception as e:
        logger.error(f"Archive creation failed: {e}")
        return None

def convert_pkcs7_to_pem(pkcs7_data):
    """Convert PKCS7 format to PEM (or pass through if already PEM)."""
    if "-----BEGIN CERTIFICATE-----" in pkcs7_data:
        return pkcs7_data
    
    # If it's base64-encoded PKCS7, try to parse it
    try:
        from cryptography.hazmat.primitives.serialization import pkcs7
        if isinstance(pkcs7_data, str):
            pkcs7_data = pkcs7_data.encode('utf-8')
        
        p7 = pkcs7.load_der_pkcs7_data(pkcs7_data)
        certs = p7.certificates
        
        pem_certs = []
        for cert in certs:
            pem_certs.append(cert.public_bytes(serialization.Encoding.PEM).decode('utf-8'))
        
        return "\n".join(pem_certs)
    except:
        return pkcs7_data
