#!/usr/bin/env python3
"""nested_sim — simulation-within-simulation coverage audit.

OUTER loop draws random WORLDS (true target range/bearing, baseline, noise level,
sensor geometry family). INNER loop runs the real validator + triangulation on each
world. Then it audits synthetic coverage: does the reported confidence/verdict
track measured error across this fixed simulated distribution?

This is the honest test most tools never run: not "does it work on my hand-picked
cases" but "across a distribution of plausible realities, is the tool's self-report
trustworthy?"
"""
import math
import random

from validator import assess_sighting, triangulate
from uap_conditioning import assess_conditioning

rng = random.Random(2026)
WORLD_SEED = 2026
PEARSON_BOOTSTRAP_SEED = 918273


def _pearson_r(pairs):
    """Pearson correlation for validated finite pairs; undefined cases raise."""
    if len(pairs) < 4:
        raise ValueError("Pearson correlation requires at least four pairs")
    clean = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("each Pearson observation must be an (x, y) pair")
        x, y = pair
        if (isinstance(x, bool) or isinstance(y, bool) or
                not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or
                not math.isfinite(x) or not math.isfinite(y)):
            raise ValueError("Pearson pairs must contain finite numeric values")
        clean.append((float(x), float(y)))
    mx = sum(x for x, _ in clean) / len(clean)
    my = sum(y for _, y in clean) / len(clean)
    cov = sum((x - mx) * (y - my) for x, y in clean)
    vx = sum((x - mx) ** 2 for x, _ in clean)
    vy = sum((y - my) ** 2 for _, y in clean)
    if vx <= 0 or vy <= 0:
        raise ValueError("Pearson correlation is undefined for a constant margin")
    return cov / math.sqrt(vx * vy)


def _type7_quantile(values, probability):
    """R/NumPy-default linear quantile, specified here for version independence."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile requires values and probability in [0, 1]")
    ordered = sorted(values)
    h = (len(ordered) - 1) * probability
    lo = int(math.floor(h))
    hi = int(math.ceil(h))
    return ordered[lo] + (h - lo) * (ordered[hi] - ordered[lo])


def pearson_pairs_bootstrap(pairs, B=10000, seed=PEARSON_BOOTSTRAP_SEED):
    """Audit-only solved-pairs bootstrap for conditional Pearson uncertainty.

    This estimates simulation-design uncertainty conditional on solvability. It
    is not an outlier-robust correlation, a selection-bias correction, or a
    claim about observations outside this simulator's world distribution.
    """
    if isinstance(B, bool) or not isinstance(B, int) or B < 100:
        raise ValueError("B must be an integer of at least 100")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    point = _pearson_r(pairs)
    clean = [(float(pair[0]), float(pair[1])) for pair in pairs]
    local_rng = random.Random(seed)
    n = len(clean)
    replicates = []
    for _ in range(B):
        sample = [clean[local_rng.randrange(n)] for _ in range(n)]
        try:
            value = _pearson_r(sample)
        except ValueError:
            continue
        if math.isfinite(value):
            replicates.append(value)
    valid_B = len(replicates)
    if valid_B < max(4, math.ceil(0.99 * B)):
        raise ValueError("insufficient nondegenerate bootstrap replicates")
    mean = sum(replicates) / valid_B
    variance = sum((value - mean) ** 2 for value in replicates) / (valid_B - 1)
    if not math.isfinite(variance) or variance < 0:
        raise ValueError("bootstrap correlation variance is invalid")
    return {
        "method": "independent solved-pairs bootstrap",
        "estimand": "conditional on solvability and simulator world distribution",
        "quantile_method": "type-7 linear interpolation",
        "n": n, "B": B, "seed": seed, "valid_B": valid_B,
        "r": point, "bootstrap_se": math.sqrt(variance),
        "ci_low": _type7_quantile(replicates, 0.025),
        "ci_high": _type7_quantile(replicates, 0.975),
    }


# ---------- world generator ----------

def draw_world():
    """A random plausible sighting reality."""
    # true target: range 1-20 km, altitude 200-12000 m, random azimuth
    rng_true = rng.uniform(1000, 20000)
    az = rng.uniform(0, 2 * math.pi)
    alt = rng.uniform(200, 12000)
    horiz = math.sqrt(max(rng_true ** 2 - alt ** 2, 1.0))
    T = (horiz * math.cos(az), horiz * math.sin(az), alt)

    # sensor 1 at origin. baseline 200 m - 5 km to sensor 2.
    s1 = (0.0, 0.0, 0.0)
    base = rng.uniform(200, 5000)
    baz = rng.uniform(0, 2 * math.pi)
    s2 = (base * math.cos(baz), base * math.sin(baz), rng.uniform(-50, 50))

    # geometry family for the single-sensor conditioning test
    family = rng.choice(["straight", "orbit", "turn"])
    # bearing noise
    noise = rng.choice([0.0, 1e-4, 5e-4, 1e-3, 2e-3])
    n = rng.choice([20, 30, 60])
    fps = rng.choice([1.0, 24.0, 30.0])
    return dict(T=T, s1=s1, s2=s2, base=base, family=family, noise=noise, n=n, fps=fps)


def sensor_path(family, n, fps):
    """Per-frame sensor-1 positions for the conditioning test (straight = degenerate)."""
    sp = []
    for i in range(n):
        t = i / fps
        if family == "straight":
            p = (100.0 * t, 0.0, 0.0)
        elif family == "orbit":
            a = t * 0.1
            p = (2000 * math.cos(a), 2000 * math.sin(a), 500.0)
        else:  # turn
            a = t * 0.02
            p = (100.0 * t, 1500 * math.sin(a), 200.0)
        sp += list(p)
    return sp


def bearing_rays(sensor_pos_flat, T, noise):
    """LOS dirs from each sensor frame to the true target, plus rotation noise."""
    n = len(sensor_pos_flat) // 3
    ld = []
    for i in range(n):
        b = i * 3
        d = [T[0] - sensor_pos_flat[b], T[1] - sensor_pos_flat[b + 1], T[2] - sensor_pos_flat[b + 2]]
        m = math.hypot(*d) or 1.0
        x, y, z = d[0] / m, d[1] / m, d[2] / m
        if noise > 0:
            a = rng.gauss(0, noise); bb = rng.gauss(0, noise)
            x1 = x * math.cos(a) - y * math.sin(a); y1 = x * math.sin(a) + y * math.cos(a)
            y2 = y1 * math.cos(bb) - z * math.sin(bb); z2 = y1 * math.sin(bb) + z * math.cos(bb)
            x, y, z = x1, y2, z2
        ld += [x * m, y * m, z * m]
    return ld


# ---------- nested run ----------

def run(worlds=200):
    # A run is reproducible even when invoked repeatedly in one process.
    rng.seed(WORLD_SEED)
    cond_correct = 0      # single-sensor verdict matched a sensible expectation
    cond_total = 0
    tri_solved = 0
    tri_total = 0
    range_covered = 0     # true range fell within the quoted uncertainty bound
    tri_errs = []         # (noise, baseline/range ratio, measured err, claimed range)
    stability_flags = 0   # times stability said UNSTABLE
    misconf = 0           # triangulation 'solvable' but error huge AND miss tiny (overconfident)

    for w in range(worlds):
        W = draw_world()
        T, s1, s2, noise, n, fps = W["T"], W["s1"], W["s2"], W["noise"], W["n"], W["fps"]
        base = W["base"]

        # --- single-sensor conditioning (the flag) ---
        sp = sensor_path(W["family"], n, fps)
        ld = bearing_rays(sp, T, noise)
        rec = {"sensor_pos": sp, "los_dir": ld, "fps": fps, "sensor_count": 1,
               "position_units": "m", "coordinate_frame": "ENU",
               "bearing_units": "dimensionless"}
        a = assess_sighting(rec)
        flag = a["underdetermination"]
        cond_total += 1
        # expectation: 'straight' -> poor; orbit/turn -> not-necessarily-poor
        if W["family"] == "straight":
            cond_correct += (flag["conditioning"] == "poor")
        else:
            cond_correct += (flag["conditioning"] in ("marginal", "good", "poor"))  # any valid
        if flag.get("stability") and flag["stability"].get("stable") is False:
            stability_flags += 1

        # --- two-sensor triangulation (the fix) ---
        ld1 = bearing_rays([s1[0], s1[1], s1[2]] * n, T, noise)
        ld2 = bearing_rays([s2[0], s2[1], s2[2]] * n, T, noise)
        trec = {"sensor_pos": [s1[0], s1[1], s1[2]] * n, "los_dir": ld1,
                 "sensor_pos_2": [s2[0], s2[1], s2[2]] * n, "los_dir_2": ld2,
                 "fps": fps, "bearing_noise_rad": noise, "time_sync_precision_s": 0,
                 "position_units": "m", "coordinate_frame": "ENU",
                 "bearing_units": "dimensionless", "bearing_noise_units": "rad"}
        tri = triangulate(trec)
        tri_total += 1
        if tri and tri.get("solvable"):
            tri_solved += 1
            true_range = math.dist(s1, T)
            err = math.dist(tri["position_m"], T)
            range_covered += abs(tri["range_m"] - true_range) <= tri["sigma_range_m"]
            ratio = base / true_range
            tri_errs.append((noise, ratio, err, tri["range_m"], true_range, tri["miss_distance_m"]))
            # overconfidence: an established solve claims a clean result but its
            # actual 3D error exceeds the 5% confidence threshold.
            if (tri.get("confident") and tri["miss_distance_m"] < 1.0 and
                    err > 0.05 * true_range):
                misconf += 1

    print(f"WORLDS: {worlds}")
    print(f"single-sensor conditioning: {cond_correct}/{cond_total} verdicts behaved as expected")
    print(f"  stability flagged UNSTABLE in {stability_flags} worlds")
    print(f"two-sensor triangulation:   {tri_solved}/{tri_total} solvable")
    print(f"  overconfident solves (clean miss, big true error): {misconf}")
    print(f"  quoted range bound coverage: {range_covered}/{tri_solved} "
          f"({range_covered / max(tri_solved, 1):.1%})")

    if tri_errs:
        # Characterize error by noise level inside the fixed synthetic distribution.
        print("\nTRIANGULATION SYNTHETIC COVERAGE (relative error vs noise):")
        by_noise = {}
        for noise, ratio, err, cr, tr, miss in tri_errs:
            by_noise.setdefault(noise, []).append(err / tr)
        for noise in sorted(by_noise):
            rel = sorted(by_noise[noise])
            med = rel[len(rel) // 2]
            p90 = rel[int(len(rel) * 0.9)]
            print(f"  noise={noise:8.1e}  worlds={len(rel):4d}  median rel.err={med:7.4%}  p90={p90:7.4%}")

        # Descriptive association uncertainty, conditional on a solvable result.
        pairs = [(math.log(max(r, 1e-6)), math.log(e))
                 for _, r, e, *_ in tri_errs if e > 0]
        if len(pairs) > 3:
            assoc = pearson_pairs_bootstrap(pairs)
            print("\nPearson association uncertainty:")
            print("  corr(log baseline/range, log 3D error | solvable) "
                  f"r={assoc['r']:+.9f}")
            print(f"  method={assoc['method']} n={assoc['n']} B={assoc['B']} "
                  f"seed={assoc['seed']} valid_B={assoc['valid_B']}")
            print(f"  bootstrap_SE={assoc['bootstrap_se']:.9f} "
                  f"95% CI=[{assoc['ci_low']:.9f}, {assoc['ci_high']:.9f}] "
                  f"quantile={assoc['quantile_method']}")
            print(f"  estimand={assoc['estimand']}; descriptive audit diagnostic only")

    print("\nDETERMINISTIC SYNTHETIC COVERAGE AUDIT:",
          "PASS" if (misconf == 0 and tri_solved / max(tri_total, 1) > 0.9 and
                     range_covered / max(tri_solved, 1) >= 0.93) else "REVIEW")


if __name__ == "__main__":
    run(200)
