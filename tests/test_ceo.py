"""Unit tests for CeoOrchestrator and McpServer."""
import json
import os
import shutil
import tempfile
import unittest

from src.ceo.orchestrator import CeoOrchestrator
from src.ceo.mcp_server import McpServer
from src.models import JobLead, FilterDecision
from src.db.manager import DatabaseManager


class TestCeoOrchestratorAndMcp(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_ceo.db")
        self.db = DatabaseManager(self.db_path)
        self.db.init_db()
        self.orchestrator = CeoOrchestrator(self.db)
        self.mcp = McpServer(self.orchestrator)

        self.sample_job = JobLead(
            id="job:sample_1",
            title="FastAPI Payment Integration",
            description="Integrate Stripe checkout webhooks with PostgreSQL.",
            job_type="fixed",
            platform="upwork",
            budget=900.0,
            client_payment_verified=True,
            client_rating=4.95,
            proposals_count=6,
            url="https://upwork.com/jobs/sample_1"
        )
        self.db.insert_job(self.sample_job, FilterDecision(passed=True, reason="ok", rule_name="r"))
        self.db.update_job_status(self.sample_job.id, status="evaluated", roi_score=8.7, estimated_hours=12.0)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_overview(self):
        overview = self.orchestrator.get_status_overview()
        self.assertEqual(overview["evaluated_jobs_count"], 1)
        self.assertEqual(overview["hot_leads_count"], 1)
        self.assertEqual(overview["proposals_pending_count"], 0)

    def test_list_hot_opportunities(self):
        leads = self.orchestrator.list_hot_opportunities(min_roi=7.0)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["id"], "job:sample_1")
        self.assertEqual(leads[0]["roi_score"], 8.7)

    def test_draft_proposal_workflow(self):
        res = self.orchestrator.draft_proposal("job:sample_1", "Focus on PCI compliance.")
        self.assertTrue(res["success"])
        self.assertEqual(res["bid_amount"], 900.0)
        self.assertIn("PCI compliance", res["cover_letter"])

        job = self.db.get_job("job:sample_1")
        self.assertEqual(job["status"], "proposal_drafted")

        proposals = self.db.get_proposals_for_job("job:sample_1")
        self.assertEqual(len(proposals), 1)

    def test_handle_callback_buttons(self):
        reply = self.orchestrator.handle_callback("draft:job:sample_1")
        self.assertIn("Proposal drafted", reply)

        job2 = JobLead(id="job:sample_2", title="Task", description="Desc", job_type="fixed", platform="freelancer")
        self.db.insert_job(job2)
        skip_reply = self.orchestrator.handle_callback("skip:job:sample_2")
        self.assertIn("dismissed", skip_reply)

        row = self.db.get_job("job:sample_2")
        self.assertEqual(row["status"], "rejected")

        # In-place pagination callback
        page_reply = self.orchestrator.handle_callback("page:listall:1")
        self.assertIsInstance(page_reply, tuple)
        self.assertIn("Tüm Aktif Fırsatlar", page_reply[0])
        self.assertIn("inline_keyboard", page_reply[1])

    def test_handle_message_commands(self):
        # Default Turkish
        status_text = self.orchestrator.handle_message("/status")
        self.assertIn("Ajans Durum Raporu", status_text)

        hot_text = self.orchestrator.handle_message("/hot")
        self.assertIn("Öne Çıkan Sıcak Fırsatlar", hot_text)
        self.assertIn("FastAPI Payment Integration", hot_text)
        self.assertIn("Detay:", hot_text)

        # List all command (returns in-place paginated tuple with inline buttons)
        listall_res = self.orchestrator.handle_message("/listall")
        self.assertIsInstance(listall_res, tuple)
        listall_text, listall_kb = listall_res
        self.assertIn("Tüm Aktif Fırsatlar", listall_text)
        self.assertIn("FastAPI Payment Integration", listall_text)
        self.assertIn("show", listall_text)
        self.assertIn("inline_keyboard", listall_kb)

        # Persistent reply keyboard button presses
        btn_hot = self.orchestrator.handle_message("🔥 Sıcak Fırsatlar")
        self.assertIn("Öne Çıkan Sıcak Fırsatlar", btn_hot)

        btn_list = self.orchestrator.handle_message("📋 Tüm İlanlar")
        self.assertIsInstance(btn_list, tuple)
        self.assertIn("Tüm Aktif Fırsatlar", btn_list[0])

        btn_status = self.orchestrator.handle_message("📊 Ajans Durumu")
        self.assertIn("Ajans Durum Raporu", btn_status)

        draft_text = self.orchestrator.handle_message("draft job:sample_1")
        self.assertIn("Teklif Hazırlandı", draft_text)

        draft_slash = self.orchestrator.handle_message("/draft job:sample_1")
        self.assertIn("Teklif Hazırlandı", draft_slash)

        help_text = self.orchestrator.handle_message("hello")
        self.assertIn("Freelancer Agency CEO Arayüzü", help_text)

        # Show command (Turkish)
        show_res = self.orchestrator.handle_message("show job:sample_1")
        self.assertIsInstance(show_res, tuple)
        card_text, keyboard = show_res
        self.assertIn("*Platform:* Upwork", card_text)
        self.assertIn("*Fiyat:*", card_text)
        self.assertIn("inline_keyboard", keyboard)
        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "İlanı Aç ↗")

        # Slash show command
        show_slash = self.orchestrator.handle_message("/show job:sample_1")
        self.assertIsInstance(show_slash, tuple)
        self.assertIn("*Platform:* Upwork", show_slash[0])

        # Show without prefix
        show_noprefix = self.orchestrator.handle_message("show sample_1")
        self.assertIsInstance(show_noprefix, tuple)
        self.assertIn("FastAPI Payment Integration", show_noprefix[0])

        # Show non-existing
        show_missing = self.orchestrator.handle_message("show nonexistent_99")
        self.assertIn("İlan bulunamadı", show_missing)

        # Language change to English
        lang_reply = self.orchestrator.handle_message("/lang en")
        self.assertIn("English", lang_reply)

        status_en = self.orchestrator.handle_message("/status")
        self.assertIn("Agency Status Overview", status_en)

        # Show command (English)
        show_en = self.orchestrator.handle_message("show job:sample_1")
        self.assertIn("*Price:*", show_en[0])

        # Switch back to Turkish
        self.orchestrator.handle_message("/dil tr")

    def test_mcp_tools_list_and_call(self):
        # 1. MCP Handshake Initialize
        req_init = {"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}}
        res_init = self.mcp.handle_request(req_init)
        self.assertEqual(res_init["result"]["serverInfo"]["name"], "freelancer-agency-mcp")
        self.assertIn("protocolVersion", res_init["result"])

        # 2. MCP Handshake Notification
        req_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        res_notif = self.mcp.handle_request(req_notif)
        self.assertIsNone(res_notif)

        # 3. MCP Ping
        req_ping = {"jsonrpc": "2.0", "id": 101, "method": "ping"}
        res_ping = self.mcp.handle_request(req_ping)
        self.assertEqual(res_ping["result"], {})

        # 4. Tools list
        req_list = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        res_list = self.mcp.handle_request(req_list)
        tools = res_list["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("list_hot_jobs", tool_names)
        self.assertIn("get_agency_stats", tool_names)
        self.assertIn("draft_proposal", tool_names)

        req_call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_hot_jobs", "arguments": {"min_roi": 5.0}}
        }
        res_call = self.mcp.handle_request(req_call)
        payload = json.loads(res_call["result"]["content"][0]["text"])
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], "job:sample_1")


if __name__ == "__main__":
    unittest.main()
