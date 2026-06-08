#!/usr/bin/env python3
"""Parse fio JSON output and emit a single-line CSV summary row.

fio's JSON output puts percentile data in `clat_ns.percentile` as a dict
keyed by percentile strings (e.g. "50.000000"), value in NANOSECONDS.
Empty I/O streams (e.g. zero-read workload) just have an empty dict.
"""
import json
import sys


def ns_to_us(ns):
    if ns is None:
        return None
    return float(ns) / 1000.0


def get_pct(rdict, target_str):
    """target_str is the percentile we want, as a string fio emits it."""
    p = rdict.get("clat_ns", {}).get("percentile", {})
    # fio writes keys like "50.000000" — match by prefix
    for k, v in p.items():
        if k.startswith(target_str):
            return ns_to_us(v)
    return None


def main(path):
    with open(path) as f:
        data = json.load(f)
    jobs = data.get("jobs", [])
    if not jobs:
        print("PARSE_FAIL: no jobs", file=sys.stderr)
        sys.exit(1)
    j = jobs[0]
    r = j["read"]
    w = j["write"]

    # ,{r_iops},{r_bw},{w_iops},{w_bw},<8 pcts>
    fields = [
        "{:.0f}".format(r["iops"]),
        "{:.1f}".format(r["bw"] / 1024.0),
        "{:.0f}".format(w["iops"]),
        "{:.1f}".format(w["bw"] / 1024.0),
        "{}".format(get_pct(r, "50.")),
        "{}".format(get_pct(r, "95.")),
        "{}".format(get_pct(r, "99.")),
        "{}".format(get_pct(r, "99.9")),
        "{}".format(get_pct(w, "50.")),
        "{}".format(get_pct(w, "95.")),
        "{}".format(get_pct(w, "99.")),
        "{}".format(get_pct(w, "99.9")),
    ]
    print(",{}".format(",".join(fields)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: parse_fio_json.py <fio_output.json>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])