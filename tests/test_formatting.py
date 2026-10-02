"""수치 보존, 안전한 HTML, 길이 제한, 발행 요청 형식을 확인한다."""
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import cafe_poster
from utils import remove_emojis


def sample_digest():
    return {
        "date": "2026-08-06",
        "chat_name": "경제 시황 자료 채널",
        "count": 3,
        "items": [
            {
                "date_kst": "2026-08-06T07:10:00+09:00",
                "body": (
                    "📌 **미국 증시, 기술주 중심 상승**\n\n"
                    "✅ 가상의 미국 주가지수는 전 거래일보다 1.2% 상승했다.\n"
                    "● 기술주에 매수세가 유입되며 지수 상승을 이끌었다.\n"
                    "■ 시장은 다음 주 발표될 물가 지표를 주시하고 있다.\n"
                    "원문: https://example.com/news/markets"
                ),
            },
            {
                "date_kst": "2026-08-06T07:20:00+09:00",
                "body": (
                    "💵 원·달러 환율 하락\n\n"
                    "가상의 원·달러 환율은 전날보다 5.5원 내린 1,350.0원을 기록했다.\n"
                    "달러 약세와 외국인 자금 유입이 환율 하락 요인으로 작용했다."
                ),
            },
            {
                "date_kst": "2026-08-06T07:30:00+09:00",
                "body": (
                    "🛢 국제 유가, 수요 전망에 하락\n\n"
                    "가상의 국제 유가는 전 거래일보다 0.8% 하락했다.\n"
                    "시장에서는 주요국의 경기 흐름과 원유 수요 전망을 함께 살피고 있다."
                ),
            },
        ],
    }


class FormattingTests(unittest.TestCase):
    def test_financial_figures_survive_emoji_removal(self):
        raw = "📈✅⭐❤️🇰🇷👩‍💻1️⃣ 3.5% -1.2% +0.8% $90 €80 ₩1,350 ↑↓ ▲▼"
        self.assertEqual(
            remove_emojis(raw), "1 3.5% -1.2% +0.8% $90 €80 ₩1,350 ↑↓ ▲▼"
        )

    def test_korean_subject_keeps_source_without_decorations(self):
        subject = cafe_poster._build_subject("2026-08-06", 1, 2, "📌 경제 자료")
        self.assertEqual(subject, "2026.08.06(목) 경제 뉴스 브리핑 | 경제 자료")

    def test_summary_preserves_numbers_and_separates_links(self):
        headline, summary, links = cafe_poster._prepare_news_item({"body": (
            "📌 **환율과 금리**\n✅ 환율은 ₩1,350.5로 0.8% 하락했다.\n"
            "- 금리는 3.5%를 유지했다.\n-1.2% 변동이다.\n"
            "원문: https://example.com/news?a=1&b=2\n"
            "https://t.me/example"
        )})
        self.assertEqual(headline, "환율과 금리")
        for value in ("₩1,350.5", "0.8%", "3.5%", "-1.2%"):
            self.assertIn(value, summary)
        self.assertNotIn("http", summary)
        self.assertEqual(links, ["https://example.com/news?a=1&b=2"])

    def test_omission_is_visible_and_length_is_bounded(self):
        summary = cafe_poster._summarize_body("첫 문장.\n두 번째.\n세 번째.\n네 번째.", 900)
        self.assertTrue(summary.endswith("…"))
        self.assertNotIn("네 번째", summary)
        long_summary = cafe_poster._summarize_body("긴 문장 " * 100, 60)
        self.assertLessEqual(len(long_summary), 60)
        self.assertTrue(long_summary.endswith("…"))
        decimal_summary = cafe_poster._summarize_body("금리는 3.5%다. " + "다음 문장 " * 100, 30)
        self.assertEqual(decimal_summary, "금리는 3.5%다.…")

    def test_untrusted_text_is_escaped_and_links_are_separate(self):
        digest = sample_digest()
        digest["chat_name"] = '<script>alert("x")</script>'
        digest["items"] = [{"body": '제목 <img src=x>\n본문 & 수치 3.5%.\nhttps://example.com/?a=1&b=2'}]
        content = cafe_poster._build_channel_content(digest, digest["date"])
        self.assertNotIn("<script>", content)
        self.assertNotIn("<img", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("&lt;img src=x&gt;", content)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', content)
        self.assertIn("본문 &amp; 수치 3.5%.", content)

    def test_post_request_keeps_html_and_korean_text(self):
        digest = sample_digest()
        content = cafe_poster._build_channel_content(digest, digest["date"])
        subject = cafe_poster._build_subject(digest["date"], 1, 1, digest["chat_name"])
        response = Mock(status_code=200, text="mock success")
        response.json.return_value = {"message": {"status": "200", "result": {"articleUrl": "https://example.com/cafe/1"}}}
        with patch.object(cafe_poster.requests, "post", return_value=response) as post:
            success, _, url = cafe_poster._post_once(subject, content, "test-token")
        self.assertTrue(success)
        self.assertEqual(url, "https://example.com/cafe/1")
        fields = parse_qs(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(fields["subject"], [subject])
        self.assertEqual(fields["content"], [content])
        self.assertIn("<strong>", content)
        self.assertNotIn("📌", content)

    def test_large_digest_stays_within_body_limit(self):
        digest = sample_digest()
        digest["items"] = [{"body": "기사 제목\n" + "내용 & <수치> 3.5%. " * 90}] * 100
        content = cafe_poster._build_channel_content(digest, digest["date"])
        self.assertLessEqual(len(content), cafe_poster.MAX_TOTAL_BODY)
        self.assertIn("나머지", content)
        self.assertIn("생략했습니다", content)

    def test_malformed_url_does_not_stop_formatting(self):
        headline, summary, links = cafe_poster._prepare_news_item(
            {"body": "기사 제목\n본문입니다.\nhttp://[broken"}
        )
        self.assertEqual(headline, "기사 제목")
        self.assertEqual(summary, "본문입니다.")
        self.assertEqual(links, [])


if __name__ == "__main__":
    unittest.main()
