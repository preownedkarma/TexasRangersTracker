import os
import sys
import time
from dotenv import load_dotenv
from sectigo_client import SectigoClient
from collections import Counter, defaultdict

load_dotenv()

def get_validation_type(profile_name):
    """Classifies a profile name into DV, OV, or EV."""
    name = str(profile_name).upper()
    if "EV" in name: return "EV (Extended Validation)"
    if "DV" in name: return "DV (Domain Validation)"
    if "OV" in name: return "OV (Organization Validation)"
    return "Other / Unclassified"

def main():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("========================================")
    print("   ADVANCED CERTIFICATE INVENTORY       ")
    print("========================================")
    
    try:
        client = SectigoClient()
    except Exception as e:
        print(f"[-] Init Failed: {e}")
        return

    # 1. Fetch Profiles (The Legend)
    print("[*] Fetching Certificate Profiles (The Legend)...")
    try:
        profiles_raw = client.get_profiles()
        profile_map = {p['id']: p['name'] for p in profiles_raw}
    except:
        profile_map = {}
        print("[-] Warning: Could not fetch profiles map. Names might appear as IDs.")

    # 2. Fetch Basic Inventory (List of IDs)
    print("[*] Fetching Certificate List...")
    basic_certs = client.get_all_certificates()
    if not basic_certs:
        print("[-] No certificates found.")
        return

    total_certs = len(basic_certs)
    print(f"[+] Found {total_certs} certificates. Fetching details for each...")

    # 3. Fetch Details & Analyze
    validation_counts = Counter()
    profile_usage = Counter()
    status_counts = Counter()
    inventory_details = defaultdict(list)
    
    # Loop through each cert to get full details
    for index, basic_cert in enumerate(basic_certs, 1):
        ssl_id = basic_cert.get('sslId')
        common_name = basic_cert.get('commonName')
        
        # Print progress (overwrite line)
        sys.stdout.write(f"\r    Processing [{index}/{total_certs}]: {common_name[:30]:<30}")
        sys.stdout.flush()
        
        # --- SLOW BUT NECESSARY: Fetch Full Details ---
        try:
            /* Lines 84-115 omitted */ 

        except Exception as e:
            /* Lines 117-119 omitted */

    print("\n\n" + "="*40)
    print(f" INVENTORY COMPLETE")
    print("="*40)

    print("\n--- 1. VALIDATION LEVEL BREAKDOWN ---")
    for v_type, count in validation_counts.items():
        print(f"{v_type:<30} : {count}")

    print("\n--- 2. PROFILE USAGE (Billable Items) ---")
    sorted_profiles = sorted(profile_usage.items(), key=lambda x: x[1], reverse=True)
    for name, count in sorted_profiles:
        print(f"{name:<45} : {count}")

    print("\n--- 3. STATUS SUMMARY ---")
    for status, count in status_counts.items():
        print(f"{status:<20} : {count}")

    # Drill Down Menu
    while True:
        print("\n----------------------------------------")
        print("View detailed inventory for:")
        print("1. EV Certificates")
        print("2. OV Certificates")
        print("3. DV Certificates")
        print("Q. Quit")
        
        choice = input("Select Option: ").strip().upper()
        if choice == 'Q': break
        
        target = ""
        if choice == '1': target = "EV"
        elif choice == '2': target = "OV"
        elif choice == '3': target = "DV"
        
        if target:
if __name__ == "__main__":
    main()