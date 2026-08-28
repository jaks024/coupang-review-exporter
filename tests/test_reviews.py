from __future__ import annotations

import csv
import io
import json
import os
import unittest
from unittest.mock import patch

from api.reviews import (
    MRSCRAPER_URL,
    MRSCRAPER_UNBLOCKER_URL,
    InvalidProductUrl,
    ReviewTransport,
    normalize_review,
    parse_product_url,
    reviews_to_csv,
)


class ProductUrlTests(unittest.TestCase):
    def test_extracts_product_id(self) -> None:
        product_id, source_url = parse_product_url(
            "https://www.coupang.com/vp/products/1920045216?itemId=3260034071"
        )
        self.assertEqual(product_id, "1920045216")
        self.assertIn("itemId=3260034071", source_url)

    def test_rejects_external_hosts(self) -> None:
        with self.assertRaises(InvalidProductUrl):
            parse_product_url("https://example.com/vp/products/1920045216")


class CsvTests(unittest.TestCase):
    def test_normalization_omits_member_email_and_writes_utf8_csv(self) -> None:
        review = normalize_review(
            {
                "reviewId": 123,
                "productId": 456,
                "rating": 5,
                "content": "좋아요",
                "displayName": "김*수",
                "member": {"email": "masked@example.com"},
                "reviewAt": 1_700_000_000_000,
                "reviewSurveyAnswers": [{"question": "품질", "answer": "좋아요"}],
            },
            "https://www.coupang.com/vp/products/456",
        )

        self.assertNotIn("email", review)
        payload = reviews_to_csv([review])
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))

        decoded = payload.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(decoded)))
        self.assertEqual(rows[0]["review_text"], "좋아요")
        self.assertEqual(rows[0]["survey_answers"], "품질: 좋아요")


class FakeResponse:
    headers = {"content-type": "application/json"}

    def __init__(self, body: dict[str, object], status: int = 200) -> None:
        self.body = json.dumps(body).encode("utf-8")
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class TransportTests(unittest.TestCase):
    def test_api_key_uses_proxy_without_a_direct_coupang_request(self) -> None:
        response = FakeResponse({"success": True, "data": {"rCode": "RET0000"}})
        with patch.dict(os.environ, {"MRSCRAPER_API_KEY": "test-token"}), patch(
            "api.reviews.urlopen", return_value=response
        ) as mocked_urlopen:
            transport = ReviewTransport("https://www.coupang.com/vp/products/1920045216")
            payload = transport.get_page("1920045216", 1, "DATE_DESC")

        request = mocked_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, MRSCRAPER_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertIn("productId=1920045216", request_body["url"])
        self.assertEqual(payload["rCode"], "RET0000")

    def test_proxy_uses_web_unblocker_when_marketplace_route_is_missing(self) -> None:
        responses = [
            FakeResponse({}, status=404),
            FakeResponse({"rCode": "RET0000"}),
        ]
        with patch.dict(os.environ, {"MRSCRAPER_API_KEY": "test-token"}), patch(
            "api.reviews.urlopen", side_effect=responses
        ) as mocked_urlopen:
            transport = ReviewTransport("https://www.coupang.com/vp/products/1920045216")
            transport.get_page("1920045216", 1, "DATE_DESC")

        requested_urls = [call.args[0].full_url for call in mocked_urlopen.call_args_list]
        self.assertEqual(requested_urls[0], MRSCRAPER_URL)
        self.assertTrue(requested_urls[1].startswith(MRSCRAPER_UNBLOCKER_URL))
        self.assertIn("proxyCountry=kr", requested_urls[1])
        self.assertNotIn("test-token", requested_urls[1])
        self.assertEqual(mocked_urlopen.call_args_list[1].args[0].get_header("X-api-token"), "test-token")

    def test_decodes_browser_wrapped_json(self) -> None:
        browser_html = (
            '<html><body><pre>{&quot;rCode&quot;:&quot;RET0000&quot;,'
            '&quot;rData&quot;:{&quot;paging&quot;:{}}}</pre></body></html>'
        )

        payload = ReviewTransport._decode_coupang_payload(browser_html, "text/html")

        self.assertEqual(payload["rCode"], "RET0000")

    def test_decodes_nested_browser_wrapped_json(self) -> None:
        browser_html = '<html><body><pre>{"rCode":"RET0000"}</pre></body></html>'
        response_body = json.dumps({"success": True, "data": browser_html})

        payload = ReviewTransport._decode_coupang_payload(response_body, "application/json")

        self.assertEqual(payload["rCode"], "RET0000")


if __name__ == "__main__":
    unittest.main()
