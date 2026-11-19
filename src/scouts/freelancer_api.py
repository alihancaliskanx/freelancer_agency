"""Freelancer.com REST API scout parser."""
import json
from typing import List, Optional, Dict, Any
import urllib.request
import urllib.error

from src.models import JobLead
from src.scouts.base import BaseScout


class FreelancerApiScout(BaseScout):
    """Consumes Freelancer.com public REST API into standardized JobLead instances."""

    DEFAULT_API_URL = "https://www.freelancer.com/api/projects/0.1/projects/active"

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url or self.DEFAULT_API_URL

    def parse_json(self, payload: Dict[str, Any]) -> List[JobLead]:
        """Parses Freelancer.com active projects JSON structure."""
        leads: List[JobLead] = []
        result = payload.get("result", {})
        projects = result.get("projects", [])

        for p in projects:
            project_id = str(p.get("id", ""))
            if not project_id:
                continue

            title = p.get("title", "").strip()
            desc = p.get("preview_description", "").strip()

            raw_type = p.get("type", "fixed").lower()
            job_type = "hourly" if raw_type == "hourly" else "fixed"

            budget_info = p.get("budget", {})
            min_b = budget_info.get("minimum")
            max_b = budget_info.get("maximum")

            budget = None
            hourly_min = None
            hourly_max = None

            if job_type == "fixed":
                budget = float(max_b) if max_b is not None else (float(min_b) if min_b is not None else None)
            else:
                hourly_min = float(min_b) if min_b is not None else None
                hourly_max = float(max_b) if max_b is not None else None

            bid_stats = p.get("bid_stats", {})
            proposals_count = int(bid_stats.get("bid_count", 0))

            seo_url = p.get("seo_url", "")
            url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else f"https://www.freelancer.com/projects/{project_id}"

            currency = p.get("currency", {})
            rate = currency.get("rate", 1.0) or 1.0

            if rate and rate > 0 and rate != 1.0:
                if budget is not None:
                    budget = round(budget / rate, 2)
                if hourly_min is not None:
                    hourly_min = round(hourly_min / rate, 2)
                if hourly_max is not None:
                    hourly_max = round(hourly_max / rate, 2)

            leads.append(
                JobLead(
                    id=f"freelancer:{project_id}",
                    title=title,
                    description=desc,
                    job_type=job_type,
                    platform="freelancer",
                    budget=budget,
                    hourly_rate_min=hourly_min,
                    hourly_rate_max=hourly_max,
                    client_payment_verified=True,
                    proposals_count=proposals_count,
                    url=url,
                    raw_metadata={"currency": currency.get("code", "USD")}
                )
            )

        return leads

    def fetch_leads(self) -> List[JobLead]:
        """Fetches active projects from the Freelancer REST API."""
        url = f"{self.api_url}?compact=true&languages[]=en&limit=30"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FreelancerAgency/1.0 (Mozilla/5.0)",
                "Accept": "application/json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return self.parse_json(data)
        except Exception:
            return []
