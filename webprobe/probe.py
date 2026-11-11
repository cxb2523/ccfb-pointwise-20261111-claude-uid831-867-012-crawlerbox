"""Page probing / crawling logic for webprobe."""

from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from .manager import NetworkManager

#: Field order of one serialized probe record. JSON and CSV exports are
#: produced from the exact same serialized dicts.
RECORD_FIELDS = [
    "url",
    "final_url",
    "status_code",
    "ok",
    "elapsed_ms",
    "content_type",
    "error",
    "timestamp",
]


class _LinkParser(HTMLParser):
    """Collects ``href`` targets of <a> tags."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.links.append(value)


def extract_links(html, base_url):
    """Return absolute http(s) URLs linked from ``html`` at ``base_url``."""
    parser = _LinkParser()
    parser.feed(html)
    urls = []
    for href in parser.links:
        absolute = urldefrag(urljoin(base_url, href)).url
        if urlsplit(absolute).scheme in ("http", "https"):
            urls.append(absolute)
    return urls


def serialize_record(record):
    """Project ``record`` onto :data:`RECORD_FIELDS` (shared by exporters)."""
    return {field: record.get(field) for field in RECORD_FIELDS}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _response_record(url, response):
    elapsed = getattr(response, "elapsed", None)
    elapsed_ms = round(elapsed.total_seconds() * 1000, 3) if elapsed is not None else None
    return {
        "url": url,
        "final_url": response.url,
        "status_code": response.status_code,
        "ok": bool(response.ok),
        "elapsed_ms": elapsed_ms,
        "content_type": response.headers.get("Content-Type", ""),
        "error": "",
        "timestamp": _now_iso(),
    }


def _error_record(url, exc):
    return {
        "url": url,
        "final_url": "",
        "status_code": None,
        "ok": False,
        "elapsed_ms": None,
        "content_type": "",
        "error": f"{type(exc).__name__}: {exc}",
        "timestamp": _now_iso(),
    }


def probe_page(seed_url, manager=None, *, headers=None, delay=0.0,
               include=None, exclude=None, timeout=10.0, max_pages=100,
               session=None):
    """Probe ``seed_url`` and follow links, breadth-first.

    Either pass a configured :class:`~webprobe.manager.NetworkManager` via
    ``manager``, or let one be built from the keyword arguments.

    The seed is probed once even if it does not match the ``include``
    filter. Every URL is checked against the filters before being enqueued
    and again right before the request is sent; the final URL is checked
    once more after redirects so a redirect cannot smuggle a filtered URL
    past the probe.

    Returns a list of serialized records (see :data:`RECORD_FIELDS`).
    """
    if manager is None:
        manager = NetworkManager(
            headers=headers, delay=delay, include=include, exclude=exclude,
            timeout=timeout, session=session,
        )

    records = []
    visited = set()
    queue = deque([(urldefrag(seed_url).url, True)])

    while queue and len(records) < max_pages:
        url, is_seed = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            response = manager.fetch(url, is_seed=is_seed)
        except Exception as exc:  # network error: still record the probe
            records.append(serialize_record(_error_record(url, exc)))
            continue
        if response is None:
            continue  # rejected by the pre-send filter check
        # Redirect guard: the final URL must pass the filters too.
        if not manager.allowed(response.url, is_seed=is_seed):
            continue

        record = _response_record(url, response)
        records.append(serialize_record(record))

        content_type = record["content_type"] or ""
        if "html" not in content_type.lower():
            continue
        for link in extract_links(response.text, response.url):
            # Enqueue-time filter check (re-checked before sending).
            if link not in visited and manager.allowed(link):
                queue.append((link, False))

    return records
