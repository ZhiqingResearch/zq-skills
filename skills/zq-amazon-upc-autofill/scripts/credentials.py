"""Shared secret resolution for zq-amazon-upc-autofill.

Keys are looked up in this order (first hit wins), so a user can pick whatever is
convenient and never has to touch their shell profile:

  1. environment variable            (e.g. KEEPA_API_KEY)          — CI / power users
  2. ./.env                          KEEPA_API_KEY=...              — per-project
  3. ~/.config/zq-skills/credentials.json  {"KEEPA_API_KEY": "..."} — set once, reused

`save_secret()` writes to #3 with 0600 perms, so the agent can capture a key the
user pastes once and reuse it on every later run. The config file lives OUTSIDE
this (public) repo and is never committed.
"""
import json
import os
import stat

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "zq-skills")
CONFIG_PATH = os.path.join(CONFIG_DIR, "credentials.json")


def _from_env(name):
    v = os.environ.get(name)
    return v.strip() if v else None


def _from_dotenv(name, path=".env"):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        return None
    return None


def _load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def resolve_secret(name):
    """Return the secret value, or None if not configured anywhere."""
    return _from_env(name) or _from_dotenv(name) or _load_config().get(name)


def save_secret(name, value):
    """Persist a secret to the user-level config file (0600). Returns the path."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = _load_config()
    data[name] = value.strip()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    os.replace(tmp, CONFIG_PATH)
    return CONFIG_PATH


def delete_secret(name):
    """Remove a secret from the user-level config file. Returns True if removed."""
    data = _load_config()
    if name not in data:
        return False
    del data[name]
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    os.replace(tmp, CONFIG_PATH)
    return True


def source_of(name):
    """Where would `name` resolve from? For diagnostics/messages."""
    if _from_env(name):
        return "environment variable"
    if _from_dotenv(name):
        return "./.env"
    if name in _load_config():
        return CONFIG_PATH
    return None
