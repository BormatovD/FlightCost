"""Bing RSS для прогона цен. Заголовки ленты помогают найти первоисточник."""

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPException
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from xml.etree import ElementTree as ET


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
    return {"final_url": final_url}


def coverage(feeds: list[dict], fetches: list[dict] | None) -> dict:
    candidates = {article["url"] for feed in feeds for article in feed.get("articles", [])}
    feed_errors = [feed for feed in feeds if "error" in feed]
    attempts = [fetch for fetch in (fetches or []) if _publisher_url(fetch["url"]) in candidates]
    opened = {row["final_url"] for row in attempts if "final_url" in row}
    article_errors = [row for row in attempts if "error" in row]
    return {
        "feeds_total": len(feeds),
        "feeds_loaded": len(feeds) - len(feed_errors),
        "feed_errors": feed_errors,
        "articles_candidates": len(candidates),
        "articles_opened": len(opened) if fetches is not None else None,
        "article_errors": article_errors,
    }


def describe_coverage(coverage: dict, diagnostics: str) -> str:
    opened = coverage["articles_opened"]
    count = str(opened) if opened is not None else "нет данных журнала"
    lines = [f"RSS загружено {coverage['feeds_loaded']}/{coverage['feeds_total']}. "
             f"Статей из RSS открыто: {count}. Найдено ссылок: {coverage['articles_candidates']}."]
    feed_errors, article_errors = coverage["feed_errors"], coverage["article_errors"]
    if feed_errors or article_errors:
        lines.append(f"Ошибок RSS: {len(feed_errors)}, открытия статей: {len(article_errors)}.")
        lines.extend(f"· RSS {row['icao']} {row['query']}: {row['error'][:80]}" for row in feed_errors[:2])
        lines.extend(f"· {row['url'][:100]}: {row['error']}" for row in article_errors[:2])
        if len(feed_errors) > 2 or len(article_errors) > 2:
            lines.append(f"Все ошибки — {diagnostics}.")
    return "\n".join(lines)
