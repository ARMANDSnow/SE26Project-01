from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from ...models import PaperCandidate, PaperSource
from ..research_contracts import canonical_arxiv_id


ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _entry_to_paper(entry: ET.Element) -> PaperCandidate:
    raw_id = _clean_text(entry.findtext(f"{ATOM}id"))
    source_id = canonical_arxiv_id(raw_id)
    authors = [_clean_text(author.findtext(f"{ATOM}name")) for author in entry.findall(f"{ATOM}author")]
    categories = [item.attrib.get("term", "") for item in entry.findall(f"{ATOM}category") if item.attrib.get("term")]
    pdf_url = ""
    landing_url = raw_id
    for link in entry.findall(f"{ATOM}link"):
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", "").replace("http://", "https://", 1)
        if link.attrib.get("rel") == "alternate":
            landing_url = link.attrib.get("href", landing_url).replace("http://", "https://", 1)
    published = _clean_text(entry.findtext(f"{ATOM}published"))[:10] or datetime.utcnow().date().isoformat()
    updated = _clean_text(entry.findtext(f"{ATOM}updated"))[:10]
    return PaperCandidate(
        source=PaperSource.ARXIV,
        source_id=source_id,
        source_url=(landing_url or f"https://arxiv.org/abs/{source_id}").replace("http://", "https://", 1),
        title=_clean_text(entry.findtext(f"{ATOM}title")),
        authors=tuple(author for author in authors if author),
        abstract=_clean_text(entry.findtext(f"{ATOM}summary")),
        categories=tuple(categories),
        primary_category=categories[0] if categories else "cs.AI",
        published_at=published,
        updated_at=updated or None,
        pdf_url=pdf_url or f"https://arxiv.org/pdf/{source_id}",
    )


def build_query(
    categories: list[str],
    keywords: list[str],
    match_any: bool = False,
    require_first: bool = False,
) -> str:
    parts: list[str] = []
    if categories:
        parts.append("(" + " OR ".join(f"cat:{item}" for item in categories) + ")")
    keyword_parts = [f'all:"{keyword.strip()}"' for keyword in keywords if keyword.strip()]
    if keyword_parts:
        if require_first and len(keyword_parts) > 1:
            parts.extend([keyword_parts[0], "(" + " OR ".join(keyword_parts[1:]) + ")"])
        elif match_any:
            parts.append("(" + " OR ".join(keyword_parts) + ")")
        else:
            parts.extend(keyword_parts)
    return " AND ".join(parts) if parts else "cat:cs.AI"


def fetch_arxiv_papers(
    categories: list[str],
    keywords: list[str],
    max_results: int = 10,
    match_any: bool = False,
    require_first: bool = False,
) -> list[PaperCandidate]:
    query = quote_plus(
        build_query(
            categories,
            keywords,
            match_any=match_any,
            require_first=require_first,
        )
    )
    url = f"{ARXIV_API}?search_query={query}&sortBy=submittedDate&sortOrder=descending&start=0&max_results={max_results}"
    request = Request(url, headers={"User-Agent": "arxiv-paper-wiki-mvp/0.1"})
    with urlopen(request, timeout=12) as response:
        data = response.read()
    root = ET.fromstring(data)
    return [_entry_to_paper(entry) for entry in root.findall(f"{ATOM}entry")]
