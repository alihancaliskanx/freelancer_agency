"""Telegram notification dispatcher for urgent job leads and agency alerts."""
import json
import math
import os
import re
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any, Tuple

from src.models import JobLead

KNOWN_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "C++", "CPP", "C#", "Rust", "Go", "Golang",
    "Java", "PHP", "Ruby", "Swift", "Kotlin", "Dart", "Solidity", "SQL", "Bash", "Shell", "R"
]

KNOWN_TOOLS = [
    "Docker", "Kubernetes", "FastAPI", "Django", "Flask", "React", "Vue", "Next.js", "Node.js",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Nmap", "Metasploit", "Wireshark",
    "Matplotlib", "Pandas", "NumPy", "Scikit-Learn", "PyTorch", "TensorFlow", "Selenium",
    "Playwright", "BeautifulSoup", "Scrapy", "AWS", "Azure", "GCP", "Linux", "Git", "Celery"
]

DOMAIN_DEFAULTS = {
    "scraping": (["Python"], ["Playwright", "BeautifulSoup", "SQLite"]),
    "automation": (["Python"], ["Selenium", "Cron", "Pandas"]),
    "data": (["Python"], ["Pandas", "Matplotlib", "SQLite"]),
    "web": (["TypeScript", "Python"], ["FastAPI", "React", "PostgreSQL"]),
    "api": (["Python", "Go"], ["FastAPI", "Docker", "PostgreSQL"]),
    "security": (["Python", "Bash"], ["Nmap", "Wireshark", "Metasploit"]),
    "finance": (["Python"], ["Pandas", "NumPy", "ReportLab"]),
    "bot": (["Python"], ["AsyncIO", "Telegram API", "SQLite"]),
}


def extract_clean_summary(description: str, max_chars: int = 240) -> str:
    """Extracts a concise 1-2 sentence overview from job description without noise."""
    if not description:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", description)
    # Unescape common HTML entities
    clean = (
        clean.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    # Normalize whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""

    # Split into sentences based on punctuation
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    selected = []
    total_len = 0

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if total_len + len(s) <= max_chars or not selected:
            selected.append(s)
            total_len += len(s) + 1
            if len(selected) >= 2:
                break
        else:
            break

    result = " ".join(selected)
    if len(result) > max_chars:
        result = result[:max_chars].rstrip() + "..."
    return result


def extract_tech_stack(text: str, skills_list: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """Extracts mentioned languages and tools from text and metadata."""
    found_langs = set()
    found_tools = set()

    combined_text = (text + " " + " ".join(skills_list or [])).lower()

    for lang in KNOWN_LANGUAGES:
        pattern = r"\b" + re.escape(lang.lower()) + r"\b"
        if re.search(pattern, combined_text):
            found_langs.add("C++" if lang.upper() == "CPP" else lang)

    for tool in KNOWN_TOOLS:
        pattern = r"\b" + re.escape(tool.lower()) + r"\b"
        if re.search(pattern, combined_text):
            found_tools.add(tool)

    return sorted(list(found_langs)), sorted(list(found_tools))


def get_agent_recommendations(text: str) -> Tuple[List[str], List[str]]:
    """Suggests modern languages and tools based on job context if unspecified."""
    text_lower = text.lower()
    for domain, (rec_langs, rec_tools) in DOMAIN_DEFAULTS.items():
        if domain in text_lower:
            return rec_langs, rec_tools
    return ["Python"], ["Docker", "SQLite"]


def format_price(job: JobLead, lang: str = "tr") -> str:
    """Formats project price preserving original currency and showing USD equivalence."""
    curr = (job.currency or "USD").upper()
    sym = job.currency_symbol or "$"
    is_usd = (curr == "USD")

    if job.job_type == "fixed":
        orig_b = job.original_budget if job.original_budget is not None else job.budget
        usd_b = job.budget if job.budget is not None else orig_b

        if orig_b is None and usd_b is None:
            return "*Belirtilmedi*" if lang == "tr" else "*Not Specified*"

        if is_usd or orig_b is None:
            return f"{usd_b:,.0f} $"
        else:
            return f"{orig_b:,.0f} {sym} ({curr}) (~{usd_b:,.0f} $)"
    else:
        orig_min = job.original_hourly_min if job.original_hourly_min is not None else job.hourly_rate_min
        orig_max = job.original_hourly_max if job.original_hourly_max is not None else job.hourly_rate_max
        usd_min = job.hourly_rate_min
        usd_max = job.hourly_rate_max

        if is_usd or orig_min is None or orig_max is None:
            h_min = f"{usd_min:.0f}" if usd_min is not None else "0"
            h_max = f"{usd_max:.0f}" if usd_max is not None else "0"
            return f"{h_min} $ - {h_max} $ / saat" if lang == "tr" else f"${h_min} - ${h_max} / hr"
        else:
            if lang == "tr":
                return f"{orig_min:,.0f} {sym} - {orig_max:,.0f} {sym} / saat (~{usd_min:.0f} $ - ~{usd_max:.0f} $ / saat)"
            else:
                return f"{orig_min:,.0f} {sym} - {orig_max:,.0f} {sym} / hr (~${usd_min:.0f} - ~${usd_max:.0f} / hr)"


def translate_job_details(title: str, summary: str, target_lang: str = "tr") -> Tuple[str, str]:
    """Translates job title and summary into natural Turkish using Gemini, with instant fallback."""
    if target_lang != "tr" or not (title or summary):
        return title, summary

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return title, summary

    model = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.5-flash-lite")
    if "gemini-2.0" in model:
        model = "gemini-3.5-flash-lite"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    prompt = (
        "Translate the following freelance software job title and summary into natural, professional Turkish. "
        "Keep standard technical terms (e.g. Python, Docker, API, PostgreSQL, AWS, C++, React, Git, Linux) unchanged.\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        "Return ONLY a valid JSON object in this exact schema without markdown formatting:\n"
        '{"title": "...", "summary": "..."}'
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "FreelancerAgency/1.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            candidates = body.get("candidates", [])
            if candidates:
                raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
                clean_json = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.I)
                clean_json = re.sub(r"\s*```$", "", clean_json).strip()
                parsed = json.loads(clean_json)
                tr_title = parsed.get("title", "").strip() or title
                tr_summary = parsed.get("summary", "").strip() or summary
                return tr_title, tr_summary
    except Exception:
        pass

    return title, summary


def format_duration(estimated_hours: float, lang: str = "tr") -> str:
    """Calculates completion days assuming 3 hours of focused daily work."""
    hours = max(1.0, float(estimated_hours))
    days = max(1, math.ceil(hours / 3.0))

    if lang == "tr":
        return f"{days} gün (günde 3 saatten toplam {hours:.0f} saat)"
    else:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} (based on 3h/day, total {hours:.0f}h)"


class TelegramNotifier:
    """Dispatches proactive alerts and proposal approval requests via Telegram Bot API."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def format_urgent_lead(self, job: JobLead, roi_score: float, estimated_hours: float, lang: str = "tr") -> str:
        # Price formatting with multi-currency & USD conversion support
        price = format_price(job, lang=lang)

        # Duration
        duration_str = format_duration(estimated_hours, lang=lang)

        # Tech stack
        text_to_scan = f"{job.title} {job.description}"
        skills = job.raw_metadata.get("skills", [])
        if isinstance(skills, list):
            skill_names = [s.get("name", str(s)) if isinstance(s, dict) else str(s) for s in skills]
        else:
            skill_names = []

        langs, tools = extract_tech_stack(text_to_scan, skill_names)
        rec_langs, rec_tools = get_agent_recommendations(text_to_scan)

        # Summary extraction
        raw_summary = extract_clean_summary(job.description)

        # If Turkish is requested, translate title and summary into professional Turkish
        if lang == "tr":
            display_title, display_summary = translate_job_details(job.title, raw_summary, target_lang="tr")
        else:
            display_title, display_summary = job.title, raw_summary

        if lang == "tr":
            price_header = "Fiyat:"
            job_header = "İş:"
            summary_header = "Özet:"
            time_header = "Tahmini tamamlanma süresi:"
            lang_header = "Kullanılacak diller:"
            tools_header = "İş için kullanılacak araçlar ve sistemler:"
            client_header = "İş veren bilgileri:"
            unspecified = "*BELİRTİLMEDİ*"
            rec_prefix = "AGENT ÖNERİLERİ:"
            payment_info = "Ödeme Onaylı" if job.client_payment_verified else "Ödeme Doğrulanmamış"
            hire_info = f"İşe Alma: %{job.client_hire_rate:.0f}" if job.client_hire_rate is not None else "İşe Alma: N/A"
            rating_info = f"Puan: {job.client_rating:.1f}/5" if job.client_rating else "Puan: Yeni"
            proposals_info = f"Teklif Sayısı: {job.proposals_count}"
            platform_badge = f"*Platform:* {job.platform.capitalize()} | *ROI:* {roi_score:.1f}/10"
        else:
            price_header = "Price:"
            job_header = "Job:"
            summary_header = "Summary:"
            time_header = "Estimated completion time:"
            lang_header = "Languages to use:"
            tools_header = "Tools and systems to use:"
            client_header = "Client information:"
            unspecified = "*NOT SPECIFIED*"
            rec_prefix = "AGENT RECOMMENDATIONS:"
            payment_info = "Payment Verified" if job.client_payment_verified else "Payment Unverified"
            hire_info = f"Hire Rate: {job.client_hire_rate:.0f}%" if job.client_hire_rate is not None else "Hire Rate: N/A"
            rating_info = f"Rating: {job.client_rating:.1f}/5" if job.client_rating else "Rating: New"
            proposals_info = f"Proposals: {job.proposals_count}"
            platform_badge = f"*Platform:* {job.platform.capitalize()} | *ROI:* {roi_score:.1f}/10"

        # Languages block
        langs_str = ", ".join(langs) if langs else f"{unspecified}\n{rec_prefix} {', '.join(rec_langs)}"

        # Tools block
        tools_str = ", ".join(tools) if tools else f"{unspecified}\n{rec_prefix} {', '.join(rec_tools)}"

        # Client line
        client_line = f"{rating_info} | {hire_info} | {payment_info} | {proposals_info}"

        summary_block = f"*{summary_header}*\n{display_summary}\n\n" if display_summary else ""

        return (
            f"{platform_badge}\n\n"
            f"*{price_header}*\n"
            f"{price}\n\n"
            f"*{job_header}*\n"
            f"{display_title}\n\n"
            f"{summary_block}"
            f"*{time_header}*\n"
            f"{duration_str}\n\n"
            f"*{lang_header}*\n"
            f"{langs_str}\n\n"
            f"*{tools_header}*\n"
            f"{tools_str}\n\n"
            f"*{client_header}*\n"
            f"{client_line}"
        )

    def build_urgent_lead_keyboard(self, job_id: str, job_url: str = "", lang: str = "tr") -> dict:
        """Constructs inline action buttons including direct URL launcher."""
        open_text = "İlanı Aç ↗" if lang == "tr" else "Open Job ↗"
        draft_text = "Teklif Hazırla" if lang == "tr" else "Draft Proposal"
        skip_text = "Reddet" if lang == "tr" else "Reject"

        rows = []
        if job_url:
            rows.append([{"text": open_text, "url": job_url}])

        rows.append([
            {"text": draft_text, "callback_data": f"draft:{job_id}"},
            {"text": skip_text, "callback_data": f"skip:{job_id}"}
        ])

        return {"inline_keyboard": rows}

    def build_listall_keyboard(self, page: int, total_pages: int, lang: str = "tr") -> dict:
        """Constructs in-place pagination buttons for browsing opportunities."""
        prev_text = "⬅️ Önceki" if lang == "tr" else "⬅️ Prev"
        next_text = "Sonraki ➡️" if lang == "tr" else "Next ➡️"
        page_text = f"📄 {page} / {total_pages}"

        row = []
        if page > 1:
            row.append({"text": prev_text, "callback_data": f"page:listall:{page - 1}"})
        row.append({"text": page_text, "callback_data": f"page:listall:{page}"})
        if page < total_pages:
            row.append({"text": next_text, "callback_data": f"page:listall:{page + 1}"})

        return {"inline_keyboard": [row]}

    def build_main_reply_keyboard(self, lang: str = "tr", web_app_url: Optional[str] = None) -> dict:
        """Constructs persistent bottom touch keyboard replacing tedious manual typing."""
        url = web_app_url or os.environ.get("TELEGRAM_WEB_APP_URL")

        if lang == "tr":
            row1 = [{"text": "🔥 Sıcak Fırsatlar"}, {"text": "📋 Tüm İlanlar"}]
            row2 = [{"text": "⚡ Anlık Tara"}, {"text": "📊 Ajans Durumu"}]
        else:
            row1 = [{"text": "🔥 Hot Leads"}, {"text": "📋 All Jobs"}]
            row2 = [{"text": "⚡ Scan Now"}, {"text": "📊 Status"}]

        keyboard = [row1, row2]
        if url:
            app_text = "📱 Ajans Paneli (Mini App)" if lang == "tr" else "📱 Agency Dashboard (Mini App)"
            keyboard.append([{"text": app_text, "web_app": {"url": url}}])

        return {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "is_persistent": True
        }

    def send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Sends message to the configured Telegram chat with web preview disabled and Markdown fallback."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "link_preview_options": {"is_disabled": True}
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            # If 400 Bad Request happens due to unescaped markdown in client text, fallback to plain text
            if e.code == 400:
                try:
                    payload.pop("parse_mode", None)
                    payload["text"] = text.replace("*", "")
                    fallback_data = json.dumps(payload).encode("utf-8")
                    fb_req = urllib.request.Request(
                        url,
                        data=fallback_data,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(fb_req, timeout=10) as fb_resp:
                        return fb_resp.status == 200
                except Exception:
                    return False
            return False
        except Exception:
            return False

    def send_urgent_alert(self, job: JobLead, roi_score: float, estimated_hours: float, lang: str = "tr") -> bool:
        message = self.format_urgent_lead(job, roi_score, estimated_hours, lang=lang)
        keyboard = self.build_urgent_lead_keyboard(job.id, job_url=job.url, lang=lang)
        return self.send_message(message, reply_markup=keyboard)

    def set_bot_commands(self) -> bool:
        """Registers official bot commands with Telegram for '/' auto-completion and command menu."""
        if not self.is_configured:
            return False

        commands_tr = [
            {"command": "hot", "description": "🔥 En karlı sıcak fırsatları listele"},
            {"command": "listall", "description": "📋 Tüm aktif fırsatları sayfalı listele"},
            {"command": "status", "description": "📊 Ajans performans ve metrik raporu"},
            {"command": "scan", "description": "⚡ Anlık piyasa taraması başlat"},
            {"command": "audit", "description": "🔍 İlanları denetle ve teklif sayılarını tazele"},
            {"command": "show", "description": "🔍 İlan kartını detaylı görüntüle (/show <id>)"},
            {"command": "draft", "description": "✍️ İlan için teklif taslağı üret (/draft <id>)"},
            {"command": "portfolio", "description": "💼 Portföy ve GitHub imza ayarları"},
            {"command": "dil", "description": "🌐 Dili değiştir (/dil tr veya /dil en)"},
            {"command": "start", "description": "🚀 Botu başlat ve yardım menüsünü gör"}
        ]

        commands_en = [
            {"command": "hot", "description": "🔥 List qualified hot opportunities"},
            {"command": "listall", "description": "📋 Browse all opportunities paginated"},
            {"command": "status", "description": "📊 View agency performance metrics"},
            {"command": "scan", "description": "⚡ Trigger immediate market scan"},
            {"command": "audit", "description": "🔍 Audit jobs and refresh live proposal counts"},
            {"command": "show", "description": "🔍 Inspect full job card (/show <id>)"},
            {"command": "draft", "description": "✍️ Draft proposal (/draft <id>)"},
            {"command": "portfolio", "description": "💼 Portfolio and GitHub signature settings"},
            {"command": "lang", "description": "🌐 Switch language (/lang tr or /lang en)"},
            {"command": "start", "description": "🚀 Start bot and show menu"}
        ]

        url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"

        # Register default fallback (English)
        payload_default = json.dumps({"commands": commands_en}).encode("utf-8")
        req_def = urllib.request.Request(url, data=payload_default, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req_def, timeout=10):
                pass
        except Exception:
            pass

        # Register Turkish commands for Turkish clients
        payload_tr = json.dumps({"commands": commands_tr, "language_code": "tr"}).encode("utf-8")
        req_tr = urllib.request.Request(url, data=payload_tr, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req_tr, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"[Telegram] Failed to set bot commands: {e}")
            return False

    def set_chat_menu_button(self, web_app_url: Optional[str] = None, lang: str = "tr") -> bool:
        """Sets the persistent bottom-left menu button to launch Web App Mini App or default menu."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/setChatMenuButton"
        if web_app_url:
            button_text = "📱 Ajans Paneli" if lang == "tr" else "📱 Dashboard"
            payload = {
                "menu_button": {
                    "type": "web_app",
                    "text": button_text,
                    "web_app": {"url": web_app_url}
                }
            }
        else:
            payload = {"menu_button": {"type": "commands"}}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"[Telegram] Failed to set chat menu button: {e}")
            return False
