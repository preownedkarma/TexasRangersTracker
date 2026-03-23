import requests
from dotenv import load_dotenv
load_dotenv()
from sectigo_client import SectigoClient
c = SectigoClient()
urls = [c.base_url + '/dcv/v1/domain/sectester.mclaneco.com', c.base_url + '/dcv/v1/validation']
for url in urls:
    params = {'domain': 'sectester.mclaneco.com'} if 'validation' in url else None
    r = requests.get(url, headers=c._get_headers(), params=params, timeout=20)
    print('URL:', url, 'status:', r.status_code)
    print('BODY:', r.text[:600], '\n---')
