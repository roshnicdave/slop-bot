"""Owner-run replacement prompt: read-only authentication check, no model call."""

import getpass
import requests
from .connect_instagram import save_keys


def main():
    print(
        "Replace the revoked/invalid DeepSeek key. Input is hidden.\nNo model requests or credits are used by this check."
    )
    key = getpass.getpass("New DEEPSEEK_API_KEY: ").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("Invalid key format")
    r = requests.get(
        "https://api.deepseek.com/models",
        headers={"Authorization": "Bearer " + key},
        timeout=30,
    )
    if not r.ok:
        raise ValueError(
            f"Authentication check returned HTTP {r.status_code}; nothing saved"
        )
    save_keys({"DEEPSEEK_API_KEY": key})
    print(
        "Active replacement key saved locally. Tell Codex: replacement saved. Do not paste the key into chat."
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("Cancelled; nothing saved.")
    except Exception as exc:
        print(
            "Key not saved: " + str(exc)
            if isinstance(exc, ValueError)
            else "Key not saved; connection check failed."
        )
