#!/usr/bin/env python3
"""uap_assess — CLI: assess a UAP sighting intake JSON file.

  python3 uap_assess.py sighting.json

Prints the verdict, the assumed-vs-model-conditional measurement split, the underdetermination
flag (when sightlines present), and two-sensor triangulation (when a second
observer's bearings are supplied).
"""
import json
import sys

from validator import assess_sighting


def main(path):
    try:
        with open(path) as f:
            record = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read valid sighting JSON: {exc}", file=sys.stderr)
        return 2
    r = assess_sighting(record)
    print(f"VERDICT: {r['verdict']}")
    print("\nASSUMED (you / the analyst):")
    for a in r["assumed"]:
        print(f"  - {a}")
    print("\nMODEL-CONDITIONAL MEASUREMENTS:")
    for e in r["measurements"]:
        print(f"  - {e}")
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
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
