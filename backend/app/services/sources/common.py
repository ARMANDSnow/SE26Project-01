from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class MetadataPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._link_text: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            value = values.get("content", "").strip()
            if key and value:
                self.meta.setdefault(key, []).append(value)
        elif tag == "a":
            self._href = values.get("href", "")
            self._link_text = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.text.append(cleaned)
            if self._href:
                self._link_text.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._link_text)))
            self._href = ""
            self._link_text = []


def fetch_page(url: str) -> MetadataPage:
    request = Request(url, headers={"User-Agent": "PaperWiki/0.2 (+metadata import)"})
    with urlopen(request, timeout=15) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    page = MetadataPage()
    page.feed(body)
    return page


def first_meta(page: MetadataPage, *names: str) -> str:
    for name in names:
        values = page.meta.get(name.lower())
        if values:
            return values[0].strip()
    return ""


def all_meta(page: MetadataPage, *names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        values.extend(page.meta.get(name.lower(), []))
    return [item.strip() for item in values if item.strip()]


def absolute_links(page: MetadataPage, base_url: str) -> list[tuple[str, str]]:
    return [(urljoin(base_url, href), text.strip()) for href, text in page.links if href]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()
