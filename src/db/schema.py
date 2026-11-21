"""SQLite schema definition for the Freelancer Agency system."""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    job_type TEXT NOT NULL,
    budget REAL,
    hourly_rate_min REAL,
    hourly_rate_max REAL,
    currency TEXT DEFAULT 'USD',
    currency_symbol TEXT DEFAULT '$',
    original_budget REAL,
    original_hourly_min REAL,
    original_hourly_max REAL,
    client_payment_verified INTEGER NOT NULL DEFAULT 0,
    client_rating REAL,
    client_hire_rate REAL,
    proposals_count INTEGER DEFAULT 0,
    url TEXT NOT NULL,
    manual_time_allowed INTEGER,
    status TEXT NOT NULL DEFAULT 'discovered',
    filter_passed INTEGER NOT NULL DEFAULT 0,
    filter_reason TEXT,
    roi_score REAL,
    estimated_hours REAL,
    estimated_token_cost REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_filter_passed ON jobs(filter_passed);
CREATE INDEX IF NOT EXISTS idx_jobs_roi_score ON jobs(roi_score DESC);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    cover_letter TEXT NOT NULL,
    bid_amount REAL NOT NULL,
    estimated_timeline TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    token_cost_usd REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_proposals_job_id ON proposals(job_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);

CREATE TABLE IF NOT EXISTS agency_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_date TEXT UNIQUE NOT NULL,
    total_jobs_scanned INTEGER DEFAULT 0,
    jobs_passed_filter INTEGER DEFAULT 0,
    proposals_generated INTEGER DEFAULT 0,
    total_token_cost_usd REAL DEFAULT 0.0,
    active_jobs_count INTEGER DEFAULT 0,
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

"""
