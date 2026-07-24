from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import gzip
import re
import tarfile
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote
from urllib.request import Request

from ..models import PaperRecord, PaperSource
from .http_safety import UnsafeUrlError, open_trusted_url


ARXIV_SOURCE_TIMEOUT_SECONDS = 20
ARXIV_HTML_TIMEOUT_SECONDS = 4
ARXIV_SOURCE_MAX_BYTES = 80 * 1024 * 1024
ARXIV_SOURCE_MAX_TEX_BYTES = 8 * 1024 * 1024
ARXIV_HTML_MAX_BYTES = 16 * 1024 * 1024
ARXIV_MIN_STRUCTURED_TEXT_CHARS = 4_000
ARXIV_LATEX_PARSER_NAME = "arxiv_latex"
ARXIV_LATEX_PARSER_VERSION = "arxiv-latex-source-v1"
ARXIV_HTML_PARSER_NAME = "arxiv_html"
ARXIV_HTML_PARSER_VERSION = "arxiv-html-source-v1"
ARXIV_SOURCE_ALLOWED_HOSTS = {"arxiv.org", "export.arxiv.org"}
ARXIV_HTML_ALLOWED_HOSTS = {"arxiv.org", "ar5iv.labs.arxiv.org"}
_ARXIV_ID_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
_INCLUDE_PATTERN = re.compile(r"\\(?:input|include)\{([^{}]+)\}")
_SECTION_PATTERN = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\{([^{}]+)\}")
_FORMAT_COMMANDS = (
    "emph",
    "textbf",
    "textit",
    "textrm",
    "textsf",
    "texttt",
    "textsc",
    "underline",
    "mathbf",
    "mathrm",
    "mathit",
    "mathsf",
    "mathtt",
)


class ArxivSourceError(RuntimeError):
    pass


class ArxivSourceUnavailable(ArxivSourceError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedSourceDocument:
    parser_name: str
    parser_version: str
    source_hash: str
    markdown: str
    structure: dict[str, Any]


def arxiv_source_cache_key(paper: PaperRecord) -> str | None:
    if paper.source != PaperSource.ARXIV:
        return None
    source_id = _normalize_arxiv_id(paper.source_id)
    if source_id is None:
        return None
    identity = f"{ARXIV_LATEX_PARSER_VERSION}:{source_id}:{paper.updated_at or ''}"
    return sha256(identity.encode("utf-8")).hexdigest()


def parse_arxiv_structured_source(paper: PaperRecord) -> ParsedSourceDocument | None:
    source_id = _normalize_arxiv_id(paper.source_id)
    if paper.source != PaperSource.ARXIV or source_id is None:
        return None
    errors: list[Exception] = []

    try:
        document = parse_arxiv_html_source(paper)
    except ArxivSourceError as exc:
        errors.append(exc)
    else:
        if document is not None:
            return document

    try:
        if arxiv_eprint_returns_pdf(source_id):
            return None
    except ArxivSourceError:
        return None

    try:
        document = parse_arxiv_latex_source(paper)
    except ArxivSourceUnavailable:
        return None
    except ArxivSourceError as exc:
        errors.append(exc)
    else:
        if document is not None:
            return document
    if errors:
        message = "; ".join(str(error) for error in errors)
        raise ArxivSourceError(message)
    return None


def arxiv_eprint_returns_pdf(source_id: str) -> bool:
    normalized = _normalize_arxiv_id(source_id)
    if normalized is None:
        raise ArxivSourceError("invalid arXiv source id")
    request = Request(
        _arxiv_eprint_url(normalized),
        headers={
            "Accept": "application/e-print,application/gzip,application/x-tar,*/*;q=0.1",
            "User-Agent": "PaperWiki/0.4 (+arXiv source resolver)",
        },
    )
    try:
        with open_trusted_url(
            request,
            allowed_hosts=ARXIV_SOURCE_ALLOWED_HOSTS,
            timeout=ARXIV_HTML_TIMEOUT_SECONDS,
        ) as response:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            first = response.read(8192)
            return first.startswith(b"%PDF") or "application/pdf" in content_type
    except (OSError, TimeoutError, UnsafeUrlError) as exc:
        raise ArxivSourceError(f"arXiv source probe failed: {exc}") from exc


def parse_arxiv_latex_source(paper: PaperRecord) -> ParsedSourceDocument | None:
    source_hash = arxiv_source_cache_key(paper)
    source_id = _normalize_arxiv_id(paper.source_id)
    if source_hash is None or source_id is None:
        return None

    source_bytes = download_arxiv_source(source_id)
    tex_files = extract_tex_files(source_bytes)
    if not tex_files:
        return None

    main_path = select_main_tex_file(tex_files)
    if main_path is None:
        return None

    expanded = expand_latex_inputs(tex_files, main_path)
    markdown = latex_to_markdown(expanded).strip()
    if not markdown:
        return None

    structure: dict[str, Any] = {
        "source": "arxiv_eprint",
        "source_id": source_id,
        "source_url": f"https://arxiv.org/e-print/{source_id}",
        "source_digest": sha256(source_bytes).hexdigest(),
        "source_bytes": len(source_bytes),
        "main_tex": main_path,
        "tex_files": sorted(tex_files),
    }
    return ParsedSourceDocument(
        parser_name=ARXIV_LATEX_PARSER_NAME,
        parser_version=ARXIV_LATEX_PARSER_VERSION,
        source_hash=source_hash,
        markdown=markdown,
        structure=structure,
    )


def parse_arxiv_html_source(paper: PaperRecord) -> ParsedSourceDocument | None:
    source_id = _normalize_arxiv_id(paper.source_id)
    if paper.source != PaperSource.ARXIV or source_id is None:
        return None

    errors: list[Exception] = []
    for url in _arxiv_html_candidates(source_id):
        try:
            html = download_arxiv_html(url)
        except ArxivSourceError as exc:
            errors.append(exc)
            continue
        markdown = html_to_markdown(html).strip()
        if not _looks_like_fulltext_html(html, markdown):
            continue
        digest = sha256(html.encode("utf-8")).hexdigest()
        structure: dict[str, Any] = {
            "source": "arxiv_html",
            "source_id": source_id,
            "source_url": url,
            "source_digest": digest,
            "source_bytes": len(html.encode("utf-8")),
        }
        return ParsedSourceDocument(
            parser_name=ARXIV_HTML_PARSER_NAME,
            parser_version=ARXIV_HTML_PARSER_VERSION,
            source_hash=sha256(f"{ARXIV_HTML_PARSER_VERSION}:{source_id}:{url}:{digest}".encode("utf-8")).hexdigest(),
            markdown=markdown,
            structure=structure,
        )
    if errors:
        message = "; ".join(str(error) for error in errors)
        raise ArxivSourceError(f"arXiv HTML download failed: {message}")
    return None


def download_arxiv_source(source_id: str) -> bytes:
    normalized = _normalize_arxiv_id(source_id)
    if normalized is None:
        raise ArxivSourceError("invalid arXiv source id")
    request = Request(
        _arxiv_eprint_url(normalized),
        headers={
            "Accept": "application/e-print,application/gzip,application/x-tar,*/*;q=0.1",
            "User-Agent": "PaperWiki/0.4 (+arXiv source resolver)",
        },
    )
    try:
        with open_trusted_url(
            request,
            allowed_hosts=ARXIV_SOURCE_ALLOWED_HOSTS,
            timeout=ARXIV_SOURCE_TIMEOUT_SECONDS,
        ) as response:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            first = response.read(8192)
            if first.startswith(b"%PDF") or "application/pdf" in content_type:
                raise ArxivSourceUnavailable("arXiv e-print returned PDF instead of TeX source")
            chunks: list[bytes] = [first] if first else []
            total = len(first)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > ARXIV_SOURCE_MAX_BYTES:
                    raise ArxivSourceError("arXiv source package is too large")
                chunks.append(chunk)
            return b"".join(chunks)
    except (OSError, TimeoutError, UnsafeUrlError) as exc:
        raise ArxivSourceError(f"arXiv source download failed: {exc}") from exc


def download_arxiv_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "User-Agent": "PaperWiki/0.4 (+arXiv HTML resolver)",
        },
    )
    try:
        with open_trusted_url(
            request,
            allowed_hosts=ARXIV_HTML_ALLOWED_HOSTS,
            timeout=ARXIV_HTML_TIMEOUT_SECONDS,
        ) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > ARXIV_HTML_MAX_BYTES:
                    raise ArxivSourceError("arXiv HTML document is too large")
                chunks.append(chunk)
            return _decode_tex(b"".join(chunks))
    except (OSError, TimeoutError, UnsafeUrlError) as exc:
        raise ArxivSourceError(f"arXiv HTML download failed: {exc}") from exc


def extract_tex_files(source_bytes: bytes) -> dict[str, str]:
    tex_files = _extract_tar_tex_files(source_bytes)
    if tex_files:
        return tex_files

    try:
        decompressed = gzip.decompress(source_bytes)
    except OSError:
        decompressed = b""

    if decompressed:
        tex_files = _extract_tar_tex_files(decompressed)
        if tex_files:
            return tex_files
        decoded = _decode_tex(decompressed)
        if "\\begin{document}" in decoded or "\\documentclass" in decoded:
            return {"main.tex": decoded}

    decoded = _decode_tex(source_bytes)
    if "\\begin{document}" in decoded or "\\documentclass" in decoded:
        return {"main.tex": decoded}
    return {}


def select_main_tex_file(tex_files: dict[str, str]) -> str | None:
    best_path: str | None = None
    best_score = -1
    for path, text in tex_files.items():
        lowered_name = PurePosixPath(path).name.lower()
        score = min(len(text), 100_000)
        if "\\documentclass" in text:
            score += 1_000_000
        if "\\begin{document}" in text:
            score += 500_000
        if "\\title" in text:
            score += 20_000
        if "\\begin{abstract}" in text:
            score += 20_000
        if lowered_name in {"main.tex", "paper.tex", "ms.tex", "article.tex"}:
            score += 10_000
        if score > best_score:
            best_score = score
            best_path = path
    return best_path


def expand_latex_inputs(tex_files: dict[str, str], main_path: str) -> str:
    normalized_files = {_normalize_archive_path(path): text for path, text in tex_files.items()}

    def expand(path: str, seen: frozenset[str], depth: int) -> str:
        text = normalized_files.get(path, "")
        if depth > 12:
            return text
        base = PurePosixPath(path).parent

        def replace(match: re.Match[str]) -> str:
            include_name = match.group(1).strip()
            include_path = _resolve_include_path(base, include_name)
            if include_path in seen:
                return ""
            if include_path not in normalized_files:
                return ""
            return expand(include_path, seen | {include_path}, depth + 1)

        return _INCLUDE_PATTERN.sub(replace, text)

    normalized_main = _normalize_archive_path(main_path)
    return expand(normalized_main, frozenset({normalized_main}), 0)


def latex_to_markdown(source: str) -> str:
    text = _strip_latex_comments(source)
    title = _latex_group_to_text(_extract_command_argument(text, "title") or "")
    body = _document_body(text)
    if title:
        body = re.sub(r"\\maketitle\b", f"# {title}\n\n", body, count=1)
    else:
        body = re.sub(r"\\maketitle\b", "", body)
    body = _convert_abstract(body)
    body = _convert_sections(body)
    body = _strip_latex_noise(body)
    return _normalize_markdown(body)


def html_to_markdown(source: str) -> str:
    parser = _StructuredHtmlToMarkdown()
    parser.feed(source)
    parser.close()
    return _normalize_markdown(parser.markdown())


def _normalize_arxiv_id(source_id: str) -> str | None:
    candidate = source_id.strip().rstrip("/")
    if not candidate or not _ARXIV_ID_PATTERN.fullmatch(candidate):
        return None
    return candidate


def _arxiv_html_candidates(source_id: str) -> list[str]:
    versionless = re.sub(r"v\d+$", "", source_id)
    return [f"https://ar5iv.labs.arxiv.org/html/{quote(versionless, safe='/')}"]


def _arxiv_eprint_url(source_id: str) -> str:
    return f"https://arxiv.org/e-print/{quote(source_id, safe='/')}"


def _looks_like_fulltext_html(source: str, markdown: str) -> bool:
    if len(markdown) < ARXIV_MIN_STRUCTURED_TEXT_CHARS:
        return False
    lowered = source.lower()
    if any(marker in lowered for marker in ("ltx_document", "ltx_article", "ltx_para", "ltx_section")):
        return True
    return False


def _extract_tar_tex_files(source_bytes: bytes) -> dict[str, str]:
    try:
        archive = tarfile.open(fileobj=BytesIO(source_bytes), mode="r:*")
    except tarfile.TarError:
        return {}
    tex_files: dict[str, str] = {}
    with archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".tex"):
                continue
            path = _normalize_archive_path(member.name)
            if not path or member.size > ARXIV_SOURCE_MAX_TEX_BYTES:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read(ARXIV_SOURCE_MAX_TEX_BYTES + 1)
            if len(data) > ARXIV_SOURCE_MAX_TEX_BYTES:
                continue
            tex_files[path] = _decode_tex(data)
    return tex_files


def _decode_tex(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_archive_path(path: str) -> str:
    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return ""
    return candidate.as_posix()


def _resolve_include_path(base: PurePosixPath, include_name: str) -> str:
    candidate = PurePosixPath(include_name.replace("\\", "/"))
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".tex")
    if not candidate.is_absolute():
        candidate = base / candidate
    return _normalize_archive_path(candidate.as_posix())


def _strip_latex_comments(text: str) -> str:
    stripped_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cut_at = len(line)
        for index, char in enumerate(line):
            if char == "%" and not _is_escaped(line, index):
                cut_at = index
                break
        stripped_lines.append(line[:cut_at])
    return "\n".join(stripped_lines)


def _is_escaped(text: str, index: int) -> bool:
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def _extract_command_argument(text: str, command: str) -> str | None:
    match = re.search(rf"\\{command}\s*\{{", text)
    if match is None:
        return None
    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{" and not _is_escaped(text, index):
            depth += 1
        elif char == "}" and not _is_escaped(text, index):
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return None


def _document_body(text: str) -> str:
    begin = re.search(r"\\begin\{document\}", text)
    if begin is None:
        return text
    end = re.search(r"\\end\{document\}", text[begin.end() :])
    if end is None:
        return text[begin.end() :]
    return text[begin.end() : begin.end() + end.start()]


def _convert_abstract(text: str) -> str:
    return re.sub(
        r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
        lambda match: "## Abstract\n\n" + match.group(1).strip() + "\n\n",
        text,
        flags=re.DOTALL,
    )


def _convert_sections(text: str) -> str:
    levels = {
        "part": 1,
        "chapter": 1,
        "section": 2,
        "subsection": 3,
        "subsubsection": 4,
        "paragraph": 5,
    }

    def replace(match: re.Match[str]) -> str:
        level = levels[match.group(1)]
        title = _latex_group_to_text(match.group(2)).strip()
        return f"\n\n{'#' * level} {title}\n\n"

    return _SECTION_PATTERN.sub(replace, text)


def _strip_latex_noise(text: str) -> str:
    text = re.sub(r"\\bibliographystyle\{[^{}]*\}", "", text)
    text = re.sub(r"\\bibliography\{[^{}]*\}", "", text)
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:cite|citep|citet|citealp|ref|eqref)\*?(?:\[[^\]]*\])?\{[^{}]*\}", "[ref]", text)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\url\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\begin\{[^{}]*\}", "\n\n", text)
    text = re.sub(r"\\end\{[^{}]*\}", "\n\n", text)
    text = _unwrap_formatting_commands(text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace(r"\%", "%").replace(r"\_", "_").replace(r"\&", "&")
    text = text.replace(r"\#", "#").replace(r"\$", "$").replace(r"\{", "{").replace(r"\}", "}")
    text = text.replace("~", " ")
    text = text.replace("``", '"').replace("''", '"')
    return text.replace("{", "").replace("}", "")


def _unwrap_formatting_commands(text: str) -> str:
    command_pattern = "|".join(re.escape(command) for command in _FORMAT_COMMANDS)
    pattern = re.compile(rf"\\(?:{command_pattern})\{{([^{{}}]*)\}}")
    previous = None
    current = text
    while previous != current:
        previous = current
        current = pattern.sub(r"\1", current)
    return current


def _latex_group_to_text(text: str) -> str:
    return _normalize_markdown(_strip_latex_noise(text))


def _normalize_markdown(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    output: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    return "\n".join(output).strip()


class _StructuredHtmlToMarkdown(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "section",
        "div",
        "p",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "blockquote",
        "pre",
    }
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "math", "head", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._heading_level: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._append_block(f"{'#' * self._heading_level} ")
            return
        if tag == "br":
            self._parts.append("\n")
            return
        if tag == "li":
            self._append_block("- ")
            return
        if tag in self._BLOCK_TAGS:
            self._append_block("")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS or tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._append_block("")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._parts and not self._parts[-1].endswith(("\n", " ", "# ", "- ")):
            self._parts.append(" ")
        self._parts.append(text)

    def markdown(self) -> str:
        return "".join(self._parts)

    def _append_block(self, text: str) -> None:
        if self._parts and not self._parts[-1].endswith("\n\n"):
            self._parts.append("\n\n")
        if text:
            self._parts.append(text)
