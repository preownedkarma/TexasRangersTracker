#!/usr/bin/env python3
"""
Test Authentication - Verifies Sectigo API connectivity.
"""

import os
import sys
from dotenv import load_dotenv
from sectigo_client import SectigoClient

# Load env vars from .env file
load_dotenv()

try:
    print("[*] Initializing Sectigo client...")
    client = SectigoClient()
    print("[+] Client initialized")
    
    print("[*] Attempting to fetch organizations...")
    orgs = client.get_organizations()
    
    if orgs:
        print(f"\n[+] Success! Found {len(orgs)} organization(s):")
        for i, org in enumerate(orgs, 1):
            org_name = org.get('organizationName', 'Unknown')
            org_id = org.get('organizationId', 'N/A')
            print(f"    {i}. {org_name} (ID: {org_id})")
    else:
        print("[!] No organizations found or empty response")
    
    print("\n[+] Authentication test PASSED")

except Exception as e:
    print(f"\n[-] Authentication test FAILED")
    print(f"[-] Error: {e}")
    sys.exit(1)
