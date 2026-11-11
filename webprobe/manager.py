"""Network manager for webprobe.

Handles HTTP header merging, per-host request pacing and include/exclude
URL filtering so callers do not have to re-implement them.
"""

import re
import time
from urllib.parse import urlsplit

import requests

#: Headers sent when the caller does not override them.
DEFAULT_HEADERS = {
    "User-Agent": "webprobe/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def parse_header(line):
    """Split a ``Name: Value`` header line on the *first* colon.

    Values may themselves contain colons (e.g. ``X-Time: 12:30:00``).
    """
    name, sep, value = line.partition(":")
    if not sep:
        raise ValueError(f"invalid header (expected 'Name: Value'): {line!r}")
    name = name.strip()
    if not name:
        raise ValueError(f"invalid header (empty name): {line!r}")
    return name, value.strip()


def merge_headers(defaults, overrides):
    """Merge ``overrides`` onto ``defaults`` case-insensitively.

    An explicitly passed ``user-agent`` (any casing) replaces the default
    ``User-Agent`` instead of producing a duplicate entry.
    """
    merged = {name.lower(): (name, value) for name, value in defaults.items()}
    for name, value in overrides:
        merged[name.lower()] = (name, value)
    return {name: value for name, value in merged.values()}


class NetworkManager:
    """Owns the HTTP session, header set, per-host pacing and URL filters.

    Parameters
    ----------
    headers:
        Iterable of ``"Name: Value"`` strings or a mapping. Explicit entries
        override :data:`DEFAULT_HEADERS` case-insensitively.
    delay:
        Minimum wall-clock seconds between two consecutive requests actually
        sent to the same host. The first request to a host is never delayed;
        the next allowed send time is recorded when the response comes back,
        so time spent parsing a page does not eat into the window.
    include / exclude:
        Regex strings matched with :func:`re.search` against the absolute
        URL. ``exclude`` wins over ``include``.
    """

    def __init__(self, headers=None, delay=0.0, include=None, exclude=None,
                 timeout=10.0, session=None):
        if headers is None:
            overrides = []
        elif isinstance(headers, dict):
            overrides = list(headers.items())
        else:
            overrides = [parse_header(line) for line in headers]
        self.headers = merge_headers(DEFAULT_HEADERS, overrides)
        self.delay = float(delay)
        self.include = re.compile(include) if include else None
        self.exclude = re.compile(exclude) if exclude else None
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        # host (netloc) -> monotonic timestamp of the next allowed send
        self._next_allowed = {}

    def allowed(self, url, is_seed=False):
        """Check ``url`` against the exclude/include filters.

        ``exclude`` takes priority. The seed URL is exempt from ``include``
        (it is probed once regardless) but never from ``exclude``.
        """
        if self.exclude is not None and self.exclude.search(url):
            return False
        if is_seed:
            return True
        if self.include is not None and not self.include.search(url):
            return False
        return True

    def _wait_for_host(self, host):
        next_allowed = self._next_allowed.get(host)
        if next_allowed is None:
            return  # first request to this host: no sleep
        remaining = next_allowed - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def fetch(self, url, is_seed=False):
        """GET ``url`` respecting filters and per-host pacing.

        Returns the :class:`requests.Response`, or ``None`` when the URL is
        rejected by the filters (checked again right before sending, so a
        URL that was enqueued earlier cannot slip through).
        """
        if not self.allowed(url, is_seed=is_seed):
            return None
        host = urlsplit(url).netloc
        self._wait_for_host(host)
        response = self.session.get(
            url,
            headers=self.headers,
            timeout=self.timeout,
            allow_redirects=True,
        )
        # Response is back: record when this host may be contacted again.
        self._next_allowed[host] = time.monotonic() + self.delay
        return response
