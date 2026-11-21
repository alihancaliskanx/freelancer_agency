"""HTTP REST API and static dashboard server for Telegram Mini App."""
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional
from urllib.parse import urlparse, parse_qs

from src.ceo.orchestrator import CeoOrchestrator
from src.db.manager import DatabaseManager
from src.notifications.telegram import (
    format_price,
    extract_clean_summary,
    format_duration,
    extract_tech_stack,
    get_agent_recommendations,
)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(BaseHTTPRequestHandler):
    orchestrator: Optional[CeoOrchestrator] = None
    db: Optional[DatabaseManager] = None
    web_dir: str = os.path.dirname(os.path.abspath(__file__))

    def log_message(self, format, *args):
        # Suppress noisy standard server access logs
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # 1. API: Agency Status Overview
        if path == "/api/stats":
            if not self.orchestrator:
                self._send_json(500, {"error": "Orchestrator not initialized"})
                return
            overview = self.orchestrator.get_status_overview()
            curr_lang = self.db.get_setting("language", "tr") if self.db else "tr"
            overview["current_language"] = curr_lang
            self._send_json(200, overview)
            return

        # 2. API: Job Listings
        elif path == "/api/jobs":
            if not self.db or not self.orchestrator:
                self._send_json(500, {"error": "Database not initialized"})
                return

            filter_type = params.get("type", ["all"])[0].lower()
            limit = int(params.get("limit", [50])[0])
            min_roi = float(params.get("min_roi", [0.0])[0])
            lang = params.get("lang", [self.db.get_setting("language", "tr")])[0]

            if filter_type == "hot":
                threshold = max(min_roi, 6.0)
                raw_jobs = self.db.get_hot_leads(min_roi=threshold, limit=limit)
            else:
                raw_jobs, _ = self.db.get_all_qualified_jobs(limit=limit, offset=0)
                if min_roi > 0.0:
                    raw_jobs = [j for j in raw_jobs if (j.get("roi_score") or 0.0) >= min_roi]

            formatted_list = []
            for j in raw_jobs:
                lead = self.orchestrator.get_job_lead_from_row(j)
                desc = j.get("description") or ""
                langs, tools = extract_tech_stack(j.get("title", ""), desc)
                if not langs and not tools:
                    langs, tools = get_agent_recommendations(desc)

                hours = j.get("estimated_hours") or 10.0
                formatted_list.append({
                    "id": j.get("id"),
                    "title": j.get("title"),
                    "platform": j.get("platform", "freelancer"),
                    "job_type": j.get("job_type", "fixed"),
                    "currency": j.get("currency", "USD"),
                    "currency_symbol": j.get("currency_symbol", "$"),
                    "budget": j.get("budget"),
                    "original_budget": j.get("original_budget"),
                    "hourly_rate_min": j.get("hourly_rate_min"),
                    "hourly_rate_max": j.get("hourly_rate_max"),
                    "original_hourly_min": j.get("original_hourly_min"),
                    "original_hourly_max": j.get("original_hourly_max"),
                    "formatted_price": format_price(lead, lang=lang),
                    "roi_score": round(j.get("roi_score") or 0.0, 1),
                    "estimated_hours": hours,
                    "duration_label": format_duration(hours, lang=lang),
                    "clean_summary": extract_clean_summary(desc, max_chars=180),
                    "full_description": desc.strip(),
                    "languages": langs,
                    "tools": tools,
                    "job_type_label": "Sabit Ücret" if j.get("job_type") == "fixed" else "Saatlik Ücret",
                    "tech_stack": sorted(list(set(langs + tools))),
                    "client_rating": j.get("client_rating"),
                    "client_hire_rate": j.get("client_hire_rate"),
                    "client_payment_verified": bool(j.get("client_payment_verified")),
                    "proposals_count": j.get("proposals_count", 0),
                    "url": j.get("url", ""),
                    "status": j.get("status", "evaluated")
                })

            self._send_json(200, {"jobs": formatted_list, "total": len(formatted_list)})
            return

        # 3. API: Settings (Portfolio, Signature, Language)
        elif path == "/api/settings":
            if not self.db:
                self._send_json(500, {"error": "Database not initialized"})
                return
            p_url = self.db.get_setting("portfolio_url") or os.environ.get("AGENCY_PORTFOLIO_URL", "https://github.com/alihancaliskanx")
            s_name = self.db.get_setting("signature_name") or os.environ.get("AGENCY_SIGNATURE_NAME", "Alihan Çalışkan")
            lang = self.db.get_setting("language", "tr")
            self._send_json(200, {
                "portfolio_url": p_url,
                "signature_name": s_name,
                "language": lang
            })
            return

        # 4. Static Web Application (index.html)
        elif path in ("/", "/index.html", "/app"):
            html_file = os.path.join(self.web_dir, "index.html")
            if not os.path.exists(html_file):
                self._send_json(404, {"error": "Dashboard index.html not found"})
                return

            with open(html_file, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            body = {}

        # 1. API: Draft Proposal for a Job
        if path == "/api/draft":
            if not self.orchestrator:
                self._send_json(500, {"error": "Orchestrator not initialized"})
                return

            job_id = body.get("job_id")
            if not job_id:
                self._send_json(400, {"error": "Missing job_id parameter"})
                return

            instructions = body.get("instructions", "")
            result = self.orchestrator.draft_proposal(job_id, custom_instructions=instructions)
            status_code = 200 if result.get("success") else 400
            self._send_json(status_code, result)
            return

        # 2. API: Change System Language
        elif path == "/api/lang":
            if not self.db:
                self._send_json(500, {"error": "Database not initialized"})
                return

            new_lang = body.get("lang")
            if new_lang in ("tr", "en"):
                self.db.set_setting("language", new_lang)
                self._send_json(200, {"success": True, "language": new_lang})
            else:
                self._send_json(400, {"error": "Invalid language, choose 'tr' or 'en'"})
            return

        # 3. API: Update Settings (Portfolio, Signature, Language)
        elif path == "/api/settings":
            if not self.db:
                self._send_json(500, {"error": "Database not initialized"})
                return
            if "portfolio_url" in body:
                self.db.set_setting("portfolio_url", str(body["portfolio_url"]).strip())
            if "signature_name" in body:
                self.db.set_setting("signature_name", str(body["signature_name"]).strip())
            if "language" in body and body["language"] in ("tr", "en"):
                self.db.set_setting("language", body["language"])

            p_url = self.db.get_setting("portfolio_url") or os.environ.get("AGENCY_PORTFOLIO_URL", "https://github.com/alihancaliskanx")
            s_name = self.db.get_setting("signature_name") or os.environ.get("AGENCY_SIGNATURE_NAME", "Alihan Çalışkan")
            lang = self.db.get_setting("language", "tr")
            self._send_json(200, {
                "success": True,
                "settings": {
                    "portfolio_url": p_url,
                    "signature_name": s_name,
                    "language": lang
                }
            })
            return

        self._send_json(404, {"error": "Not Found"})


class DashboardServer:
    """Manages the lifecycle of the interactive HTTP dashboard server."""

    def __init__(self, orchestrator: CeoOrchestrator, db: DatabaseManager, host: str = "0.0.0.0", port: int = 8080):
        self.orchestrator = orchestrator
        self.db = db
        self.host = host
        self.port = port
        self.server: Optional[ThreadedHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        DashboardHandler.orchestrator = self.orchestrator
        DashboardHandler.db = self.db

        self.server = ThreadedHTTPServer((self.host, self.port), DashboardHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="DashboardServerThread")
        self.thread.start()
        print(f"[DashboardServer] Active on http://{self.host}:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        print("[DashboardServer] Stopped.")
