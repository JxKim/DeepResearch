import asyncio
import re
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from loguru import logger

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_MAX_CHARS = 12000
USER_AGENT = "DeepResearchBot/0.1 (+https://example.local/research)"


async def read_web_page(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    """读取网页正文和基础元数据。

    输入为 URL；输出为标题、发布时间线索、正文摘要和读取状态。该工具只做轻量解析，
    不对网页内容做事实判断。
    """

    normalized_url = url.strip()
    if not normalized_url.startswith(("http://", "https://")):
        return {
            "status": "error",
            "url": url,
            "title": None,
            "published_at": None,
            "content": "",
            "error": "仅支持 http 或 https URL",
        }

    try:
        html, final_url, content_type = await asyncio.to_thread(_fetch_html, normalized_url)
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, OSError) as exc:
        logger.warning("网页读取失败，url={}, error={}", normalized_url, exc)
        return {
            "status": "error",
            "url": normalized_url,
            "title": None,
            "published_at": None,
            "content": "",
            "error": str(exc),
        }

    parser = _ReadableHtmlParser()
    parser.feed(html)
    content = _normalize_space(" ".join(parser.text_parts))
    limited_content = content[: max(500, min(max_chars, 30000))]
    title = parser.title or _extract_title(html)
    published_at = parser.published_at or _extract_published_at(html)

    logger.info("网页读取完成，url={}, chars={}", final_url, len(limited_content))
    return {
        "status": "ok",
        "url": final_url,
        "title": title,
        "published_at": published_at,
        "content_type": content_type,
        "content": limited_content,
        "truncated": len(content) > len(limited_content),
        "source_type": "public_web",
    }


def _fetch_html(url: str) -> tuple[str, str, str | None]:
    request = Request(url=url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type")
        encoding = response.headers.get_content_charset() or "utf-8"
        return raw.decode(encoding, errors="replace"), response.geturl(), content_type


class _ReadableHtmlParser(HTMLParser):
    """轻量 HTML 正文提取器，跳过脚本、样式和导航噪音标签。"""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.title: str | None = None
        self.published_at: str | None = None
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            self._handle_meta(attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        normalized = _normalize_space(data)
        if not normalized:
            return
        if self._in_title:
            self.title = normalized
            return
        if self._ignored_depth == 0:
            self.text_parts.append(normalized)

    def _handle_meta(self, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        meta_key = (attr_map.get("property") or attr_map.get("name") or "").lower()
        content = attr_map.get("content")
        if meta_key in {"article:published_time", "datepublished", "pubdate", "date"} and content:
            self.published_at = content


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _normalize_space(re.sub(r"<[^>]+>", " ", match.group(1)))


def _extract_published_at(html: str) -> str | None:
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateModified"\s*:\s*"([^"]+)"',
        r"(\d{4}-\d{2}-\d{2}(?:[T ][0-9:]+(?:Z|[+-]\d{2}:?\d{2})?)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
