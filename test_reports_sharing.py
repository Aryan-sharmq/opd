import os
import time
import unittest

from vision_radar.api.errors import NotFound, ValidationError
from vision_radar.event_engine.models import Event, EventState, EventType
from vision_radar.security.auth import PermissionDenied
from vision_radar.tests.test_api_service import ApiCase


class TestReportsAndSharing(ApiCase):
    def setUp(self):
        super().setUp()
        now = time.time()
        self.t0 = now - 3600
        self.event_id = "ev-share-1"
        self.repo.save_event(Event(
            event_id=self.event_id, event_type=EventType.ZONE_ENTRY, entity_ids=["e1"], entity_type="person",
            zone_id=None, start_time=now - 60, end_time=None, confidence=0.9, state=EventState.ACTIVE,
            evidence={}, created_at=now), None)

    def test_csv_exports_and_formula_injection_guard(self):
        csv_text = self.svc.export_events_csv(self.view)
        self.assertIn("event_id,event_type", csv_text.splitlines()[0])
        self.assertIn(self.event_id, csv_text)
        from vision_radar.reports.exporter import _safe
        self.assertEqual(_safe("=cmd|' /C calc'!A0"), "'=cmd|' /C calc'!A0")
        self.assertIn("alert_id", self.svc.export_alerts_csv(self.view))

    def test_pdf_report_builds(self):
        pdf = self.svc.build_report(self.view, self.t0, time.time())
        self.assertTrue(pdf.startswith(b"%PDF"))
        with self.assertRaises(ValidationError):
            self.svc.build_report(self.view, time.time(), self.t0)           # end before start
        with self.assertRaises(ValidationError):
            self.svc.build_report(self.view, self.t0, None)                  # only one bound

    def test_only_administrators_can_share(self):
        for tok in (self.view, self.oper):
            with self.assertRaises(PermissionDenied):
                self.svc.create_share(tok, self.t0, time.time())

    def test_share_link_opens_without_login_then_expires_or_is_revoked(self):
        s = self.svc.create_share(self.admin, self.t0, time.time(), expires_in_hours=1)
        self.assertTrue(self.svc.shared_report(s["token"]).startswith(b"%PDF"))
        listed = self.svc.list_shares(self.admin)[0]
        self.assertEqual((listed["access_count"], listed["active"]), (1, True))
        self.assertNotIn("token", listed)                                    # token is shown once only
        self.svc.revoke_share(self.admin, s["share_id"])
        with self.assertRaises(NotFound):
            self.svc.shared_report(s["token"])

        s2 = self.svc.create_share(self.admin, event_id=self.event_id)
        self.repo.db.execute("UPDATE shares SET expires_at = ? WHERE share_id = ?", (time.time() - 1, s2["share_id"]))
        with self.assertRaises(NotFound):
            self.svc.shared_report(s2["token"])
        with self.assertRaises(NotFound):
            self.svc.shared_report("not-a-real-token")

    def test_share_validation(self):
        with self.assertRaises(ValidationError):
            self.svc.create_share(self.admin)                                # nothing chosen
        with self.assertRaises(ValidationError):
            self.svc.create_share(self.admin, self.t0, time.time(), expires_in_hours=99999)
        with self.assertRaises(NotFound):
            self.svc.create_share(self.admin, event_id="missing")

    def test_token_is_stored_hashed(self):
        s = self.svc.create_share(self.admin, self.t0, time.time())
        row = self.repo.db.query_one("SELECT * FROM shares WHERE share_id = ?", (s["share_id"],))
        self.assertNotIn(s["token"], str(dict(row)))


if __name__ == "__main__":
    unittest.main()
