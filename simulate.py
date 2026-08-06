#!/usr/bin/env python3
"""simulate — Monte-Carlo validation of the underdetermination flag.

Goal: confirm the flag is a RELIABLE one-way warning before shipping.
  - degenerate geometry  -> must read 'poor' (catch the trap)
  - well-posed geometry  -> must NOT read 'poor' (no false alarms)

The load-bearing claim (from Sitrec BOT Bench): 'poor' is a warning, 'good'
is not proof. A correct implementation has ZERO false-good on degenerate cases
and (ideally) zero false-poor on well-posed cases.
"""
import math
import random

from validator import assess_sighting, triangulate

random.seed(37)

def sightlines_for(sensor_xyz_list, target_xyz_list):
    sp, ld = [], []
    for (sx, sy, sz), (tx, ty, tz) in zip(sensor_xyz_list, target_xyz_list):
        sp += [sx, sy, sz]
        dx, dy, dz = tx - sx, ty - sy, tz - sz
        n = math.sqrt(dx*dx + dy*dy + dz*dz) or 1.0
        ld += [dx/n, dy/n, dz/n]
    return sp, ld

def base_record(sp, ld, motion):
    return {
        "timestamp_utc": "2026-05-01T14:22:00Z",
        "time_sync_precision_s": 2,
        "sensor_position": [34.0, -118.0, 7600],
        "position_datum": "WGS84",
        "field_of_view_deg": 0.7,
        "bearing_count": len(sp)//3,
        "sensor_type": "IR pod",
        "platform_motion": motion,
        "fps": 1.0,
        "sensor_pos": sp,
        "los_dir": ld,
    }

def run_case(name, n, sensor_fn, target_fn):
    sensor = [sensor_fn(i) for i in range(n)]
    target = [target_fn(i) for i in range(n)]
    sp, ld = sightlines_for(sensor, target)
    r = assess_sighting(base_record(sp, ld, name))
    u = r.get("underdetermination") or {}
    return r["verdict"], u.get("conditioning"), u.get("rcond"), u.get("log10Rcond"), u.get("effectiveRank")

# ── DEGENERATE family (must flag 'poor') ─────────────────────────────
# straight-and-level sensor, target fixed ahead — the classic collapse case
def straight(n=60):
    return run_case(
        "straight-level", n,
        lambda i: (100.0*i, 0.0, 0.0),
        lambda i: (5000.0, 0.0, 1000.0),
    )

# constant-velocity object, sensor straight — still CV-family degenerate geometry
def cv_object_straight_sensor(n=60):
    return run_case(
        "cv-object/straight-sensor", n,
        lambda i: (50.0*i, 0.0, 0.0),
        lambda i: (4000.0 + 20.0*i, 0.0, 900.0),
    )

# ── WELL-POSED family (must NOT flag 'poor') ─────────────────────────
# orbiting sensor around a fixed target — strong parallax
def orbit(n=120):
    def s(i):
        a = 2*math.pi*i/n
        return (8000.0*math.cos(a), 8000.0*math.sin(a), 0.0)
    return run_case("orbit", n, s, lambda i: (0.0, 0.0, 500.0))

# two-segment parallax (sensor turns once)
def turn(n=120):
    def s(i):
        if i < n//2:
            return (50.0*i, 0.0, 0.0)
        j = i - n//2
        return (50.0*(n//2), 40.0*j, 0.0)
    return run_case("single-turn", n, s, lambda i: (6000.0, 3000.0, 800.0))

cases = [
    ("DEGENERATE", "straight-level", straight),
    ("DEGENERATE", "cv-object/straight-sensor", cv_object_straight_sensor),
    ("WELL-POSED", "orbit", orbit),
    ("WELL-POSED", "single-turn", turn),
]

print(f"{'expect':<11} {'case':<26} {'verdict':<28} {'cond':<9} {'log10rcond':>10} {'rank':>4}  result")
print("-"*95)
false_good = 0
false_poor = 0
for expect, name, fn in cases:
    verdict, cond, rcond, logr, rank = fn()
    logr_s = f"{logr:10.2f}" if isinstance(logr, float) else f"{'—':>10}"
    rank_s = f"{rank:4}" if isinstance(rank, int) else f"{'—':>4}"
    if expect == "DEGENERATE":
        ok = (cond == "poor")
        if not ok: false_good += 1
        tag = "OK (caught trap)" if ok else "!! FALSE-GOOD (missed degenerate)"
    else:
        ok = (cond != "poor")
        if not ok: false_poor += 1
        tag = "OK (no false alarm)" if ok else "!! FALSE-POOR (condemned good geometry)"
    print(f"{expect:<11} {name:<26} {verdict:<28} {str(cond):<9} {logr_s} {rank_s}  {tag}")

print("-"*95)
print(f"FALSE-GOOD (degenerate not flagged): {false_good}  <- must be 0 (one-way warning holds)")
print(f"FALSE-POOR (good geometry condemned): {false_poor}  <- should be 0 (no false alarms)")
det_pass = (false_good == 0 and false_poor == 0)

# ── RANDOMIZED MONTE-CARLO SWEEP ─────────────────────────────────────
# Perturb bearing angles with Gaussian noise (operator wobble) across geometry
# families + noise levels. Measure false-good (degenerate missed) and
# false-poor (good geometry condemned) rates. This is the real ship evidence.
def noisy_record(sensor, target, sigma_rad, motion):
    sp, ld = [], []
    for (sx, sy, sz), (tx, ty, tz) in zip(sensor, target):
        sp += [sx, sy, sz]
        dx, dy, dz = tx - sx, ty - sy, tz - sz
        n = math.sqrt(dx*dx+dy*dy+dz*dz) or 1.0
        # perturb the bearing by small angular noise
        a = random.gauss(0, sigma_rad); b = random.gauss(0, sigma_rad)
        ld += [(dx/n)+a, (dy/n)+b, dz/n]
    return base_record(sp, ld, motion)

def mc_family(expect, name, n, sensor_fn, target_fn, sigmas, trials=40):
    fg = fp = 0
    for s in sigmas:
        for _ in range(trials):
            sensor = [sensor_fn(i) for i in range(n)]
            target = [target_fn(i) for i in range(n)]
            u = (assess_sighting(noisy_record(sensor, target, s, name)).get("underdetermination") or {})
            cond = u.get("conditioning")
            if expect == "DEG" and cond != "poor": fg += 1
            if expect == "WP" and cond == "poor": fp += 1
    tot = len(sigmas)*trials
    return fg, fp, tot

SIGMAS = [0.0, 1e-4, 5e-4, 1e-3]  # radians ~ up to ~0.06 deg operator wobble
mc_fg = mc_fp = mc_tot = 0
print()
print("MONTE-CARLO SWEEP (bearing noise, 40 trials per noise level)")
print(f"{'expect':<6} {'family':<26} {'false-good':>10} {'false-poor':>10} {'trials':>7}")
print("-"*65)

mc_defs = [
    ("DEG", "straight-level", 60,
        lambda i:(100.0*i,0,0), lambda i:(5000.0,0,1000.0)),
    ("DEG", "cv-object/straight-sensor", 60,
        lambda i:(50.0*i,0,0), lambda i:(4000.0+20.0*i,0,900.0)),
    ("WP", "orbit", 120,
        lambda i:(8000.0*math.cos(2*math.pi*i/120),8000.0*math.sin(2*math.pi*i/120),0),
        lambda i:(0.0,0.0,500.0)),
    ("WP", "single-turn", 120,
        lambda i:(50.0*i,0,0) if i<60 else (3000.0,40.0*(i-60),0),
        lambda i:(6000.0,3000.0,800.0)),
]
for expect, name, n, sf, tf in mc_defs:
    fg, fp, tot = mc_family(expect, name, n, sf, tf, SIGMAS)
    mc_fg += fg; mc_fp += fp; mc_tot += tot
    print(f"{expect:<6} {name:<26} {fg:>10} {fp:>10} {tot:>7}")

print("-"*65)
print(f"TOTALS  false-good={mc_fg}  false-poor={mc_fp}  trials={mc_tot}")
print(f"false-good rate (must be ~0): {mc_fg/mc_tot:.3%}")
print(f"false-poor rate (should be ~0): {mc_fp/mc_tot:.3%}")
mc_pass = (mc_fg == 0 and mc_fp == 0)
print()
print("SHIP GATE:", "PASS" if (det_pass and mc_pass) else "REVIEW — see rates above")


# ---------- two-sensor triangulation regression ----------

def tri_regression():
    """Two sensors on a baseline, target at known truth. Triangulation must
    recover the position, and degrade gracefully under bearing noise."""
    import math as _m, random as _r
    print("TRIANGULATION REGRESSION")
    print("-" * 70)
    T = (5000.0, 3000.0, 1000.0)
    s1, s2 = (0.0, 0.0, 0.0), (2000.0, 0.0, 0.0)

    def rays(sensor, n=30):
        sp, ld = [], []
        for _ in range(n):
            sp += list(sensor)
            ld += [T[0]-sensor[0], T[1]-sensor[1], T[2]-sensor[2]]
        return sp, ld

    # 1) noise-free: must recover truth exactly
    sp1, ld1 = rays(s1); sp2, ld2 = rays(s2)
    rec = {"sensor_pos": sp1, "los_dir": ld1, "sensor_pos_2": sp2,
           "los_dir_2": ld2, "fps": 30, "bearing_noise_rad": 0,
           "time_sync_precision_s": 0}
    tri = triangulate(rec)
    err = _m.dist(tri["position_m"], T) if tri.get("solvable") else float("inf")
    print(f"  noise-free: solved={tri.get('solvable')} pos_err={err:.4f} m  "
          f"{'OK' if tri.get('solvable') and err < 1e-6 else 'FAIL'}")

    # 2) noise sweep: HONEST rotation noise (additive component noise is partly
    #    absorbed by the unit-normalize inside triangulate — that model is wrong).
    def perturb(ld, ang, rng):
        out = list(ld)
        for i in range(len(ld) // 3):
            b = i * 3
            x, y, z = ld[b], ld[b+1], ld[b+2]
            n = _m.hypot(x, y, z) or 1.0
            x, y, z = x/n, y/n, z/n
            a = rng.gauss(0, ang); bb = rng.gauss(0, ang)
            x1 = x*_m.cos(a) - y*_m.sin(a); y1 = x*_m.sin(a) + y*_m.cos(a)
            y2 = y1*_m.cos(bb) - z*_m.sin(bb); z2 = y1*_m.sin(bb) + z*_m.cos(bb)
            out[b], out[b+1], out[b+2] = x1*n, y2*n, z2*n
        return out

    rng = _r.Random(11)
    prev = -1.0
    mono = True
    for noise in (0.0, 1e-4, 5e-4, 1e-3, 2e-3):
        errs = []
        for _ in range(40):
            nld1 = perturb(ld1, noise, rng)
            nld2 = perturb(ld2, noise, rng)
            t2 = triangulate({"sensor_pos": sp1, "los_dir": nld1,
                              "sensor_pos_2": sp2, "los_dir_2": nld2, "fps": 30,
                              "bearing_noise_rad": noise, "time_sync_precision_s": 0})
            if t2.get("solvable"):
                errs.append(_m.dist(t2["position_m"], T))
        med = sorted(errs)[len(errs)//2] if errs else float("nan")
        if med < prev - 1e-9:
            mono = False
        prev = med
        print(f"  noise={noise:8.1e} rad -> median pos err {med:8.2f} m over {len(errs)} solves")
    print(f"  error monotonic in noise: {mono}  {'OK' if mono else 'FAIL'}")
    print()

if __name__ == "__main__":
    tri_regression()
