"""ROI, duration, and token cost evaluation engine for qualified job leads."""
from dataclasses import dataclass, field
import re
from typing import Optional, Dict, Any, List, Callable

from src.models import JobLead
from src.db.manager import DatabaseManager


@dataclass
class ScoringResult:
    roi_score: float  # Normalized score (0.0 to 10.0)
    estimated_hours: float
    estimated_token_cost: float
    complexity: str  # 'low', 'medium', 'high'
    recommendation: str  # 'strong_fit', 'fit', 'marginal', 'skip'
    is_urgent: bool = False
    breakdown: Dict[str, Any] = field(default_factory=dict)


class ScoringConfig:
    def __init__(
        self,
        target_hourly_rate: float = 50.0,
        default_token_cost_usd: float = 0.50,
        min_strong_fit_roi: float = 7.0,
        min_fit_roi: float = 4.5,
        min_marginal_roi: float = 2.5,
        urgent_roi_threshold: float = 8.5,
        urgent_max_proposals: int = 5,
    ):
        self.target_hourly_rate = target_hourly_rate
        self.default_token_cost_usd = default_token_cost_usd
        self.min_strong_fit_roi = min_strong_fit_roi
        self.min_fit_roi = min_fit_roi
        self.min_marginal_roi = min_marginal_roi
        self.urgent_roi_threshold = urgent_roi_threshold
        self.urgent_max_proposals = urgent_max_proposals


class RoiScoringEngine:
    """Evaluates qualified jobs on feasibility, duration, token costs, and ROI yield."""

    def __init__(
        self,
        config: Optional[ScoringConfig] = None,
        on_urgent_lead: Optional[Callable[[JobLead, ScoringResult], None]] = None
    ):
        self.config = config or ScoringConfig()
        self.on_urgent_lead = on_urgent_lead
        self._init_complexity_keywords()

    def _init_complexity_keywords(self):
        self.high_complexity_pattern = re.compile(
            r"\b(architect(ure)?|distributed|microservices?|high-availability|cluster|low-level|compiler|cryptography|scale\s+to\s+millions)\b",
            re.I
        )
        self.low_complexity_pattern = re.compile(
            r"\b(script|bugfix|simple|single\s+page|endpoint|scraper|cron|minor\s+change|quick\s+fix)\b",
            re.I
        )

    def _assess_complexity(self, text: str) -> str:
        if self.high_complexity_pattern.search(text):
            return "high"
        if self.low_complexity_pattern.search(text):
            return "low"
        return "medium"

    def _estimate_fixed_hours(self, text: str, budget: float, complexity: str) -> float:
        word_count = len(text.split())

        if complexity == "low":
            base_hours = 3.0 + min(4.0, word_count / 100.0)
        elif complexity == "high":
            base_hours = 15.0 + min(20.0, word_count / 50.0)
        else:
            base_hours = 8.0 + min(10.0, word_count / 80.0)

        implied_hours = budget / 40.0
        estimated = (base_hours * 0.6) + (implied_hours * 0.4)
        return max(2.0, round(estimated, 1))

    def score_fixed_job(self, job: JobLead) -> ScoringResult:
        combined = f"{job.title} {job.description}"
        complexity = self._assess_complexity(combined)
        budget = job.budget or 100.0

        estimated_hours = self._estimate_fixed_hours(combined, budget, complexity)
        token_multiplier = {"low": 0.5, "medium": 1.0, "high": 2.5}[complexity]
        estimated_token_cost = round(self.config.default_token_cost_usd * token_multiplier, 2)

        net_earnings = max(0.0, budget - estimated_token_cost)
        target_yield = estimated_hours * self.config.target_hourly_rate
        raw_ratio = net_earnings / target_yield if target_yield > 0 else 1.0

        rating_mult = (job.client_rating / 5.0) if (job.client_rating and job.client_rating > 0) else 0.95
        competition_mult = 1.0
        if job.proposals_count <= 5:
            competition_mult = 1.15
        elif job.proposals_count > 25:
            competition_mult = 0.85

        combined_ratio = raw_ratio * rating_mult * competition_mult
        roi_score = round(min(10.0, max(1.0, combined_ratio * 5.0)), 2)

        if roi_score >= self.config.min_strong_fit_roi:
            recommendation = "strong_fit"
        elif roi_score >= self.config.min_fit_roi:
            recommendation = "fit"
        elif roi_score >= self.config.min_marginal_roi:
            recommendation = "marginal"
        else:
            recommendation = "skip"

        is_urgent = bool(
            roi_score >= self.config.urgent_roi_threshold
            and job.proposals_count <= self.config.urgent_max_proposals
        )

        return ScoringResult(
            roi_score=roi_score,
            estimated_hours=estimated_hours,
            estimated_token_cost=estimated_token_cost,
            complexity=complexity,
            recommendation=recommendation,
            is_urgent=is_urgent,
            breakdown={
                "job_type": "fixed",
                "budget": budget,
                "net_earnings": net_earnings,
                "raw_ratio": round(raw_ratio, 2),
                "rating_mult": round(rating_mult, 2),
                "competition_mult": round(competition_mult, 2),
                "is_urgent": is_urgent
            }
        )

    def score_hourly_job(self, job: JobLead) -> ScoringResult:
        combined = f"{job.title} {job.description}"
        complexity = self._assess_complexity(combined)

        effective_rate = job.hourly_rate_max or job.hourly_rate_min or self.config.target_hourly_rate
        estimated_hours = 20.0
        estimated_token_cost = round(self.config.default_token_cost_usd * 0.75, 2)

        raw_ratio = effective_rate / self.config.target_hourly_rate
        rating_mult = (job.client_rating / 5.0) if (job.client_rating and job.client_rating > 0) else 0.95
        hire_mult = 1.0
        if job.client_hire_rate and job.client_hire_rate >= 70.0:
            hire_mult = 1.1
        elif job.client_hire_rate and job.client_hire_rate < 50.0:
            hire_mult = 0.9

        combined_ratio = raw_ratio * rating_mult * hire_mult
        roi_score = round(min(10.0, max(1.0, combined_ratio * 5.0)), 2)

        if roi_score >= self.config.min_strong_fit_roi:
            recommendation = "strong_fit"
        elif roi_score >= self.config.min_fit_roi:
            recommendation = "fit"
        elif roi_score >= self.config.min_marginal_roi:
            recommendation = "marginal"
        else:
            recommendation = "skip"

        is_urgent = bool(
            roi_score >= self.config.urgent_roi_threshold
            and job.proposals_count <= self.config.urgent_max_proposals
        )

        return ScoringResult(
            roi_score=roi_score,
            estimated_hours=estimated_hours,
            estimated_token_cost=estimated_token_cost,
            complexity=complexity,
            recommendation=recommendation,
            is_urgent=is_urgent,
            breakdown={
                "job_type": "hourly",
                "effective_rate": effective_rate,
                "raw_ratio": round(raw_ratio, 2),
                "rating_mult": round(rating_mult, 2),
                "hire_mult": round(hire_mult, 2),
                "is_urgent": is_urgent
            }
        )

    def score_job(self, job: JobLead) -> ScoringResult:
        """Routes job to fixed or hourly scoring track."""
        if job.job_type == "fixed":
            return self.score_fixed_job(job)
        return self.score_hourly_job(job)

    def evaluate_pending_jobs(self, db: DatabaseManager) -> int:
        """Fetches newly discovered jobs that passed filters, computes ROI, and updates DB."""
        unscored = db.get_jobs_by_status("discovered", limit=100)
        evaluated_count = 0

        for row in unscored:
            if not row["filter_passed"]:
                continue

            lead = JobLead(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                job_type=row["job_type"],
                platform=row["platform"],
                budget=row["budget"],
                hourly_rate_min=row["hourly_rate_min"],
                hourly_rate_max=row["hourly_rate_max"],
                client_payment_verified=bool(row["client_payment_verified"]),
                client_rating=row["client_rating"],
                client_hire_rate=row["client_hire_rate"],
                proposals_count=row["proposals_count"],
                url=row["url"]
            )

            result = self.score_job(lead)
            db.update_job_status(
                job_id=row["id"],
                status="evaluated",
                roi_score=result.roi_score,
                estimated_hours=result.estimated_hours,
                estimated_token_cost=result.estimated_token_cost
            )
            evaluated_count += 1

            if result.is_urgent and self.on_urgent_lead:
                try:
                    self.on_urgent_lead(lead, result)
                except Exception:
                    pass

        return evaluated_count
