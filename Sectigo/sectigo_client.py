import os
import json
import time
import requests
import re
import logging
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SectigoClient:
    def __init__(self):
        self.client_id = os.getenv("SECTIGO_CLIENT_ID")
        self.client_secret = os.getenv("SECTIGO_CLIENT_SECRET")
        self.base_url = "https://admin.enterprise.sectigo.com/api"
        self.auth_url = "https://auth.sso.sectigo.com/auth/realms/apiclients/protocol/openid-connect/token"
        self.token = None
        self.token_expires_at = 0
        
        if not self.client_id or not self.client_secret:
            raise ValueError("SECTIGO_CLIENT_ID and SECTIGO_CLIENT_SECRET must be set in environment variables")
        
        # Rate limiting
        self.request_times = []
        self.rate_limit_per_second = 2
    
    def _validate_ssl_id(self, ssl_id):
        """Validate SSL ID format."""
        if not ssl_id:
            raise ValueError("ssl_id cannot be empty")
        if isinstance(ssl_id, str) and not ssl_id.isdigit():
            raise ValueError(f"Invalid ssl_id format: {ssl_id}")
        return str(ssl_id)
    
    def _validate_domain(self, domain):
        """Validate domain format."""
        FQDN_REGEX = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'
        if not domain or len(domain) > 253:
            raise ValueError("Domain must be 1-253 characters")
        
        if domain.startswith('*.'):
            if not re.match(FQDN_REGEX, domain[2:]):
                raise ValueError("Invalid wildcard domain format")
        else:
            if not re.match(FQDN_REGEX, domain):
                raise ValueError("Invalid domain format")
        return domain
    
    def _check_rate_limit(self):
        """Enforce rate limiting."""
        now = time.time()
        # Remove requests older than 1 second
        self.request_times = [t for t in self.request_times if now - t < 1.0]
        
        if len(self.request_times) >= self.rate_limit_per_second:
            sleep_time = 1.0 - (now - self.request_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.request_times.append(now)

    def _get_headers(self):
        """Checks token freshness and returns auth headers."""
        # Refresh if token is missing or expired
        if not self.token or time.time() >= self.token_expires_at:
            self.authenticate()
        return {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}

    def _get_session(self):
        """Creates a session with built-in retry logic for network stability."""
        session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('https://', adapter)
        return session

    def authenticate(self):
        """Exchanges Client ID/Secret for a Bearer Token with expiration tracking."""
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            response = requests.post(self.auth_url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            self.token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self.token_expires_at = time.time() + expires_in - 300  # 5 min buffer
            
            logger.debug(f"Token acquired, expires in {expires_in}s")
        except requests.HTTPError as e:
            logger.error(f"Authentication failed: HTTP {e.response.status_code}")
            raise ValueError("API authentication failed. Check SECTIGO_CLIENT_ID and SECTIGO_CLIENT_SECRET.")
        except requests.Timeout:
            logger.error("Authentication timeout")
            raise ValueError("API authentication timeout. Check network connectivity.")
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise

    def get_organizations(self):
        """Fetches list of available organizations with increased timeout."""
        self._check_rate_limit()
        url = f"{self.base_url}/organization/v1"
        try:
            response = self._get_session().get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"get_organizations request failed: {e}", exc_info=True)
            return []

    def get_profiles(self):
        """Fetches available certificate profiles with increased timeout."""
        self._check_rate_limit()
        url = f"{self.base_url}/ssl/v1/types"
        try:
            response = self._get_session().get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"get_profiles request failed: {e}", exc_info=True)
            return []

    def get_order_status(self, ssl_id):
        ssl_id = self._validate_ssl_id(ssl_id)
        self._check_rate_limit()
        
        url = f"{self.base_url}/ssl/v1/{ssl_id}"
        try:
            response = self._get_session().get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            logger.info(f"Retrieved order status for SSL ID: {ssl_id}")
            return response.json()
        except requests.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for SSL ID {ssl_id}: {e}")
            return None
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error(f"Network error fetching order {ssl_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching order {ssl_id}: {e}")
            return None

    def get_all_certificates(self):
        """Fetches all certificates from Sectigo API with pagination."""
        url = f"{self.base_url}/ssl/v1"
        certs = []
        position = 0
        size = 100

        while True:
            self._check_rate_limit()
            params = {"size": size, "position": position}
            try:
                resp = self._get_session().get(url, headers=self._get_headers(), params=params, timeout=30)
                resp.raise_for_status()
                batch = resp.json() or []
            except requests.RequestException as e:
                logger.error(f"Error fetching certificates page {position}: {e}")
                break

            certs.extend(batch)
            if len(batch) < size:
                break
            position += size

        return certs

    def get_renewal_candidate(self, domain, renewal_window_days=90):
        """Return sslId of candidate in renewal window (placeholder)."""
        if not domain:
            raise ValueError("domain is required")
        # placeholder: implement actual lookup logic
        return None

    def get_domain_status(self, domain):
        """Fetches domain DCV status."""
        if not domain:
            raise ValueError("domain is required")

        # Sectigo validates domains using the /dcv/v1/validation endpoint.
        # The /dcv/v1/domain endpoint may produce 404 for validated records.
        url = f"{self.base_url}/dcv/v1/validation"
        params = {"domain": domain}

        try:
            resp = self._get_session().get(url, headers=self._get_headers(), params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Domain status error for {domain}: {e}")
            return None

    def get_latest_order_id(self, domain):
        """Fetch latest order ID by domain."""
        if not domain:
            raise ValueError("domain is required")
        certs = self.list_certificates_by_domain(domain)
        if not certs:
            return None
        certs_sorted = sorted(certs, key=lambda c: c.get('sslId', 0), reverse=True)
        return certs_sorted[0].get('sslId') if certs_sorted else None

    def rescue_from_sectigo_search(self, ssl_id):
        """Fallback A: search Sectigo API by serial number when direct collect fails."""
        print(f"    [*] Attempting Internal Serial Search rescue...")
        order = self.get_order_status(ssl_id)
        if not order:
            return None

        serial_raw = order.get('serialNumber')
        if not serial_raw:
            print("    [-] Rescue failed: No Serial Number in order details.")
            return None

        search_url = f"{self.base_url}/ssl/v1"
        params = {"serialNumber": serial_raw}
        try:
            response = requests.get(search_url, headers=self._get_headers(), params=params, timeout=15)
            if response.status_code == 200:
                results = response.json()
                if results and isinstance(results, list):
                    pem = results[0].get('certificate') or results[0].get('crt')
                    if pem and "-----BEGIN CERTIFICATE-----" in pem:
                        print("    [+] Internal Rescue Successful!")
                        return pem
        except Exception as e:
            print(f"    [-] Internal Rescue Error: {e}")
        return None

    def rescue_from_ct_logs(self, ssl_id):
        """Fallback B: download certificate from public CT logs (crt.sh) using serial number."""
        print(f"    [*] Initiating CT Log Rescue (crt.sh)...")
        order = self.get_order_status(ssl_id)
        if not order:
            return None

        serial_raw = order.get('serialNumber')
        if not serial_raw:
            return None

        serial_clean = serial_raw.replace(":", "").lower()
        print(f"    [*] Serial: {serial_clean}")

        crt_url = f"https://crt.sh/?serial={serial_clean}&output=json"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    print(f"    [*] Retry {attempt}/3...")
                response = requests.get(crt_url, headers=headers, timeout=45)
                if response.status_code != 200:
                    print(f"    [-] crt.sh query failed: {response.status_code}")
                    if response.status_code in [502, 503, 504]:
                        time.sleep(5)
                        continue
                    return None

                data = response.json()
                if not data:
                    print("    [-] No records found in CT logs yet.")
                    return None

                crt_id = data[0]['id']
                dl_url = f"https://crt.sh/?d={crt_id}"
                print(f"    [+] Record found (ID: {crt_id}). Downloading...")
                cert_resp = requests.get(dl_url, headers=headers, timeout=45)
                if cert_resp.status_code == 200 and "-----BEGIN CERTIFICATE-----" in cert_resp.text:
                    print("    [+] CT Log Rescue Successful!")
                    return cert_resp.text
                break
            except requests.exceptions.Timeout:
                print("    [!] Connection timed out.")
                time.sleep(3)
            except Exception as e:
                print(f"    [-] CT Log Rescue Error: {e}")
                break
        return None

    def collect_certificate(self, ssl_id):
        """Download issued certificate content for given ssl_id.

        Strategy:
        1. Try P7B format
        2. Try X509 (PEM) format
        3. Try extracting cert from detail JSON response
        """
        if not ssl_id:
            raise ValueError('ssl_id is required')
        self._check_rate_limit()
        download_url = f"{self.base_url}/ssl/v1/{ssl_id}/collect"

        # 1. P7B
        try:
            response = requests.get(download_url, headers=self._get_headers(), params={"format": "p7b"}, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception:
            pass

        # 2. X509 (PEM)
        try:
            logger.info(f"P7B unavailable for {ssl_id}, trying X509...")
            response = requests.get(download_url, headers=self._get_headers(), params={"format": "x509"}, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception:
            pass

        # 3. Extract from detail JSON
        try:
            logger.info(f"API download unavailable for {ssl_id}, trying JSON extraction...")
            details_url = f"{self.base_url}/ssl/v1/{ssl_id}"
            response = requests.get(details_url, headers=self._get_headers(), timeout=15)
            if response.status_code == 200:
                data = response.json()
                pem = data.get('certificate') or data.get('crt')
                if not pem and 'certificateDetails' in data:
                    pem = data['certificateDetails'].get('certificate')
                if pem and "-----BEGIN CERTIFICATE-----" in pem:
                    return pem
        except Exception:
            pass

        # 4. Internal rescue via serial number search
        pem = self.rescue_from_sectigo_search(ssl_id)
        if pem:
            return pem

        # 5. External rescue via CT logs (crt.sh)
        print(f"    [!] Internal methods failed. Attempting CT Log Rescue...")
        pem = self.rescue_from_ct_logs(ssl_id)
        if pem:
            return pem

        logger.error(f"collect_certificate failed for {ssl_id}: all download strategies exhausted")
        return None

    def list_certificates_by_domain(self, domain):
        if not domain:
            raise ValueError('domain is required')
        self._check_rate_limit()
        url = f"{self.base_url}/ssl/v1"
        params = {'commonName': domain}
        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            summary_list = response.json() or []
        except requests.RequestException as e:
            logger.error(f"list_certificates_by_domain failed for {domain}: {e}")
            return []

        # Fetch full details for each result so callers have status, dates, etc.
        detailed_list = []
        for item in summary_list:
            ssl_id = item.get('sslId') or item.get('id')
            if ssl_id:
                details = self.get_order_status(ssl_id)
                if details:
                    detailed_list.append(details)
        return detailed_list

    def submit_order(self, domain, csr_content, org_id, profile_id, renewal_id=None, term=365, comments=None, external_requester=None, dcv_method='TXT'):
        headers = self._get_headers()
        url = f"{self.base_url}/ssl/v1/enroll"
        
        payload = {
            "orgId": org_id,
            "csr": csr_content,
            "commonName": domain,
            "term": term, 
            "certType": profile_id,
            "dcvMethod": dcv_method
        }

        if comments: payload["comments"] = comments
        if external_requester: payload["externalRequester"] = external_requester
        if renewal_id is not None: payload["renewalId"] = renewal_id
        
        print(f"[*] Submitting Order (Bypassing strict renewal endpoint)...")

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            ssl_id = data.get("sslId")
            print(f"[+] Order Submitted Successfully! SSL ID: {ssl_id}")
            return ssl_id

        except requests.exceptions.RequestException as e:
            print(f"[-] Order Submission Failed: {e}")
            if e.response is not None:
                try:
                    err_json = e.response.json()
                    print(f"    Server Message: {json.dumps(err_json, indent=2)}")
                except:
                    print(f"    Server Message: {e.response.text[:200]}...") 
            return None
