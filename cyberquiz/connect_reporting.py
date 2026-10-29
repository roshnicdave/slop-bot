"""Optional read-only reporting key for provider-side cost reconciliation."""
import getpass
import requests
from .providers import checked
from .connect_instagram import save_keys


def main():
    print('Paste a Fal BILLING/reporting key, not a FULL-access key. Input is hidden.')
    key=getpass.getpass('Fal reporting key: ').strip()
    if not key or any(c.isspace() for c in key):raise ValueError('Invalid key')
    checked(requests.get('https://api.fal.ai/v1/models/usage',
        headers={'Authorization':'Key '+key},params={'endpoint_id':'fal-ai/flux/schnell,fal-ai/kokoro','expand':'summary'},timeout=30))
    save_keys({'FAL_REPORTING_KEY':key})
    print('Read-only usage access verified and saved. No generation requests were made.')

if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,EOFError):print('Cancelled; nothing saved.')
    except Exception as exc:print('Reporting access unavailable ('+type(exc).__name__+'); nothing saved.')
