import os
from dotenv import load_dotenv
from sectigo_client import SectigoClient

load_dotenv()

def main():
    client = SectigoClient()
    domain = "sectester.mclaneco.com"
    print(f"[*] Checking DCV status for: {domain}")

    dcv_data = client.get_domain_status(domain)
    if dcv_data:
        print("DCV Data:")
        import json
        print(json.dumps(dcv_data, indent=2))
    else:
        print("No DCV data returned.")

if __name__ == "__main__":
    main()