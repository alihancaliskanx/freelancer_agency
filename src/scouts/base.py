"""Base abstract scout interface for job platforms."""
from abc import ABC, abstractmethod
from typing import List
from src.models import JobLead


class BaseScout(ABC):
    """Abstract scout interface."""

    @abstractmethod
    def fetch_leads(self) -> List[JobLead]:
        """Fetches raw leads from the platform and transforms them into JobLead models."""
        pass
