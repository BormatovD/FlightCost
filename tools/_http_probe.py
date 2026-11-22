"""Mark requests from site checks and capture tools on the configured origin."""

from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from flightcostapp.probe import probe_url

BROWSER_FETCH_OPTIONS = {"patterns": [{"urlPattern": "http*://*"}]}


def _origin(url):
    parsed = urlsplit(url)
    defaults = {"http": 80, "https": 443}
    port = parsed.port if parsed.port is not None else defaults.get(parsed.scheme)
    return parsed.scheme, parsed.hostname, port


def probe_for_origin(base):
    origin = _origin(base)

    def tag(url):
        return probe_url(url) if _origin(url) == origin else url

    return tag


def probe_opener(base):
    tag = probe_for_origin(base)

    class ProbeRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return super().redirect_request(req, fp, code, msg, headers, tag(newurl))

    return build_opener(ProbeRedirect())


def browser_continue_params(tag, event):
    # CDP pauses each redirect hop. Playwright route overrides only the first.
    url = event["request"]["url"]
    marked = tag(url)
    params = {"requestId": event["requestId"]}
    if marked != url:
        params["url"] = marked
    return params
