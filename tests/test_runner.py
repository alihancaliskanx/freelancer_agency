"""Unit tests for the integrated AgencyApplication runner."""
import os
import shutil
import tempfile
import unittest

from src.app import AgencyApplication, load_env


class TestAgencyApplication(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_app.db")
        self.app = AgencyApplication(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_app_wiring(self):
        self.assertIsNotNone(self.app.db)
        self.assertIsNotNone(self.app.filter_engine)
        self.assertIsNotNone(self.app.coordinator)
        self.assertIsNotNone(self.app.scoring_engine)
        self.assertIsNotNone(self.app.status_watcher)
        self.assertIsNotNone(self.app.watchdog)
        self.assertIsNotNone(self.app.ceo)
        self.assertIsNotNone(self.app.mcp)

    def test_scan_and_score_cycle(self):
        stats = self.app.scan_and_score()
        self.assertIn("total_scanned", stats)
        self.assertIn("evaluated_count", stats)

    def test_mcp_integration(self):
        req = {"jsonrpc": "2.0", "id": 100, "method": "tools/list"}
        res = self.app.mcp.handle_request(req)
        self.assertEqual(res["id"], 100)
        self.assertIn("tools", res["result"])


if __name__ == "__main__":
    unittest.main()
