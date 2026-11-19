"""Deterministic 0-Token Filter Engine for freelance job leads."""
import re
from typing import Optional, List, Tuple

try:
    from src.models import JobLead, FilterDecision
except ImportError:
    from models import JobLead, FilterDecision


class FilterConfig:
    def __init__(
        self,
        min_fixed_budget: float = 100.0,
        min_hourly_rate: float = 30.0,
        min_client_rating: float = 4.5,
        require_payment_verified: bool = True,
        min_client_hire_rate: float = 40.0,
        max_proposals_count: int = 35,
        banned_keywords: Optional[List[str]] = None,
    ):
        self.min_fixed_budget = min_fixed_budget
        self.min_hourly_rate = min_hourly_rate
        self.min_client_rating = min_client_rating
        self.require_payment_verified = require_payment_verified
        self.min_client_hire_rate = min_client_hire_rate
        self.max_proposals_count = max_proposals_count
        self.banned_keywords = banned_keywords or []


class DeterministicFilterEngine:
    """Evaluates JobLead instances against strict deterministic criteria at $0 token cost."""

    def __init__(self, config: Optional[FilterConfig] = None):
        self.config = config or FilterConfig()
        self._init_patterns()

    def _init_patterns(self):
        # Hard drop: Strict Anti-AI patterns (proposals/submissions/automation forbidden)
        self.anti_ai_patterns = [
            re.compile(r"\b(no\s+(ai|chatgpt|gpt-?4|llm|copilot|bots?|ai-generated)\s+(proposals?|bids?|cover\s+letters?|applications?|submissions?))\b", re.I),
            re.compile(r"\b(do\s+not\s+use\s+(ai|chatgpt|gpt|llm|copilot|bots?)\s+(to\s+(write|generate|apply|bid)|for\s+(this|proposals?|bids?)))\b", re.I),
            re.compile(r"\b(ai\s+(generated\s+)?(proposals?|bids?|cover\s+letters?)\s+will\s+be\s+(rejected|deleted|flagged|ignored|disqualified))\b", re.I),
            re.compile(r"\b(strictly\s+no\s+(ai|chatgpt|llm)\s+(allowed|proposals?|tools?))\b", re.I),
            re.compile(r"\b(human\s+(written\s+)?proposals?\s+only|no\s+bot\s+proposals?)\b", re.I),
            re.compile(r"\b(if\s+you\s+use\s+(ai|chatgpt|llm)\s+to\s+(apply|write))\b", re.I),
        ]

        # Hard drop: Desktop Time-Tracker patterns
        self.tracker_patterns = [
            re.compile(r"\b(must\s+track\s+time|time\s+tracker\s+(is\s+)?required|track\s+(your\s+)?time\s+with)\b", re.I),
            re.compile(r"\b(upwork\s+(desktop\s+app|time\s+tracker|tracker)\s+(is\s+)?(mandatory|required|needed))\b", re.I),
            re.compile(r"\b(manual\s+time\s+(is\s+)?(not\s+allowed|disabled|not\s+accepted|prohibited|no))\b", re.I),
            re.compile(r"\b(track(ing)?\s+keystrokes?|screen\s+(captures?|recording|screenshots?))\b", re.I),
            re.compile(r"\b(must\s+use\s+(the\s+)?(upwork\s+)?(desktop\s+app|time\s+tracker))\b", re.I),
        ]

        # Exception pattern: Project deliverable is building a tracker/timer tool
        self.tracker_app_dev_pattern = re.compile(
            r"\b(build|develop|create|code|design|engineer)\b.*\b(time\s+track(er|ing)|timer\s+app|work\s+hour\s+tracker)\b",
            re.I
        )

        # Scam / High Risk patterns
        self.scam_patterns = [
            re.compile(r"\b(unpaid\s+(test|trial|sample|task)|work\s+for\s+equity\s+only|pay\s+after\s+launch)\b", re.I),
            re.compile(r"\b(contact\s+me\s+on\s+telegram|telegram\s+me|dm\s+me\s+on\s+whatsapp|send\s+message\s+to\s+telegram)\b", re.I),
        ]

        # Custom banned tech keywords
        self.banned_keyword_patterns = [
            re.compile(rf"\b{re.escape(kw)}\b", re.I)
            for kw in self.config.banned_keywords
            if kw and kw.strip()
        ]

    def evaluate(self, job: JobLead) -> FilterDecision:
        """Run all stage 1 deterministic filters on the job lead."""
        combined_text = f"{job.title}\n{job.description}"

        # 0. Banned Technology Keywords
        for pattern in self.banned_keyword_patterns:
            match = pattern.search(combined_text)
            if match:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:banned_keyword ({match.group(0)})",
                    rule_name="BannedKeywordRule",
                    details={"matched_keyword": match.group(0)}
                )

        # 1. Scam & Off-Platform Red Flags
        for pattern in self.scam_patterns:
            match = pattern.search(combined_text)
            if match:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:scam_or_unpaid ({match.group(0)})",
                    rule_name="ScamRedFlagRule",
                    details={"matched_text": match.group(0)}
                )

        # 2. Strict Anti-AI Application Filter
        for pattern in self.anti_ai_patterns:
            match = pattern.search(combined_text)
            if match:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:anti_ai_policy ({match.group(0)})",
                    rule_name="AntiAiFilterRule",
                    details={"matched_text": match.group(0)}
                )

        # 3. Desktop Time-Tracker Guard
        # Check metadata flag first
        if job.manual_time_allowed is False:
            return FilterDecision(
                passed=False,
                reason="drop:tracker_required (manual_time_allowed=False)",
                rule_name="TrackerGuardMetadataRule",
                details={"manual_time_allowed": False}
            )

        # Check tracker text requirements unless this is a project to build a tracker tool
        is_tracker_dev = bool(self.tracker_app_dev_pattern.search(job.title))
        if not is_tracker_dev:
            for pattern in self.tracker_patterns:
                match = pattern.search(combined_text)
                if match:
                    return FilterDecision(
                        passed=False,
                        reason=f"drop:tracker_required ({match.group(0)})",
                        rule_name="TrackerGuardTextRule",
                        details={"matched_text": match.group(0)}
                    )

        # 4. Client Payment Verification Check
        if self.config.require_payment_verified and not job.client_payment_verified:
            return FilterDecision(
                passed=False,
                reason="drop:client_payment_unverified",
                rule_name="ClientPaymentVerifiedRule",
                details={"client_payment_verified": job.client_payment_verified}
            )

        # 5. Client Rating Check
        if job.client_rating is not None and job.client_rating > 0:
            if job.client_rating < self.config.min_client_rating:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:client_rating_too_low ({job.client_rating} < {self.config.min_client_rating})",
                    rule_name="ClientRatingRule",
                    details={"client_rating": job.client_rating, "min_required": self.config.min_client_rating}
                )

        # 6. Ghost Job & Proposal Crowd Filter
        # If proposals > max_proposals_count and client has low hire rate, discard.
        if job.proposals_count > self.config.max_proposals_count:
            if job.client_hire_rate is not None and job.client_hire_rate < self.config.min_client_hire_rate:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:ghost_job (proposals={job.proposals_count}, hire_rate={job.client_hire_rate}%)",
                    rule_name="GhostJobRule",
                    details={"proposals_count": job.proposals_count, "client_hire_rate": job.client_hire_rate}
                )

        # 7. Budget & Rate Routing Checks
        if job.job_type == "fixed":
            if job.budget is not None and job.budget < self.config.min_fixed_budget:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:fixed_budget_too_low (${job.budget} < ${self.config.min_fixed_budget})",
                    rule_name="FixedBudgetRule",
                    details={"budget": job.budget, "min_budget": self.config.min_fixed_budget}
                )
        elif job.job_type == "hourly":
            # For hourly, evaluate hourly_rate_max or hourly_rate_min
            rate = job.hourly_rate_max if job.hourly_rate_max is not None else job.hourly_rate_min
            if rate is not None and rate < self.config.min_hourly_rate:
                return FilterDecision(
                    passed=False,
                    reason=f"drop:hourly_rate_too_low (${rate}/hr < ${self.config.min_hourly_rate}/hr)",
                    rule_name="HourlyRateRule",
                    details={"rate": rate, "min_hourly_rate": self.config.min_hourly_rate}
                )

        # If all checks pass
        return FilterDecision(
            passed=True,
            reason="passed:all_deterministic_filters",
            rule_name="PassedAllFilters",
            details={
                "job_type": job.job_type,
                "platform": job.platform,
                "budget_or_rate": job.budget if job.job_type == "fixed" else (job.hourly_rate_max or job.hourly_rate_min)
            }
        )
