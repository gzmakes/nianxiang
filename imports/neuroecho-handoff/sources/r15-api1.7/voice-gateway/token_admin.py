#!/usr/bin/env python3
"""Offline token helper for the Voice Gateway.

This command never contacts the gateway and never writes a token to disk.  It
prints a newly generated token once and the SHA-256 hash to place in the
administrator's secret store.  Revocation/rotation is performed by replacing
VOICE_GATEWAY_TOKEN_HASHES and restarting the service.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or hash a gateway token offline")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--generate", action="store_true", help="generate a new URL-safe token")
    group.add_argument("--hash", metavar="TOKEN", help="hash an existing token")
    args = parser.parse_args()
    token = args.hash or secrets.token_urlsafe(32)
    print(f"token={token}")
    print(f"sha256={token_hash(token)}")
    if args.generate or not args.hash:
        print("Store only sha256 in VOICE_GATEWAY_TOKEN_HASHES; deliver token through a private channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
