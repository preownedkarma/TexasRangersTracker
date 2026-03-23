#!/usr/bin/env python3
"""
Check Passphrase Tool - Validates PFX files and verifies key-certificate pairs.
"""

import os
import sys
from colorama import init, Fore, Style
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

init(autoreset=True)

def verify_pfx(pfx_path, password):
    """Verify that a passphrase can unlock a PFX file."""
    print(f"\n{Fore.CYAN}[*] TEST 1: PFX Unlock Test")
    print(f"    Target: {os.path.basename(pfx_path)}{Style.RESET_ALL}")
    try:
        with open(pfx_path, "rb") as f:
            pfx_data = f.read()
        
        # Try to load the PFX with the provided password
        pkcs12.load_key_and_certificates(
            pfx_data,
            password.encode('utf-8') if isinstance(password, str) else password,
            backend=default_backend()
        )
        print(f"    {Fore.GREEN}[+] SUCCESS: The passphrase is VALID and unlocks the PFX.{Style.RESET_ALL}")
        return True
        
    except ValueError:
        print(f"    {Fore.RED}[-] FAILED: Invalid passphrase. The PFX could not be unlocked.{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"    {Fore.RED}[-] ERROR: Could not process file. ({e}){Style.RESET_ALL}")
        return False

def verify_key_pair(cert_path, key_path, key_password=None):
    """Verify that a certificate and private key form a valid pair."""
    print(f"\n{Fore.CYAN}[*] TEST 2: Certificate & Private Key Mathematical Match")
    print(f"    Cert: {os.path.basename(cert_path)}")
    print(f"    Key:  {os.path.basename(key_path)}{Style.RESET_ALL}")
    
    try:
        # Load the certificate
        with open(cert_path, "rb") as f:
            cert_data = f.read()
        
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        
        # Load the private key (may be encrypted)
        with open(key_path, "rb") as f:
            key_data = f.read()
        
        # Try to load with password first, then without
        private_key = None
        try:
            if key_password:
                private_key = serialization.load_pem_private_key(
                    key_data,
                    password=key_password.encode('utf-8') if isinstance(key_password, str) else key_password,
                    backend=default_backend()
                )
            else:
                private_key = serialization.load_pem_private_key(
                    key_data,
                    password=None,
                    backend=default_backend()
                )
        except TypeError:
            # Key is encrypted, ask for password
            if not key_password:
                key_password = input(f"    Enter key password: ")
                private_key = serialization.load_pem_private_key(
                    key_data,
                    password=key_password.encode('utf-8'),
                    backend=default_backend()
                )
            else:
                raise
        
        # Compare the public numbers (modulus for RSA)
        cert_public_numbers = cert.public_key().public_numbers()
        key_public_numbers = private_key.public_key().public_numbers()
        
        if cert_public_numbers == key_public_numbers:
            print(f"    {Fore.GREEN}[+] SUCCESS: Certificate and Private Key match mathematically!{Style.RESET_ALL}")
            return True
        else:
            print(f"    {Fore.RED}[-] FAILED: Certificate and Private Key DO NOT match.{Style.RESET_ALL}")
            return False

    except Exception as e:
        print(f"    {Fore.RED}[-] ERROR: Could not read files for comparison. ({e}){Style.RESET_ALL}")
        return False

def main():
    """Interactive menu for passphrase verification."""
    print(Fore.CYAN + "\n==========================================")
    print("     PASSPHRASE & KEY VERIFICATION TOOL")
    print("==========================================" + Style.RESET_ALL)
    
    while True:
        print("\n1) Verify PFX Password")
        print("2) Check Key-Certificate Match")
        print("3) Exit")
        choice = input("Select option: ").strip()
        
        if choice == '1':
            pfx_path = input("PFX file path: ").strip().strip('"')
            password = input("Passphrase: ").strip()
            
            if os.path.exists(pfx_path):
                verify_pfx(pfx_path, password)
            else:
                print(Fore.RED + "File not found" + Style.RESET_ALL)
        
        elif choice == '2':
            cert_path = input("Certificate path (.crt/.pem): ").strip().strip('"')
            key_path = input("Private key path (.key): ").strip().strip('"')
            
            if os.path.exists(cert_path) and os.path.exists(key_path):
                verify_key_pair(cert_path, key_path)
            else:
                print(Fore.RED + "One or both files not found" + Style.RESET_ALL)
        
        elif choice == '3':
            print(Fore.CYAN + "Goodbye!" + Style.RESET_ALL)
            break
        
        else:
            print(Fore.YELLOW + "Invalid selection" + Style.RESET_ALL)

if __name__ == '__main__':
    main()
