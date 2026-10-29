import getpass
import re
import requests
from .connect_instagram import save_keys


def main():
    print('Cloudflare Workers Free setup. No inference or payment changes.\nUse an API token limited to Workers AI for this account. Input is hidden.')
    account=getpass.getpass('Cloudflare Account ID: ').strip()
    token=getpass.getpass('Cloudflare Workers AI token: ').strip()
    if not re.fullmatch('[a-fA-F0-9]{32}',account):raise ValueError('Account ID must be 32 hexadecimal characters')
    r=requests.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/models/search',
        headers={'Authorization':'Bearer '+token},timeout=30)
    if not r.ok or not r.json().get('success'):raise ValueError('Workers AI access check failed; nothing saved')
    save_keys({'CLOUDFLARE_ACCOUNT_ID':account,'CLOUDFLARE_API_TOKEN':token})
    print('Workers AI access verified and saved locally. Tell Codex: Cloudflare saved. No paid requests were made.')

if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,EOFError):print('Cancelled; nothing saved.')
    except Exception as exc:print(str(exc) if isinstance(exc,ValueError) else 'Connection check failed; nothing saved.')
