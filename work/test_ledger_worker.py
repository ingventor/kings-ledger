import unittest
from datetime import datetime, timedelta, timezone

from ledger_worker import upload_due


class UploadDueTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.prior = {"source_sha256": "same", "document_id": "ledger"}

    def test_changed_calendar_uploads(self):
        self.assertTrue(upload_due(self.prior, "changed", "ledger", self.now))

    def test_unchanged_calendar_waits_until_day_28(self):
        self.prior["uploaded_at"] = (self.now - timedelta(days=27, hours=23)).isoformat()
        self.assertFalse(upload_due(self.prior, "same", "ledger", self.now))
        self.prior["uploaded_at"] = (self.now - timedelta(days=28)).isoformat()
        self.assertTrue(upload_due(self.prior, "same", "ledger", self.now))

    def test_existing_state_uploads_once_to_start_clock(self):
        self.assertTrue(upload_due(self.prior, "same", "ledger", self.now))

    def test_missing_or_invalid_date_refreshes(self):
        self.prior["uploaded_at"] = "not-a-date"
        self.assertTrue(upload_due(self.prior, "same", "ledger", self.now))
        self.prior["uploaded_at"] = (self.now + timedelta(days=1)).isoformat()
        self.assertTrue(upload_due(self.prior, "same", "ledger", self.now))


if __name__ == "__main__":
    unittest.main()
