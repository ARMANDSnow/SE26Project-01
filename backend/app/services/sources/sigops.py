from __future__ import annotations

from difflib import SequenceMatcher
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from .common import MetadataPage, absolute_links, clean_text


class SigopsTocParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self._in_heading = False
        self._in_link = False
        self._in_author = False
        self._in_paragraph = False

    def _finish_current(self) -> None:
        if self.current and self.current.get("title"):
            self.current["abstract"] = clean_text(" ".join(self.current.pop("abstract_parts", [])))
            self.papers.append(self.current)
        self.current = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "h3":
            self._finish_current()
            self.current = {"title": "", "url": "", "authors": [], "abstract_parts": []}
            self._in_heading = True
        elif tag == "a" and self._in_heading and self.current is not None:
            self.current["url"] = values.get("href", "")
            self._in_link = True
        elif tag == "li" and self.current is not None:
            self._in_author = True
        elif tag == "p" and self.current is not None:
            self._in_paragraph = True

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text or self.current is None:
            return
        if self._in_link:
            self.current["title"] += text
        elif self._in_author:
            self.current["authors"].append(text)
        elif self._in_paragraph:
            self.current["abstract_parts"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3":
            self._in_heading = False
        elif tag == "a":
            self._in_link = False
        elif tag == "li":
            self._in_author = False
        elif tag == "p":
            self._in_paragraph = False

    def close(self) -> None:
        super().close()
        self._finish_current()


class SigopsAcceptedPapersParser(HTMLParser):
    """Parse the ``ul.paperlist`` structure used by recent SOSP sites."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: list[dict[str, Any]] = []
        self.current: dict[str, list[str]] | None = None
        self._in_paper_list = False
        self._in_title = False
        self._in_authors = False

    def _finish_current(self) -> None:
        if self.current is None:
            return
        title = clean_text(" ".join(self.current["title"]))
        author_text = clean_text(" ".join(self.current["authors"]))
        if title:
            self.papers.append(
                {
                    "title": title,
                    "url": "",
                    "authors": [clean_text(item) for item in author_text.split(",") if clean_text(item)],
                    "abstract": "",
                }
            )
        self.current = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "ul" and "paperlist" in values.get("class", "").split():
            self._in_paper_list = True
        elif tag == "li" and self._in_paper_list:
            self._finish_current()
            self.current = {"title": [], "authors": []}
        elif tag == "b" and self.current is not None:
            self._in_title = True
        elif tag == "em" and self.current is not None:
            self._in_authors = True

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = clean_text(data)
        if not text:
            return
        if self._in_title:
            self.current["title"].append(text)
        elif self._in_authors:
            self.current["authors"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "b":
            self._in_title = False
        elif tag == "em":
            self._in_authors = False
        elif tag == "li" and self._in_paper_list:
            self._finish_current()
        elif tag == "ul" and self._in_paper_list:
            self._finish_current()
            self._in_paper_list = False

    def close(self) -> None:
        super().close()
        self._finish_current()


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).casefold()).strip()


def _title_prefix(value: str) -> str:
    return _normalize_title(clean_text(value).split(":", 1)[0])


def _doi_from_acm_url(url: str) -> str:
    match = re.search(r"10\.1145/\d+(?:\.\d+)+", url)
    return match.group(0) if match else ""


def _schedule_candidates(html: str, schedule_url: str) -> list[dict[str, str]]:
    page = MetadataPage()
    page.feed(html)
    candidates: list[dict[str, str]] = []
    for link, label in absolute_links(page, schedule_url):
        title = clean_text(label)
        parsed = urlparse(link)
        doi = _doi_from_acm_url(link) if parsed.hostname == "dl.acm.org" else ""
        if doi:
            candidates.append(
                {
                    "title": title,
                    "source_url": f"https://dl.acm.org/doi/{doi}",
                    "pdf_url": f"https://dl.acm.org/doi/pdf/{doi}?download=true",
                    "doi": doi,
                }
            )
        elif parsed.path.lower().endswith(".pdf"):
            candidates.append(
                {
                    "title": title,
                    "source_url": link,
                    "pdf_url": link,
                    "doi": "",
                }
            )
    return candidates


def _match_candidate(title: str, candidates: list[dict[str, str]]) -> dict[str, str] | None:
    normalized = _normalize_title(title)
    exact = [item for item in candidates if _normalize_title(item["title"]) == normalized]
    if len(exact) == 1:
        return exact[0]

    prefix = _title_prefix(title)
    if len(prefix) >= 3:
        prefix_matches = [item for item in candidates if _title_prefix(item["title"]) == prefix]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

    scored = [
        (SequenceMatcher(None, normalized, _normalize_title(item["title"])).ratio(), item)
        for item in candidates
    ]
    if not scored:
        return None
    score, candidate = max(scored, key=lambda pair: pair[0])
    return candidate if score >= 0.82 else None


def _crossref_candidate(title: str, year: int) -> dict[str, str] | None:
    params = urlencode(
        {
            "query.title": title,
            "filter": f"prefix:10.1145,from-pub-date:{year}-01-01,until-pub-date:{year}-12-31,type:proceedings-article",
            "rows": 5,
            "select": "DOI,title,container-title",
        }
    )
    request = Request(
        f"https://api.crossref.org/works?{params}",
        headers={"User-Agent": "PaperWiki/0.2 (+SOSP DOI lookup)"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            items = json.load(response).get("message", {}).get("items", [])
    except Exception:
        return None

    normalized = _normalize_title(title)
    for item in items:
        containers = item.get("container-title") or []
        titles = item.get("title") or []
        doi = clean_text(item.get("DOI") or "")
        candidate_title = clean_text(titles[0] if titles else "")
        if (
            doi.startswith("10.1145/")
            and any("Operating Systems Principles" in value for value in containers)
            and SequenceMatcher(None, normalized, _normalize_title(candidate_title)).ratio() >= 0.9
        ):
            return {
                "title": candidate_title,
                "source_url": f"https://dl.acm.org/doi/{doi}",
                "pdf_url": f"https://dl.acm.org/doi/pdf/{doi}?download=true",
                "doi": doi,
            }
    return None


def _fetch_crossref_candidates(year: int) -> list[dict[str, str]]:
    params = urlencode(
        {
            "query.container-title": "Symposium on Operating Systems Principles",
            "filter": f"prefix:10.1145,from-pub-date:{year}-01-01,until-pub-date:{year}-12-31,type:proceedings-article",
            "rows": 200,
            "select": "DOI,title,container-title",
        }
    )
    request = Request(
        f"https://api.crossref.org/works?{params}",
        headers={"User-Agent": "PaperWiki/0.2 (+SOSP DOI lookup)"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            items = json.load(response).get("message", {}).get("items", [])
    except Exception:
        return []

    candidates: list[dict[str, str]] = []
    for item in items:
        containers = item.get("container-title") or []
        titles = item.get("title") or []
        doi = clean_text(item.get("DOI") or "")
        title = clean_text(titles[0] if titles else "")
        if doi.startswith("10.1145/") and title and any(
            "Operating Systems Principles" in value for value in containers
        ):
            candidates.append(
                {
                    "title": title,
                    "source_url": f"https://dl.acm.org/doi/{doi}",
                    "pdf_url": f"https://dl.acm.org/doi/pdf/{doi}?download=true",
                    "doi": doi,
                }
            )
    return candidates


def _fetch_schedule_candidates(base_url: str) -> list[dict[str, str]]:
    schedule_url = f"{base_url}/schedule.html"
    request = Request(schedule_url, headers={"User-Agent": "PaperWiki/0.2 (+metadata import)"})
    try:
        with urlopen(request, timeout=15) as response:
            html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return []
    return _schedule_candidates(html, schedule_url)


def fetch_sigops_papers(venue: str, year: int, max_results: int = 10, proceedings_url: str = "") -> list[dict[str, Any]]:
    """Import metadata linked by a SIGOPS proceedings page.

    A caller may provide a specific proceedings URL because historical SIGOPS
    editions do not all share one stable URL pattern.
    """
    venue_code = venue.strip().lower() or "sosp"
    base_url = f"https://sigops.org/s/conferences/{quote(venue_code)}/{year}"
    url = proceedings_url.strip() or f"{base_url}/accepted.html"
    request = Request(url, headers={"User-Agent": "PaperWiki/0.2 (+metadata import)"})
    try:
        with urlopen(request, timeout=15) as response:
            html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as exc:
        if proceedings_url.strip() or exc.code != 404:
            raise
        url = f"{base_url}/toc.html"
        request = Request(url, headers={"User-Agent": "PaperWiki/0.2 (+metadata import)"})
        with urlopen(request, timeout=15) as response:
            html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")

    accepted_parser = SigopsAcceptedPapersParser()
    accepted_parser.feed(html)
    accepted_parser.close()
    parser = SigopsTocParser()
    parser.feed(html)
    parser.close()
    source_items = accepted_parser.papers or parser.papers
    schedule_candidates = _fetch_schedule_candidates(base_url)
    crossref_candidates = _fetch_crossref_candidates(year) if venue_code == "sosp" else []
    papers: list[dict[str, Any]] = []
    for item in source_items[:max_results]:
        title = clean_text(item["title"])
        if not title:
            continue
        candidate = _match_candidate(title, crossref_candidates)
        if candidate is None:
            candidate = _match_candidate(title, schedule_candidates)
        if candidate is None and venue_code == "sosp":
            candidate = _crossref_candidate(title, year)
        detail_url = (
            candidate["source_url"]
            if candidate
            else urljoin(url, item["url"]) if item["url"] else url
        )
        external_id = sha256(title.lower().encode("utf-8")).hexdigest()[:16]
        papers.append(
            {
                "arxiv_id": f"sigops:{venue_code}:{year}:{external_id}",
                "source": "sigops",
                "source_url": detail_url,
                "venue": f"{venue_code.upper()} {year}",
                "title": title,
                "authors": item["authors"],
                "abstract": item["abstract"] or f"Imported from {venue_code.upper()} {year} accepted papers; the official list does not provide an abstract.",
                "categories": ["systems", venue_code],
                "primary_category": venue_code.upper(),
                "published_at": f"{year}-01-01",
                "updated_at": None,
                "pdf_url": candidate["pdf_url"] if candidate else None,
                "arxiv_url": None,
                "doi": candidate["doi"] if candidate and candidate["doi"] else None,
                "processing_status": "pending",
            }
        )
    return papers
