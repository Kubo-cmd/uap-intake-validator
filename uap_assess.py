#!/usr/bin/env python3
"""Bounded CLI for assessing one UAP sighting JSON document."""
import json
import sys

from runtime_v0_2 import MAX_JSON_DEPTH
from validator import assess_sighting

MAX_CLI_BYTES = 1_048_576


class InputError(ValueError):
    pass


def _scan_depth(text):
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise InputError(f"JSON exceeds maximum depth {MAX_JSON_DEPTH}")
        elif char in "]}":
            depth -= 1
    return depth


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise InputError(f"non-standard JSON numeric constant: {value}")


def _read_record(path):
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_CLI_BYTES + 1)
    except OSError as exc:
        raise InputError(f"cannot read input: {exc}") from exc
    if len(raw) > MAX_CLI_BYTES:
        raise InputError(f"input exceeds {MAX_CLI_BYTES} bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise InputError("UTF-8 BOM is not accepted")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputError("input is not valid UTF-8") from exc
    _scan_depth(text)
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError, UnicodeError) as exc:
        raise InputError(f"input is not one valid JSON document: {exc}") from exc


def main(path):
    try:
        record = _read_record(path)
    except (InputError, RecursionError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read valid sighting JSON: {exc}", file=sys.stderr)
        return 2
    r = assess_sighting(record)
    print(f"VERDICT: {r['verdict']}")
    print("\nASSUMED (you / the analyst):")
    for assumption in r["assumed"]:
        print(f"  - {assumption}")
    print("\nMODEL-CONDITIONAL MEASUREMENTS:")
    for measurement in r["measurements"]:
        print(f"  - {measurement}")
    flag = r.get("underdetermination")
    if flag and flag.get("rcond") is not None:
        print(f"\nUNDETERMINATION FLAG: {flag['conditioning']}  "
              f"rcond={flag['rcond']:.3e} (log10={flag['log10Rcond']:.2f}, "
              f"rank={flag['effectiveRank']})")
    tri = r.get("triangulation")
    if tri:
        if tri.get("solvable"):
            selected = tri.get("selected_frame_index")
            frame_text = f"  selected frame {selected}" if selected is not None else ""
            print(f"\nTRIANGULATION: pos {tri['position_m']}  range {tri['range_m']} m  "
                  f"±{tri['sigma_range_m']} m ({tri['interval_kind']})  "
                  f"miss {tri['miss_distance_m']} m  baseline {tri['baseline_m']} m  "
                  f"confidence {'OK' if tri['confident'] else 'LOW'}{frame_text}")
        else:
            print(f"\nTRIANGULATION: not solvable — {tri.get('reason')}")
    print("\nSCOPE: validates declared data and geometry assumptions; does not prove or "
          "disprove a sighting, identify an object, or establish field accuracy.")
    return 2 if r["verdict"] == "INVALID SIGHTLINE DATA" else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
