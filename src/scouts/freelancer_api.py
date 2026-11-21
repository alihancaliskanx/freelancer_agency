"""Freelancer.com REST API scout parser."""
import json
from typing import List, Optional, Dict, Any
import urllib.request
import urllib.error
import urllib.parse

from src.models import JobLead
from src.scouts.base import BaseScout


class FreelancerApiScout(BaseScout):
    """Consumes Freelancer.com public REST API into standardized JobLead instances."""

    DEFAULT_API_URL = "https://www.freelancer.com/api/projects/0.1/projects/active"
    DEFAULT_QUERIES = ["python", "automation", "api", "backend", "scraping", "bot", "full stack"]

    def __init__(self, api_url: Optional[str] = None, queries: Optional[List[str]] = None):
        self.api_url = api_url or self.DEFAULT_API_URL
        self.queries = queries if queries is not None else self.DEFAULT_QUERIES

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
            curr_code = currency.get("code", "USD") or "USD"
            curr_sign = currency.get("sign", "$") or "$"

            original_budget = budget
            original_hourly_min = hourly_min
            original_hourly_max = hourly_max

            # Freelancer API standard: exchange_rate is multiplier to USD
            if "exchange_rate" in currency and currency["exchange_rate"] is not None:
                usd_mult = float(currency["exchange_rate"] or 1.0)
            elif "rate" in currency and currency["rate"] is not None:
                # Legacy / mock rate fallback: divisor (e.g. rate: 0.92 EUR per USD)
                r = float(currency["rate"] or 1.0)
                usd_mult = (1.0 / r) if r > 0 else 1.0
            else:
                usd_mult = 1.0

            if usd_mult and usd_mult != 1.0:
                if budget is not None:
                    budget = round(budget * usd_mult, 2)
                if hourly_min is not None:
                    hourly_min = round(hourly_min * usd_mult, 2)
                if hourly_max is not None:
                    hourly_max = round(hourly_max * usd_mult, 2)

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
                    currency=curr_code,
                    currency_symbol=curr_sign,
                    original_budget=original_budget,
                    original_hourly_min=original_hourly_min,
                    original_hourly_max=original_hourly_max,
                    client_payment_verified=True,
                    proposals_count=proposals_count,
                    url=url,
                    raw_metadata={"currency": curr_code, "exchange_rate": usd_mult}
                )
            )

        return leads

    def fetch_leads(self) -> List[JobLead]:
        """Fetches active projects from the Freelancer REST API across targeted software queries."""
        all_leads: List[JobLead] = []
        seen_ids = set()

        query_list = self.queries if self.queries else [""]

        for q in query_list:
            q_param = f"&query={urllib.parse.quote(q)}" if q else ""
            url = f"{self.api_url}?compact=true&languages[]=en{q_param}&limit=25"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "FreelancerAgency/1.0 (Mozilla/5.0)",
                    "Accept": "application/json"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    parsed = self.parse_json(data)
                    for lead in parsed:
                        if lead.id not in seen_ids:
                            seen_ids.add(lead.id)
                            all_leads.append(lead)
            except Exception:
                continue

        return all_leads
