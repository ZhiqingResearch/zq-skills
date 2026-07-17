#!/usr/bin/env python3
"""Manage saved API keys for zq-amazon-upc-autofill (stored once, reused forever).

  python3 config.py set KEEPA_API_KEY <value>   # save (0600 file). Omit <value> or
  python3 config.py set KEEPA_API_KEY --stdin    #   use --stdin to avoid shell history
  python3 config.py get KEEPA_API_KEY           # show where it resolves from (masked)
  python3 config.py validate KEEPA_API_KEY      # live-check the key against Keepa (~1 token)
  python3 config.py unset KEEPA_API_KEY         # delete from the user config file
  python3 config.py check                        # status of all known keys

The agent normally calls `set` after the user pastes a key once, so end users never
configure environment variables themselves.
"""
import sys

from credentials import (CONFIG_PATH, delete_secret, resolve_secret, save_secret,
                         source_of)

KNOWN = ["KEEPA_API_KEY"]

# Heuristics to catch an obviously wrong key being stored under the wrong name.
WRONG_TYPE = {
    "KEEPA_API_KEY": lambda v: (
        "looks like a SIF key" if v.lower().startswith("sif") else
        "too short for a Keepa key (expected ~64 chars)" if len(v) < 20 else
        None
    ),
}


def mask(v):
    return "•" * (len(v) - 4) + v[-4:] if v and len(v) > 4 else "••••"


def _read_value(argv):
    if "--stdin" in argv or len(argv) < 3:
        return sys.stdin.readline().strip()
    return argv[2]


def cmd_set(argv, force):
    name = argv[1]
    value = _read_value(argv)
    if not value:
        print("No value provided.", file=sys.stderr)
        return 1
    warn = WRONG_TYPE.get(name, lambda _v: None)(value)
    if warn and not force:
        print(f"Refusing to save {name}: {warn}. Re-run with --force to override.",
              file=sys.stderr)
        return 1
    path = save_secret(name, value)
    print(f"Saved {name} to {path}")
    return 0


def cmd_validate(name):
    value = resolve_secret(name)
    if not value:
        print(f"{name}: not set", file=sys.stderr)
        return 1
    if name != "KEEPA_API_KEY":
        print(f"No live validator for {name}; format check only: "
              f"{'ok' if len(value) >= 20 else 'suspiciously short'}")
        return 0
    try:
        from keepa_lookup import KeepaError, validate_key
        tokens = validate_key(value)
        print(f"{name}: VALID (Keepa tokensLeft={tokens})")
        return 0
    except KeepaError as e:
        print(f"{name}: INVALID — {e}", file=sys.stderr)
        return 1


def main(argv):
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "set" and len(argv) >= 2:
        return cmd_set(argv, force)
    if cmd == "get" and len(argv) == 2:
        v, src = resolve_secret(argv[1]), source_of(argv[1])
        print(f"{argv[1]}: {mask(v) if v else '(not set)'}" + (f"  [from {src}]" if src else ""))
        return 0
    if cmd == "validate" and len(argv) == 2:
        return cmd_validate(argv[1])
    if cmd in ("unset", "delete") and len(argv) == 2:
        print(f"Removed {argv[1]}" if delete_secret(argv[1]) else f"{argv[1]} was not saved")
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
