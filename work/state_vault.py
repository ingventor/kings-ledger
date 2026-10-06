"""Seal only the three small Ledger credentials/state files for a stateless runner.

The encrypted blob can be stored in Git; the Fernet key must remain a private
Actions secret and a private local recovery file. Never include a calendar PDF.
"""

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


FILES = ("graph-msal-cache.json", "rmapi-config", "last-upload.json")
MAX_FILE_SIZE = 1024 * 1024


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".ledger-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cipher(key_file):
    key = key_file.read_bytes().strip() if key_file else os.environ["LEDGER_STATE_KEY"].encode()
    return Fernet(key)


def seal(state_dir, vault, key_file):
    payload = {}
    for name in FILES:
        path = state_dir / name
        if path.exists():
            data = path.read_bytes()
            if len(data) > MAX_FILE_SIZE:
                raise RuntimeError("A state file exceeded the safe size limit")
            payload[name] = base64.b64encode(data).decode("ascii")
    if not all(name in payload for name in FILES[:2]):
        raise RuntimeError("Outlook and reMarkable sign-ins must both be present")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    private_write(vault, b"LEDGERV1\n" + cipher(key_file).encrypt(encoded) + b"\n")


def open_vault(state_dir, vault, key_file):
    raw = vault.read_bytes()
    if not raw.startswith(b"LEDGERV1\n"):
        raise RuntimeError("Unrecognized encrypted state format")
    payload = json.loads(cipher(key_file).decrypt(raw.split(b"\n", 1)[1].strip()))
    if set(payload) - set(FILES) or not all(name in payload for name in FILES[:2]):
        raise RuntimeError("Encrypted state contains unexpected files")
    for name, value in payload.items():
        data = base64.b64decode(value, validate=True)
        if len(data) > MAX_FILE_SIZE:
            raise RuntimeError("A state file exceeded the safe size limit")
        private_write(state_dir / name, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("new-key", "seal", "open"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if args.operation == "new-key":
        if not args.key_file or args.key_file.exists():
            parser.error("A new, nonexistent --key-file is required")
        private_write(args.key_file, Fernet.generate_key() + b"\n")
        return
    if not args.state_dir or not args.vault:
        parser.error("--state-dir and --vault are required")
    if args.operation == "seal":
        seal(args.state_dir, args.vault, args.key_file)
    else:
        open_vault(args.state_dir, args.vault, args.key_file)


if __name__ == "__main__":
    main()
