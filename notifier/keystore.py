"""Where API keys come from — never from a file in this folder.

Lookup order:
  1. Environment variable (this is how GitHub Actions passes repository secrets in).
  2. Windows Credential Manager via `keyring` (how your PC stores them; encrypted
     with your Windows login, never written into the project folder or OneDrive).

Store keys on your PC with:  python -m notifier.set_keys
"""
import os

SERVICE = "NotifierApp"

KEYS = {
    "PANDASCORE_TOKEN": "PandaScore API token (CS2)",
    "FOOTBALL_DATA_TOKEN": "football-data.org API token (Liverpool)",
    "SPORTSAPIPRO_KEY": "SportsAPI Pro key (darts match-ups, optional)",
    "NTFY_TOPIC": "ntfy topic name for phone alerts (optional, treat like a password)",
}


def get_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        import keyring  # only needed on your PC

        value = keyring.get_password(SERVICE, name)
        return value.strip() if value else None
    except Exception:
        return None


def mask(value: str | None) -> str:
    """Safe to print: shows only that a key exists, never the key itself."""
    if not value:
        return "(not set)"
    return f"set ({len(value)} chars, ends …{value[-2:]})"
