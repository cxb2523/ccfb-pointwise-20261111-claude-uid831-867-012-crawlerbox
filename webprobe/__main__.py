"""Thin CLI wrapper around the webprobe library.

All behaviour lives in :class:`webprobe.NetworkManager` and
:func:`webprobe.probe_page`; this entry point only parses arguments.
"""

import argparse

from .exporters import export_csv, export_json
from .manager import NetworkManager
from .probe import probe_page

help_desc = """
Probe a seed URL, follow links and export one record per probed page.
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="webprobe",
        description=help_desc,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("url", help="seed URL to start probing from")
    parser.add_argument(
        "-H", "--header", action="append", default=[], metavar="'NAME: VALUE'",
        help="extra request header (split on the first colon); may be repeated. "
             "Overrides the default headers case-insensitively, e.g. User-Agent",
    )
    parser.add_argument(
        "-d", "--delay", type=float, default=0.0,
        help="minimum seconds between two requests to the same host "
             "(wall clock, measured between actual sends; default: 0)",
    )
    parser.add_argument(
        "-i", "--include", default=None, metavar="REGEX",
        help="only probe absolute URLs matching this regex (re.search); "
             "the seed is always probed once",
    )
    parser.add_argument(
        "-e", "--exclude", default=None, metavar="REGEX",
        help="never probe absolute URLs matching this regex (re.search); "
             "takes priority over --include",
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=10.0,
        help="per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "-m", "--max-pages", type=int, default=100,
        help="maximum number of pages to probe (default: 100)",
    )
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="write results as JSON to PATH")
    parser.add_argument("--csv", dest="csv_path", default=None, metavar="PATH",
                        help="write results as CSV to PATH")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    manager = NetworkManager(
        headers=args.header,
        delay=args.delay,
        include=args.include,
        exclude=args.exclude,
        timeout=args.timeout,
    )
    records = probe_page(args.url, manager=manager, max_pages=args.max_pages)

    if args.json_path:
        export_json(records, args.json_path)
    if args.csv_path:
        export_csv(records, args.csv_path)

    for record in records:
        print(f"{record['status_code'] or '-':>4} {record['url']}")
    print(f"probed {len(records)} page(s)")
    return records


if __name__ == "__main__":
    main()
