"""Scout coordinator module that pipes incoming leads through filters into SQLite."""
from typing import List, Dict, Any, Optional
from src.models import JobLead
from src.filters.engine import DeterministicFilterEngine
from src.db.manager import DatabaseManager
from src.scouts.base import BaseScout


class ScoutCoordinator:
    """Coordinates multi-platform scouts, runs 0-token filters, and persists to database."""

    def __init__(
        self,
        scouts: List[BaseScout],
        filter_engine: DeterministicFilterEngine,
        db_manager: DatabaseManager
    ):
        self.scouts = scouts
        self.filter_engine = filter_engine
        self.db = db_manager

    def run_scan(self) -> Dict[str, Any]:
        """
        Runs one scanning cycle across all configured platform scouts.
        Returns aggregated summary statistics.
        """
        total_scanned = 0
        new_inserted = 0
        passed_filters = 0
        duplicates = 0

        for scout in self.scouts:
            try:
                leads = scout.fetch_leads()
            except Exception:
                leads = []

            for lead in leads:
                total_scanned += 1
                decision = self.filter_engine.evaluate(lead)
                if decision.passed:
                    passed_filters += 1

                inserted, _ = self.db.insert_job(lead, decision)
                if inserted:
                    new_inserted += 1
                else:
                    duplicates += 1

        self.db.record_metric_heartbeat(
            jobs_scanned_increment=total_scanned,
            passed_filter_increment=passed_filters
        )

        return {
            "total_scanned": total_scanned,
            "new_inserted": new_inserted,
            "passed_filters": passed_filters,
            "duplicates": duplicates
        }
