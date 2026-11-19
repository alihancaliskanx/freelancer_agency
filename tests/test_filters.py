"""Unit tests for the Deterministic 0-Token Filter Engine with real-world edge cases."""
import unittest
from src.models import JobLead
from src.filters.engine import DeterministicFilterEngine, FilterConfig


class TestDeterministicFilterEngine(unittest.TestCase):
    def setUp(self):
        self.config = FilterConfig(
            min_fixed_budget=100.0,
            min_hourly_rate=30.0,
            min_client_rating=4.5,
            require_payment_verified=True,
            min_client_hire_rate=40.0,
            max_proposals_count=35,
            banned_keywords=["WordPress", "Shopify", "PHP 5", "Magento"],
        )
        self.engine = DeterministicFilterEngine(self.config)

    # --- POSITIVE TEST CASES (MUST PASS) ---

    def test_clean_fixed_price_dev_job_passes(self):
        job = JobLead(
            id="job-01",
            title="FastAPI Backend Engineer for Payment Integration",
            description="We need an experienced Python developer to integrate Stripe and webhooks. Clear specs provided.",
            job_type="fixed",
            platform="upwork",
            budget=600.0,
            client_payment_verified=True,
            client_rating=4.9,
            client_hire_rate=75.0,
            proposals_count=12,
        )
        decision = self.engine.evaluate(job)
        self.assertTrue(decision.passed)
        self.assertEqual(decision.rule_name, "PassedAllFilters")

    def test_clean_hourly_dev_job_passes(self):
        job = JobLead(
            id="job-02",
            title="Senior Full-Stack Developer (Vue + Django)",
            description="Looking for ongoing development support. Flexible hours, manual time entry is welcomed.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=40.0,
            hourly_rate_max=60.0,
            manual_time_allowed=True,
            client_payment_verified=True,
            client_rating=4.95,
            client_hire_rate=60.0,
            proposals_count=8,
        )
        decision = self.engine.evaluate(job)
        self.assertTrue(decision.passed)
        self.assertEqual(decision.rule_name, "PassedAllFilters")

    def test_ai_agent_dev_job_passes(self):
        """Crucial edge case: Job is ABOUT building AI, not prohibiting AI proposals."""
        job = JobLead(
            id="job-03",
            title="Build an AI Agent and RAG Pipeline with LangChain",
            description="We want to develop an autonomous AI agent that ingests documents and queries an LLM model.",
            job_type="fixed",
            platform="upwork",
            budget=1200.0,
            client_payment_verified=True,
            client_rating=5.0,
            client_hire_rate=80.0,
            proposals_count=14,
        )
        decision = self.engine.evaluate(job)
        self.assertTrue(decision.passed, f"Failed with reason: {decision.reason}")
        self.assertEqual(decision.rule_name, "PassedAllFilters")

    def test_time_tracking_app_dev_job_passes(self):
        """Crucial edge case: Job is to BUILD a time tracker tool, not demanding time tracking."""
        job = JobLead(
            id="job-04",
            title="Build a Time Tracker App for Remote Teams",
            description="We need a React Native and Python developer to create a clean work hour tracker tool.",
            job_type="fixed",
            platform="freelancer",
            budget=950.0,
            client_payment_verified=True,
            client_rating=4.8,
            client_hire_rate=50.0,
            proposals_count=10,
        )
        decision = self.engine.evaluate(job)
        self.assertTrue(decision.passed, f"Failed with reason: {decision.reason}")
        self.assertEqual(decision.rule_name, "PassedAllFilters")

    # --- NEGATIVE TEST CASES: HARD DROP FILTERS ---

    def test_anti_ai_proposals_forbidden_drops(self):
        job = JobLead(
            id="job-05",
            title="Web Scraping Specialist Needed",
            description="Need scripts to parse public data. Attention: No AI proposals, do not use ChatGPT to apply.",
            job_type="fixed",
            platform="upwork",
            budget=300.0,
            client_payment_verified=True,
            client_rating=4.9,
            proposals_count=5,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "AntiAiFilterRule")
        self.assertIn("anti_ai", decision.reason)

    def test_anti_ai_strictly_no_ai_drops(self):
        job = JobLead(
            id="job-06",
            title="Article and Technical Documentation Writer",
            description="We need accurate tech guides. Strictly no AI allowed in submissions. Human written proposals only.",
            job_type="fixed",
            platform="upwork",
            budget=250.0,
            client_payment_verified=True,
            client_rating=4.8,
            proposals_count=9,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "AntiAiFilterRule")

    def test_time_tracker_mandatory_in_text_drops(self):
        job = JobLead(
            id="job-07",
            title="Python Data Cleaning Assistant",
            description="Hourly task. You must track time with the Upwork desktop app. Screen recording will be checked.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=35.0,
            client_payment_verified=True,
            client_rating=4.7,
            proposals_count=6,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "TrackerGuardTextRule")
        self.assertIn("tracker_required", decision.reason)

    def test_time_tracker_metadata_flag_drops(self):
        job = JobLead(
            id="job-08",
            title="DevOps / Cloud Maintenance",
            description="Routine AWS setup and maintenance.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=50.0,
            manual_time_allowed=False,
            client_payment_verified=True,
            client_rating=4.9,
            proposals_count=4,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "TrackerGuardMetadataRule")

    def test_scam_offplatform_telegram_drops(self):
        job = JobLead(
            id="job-09",
            title="Data Entry and Scripting",
            description="Simple task. Please contact me on Telegram @fakeuser immediately for instructions.",
            job_type="fixed",
            platform="freelancer",
            budget=500.0,
            client_payment_verified=True,
            client_rating=5.0,
            proposals_count=2,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "ScamRedFlagRule")

    def test_unpaid_test_task_drops(self):
        job = JobLead(
            id="job-10",
            title="Frontend React Component Design",
            description="We require candidates to complete an unpaid test task before selection.",
            job_type="fixed",
            platform="upwork",
            budget=400.0,
            client_payment_verified=True,
            client_rating=4.6,
            proposals_count=15,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "ScamRedFlagRule")

    # --- NEGATIVE TEST CASES: BUDGET, QUALITY & GHOST JOBS ---

    def test_fixed_budget_too_low_drops(self):
        job = JobLead(
            id="job-11",
            title="Quick Bugfix on Flask App",
            description="Fix 500 error on checkout page.",
            job_type="fixed",
            platform="upwork",
            budget=35.0,
            client_payment_verified=True,
            client_rating=4.8,
            proposals_count=5,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "FixedBudgetRule")

    def test_hourly_rate_too_low_drops(self):
        job = JobLead(
            id="job-12",
            title="Junior Script Writer",
            description="Write python web scrapers.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=15.0,
            hourly_rate_max=22.0,
            client_payment_verified=True,
            client_rating=4.9,
            proposals_count=7,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "HourlyRateRule")

    def test_client_payment_unverified_drops(self):
        job = JobLead(
            id="job-13",
            title="Build an Ecommerce Store",
            description="Large project for our new retail branch.",
            job_type="fixed",
            platform="upwork",
            budget=800.0,
            client_payment_verified=False,
            client_rating=5.0,
            proposals_count=10,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "ClientPaymentVerifiedRule")

    def test_client_rating_too_low_drops(self):
        job = JobLead(
            id="job-14",
            title="Node.js Microservice Optimization",
            description="Improve response times on existing endpoints.",
            job_type="fixed",
            platform="upwork",
            budget=450.0,
            client_payment_verified=True,
            client_rating=3.9,
            proposals_count=12,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "ClientRatingRule")

    def test_ghost_job_drops(self):
        job = JobLead(
            id="job-15",
            title="Full-Stack Developer for SaaS Dashboard",
            description="Looking for experienced web devs.",
            job_type="fixed",
            platform="upwork",
            budget=1500.0,
            client_payment_verified=True,
            client_rating=4.6,
            client_hire_rate=18.0,
            proposals_count=48,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "GhostJobRule")

    def test_banned_keyword_wordpress_drops(self):
        job = JobLead(
            id="job-16",
            title="Fix WordPress Elementor Bug",
            description="Our WordPress site has a broken slider widget.",
            job_type="fixed",
            platform="upwork",
            budget=200.0,
            client_payment_verified=True,
            client_rating=4.9,
            proposals_count=5,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "BannedKeywordRule")
        self.assertIn("banned_keyword", decision.reason)

    def test_banned_keyword_shopify_drops(self):
        job = JobLead(
            id="job-17",
            title="Shopify Liquid Theme Developer",
            description="Need custom section in Shopify store.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=50.0,
            client_payment_verified=True,
            client_rating=5.0,
            proposals_count=4,
        )
        decision = self.engine.evaluate(job)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.rule_name, "BannedKeywordRule")


if __name__ == "__main__":
    unittest.main()
