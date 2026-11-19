"""Unit tests for the ROI and Feasibility Scoring Engine."""
import os
import shutil
import tempfile
import unittest
from src.scoring.engine import RoiScoringEngine, ScoringConfig
from src.models import JobLead, FilterDecision
from src.db.manager import DatabaseManager


class TestRoiScoringEngine(unittest.TestCase):
    def setUp(self):
        self.config = ScoringConfig(target_hourly_rate=50.0, default_token_cost_usd=0.50)
        self.engine = RoiScoringEngine(self.config)
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_scoring.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_score_fixed_high_budget_job(self):
        job = JobLead(
            id="job:fixed_high",
            title="FastAPI Microservices Architecture",
            description="Build scalable distributed microservices with Docker and Redis.",
            job_type="fixed",
            platform="upwork",
            budget=2500.0,
            client_payment_verified=True,
            client_rating=5.0,
            client_hire_rate=80.0,
            proposals_count=4
        )
        res = self.engine.score_job(job)
        self.assertGreaterEqual(res.roi_score, 7.5)
        self.assertEqual(res.recommendation, "strong_fit")
        self.assertEqual(res.complexity, "high")
        self.assertGreater(res.estimated_hours, 15.0)

    def test_score_fixed_low_complexity_job(self):
        job = JobLead(
            id="job:fixed_low",
            title="Simple Python Web Scraper Bugfix",
            description="Quick fix for a BeautifulSoup script that breaks on pagination.",
            job_type="fixed",
            platform="upwork",
            budget=200.0,
            client_payment_verified=True,
            client_rating=4.8,
            proposals_count=10
        )
        res = self.engine.score_job(job)
        self.assertEqual(res.complexity, "low")
        self.assertLessEqual(res.estimated_hours, 8.0)
        self.assertIn(res.recommendation, ["fit", "strong_fit"])

    def test_score_hourly_high_rate(self):
        job = JobLead(
            id="job:hourly_high",
            title="Senior Python Consultant",
            description="Architect cloud pipelines. Flexible hours.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=65.0,
            hourly_rate_max=85.0,
            client_payment_verified=True,
            client_rating=4.95,
            client_hire_rate=75.0
        )
        res = self.engine.score_job(job)
        self.assertGreaterEqual(res.roi_score, 8.0)
        self.assertEqual(res.recommendation, "strong_fit")

    def test_score_hourly_marginal_rate(self):
        job = JobLead(
            id="job:hourly_marginal",
            title="Junior Data Cleaner",
            description="Clean CSV datasets.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=30.0,
            hourly_rate_max=32.0,
            client_payment_verified=True,
            client_rating=4.5,
            client_hire_rate=45.0
        )
        res = self.engine.score_job(job)
        self.assertLess(res.roi_score, 5.0)
        self.assertEqual(res.recommendation, "marginal")

    def test_evaluate_pending_jobs_in_db(self):
        job1 = JobLead(
            id="job:db_1",
            title="FastAPI Payment Gateway",
            description="Build Stripe checkout integration.",
            job_type="fixed",
            platform="upwork",
            budget=800.0,
            client_payment_verified=True,
            client_rating=5.0
        )
        job2 = JobLead(
            id="job:db_2",
            title="Senior Backend Support",
            description="Ongoing maintenance.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=50.0,
            client_payment_verified=True,
            client_rating=4.9
        )

        self.db.insert_job(job1, FilterDecision(passed=True, reason="passed", rule_name="PassedAll"))
        self.db.insert_job(job2, FilterDecision(passed=True, reason="passed", rule_name="PassedAll"))

        discovered = self.db.get_jobs_by_status("discovered")
        self.assertEqual(len(discovered), 2)

        evaluated_count = self.engine.evaluate_pending_jobs(self.db)
        self.assertEqual(evaluated_count, 2)

        evaluated = self.db.get_jobs_by_status("evaluated")
        self.assertEqual(len(evaluated), 2)
        for row in evaluated:
            self.assertIsNotNone(row["roi_score"])
            self.assertGreater(row["roi_score"], 0.0)

        hot_leads = self.db.get_hot_leads(min_roi=4.0)
        self.assertGreaterEqual(len(hot_leads), 1)

    def test_urgent_high_roi_alert_trigger(self):
        urgent_jobs = []

        def mock_notifier(job, result):
            urgent_jobs.append((job.id, result.roi_score))

        engine = RoiScoringEngine(self.config, on_urgent_lead=mock_notifier)

        urgent_job = JobLead(
            id="job:urgent_1",
            title="Urgent Senior Architect Needed",
            description="Need distributed system expert immediately.",
            job_type="fixed",
            platform="upwork",
            budget=3000.0,
            client_payment_verified=True,
            client_rating=5.0,
            proposals_count=2
        )

        res = engine.score_job(urgent_job)
        self.assertTrue(res.is_urgent)

        self.db.insert_job(urgent_job, FilterDecision(passed=True, reason="passed", rule_name="PassedAll"))
        engine.evaluate_pending_jobs(self.db)

        self.assertEqual(len(urgent_jobs), 1)
        self.assertEqual(urgent_jobs[0][0], "job:urgent_1")


if __name__ == "__main__":
    unittest.main()
