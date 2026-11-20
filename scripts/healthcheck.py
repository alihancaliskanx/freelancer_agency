#!/usr/bin/env python3
"""
Server Health Check and Diagnostic Tool for Freelancer Agency.
Validates Python runtime, database integrity, network endpoints, and daemon configuration.
Zero external dependencies (Standard Library only).
"""

import sys
import os
import json
import sqlite3
import urllib.request
import urllib.error
import argparse
from pathlib import Path

# Ensure project root is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def find_env_file(candidate_name: str) -> str:
    """Finds env file either by absolute path, relative to cwd, or relative to project root."""
    if os.path.isabs(candidate_name) and os.path.isfile(candidate_name):
        return candidate_name
    cwd_path = os.path.join(os.getcwd(), candidate_name)
    if os.path.isfile(cwd_path):
        return cwd_path
    root_path = os.path.join(PROJECT_ROOT, candidate_name)
    if os.path.isfile(root_path):
        return root_path
    return ""


def load_env_file(path: str) -> None:
    """Load key-value pairs from .env or .env.local into os.environ if not already set."""
    if not path or not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v


def check_python_version() -> bool:
    v = sys.version_info
    print(f"[*] Python Version: {v.major}.{v.minor}.{v.micro}", end=" ")
    if v.major >= 3 and v.minor >= 10:
        print("[OK]")
        return True
    print("[FAIL] (Requires >= 3.10)")
    return False


def check_database(db_path: str) -> bool:
    print(f"[*] Database Path ({db_path}):", end=" ")
    try:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        journal_mode = cursor.fetchone()[0]
        cursor.execute("SELECT 1;")
        res = cursor.fetchone()[0]
        conn.close()

        if res == 1 and journal_mode.upper() == "WAL":
            print(f"[OK] (WAL mode active)")
            return True
        else:
            print(f"[WARN] (journal_mode={journal_mode})")
            return True
    except Exception as e:
        print(f"[FAIL] ({e})")
        return False


def check_telegram_credentials(token: str, chat_id: str, live_check: bool = True) -> bool:
    print(f"[*] Telegram Configuration:", end=" ")
    if not token or not chat_id:
        print("[FAIL] (Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    print("[CONFIGURED]")
    if not live_check:
        return True

    print(f"[*] Telegram Live API Test (getMe):", end=" ")
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FreelancerAgencyHealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                username = data.get("result", {}).get("username", "unknown")
                print(f"[OK] (Connected to @{username})")
                return True
            print(f"[FAIL] ({data.get('description', 'Unknown API error')})")
            return False
    except urllib.error.HTTPError as e:
        print(f"[FAIL] (HTTP {e.code}: {e.reason})")
        return False
    except Exception as e:
        print(f"[FAIL] ({e})")
        return False


def check_network_reachability() -> bool:
    upwork_env_urls = [u.strip() for u in os.environ.get("UPWORK_RSS_URLS", "").split(";") if u.strip()]
    if upwork_env_urls:
        test_upwork_url = upwork_env_urls[0]
        upwork_label = "Upwork Custom RSS"
    else:
        test_upwork_url = "https://www.upwork.com/ab/feed/jobs/rss?q=python&sort=recency"
        upwork_label = "Upwork Public RSS"

    endpoints = [
        (upwork_label, test_upwork_url),
        ("Freelancer API", "https://www.freelancer.com/api/projects/0.1/projects/active?query=python&limit=1"),
    ]

    all_passed = True
    for name, url in endpoints:
        print(f"[*] Network Reachability ({name}):", end=" ")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FreelancerAgency/1.0"})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                code = resp.getcode()
                if 200 <= code < 400:
                    print(f"[OK] (HTTP {code})")
                else:
                    print(f"[WARN] (HTTP {code})")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"[WARN] (HTTP {e.code} Cloudflare/Protected)")
            elif e.code == 410 and not upwork_env_urls:
                print(f"[WARN] (HTTP 410: Public Upwork feed deprecated; configure UPWORK_RSS_URLS in .env.local)")
            else:
                print(f"[FAIL] (HTTP {e.code})")
                all_passed = False
        except Exception as e:
            print(f"[FAIL] ({e})")
            all_passed = False

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Freelancer Agency Diagnostic & Health Check")
    parser.add_argument("--env", default=".env.local", help="Path to environment file (default: .env.local)")
    parser.add_argument("--db", default="data/agency.db", help="Path to SQLite database (default: data/agency.db)")
    parser.add_argument("--offline", action="store_true", help="Skip live network and Telegram API requests")
    args = parser.parse_args()

    # Discover and load env file
    found_env = find_env_file(args.env)
    if not found_env and args.env == ".env.local":
        found_env = find_env_file(".env")
    if found_env:
        load_env_file(found_env)

    print("========================================")
    print("Freelancer Agency Server Health Check")
    print("========================================")

    py_ok = check_python_version()
    db_target = os.environ.get("DB_PATH", args.db)
    if not os.path.isabs(db_target):
        db_target = os.path.join(os.getcwd(), db_target)
    db_ok = check_database(db_target)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    tg_ok = check_telegram_credentials(token, chat_id, live_check=not args.offline)

    net_ok = True
    if not args.offline:
        net_ok = check_network_reachability()

    print("----------------------------------------")
    overall = py_ok and db_ok and tg_ok
    if overall:
        print("[SUCCESS] All core system checks passed.")
        sys.exit(0)
    else:
        print("[WARNING] One or more checks failed. Review errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
