"""CEO Orchestrator: The single conversational executive touchpoint for the user."""
import json
import re
from typing import Optional, Dict, Any, List

from src.db.manager import DatabaseManager
from src.scouts.coordinator import ScoutCoordinator
from src.notifications.telegram import TelegramNotifier
from src.models import JobLead


class CeoOrchestrator:
    """Coordinates agency operations and communicates directly with the user."""

    def __init__(
        self,
        db: DatabaseManager,
        coordinator: Optional[ScoutCoordinator] = None,
        notifier: Optional[TelegramNotifier] = None
    ):
        self.db = db
        self.coordinator = coordinator
        self.notifier = notifier

    def get_status_overview(self) -> Dict[str, Any]:
        metrics = self.db.get_latest_metrics() or {}
        hot_leads = self.db.get_hot_leads(min_roi=6.0, limit=5)
        active_evaluated = self.db.get_jobs_by_status("evaluated", limit=100)
        drafted_proposals = self.db.get_jobs_by_status("proposal_drafted", limit=100)

        return {
            "metrics": metrics,
            "hot_leads_count": len(hot_leads),
            "evaluated_jobs_count": len(active_evaluated),
            "proposals_pending_count": len(drafted_proposals),
            "top_hot_leads": hot_leads
        }

    def list_hot_opportunities(self, min_roi: float = 5.0, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.get_hot_leads(min_roi=min_roi, limit=limit)

    def draft_proposal(self, job_id: str, custom_instructions: str = "") -> Dict[str, Any]:
        job = self.db.get_job(job_id)
        if not job:
            return {"success": False, "error": f"Job not found: {job_id}"}

        title = job["title"]
        job_type = job["job_type"]
        budget = job["budget"] or 0.0
        hourly_min = job["hourly_rate_min"] or 0.0
        hourly_max = job["hourly_rate_max"] or 0.0

        if job_type == "fixed":
            bid_amount = budget if budget > 0 else 500.0
            bid_summary = f"${bid_amount:,.2f}"
            timeline = "3-5 business days"
        else:
            bid_amount = hourly_max if hourly_max > 0 else (hourly_min if hourly_min > 0 else 50.0)
            bid_summary = f"${bid_amount:,.2f}/hr"
            timeline = "Ongoing / Flexible"

        cover_letter = (
            f"Dear Client,\n\n"
            f"I reviewed your project '{title}' and have the direct technical expertise "
            f"to deliver a robust solution without unnecessary complexity.\n\n"
            f"Technical Approach:\n"
            f"- Thorough requirement analysis and structured delivery.\n"
            f"- Clean, modular, well-tested code following best practices.\n"
            f"- Transparent milestones with regular async progress updates.\n\n"
            f"{custom_instructions}\n"
            f"I look forward to discussing the next steps.\n\n"
            f"Best regards."
        ).strip()

        prop_id = self.db.create_proposal(
            job_id=job_id,
            cover_letter=cover_letter,
            bid_amount=bid_amount,
            estimated_timeline=timeline,
            token_cost_usd=0.02
        )

        self.db.update_job_status(job_id, status="proposal_drafted")
        self.db.record_metric_heartbeat(proposals_increment=1, token_cost_increment=0.02)

        return {
            "success": True,
            "proposal_id": prop_id,
            "job_id": job_id,
            "bid_amount": bid_amount,
            "bid_summary": bid_summary,
            "cover_letter": cover_letter
        }

    def handle_callback(self, callback_data: str) -> str:
        """Handles inline button callbacks (e.g. from Telegram)."""
        if callback_data.startswith("draft:"):
            job_id = callback_data.split("draft:", 1)[1]
            res = self.draft_proposal(job_id)
            if res.get("success"):
                return f"Proposal drafted for {job_id} ({res['bid_summary']}):\n\n{res['cover_letter']}"
            return f"Failed to draft proposal: {res.get('error')}"

        elif callback_data.startswith("skip:"):
            job_id = callback_data.split("skip:", 1)[1]
            self.db.update_job_status(job_id, status="rejected")
            return f"Opportunity {job_id} dismissed."

        return "Unknown action."

    def handle_message(self, message: str) -> str:
        """Processes conversational executive commands from user."""
        msg = message.strip().lower()

        if msg in ("/status", "status", "durum"):
            overview = self.get_status_overview()
            m = overview["metrics"]
            return (
                f"Agency Status\n"
                f"Scanned today: {m.get('total_jobs_scanned', 0)}\n"
                f"Passed filter: {m.get('jobs_passed_filter', 0)}\n"
                f"Proposals generated: {m.get('proposals_generated', 0)}\n"
                f"Token cost: ${m.get('total_token_cost_usd', 0.0):.4f}\n"
                f"Active leads: {overview['evaluated_jobs_count']}\n"
                f"Pending proposals: {overview['proposals_pending_count']}"
            )

        if msg in ("/hot", "hot", "leads", "fırsatlar"):
            leads = self.list_hot_opportunities(min_roi=5.0, limit=5)
            if not leads:
                return "No hot opportunities found."
            lines = ["Qualified Opportunities:"]
            for l in leads:
                rate = f"${l['budget']} fixed" if l['job_type'] == 'fixed' else f"${l['hourly_rate_min'] or 0:.0f}-${l['hourly_rate_max'] or 0:.0f}/hr"
                lines.append(f"• [{l['id']}] {l['title']} (ROI: {l['roi_score']} | {rate})")
            return "\n".join(lines)

        if msg in ("/scan", "scan", "tara"):
            if self.coordinator:
                stats = self.coordinator.run_scan()
                return (
                    f"Scan Completed:\n"
                    f"Scanned: {stats['total_scanned']}\n"
                    f"Passed: {stats['passed_filters']}\n"
                    f"New: {stats['new_inserted']}\n"
                    f"Duplicates: {stats['duplicates']}"
                )
            return "Scout coordinator not configured on this instance."

        draft_match = re.match(r"(?:draft|teklif\s+hazırla)\s+([^\s]+)", msg)
        if draft_match:
            job_id = draft_match.group(1)
            res = self.draft_proposal(job_id)
            if res.get("success"):
                return f"Proposal Drafted:\n\n{res['cover_letter']}"
            return f"Error: {res.get('error')}"

        return (
            "Agency CEO Interface\n\n"
            "Commands:\n"
            "/status - View metrics and pipeline counts\n"
            "/hot    - View qualified opportunities\n"
            "/scan   - Trigger immediate scan cycle\n"
            "draft <id> - Generate proposal for job"
        )
