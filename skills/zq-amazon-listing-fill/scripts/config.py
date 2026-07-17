#!/usr/bin/env python3
"""Manage saved API keys for zq-amazon-listing-fill (stored once, reused forever).

  python3 config.py set KEEPA_API_KEY <value>   # save to ~/.config/zq-skills/credentials.json (0600)
  python3 config.py get KEEPA_API_KEY           # show where it resolves from (value masked)
  python3 config.py check                        # report status of all known keys

The agent normally calls `set` automatically after the user pastes a key once, so
end users never have to configure environment variables themselves.
"""
import sys

from credentials import CONFIG_PATH, resolve_secret, save_secret, source_of

# Only keys the skill actually uses. SIF is not wired in yet, so it is
# intentionally omitted to avoid implying it can be configured/used.
KNOWN = ["KEEPA_API_KEY"]


def mask(v):
    return "•" * (len(v) - 4) + v[-4:] if v and len(v) > 4 else "••••"


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "set" and len(argv) == 3:
        path = save_secret(argv[1], argv[2])
        print(f"Saved {argv[1]} to {path}")
        return 0
    if cmd == "get" and len(argv) == 2:
        v, src = resolve_secret(argv[1]), source_of(argv[1])
        print(f"{argv[1]}: {mask(v) if v else '(not set)'}"
              + (f"  [from {src}]" if src else ""))
        return 0
    if cmd == "check":
        for name in KNOWN:
            src = source_of(name)
            print(f"{name:16} {'OK' if src else 'missing':8} {('[' + src + ']') if src else ''}")
        print(f"\nConfig file: {CONFIG_PATH}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
