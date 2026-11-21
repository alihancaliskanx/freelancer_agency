"""Database management module for Freelancer Agency system."""
import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Tuple
from src.db.schema import SCHEMA_SQL
from src.models import JobLead, FilterDecision


def compute_fingerprint(title: str, description: str) -> str:
    """Computes a normalized SHA-256 fingerprint for deduplication."""
    clean_title = re.sub(r"\W+", "", title.lower())
    clean_desc = re.sub(r"\W+", "", description[:500].lower())
    raw_key = f"{clean_title}:{clean_desc}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class DatabaseManager:
    """Manages SQLite connections, schema initialization, and transactional operations."""

    def __init__(self, db_path: str = "agency.db"):
        self.db_path = db_path

    @contextmanager
    def get_connection(self):
        """Context manager that guarantees transaction commit and connection closure."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        """Initializes tables and WAL mode."""
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            # Automatic schema migration for existing databases
            existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            for col_name, col_def in [
                ("currency", "TEXT DEFAULT 'USD'"),
                ("currency_symbol", "TEXT DEFAULT '$'"),
                ("original_budget", "REAL"),
                ("original_hourly_min", "REAL"),
                ("original_hourly_max", "REAL"),
            ]:
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def};")

    def maintenance(self):
        """Runs checkpoint on WAL and compacts database to prevent disk bloat."""
        with self.get_connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def insert_job(
        self,
        job: JobLead,
        filter_decision: Optional[FilterDecision] = None
    ) -> Tuple[bool, str]:
        """
        Inserts a new job lead.
        Returns:
            (True, job.id) if inserted successfully.
            (False, existing_id) if duplicate detected by fingerprint or ID.
        """
        fingerprint = compute_fingerprint(job.title, job.description)

        filter_passed = 1 if (filter_decision and filter_decision.passed) else 0
        filter_reason = filter_decision.reason if filter_decision else None
        status = "filtered_out" if (filter_decision and not filter_decision.passed) else "discovered"

        sql = """
        INSERT INTO jobs (
            id, fingerprint, platform, external_id, title, description,
            job_type, budget, hourly_rate_min, hourly_rate_max,
            currency, currency_symbol, original_budget, original_hourly_min, original_hourly_max,
            client_payment_verified, client_rating, client_hire_rate,
            proposals_count, url, manual_time_allowed, status,
            filter_passed, filter_reason
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?
        );
        """
        params = (
            job.id,
            fingerprint,
            job.platform,
            job.id.split(":", 1)[-1] if ":" in job.id else job.id,
            job.title,
            job.description,
            job.job_type,
            job.budget,
            job.hourly_rate_min,
            job.hourly_rate_max,
            job.currency or "USD",
            job.currency_symbol or "$",
            job.original_budget if job.original_budget is not None else job.budget,
            job.original_hourly_min if job.original_hourly_min is not None else job.hourly_rate_min,
            job.original_hourly_max if job.original_hourly_max is not None else job.hourly_rate_max,
            1 if job.client_payment_verified else 0,
            job.client_rating,
            job.client_hire_rate,
            job.proposals_count,
            job.url,
            1 if job.manual_time_allowed is True else (0 if job.manual_time_allowed is False else None),
            status,
            filter_passed,
            filter_reason,
        )

        with self.get_connection() as conn:
            try:
                conn.execute(sql, params)
                return True, job.id
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id, description FROM jobs WHERE id = ? OR fingerprint = ?;",
                    (job.id, fingerprint)
                ).fetchone()
                existing_id = row["id"] if row else job.id
                if row and job.description and len(job.description) > len(row["description"] or ""):
                    conn.execute(
                        "UPDATE jobs SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                        (job.description, existing_id)
                    )
                return False, existing_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,)).fetchone()
            if not row and ":" not in job_id:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE id = ? OR id = ? OR external_id = ?;",
                    (f"freelancer:{job_id}", f"upwork:{job_id}", job_id)
                ).fetchone()
            return dict(row) if row else None

    def get_jobs_by_status(self, status: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?;",
                (status, limit)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_hot_leads(self, min_roi: float = 0.0, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM jobs
                WHERE filter_passed = 1 AND roi_score >= ? AND status NOT IN ('filtered_out', 'closed', 'rejected')
                ORDER BY roi_score DESC, created_at DESC
                LIMIT ?;
                """,
                (min_roi, limit)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_all_qualified_jobs(self, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        with self.get_connection() as conn:
            total = conn.execute(
                "SELECT count(*) FROM jobs WHERE filter_passed = 1 AND status NOT IN ('filtered_out', 'closed', 'rejected');"
            ).fetchone()[0]
            cursor = conn.execute(
                """
                SELECT * FROM jobs
                WHERE filter_passed = 1 AND status NOT IN ('filtered_out', 'closed', 'rejected')
                ORDER BY roi_score DESC, created_at DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset)
            )
            return [dict(r) for r in cursor.fetchall()], total

    def update_job_status(
        self,
        job_id: str,
        status: str,
        roi_score: Optional[float] = None,
        estimated_hours: Optional[float] = None,
        estimated_token_cost: Optional[float] = None
    ) -> bool:
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [status]

        if roi_score is not None:
            updates.append("roi_score = ?")
            params.append(roi_score)
        if estimated_hours is not None:
            updates.append("estimated_hours = ?")
            params.append(estimated_hours)
        if estimated_token_cost is not None:
            updates.append("estimated_token_cost = ?")
            params.append(estimated_token_cost)

        params.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?;"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            return cursor.rowcount > 0

    def create_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: float,
        estimated_timeline: str = "",
        token_cost_usd: float = 0.0
    ) -> int:
        sql = """
        INSERT INTO proposals (job_id, cover_letter, bid_amount, estimated_timeline, token_cost_usd)
        VALUES (?, ?, ?, ?, ?);
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (job_id, cover_letter, bid_amount, estimated_timeline, token_cost_usd))
            return cursor.lastrowid

    def get_proposals_for_job(self, job_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM proposals WHERE job_id = ? ORDER BY created_at DESC;", (job_id,))
            return [dict(r) for r in cursor.fetchall()]

    def record_metric_heartbeat(
        self,
        jobs_scanned_increment: int = 0,
        passed_filter_increment: int = 0,
        proposals_increment: int = 0,
        token_cost_increment: float = 0.0,
        active_jobs_count: Optional[int] = None
    ):
        """Records daily metrics and updates OCI keep-alive heartbeat timestamp."""
        today = str(date.today())
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO agency_metrics (metric_date, total_jobs_scanned, jobs_passed_filter, proposals_generated, total_token_cost_usd, active_jobs_count, last_heartbeat)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, 0), CURRENT_TIMESTAMP)
                ON CONFLICT(metric_date) DO UPDATE SET
                    total_jobs_scanned = total_jobs_scanned + excluded.total_jobs_scanned,
                    jobs_passed_filter = jobs_passed_filter + excluded.jobs_passed_filter,
                    proposals_generated = proposals_generated + excluded.proposals_generated,
                    total_token_cost_usd = total_token_cost_usd + excluded.total_token_cost_usd,
                    active_jobs_count = CASE WHEN ? IS NOT NULL THEN ? ELSE active_jobs_count END,
                    last_heartbeat = CURRENT_TIMESTAMP;
                """,
                (
                    today,
                    jobs_scanned_increment,
                    passed_filter_increment,
                    proposals_increment,
                    token_cost_increment,
                    active_jobs_count,
                    active_jobs_count,
                    active_jobs_count,
                )
            )

    def get_latest_metrics(self) -> Optional[Dict[str, Any]]:
        today = str(date.today())
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM agency_metrics WHERE metric_date = ?;", (today,)).fetchone()
            return dict(row) if row else None

    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_connection() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = ?;", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP;
                """,
                (key, value)
            )
