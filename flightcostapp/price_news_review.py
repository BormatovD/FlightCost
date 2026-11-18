"""Учёт проверки групп новостей по журналу загрузок и причинам исключения."""

import re

from .price_news import _canonical_article_url


_SKIP_CODES = {"wrong_type", "off_topic", "aggregate_order", "duplicate"}


def index_groups(groups: dict[str, list[dict]]) -> dict[str, dict]:
    return {
        f"{icao}-{number:02d}": {**article, "icao": icao}
        for icao, articles in groups.items()
        for number, article in enumerate(articles, 1)
    }


def _attempts(fetches: list[dict]) -> dict[str, dict]:
    attempts = {}
    for fetch in fetches:
        url = _canonical_article_url(fetch["url"])
        if fetch.get("final_url"):
            attempts[url] = {"status": "opened", "fetched_url": fetch["url"],
                             "final_url": fetch["final_url"]}
        elif fetch.get("error") and url not in attempts:
            attempts[url] = {"status": "failed", "fetched_url": fetch["url"],
                             "error": fetch["error"]}
    return attempts


def _group_attempt(story: dict, attempts: dict[str, dict]) -> dict:
    first_failure = None
    for article in (story, *story.get("alternates", ())):
        attempt = attempts.get(_canonical_article_url(article["url"]))
        if attempt and attempt["status"] == "opened":
            return attempt
        if attempt and first_failure is None:
            first_failure = attempt
    return first_failure or {"status": "unreviewed"}


def _skip_rows(skip_text: str, stories: dict[str, dict], issues: list[str]) -> dict[str, tuple[str, str]]:
    seen = set()
    rows = {}
    for line_number, line in enumerate(skip_text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [field.strip() for field in line.split("\t")]
        story_id = parts[0]
        if story_id not in stories:
            issues.append(f"Строка {line_number}: неизвестный ID группы")
            continue
        if story_id in seen:
            rows.pop(story_id, None)
            issues.append(f"Строка {line_number}: повтор ID {story_id}")
            continue
        seen.add(story_id)
        if len(parts) != 3 or parts[1] not in _SKIP_CODES or not parts[2]:
            issues.append(f"Строка {line_number}: некорректная причина для {story_id}")
            continue
        rows[story_id] = (parts[1], parts[2])
    return rows


def _has_explanation(text: str, story_ids: dict[str, dict]) -> bool:
    # Проверяем наличие пояснения. Его фактическую обоснованность определяет агент.
    tokens = re.findall(r"[\w-]+", text)
    return any(token not in story_ids and token.casefold() not in _SKIP_CODES
               and any(char.isalpha() for char in token) for token in tokens)


def _apply_skips(reviewed: dict[str, dict], skip_text: str, issues: list[str]) -> None:
    rows = _skip_rows(skip_text, reviewed, issues)
    for story_id, (code, reason) in sorted(rows.items(), key=lambda item: item[1][0] == "duplicate"):
        story = reviewed[story_id]
        if story["status"] != "unreviewed":
            continue
        explanation = reason
        if code == "duplicate":
            target_id, *description = re.split(r"[\s:;,]+", reason, maxsplit=1)
            target = reviewed.get(target_id)
            if (target_id == story_id or target is None or target["status"] == "unreviewed"
                    or target.get("skip_code") == "duplicate"):
                issues.append(f"{story_id}: нет самостоятельного решения по группе-дублю")
                continue
            explanation = description[0] if description else ""
        if not _has_explanation(explanation, reviewed):
            issues.append(f"{story_id}: отсутствует пояснение причины исключения")
            continue
        story.update(status="skipped", skip_code=code, reason=reason)


def review(stories: dict[str, dict], fetches: list[dict] | None, skip_text: str = "") -> dict:
    """Сопоставить попытки загрузки с группами и проверить причины пропуска."""
    attempts = _attempts(fetches or [])
    reviewed = {
        story_id: {"icao": story["icao"], "title": story["title"], "url": story["url"],
                   "published": story["published"], **_group_attempt(story, attempts)}
        for story_id, story in stories.items()
    }
    issues: list[str] = []
    if fetches is None and stories:
        issues.append("Журнал попыток открыть статьи недоступен")
    else:
        _apply_skips(reviewed, skip_text, issues)

    counts = dict.fromkeys(("opened", "failed", "skipped", "unreviewed"), 0)
    for story in reviewed.values():
        counts[story["status"]] += 1
    return {"total": len(reviewed), **counts, "complete": counts["unreviewed"] == 0,
            "stories": reviewed, "issues": issues}
