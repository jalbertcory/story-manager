"""Best-effort Amazon metadata collector.

Amazon does not offer a public search API comparable to Google Books or Open
Library. This module is deliberately optional and isolated so a CAPTCHA,
markup change, or HTTP failure cannot break the rest of metadata sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .clients import amazon_base_url, request_amazon_html
from .scoring import clean_isbn, infer_series_metadata, normalize_text

_ISBN_10_RE = re.compile(r"ISBN-10\s*:?\s*([0-9Xx\- ]{10,20})", re.IGNORECASE)
_ISBN_13_RE = re.compile(r"ISBN-13\s*:?\s*([0-9\- ]{13,24})", re.IGNORECASE)
_BYLINE_NOISE_RE = re.compile(r"\s*\((?:author|editor|illustrator|translator|contributor)\)\s*", re.IGNORECASE)
_PAGE_COUNT_RE = re.compile(r"(?<!\d)(\d{1,6})\s+pages?\b", re.IGNORECASE)
_RATING_RE = re.compile(r"([0-5](?:[.,]\d+)?)\s+out of 5 stars", re.IGNORECASE)
_REVIEW_COUNT_RE = re.compile(r"([\d,]+)\s+(?:ratings?|reviews?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AmazonCandidate:
    asin: str
    title: str
    authors: list[str]
    url: str
    categories: list[str]
    isbn_10: Optional[str] = None
    isbn_13: Optional[str] = None
    metadata_details: dict[str, object] = field(default_factory=dict)

    @property
    def remote_ids(self) -> dict[str, str]:
        identifiers = {"asin": self.asin}
        if self.isbn_10:
            identifiers["isbn_10"] = self.isbn_10
        if self.isbn_13:
            identifiers["isbn_13"] = self.isbn_13
        return identifiers


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        normalized = normalize_text(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return result


def search_amazon(query: str, *, limit: int = 5) -> list[AmazonCandidate]:
    html = request_amazon_html("/s", params={"k": query, "i": "stripbooks"})
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[AmazonCandidate] = []
    seen_asins: set[str] = set()
    for item in soup.select('[data-component-type="s-search-result"][data-asin]'):
        raw_asin = item.get("data-asin")
        asin = raw_asin.strip() if isinstance(raw_asin, str) else ""
        title_element = item.select_one("h2 a span, h2 span")
        link_element = item.select_one("h2 a[href]")
        if not asin or asin in seen_asins or title_element is None:
            continue

        title = " ".join(title_element.get_text(" ", strip=True).split())
        normalized_title = normalize_text(title)
        if not normalized_title or any(noise in normalized_title for noise in ("summary study guide", "books set", "box set")):
            continue

        authors: list[str] = []
        for byline in item.select(".a-row.a-size-base.a-color-secondary a, .a-row.a-size-base a.a-link-normal"):
            name = _BYLINE_NOISE_RE.sub("", byline.get_text(" ", strip=True)).strip(" ,")
            if name and not re.fullmatch(r"(?:paperback|hardcover|kindle|audible|audio cd)", name, re.IGNORECASE):
                authors.append(name)

        href = link_element.get("href") if link_element is not None else f"/dp/{asin}"
        candidates.append(
            AmazonCandidate(
                asin=asin,
                title=title,
                authors=_dedupe(authors),
                url=urljoin(amazon_base_url(), str(href)),
                categories=[],
            )
        )
        seen_asins.add(asin)
        if len(candidates) >= limit:
            break
    return candidates


def enrich_amazon_candidate(candidate: AmazonCandidate) -> AmazonCandidate:
    html = request_amazon_html(f"/dp/{candidate.asin}")
    if not html:
        return candidate

    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    title_element = soup.select_one("#productTitle")
    title = title_element.get_text(" ", strip=True) if title_element is not None else candidate.title

    authors = [
        _BYLINE_NOISE_RE.sub("", element.get_text(" ", strip=True)).strip(" ,")
        for element in soup.select("#bylineInfo .author a, #bylineInfo_feature_div .author a")
    ]
    authors = _dedupe(authors) or candidate.authors

    categories = _dedupe(
        [
            element.get_text(" ", strip=True).replace("(Books)", "").strip()
            for element in soup.select("#detailBullets_feature_div .zg_hrsr a, #wayfinding-breadcrumbs_feature_div a")
        ]
    )
    isbn_10_match = _ISBN_10_RE.search(page_text)
    isbn_13_match = _ISBN_13_RE.search(page_text)
    isbn_10 = clean_isbn(isbn_10_match.group(1)) if isbn_10_match else ""
    isbn_13 = clean_isbn(isbn_13_match.group(1)) if isbn_13_match else ""
    description_element = soup.select_one(
        "[data-a-expander-name='book_description_expander'] .a-expander-content, "
        "#bookDescription_feature_div noscript, .product-description"
    )
    publisher_element = soup.select_one("#rpi-attribute-book_details-publisher .rpi-attribute-value span")
    publication_element = soup.select_one("#rpi-attribute-book_details-publication_date .rpi-attribute-value span")
    language_element = soup.select_one("#rpi-attribute-language .rpi-attribute-value span")
    cover_element = soup.select_one("#landingImage, #imgBlkFront")
    page_match = _PAGE_COUNT_RE.search(page_text)
    rating_match = _RATING_RE.search(page_text)
    review_match = _REVIEW_COUNT_RE.search(page_text)
    inferred_series, inferred_series_index = infer_series_metadata(title or candidate.title)
    metadata_details: dict[str, object] = {
        key: value
        for key, value in {
            "description": description_element.get_text(" ", strip=True) if description_element else None,
            "publisher": publisher_element.get_text(" ", strip=True) if publisher_element else None,
            "published_date": publication_element.get_text(" ", strip=True) if publication_element else None,
            "language": language_element.get_text(" ", strip=True) if language_element else None,
            "page_count": int(page_match.group(1)) if page_match else None,
            "cover_url": cover_element.get("src") if cover_element else None,
            "amazon_rating": float(rating_match.group(1).replace(",", ".")) if rating_match else None,
            "amazon_review_count": int(review_match.group(1).replace(",", "")) if review_match else None,
            "series": inferred_series,
            "series_index": inferred_series_index,
        }.items()
        if value not in {None, ""}
    }

    return replace(
        candidate,
        title=title or candidate.title,
        authors=authors,
        categories=categories,
        isbn_10=isbn_10 or candidate.isbn_10,
        isbn_13=isbn_13 or candidate.isbn_13,
        metadata_details=metadata_details,
    )
