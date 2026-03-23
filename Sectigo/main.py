import os
import sys
import json
import shutil
import warnings
import logging
from datetime import datetime
from dotenv import load_dotenv
from colorama import init, Fore, Style
from sectigo_client import SectigoClient
from crypto_utils import (
    generate_key_and_csr,
    create_pfx,
    create_zip_archive,
    convert_pkcs7_to_pem,
    extract_certs_from_bundle,
    verify_key_payload,
    re_encrypt_key,
    verify_passphrase_strength,
    generate_secure_passphrase
)

init(autoreset=True)
warnings.filterwarnings("ignore", message="PKCS#7 certificates could not be parsed as DER")
load_dotenv()

# Setup logging
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "sectigo.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BANNER = Fore.CYAN + r"""
 _______  _______  _______    _______  _______  ______    _______  _______ 
|       ||       ||       |  |       ||       ||    _ |  |       ||       |
|    ___||    ___||_     _|  |       ||___    ||   | ||  |_     _||  _____|
|   | __ |   |___   |   |    |       | ___|   ||   |_||_   |   |  | |_____ 
|   ||  ||    ___|  |   |    |      _||___    ||    __  |  |   |  |_____  |
|   |_| ||   |___   |   |    |     |_  ___|   ||   |  | |  |   |   _____| |
|_______||_______|  |___|    |_______||_______||___|  |_|  |___|  |_______|
      SECTIGO CERTIFICATE AUTOMATION CLI
""" + Style.RESET_ALL


def safe_env_get(key, default=None):
    value = os.getenv(key, default)
    if value is None:
        logger.warning(f"Environment variable {key} is not set")
    return value


def configure_environment():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)


def validate_environment():
    """Verify all required environment variables are set."""
    required_vars = ["SECTIGO_CLIENT_ID", "SECTIGO_CLIENT_SECRET"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print(Fore.RED + f"Missing environment variables: {', '.join(missing)}")
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        return False
    
    cert_dir = safe_env_get("CERT_OUTPUT_DIR", "certificates")
    staging_dir = safe_env_get("STAGING_DIR", "staging")
    
    for directory in [cert_dir, staging_dir, "logs"]:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
                logger.info(f"Created directory: {directory}")
            except Exception as e:
                print(Fore.RED + f"Failed to create directory {directory}: {e}")
                logger.error(f"Failed to create directory {directory}: {e}")
                return False
    
    return True


def prompt_domain():
    while True:
        domain = input("Enter FQDN (e.g. test.example.com): ").strip()
        if not domain:
            print(Fore.YELLOW + "Domain is required, please try again.")
            continue
        return domain


def prompt_yes_no(prompt_text):
    """Prompt user for yes/no response."""
    while True:
        response = input(f"{prompt_text} (y/n): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            print(Fore.YELLOW + "Please enter 'y' or 'n'")


def _prepare_download_directory(base_path, folder_name):
    """Create cert output directory, preserving it if a private key already exists inside."""
    target_dir = os.path.join(base_path, folder_name)

    if os.path.exists(target_dir):
        key_file = os.path.join(target_dir, f"{folder_name}.key")
        if os.path.exists(key_file):
            print(Fore.GREEN + f"[*] Found existing Private Key in target. Preserving directory.")
            return target_dir
        # Backup the old folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(base_path, f"{folder_name}_BACKUP_{timestamp}")
        try:
            print(Fore.CYAN + f"[*] Archiving existing folder to: {os.path.basename(backup_path)}")
            os.rename(target_dir, backup_path)
        except OSError as e:
            print(Fore.YELLOW + f"[!] Could not archive existing folder: {e}")

    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _stage_artifacts(source_path, folder_name):
    """Move artifacts to STAGING_DIR if configured, otherwise return source path."""
    staging_root = os.getenv("STAGING_DIR")
    if not staging_root:
        return source_path

    os.makedirs(staging_root, exist_ok=True)
    dest_path = os.path.join(staging_root, folder_name)

    if os.path.exists(dest_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(staging_root, f"{folder_name}_BACKUP_{timestamp}")
        try:
            os.rename(dest_path, backup_path)
        except OSError:
            pass

    print(Fore.CYAN + f"[*] Moving artifacts to Staging: {dest_path}")
    try:
        shutil.move(source_path, dest_path)
        print(Fore.GREEN + "[+] Move Successful.")
        return dest_path
    except Exception as e:
        print(Fore.RED + f"[-] Staging Move Failed: {e}")
        return source_path


def _open_folder(path):
    """Open a folder in Windows Explorer."""
    try:
        if os.path.exists(path):
            os.startfile(path)
        else:
            print(Fore.YELLOW + f"[-] Cannot open folder: {path}")
    except Exception as e:
        print(Fore.YELLOW + f"[-] Could not open folder: {e}")


def new_order_flow(sectigo_client):
    """Handle new certificate order/renewal workflow."""
    try:
        print(Fore.CYAN + "\n=== NEW ORDER / RENEWAL ===")
        domain = prompt_domain()

        # Load orgs and profiles upfront (needed for renewal auto-match too)
        print(Fore.CYAN + "Loading account options...")
        orgs = sectigo_client.get_organizations()
        profiles = sectigo_client.get_profiles()
        if not orgs:
            print(Fore.RED + "No organizations available")
            return
        if not profiles:
            print(Fore.RED + "No profiles available")
            return

        # --- RENEWAL DETECTION ---
        print(Fore.CYAN + "\nChecking for active certificates...")
        existing_certs = sectigo_client.list_certificates_by_domain(domain)
        active_certs = [c for c in existing_certs if c.get('status', '').lower() == 'issued']

        renewal_id = None
        selected_org = None
        selected_profile = None
        is_renewal = False

        if active_certs:
            print(Fore.GREEN + f"\nFound {len(active_certs)} active certificate(s) for {domain}:")
            print(f"  [0] {Fore.YELLOW}Start a NEW order (do not renew){Style.RESET_ALL}")
            for idx, c in enumerate(active_certs, 1):
                ssl_id_val = c.get('sslId') or c.get('id')
                expires    = c.get('expires', 'Unknown')
                serial     = c.get('serialNumber', 'N/A')
                cert_type  = c.get('certType', {})
                prof_name  = cert_type.get('name', 'Unknown') if isinstance(cert_type, dict) else str(cert_type)
                print(f"  [{idx}] SSL ID: {ssl_id_val} | Expires: {expires} | Profile: {prof_name} | Serial: {serial}")

            while True:
                try:
                    sel = int(input(f"\nSelect certificate to renew [0-{len(active_certs)}]: ").strip())
                    if 0 <= sel <= len(active_certs):
                        break
                    print(Fore.RED + f"Enter a number between 0 and {len(active_certs)}")
                except ValueError:
                    print(Fore.RED + "Invalid input, enter a number")

            if sel > 0:
                selected_cert = active_certs[sel - 1]
                renewal_id    = selected_cert.get('sslId') or selected_cert.get('id')
                is_renewal    = True

                # Auto-match org and profile from the existing cert
                old_org_id      = selected_cert.get('orgId')
                cert_type_obj   = selected_cert.get('certType', {})
                old_profile_id  = cert_type_obj.get('id') if isinstance(cert_type_obj, dict) else None

                matched_org     = next((o for o in orgs     if str(o.get('id', ''))  == str(old_org_id)),     None)
                matched_profile = next((p for p in profiles if str(p.get('id', ''))  == str(old_profile_id)), None)

                if matched_org and matched_profile:
                    print(Fore.BLUE + "\n--- RENEWAL CONFIGURATION FOUND ---")
                    print(f"  Org:     {matched_org.get('name') or matched_org.get('organizationName')}")
                    print(f"  Profile: {matched_profile.get('name') or matched_profile.get('profileName')}")
                    if input(Fore.YELLOW + "Reuse this configuration? (Y/n): ").strip().lower() != 'n':
                        selected_org     = matched_org
                        selected_profile = matched_profile
                else:
                    print(Fore.YELLOW + "[-] Could not auto-match previous config — please select manually.")
        else:
            print(Fore.YELLOW + "No active certificates found. Starting fresh order.")

        # --- MANUAL ORG / PROFILE SELECTION (if not auto-matched) ---
        if not selected_org:
            print(Fore.CYAN + "\nAvailable organizations:")
            for i, org in enumerate(orgs, 1):
                print(f"  {i}) {org.get('name') or org.get('organizationName') or str(org)}")
            while True:
                try:
                    idx = int(input("Select organization (number): ").strip()) - 1
                    if 0 <= idx < len(orgs):
                        selected_org = orgs[idx]
                        break
                    print(Fore.RED + "Invalid selection")
                except ValueError:
                    print(Fore.RED + "Invalid input")

        if not selected_profile:
            print(Fore.CYAN + "\nAvailable profiles:")
            for i, p in enumerate(profiles, 1):
                print(f"  {i}) {p.get('name') or p.get('profileName') or str(p)}")
            while True:
                try:
                    idx = int(input("Select profile (number): ").strip()) - 1
                    if 0 <= idx < len(profiles):
                        selected_profile = profiles[idx]
                        break
                    print(Fore.RED + "Invalid selection")
                except ValueError:
                    print(Fore.RED + "Invalid input")

        org_id     = selected_org.get('id') or selected_org.get('organizationId')
        profile_id = selected_profile.get('id') or selected_profile.get('profileId') or selected_profile.get('typeId')

        if not org_id:
            print(Fore.RED + "Selected organization has no valid ID")
            return
        if not profile_id:
            print(Fore.RED + "Selected profile has no valid ID")
            return

        # --- FRIENDLY NAME / COMMENTS ---
        print(Fore.CYAN + f"\n--- Friendly Name (Comments) ---")
        print(f"  Default: '{domain}'")
        comment_input = input("Enter friendly name [Enter for default]: ").strip()
        if comment_input:
            final_comment = f"{domain}{comment_input}" if comment_input.startswith(('-', ' ')) else comment_input
        else:
            final_comment = domain

        # --- EXTERNAL REQUESTER ---
        requester_input = input("\nExternal requester email(s) (comma-separated) [Enter to skip]: ").strip() or None

        # --- CONFIRMATION SUMMARY ---
        print(Fore.BLUE + "\n" + "=" * 45)
        print("  CONFIGURATION SUMMARY")
        print("=" * 45)
        print(f"  Domain:      {domain}")
        print(f"  Org:         {selected_org.get('name') or selected_org.get('organizationName')}")
        print(f"  Profile:     {selected_profile.get('name') or selected_profile.get('profileName')}")
        print(f"  Comment:     {final_comment}")
        print(f"  Requester:   {requester_input or 'None'}")
        print(f"  Order Type:  {'RENEWAL (SSL ID: ' + str(renewal_id) + ')' if is_renewal else 'NEW ORDER'}")
        print("=" * 45)

        if input(Fore.YELLOW + "\nProceed with order submission? (y/n): ").strip().lower() != 'y':
            print(Fore.RED + "Aborted.")
            return

        # --- KEY / CSR GENERATION ---
        cert_dir = safe_env_get("CERT_OUTPUT_DIR", "certificates")
        safe_name = domain.replace("*", "wildcard")
        work_dir = _prepare_download_directory(cert_dir, safe_name)
        print(Fore.CYAN + f"\nOutput directory: {work_dir}")

        passphrase = generate_secure_passphrase()
        ok, msg = verify_passphrase_strength(passphrase)
        if not ok:
            print(Fore.RED + f"Passphrase validation failed: {msg}")
            return

        # Save passphrase to .txt alongside the key
        pass_path = os.path.join(work_dir, f"{safe_name}.txt")
        with open(pass_path, 'w') as f:
            f.write(passphrase)
        os.chmod(pass_path, 0o600)

        print(Fore.CYAN + "Generating key and CSR...")
        org_name = selected_org.get('name') or selected_org.get('organizationName') or "My Organization"
        csr_path, _ = generate_key_and_csr(domain, work_dir, org_name=org_name, ou_name="Network Security", passphrase=passphrase)

        with open(csr_path, 'r') as f:
            csr_content = f.read()

        # --- ORDER SUBMISSION ---
        print(Fore.CYAN + "Submitting order to Sectigo...")
        ssl_id = sectigo_client.submit_order(
            domain=domain,
            csr_content=csr_content,
            org_id=org_id,
            profile_id=profile_id,
            renewal_id=renewal_id,
            term=397,
            comments=final_comment,
            external_requester=requester_input
        )

        if ssl_id:
            order_file = os.path.join(work_dir, "order_info.txt")
            with open(order_file, 'w') as f:
                f.write(f"Domain:      {domain}\n")
                f.write(f"SSL ID:      {ssl_id}\n")
                f.write(f"Created:     {datetime.now().isoformat()}\n")
                f.write(f"Org ID:      {org_id}\n")
                f.write(f"Profile ID:  {profile_id}\n")
                f.write(f"Order Type:  {'RENEWAL (ID: ' + str(renewal_id) + ')' if is_renewal else 'NEW ORDER'}\n")
                f.write(f"Comment:     {final_comment}\n")

            print(Fore.GREEN + "\n" + "=" * 45)
            print(f"  [+] Order Submitted Successfully!")
            print(f"  [+] SSL ID: {ssl_id}")
            print("=" * 45)
            print(Fore.YELLOW + "[!] Use 'Check Status / Download' in ~5 minutes to retrieve the certificate.")
            logger.info(f"{'Renewal' if is_renewal else 'New'} order submitted for {domain}, SSL ID: {ssl_id}")
        else:
            print(Fore.RED + "Order submission failed.")

    except Exception as e:
        print(Fore.RED + f"Error in order flow: {e}")
        logger.exception(f"Error in order flow: {e}")


def check_status_flow(sectigo_client):
    """Handle status check and certificate download."""
    try:
        print(Fore.CYAN + "\n=== CHECK STATUS / DOWNLOAD ===")
        
        lookup_type = input("Enter SSL ID or domain: ").strip()
        if not lookup_type:
            print(Fore.YELLOW + "Input required")
            return
        
        ssl_id = None
        domain = None
        
        # Try to determine if it's an SSL ID (numeric) or domain
        if lookup_type.isdigit():
            ssl_id = int(lookup_type)
        else:
            domain = lookup_type
            # Try to find SSL ID by domain
            print(Fore.CYAN + "Searching for certificate by domain...")
            certs = sectigo_client.list_certificates_by_domain(domain)
            if certs:
                print(Fore.GREEN + "Found certificates:")
                for i, cert in enumerate(certs):
                    ssl_id_val = cert.get('sslId') or cert.get('id')
                    common_name = cert.get('commonName') or cert.get('commonname') or ''
                    status = cert.get('status') or 'Unknown'
                    requested = cert.get('requested') or ''
                    expires = cert.get('expires') or ''
                    line = f"  {i+1}) SSL ID: {ssl_id_val}"
                    if common_name:
                        line += f" | CN: {common_name}"
                    line += f" | Status: {status}"
                    if requested:
                        line += f" | Requested: {requested}"
                    if expires:
                        line += f" | Expires: {expires}"
                    print(line)

                choice = input("Select certificate (number): ").strip()
                try:
                    choice_idx = int(choice) - 1
                    if choice_idx < 0 or choice_idx >= len(certs):
                        print(Fore.RED + "Invalid selection")
                        return
                    ssl_id = certs[choice_idx].get('sslId') or certs[choice_idx].get('id')
                except ValueError:
                    print(Fore.RED + "Invalid input")
                    return
            else:
                print(Fore.YELLOW + "No certificates found for this domain")
                return
        
        if not ssl_id:
            print(Fore.RED + "Could not determine SSL ID")
            return
        
        # Get order status
        print(Fore.CYAN + f"Fetching status for SSL ID: {ssl_id}...")
        status_data = sectigo_client.get_order_status(ssl_id)
        if not status_data:
            print(Fore.RED + "Could not fetch status")
            return
        
        print(Fore.GREEN + "\n=== CERTIFICATE STATUS ===")
        for key, value in status_data.items():
            print(f"  {key}: {value}")
        
        # Try to download certificate if issued
        status = status_data.get('status', '')
        if status.lower() == 'issued':
            if prompt_yes_no("Download certificate?"):
                print(Fore.CYAN + "Downloading certificate...")
                raw_content = sectigo_client.collect_certificate(ssl_id)

                if not raw_content:
                    print(Fore.YELLOW + "\n[!] SYNCHRONIZATION DELAY DETECTED")
                    print(Fore.YELLOW + "    Sectigo reports ISSUED but files are not yet available.")
                    print(Fore.CYAN  + "    Please wait 5-15 minutes and try again.")
                    return

                common_name = status_data.get('commonName', str(ssl_id))
                safe_name = common_name.replace('*', 'wildcard')
                cert_dir = safe_env_get("CERT_OUTPUT_DIR", "certificates")
                work_dir = _prepare_download_directory(cert_dir, safe_name)

                # Save P7B if applicable, then convert to PEM
                if "BEGIN PKCS7" in raw_content:
                    p7b_path = os.path.join(work_dir, f"{safe_name}.p7b")
                    with open(p7b_path, 'w') as f:
                        f.write(raw_content)
                    print(Fore.GREEN + f"[+] Saved PKCS#7 Bundle: {p7b_path}")
                    cert_content = convert_pkcs7_to_pem(raw_content)
                else:
                    cert_content = raw_content

                # Split bundle into components
                components = extract_certs_from_bundle(cert_content)
                if components:
                    if components['leaf']:
                        crt_path = os.path.join(work_dir, f"{safe_name}.crt")
                        with open(crt_path, 'w') as f:
                            f.write(components['leaf'])
                        print(Fore.GREEN + f"[+] Saved Leaf Certificate:      {crt_path}")

                    if components['intermediates']:
                        chain_path = os.path.join(work_dir, f"{safe_name}-intermediate.crt")
                        with open(chain_path, 'w') as f:
                            f.write(components['intermediates'])
                        print(Fore.GREEN + f"[+] Saved Intermediate Chain:    {chain_path}")

                    if components['root']:
                        root_path = os.path.join(work_dir, f"{safe_name}-root.crt")
                        with open(root_path, 'w') as f:
                            f.write(components['root'])
                        print(Fore.GREEN + f"[+] Saved Root Certificate:      {root_path}")

                    if components['full_chain']:
                        full_path = os.path.join(work_dir, f"{safe_name}-fullchain.crt")
                        with open(full_path, 'w') as f:
                            f.write(components['full_chain'])
                        print(Fore.GREEN + f"[+] Saved Full Chain:            {full_path}")

                # PFX generation (only if matching private key exists)
                key_path = os.path.join(work_dir, f"{safe_name}.key")
                pfx_path = os.path.join(work_dir, f"{safe_name}.pfx")

                if os.path.exists(key_path):
                    print(Fore.CYAN + f"\n[?] Friendly Name — Current CN: {common_name}")
                    suffix = input(Fore.YELLOW + "    Append identifier (e.g. IIS01) [Enter to skip]: ").strip()
                    friendly_name = f"{common_name} - {suffix}" if suffix else common_name
                    create_pfx(key_path, cert_content, pfx_path, friendly_name=friendly_name)
                else:
                    print(Fore.YELLOW + f"\n[!] No private key found at {key_path} — skipping PFX generation.")

                # All conversions complete — ZIP everything inside work_dir first
                print(Fore.CYAN + "\n[*] Creating bundle archive...")
                create_zip_archive(work_dir, os.path.join(work_dir, f"{safe_name}-Bundle.zip"))

                # Only now move to staging
                print(Fore.CYAN + "[*] Staging artifacts...")
                final_path = _stage_artifacts(work_dir, safe_name)

                logger.info(f"Certificate artifacts saved for SSL ID {ssl_id} in {final_path}")
                print(Fore.CYAN + "[*] Opening output folder...")
                _open_folder(final_path)
        else:
            print(Fore.YELLOW + f"Certificate status is '{status}', not ready for download")
    
    except Exception as e:
        print(Fore.RED + f"Error in status flow: {e}")
        logger.exception(f"Error in status flow: {e}")


def check_passphrase_flow():
    """Validate passphrase against key and certificate."""
    try:
        print(Fore.CYAN + "\n=== VALIDATE PASSPHRASE + KEY ===")
        key_path = input("Path to private key (.key): ").strip().strip('"')
        target_path = input("Path to cert/csr (.crt/.csr): ").strip().strip('"')
        
        if not os.path.exists(key_path) or not os.path.exists(target_path):
            print(Fore.RED + "File path is invalid. Ensure both key and cert/csr files exist.")
            return
        
        success, message = verify_key_payload(key_path, target_path)
        print((Fore.GREEN if success else Fore.RED) + message)
        if success:
            logger.info(f"Key validation successful for {key_path}")
        else:
            logger.warning(f"Key validation failed for {key_path}")
    
    except Exception as e:
        print(Fore.RED + f"Error in passphrase validation: {e}")
        logger.exception(f"Error in passphrase validation: {e}")


def generate_passphrase_flow():
    """Generate and optionally save secure passphrase."""
    try:
        print(Fore.CYAN + "\n=== GENERATE SECURE PASSPHRASE ===")
        passphrase = generate_secure_passphrase()
        ok, msg = verify_passphrase_strength(passphrase)
        print(Fore.GREEN + f"Generated: {passphrase} ({len(passphrase)} chars)")
        print(Fore.GREEN + f"Strength: {msg}")
        
        if prompt_yes_no("Save passphrase to file?"):
            filename = input("Filename (e.g. passphrase.txt): ").strip()
            if filename:
                try:
                    with open(filename, 'w') as f:
                        f.write(passphrase)
                    os.chmod(filename, 0o600)
                    print(Fore.GREEN + f"Passphrase saved to {filename} (permissions: 0o600)")
                    logger.info(f"Passphrase saved to {filename}")
                except Exception as e:
                    print(Fore.RED + f"Failed to save passphrase: {e}")
                    logger.error(f"Failed to save passphrase: {e}")
    
    except Exception as e:
        print(Fore.RED + f"Error in passphrase generation: {e}")
        logger.exception(f"Error in passphrase generation: {e}")


def main_menu():
    """Interactive main menu for certificate operations."""
    configure_environment()
    
    if not validate_environment():
        print(Fore.RED + "Environment validation failed. Exiting.")
        return
    
    print(BANNER)
    sectigo_client = None

    try:
        print(Fore.CYAN + "Initializing Sectigo client...")
        sectigo_client = SectigoClient()
        print(Fore.GREEN + "✓ Sectigo client initialized successfully")
        logger.info("Sectigo client initialized successfully")
    except Exception as e:
        print(Fore.RED + f"✗ Could not initialize SectigoClient: {e}")
        logger.error(f"Could not initialize SectigoClient: {e}")
        return

    while True:
        try:
            print("\n" + Fore.CYAN + "=" * 50)
            print("MAIN MENU")
            print("=" * 50)
            print("1) New Order/Renewal")
            print("2) Check Status/Download")
            print("3) Validate Passphrase + Key")
            print("4) Generate Secure Passphrase")
            print("q) Quit")
            print("=" * 50)
            choice = input(Fore.YELLOW + "Select option: ").strip().lower()

            if choice == '1':
                if not sectigo_client:
                    print(Fore.RED + "Sectigo client is unavailable")
                    continue
                new_order_flow(sectigo_client)

            elif choice == '2':
                if not sectigo_client:
                    print(Fore.RED + "Sectigo client is unavailable")
                    continue
                check_status_flow(sectigo_client)

            elif choice == '3':
                check_passphrase_flow()

            elif choice == '4':
                generate_passphrase_flow()

            elif choice == 'q':
                print(Fore.CYAN + "Goodbye!")
                logger.info("Application closed by user")
                break

            else:
                print(Fore.YELLOW + "Invalid selection, try again.")
        
        except KeyboardInterrupt:
            print(Fore.YELLOW + "\n\nApplication interrupted by user")
            logger.info("Application interrupted by user (Ctrl+C)")
            break
        except Exception as e:
            print(Fore.RED + f"Unexpected error in menu: {e}")
            logger.exception(f"Unexpected error in menu: {e}")
            print(Fore.YELLOW + "Attempting to continue...")


if __name__ == '__main__':
    try:
        main_menu()
    except Exception as e:
        print(Fore.RED + f"Fatal error: {e}")
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
