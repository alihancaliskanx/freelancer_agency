"""Manages Cloudflare Quick Tunnel for Telegram Mini App HTTPS endpoints."""
import os
import re
import shutil
import subprocess
import threading
from typing import Optional, Callable
from src.db.manager import DatabaseManager


class CloudflareTunnelManager:
    def __init__(self, db: DatabaseManager, local_port: int = 8080, on_url_ready: Optional[Callable[[str], None]] = None):
        self.db = db
        self.local_port = local_port
        self.on_url_ready = on_url_ready
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _find_binary(self) -> Optional[str]:
        candidates = [
            os.path.expanduser("~/freelancer_agency/bin/cloudflared"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "cloudflared")),
            shutil.which("cloudflared")
        ]
        for c in candidates:
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                return c
        return None

    def start(self) -> Optional[str]:
        # If static URL is explicitly configured via environment, skip quick tunnel
        static_url = os.environ.get("TELEGRAM_WEB_APP_URL")
        if static_url:
            self.public_url = static_url.strip()
            self.db.set_setting("web_app_url", self.public_url)
            print(f"[CloudflareTunnel] Using static configured URL: {self.public_url}")
            if self.on_url_ready:
                self.on_url_ready(self.public_url)
            return self.public_url

        binary = self._find_binary()
        if not binary:
            print("[CloudflareTunnel] cloudflared binary not found; quick tunnel disabled.")
            return None

        cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{self.local_port}"]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        except Exception as e:
            print(f"[CloudflareTunnel] Failed to start cloudflared: {e}")
            return None

        self._thread = threading.Thread(target=self._monitor_output, daemon=True, name="CloudflareTunnelMonitor")
        self._thread.start()
        return None

    def _monitor_output(self):
        if not self.process or not self.process.stderr:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        for line in self.process.stderr:
            if self._stop_event.is_set():
                break
            match = url_pattern.search(line)
            if match and not self.public_url:
                self.public_url = match.group(0)
                self.db.set_setting("web_app_url", self.public_url)
                print(f"[CloudflareTunnel] Live Mini App URL established: {self.public_url}")
                if self.on_url_ready:
                    self.on_url_ready(self.public_url)

    def stop(self):
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        print("[CloudflareTunnel] Tunnel terminated.")
