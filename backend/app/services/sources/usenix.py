from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .common import absolute_links, all_meta, clean_text, fetch_page, first_meta


USENIX_BASE = "https://www.usenix.org/conference"


def fetch_usenix_papers(venue: str, year: int, max_results: int = 10) -> list[dict[str, Any]]:
    venue_code = venue.strip().lower()
    if venue_code not in {"osdi", "atc"}:
        raise ValueError("USENIX 暂仅支持 OSDI 和 ATC")
    slug = f"{venue_code}{year % 100:02d}"
    sessions_url = f"{USENIX_BASE}/{slug}/technical-sessions"
    listing = fetch_page(sessions_url)
    detail_urls: list[str] = []
    for url, _ in absolute_links(listing, sessions_url):
        if f"/conference/{slug}/presentation/" in url and url not in detail_urls:
            detail_urls.append(url)
    papers: list[dict[str, Any]] = []
    for url in detail_urls[:max_results]:
        paper = _detail_to_paper(fetch_page(url), url, venue_code.upper(), year)
        if paper is not None:
            papers.append(paper)
    return papers


def _detail_to_paper(page: Any, url: str, venue: str, year: int) -> dict[str, Any] | None:
    title = clean_text(first_meta(page, "citation_title", "dc.title"))
    authors = all_meta(page, "citation_author", "dc.creator")
    abstract = clean_text(first_meta(page, "citation_abstract", "description", "dc.description"))
    pdf_url = first_meta(page, "citation_pdf_url")
    if not pdf_url:
        for link, label in absolute_links(page, url):
            if link.lower().endswith(".pdf") and ("pdf" in label.lower() or not pdf_url):
                pdf_url = link
                break
    if not title:
        bibtex = " ".join(page.text)
        title_match = re.search(r"title\s*=\s*\{(.+?)\}\s*,", bibtex, re.IGNORECASE)
        author_match = re.search(r"author\s*=\s*\{(.+?)\}\s*,", bibtex, re.IGNORECASE)
        title = clean_text(title_match.group(1)) if title_match else ""
        if not authors and author_match:
            authors = [clean_text(item) for item in re.split(r"\s+and\s+", author_match.group(1))]
    title = clean_text(title.replace("{", "").replace("}", ""))
    if not title:
        return None
    external_id = url.rstrip("/").split("/")[-1]
    return {
        "arxiv_id": f"usenix:{venue.lower()}:{year}:{external_id}",
        "source": "usenix",
        "source_url": url,
        "venue": f"{venue} {year}",
        "title": title,
        "authors": authors,
        "abstract": abstract or f"Imported from {venue} {year} proceedings.",
        "categories": ["systems", venue.lower()],
        "primary_category": venue,
        "published_at": f"{year}-01-01" if year else datetime.utcnow().date().isoformat(),
        "updated_at": None,
        "pdf_url": pdf_url or None,
        "arxiv_url": None,
        "doi": first_meta(page, "citation_doi"),
        "processing_status": "pending",
    }
