"""Unit tests for Upwork RSS, Freelancer API, and ScoutCoordinator."""
import os
import shutil
import tempfile
import unittest
from src.scouts.upwork_rss import UpworkRssScout
from src.scouts.freelancer_api import FreelancerApiScout
from src.scouts.coordinator import ScoutCoordinator
from src.scouts.base import BaseScout
from src.models import JobLead
from src.filters.engine import DeterministicFilterEngine
from src.db.manager import DatabaseManager


SAMPLE_UPWORK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Upwork Jobs</title>
    <link>https://www.upwork.com</link>
    <description>Jobs feed</description>
    <item>
        <title>FastAPI Developer Needed for Webhooks - Upwork</title>
        <link>https://www.upwork.com/jobs/FastAPI-Developer_~01fedcba9876543210/</link>
        <description>Looking for a Python dev to integrate Stripe webhooks.&lt;br /&gt;&lt;br /&gt;&lt;b&gt;Budget&lt;/b&gt;: $650&lt;br /&gt;&lt;b&gt;Posted On&lt;/b&gt;: November 19, 2026 10:00 UTC&lt;br /&gt;&lt;b&gt;Country&lt;/b&gt;: United States&lt;br /&gt;&lt;b&gt;Payment Method&lt;/b&gt;: Verified</description>
    </item>
    <item>
        <title>Ongoing Django Engineer - Upwork</title>
        <link>https://www.upwork.com/jobs/Django-Engineer_~011122334455667788/</link>
        <description>Need regular backend support.&lt;br /&gt;&lt;br /&gt;&lt;b&gt;Hourly Range&lt;/b&gt;: $45.00-$65.00&lt;br /&gt;&lt;b&gt;Posted On&lt;/b&gt;: November 19, 2026 11:00 UTC&lt;br /&gt;&lt;b&gt;Payment Method&lt;/b&gt;: Verified</description>
    </item>
</channel>
</rss>
"""

SAMPLE_FREELANCER_JSON = {
    "status": "success",
    "result": {
        "projects": [
            {
                "id": 99887766,
                "title": "Build a Cloudflare Worker API",
                "preview_description": "We need an edge worker built with TypeScript and Python.",
                "type": "fixed",
                "budget": {"minimum": 200, "maximum": 500},
                "currency": {"code": "EUR", "rate": 0.92},
                "bid_stats": {"bid_count": 5},
                "seo_url": "python/Build-Cloudflare-Worker"
            },
            {
                "id": 88776655,
                "title": "Hourly Data Pipeline Setup",
                "preview_description": "Setup ETL pipelines. Manual time allowed.",
                "type": "hourly",
                "budget": {"minimum": 35, "maximum": 55},
                "currency": {"code": "USD", "rate": 1.0},
                "bid_stats": {"bid_count": 12},
                "seo_url": "python/Hourly-Data-Pipeline"
            }
        ]
    }
}


class MockScout(BaseScout):
    def __init__(self, leads):
        self.leads = leads

    def fetch_leads(self):
        return self.leads


class TestScouts(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_scouts.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()
        self.filter_engine = DeterministicFilterEngine()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_upwork_rss_parser(self):
        scout = UpworkRssScout()
        leads = scout.parse_xml(SAMPLE_UPWORK_RSS)
        self.assertEqual(len(leads), 2)

        fixed_job = leads[0]
        self.assertEqual(fixed_job.id, "upwork:~01fedcba9876543210")
        self.assertEqual(fixed_job.title, "FastAPI Developer Needed for Webhooks")
        self.assertEqual(fixed_job.budget, 650.0)
        self.assertEqual(fixed_job.job_type, "fixed")
        self.assertTrue(fixed_job.client_payment_verified)
        self.assertEqual(fixed_job.raw_metadata["country"], "United States")

        hourly_job = leads[1]
        self.assertEqual(hourly_job.id, "upwork:~011122334455667788")
        self.assertEqual(hourly_job.job_type, "hourly")
        self.assertEqual(hourly_job.hourly_rate_min, 45.0)
        self.assertEqual(hourly_job.hourly_rate_max, 65.0)
        self.assertTrue(hourly_job.client_payment_verified)

    def test_freelancer_api_parser(self):
        scout = FreelancerApiScout()
        leads = scout.parse_json(SAMPLE_FREELANCER_JSON)
        self.assertEqual(len(leads), 2)

        fixed_job = leads[0]
        self.assertEqual(fixed_job.id, "freelancer:99887766")
        self.assertEqual(fixed_job.title, "Build a Cloudflare Worker API")
        self.assertEqual(fixed_job.job_type, "fixed")
        self.assertAlmostEqual(fixed_job.budget, 543.48, places=2)
        self.assertEqual(fixed_job.proposals_count, 5)

        hourly_job = leads[1]
        self.assertEqual(hourly_job.id, "freelancer:88776655")
        self.assertEqual(hourly_job.job_type, "hourly")
        self.assertEqual(hourly_job.hourly_rate_min, 35.0)
        self.assertEqual(hourly_job.hourly_rate_max, 55.0)

    def test_coordinator_scan_pipeline(self):
        lead1 = JobLead(
            id="test:1",
            title="Senior Python Architect",
            description="Build scalable microservices with FastAPI.",
            job_type="fixed",
            platform="upwork",
            budget=800.0,
            client_payment_verified=True,
            client_rating=4.9
        )
        lead2_bad = JobLead(
            id="test:2",
            title="Simple Task",
            description="Must track time with desktop app.",
            job_type="hourly",
            platform="upwork",
            hourly_rate_min=40.0,
            client_payment_verified=True
        )

        mock = MockScout([lead1, lead2_bad])
        coordinator = ScoutCoordinator([mock], self.filter_engine, self.db)

        stats1 = coordinator.run_scan()
        self.assertEqual(stats1["total_scanned"], 2)
        self.assertEqual(stats1["new_inserted"], 2)
        self.assertEqual(stats1["passed_filters"], 1)
        self.assertEqual(stats1["duplicates"], 0)

        stats2 = coordinator.run_scan()
        self.assertEqual(stats2["total_scanned"], 2)
        self.assertEqual(stats2["new_inserted"], 0)
        self.assertEqual(stats2["duplicates"], 2)

        metrics = self.db.get_latest_metrics()
        self.assertEqual(metrics["total_jobs_scanned"], 4)
        self.assertEqual(metrics["jobs_passed_filter"], 2)


if __name__ == "__main__":
    unittest.main()
