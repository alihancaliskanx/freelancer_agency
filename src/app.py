"""Production agency runner: Coordinates periodic scans, scoring, OCI watchdog, and live Telegram bot."""
import asyncio
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

from src.db.manager import DatabaseManager
from src.filters.engine import DeterministicFilterEngine, FilterConfig
from src.scouts.upwork_rss import UpworkRssScout
from src.scouts.freelancer_api import FreelancerApiScout
from src.scouts.coordinator import ScoutCoordinator
from src.scoring.engine import RoiScoringEngine, ScoringConfig
from src.notifications.telegram import TelegramNotifier
from src.watchers.status_watcher import JobStatusWatcher
from src.watchers.keep_alive import OciKeepAliveWatchdog
from src.ceo.orchestrator import CeoOrchestrator
from src.ceo.mcp_server import McpServer
from src.web.server import DashboardServer
from src.web.tunnel import CloudflareTunnelManager


def load_env(env_path: Optional[str] = None):
    """Loads environment variables from .env.local, .env, or specified path without external deps."""
    candidates = [env_path, ".env.local", ".env"]
    for c in candidates:
        if c and os.path.exists(c):
            with open(c, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v
            break


class AgencyApplication:
    """Integrated runtime orchestrator for Freelancer Agency."""

    def __init__(self, db_path: str = "agency.db"):
        load_env()
        self.db = DatabaseManager(db_path)
        self.db.init_db()

        # 1. Notifications
        self.notifier = TelegramNotifier()

        # 2. Filters & Scoring
        filter_config = FilterConfig(
            min_fixed_budget=float(os.environ.get("MIN_FIXED_BUDGET", "100")),
            min_hourly_rate=float(os.environ.get("MIN_HOURLY_RATE", "30")),
            banned_keywords=["WordPress", "Shopify", "PHP 5", "Magento"]
        )
        self.filter_engine = DeterministicFilterEngine(filter_config)

        def on_urgent_lead_hook(job, result):
            if self.notifier.is_configured:
                lang = self.db.get_setting("language", "tr")
                self.notifier.send_urgent_alert(job, result.roi_score, result.estimated_hours, lang=lang)

        self.scoring_engine = RoiScoringEngine(
            config=ScoringConfig(
                target_hourly_rate=float(os.environ.get("TARGET_HOURLY_RATE", "50")),
                urgent_roi_threshold=float(os.environ.get("URGENT_ROI_THRESHOLD", "7.0")),
                urgent_max_proposals=int(os.environ.get("URGENT_MAX_PROPOSALS", "15"))
            ),
            on_urgent_lead=on_urgent_lead_hook
        )

        # 3. Scouts
        upwork_urls = [
            u.strip() for u in os.environ.get("UPWORK_RSS_URLS", "").split(";") if u.strip()
        ]
        scouts = [
            UpworkRssScout(upwork_urls),
            FreelancerApiScout()
        ]
        self.coordinator = ScoutCoordinator(scouts, self.filter_engine, self.db)

        # 4. Watchers
        self.status_watcher = JobStatusWatcher(self.db)
        self.watchdog = OciKeepAliveWatchdog(self.db)

        # 5. CEO & MCP
        self.ceo = CeoOrchestrator(self.db, self.coordinator, self.notifier)
        self.mcp = McpServer(self.ceo)

        # 6. Web Dashboard & Cloudflare Tunnel
        web_port = int(os.environ.get("WEB_APP_PORT", "8080"))
        self.dashboard_server = DashboardServer(self.ceo, self.db, port=web_port)

        def on_tunnel_url_ready(url: str):
            curr_lang = self.db.get_setting("language", "tr")
            self.notifier.set_chat_menu_button(web_app_url=url, lang=curr_lang)

        self.tunnel_manager = CloudflareTunnelManager(self.db, local_port=web_port, on_url_ready=on_tunnel_url_ready)

    def scan_and_score(self) -> Dict[str, Any]:
        """Runs single scan cycle and scores discovered leads."""
        scan_stats = self.coordinator.run_scan()
        scored_count = self.scoring_engine.evaluate_pending_jobs(self.db)
        scan_stats["evaluated_count"] = scored_count
        return scan_stats

    async def telegram_polling_loop(self):
        """Asynchronous long-polling worker for Telegram interactions."""
        if not self.notifier.is_configured:
            print("[Telegram] Not configured (TELEGRAM_BOT_TOKEN missing). Polling disabled.")
            return

        bot_token = self.notifier.bot_token
        last_update_id = 0
        print("[Telegram] Polling listener active.")

        while True:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={last_update_id + 1}&timeout=30"
            try:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, self._http_get_json, url)
                if data and data.get("ok"):
                    for update in data.get("result", []):
                        last_update_id = max(last_update_id, update.get("update_id", 0))

                        # Message handling
                        if "message" in update and "text" in update["message"]:
                            chat_id = update["message"]["chat"]["id"]
                            user_text = update["message"]["text"]
                            reply = self.ceo.handle_message(user_text)
                            if isinstance(reply, tuple):
                                text_msg, markup = reply
                                self._send_telegram(bot_token, chat_id, text_msg, reply_markup=markup)
                            else:
                                curr_lang = self.db.get_setting("language", "tr")
                                web_url = self.db.get_setting("web_app_url") or os.environ.get("TELEGRAM_WEB_APP_URL")
                                reply_markup = self.notifier.build_main_reply_keyboard(lang=curr_lang, web_app_url=web_url)
                                self._send_telegram(bot_token, chat_id, reply, reply_markup=reply_markup)

                        # Callback button handling
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb.get("id")
                            cb_data = cb.get("data", "")
                            msg_obj = cb.get("message", {})
                            chat_id = msg_obj.get("chat", {}).get("id")
                            message_id = msg_obj.get("message_id")

                            reply = self.ceo.handle_callback(cb_data)
                            self._answer_callback(bot_token, cb_id)
                            if chat_id:
                                if isinstance(reply, tuple):
                                    text_msg, markup = reply
                                    if message_id and cb_data.startswith("page:"):
                                        self._edit_telegram_message(bot_token, chat_id, message_id, text_msg, reply_markup=markup)
                                    else:
                                        self._send_telegram(bot_token, chat_id, text_msg, reply_markup=markup)
                                else:
                                    self._send_telegram(bot_token, chat_id, reply)

            except Exception:
                await asyncio.sleep(5)
                continue

            await asyncio.sleep(1)

    def _http_get_json(self, url: str) -> Optional[dict]:
        try:
            with urllib.request.urlopen(url, timeout=35) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _send_telegram(self, token: str, chat_id: Any, text: str, reply_markup: Optional[dict] = None):
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload_data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "link_preview_options": {"is_disabled": True}
        }
        if reply_markup:
            payload_data["reply_markup"] = reply_markup

        payload = json.dumps(payload_data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except urllib.error.HTTPError as e:
            if e.code == 400:
                try:
                    payload_data.pop("parse_mode", None)
                    payload_data["text"] = text.replace("*", "")
                    fallback_data = json.dumps(payload_data).encode("utf-8")
                    fb_req = urllib.request.Request(url, data=fallback_data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(fb_req, timeout=10):
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    def _edit_telegram_message(self, token: str, chat_id: Any, message_id: Any, text: str, reply_markup: Optional[dict] = None) -> bool:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload_data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "link_preview_options": {"is_disabled": True}
        }
        if reply_markup:
            payload_data["reply_markup"] = reply_markup

        payload = json.dumps(payload_data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 400:
                try:
                    payload_data.pop("parse_mode", None)
                    payload_data["text"] = text.replace("*", "")
                    fallback_data = json.dumps(payload_data).encode("utf-8")
                    fb_req = urllib.request.Request(url, data=fallback_data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(fb_req, timeout=10):
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _answer_callback(self, token: str, cb_id: str):
        url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
        payload = json.dumps({"callback_query_id": cb_id}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass

    async def periodic_scout_loop(self, interval_seconds: int = 3600):
        """Runs periodic job search and evaluation."""
        while True:
            try:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, self.scan_and_score)
                print(f"[Scout] Scan cycle completed: {stats}")
            except Exception as e:
                print(f"[Scout] Error during scan cycle: {e}")
            await asyncio.sleep(interval_seconds)

    async def periodic_watcher_loop(self, interval_seconds: int = 3600):
        """Runs hourly status pruning."""
        while True:
            try:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, self.status_watcher.prune_stale_jobs)
                print(f"[Watcher] Job status check: {res}")
            except Exception as e:
                print(f"[Watcher] Error: {e}")
            await asyncio.sleep(interval_seconds)

    async def oci_keepalive_loop(self, interval_seconds: int = 14400):
        """Runs 4-hour OCI keep-alive maintenance."""
        while True:
            try:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, self.watchdog.run_maintenance_cycle)
                print(f"[OCI KeepAlive] Heartbeat and vacuum cycle completed in {res['duration_ms']}ms")
            except Exception as e:
                print(f"[OCI KeepAlive] Error: {e}")
            await asyncio.sleep(interval_seconds)

    async def run_server(self):
        """Runs all concurrent background tasks."""
        print("🚀 Freelancer Agency System is starting up...")
        curr_lang = self.db.get_setting("language", "tr")
        self.notifier.set_bot_commands()
        web_url = self.db.get_setting("web_app_url") or os.environ.get("TELEGRAM_WEB_APP_URL")
        if web_url:
            self.notifier.set_chat_menu_button(web_app_url=web_url, lang=curr_lang)

        self.dashboard_server.start()
        self.tunnel_manager.start()
        try:
            await asyncio.gather(
                self.telegram_polling_loop(),
                self.periodic_scout_loop(interval_seconds=3600),
                self.periodic_watcher_loop(interval_seconds=3600),
                self.oci_keepalive_loop(interval_seconds=14400)
            )
        finally:
            self.tunnel_manager.stop()
            self.dashboard_server.stop()

    def run_mcp_stdio(self):
        """Runs STDIO JSON-RPC server for Model Context Protocol."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.mcp.handle_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()
