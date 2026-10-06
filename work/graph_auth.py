"""Read-only personal Outlook authentication for the Ledger worker.

Uses Microsoft's public Graph PowerShell application, so no Azure subscription or
custom app registration is needed. The user grants Calendars.Read and User.Read
once with device sign-in. MSAL refreshes the cached delegated token thereafter.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import msal


CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Calendars.Read", "User.Read"]
CACHE_NAME = "graph-msal-cache.json"


def _cache(state_dir):
    cache = msal.SerializableTokenCache()
    path = state_dir / CACHE_NAME
    if path.exists():
        cache.deserialize(path.read_text())
    return cache, path


def _save_cache(cache, path):
    if not cache.has_state_changed:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".graph-cache-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(cache.serialize())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _app(state_dir):
    cache, path = _cache(state_dir)
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    return app, cache, path


def access_token(state_dir):
    app, cache, path = _app(state_dir)
    accounts = app.get_accounts()
    if len(accounts) != 1:
        raise RuntimeError("Outlook sign-in missing or ambiguous; run graph_auth.py once")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(cache, path)
    if not result or "access_token" not in result:
        raise RuntimeError("Outlook sign-in expired; run graph_auth.py again")
    return result["access_token"]


def device_sign_in(state_dir):
    app, cache, path = _app(state_dir)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Microsoft did not start device sign-in")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError("Microsoft sign-in failed: " + result.get("error_description", result.get("error", "unknown")))
    _save_cache(cache, path)
    print("Read-only Outlook sign-in saved privately")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    state_dir = args.state_dir.expanduser().resolve()
    if state_dir.is_relative_to(Path(__file__).resolve().parent.parent):
        parser.error("The private token state must be outside this project")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        device_sign_in(state_dir)
    except Exception as exc:
        print(f"Outlook sign-in stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
