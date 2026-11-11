"""Exporters: JSON and CSV built from the same serialized records."""

import csv
import json

from .probe import RECORD_FIELDS, serialize_record


def export_json(records, path):
    """Write ``records`` to ``path`` as a JSON array."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([serialize_record(r) for r in records], fh,
                  ensure_ascii=False, indent=2)
        fh.write("\n")


def export_csv(records, path):
    """Write ``records`` to ``path`` as CSV via the stdlib csv module.

    Commas, quotes and newlines inside field values are quoted by
    :mod:`csv`, so no manual escaping is needed.
    """
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(serialize_record(record))
