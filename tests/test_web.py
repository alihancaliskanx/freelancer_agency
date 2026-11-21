"""Unit tests for DashboardServer REST endpoints and Mini App static files."""
import json
import os
import shutil
import tempfile
import unittest
import urllib.request

from src.ceo.orchestrator import CeoOrchestrator
from src.db.manager import DatabaseManager
from src.models import JobLead, FilterDecision
from src.web.server import DashboardServer


class TestDashboardServer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_web.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()
        self.orchestrator = CeoOrchestrator(self.db)

        # Seed sample job
        job = JobLead(
            id="freelancer:web_1",
            title="Python Cloud Scraping API",
            description="Build a high-performance scraping service in Python and Docker.",
            job_type="fixed",
            platform="freelancer",
            budget=850.0,
            currency="USD",
            currency_symbol="$",
            original_budget=850.0,
            client_payment_verified=True,
            client_rating=4.9,
            proposals_count=3,
            url="https://freelancer.com/projects/web_1"
        )
        self.db.insert_job(job, FilterDecision(passed=True, reason="ok", rule_name="test"))
        self.db.update_job_status(job.id, status="evaluated", roi_score=9.1, estimated_hours=14.0)

        # Run on a local testing port
        self.port = 18999
        self.server = DashboardServer(self.orchestrator, self.db, host="127.0.0.1", port=self.port)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_index_html(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("Freelancer Agency OS", content)
            self.assertIn("telegram-web-app.js", content)

    def test_get_api_stats(self):
        url = f"http://127.0.0.1:{self.port}/api/stats"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("evaluated_jobs_count", data)
            self.assertEqual(data["evaluated_jobs_count"], 1)

    def test_get_api_jobs(self):
        url = f"http://127.0.0.1:{self.port}/api/jobs?type=hot"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("jobs", data)
            self.assertEqual(len(data["jobs"]), 1)
            j = data["jobs"][0]
            self.assertEqual(j["id"], "freelancer:web_1")
            self.assertEqual(j["roi_score"], 9.1)
            self.assertIn("formatted_price", j)
            self.assertIn("850 $", j["formatted_price"])

    def test_post_api_draft(self):
        url = f"http://127.0.0.1:{self.port}/api/draft"
        payload = json.dumps({"job_id": "freelancer:web_1"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            self.assertIn("cover_letter", data)
