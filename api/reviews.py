"""Vercel Function: collect every public review for a Coupang product and return CSV."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import traceback
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://www.coupang.com"
MRSCRAPER_URL = "https://sync.scraper.mrscraper.com/api/commerce/coupang/reviews/sync"
PRODUCT_PATH_RE = re.compile(r"/products/(\d+)")
SORT_OPTIONS = {"DATE_DESC", "ORDER_SCORE_ASC", "ORDER_SCORE_DESC"}
PAGE_SIZE = 30
MAX_PAGES = 500
HTTP_TIMEOUT_SECONDS = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

CSV_FIELDS = [
    "review_id",
    "rating",
    "title",
    "review_text",
    "reviewer",
    "reviewed_at",
    "item_name",
    "vendor_name",
    "helpful_count",
    "survey_answers",
    "image_urls",
    "product_id",
    "item_id",
    "vendor_item_id",
    "source_url",
]


class ExporterError(RuntimeError):
    code = "EXPORT_FAILED"
    status = 502


class InvalidProductUrl(ExporterError):
    code = "INVALID_PRODUCT_URL"
    status = 400


class CoupangBlocked(ExporterError):
    code = "COUPANG_BLOCKED"
    status = 502


class UpstreamTemporaryError(ExporterError):
    code = "UPSTREAM_TEMPORARY_ERROR"
    status = 503


class TooManyReviews(ExporterError):
    code = "TOO_MANY_REVIEW_PAGES"
    status = 422


def parse_product_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.isdigit():
        return value, f"{BASE_URL}/vp/products/{value}"

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise InvalidProductUrl("Enter a complete http:// or https:// Coupang product URL.")
    if hostname != "coupang.com" and not hostname.endswith(".coupang.com"):
        raise InvalidProductUrl("The URL must be on coupang.com.")

    match = PRODUCT_PATH_RE.search(parsed.path)
    if not match:
        raise InvalidProductUrl("The URL must contain /products/<productId>.")
    return match.group(1), value


def make_review_url(product_id: str, page: int, sort_by: str) -> str:
    query = urlencode(
        [
            ("productId", product_id),
            ("page", page),
            ("size", PAGE_SIZE),
            ("sortBy", sort_by),
            ("ratingSummary", "true"),
            ("ratings", ""),
            ("market", ""),
        ]
    )
    return f"{BASE_URL}/next-api/review?{query}"


def request_headers(source_url: str) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "referer": source_url,
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "user-agent": USER_AGENT,
    }
    cookie = os.environ.get("COUPANG_COOKIE", "").strip()
    if cookie:
        headers["cookie"] = cookie
    return headers


def response_is_blocked(status: int, headers: Any, body: str) -> bool:
    content_type = headers.get("content-type", "")
    if status in {401, 403}:
        return True
    if "text/html" in content_type:
        return "Access Denied" in body or "sec-if-cpt-container" in body or "error403" in body
    return False


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        return error.code, error.headers, error.read().decode("utf-8", errors="replace")
    except (OSError, URLError) as error:
        raise UpstreamTemporaryError(f"The upstream request failed: {error.reason if isinstance(error, URLError) else error}") from error


class ReviewTransport:
    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        self.headers = request_headers(source_url)
        self.proxy_key = os.environ.get("MRSCRAPER_API_KEY", "").strip()
        # Vercel data-center requests are commonly blocked by Coupang. When a
        # fallback key exists, use it immediately instead of spending function
        # time on a direct request that is expected to fail.
        self.use_proxy = bool(self.proxy_key)

    def get_page(self, product_id: str, page: int, sort_by: str) -> dict[str, Any]:
        review_url = make_review_url(product_id, page, sort_by)
        for attempt in range(3):
            try:
                if self.use_proxy:
                    return self._request_proxy(review_url)
                return self._request_direct(review_url)
            except CoupangBlocked:
                if not self.proxy_key:
                    raise CoupangBlocked(
                        "Coupang blocked this deployment. Keep the Vercel function in icn1, "
                        "or configure MRSCRAPER_API_KEY as a fallback."
                    )
                self.use_proxy = True
            except UpstreamTemporaryError:
                if attempt == 2:
                    raise
                time.sleep(0.6 * (attempt + 1))
        raise UpstreamTemporaryError("The review source did not respond after retries.")

    def _request_direct(self, review_url: str) -> dict[str, Any]:
        status, headers, body = request_json(review_url, headers=self.headers)
        if response_is_blocked(status, headers, body):
            raise CoupangBlocked("Coupang rejected the direct review request.")
        if status == 429 or status >= 500:
            raise UpstreamTemporaryError(f"Coupang returned HTTP {status}.")
        if status >= 400:
            raise ExporterError(f"Coupang returned HTTP {status}.")
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise UpstreamTemporaryError("Coupang returned an unexpected non-JSON response.") from error

    def _request_proxy(self, review_url: str) -> dict[str, Any]:
        status, _, response_body = request_json(
            MRSCRAPER_URL,
            method="POST",
            headers={
                "authorization": f"Bearer {self.proxy_key}",
                "content-type": "application/json",
                "user-agent": USER_AGENT,
            },
            payload={"url": review_url},
        )
        if status in {408, 429} or status >= 500:
            raise UpstreamTemporaryError(f"The configured fallback returned HTTP {status}.")
        if status in {401, 403}:
            raise ExporterError("MRSCRAPER_API_KEY was rejected by the configured fallback.")
        if status >= 400:
            raise ExporterError(f"The configured fallback returned HTTP {status}.")
        try:
            body = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise ExporterError("The configured fallback returned an unexpected response.") from error
        if not body.get("success") or not isinstance(body.get("data"), dict):
            raise ExporterError(body.get("message") or "The configured fallback returned no review data.")
        return body["data"]


def parse_review_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    if payload.get("rCode") != "RET0000":
        raise ExporterError(
            f"Coupang review API error {payload.get('rCode')}: {payload.get('rMessage') or 'unknown error'}"
        )
    data = payload.get("rData") or {}
    paging = data.get("paging") or {}
    contents = paging.get("contents") or []
    total_count = int(paging.get("totalCount") or data.get("reviewTotalCount") or 0)
    total_pages = int(paging.get("totalPage") or 0)
    return contents, total_count, total_pages


def epoch_ms_to_iso(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


def absolute_image_url(value: Any) -> str:
    if not value:
        return ""
    value = str(value)
    return f"https:{value}" if value.startswith("//") else value


def normalize_review(review: dict[str, Any], source_url: str) -> dict[str, Any]:
    images = []
    for attachment in review.get("attachments") or []:
        url = absolute_image_url(attachment.get("imgSrcOrigin") or attachment.get("imgSrcThumbnail"))
        if url:
            images.append(url)

    survey_answers = []
    for answer in review.get("reviewSurveyAnswers") or []:
        question = str(answer.get("question") or "").strip()
        response = str(answer.get("answer") or "").strip()
        if question or response:
            survey_answers.append(f"{question}: {response}".strip(": "))

    return {
        "review_id": str(review.get("reviewId") or ""),
        "rating": int(review.get("rating") or 0),
        "title": review.get("title") or "",
        "review_text": review.get("content") or "",
        "reviewer": review.get("displayName") or review.get("displayWriter") or "",
        "reviewed_at": epoch_ms_to_iso(review.get("reviewAt") or review.get("createdAt")),
        "item_name": review.get("itemName") or "",
        "vendor_name": review.get("vendorName") or "",
        "helpful_count": int(review.get("helpfulCount") or 0),
        "survey_answers": " | ".join(survey_answers),
        "image_urls": " | ".join(images),
        "product_id": str(review.get("productId") or ""),
        "item_id": str(review.get("itemId") or ""),
        "vendor_item_id": str(review.get("vendorItemId") or ""),
        "source_url": source_url,
    }


def collect_reviews(product_url: str, sort_by: str = "DATE_DESC") -> tuple[str, list[dict[str, Any]]]:
    product_id, source_url = parse_product_url(product_url)
    if sort_by not in SORT_OPTIONS:
        sort_by = "DATE_DESC"

    transport = ReviewTransport(source_url)
    first_payload = transport.get_page(product_id, 1, sort_by)
    first_page, total_count, total_pages = parse_review_page(first_payload)
    if total_pages > MAX_PAGES:
        raise TooManyReviews(
            f"This product has {total_pages} review pages; the deployment safety limit is {MAX_PAGES}."
        )

    raw_reviews = list(first_page)
    for page in range(2, total_pages + 1):
        payload = transport.get_page(product_id, page, sort_by)
        page_reviews, _, _ = parse_review_page(payload)
        raw_reviews.extend(page_reviews)
        if not page_reviews:
            break
        time.sleep(0.08)

    unique_reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for review in raw_reviews:
        review_id = str(review.get("reviewId") or "")
        if review_id and review_id in seen_ids:
            continue
        if review_id:
            seen_ids.add(review_id)
        unique_reviews.append(normalize_review(review, source_url))

    if total_count and len(unique_reviews) != total_count:
        raise ExporterError(
            f"Coupang reported {total_count} reviews, but {len(unique_reviews)} unique rows were returned. "
            "Retry the export."
        )
    return product_id, unique_reviews


def reviews_to_csv(reviews: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(reviews)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json(200, {"ok": True, "service": "coupang-review-exporter"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 20_000:
                raise InvalidProductUrl("Send a small JSON body containing a Coupang product URL.")
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            product_url = str(body.get("url") or "")
            sort_by = str(body.get("sortBy") or "DATE_DESC")
            product_id, reviews = collect_reviews(product_url, sort_by)
            csv_bytes = reviews_to_csv(reviews)

            filename = f"coupang-reviews-{product_id}.csv"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Product-Id", product_id)
            self.send_header("X-Review-Count", str(len(reviews)))
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)
        except json.JSONDecodeError:
            self._send_json(400, {"code": "INVALID_JSON", "message": "The request body must be valid JSON."})
        except ExporterError as error:
            self._send_json(error.status, {"code": error.code, "message": str(error)})
        except Exception:
            traceback.print_exc()
            self._send_json(
                500,
                {
                    "code": "UNEXPECTED_ERROR",
                    "message": "The export failed unexpectedly. Check the function logs and retry.",
                },
            )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


__all__ = [
    "CSV_FIELDS",
    "InvalidProductUrl",
    "collect_reviews",
    "handler",
    "normalize_review",
    "parse_product_url",
    "parse_review_page",
    "reviews_to_csv",
]
