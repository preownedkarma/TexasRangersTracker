import os
import sys
from dotenv import load_dotenv
from sectigo_client import SectigoClient
from collections import Counter
from datetime import datetime

# Load env vars
load_dotenv()

def print_table(headers, rows):
    """Simple helper to print a formatted ASCII table."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            /* Lines 189-190 omitted */
            
    # Create format string
    fmt = " | ".join([f"{{:<{w}}}" for w in widths])
    
    # Print Table
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))
    
    for row in rows:
        print(fmt.format(*[str(r) for r in row]))
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))

def main():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("========================================")
    print("      CERTIFICATE PROFILE INVENTORY     ")
    print("========================================")
    
    try:
        client = SectigoClient()
    except Exception as e:
        print(f"[-] Init Failed: {e}")
        return

    # 1. Fetch Basic List
    basic_certs = client.get_all_certificates()
    if not basic_certs:
        print("[-] No certificates found.")
        return

    total_count = len(basic_certs)
    profile_counts = Counter()
    status_counts = Counter()
    expiring_soon = 0
    now = datetime.now()

    print(f"\n[*] Analyzing {total_count} certificates (Fetching Full Details)...")
    
    for index, basic in enumerate(basic_certs, 1):
        ssl_id = basic.get('sslId')
        
        # PROGRESS TRACKER
        sys.stdout.write(f"\r    Processing [{index}/{total_count}] ID: {ssl_id}...")
        sys.stdout.flush()

        # FETCH FULL DETAILS (This provides status, certType, and expires)
        cert = client.get_order_status(ssl_id)
        if not cert:
            /* Lines 239-240 omitted */
        
        # 1. Count Profiles
        c_type = cert.get('certType')
        profile_name = c_type.get('name', 'Unknown Profile') if isinstance(c_type, dict) else "Unknown Profile"
        profile_counts[profile_name] += 1
        
        # 2. Count Status
        status = cert.get('status', 'Unknown')
        status_counts[status] += 1

        # 3. Check Expiry
        expires_str = cert.get('expires')
        if expires_str and status.lower() == 'issued':
    print("\n\n" + "-"*30)

    # 3. Prepare Table Data
    # Sort by Count (Descending)
    sorted_profiles = sorted(profile_counts.items(), key=lambda x: x[1], reverse=True)
    
    table_rows = []
    for name, count in sorted_profiles:
        percentage = (count / total_count) * 100
        table_rows.append([name, count, f"{percentage:.1f}%"])

    # 4. Output Report
    print(f"\nTotal Certificates Scanned: {total_count}")
    print(f"Active (Issued):            {status_counts.get('issued', 0)}")
    print(f"Expiring (90 Days):         {expiring_soon}")
    print("\n--- Usage by Profile Type ---")
    
    print_table(["Profile Name", "Count", "Usage %"], table_rows)
    
    print("\n--- Status Breakdown ---")
    status_rows = [[k, v] for k, v in status_counts.items()]
    print_table(["Status", "Count"], status_rows)

if __name__ == "__main__":
    main()