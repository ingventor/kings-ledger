"""Deterministic Outlook-to-Ledger refresh. No AI or resident process.

Run on a private scheduled host with persistent, private state. Upload is opt-in
and restricted to one explicitly identified separate reMarkable Ledger document.
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from render_ledger import MONTHS, ROOT, render
from graph_auth import access_token


GRAPH = "https://graph.microsoft.com/v1.0"
NEW_YORK = ZoneInfo("America/New_York")


def rmapi_binary():
    return os.environ.get("LEDGER_RMAPI_BIN", "rmapi")


def request_json(url, token=None, form=None):
    body = urllib.parse.urlencode(form).encode() if form else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Prefer"] = 'outlook.timezone="UTC"'
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503, 504) or attempt == 4:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
            time.sleep(min(60, max(1, delay)))


def save_private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ledger-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def graph_pages(path, token):
    url = GRAPH + path
    while url:
        result = request_json(url, token)
        yield from result["value"]
        url = result.get("@odata.nextLink")


def utc_value(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def outlook_snapshot(token, expected_account):
    me = request_json(GRAPH + "/me?$select=mail,userPrincipalName", token)
    identities = {str(me.get(field, "")).lower() for field in ("mail", "userPrincipalName")}
    if expected_account.lower() not in identities:
        raise RuntimeError("Outlook account did not match the configured personal account")
    calendars = list(graph_pages("/me/calendars?$select=id,name&$top=100", token))
    if not calendars:
        raise RuntimeError("No Outlook calendars returned")
    result = {}
    for year, month in MONTHS:
        key = f"{year}-{month:02d}"
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        start = datetime(year, month, 1, tzinfo=NEW_YORK).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = datetime(next_year, next_month, 1, tzinfo=NEW_YORK).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        selected = {}
        for cal in calendars:
            calendar_id = urllib.parse.quote(cal["id"], safe="")
            query = urllib.parse.urlencode({
                "startDateTime": start, "endDateTime": end,
                "$select": "id,subject,start,end,isAllDay,location,iCalUId",
                "$top": "1000",
            })
            path = f"/me/calendars/{calendar_id}/calendarView?{query}"
            for item in graph_pages(path, token):
                event = {
                    "title": item.get("subject") or "(Untitled)",
                    "start": utc_value(item["start"]["dateTime"]),
                    "end": utc_value(item["end"]["dateTime"]),
                    "all_day": bool(item.get("isAllDay")),
                    "location": (item.get("location") or {}).get("displayName") or "",
                    "calendar_name": cal["name"],
                }
                duplicate_key = (event["start"], event["end"], event["title"], event["location"])
                if duplicate_key not in selected or (selected[duplicate_key]["calendar_name"] == "Calendar" and cal["name"] != "Calendar"):
                    selected[duplicate_key] = event
        result[key] = sorted(selected.values(), key=lambda event: (event["start"], event["title"], event["calendar_name"]))
    return result


def confirmed_test_target(document_name, document_id):
    if not document_name.endswith(".pdf") or "/" in document_name or "\\" in document_name:
        raise RuntimeError("A plain PDF filename is required for the test target")
    protected_id = os.environ.get("LEDGER_PROTECTED_DOCUMENT_ID")
    if not protected_id:
        raise RuntimeError("The protected original document ID must be configured")
    if document_id == protected_id:
        raise RuntimeError("The annotated 2026 Cal.pdf is never an upload target")
    if not re.fullmatch(r"[0-9a-f-]{36}", document_id):
        raise RuntimeError("An exact reMarkable test document ID is required")
    found = subprocess.run(
        [rmapi_binary(), "-json", "find", "/"],
        check=True, capture_output=True, text=True, timeout=90,
    )
    matches = [item for item in json.loads(found.stdout) if item.get("name") == document_name[:-4]]
    if len(matches) != 1 or matches[0].get("id") != document_id or matches[0].get("type") != "DocumentType" or matches[0].get("parent"):
        raise RuntimeError("Test document name and ID did not uniquely match in reMarkable")
    return matches[0]


def verify_uploaded_pages(document_id, expected_pages):
    with tempfile.TemporaryDirectory(prefix="ledger-cloud-check-") as directory:
        subprocess.run(
            [rmapi_binary(), "get", "--id", document_id],
            cwd=directory, check=True, capture_output=True, text=True, timeout=180,
        )
        archives = list(Path(directory).glob("*.rmdoc"))
        if len(archives) != 1:
            raise RuntimeError("Cloud document verification returned no unique archive")
        with zipfile.ZipFile(archives[0]) as archive:
            content = json.loads(archive.read(f"{document_id}.content"))
            pdf_pages = len(PdfReader(io.BytesIO(archive.read(f"{document_id}.pdf"))).pages)
        recorded = (
            content.get("pageCount"), content.get("originalPageCount"),
            (content.get("cPages") or {}).get("original", {}).get("value"),
            len((content.get("cPages") or {}).get("pages", [])), pdf_pages,
        )
        if recorded != (expected_pages,) * len(recorded):
            raise RuntimeError("Cloud document page counts disagree with the new PDF")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Use a local source snapshot instead of Outlook")
    parser.add_argument("--state-dir", type=Path, required=True, help="Private persistent directory, outside any public website")
    parser.add_argument("--upload-test", action="store_true", help="Update only the separately identified Ledger PDF")
    args = parser.parse_args()
    state_dir = args.state_dir.resolve()
    if state_dir.is_relative_to(ROOT):
        raise RuntimeError("Private worker state must be outside the project and any public website")
    if args.snapshot and args.upload_test:
        raise RuntimeError("A local snapshot cannot be used for an automatic upload")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.snapshot:
        data = json.loads(args.snapshot.read_text())
    else:
        data = outlook_snapshot(access_token(state_dir), os.environ["LEDGER_OUTLOOK_ACCOUNT"])
    source = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    from render_ledger import ART
    artwork = b"".join((ROOT / "assets" / name).read_bytes() for name in sorted(set(ART.values())))
    digest = hashlib.sha256(source + (ROOT / "work" / "render_ledger.py").read_bytes() + artwork).hexdigest()
    saved = state_dir / "last-upload.json"
    if args.upload_test:
        if os.environ.get("LEDGER_TEST_APPROVED") != "yes":
            raise RuntimeError("Ledger upload is locked until the separate document is explicitly approved")
        name = os.environ["LEDGER_TEST_DOCUMENT_NAME"]
        document_id = os.environ["LEDGER_TEST_DOCUMENT_ID"]
        confirmed_test_target(name, document_id)
        if saved.exists():
            prior = json.loads(saved.read_text())
            if prior.get("source_sha256") == digest and prior.get("document_id") == document_id:
                print("No calendar changes; upload skipped")
                return
    else:
        name = "K-Ings-Ledger-Months-Oct-2026-Dec-2027.pdf"
    with tempfile.TemporaryDirectory(prefix="ledger-refresh-") as directory:
        pdf = Path(directory) / name
        render(data, pdf)
        if args.upload_test:
            expected_pages = len(PdfReader(str(pdf)).pages)
            subprocess.run([rmapi_binary(), "put", "--content-only", str(pdf)], check=True, timeout=300)
            confirmed_test_target(name, document_id)
            verify_uploaded_pages(document_id, expected_pages)
            save_private_json(saved, {"source_sha256": digest, "document_id": document_id})
            print("Separate Ledger document updated; confirm its pages on Paper Pro")
        else:
            destination = state_dir / name
            os.replace(pdf, destination)
            print(f"Rendered {destination} (source SHA-256 {digest[:12]})")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Ledger refresh stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
