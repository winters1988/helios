"""News article collector - crawls Korean news RSS feeds and web pages."""

import re
import hashlib
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup


@dataclass
class Article:
    id: str
    title: str
    content: str
    summary: str
    url: str
    source: str
    author: Optional[str]
    published: Optional[str]
    collected_at: str
    categories: list[str]


# Korean news RSS feeds
RSS_SOURCES = {
    "연합뉴스": {
        "전체":      "https://www.yna.co.kr/rss/news.xml",
        "정치":      "https://www.yna.co.kr/rss/politics.xml",
        "경제":      "https://www.yna.co.kr/rss/economy.xml",
        "사회":      "https://www.yna.co.kr/rss/society.xml",
        "국제":      "https://www.yna.co.kr/rss/international.xml",
        "IT과학":    "https://www.yna.co.kr/rss/science.xml",
    },
    "조선일보": {
        "전체":      "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    },
    "한겨레": {
        "전체":      "https://www.hani.co.kr/rss/",
    },
    "KBS": {
        "전체":      "https://world.kbs.co.kr/rss/rss_news.htm?lang=k",
    },
    "SBS": {
        "전체":      "https://news.sbs.co.kr/news/SSection.do?action=rss",
    },
    "MBC": {
        "전체":      "https://imnews.imbc.com/rss/news/news_00.xml",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def _generate_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _clean_html(html: str) -> str:
    """Remove HTML tags and clean up whitespace."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "iframe", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_article_body(url: str) -> str:
    """Fetch and extract main article text from URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "iframe", "nav", "footer",
                         "header", "aside", "figure", "figcaption"]):
            tag.decompose()

        # Try common Korean news article selectors
        selectors = [
            "article",
            ".article_body", ".article-body", ".article_text",
            ".news_body", ".news-body", ".newsview",
            "#articleBodyContents", "#articeBody", "#newsEndContents",
            ".story-news", ".article_view", ".view_con",
            "#textBody", ".text_area", "#news_body_area",
            ".article-body-content", ".article_content",
            "#article-view-content-div", ".news_cnt_detail_wrap",
            "#newsct_article", ".content_text",
        ]

        for selector in selectors:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                return _clean_html(str(el))

        # Fallback: find largest text block
        paragraphs = soup.find_all("p")
        if paragraphs:
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
            if texts:
                return "\n".join(texts)

        return ""
    except Exception:
        return ""


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def collect_from_rss(source_name: str, category: str, feed_url: str,
                     fetch_body: bool = True, max_articles: int = 20) -> list[Article]:
    """Collect articles from a single RSS feed."""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
    except Exception:
        return articles

    for entry in feed.entries[:max_articles]:
        url = entry.get("link", "")
        if not url:
            continue

        title = entry.get("title", "").strip()
        summary_raw = entry.get("summary", "") or entry.get("description", "")
        summary = _clean_html(summary_raw) if summary_raw else ""

        # Get full body if requested
        content = ""
        if fetch_body:
            content = _extract_article_body(url)
        if not content:
            content = summary

        published = entry.get("published", "") or entry.get("updated", "")
        author = entry.get("author", "")

        categories = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if category != "전체":
            categories.append(category)

        article = Article(
            id=_generate_id(url),
            title=title,
            content=content,
            summary=_truncate(summary),
            url=url,
            source=source_name,
            author=author or None,
            published=published or None,
            collected_at=datetime.now().isoformat(),
            categories=list(set(categories)),
        )
        articles.append(article)

    return articles


def collect_from_url(url: str) -> Optional[Article]:
    """Collect a single article from a direct URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")
        if not title:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

        content = _extract_article_body(url)
        if not content:
            return None

        # Extract source from meta or domain
        source = ""
        og_site = soup.find("meta", property="og:site_name")
        if og_site:
            source = og_site.get("content", "")
        if not source:
            from urllib.parse import urlparse
            source = urlparse(url).netloc

        description = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            description = og_desc.get("content", "")

        return Article(
            id=_generate_id(url),
            title=title,
            content=content,
            summary=_truncate(description or content),
            url=url,
            source=source,
            author=None,
            published=None,
            collected_at=datetime.now().isoformat(),
            categories=[],
        )
    except Exception:
        return None


def collect_all(sources: list[str] = None, categories: list[str] = None,
                fetch_body: bool = True, max_per_feed: int = 10) -> list[Article]:
    """Collect articles from multiple RSS sources."""
    all_articles = []
    seen_ids = set()

    for source_name, feeds in RSS_SOURCES.items():
        if sources and source_name not in sources:
            continue
        for cat_name, feed_url in feeds.items():
            if categories and cat_name not in categories:
                continue
            articles = collect_from_rss(source_name, cat_name, feed_url,
                                        fetch_body=fetch_body, max_articles=max_per_feed)
            for a in articles:
                if a.id not in seen_ids and a.content:
                    seen_ids.add(a.id)
                    all_articles.append(a)

    return all_articles


def get_available_sources() -> dict:
    """Return available RSS sources and categories."""
    return {name: list(feeds.keys()) for name, feeds in RSS_SOURCES.items()}
