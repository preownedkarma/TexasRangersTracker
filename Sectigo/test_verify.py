#!/usr/bin/env python3
"""
Test Verify - Tests certificate key validation and verification.
"""

import os
from crypto_utils import verify_key_payload, re_encrypt_key

def run_verification_test():
    """Test key-certificate validation."""
    print("=" * 50)
    print("CERTIFICATE VERIFICATION TEST")
    print("=" * 50)
    
    # Prompt for file paths
    key_path = input("\nPrivate key path (.key): ").strip().strip('"')
    cert_path = input("Certificate path (.crt/.pem): ").strip().strip('"')
    
    if not os.path.exists(key_path) or not os.path.exists(cert_path):
        print("[-] One or both files not found")
        return
    
    print("\n[*] Running key-certificate match verification...")
    success, message = verify_key_payload(key_path, cert_path)
    
    if success:
        print(f"[+] {message}")
    else:
        print(f"[-] {message}")

if __name__ == "__main__":
    run_verification_test()
