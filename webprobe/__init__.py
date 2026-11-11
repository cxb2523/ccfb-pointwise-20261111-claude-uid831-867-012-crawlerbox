"""Reusable web probing library.

Exposes :class:`NetworkManager` and :func:`probe_page` so callers can embed
the probing capability directly instead of spawning a subprocess.
"""

from .exporters import export_csv, export_json
from .manager import DEFAULT_HEADERS, NetworkManager, merge_headers, parse_header
from .probe import RECORD_FIELDS, extract_links, probe_page, serialize_record

__all__ = [
    "DEFAULT_HEADERS",
    "RECORD_FIELDS",
    "NetworkManager",
    "export_csv",
    "export_json",
    "extract_links",
    "merge_headers",
    "parse_header",
    "probe_page",
    "serialize_record",
]
