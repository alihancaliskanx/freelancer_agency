# Freelancer Agency

Autonomous freelance agency daemon engineered for **Oracle Cloud Infrastructure (OCI) Always Free** compute instances. Discovers, filters with zero token cost, scores ROI, dispatches proactive Telegram notifications with inline action buttons, and exposes an executive MCP (Model Context Protocol) server over SSH.

---

## Architecture & Zero-Token Pipeline

```
Raw Opportunities (Upwork RSS + Freelancer REST API)
                      │
                      ▼
       [Deterministic 0-Token Filter]
       ├── Tracker Guard (Hard Drop on mandatory desktop time tracking)
       ├── Anti-AI Policy (Hard Drop on "no AI" bans; permits AI development)
       ├── Budget & Rate Gates (Min Fixed $100, Min Hourly $30/hr)
       ├── Scam & Off-Platform Guard (Telegram/WhatsApp payment fraud)
       └── Ghost Job Rule (Age > 7 days or zero client history)
                      │ (Passes ~10% high-quality leads)
                      ▼
           [Dual-Track ROI Scoring]
       ├── Hourly Fit: Rate vs Target ($50/hr default)
       ├── Fixed-Price Fit: Budget vs Complexity Duration (Hours)
       └── LLM Token Cost Scaling ($0.05 - $0.20 per proposal)
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
 [Proactive Telegram Alert]  [SQLite WAL Database]
 ├── Minimalist Text         ├── SHA-256 Fingerprint Deduplication
 └── [Teklif Hazırla] /      ├── Proposal Tracking
     [Reddet] Inline Buttons └── OCI Metrics Heartbeat
```

---

## Features

- **0-Token Deterministic Filter:** Evaluates 100% of raw listings via regex and metadata heuristics before any LLM invocation, saving significant token costs.
- **Tracker Guard:** Drops jobs mandating desktop tracking software while preserving jobs where the deliverable is building a time tracking tool.
- **Minimalist Telegram CEO:** Real-time push notifications for hot leads with instant callback buttons (`[Teklif Hazırla]`, `[Reddet]`) and commands (`/status`, `/leads`, `/help`).
- **Remote MCP Server:** Exposes tools (`list_hot_leads`, `draft_proposal`, `reject_job`, `get_pipeline_status`) over STDIO JSON-RPC for external AI models connected via SSH.
- **Zero Third-Party Runtime Dependencies:** 100% Python Standard Library. Zero pip install requirements for running production daemon.
- **OCI Keep-Alive Watchdog:** Periodic WAL checkpoints, VACUUM maintenance, and dummy read cycles preventing OCI free tier idle reclamation.

---

## Server Deployment (Oracle Cloud Always Free VM)

### 1. Prerequisites
- Ubuntu 22.04 / 24.04 LTS (AMD64 or ARM64 Ampere A1)
- Python 3.10+ installed (`python3 --version`)
- Telegram Bot Token (from `@BotFather`) and Chat ID (from `@userinfobot`)

### 2. Quick Setup
Clone repository and run the setup script:

```bash
git clone https://github.com/alihancaliskanx/freelancer_agency.git
cd freelancer_agency
bash scripts/setup_server.sh
```

### 3. Configure Credentials
Edit `.env.local`:

```bash
nano .env.local
```

Set your tokens:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
# Optional Upwork custom search RSS feeds (semicolon separated):
UPWORK_RSS_URLS=https://www.upwork.com/ab/feed/jobs/rss?q=python&sort=recency
```

### 4. Run Diagnostics & Health Check
Verify your configuration, SQLite database, and network reachability:

```bash
python3 scripts/healthcheck.py
```

### 5. Start Daemon via Systemd
Install and activate the systemd service:

```bash
sudo cp agency.service /etc/systemd/system/agency.service
sudo systemctl daemon-reload
sudo systemctl enable --now agency.service
sudo systemctl status agency.service
```

Stream live logs:
```bash
journalctl -u agency.service -f
```

---

## Remote MCP Over SSH Configuration

To control your agency via Anthropic Claude Desktop or Antigravity IDE running on your local workstation, add the following to your local `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "freelancer-agency": {
      "command": "ssh",
      "args": [
        "-i", "/path/to/oci_private_key.key",
        "ubuntu@<OCI_VM_PUBLIC_IP>",
        "python3 /home/ubuntu/freelancer_agency/run_agency.py --mcp"
      ]
    }
  }
}
```

---

## CLI Usage

Run a single scan & scoring cycle without running the background daemon:
```bash
python3 run_agency.py --scan-once
```

Start the interactive STDIO MCP server directly:
```bash
python3 run_agency.py --mcp
```

Run test suite (48 tests):
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```
