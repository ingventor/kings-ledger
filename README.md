# K. Ing's Ledger

One-way, deterministic personal Outlook calendar to separate reMarkable PDF.
The scheduled job checks hourly. A change triggers a new month-view PDF and
replaces only the explicitly named Ledger document after checking its ID.
The original handwritten `2026 Cal.pdf` is excluded by ID in code.

This is not a website and does not use AI at runtime. Standard GitHub-hosted
Actions runners are free for public repositories. The runner stores its small
Outlook and reMarkable sign-in cache in `private-state.enc`, encrypted with a
Fernet key kept as a private repository secret. Event names, locations, PDF
pages, and plaintext credentials are never committed or logged. The local
recovery key must remain outside this repository.

Required repository secrets: `LEDGER_STATE_KEY`, `LEDGER_OUTLOOK_ACCOUNT`,
`LEDGER_TEST_DOCUMENT_NAME`, `LEDGER_TEST_DOCUMENT_ID`, and
`LEDGER_PROTECTED_DOCUMENT_ID`. The workflow
starts only by hourly schedule or manual dispatch, never on untrusted pull
requests. It uses an exact pinned rmapi source revision plus the checked-in
page-count patch. A successful upload is downloaded and its page map verified
before its source digest is marked complete. If authentication expires,
re-pairing is required; no paid plan or Azure subscription is involved.

The document keeps a rolling 15-month window, beginning October 2026 now and
advancing by one month at each month boundary. The
separate Ledger is an output surface, not an editable calendar: make changes
in the personal Outlook calendars (or through Scheduler if Scheduler writes
there). Events are never read back from the PDF.
