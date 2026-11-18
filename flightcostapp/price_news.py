"""Bing RSS для прогона цен. Заголовки ленты помогают найти первоисточник."""

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from unicodedata import normalize
from urllib.parse import parse_qs, unquote_plus, urlencode, urlsplit
from urllib.request import urlopen
from xml.etree import ElementTree as ET


_BROWSER_CHECK_HEADING = re.compile(
    r"^[ \t#>*_]*(?:just a moment|browser (?:check|verification)(?: in progress| required)?|"
    r"(?:checking|verifying) your browser(?: before accessing .+)?|"
    r"(?:please )?(?:verify|verifying) (?:that )?you(?: are|['’]re) (?:a )?human|"
    r"vercel security checkpoint)(?:[.!…*_ ]*|[.!… ]* +[-–—|:] +.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_BROWSER_CHECK_INSTRUCTIONS = re.compile(
    r"^[ \t#>*_]*(?:enable javascript and cookies to continue|"
    r"(?:we['’]re|we are) verifying your browser|"
    r"checking if (?:the site|your) connection is secure)\b",
    re.IGNORECASE | re.MULTILINE,
)
_TRACKING_QUERY_KEYS = {
    "_ga", "_gl", "dclid", "fbclid", "gbraid", "gclid", "igshid",
    "mc_cid", "mc_eid", "msclkid", "wbraid",
    "utm_campaign", "utm_content", "utm_creative_format", "utm_id", "utm_marketing_tactic",
    "utm_medium", "utm_source", "utm_source_platform", "utm_term",
}
_TITLE_TOKENS = re.compile(r"(?<!\S)[-−]\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*|\w+|[$€£¥₽%+]")
_PUBLISHER_SEPARATOR = re.compile(r"\s+[-–—|]\s+")


def _publisher_url(link: str) -> str:
    try:
        parts = urlsplit(link)
        if parts.hostname == "www.bing.com" and parts.path.lower() == "/news/apiclick.aspx":
            parts = urlsplit(parse_qs(parts.query).get("url", [""])[0])
        if parts.scheme in ("http", "https") and parts.hostname and parts.username is None:
            return parts._replace(fragment="").geturl()
    except ValueError:
        pass
    return ""


def load_feeds(names: dict[str, str]) -> list[dict]:
    """Сделать по четыре попытки на тип и сохранить результат каждой ленты."""
    feeds = []
    for code, name in names.items():
        for suffix in ("price million", "lease rate", "sale leaseback", "aircraft market value"):
            query = f'"{name}" {suffix}'
            url = "https://www.bing.com/news/search?" + urlencode({"q": query, "format": "rss"})
            feeds.append({"icao": code, "query": query, "url": url})

    def load(feed):
        try:
            limit = 1024 * 1024
            # С User-Agent FlightCostApp Bing возвращает HTML даже при format=rss.
            with urlopen(feed["url"], timeout=12) as response:
                body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError("ответ RSS больше 1 МБ")
            if body.lstrip()[:16].lower().startswith((b"<!doctype html", b"<html")):
                raise ValueError("Bing вернул HTML вместо RSS")
            root = ET.fromstring(body)
            channel = root.find("channel") if root.tag == "rss" else None
            if channel is None:
                raise ValueError("ответ без канала RSS")
            articles = []
            for item in channel.findall("item"):
                url = _publisher_url(item.findtext("link", "").strip())
                if url:
                    articles.append({"url": url, "title": item.findtext("title", ""),
                                     "published": item.findtext("pubDate", "")})
            return {**feed, "articles": articles}
        except (OSError, HTTPException, ValueError, ET.ParseError) as exc:
            return {**feed, "error": f"{type(exc).__name__}: {exc}"[:240]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(load, feeds))


def _canonical_article_url(url: str) -> str:
    publisher_url = _publisher_url(url)
    if not publisher_url:
        return url
    parts = urlsplit(publisher_url)
    query = "&".join(part for part in parts.query.split("&")
                     if unquote_plus(part.partition("=")[0]).lower() not in _TRACKING_QUERY_KEYS)
    return parts._replace(netloc=parts.netloc.lower(), query=query).geturl()


def _article_title_keys(article: dict, url: str) -> set[tuple[str, ...]]:
    title = normalize("NFKC", article.get("title") or "").casefold()
    exact = tuple(_TITLE_TOKENS.findall(title))
    if not exact:
        return set()
    keys = {exact}
    parts = _PUBLISHER_SEPARATOR.split(title)
    host = urlsplit(_publisher_url(url)).hostname or ""
    # Убираем суффикс только при совпадении с именем домена издателя.
    if len(parts) > 1 and host:
        suffix = "".join(_TITLE_TOKENS.findall(parts[-1]))
        domain = host.removeprefix("www.")
        labels = domain.split(".")
        if suffix in {labels[0], "".join(labels)}:
            keys.add(tuple(_TITLE_TOKENS.findall(" ".join(parts[:-1]))))
    # Сохраняем порядок слов, числа, модели и содержательные различия.
    for tokens in tuple(keys):
        words = tuple(token for token in tokens if token not in {"a", "an", "the"})
        if len(words) >= 5:
            keys.add(words)
    keys.discard(())
    return keys


def group_news(feeds: list[dict]) -> dict[str, list[dict]]:
    """Сгруппировать повторные публикации отдельно для каждого типа ВС."""
    articles_by_type: dict[str, list[dict]] = {}
    for feed in feeds:
        articles_by_type.setdefault(feed["icao"], []).extend(feed.get("articles", []))
    return {code: _shortlist(articles) for code, articles in articles_by_type.items()}


def _published_date(article: dict) -> date | None:
    try:
        return parsedate_to_datetime(article.get("published") or "").date()
    except ValueError:
        return None


def _shortlist(articles: list[dict]) -> list[dict]:
    shortlist = []
    urls: set[str] = set()
    titles: dict[tuple[str, ...], list[int]] = {}
    endpoints: list[set[str]] = []
    dates: list[date | None] = []
    for article in articles:
        url = _canonical_article_url(article["url"])
        if url in urls:
            continue
        urls.add(url)
        title_keys = _article_title_keys(article, url)
        parts = urlsplit(_publisher_url(url))
        endpoint = parts._replace(query="").geturl()
        published = _published_date(article)
        matches = {index for key in title_keys for index in titles.get(key, ())}
        # Один адрес с разными значимыми параметрами либо большой разрыв
        # между публикациями может указывать на разные сделки.
        group_index = min(
            (index for index in matches
             if endpoint not in endpoints[index]
             and (published is None or dates[index] is None or abs((published - dates[index]).days) <= 7)),
            default=len(shortlist),
        )
        if group_index == len(shortlist):
            shortlist.append(dict(article))
            dates.append(published)
            endpoints.append(set())
            for key in title_keys:
                titles.setdefault(key, []).append(group_index)
        else:
            shortlist[group_index].setdefault("alternates", []).append(dict(article))
        endpoints[group_index].add(endpoint)
    return shortlist


def read_article_fetches(state_dir: Path, session_id: str | None) -> list[dict] | None:
    """Прочитать вызовы web_fetch из временного журнала OpenClaw 2026.10.5."""
    if not session_id:
        return None
    databases = list(state_dir.glob("agents/*/agent/openclaw-agent.sqlite"))
    if len(databases) != 1:
        return None
    calls = {}
    try:
        with closing(sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT event_json FROM trajectory_runtime_events "
                              "WHERE session_id = ? ORDER BY seq", (session_id,))
            boundaries = set()
            for (raw,) in rows:
                event = json.loads(raw)
                if event.get("type") in ("session.started", "session.ended"):
                    boundaries.add(event["type"])
                if event.get("type") not in ("tool.call", "tool.result"):
                    continue
                data = event["data"]
                if data["name"] != "web_fetch":
                    continue
                call_id = data["toolCallId"]
                if event["type"] == "tool.call":
                    calls[call_id] = {"url": data["args"]["url"], "error": "ответ не записан"}
                else:
                    calls[call_id] = {"url": calls[call_id]["url"], **_fetch_outcome(data)}
    except (sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
        return None
    return list(calls.values()) if len(boundaries) == 2 else None


def _fetch_outcome(data: dict) -> dict:
    result = data.get("result") or {}
    details = result.get("details") or {}
    if data.get("success") is not True:
        # Не переносим в сводку тело ошибки, которое мог вернуть сайт.
        match = re.search(r"Web fetch failed \((\d{3})\)", details.get("error", ""))
        return {"error": f"HTTP {match[1]}" if match else "ошибка загрузки или извлечения текста"}
    link = details.get("finalUrl", "")
    if urlsplit(link).hostname in {"www.bing.com", "bing.com", "news.google.com"}:
        return {"error": "страница агрегатора"}
    final_url = _publisher_url(link)
    if not final_url or not 200 <= details.get("status", 0) < 300 or not details.get("rawLength"):
        return {"error": "нет текста статьи"}
    if details.get("contentType") not in (None, "text/html", "application/xhtml+xml", "text/plain", "text/markdown"):
        return {"error": "ответ не является текстом статьи"}
    title = (details.get("title") or "")[:1024]
    text = (details.get("text") or "")[:2500]
    if (_BROWSER_CHECK_HEADING.search(title) or _BROWSER_CHECK_HEADING.search(text)
            or _BROWSER_CHECK_INSTRUCTIONS.search(text)):
        return {"error": "проверка браузера"}
    return {"final_url": final_url}


def coverage(feeds: list[dict], fetches: list[dict] | None,
             groups: dict[str, list[dict]] | None = None) -> dict:
    urls_by_type: dict[str, set[str]] = {}
    for feed in feeds:
        urls_by_type.setdefault(feed["icao"], set()).update(
            article["url"] for article in feed.get("articles", [])
        )
    candidates = set().union(*urls_by_type.values())
    feed_errors = [feed for feed in feeds if "error" in feed]
    requests = [(_publisher_url(fetch["url"]), fetch) for fetch in (fetches or [])]
    attempts = [(url, fetch) for url, fetch in requests if url in candidates]
    source_errors = [fetch for url, fetch in requests if url not in candidates and "error" in fetch]
    if groups is None:
        groups = group_news(feeds)

    def article_stats(urls):
        matching = [(url, row) for url, row in attempts if url in urls]
        requested = {url for url, _ in matching}
        opened = {row["final_url"] for _, row in matching if "final_url" in row}
        errors = [row for _, row in matching if "error" in row]
        if fetches is None:
            return None, None, errors
        return len(requested), len(opened), errors

    attempted, opened, article_errors = article_stats(candidates)
    articles_by_type = {}
    for code, urls in urls_by_type.items():
        type_attempted, type_opened, errors = article_stats(urls)
        articles_by_type[code] = {
            "candidates": len(urls),
            "groups": len(groups.get(code, [])),
            "attempted": type_attempted,
            "opened": type_opened,
            "errors": len(errors),
        }
    return {
        "feeds_total": len(feeds),
        "feeds_loaded": len(feeds) - len(feed_errors),
        "feed_errors": feed_errors,
        "articles_candidates": len(candidates),
        "articles_attempted": attempted,
        "articles_opened": opened,
        "article_errors": article_errors,
        "source_errors": source_errors,
        "articles_by_type": articles_by_type,
    }


def describe_coverage(coverage: dict, diagnostics: str) -> str:
    opened = coverage["articles_opened"]
    count = str(opened) if opened is not None else "нет данных журнала"
    attempted = coverage["articles_attempted"]
    lines = [f"RSS загружено {coverage['feeds_loaded']}/{coverage['feeds_total']}. "
             f"Статей из RSS открыто: {count}. Найдено ссылок: {coverage['articles_candidates']}."]
    if attempted is not None:
        lines[0] += f" Запрошено: {attempted}."
    by_type = coverage.get("articles_by_type", {})
    if by_type:
        labels = []
        for code, stats in by_type.items():
            result = f"{code} — {stats['groups']} групп из {stats['candidates']} ссылок"
            if stats["opened"] is not None:
                result += f", открыто {stats['opened']}/{stats['attempted']}"
            if stats["errors"]:
                result += f", ошибок {stats['errors']}"
            labels.append(result)
        lines.append("По типам: " + " · ".join(labels) + ".")
    feed_errors, article_errors = coverage["feed_errors"], coverage["article_errors"]
    source_errors = coverage.get("source_errors", [])
    if feed_errors or article_errors or source_errors:
        summary = f"Ошибок RSS: {len(feed_errors)}, открытия статей: {len(article_errors)}."
        if source_errors:
            summary += f" Ошибок других источников: {len(source_errors)}."
        lines.append(summary)
        lines.extend(f"· RSS {row['icao']} {row['query']}: {row['error'][:80]}" for row in feed_errors[:2])
        lines.extend(f"· {row['url'][:100]}: {row['error']}" for row in article_errors[:2])
        lines.extend(f"· {row['url'][:100]}: {row['error']}" for row in source_errors[:2])
        if any(len(errors) > 2 for errors in (feed_errors, article_errors, source_errors)):
            lines.append(f"Все ошибки — {diagnostics}.")
    return "\n".join(lines)
