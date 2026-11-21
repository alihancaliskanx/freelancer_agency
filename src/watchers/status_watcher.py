"""Continuous zero-token job availability watcher, live proposal auditor, and stale job pruner."""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, Callable, Tuple, Dict, Any, List

from src.db.manager import DatabaseManager


class JobStatusWatcher:
    """Verifies whether discovered/evaluated jobs are still open and active on platforms,
    and runs continuous audits refreshing proposal counts, recalculating ROI, and pruning closed jobs."""

    CLOSED_PATTERNS = [
        re.compile(r"\b(job\s+is\s+no\s+longer\s+available|this\s+job\s+has\s+expired)\b", re.I),
        re.compile(r"\b(job\s+closed|project\s+is\s+closed|hired\s+freelancer)\b", re.I),
        re.compile(r"\b(this\s+posting\s+has\s+been\s+removed)\b", re.I),
    ]

    def __init__(
        self,
        db: DatabaseManager,
        http_checker: Optional[Callable[[str], Tuple[int, str]]] = None,
        freelancer_fetcher: Optional[Callable[[List[str]], Dict[str, Dict[str, Any]]]] = None,
        scoring_engine: Optional[Any] = None
    ):
        self.db = db
        self.http_checker = http_checker or self._default_http_checker
        self.freelancer_fetcher = freelancer_fetcher or self._default_freelancer_fetcher
        self.scoring_engine = scoring_engine

    def _default_http_checker(self, url: str) -> Tuple[int, str]:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read(8192).decode("utf-8", errors="replace")
                return resp.status, content
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception:
            return 500, ""

    def _default_freelancer_fetcher(self, project_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch queries Freelancer REST API for project active statuses and live proposal counts."""
        if not project_ids:
            return {}

        params = "&".join(f"projects[]={pid}" for pid in project_ids)
        url = f"https://www.freelancer.com/api/projects/0.1/projects/?compact=true&{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "FreelancerAgency/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                projects = data.get("result", {}).get("projects", [])
                result = {}
                for p in projects:
                    pid_str = str(p.get("id"))
                    result[pid_str] = {
                        "status": p.get("status"),
                        "bid_count": p.get("bid_stats", {}).get("bid_count", 0)
                    }
                return result
        except Exception:
            return {}

    def check_job_alive(self, url: str) -> Tuple[bool, str]:
        if not url:
            return False, "missing_url"

        status_code, content = self.http_checker(url)

        if status_code in (404, 410):
            return False, f"http_{status_code}"

        for pattern in self.CLOSED_PATTERNS:
            if pattern.search(content):
                return False, "closed_in_content"

        return True, "active"

    def audit_batch(
        self,
        scoring_engine: Optional[Any] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Continuously audits active leads:
        - Checks live status on Freelancer & Upwork
        - Updates proposals_count in real-time
        - Recalculates dynamic ROI score if competition changes
        - Marks expired / deleted jobs as 'closed'
        """
        jobs = self.db.get_active_jobs_for_audit(limit=limit)
        if not jobs:
            return {"audited": 0, "proposals_updated": 0, "closed": 0, "active": 0}

        proposals_updated = 0
        closed_count = 0
        active_count = 0
        engine = scoring_engine or self.scoring_engine

        # Group by platform
        fl_jobs = []
        other_jobs = []
        for j in jobs:
            if j.get("platform") == "freelancer":
                fl_jobs.append(j)
            else:
                other_jobs.append(j)

        # 1. Audit Freelancer jobs in single batch API call
        if fl_jobs:
            pid_to_job = {}
            for j in fl_jobs:
                pid = j.get("external_id") or (j["id"].split(":", 1)[-1] if ":" in j["id"] else j["id"])
                pid_to_job[str(pid)] = j

            fetched_statuses = self.freelancer_fetcher(list(pid_to_job.keys()))

            for pid, j in pid_to_job.items():
                if pid in fetched_statuses:
                    info = fetched_statuses[pid]
                    fl_status = info.get("status")
                    bid_count = info.get("bid_count")

                    if fl_status != "active":
                        self.db.update_job_status(j["id"], status="closed")
                        closed_count += 1
                    else:
                        active_count += 1
                        curr_proposals = j.get("proposals_count") or 0
                        if bid_count is not None and bid_count != curr_proposals:
                            new_roi = None
                            new_hours = None
                            if engine:
                                lead = self.db.row_to_job_lead(j)
                                lead.proposals_count = bid_count
                                res = engine.score_job(lead)
                                new_roi = res.roi_score
                                new_hours = res.estimated_hours

                            self.db.update_job_proposals_and_score(
                                job_id=j["id"],
                                proposals_count=bid_count,
                                roi_score=new_roi,
                                estimated_hours=new_hours
                            )
                            proposals_updated += 1
                        else:
                            # Touch updated_at so queue moves forward
                            self.db.update_job_proposals_and_score(
                                job_id=j["id"],
                                proposals_count=curr_proposals
                            )
                else:
                    # Not returned by API (e.g. project deleted or removed)
                    self.db.update_job_status(j["id"], status="closed")
                    closed_count += 1

        # 2. Audit Other jobs (Upwork / RSS) via HTTP check
        for j in other_jobs:
            is_alive, reason = self.check_job_alive(j["url"])
            if not is_alive:
                self.db.update_job_status(j["id"], status="closed")
                closed_count += 1
            else:
                active_count += 1
                curr_proposals = j.get("proposals_count") or 0
                self.db.update_job_proposals_and_score(
                    job_id=j["id"],
                    proposals_count=curr_proposals
                )

        stats = {
            "audited": len(jobs),
            "proposals_updated": proposals_updated,
            "closed": closed_count,
            "active": active_count
        }

        # Persist audit health timestamp
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.db.set_setting("last_audit_time", now_str)
        self.db.set_setting("last_audit_stats", json.dumps(stats))

        return stats

    def prune_stale_jobs(
        self,
        statuses: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, int]:
        target_statuses = statuses or ["evaluated", "discovered"]
        checked = 0
        closed = 0
        alive = 0

        for st in target_statuses:
            jobs = self.db.get_jobs_by_status(st, limit=limit)
            for j in jobs:
                checked += 1
                is_alive, reason = self.check_job_alive(j["url"])
                if not is_alive:
                    self.db.update_job_status(j["id"], status="closed")
                    closed += 1
                else:
                    alive += 1

        return {"checked": checked, "closed": closed, "alive": alive}
