import unittest
from urllib.parse import urlencode

from flightcostapp import price_news, price_news_review


def article(slug, *, date="Fri, 23 Oct 2026 00:00:00 GMT", host="issuer.example"):
    return {"url": f"https://{host}/{slug}", "title": f"Aircraft deal {slug}", "published": date}


class NewsReview(unittest.TestCase):
    def test_group_index_preserves_article_dates_and_alternates(self):
        original = article("transaction")
        mirror = {**article("news", host="news.example"), "title": original["title"]}
        later = {**article("later", date="Fri, 13 Nov 2026 00:00:00 GMT"), "title": original["title"]}
        groups = price_news.group_news([
            {"icao": "A320", "articles": [original, mirror, later]},
            {"icao": "B738", "articles": [original]},
        ])
        stories = price_news_review.index_groups(groups)
        self.assertEqual(stories, {
            "A320-01": {**original, "alternates": [mirror], "icao": "A320"},
            "A320-02": {**later, "icao": "A320"},
            "B738-01": {**original, "icao": "B738"},
        })
        self.assertNotIn("icao", original)

    def test_actual_fetches_override_skips_and_normalize_alternate_urls(self):
        original = {**article("transaction"), "alternates": [article("report", host="news.example")]}
        failed = article("blocked")
        complete = article("other-type")
        stories = price_news_review.index_groups({"A320": [original, failed, complete]})
        alternate_url = "https://NEWS.example/report?utm_source=rss#section"
        request = "https://www.bing.com/news/apiclick.aspx?" + urlencode({"url": alternate_url})
        result = price_news_review.review(stories, [
            {"url": original["url"], "error": "HTTP 403"},
            {"url": request, "final_url": "https://news.example/report"},
            {"url": alternate_url, "error": "HTTP 429"},
            {"url": failed["url"] + "?utm_medium=rss", "error": "HTTP 403"},
        ], "A320-01\toff_topic\tThe article is about fares.\n"
           "A320-02\toff_topic\tThe article is about routes.\n"
           "A320-03\twrong_type\tOnly covers Boeing 737-800 aircraft.")
        self.assertEqual((result["total"], result["opened"], result["failed"], result["skipped"],
                          result["unreviewed"], result["complete"]), (3, 1, 1, 1, 0, True))
        self.assertEqual(result["stories"]["A320-01"], {
            **article("transaction"), "icao": "A320", "status": "opened",
            "fetched_url": request, "final_url": "https://news.example/report",
        })
        self.assertEqual(result["stories"]["A320-02"]["error"], "HTTP 403")
        self.assertEqual(result["stories"]["A320-03"]["skip_code"], "wrong_type")

    def test_duplicates_require_unique_rows_and_an_attempted_target(self):
        stories = price_news_review.index_groups({"A320": [article(str(index)) for index in range(8)]})
        result = price_news_review.review(stories, [{"url": stories["A320-01"]["url"], "error": "HTTP 403"}],
            "A320-02\tduplicate\tA320-01: Same order for 12 aircraft from May.\n"
            "A320-03\tduplicate\tA320-02: Same order for 12 aircraft from May.\n"
            "A320-04\tduplicate\tA320-04: Same order.\n"
            "A320-05\tduplicate\tA320-99: Same order.\n"
            "A320-06\tduplicate\tA320-01 — A320-02\n"
            "A320-07\toff_topic\tOnly gives fare prices.\n"
            "A320-07\tinvalid\tRepeated ID.\n"
            "A320-08\taggregate_order\t\n")
        self.assertEqual([row["status"] for row in result["stories"].values()],
                         ["failed", "skipped", *("unreviewed",) * 6])
        self.assertEqual(result["stories"]["A320-02"]["reason"], "A320-01: Same order for 12 aircraft from May.")
        self.assertEqual(len(result["issues"]), 6)
        self.assertFalse(result["complete"])

    def test_missing_trace_blocks_completion_for_nonempty_selection(self):
        stories = price_news_review.index_groups({"A320": [article("routes")]})
        skips = "A320-01\toff_topic\tAnnual schedule changes with no aircraft transaction."
        missing = price_news_review.review(stories, None, skips)
        self.assertFalse(missing["complete"])
        self.assertEqual(missing["unreviewed"], 1)
        empty = price_news_review.review(stories, [], skips)
        self.assertTrue(empty["complete"])
        self.assertEqual(empty["skipped"], 1)
        self.assertTrue(price_news_review.review({}, None)["complete"])


if __name__ == "__main__":
    unittest.main()
