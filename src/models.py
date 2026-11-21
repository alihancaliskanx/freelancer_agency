"""Data models for freelancer job leads and filter evaluation results."""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class JobLead:
    id: str
    title: str
    description: str
    job_type: str  # 'fixed' or 'hourly'
    platform: str  # 'upwork' or 'freelancer'
    budget: Optional[float] = None
    hourly_rate_min: Optional[float] = None
    hourly_rate_max: Optional[float] = None
    currency: str = "USD"
    currency_symbol: str = "$"
    original_budget: Optional[float] = None
    original_hourly_min: Optional[float] = None
    original_hourly_max: Optional[float] = None
    client_payment_verified: bool = False
    client_rating: Optional[float] = None  # 0.0 to 5.0
    client_hire_rate: Optional[float] = None  # 0 to 100 percentage
    proposals_count: int = 0
    url: str = ""
    manual_time_allowed: Optional[bool] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterDecision:
    passed: bool
    reason: str
    rule_name: str
    details: Dict[str, Any] = field(default_factory=dict)
