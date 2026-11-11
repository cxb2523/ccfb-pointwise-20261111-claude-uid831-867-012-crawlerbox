"""Tests for the webprobe library (offline, using a fake session)."""

import csv
import json
import time
from datetime import timedelta

import pytest

from webprobe import (
    NetworkManager,
    export_csv,
    export_json,
    parse_header,
    probe_page,
)


class FakeResponse:
    def __init__(self, url, body="", status=200, final_url=None):
        self.url = final_url if final_url is not None else url
        self.status_code = status
        self.ok = 200 <= status < 400
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.text = body
        self.elapsed = timedelta(milliseconds=5)


class FakeSession:
    """Stand-in for requests.Session; maps URL -> body or FakeResponse."""

    def __init__(self, pages):
        self.pages = pages
        self.sent = []  # (url, headers, monotonic timestamp)

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.sent.append((url, dict(headers), time.monotonic()))
        page = self.pages[url]
        if isinstance(page, FakeResponse):
            return page
        return FakeResponse(url, page)


def make_manager(pages, **kwargs):
    session = FakeSession(pages)
    manager = NetworkManager(session=session, **kwargs)
    return manager, session


# --- header parsing / merging ---------------------------------------------

def test_parse_header_splits_on_first_colon():
    assert parse_header("X-Time: 12:30:00") == ("X-Time", "12:30:00")
    assert parse_header("Accept:text/html") == ("Accept", "text/html")


def test_parse_header_rejects_garbage():
    with pytest.raises(ValueError):
        parse_header("no colon here")
    with pytest.raises(ValueError):
        parse_header(": no name")


def test_explicit_user_agent_overrides_default_case_insensitively():
    manager, _ = make_manager({}, headers=["user-agent: custom/2.0"])
    ua_keys = [k for k in manager.headers if k.lower() == "user-agent"]
    assert ua_keys == ["user-agent"]
    assert manager.headers["user-agent"] == "custom/2.0"


def test_default_user_agent_kept_when_not_overridden():
    manager, _ = make_manager({})
    assert manager.headers["User-Agent"] == "webprobe/1.0"


def test_headers_actually_sent():
    pages = {"http://h.test/": ""}
    manager, session = make_manager(pages, headers=["X-Custom: yes"])
    manager.fetch("http://h.test/")
    _, sent_headers, _ = session.sent[0]
    assert sent_headers["X-Custom"] == "yes"
    assert sent_headers["User-Agent"] == "webprobe/1.0"


# --- include / exclude filtering ------------------------------------------

def test_exclude_takes_priority_over_include():
    manager, _ = make_manager({}, include=r".", exclude=r"skip")
    assert not manager.allowed("http://h.test/skip.html")
    assert manager.allowed("http://h.test/page1.html")


def test_include_uses_search_on_absolute_url():
    manager, _ = make_manager({}, include=r"page\d")
    assert manager.allowed("http://h.test/sub/page2.html")
    assert not manager.allowed("http://h.test/index.html")


def test_seed_exempt_from_include_but_not_exclude():
    manager, _ = make_manager({}, include=r"page", exclude=r"blocked")
    assert manager.allowed("http://h.test/index.html", is_seed=True)
    assert not manager.allowed("http://h.test/blocked", is_seed=True)


def test_crawl_filters_and_seed_exception():
    pages = {
        "http://h.test/index.html":
            "<a href='page1.html'>1</a>"
            "<a href='sub/page2.html'>2</a>"
            "<a href='skip.html'>s</a>",
        "http://h.test/page1.html": "<a href='index.html'>back</a>",
        "http://h.test/sub/page2.html": "",
        "http://h.test/skip.html": "",
    }
    manager, session = make_manager(pages, include=r"page", exclude=r"skip")
    records = probe_page("http://h.test/index.html", manager=manager)
    urls = {r["url"] for r in records}
    # seed probed once despite not matching include; skip never fetched
    assert urls == {
        "http://h.test/index.html",
        "http://h.test/page1.html",
        "http://h.test/sub/page2.html",
    }
    assert all("skip" not in sent_url for sent_url, _, _ in session.sent)


def test_redirect_cannot_bypass_filters():
    pages = {
        "http://h.test/index.html": "<a href='redir.html'>r</a>",
        # redir.html passes the enqueue check but lands on an excluded URL
        "http://h.test/redir.html": FakeResponse(
            "http://h.test/redir.html", final_url="http://h.test/skip.html"),
        "http://h.test/skip.html": "",
    }
    manager, _ = make_manager(pages, exclude=r"skip")
    records = probe_page("http://h.test/index.html", manager=manager)
    urls = {r["url"] for r in records}
    assert urls == {"http://h.test/index.html"}


# --- per-host delay ---------------------------------------------------------

def test_first_request_to_host_is_not_delayed():
    pages = {"http://h.test/": ""}
    manager, _ = make_manager(pages, delay=0.5)
    start = time.monotonic()
    manager.fetch("http://h.test/")
    assert time.monotonic() - start < 0.2


def test_delay_enforced_between_sends_to_same_host():
    pages = {"http://h.test/a": "", "http://h.test/b": ""}
    manager, session = make_manager(pages, delay=0.3)
    manager.fetch("http://h.test/a")
    manager.fetch("http://h.test/b")
    t1 = session.sent[0][2]
    t2 = session.sent[1][2]
    assert t2 - t1 >= 0.28


def test_delay_is_per_host():
    pages = {"http://a.test/": "", "http://b.test/": ""}
    manager, _ = make_manager(pages, delay=0.5)
    manager.fetch("http://a.test/")
    start = time.monotonic()
    manager.fetch("http://b.test/")
    assert time.monotonic() - start < 0.2


def test_parsing_time_does_not_extend_the_window():
    # Window starts when the response comes back; work done afterwards
    # (e.g. parsing) counts towards it instead of being added on top.
    pages = {"http://h.test/a": "", "http://h.test/b": ""}
    manager, session = make_manager(pages, delay=0.3)
    manager.fetch("http://h.test/a")
    response_at = time.monotonic()
    time.sleep(0.2)  # simulated page parsing
    manager.fetch("http://h.test/b")
    second_send_at = session.sent[1][2]
    assert second_send_at - response_at == pytest.approx(0.3, abs=0.1)


# --- exports ----------------------------------------------------------------

def _sample_records():
    return [{
        "url": "http://h.test/page1.html",
        "final_url": "http://h.test/page1.html",
        "status_code": 200,
        "ok": True,
        "elapsed_ms": 5.0,
        "content_type": "text/html",
        "error": "comma, and\nnewline",
        "timestamp": "2026-11-11T00:00:00+00:00",
    }]


def test_json_and_csv_share_the_same_records(tmp_path):
    records = _sample_records()
    json_path = tmp_path / "out.json"
    csv_path = tmp_path / "out.csv"
    export_json(records, json_path)
    export_csv(records, csv_path)

    from_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert from_json == records

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    # csv reads everything as strings; compare field by field
    for key, value in records[0].items():
        assert rows[0][key] == ("" if value is None else str(value))
    # comma and newline survived the round trip untouched
    assert rows[0]["error"] == "comma, and\nnewline"
