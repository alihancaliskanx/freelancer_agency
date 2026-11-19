"""Oracle Cloud (OCI) Always Free Keep-Alive Watchdog."""
import os
import time
from typing import Dict, Any
from src.db.manager import DatabaseManager


class OciKeepAliveWatchdog:
    """Maintains periodic heartbeat and database vacuuming to prevent OCI idle reclamation."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def run_maintenance_cycle(self) -> Dict[str, Any]:
        """
        Executes WAL checkpoint, refreshes daily metrics timestamp,
        and logs active system state.
        """
        start_time = time.time()

        self.db.maintenance()
        self.db.record_metric_heartbeat()
        metrics = self.db.get_latest_metrics()
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "status": "active",
            "duration_ms": duration_ms,
            "metrics": metrics
        }
