"""Unit tests for JobStatusWatcher and OciKeepAliveWatchdog."""
import os
import shutil
import tempfile
import unittest
from src.watchers.status_watcher import JobStatusWatcher
from src.watchers.keep_alive import OciKeepAliveWatchdog
from src.models import JobLead, FilterDecision
from src.db.manager import DatabaseManager


class TestWatchers(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_watchers.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_job_status_watcher_active(self):
        def mock_checker(url):
            return 200, "<html><body>Submit a Proposal for this job</body></html>"

        watcher = JobStatusWatcher(self.db, http_checker=mock_checker)
        is_alive, reason = watcher.check_job_alive("https://upwork.com/jobs/1")
        self.assertTrue(is_alive)
        self.assertEqual(reason, "active")

    def test_job_status_watcher_404_drops(self):
        def mock_checker(url):
            return 404, ""

        watcher = JobStatusWatcher(self.db, http_checker=mock_checker)
        is_alive, reason = watcher.check_job_alive("https://upwork.com/jobs/missing")
        self.assertFalse(is_alive)
        self.assertEqual(reason, "http_404")

    def test_job_status_watcher_closed_text(self):
        def mock_checker(url):
            return 200, "<div>Sorry, this job is no longer available to new applicants.</div>"

        watcher = JobStatusWatcher(self.db, http_checker=mock_checker)
        is_alive, reason = watcher.check_job_alive("https://upwork.com/jobs/closed")
        self.assertFalse(is_alive)
        self.assertEqual(reason, "closed_in_content")

    def test_prune_stale_jobs_pipeline(self):
        job1 = JobLead(id="job:active", title="Active Job", description="Active", job_type="fixed", platform="upwork", url="https://upwork.com/active")
        job2 = JobLead(id="job:expired", title="Expired Job", description="Expired", job_type="fixed", platform="upwork", url="https://upwork.com/expired")

        self.db.insert_job(job1, FilterDecision(passed=True, reason="ok", rule_name="r"))
        self.db.insert_job(job2, FilterDecision(passed=True, reason="ok", rule_name="r"))

        def mock_checker(url):
            if "expired" in url:
                return 410, ""
            return 200, "Valid job content"

        watcher = JobStatusWatcher(self.db, http_checker=mock_checker)
        stats = watcher.prune_stale_jobs(statuses=["discovered"])

        self.assertEqual(stats["checked"], 2)
        self.assertEqual(stats["closed"], 1)
        self.assertEqual(stats["alive"], 1)

        row_exp = self.db.get_job("job:expired")
        self.assertEqual(row_exp["status"], "closed")

        row_act = self.db.get_job("job:active")
        self.assertEqual(row_act["status"], "discovered")

    def test_oci_keep_alive_cycle(self):
        watchdog = OciKeepAliveWatchdog(self.db)
        res = watchdog.run_maintenance_cycle()

        self.assertEqual(res["status"], "active")
        self.assertGreater(res["duration_ms"], 0.0)
        self.assertIsNotNone(res["metrics"])
        self.assertIn("last_heartbeat", res["metrics"])


if __name__ == "__main__":
    unittest.main()
