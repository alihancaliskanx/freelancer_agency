"""Unit tests for the DatabaseManager and SQLite storage layer."""
import os
import shutil
import tempfile
import unittest
from src.db.manager import DatabaseManager, compute_fingerprint
from src.models import JobLead, FilterDecision


class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_agency.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_schema_and_wal_mode(self):
        with self.db.get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            self.assertIn("jobs", tables)
            self.assertIn("proposals", tables)
            self.assertIn("agency_metrics", tables)

    def test_maintenance_wal_checkpoint(self):
        # Insert a job, then run maintenance
        job = JobLead(id="job:maint", title="Test", description="Desc", job_type="fixed", platform="upwork")
        self.db.insert_job(job)
        self.db.maintenance()

    def test_insert_and_get_job(self):
        job = JobLead(
            id="upwork:~01abc123",
            title="Full-Stack Developer for Python API",
            description="Build scalable endpoints using FastAPI and SQLite.",
            job_type="fixed",
            platform="upwork",
            budget=500.0,
            client_payment_verified=True,
            client_rating=4.9,
            client_hire_rate=70.0,
            proposals_count=10,
            url="https://upwork.com/jobs/01abc123"
        )
        decision = FilterDecision(passed=True, reason="passed:all_deterministic_filters", rule_name="PassedAllFilters")

        inserted, job_id = self.db.insert_job(job, decision)
        self.assertTrue(inserted)
        self.assertEqual(job_id, "upwork:~01abc123")

        fetched = self.db.get_job("upwork:~01abc123")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], job.title)
        self.assertEqual(fetched["budget"], 500.0)
        self.assertEqual(fetched["filter_passed"], 1)
        self.assertEqual(fetched["status"], "discovered")

    def test_fingerprint_deduplication(self):
        job1 = JobLead(
            id="upwork:~01first",
            title="Senior React & Node Engineer",
            description="We need an expert to revamp our dashboard with clean components.",
            job_type="fixed",
            platform="upwork",
            budget=750.0
        )
        inserted1, id1 = self.db.insert_job(job1)
        self.assertTrue(inserted1)

        job2 = JobLead(
            id="upwork:~01second_repost",
            title="Senior React & Node Engineer",
            description="We need an expert to revamp our dashboard with clean components.",
            job_type="fixed",
            platform="upwork",
            budget=750.0
        )
        inserted2, existing_id = self.db.insert_job(job2)
        self.assertFalse(inserted2)
        self.assertEqual(existing_id, "upwork:~01first")

    def test_duplicate_insert_updates_proposals_count(self):
        job1 = JobLead(
            id="freelancer:dup_prop",
            title="Python Web Automation",
            description="Short desc",
            job_type="fixed",
            platform="freelancer",
            budget=500.0,
            proposals_count=3
        )
        inserted1, _ = self.db.insert_job(job1)
        self.assertTrue(inserted1)

        # Later scan discovers 25 proposals and longer description
        job2 = JobLead(
            id="freelancer:dup_prop",
            title="Python Web Automation",
            description="Much longer and detailed description of the project requirements.",
            job_type="fixed",
            platform="freelancer",
            budget=500.0,
            proposals_count=25
        )
        inserted2, existing_id = self.db.insert_job(job2)
        self.assertFalse(inserted2)
        self.assertEqual(existing_id, "freelancer:dup_prop")

        row = self.db.get_job("freelancer:dup_prop")
        self.assertEqual(row["proposals_count"], 25)
        self.assertIn("Much longer", row["description"])

    def test_filtered_out_status(self):
        job = JobLead(
            id="upwork:~01drop",
            title="Data Entry Assistant",
            description="Must track time using desktop tracker.",
            job_type="hourly",
            platform="upwork"
        )
        decision = FilterDecision(passed=False, reason="drop:tracker_required", rule_name="TrackerGuardTextRule")

        inserted, _ = self.db.insert_job(job, decision)
        self.assertTrue(inserted)

        fetched = self.db.get_job("upwork:~01drop")
        self.assertEqual(fetched["status"], "filtered_out")
        self.assertEqual(fetched["filter_passed"], 0)
        self.assertIn("tracker_required", fetched["filter_reason"])

    def test_update_status_and_get_hot_leads(self):
        job = JobLead(
            id="upwork:~01hot",
            title="High Value Python Automation",
            description="Build robust web scrapers and pipelines.",
            job_type="fixed",
            platform="upwork",
            budget=1500.0
        )
        self.db.insert_job(job, FilterDecision(passed=True, reason="passed", rule_name="PassedAll"))

        updated = self.db.update_job_status(
            job_id="upwork:~01hot",
            status="evaluated",
            roi_score=9.4,
            estimated_hours=12.0,
            estimated_token_cost=0.85
        )
        self.assertTrue(updated)

        hot_leads = self.db.get_hot_leads(min_roi=8.0)
        self.assertEqual(len(hot_leads), 1)
        self.assertEqual(hot_leads[0]["id"], "upwork:~01hot")
        self.assertEqual(hot_leads[0]["roi_score"], 9.4)

    def test_proposals_relationship(self):
        job = JobLead(
            id="upwork:~01prop",
            title="Custom FastAPI Backend",
            description="Build clean API.",
            job_type="fixed",
            platform="upwork",
            budget=800.0
        )
        self.db.insert_job(job)

        prop_id = self.db.create_proposal(
            job_id="upwork:~01prop",
            cover_letter="Hello, I have extensive FastAPI experience...",
            bid_amount=800.0,
            estimated_timeline="5 days",
            token_cost_usd=0.04
        )
        self.assertGreater(prop_id, 0)

        proposals = self.db.get_proposals_for_job("upwork:~01prop")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["bid_amount"], 800.0)
        self.assertIn("FastAPI", proposals[0]["cover_letter"])

    def test_metrics_heartbeat(self):
        self.db.record_metric_heartbeat(
            jobs_scanned_increment=50,
            passed_filter_increment=4,
            proposals_increment=1,
            token_cost_increment=0.12,
            active_jobs_count=2
        )
        self.db.record_metric_heartbeat(
            jobs_scanned_increment=25,
            passed_filter_increment=2,
            token_cost_increment=0.08
        )

        metrics = self.db.get_latest_metrics()
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_jobs_scanned"], 75)
        self.assertEqual(metrics["jobs_passed_filter"], 6)
        self.assertEqual(metrics["proposals_generated"], 1)
        self.assertAlmostEqual(metrics["total_token_cost_usd"], 0.20, places=2)
        self.assertEqual(metrics["active_jobs_count"], 2)


if __name__ == "__main__":
    unittest.main()
