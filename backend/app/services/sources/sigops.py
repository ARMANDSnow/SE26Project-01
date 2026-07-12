from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .common import clean_text


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
    papers: list[dict[str, Any]] = []
    for item in source_items[:max_results]:
        title = clean_text(item["title"])
        detail_url = urljoin(url, item["url"]) if item["url"] else url
        if not title:
            continue
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
                "pdf_url": None,
                "arxiv_url": None,
                "doi": None,
                "processing_status": "pending",
            }
        )
    return papers
