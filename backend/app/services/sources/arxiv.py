from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET


ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _entry_to_paper(entry: ET.Element) -> dict[str, object]:
    raw_id = _clean_text(entry.findtext(f"{ATOM}id"))
    arxiv_id = raw_id.rstrip("/").split("/")[-1]
    authors = [_clean_text(author.findtext(f"{ATOM}name")) for author in entry.findall(f"{ATOM}author")]
    categories = [item.attrib.get("term", "") for item in entry.findall(f"{ATOM}category") if item.attrib.get("term")]
    pdf_url = ""
    arxiv_url = raw_id
    for link in entry.findall(f"{ATOM}link"):
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", "")
        if link.attrib.get("rel") == "alternate":
            arxiv_url = link.attrib.get("href", arxiv_url)
    doi = _clean_text(entry.findtext(f"{ARXIV}doi")) or None
    published = _clean_text(entry.findtext(f"{ATOM}published"))[:10] or datetime.utcnow().date().isoformat()
    updated = _clean_text(entry.findtext(f"{ATOM}updated"))[:10]
    return {
        "arxiv_id": arxiv_id,
        "source": "arxiv",
        "source_url": arxiv_url or f"https://arxiv.org/abs/{arxiv_id}",
        "title": _clean_text(entry.findtext(f"{ATOM}title")),
        "authors": [author for author in authors if author],
        "abstract": _clean_text(entry.findtext(f"{ATOM}summary")),
        "categories": categories,
        "primary_category": categories[0] if categories else "cs.AI",
        "published_at": published,
        "updated_at": updated,
        "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
        "arxiv_url": arxiv_url or f"https://arxiv.org/abs/{arxiv_id}",
        "doi": doi,
        "processing_status": "pending",
    }


def build_query(categories: list[str], keywords: list[str]) -> str:
    parts: list[str] = []
    if categories:
        parts.append("(" + " OR ".join(f"cat:{item}" for item in categories) + ")")
    for keyword in keywords:
        keyword = keyword.strip()
        if keyword:
            parts.append(f'all:"{keyword}"')
    return " AND ".join(parts) if parts else "cat:cs.AI"


def fetch_arxiv_papers(categories: list[str], keywords: list[str], max_results: int = 10) -> list[dict[str, object]]:
    query = quote_plus(build_query(categories, keywords))
    url = f"{ARXIV_API}?search_query={query}&sortBy=submittedDate&sortOrder=descending&start=0&max_results={max_results}"
    request = Request(url, headers={"User-Agent": "arxiv-paper-wiki-mvp/0.1"})
    with urlopen(request, timeout=12) as response:
        data = response.read()
    root = ET.fromstring(data)
    return [_entry_to_paper(entry) for entry in root.findall(f"{ATOM}entry")]
