"""Upwork RSS feed scout parser supporting multi-query URL matrix."""
import html
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Union
import urllib.request
import urllib.error

from src.models import JobLead
from src.scouts.base import BaseScout


class UpworkRssScout(BaseScout):
    """Parses Upwork search RSS feeds into standardized JobLead instances."""

    def __init__(self, rss_urls: Optional[Union[str, List[str]]] = None):
        if isinstance(rss_urls, str):
            self.rss_urls = [rss_urls]
        elif isinstance(rss_urls, list):
            self.rss_urls = rss_urls
        else:
            self.rss_urls = []

    def parse_xml(self, xml_text: str) -> List[JobLead]:
        """Parses Upwork RSS XML content."""
        leads: List[JobLead] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return leads

        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")

        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")

            if title_elem is None or not title_elem.text:
                continue

            raw_title = title_elem.text.strip()
            clean_title = re.sub(r"\s*-\s*Upwork\s*$", "", raw_title, flags=re.I)

            url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            raw_desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

            raw_desc = html.unescape(raw_desc)

            id_match = re.search(r"_(~[0-9a-fA-F]+)", url)
            job_id = f"upwork:{id_match.group(1)}" if id_match else f"upwork:{hash(url)}"

            budget = None
            budget_match = re.search(r"<b>\s*Budget\s*</b>\s*:\s*\$?([\d,]+(?:\.\d+)?)", raw_desc, re.I)
            if budget_match:
                try:
                    budget = float(budget_match.group(1).replace(",", ""))
                except ValueError:
                    budget = None

            hourly_min = None
            hourly_max = None
            hourly_match = re.search(
                r"<b>\s*Hourly\s*Range\s*</b>\s*:\s*\$?([\d,]+(?:\.\d+)?)\s*-\s*\$?([\d,]+(?:\.\d+)?)",
                raw_desc,
                re.I
            )
            if hourly_match:
                try:
                    hourly_min = float(hourly_match.group(1).replace(",", ""))
                    hourly_max = float(hourly_match.group(2).replace(",", ""))
                except ValueError:
                    pass

            job_type = "hourly" if hourly_match else "fixed"

            country = None
            country_match = re.search(r"<b>\s*Country\s*</b>\s*:\s*([^<]+)", raw_desc, re.I)
            if country_match:
                country = country_match.group(1).strip()

            clean_desc = re.sub(r"<br\s*/?>", "\n", raw_desc)
            clean_desc = re.sub(r"<[^>]+>", " ", clean_desc)
            clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

            payment_verified = bool(
                re.search(r"payment\s*(?:method)?\s*:\s*verified", clean_desc, re.I)
                or re.search(r"payment\s+verified", clean_desc, re.I)
            )

            leads.append(
                JobLead(
                    id=job_id,
                    title=clean_title,
                    description=clean_desc,
                    job_type=job_type,
                    platform="upwork",
                    budget=budget,
                    hourly_rate_min=hourly_min,
                    hourly_rate_max=hourly_max,
                    client_payment_verified=payment_verified,
                    url=url,
                    raw_metadata={"country": country}
                )
            )

        return leads

    def fetch_leads(self) -> List[JobLead]:
        """Fetches from all configured live RSS URLs."""
        if not self.rss_urls:
            return []

        all_leads: List[JobLead] = []
        for url in self.rss_urls:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    xml_text = resp.read().decode("utf-8", errors="replace")
                    all_leads.extend(self.parse_xml(xml_text))
            except Exception:
                continue

        return all_leads
