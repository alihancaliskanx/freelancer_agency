"""CEO Orchestrator: The single conversational executive touchpoint for the user."""
import json
import math
import os
import re
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple, Union

from src.models import JobLead
from src.db.manager import DatabaseManager
from src.scouts.coordinator import ScoutCoordinator
from src.notifications.telegram import TelegramNotifier


def format_job_list_item(row: Dict[str, Any], index: int, lang: str = "tr") -> str:
    """Formats a job opportunity into a clean, visually structured list card."""
    job_id = row["id"]
    short_id = job_id.split(":", 1)[-1] if ":" in job_id else job_id
    title = row.get("title", "").strip()
    roi = row.get("roi_score") or 0.0
    platform = (row.get("platform") or "freelancer").capitalize()

    curr = (row.get("currency") or "USD").upper()
    sym = row.get("currency_symbol") or "$"
    is_usd = (curr == "USD")

    # Format price
    if row.get("job_type") == "fixed":
        orig_b = row.get("original_budget")
        usd_b = row.get("budget")
        if orig_b is not None and not is_usd:
            price_str = f"{orig_b:,.0f} {sym} ({curr}) (~{usd_b:,.0f} $)" if usd_b else f"{orig_b:,.0f} {sym}"
        elif usd_b is not None:
            price_str = f"{usd_b:,.0f} $"
        else:
            price_str = "Belirtilmedi" if lang == "tr" else "Not specified"
    else:
        orig_min = row.get("original_hourly_min")
        orig_max = row.get("original_hourly_max")
        usd_min = row.get("hourly_rate_min") or 0
        usd_max = row.get("hourly_rate_max") or 0
        unit = "/ saat" if lang == "tr" else "/ hr"
        if orig_min is not None and orig_max is not None and not is_usd:
            price_str = f"{orig_min:,.0f} {sym} - {orig_max:,.0f} {sym} {unit} (~{usd_min:.0f}$-~{usd_max:.0f}$)"
        else:
            price_str = f"{usd_min:.0f} $ - {usd_max:.0f} $ {unit}"

    verified = "Ödeme Onaylı" if row.get("client_payment_verified") else "Ödeme Doğrulanmamış"
    if lang != "tr":
        verified = "Payment Verified" if row.get("client_payment_verified") else "Unverified Payment"

    proposals = row.get("proposals_count") or 0
    props_str = f"{proposals} teklif" if lang == "tr" else f"{proposals} proposals"

    rating_val = row.get("client_rating")
    rating_str = f" ⭐ {rating_val:.1f}" if rating_val else ""

    show_cmd = f"/show {short_id}"

    if lang == "tr":
        return (
            f"*{index}. [{short_id}]* {title}\n"
            f"   • *Platform:* {platform} | *ROI:* {roi:.1f}/10\n"
            f"   • *Fiyat:* {price_str}\n"
            f"   • *İşveren:* {verified}{rating_str} | {props_str}\n"
            f"   • *Detay:* `{show_cmd}`"
        )
    else:
        return (
            f"*{index}. [{short_id}]* {title}\n"
            f"   • *Platform:* {platform} | *ROI:* {roi:.1f}/10\n"
            f"   • *Price:* {price_str}\n"
            f"   • *Client:* {verified}{rating_str} | {props_str}\n"
            f"   • *Details:* `{show_cmd}`"
        )


def generate_gemini_proposal(
    title: str,
    description: str,
    job_type: str,
    budget_str: str,
    custom_instructions: str = "",
    portfolio_url: str = "",
    signature_name: str = ""
) -> Optional[str]:
    """Generates human-like, zero-fluff proposal via Google Gemini API using Standard Library."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    signoff_instructions = ""
    if signature_name or portfolio_url:
        signoff_instructions = (
            f"\nSign-off Requirements:\n"
            f"- Close professionally with the sign-off.\n"
            f"- Developer name: {signature_name if signature_name else 'Lead Engineer'}\n"
            f"- Portfolio / GitHub reference: {portfolio_url if portfolio_url else ''}\n"
        )

    prompt = f"""You are a senior freelance software agency lead. Write a short, punchy, 3-paragraph proposal for this client:
Title: {title}
Type/Budget: {job_type} ({budget_str})
Description: {description}
{f'Custom Instructions: {custom_instructions}' if custom_instructions else ''}
{signoff_instructions}
Rules:
- No fluff, robotic pleasantries, or generic intro lines ('Dear hiring manager, I am excited to apply...').
- Paragraph 1: Direct technical solution and how you will solve their core problem cleanly.
- Paragraph 2: Proposed architecture, modular delivery steps, and realistic timeline. Mention relevant production experience/case studies.
- Paragraph 3: A smart technical qualification question.
- Conclude with the developer name and portfolio link if provided above.
"""

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "FreelancerAgency/1.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            candidates = body.get("candidates", [])
            if candidates:
                return candidates[0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[Gemini] Proposal generation fallback triggered: {e}")

    return None


class CeoOrchestrator:
    """Coordinates agency operations and communicates directly with the user."""

    def __init__(
        self,
        db: DatabaseManager,
        coordinator: Optional[ScoutCoordinator] = None,
        notifier: Optional[TelegramNotifier] = None,
        watcher: Optional[Any] = None,
        scoring_engine: Optional[Any] = None
    ):
        self.db = db
        self.coordinator = coordinator
        self.notifier = notifier
        self.watcher = watcher
        self.scoring_engine = scoring_engine

    def get_job_lead_from_row(self, row: Dict[str, Any]) -> JobLead:
        """Constructs standardized JobLead from a database row dictionary."""
        return self.db.row_to_job_lead(row)

    def get_status_overview(self) -> Dict[str, Any]:
        metrics = self.db.get_latest_metrics() or {}
        hot_leads = self.db.get_hot_leads(min_roi=6.0, limit=5)
        active_evaluated = self.db.get_jobs_by_status("evaluated", limit=100)
        drafted_proposals = self.db.get_jobs_by_status("proposal_drafted", limit=100)
        last_audit = self.db.get_setting("last_audit_time")
        last_stats_raw = self.db.get_setting("last_audit_stats")
        try:
            audit_stats = json.loads(last_stats_raw) if last_stats_raw else {}
        except Exception:
            audit_stats = {}

        return {
            "metrics": metrics,
            "hot_leads_count": len(hot_leads),
            "evaluated_jobs_count": len(active_evaluated),
            "proposals_pending_count": len(drafted_proposals),
            "top_hot_leads": hot_leads,
            "last_audit_time": last_audit,
            "last_audit_stats": audit_stats
        }

    def list_hot_opportunities(self, min_roi: float = 5.0, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.get_hot_leads(min_roi=min_roi, limit=limit)

    def list_all_opportunities(self, page: int = 1, limit: int = 8) -> Tuple[List[Dict[str, Any]], int, int]:
        offset = max(0, (page - 1) * limit)
        jobs, total = self.db.get_all_qualified_jobs(limit=limit, offset=offset)
        total_pages = max(1, math.ceil(total / limit))
        return jobs, total, total_pages

    def get_listall_page(self, page: int = 1, lang: Optional[str] = None) -> Tuple[str, dict]:
        """Formats a specific page of opportunities and builds in-place pagination buttons."""
        curr_lang = lang or self.db.get_setting("language", "tr")
        jobs, total, total_pages = self.list_all_opportunities(page=page, limit=8)
        notifier = self.notifier or TelegramNotifier()

        if not jobs:
            msg = "Listelenecek fırsat bulunamadı." if curr_lang == "tr" else "No opportunities found."
            return (msg, {"inline_keyboard": []})

        header = (
            f"📋 *Tüm Aktif Fırsatlar* (Sayfa {page}/{total_pages} — Toplam {total} İlan)"
        ) if curr_lang == "tr" else (
            f"📋 *All Active Opportunities* (Page {page}/{total_pages} — Total {total} Jobs)"
        )
        items = [header]
        start_idx = (page - 1) * 8 + 1
        for i, l in enumerate(jobs, start_idx):
            items.append(format_job_list_item(l, i, lang=curr_lang))

        footer = (
            f"💡 _Sayfa butonlarıyla gezinebilir veya `/show <id>` ile ilanı açabilirsiniz._"
        ) if curr_lang == "tr" else (
            f"💡 _Navigate pages with buttons below or type `/show <id>` to inspect details._"
        )
        items.append(footer)
        text = "\n\n".join(items)
        keyboard = notifier.build_listall_keyboard(page=page, total_pages=total_pages, lang=curr_lang)
        return (text, keyboard)

    def draft_proposal(self, job_id: str, custom_instructions: str = "") -> Dict[str, Any]:
        job = self.db.get_job(job_id)
        if not job:
            return {"success": False, "error": f"Job not found: {job_id}"}

        title = job["title"]
        description = job["description"] or ""
        job_type = job["job_type"]
        budget = job["budget"] or 0.0
        hourly_min = job["hourly_rate_min"] or 0.0
        hourly_max = job["hourly_rate_max"] or 0.0

        if job_type == "fixed":
            bid_amount = budget if budget > 0 else 500.0
            bid_summary = f"${bid_amount:,.2f}"
            timeline = "3-5 business days"
        else:
            bid_amount = hourly_max if hourly_max > 0 else (hourly_min if hourly_min > 0 else 50.0)
            bid_summary = f"${bid_amount:,.2f}/hr"
            timeline = "Ongoing / Flexible"

        # Retrieve configured portfolio and signature
        portfolio_url = self.db.get_setting("portfolio_url") or os.environ.get("AGENCY_PORTFOLIO_URL", "https://github.com/alihancaliskanx")
        signature_name = self.db.get_setting("signature_name") or os.environ.get("AGENCY_SIGNATURE_NAME", "Alihan Çalışkan")

        # Try Gemini generation first
        gemini_letter = generate_gemini_proposal(
            title=title,
            description=description,
            job_type=job_type,
            budget_str=bid_summary,
            custom_instructions=custom_instructions,
            portfolio_url=portfolio_url,
            signature_name=signature_name
        )

        if gemini_letter:
            cover_letter = gemini_letter
            if portfolio_url and portfolio_url not in cover_letter:
                cover_letter = f"{cover_letter}\n\nPortfolio / Code: {portfolio_url}"
            token_cost = 0.00
        else:
            sign_lines = []
            if signature_name:
                sign_lines.append(f"Best regards,\n{signature_name}")
            else:
                sign_lines.append("Best regards.")
            if portfolio_url:
                sign_lines.append(f"Portfolio / Code Repositories: {portfolio_url}")
            sign_off_block = "\n".join(sign_lines)

            custom_block = f"\n{custom_instructions}\n" if custom_instructions else ""
            cover_letter = (
                f"Dear Client,\n\n"
                f"I reviewed your project '{title}' and have the direct technical expertise "
                f"to deliver a robust solution without unnecessary complexity.\n\n"
                f"Technical Approach:\n"
                f"- Thorough requirement analysis and structured delivery.\n"
                f"- Clean, modular, well-tested code following best practices.\n"
                f"- Transparent milestones with regular async progress updates.\n"
                f"{custom_block}\n"
                f"I look forward to discussing the next steps.\n\n"
                f"{sign_off_block}"
            ).strip()
            token_cost = 0.02

        prop_id = self.db.create_proposal(
            job_id=job_id,
            cover_letter=cover_letter,
            bid_amount=bid_amount,
            estimated_timeline=timeline,
            token_cost_usd=token_cost
        )

        self.db.update_job_status(job_id, status="proposal_drafted")
        self.db.record_metric_heartbeat(proposals_increment=1, token_cost_increment=token_cost)

        return {
            "success": True,
            "proposal_id": prop_id,
            "job_id": job_id,
            "bid_amount": bid_amount,
            "bid_summary": bid_summary,
            "cover_letter": cover_letter
        }

    def handle_callback(self, callback_data: str) -> str:
        """Handles inline button callbacks (e.g. from Telegram)."""
        if callback_data.startswith("draft:"):
            job_id = callback_data.split("draft:", 1)[1]
            res = self.draft_proposal(job_id)
            if res.get("success"):
                return f"Proposal drafted for {job_id} ({res['bid_summary']}):\n\n{res['cover_letter']}"
            return f"Failed to draft proposal: {res.get('error')}"

        elif callback_data.startswith("skip:"):
            job_id = callback_data.split("skip:", 1)[1]
            self.db.update_job_status(job_id, status="rejected")
            return f"Opportunity {job_id} dismissed."

        elif callback_data.startswith("lang:"):
            new_lang = callback_data.split("lang:", 1)[1]
            if new_lang in ("tr", "en"):
                self.db.set_setting("language", new_lang)
                return "Dil Türkçe olarak ayarlandı." if new_lang == "tr" else "Language set to English."

        elif callback_data.startswith("page:listall:"):
            try:
                page_num = int(callback_data.split("page:listall:", 1)[1])
            except ValueError:
                page_num = 1
            curr_lang = self.db.get_setting("language", "tr")
            return self.get_listall_page(page=page_num, lang=curr_lang)

        return "Unknown action."

    def handle_message(self, message: str) -> Any:
        """Processes conversational executive commands from user."""
        norm_msg = message.strip().replace("İ", "i").replace("I", "ı").lower()
        msg = norm_msg
        curr_lang = self.db.get_setting("language", "tr")

        # 1. Language settings command
        if norm_msg.startswith(("/dil", "/lang")):
            parts = norm_msg.split()
            if len(parts) > 1 and parts[1].lower() in ("tr", "en"):
                new_lang = parts[1].lower()
                self.db.set_setting("language", new_lang)
                if new_lang == "tr":
                    return "Bildirim ve arayüz dili Türkçe olarak ayarlandı."
                else:
                    return "Notification and interface language set to English."
            
            return (
                f"Mevcut Dil / Current Language: {'Türkçe (tr)' if curr_lang == 'tr' else 'English (en)'}\n\n"
                f"Dili değiştirmek için:\n"
                f"/dil tr - Türkçe\n"
                f"/dil en - English"
            )

        # 2. Portfolio and Signature settings command
        if norm_msg.startswith(("/portfolio", "portfolio", "/imza", "imza", "/github", "github")):
            raw_parts = message.strip().split(maxsplit=1)
            arg = raw_parts[1].strip() if len(raw_parts) > 1 else ""

            if not arg:
                p_url = self.db.get_setting("portfolio_url") or os.environ.get("AGENCY_PORTFOLIO_URL", "https://github.com/alihancaliskanx")
                s_name = self.db.get_setting("signature_name") or os.environ.get("AGENCY_SIGNATURE_NAME", "Alihan Çalışkan")
                if curr_lang == "tr":
                    return (
                        f"💼 *Portföy ve İmza Ayarları*\n\n"
                        f"• *İsim:* {s_name}\n"
                        f"• *Portföy / GitHub:* {p_url}\n\n"
                        f"Güncellemek için:\n"
                        f"`/portfolio https://github.com/profiliniz`\n"
                        f"`/imza İsim Soyisim | https://github.com/profiliniz`"
                    )
                else:
                    return (
                        f"💼 *Portfolio & Signature Settings*\n\n"
                        f"• *Name:* {s_name}\n"
                        f"• *Portfolio / GitHub:* {p_url}\n\n"
                        f"To update:\n"
                        f"`/portfolio https://github.com/yourprofile`\n"
                        f"`/imza Name Surname | https://github.com/yourprofile`"
                    )

            if "|" in arg:
                parts = [p.strip() for p in arg.split("|", 1)]
                new_name = parts[0]
                new_url = parts[1]
                if new_name:
                    self.db.set_setting("signature_name", new_name)
                if new_url:
                    self.db.set_setting("portfolio_url", new_url)
                if curr_lang == "tr":
                    return f"✅ İmza ve portföy güncellendi:\nİsim: {new_name}\nURL: {new_url}"
                else:
                    return f"✅ Signature and portfolio updated:\nName: {new_name}\nURL: {new_url}"
            elif arg.startswith("http://") or arg.startswith("https://"):
                self.db.set_setting("portfolio_url", arg)
                if curr_lang == "tr":
                    return f"✅ Portföy adresi güncellendi: {arg}"
                else:
                    return f"✅ Portfolio URL updated: {arg}"
            else:
                self.db.set_setting("signature_name", arg)
                if curr_lang == "tr":
                    return f"✅ İmza ismi güncellendi: {arg}"
                else:
                    return f"✅ Signature name updated: {arg}"

        # 3. Status overview
        if norm_msg in ("/status", "status", "durum", "📊 ajans durumu", "📊 status"):
            overview = self.get_status_overview()
            m = overview["metrics"]
            audit_time = overview.get("last_audit_time") or "Henüz yapılmadı"
            if curr_lang == "tr":
                return (
                    f"Ajans Durum Raporu\n"
                    f"Bugün taranan: {m.get('total_jobs_scanned', 0)}\n"
                    f"Filtreyi geçen: {m.get('jobs_passed_filter', 0)}\n"
                    f"Üretilen teklif: {m.get('proposals_generated', 0)}\n"
                    f"Token maliyeti: ${m.get('total_token_cost_usd', 0.0):.4f}\n"
                    f"Aktif fırsatlar: {overview['evaluated_jobs_count']}\n"
                    f"Bekleyen teklifler: {overview['proposals_pending_count']}\n"
                    f"Son Canlı Denetim: {audit_time}"
                )
            else:
                audit_time_en = overview.get("last_audit_time") or "Not yet run"
                return (
                    f"Agency Status Overview\n"
                    f"Scanned today: {m.get('total_jobs_scanned', 0)}\n"
                    f"Passed filter: {m.get('jobs_passed_filter', 0)}\n"
                    f"Proposals generated: {m.get('proposals_generated', 0)}\n"
                    f"Token cost: ${m.get('total_token_cost_usd', 0.0):.4f}\n"
                    f"Active leads: {overview['evaluated_jobs_count']}\n"
                    f"Pending proposals: {overview['proposals_pending_count']}\n"
                    f"Last Live Audit: {audit_time_en}"
                )

        # 4. Continuous Audit trigger command
        if norm_msg in ("/audit", "audit", "/denetle", "denetle", "denetim", "🔍 denetle", "🔍 audit"):
            if self.watcher:
                stats = self.watcher.audit_batch(scoring_engine=self.scoring_engine, limit=50)
                if curr_lang == "tr":
                    return (
                        f"🔍 *Canlı Denetim Raporu*\n\n"
                        f"• *Denetlenen İlan:* {stats.get('audited', 0)}\n"
                        f"• *Teklif Sayısı Güncellenen:* {stats.get('proposals_updated', 0)}\n"
                        f"• *Kapatılan / Süresi Dolan:* {stats.get('closed', 0)}\n"
                        f"• *Aktif Kalan İlan:* {stats.get('active', 0)}"
                    )
                else:
                    return (
                        f"🔍 *Live Audit Report*\n\n"
                        f"• *Jobs Audited:* {stats.get('audited', 0)}\n"
                        f"• *Proposals Count Updated:* {stats.get('proposals_updated', 0)}\n"
                        f"• *Closed / Expired Jobs:* {stats.get('closed', 0)}\n"
                        f"• *Active Jobs:* {stats.get('active', 0)}"
                    )
            return "Denetim servisi yapılandırılmamış." if curr_lang == "tr" else "Audit service not configured."

        # 3. Hot leads
        if norm_msg in ("/hot", "hot", "leads", "fırsatlar", "🔥 sıcak fırsatlar", "🔥 hot leads"):
            leads = self.list_hot_opportunities(min_roi=5.0, limit=5)
            if not leads:
                return "Sıcak fırsat bulunamadı." if curr_lang == "tr" else "No hot opportunities found."
            
            header = "🔥 *Öne Çıkan Sıcak Fırsatlar (Top 5)*" if curr_lang == "tr" else "🔥 *Qualified Hot Opportunities (Top 5)*"
            items = [header]
            for i, l in enumerate(leads, 1):
                items.append(format_job_list_item(l, i, lang=curr_lang))
            
            footer = (
                "💡 _Detaylı kart için yanındaki `/show <id>` komutunu yazabilirsiniz._\n"
                "📋 _Tüm fırsatları listelemek için:_ `/listall`"
            ) if curr_lang == "tr" else (
                "💡 _To inspect full card with buttons: `/show <id>`_\n"
                "📋 _To list all opportunities:_ `/listall`"
            )
            items.append(footer)
            return "\n\n".join(items)

        # 4. List all opportunities (paginated with in-place buttons)
        listall_match = re.match(r"(?:/listall|listall|/all|all|/liste|liste|/tümü|tümü|📋 tüm ilanlar|📋 all jobs|tüm ilanlar)\s*(\d*)", norm_msg)
        if listall_match and (
            norm_msg.startswith(("/listall", "listall", "/all", "/liste", "liste", "📋", "tüm ilanlar"))
            or norm_msg in ("all", "tümü", "📋 tüm ilanlar", "📋 all jobs", "tüm ilanlar")
        ):
            page_str = listall_match.group(1).strip()
            page = int(page_str) if page_str.isdigit() and int(page_str) > 0 else 1
            return self.get_listall_page(page=page, lang=curr_lang)

        # 5. Immediate scan
        if norm_msg in ("/scan", "scan", "tara", "⚡ anlık tara", "⚡ scan now"):
            if self.coordinator:
                stats = self.coordinator.run_scan()
                if curr_lang == "tr":
                    return (
                        f"Tarama Tamamlandı:\n"
                        f"Taranan: {stats['total_scanned']}\n"
                        f"Filtreyi Geçen: {stats['passed_filters']}\n"
                        f"Yeni Eklenen: {stats['new_inserted']}\n"
                        f"Mükerrer: {stats['duplicates']}"
                    )
                else:
                    return (
                        f"Scan Completed:\n"
                        f"Scanned: {stats['total_scanned']}\n"
                        f"Passed: {stats['passed_filters']}\n"
                        f"New: {stats['new_inserted']}\n"
                        f"Duplicates: {stats['duplicates']}"
                    )
            return "Tarayıcı koordinatörü yapılandırılmamış." if curr_lang == "tr" else "Scout coordinator not configured."

        # 6. Show full job card
        show_match = re.match(r"(?:/show|show|/detay|detay|/göster|göster|/goster|goster)\s+([^\s]+)", msg)
        if show_match:
            job_id_input = show_match.group(1).strip()
            row = self.db.get_job(job_id_input)
            if not row:
                return f"İlan bulunamadı: '{job_id_input}'" if curr_lang == "tr" else f"Job not found: '{job_id_input}'"

            lead = self.get_job_lead_from_row(row)
            roi = row.get("roi_score") or 0.0
            hours = row.get("estimated_hours") or 10.0

            notifier = self.notifier or TelegramNotifier()
            card_text = notifier.format_urgent_lead(lead, roi, hours, lang=curr_lang)
            keyboard = notifier.build_urgent_lead_keyboard(lead.id, job_url=lead.url, lang=curr_lang)
            return (card_text, keyboard)

        # 7. Draft proposal
        draft_match = re.match(r"(?:/draft|draft|/teklif|teklif\s+hazırla|teklif)\s+([^\s]+)", msg)
        if draft_match:
            job_id = draft_match.group(1)
            res = self.draft_proposal(job_id)
            if res.get("success"):
                title_prefix = "Teklif Hazırlandı:" if curr_lang == "tr" else "Proposal Drafted:"
                return f"{title_prefix}\n\n{res['cover_letter']}"
            return f"Hata: {res.get('error')}" if curr_lang == "tr" else f"Error: {res.get('error')}"

        # 8. Default Help Menu
        if curr_lang == "tr":
            return (
                "Freelancer Agency CEO Arayüzü\n\n"
                "Komutlar:\n"
                "/status    - Metrikleri ve boru hattı sayılarını görüntüle\n"
                "/hot       - En yüksek ROI'li sıcak fırsatları listele\n"
                "/listall   - Tüm aktif fırsatları sayfalı listele (/listall <sayfa>)\n"
                "/show <id> - İlanı tüm detayları ve butonlarıyla göster\n"
                "/scan      - Anlık piyasa tarama döngüsü başlat\n"
                "/audit     - Canlı ilanları denetle ve teklif sayılarını tazele\n"
                "/portfolio - Portföy ve GitHub imza ayarlarını görüntüle/değiştir\n"
                "/dil       - Dil ayarlarını değiştir (/dil tr veya /dil en)\n"
                "/draft <id>- Belirtilen iş için teklif taslağı üret"
            )
        else:
            return (
                "Agency CEO Interface\n\n"
                "Commands:\n"
                "/status    - View metrics and pipeline counts\n"
                "/hot       - View qualified opportunities\n"
                "/listall   - View all opportunities paginated (/listall <page>)\n"
                "/show <id> - View full job card with action buttons\n"
                "/scan      - Trigger immediate scan cycle\n"
                "/audit     - Audit live jobs and refresh proposal counts\n"
                "/portfolio - View/update portfolio and GitHub signature settings\n"
                "/lang      - Change language (/lang tr or /lang en)\n"
                "/draft <id>- Draft proposal for job"
            )
