"""Hourly zero-token job availability watcher and stale job pruner."""
import re
import urllib.request
import urllib.error
from typing import Optional, Callable, Tuple, Dict, Any, List

from src.db.manager import DatabaseManager


class JobStatusWatcher:
    """Verifies whether discovered/evaluated jobs are still open and active on platforms."""

    CLOSED_PATTERNS = [
        re.compile(r"\b(job\s+is\s+no\s+longer\s+available|this\s+job\s+has\s+expired)\b", re.I),
        re.compile(r"\b(job\s+closed|project\s+is\s+closed|hired\s+freelancer)\b", re.I),
        re.compile(r"\b(this\s+posting\s+has\s+been\s+removed)\b", re.I),
    ]

    def __init__(
        self,
        db: DatabaseManager,
        http_checker: Optional[Callable[[str], Tuple[int, str]]] = None
    ):
        self.db = db
        self.http_checker = http_checker or self._default_http_checker

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
