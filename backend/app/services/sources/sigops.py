from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin

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


def fetch_sigops_papers(venue: str, year: int, max_results: int = 10, proceedings_url: str = "") -> list[dict[str, Any]]:
    """Import metadata linked by a SIGOPS proceedings page.

    A caller may provide a specific proceedings URL because historical SIGOPS
    editions do not all share one stable URL pattern.
    """
    venue_code = venue.strip().lower() or "sosp"
    url = proceedings_url.strip() or f"https://sigops.org/s/conferences/{quote(venue_code)}/{year}/toc.html"
    parser = SigopsTocParser()
    from urllib.request import Request, urlopen
    request = Request(url, headers={"User-Agent": "PaperWiki/0.2 (+metadata import)"})
    with urlopen(request, timeout=15) as response:
        parser.feed(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    parser.close()
    papers: list[dict[str, Any]] = []
    for item in parser.papers[:max_results]:
        title = clean_text(item["title"])
        detail_url = urljoin(url, item["url"])
        if not title or not detail_url:
            continue
        external_id = detail_url.rstrip("/").split("/")[-1]
        papers.append(
            {
                "arxiv_id": f"sigops:{venue_code}:{year}:{external_id}",
                "source": "sigops",
                "source_url": detail_url,
                "venue": f"{venue_code.upper()} {year}",
                "title": title,
                "authors": item["authors"],
                "abstract": item["abstract"] or f"Imported from {venue_code.upper()} {year}.",
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
