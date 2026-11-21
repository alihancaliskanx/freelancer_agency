"""Unit tests for TelegramNotifier and notification formatting."""
import unittest
from unittest.mock import patch
from src.models import JobLead
from src.notifications.telegram import (
    TelegramNotifier,
    extract_clean_summary,
    extract_tech_stack,
    format_duration,
    format_price,
    translate_job_details,
)


class TestTelegramNotifier(unittest.TestCase):
    def setUp(self):
        self.notifier = TelegramNotifier(bot_token="fake_token", chat_id="12345")
        self.sample_job = JobLead(
            id="job:sample_alert",
            title="Python Automation & Scraping",
            description="<p>We are looking for an engineer to build a financial scraper.</p><br>The bot should run daily and save data to PostgreSQL. Experience with Docker required.",
            job_type="fixed",
            platform="upwork",
            budget=1500.0,
            currency="USD",
            currency_symbol="$",
            original_budget=1500.0,
            client_payment_verified=True,
            client_hire_rate=80.0,
            client_rating=4.9,
            proposals_count=5,
            url="https://upwork.com/jobs/sample_alert",
            raw_metadata={"skills": ["Python", "Docker", "PostgreSQL"]}
        )

    def test_extract_clean_summary(self):
        desc = "<p>First sentence here.</p> Second sentence here! Third sentence should be omitted if long."
        summary = extract_clean_summary(desc, max_chars=100)
        self.assertIn("First sentence here.", summary)
        self.assertIn("Second sentence here!", summary)
        self.assertNotIn("<p>", summary)

    def test_format_price_multi_currency(self):
        # 1. USD job
        price_usd = format_price(self.sample_job, lang="tr")
        self.assertEqual(price_usd, "1,500 $")

        # 2. INR job: 37,500 INR with ~$405 USD value
        inr_job = JobLead(
            id="freelancer:inr_1",
            title="Firmware Task",
            description="STM32 C++ task",
            job_type="fixed",
            platform="freelancer",
            budget=404.74,
            currency="INR",
            currency_symbol="₹",
            original_budget=37500.0
        )
        price_inr = format_price(inr_job, lang="tr")
        self.assertIn("37,500 ₹ (INR)", price_inr)
        self.assertIn("(~405 $)", price_inr)

        # 3. EUR Hourly job: 40-60 EUR (~$44-$66 USD)
        eur_job = JobLead(
            id="freelancer:eur_1",
            title="Vue Dev",
            description="Frontend work",
            job_type="hourly",
            platform="freelancer",
            hourly_rate_min=43.85,
            hourly_rate_max=65.78,
            currency="EUR",
            currency_symbol="€",
            original_hourly_min=40.0,
            original_hourly_max=60.0
        )
        price_eur = format_price(eur_job, lang="tr")
        self.assertIn("40 € - 60 € / saat", price_eur)
        self.assertIn("(~44 $ - ~66 $ / saat)", price_eur)

    @patch("src.notifications.telegram.translate_job_details")
    def test_format_urgent_lead_turkish(self, mock_translate):
        mock_translate.return_value = (
            "Python Otomasyon ve Veri Kazıma",
            "Finansal bir veri kazıyıcı inşa edecek mühendis arıyoruz."
        )
        msg = self.notifier.format_urgent_lead(self.sample_job, roi_score=9.2, estimated_hours=15.0, lang="tr")
        self.assertIn("*Platform:* Upwork | *ROI:* 9.2/10", msg)
        self.assertIn("*Fiyat:*\n1,500 $", msg)
        self.assertIn("*İş:*\nPython Otomasyon ve Veri Kazıma", msg)
        self.assertIn("*Özet:*", msg)
        self.assertIn("Finansal bir veri kazıyıcı inşa edecek mühendis arıyoruz.", msg)
        self.assertIn("*Tahmini tamamlanma süresi:*\n5 gün (günde 3 saatten toplam 15 saat)", msg)
        self.assertIn("*Kullanılacak diller:*\nPython", msg)
        self.assertIn("*İş için kullanılacak araçlar ve sistemler:*\nDocker, PostgreSQL", msg)
        self.assertIn("*İş veren bilgileri:*", msg)

    def test_format_urgent_lead_english(self):
        msg = self.notifier.format_urgent_lead(self.sample_job, roi_score=9.2, estimated_hours=15.0, lang="en")
        self.assertIn("*Price:*\n1,500 $", msg)
        self.assertIn("*Job:*\nPython Automation & Scraping", msg)
        self.assertIn("*Summary:*", msg)
        self.assertIn("Estimated completion time:", msg)

    def test_build_urgent_lead_keyboard(self):
        kb_tr = self.notifier.build_urgent_lead_keyboard("job:sample_alert", job_url="https://upwork.com/jobs/sample_alert", lang="tr")
        rows = kb_tr["inline_keyboard"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0]["text"], "İlanı Aç ↗")
        self.assertEqual(rows[0][0]["url"], "https://upwork.com/jobs/sample_alert")
        self.assertEqual(rows[1][0]["text"], "Teklif Hazırla")
        self.assertEqual(rows[1][1]["text"], "Reddet")

    @patch("urllib.request.urlopen")
    def test_set_bot_commands(self, mock_urlopen):
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.notifier.set_bot_commands()
        self.assertTrue(res)
        self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen")
    def test_set_chat_menu_button(self, mock_urlopen):
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.notifier.set_chat_menu_button(web_app_url="https://test.trycloudflare.com", lang="tr")
        self.assertTrue(res)
        self.assertTrue(mock_urlopen.called)


if __name__ == "__main__":
    unittest.main()
