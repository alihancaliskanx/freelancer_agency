"""Telegram notification dispatcher for urgent job leads and agency alerts."""
import json
import os
import urllib.request
import urllib.error
from typing import Optional

from src.models import JobLead


class TelegramNotifier:
    """Dispatches proactive alerts and proposal approval requests via Telegram Bot API."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def format_urgent_lead(self, job: JobLead, roi_score: float, estimated_hours: float) -> str:
        rate_or_budget = (
            f"${job.budget:,.0f} fixed"
            if job.job_type == "fixed" and job.budget is not None
            else f"${job.hourly_rate_min or 0:.0f}-${job.hourly_rate_max or 0:.0f}/hr"
        )
        hire_info = f"{job.client_hire_rate:.0f}%" if job.client_hire_rate is not None else "N/A"
        rating_info = f"{job.client_rating:.1f}" if job.client_rating else "N/A"

        return (
            f"[{job.platform.upper()}] {job.title}\n"
            f"Budget: {rate_or_budget}\n"
            f"ROI: {roi_score:.1f}/10 | Est: {estimated_hours:.0f}h | Proposals: {job.proposals_count}\n"
            f"Client: {rating_info} (Hire: {hire_info})\n\n"
            f"{job.url}"
        )

    def build_urgent_lead_keyboard(self, job_id: str) -> dict:
        """Constructs inline buttons for one-tap action on mobile."""
        return {
            "inline_keyboard": [
                [
                    {"text": "Teklif Hazırla", "callback_data": f"draft:{job_id}"},
                    {"text": "Reddet", "callback_data": f"skip:{job_id}"}
                ]
            ]
        }

    def send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Sends message to the configured Telegram chat."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def send_urgent_alert(self, job: JobLead, roi_score: float, estimated_hours: float) -> bool:
        message = self.format_urgent_lead(job, roi_score, estimated_hours)
        keyboard = self.build_urgent_lead_keyboard(job.id)
        return self.send_message(message, reply_markup=keyboard)
