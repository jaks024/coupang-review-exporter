from __future__ import annotations

import csv
import io
import unittest

from api.reviews import InvalidProductUrl, normalize_review, parse_product_url, reviews_to_csv


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


if __name__ == "__main__":
    unittest.main()

