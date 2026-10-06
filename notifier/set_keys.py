"""Save your API keys into Windows Credential Manager.

Run:  python -m notifier.set_keys
Typing is hidden (like a password box). Press Enter to keep an existing value.
"""
import getpass
import secrets as pysecrets

import keyring

from .keystore import KEYS, SERVICE, get_secret, mask


def main():
    print("Keys are saved in Windows Credential Manager (entry name: NotifierApp).")
    print("They are NOT written to this folder, OneDrive or GitHub.\n")
    for name, label in KEYS.items():
        current = keyring.get_password(SERVICE, name)
        print(f"{label}\n  current: {mask(current)}")
        if name == "NTFY_TOPIC" and not current:
            suggestion = "notifier-" + pysecrets.token_urlsafe(12)
            print(f"  tip: a random, unguessable topic is best, e.g. {suggestion}")
        value = getpass.getpass("  new value (hidden, Enter to skip): ").strip()
        if value:
            keyring.set_password(SERVICE, name, value)
            print("  saved.\n")
        else:
            print("  unchanged.\n")
    print("Done. Check:")
    for name in KEYS:
        print(f"  {name}: {mask(get_secret(name))}")


if __name__ == "__main__":
    main()
