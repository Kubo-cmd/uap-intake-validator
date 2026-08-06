"""Numerical conditioning assessment for bearing-only 3D observations.

The implementation uses only the Python standard library.  Symmetric
six-by-six eigenvalues are computed by a cyclic Jacobi iteration: every
off-diagonal pair is annihilated in a fixed sweep order with an orthogonal
plane rotation, and sweeps stop when the off-diagonal norm is negligible.
"""

import math


_MAX_FRAMES = 10000
LINEAR_RCOND_POOR = 10.0 ** -2.5
LINEAR_RCOND_MARGINAL = 10.0 ** -2.0
_POOR_LIMIT = LINEAR_RCOND_POOR
_GOOD_LIMIT = LINEAR_RCOND_MARGINAL


def _failure(message):
    return {
        "rcond": 0.0,
        "log10Rcond": float("-inf"),
        "effectiveRank": 0,
        "conditioning": "poor",
        "error": str(message),
    }


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("input contains a non-numeric value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("input contains a non-numeric value")
    if not math.isfinite(number):
        raise ValueError("input contains a non-finite value")
    return number


def _flat_xyz(values, name):
    if isinstance(values, (str, bytes)):
        raise ValueError(name + " must be a flat xyz sequence")
    try:
        size = len(values)
    except (TypeError, OverflowError):
        raise ValueError(name + " must be a sized flat xyz sequence")
    if size % 3:
        raise ValueError(name + " length must be divisible by three")
    frames = size // 3
    if frames > _MAX_FRAMES:
        raise ValueError("frame count exceeds 10000")
    result = []
    for index in range(size):
        try:
            result.append(_finite_number(values[index]))
        except (IndexError, KeyError):
            raise ValueError(name + " is not a valid flat sequence")
    return result, frames


def _time_coordinates(times, fps, frames):
    if times is not None:
        if isinstance(times, (str, bytes)):
            raise ValueError("times must be a sequence")
        try:
            if len(times) != frames:
                raise ValueError("times length does not match frame count")
        except TypeError:
            raise ValueError("times must be a sized sequence")
        raw = [_finite_number(times[index]) for index in range(frames)]
    else:
        if fps is not None:
            rate = _finite_number(fps)
            if rate <= 0.0:
                raise ValueError("fps must be positive")
        else:
            rate = 1.0
        raw = [index / rate for index in range(frames)]

    if not raw:
        raise ValueError("at least one frame is required")
    low = min(raw)
    high = max(raw)
    if high == low:
        return [0.0] * frames
    midpoint = 0.5 * (low + high)
    half_span = 0.5 * (high - low)
    return [(value - midpoint) / half_span for value in raw]


def _unit_bearings(values, frames):
    bearings = []
    for frame in range(frames):
        offset = 3 * frame
        x, y, z = values[offset:offset + 3]
        norm = math.sqrt(x * x + y * y + z * z)
        if not math.isfinite(norm) or norm == 0.0:
            raise ValueError("line-of-sight bearing must be nonzero and finite")
        bearings.append((x / norm, y / norm, z / norm))
    return bearings


def _normal_matrix(bearings, taus):
    normal = [[0.0] * 6 for _ in range(6)]
    for direction, tau in zip(bearings, taus):
        projection = [[0.0] * 3 for _ in range(3)]
        for row in range(3):
            for column in range(3):
                projection[row][column] = (
                    (1.0 if row == column else 0.0)
                    - direction[row] * direction[column]
                )
        # P is symmetric and idempotent, so B^T B has blocks
        # P, tau*P, and tau^2*P for B = [P, tau*P].
        for row in range(3):
            for column in range(3):
                value = projection[row][column]
                normal[row][column] += value
                normal[row][column + 3] += tau * value
                normal[row + 3][column] += tau * value
                normal[row + 3][column + 3] += tau * tau * value
    return normal


def _equilibrate(matrix):
    scales = []
    for index in range(6):
        diagonal = matrix[index][index]
        scales.append(1.0 / math.sqrt(diagonal) if diagonal > 0.0 else 0.0)
    return [
        [matrix[row][column] * scales[row] * scales[column] for column in range(6)]
        for row in range(6)
    ]


def _symmetric_eigenvalues(matrix):
    """Return eigenvalues using fixed-order cyclic Jacobi rotations.

    A sweep visits all 15 upper-triangle pairs.  Each rotation zeros one
    pair while preserving symmetry and eigenvalues.  The iteration ends
    after convergence of the off-diagonal Frobenius norm or 100 sweeps.
    """
    a = [row[:] for row in matrix]
    size = len(a)
    for _sweep in range(100):
        off_squared = 0.0
        diagonal_squared = 0.0
        for row in range(size):
            diagonal_squared += a[row][row] * a[row][row]
            for column in range(row + 1, size):
                off_squared += 2.0 * a[row][column] * a[row][column]
        if off_squared <= 1e-30 * max(1.0, diagonal_squared):
            break

        for p in range(size - 1):
            for q in range(p + 1, size):
                apq = a[p][q]
                if apq == 0.0:
                    continue
                tau = (a[q][q] - a[p][p]) / (2.0 * apq)
                if tau >= 0.0:
                    tangent = 1.0 / (tau + math.sqrt(1.0 + tau * tau))
                else:
                    tangent = -1.0 / (-tau + math.sqrt(1.0 + tau * tau))
                cosine = 1.0 / math.sqrt(1.0 + tangent * tangent)
                sine = tangent * cosine
                app = a[p][p]
                aqq = a[q][q]
                a[p][p] = app - tangent * apq
                a[q][q] = aqq + tangent * apq
                a[p][q] = 0.0
                a[q][p] = 0.0
                for k in range(size):
                    if k == p or k == q:
                        continue
                    akp = a[k][p]
                    akq = a[k][q]
                    new_kp = cosine * akp - sine * akq
                    new_kq = sine * akp + cosine * akq
                    a[k][p] = new_kp
                    a[p][k] = new_kp
                    a[k][q] = new_kq
                    a[q][k] = new_kq
    return sorted(a[index][index] for index in range(size))


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def _collapse_diagnostics(sensors, positions, bearings, frames):
    signed_ranges = []
    on_sensor = 0
    behind = 0
    for frame in range(frames):
        offset = 3 * frame
        delta = (
            positions[offset] - sensors[offset],
            positions[offset + 1] - sensors[offset + 1],
            positions[offset + 2] - sensors[offset + 2],
        )
        distance = math.sqrt(sum(component * component for component in delta))
        signed = sum(delta[index] * bearings[frame][index] for index in range(3))
        signed_ranges.append(signed)
        if distance <= 1e-6:
            on_sensor += 1
        if signed < 0.0:
            behind += 1

    on_fraction = on_sensor / float(frames)
    behind_fraction = behind / float(frames)
    if on_sensor:
        reason = "position_on_sensor"
    elif behind_fraction > 0.5:
        reason = "positions_behind_sensor"
    else:
        reason = None
    return {
        "onSensorFraction": on_fraction,
        "behindSensorFraction": behind_fraction,
        "medianSignedRangeM": _median(signed_ranges),
        "collapseReason": reason,
        "collapse": reason is not None,
    }


def assess_conditioning(sensor_pos, los_dir, times=None, fps=None, positions=None):
    """Assess constant-velocity bearing geometry without raising on bad input."""
    try:
        sensors, frames = _flat_xyz(sensor_pos, "sensor_pos")
        directions, direction_frames = _flat_xyz(los_dir, "los_dir")
        if frames != direction_frames:
            raise ValueError("sensor_pos and los_dir frame counts do not match")
        taus = _time_coordinates(times, fps, frames)
        bearings = _unit_bearings(directions, frames)

        position_values = None
        if positions is not None:
            position_values, position_frames = _flat_xyz(positions, "positions")
            if position_frames != frames:
                raise ValueError("positions frame count does not match")

        eigenvalues = _symmetric_eigenvalues(
            _equilibrate(_normal_matrix(bearings, taus))
        )
        largest = max(eigenvalues)
        if not math.isfinite(largest) or largest <= 0.0:
            rcond = 0.0
            rank = 0
        else:
            smallest = min(eigenvalues)
            rcond = math.sqrt(max(0.0, smallest) / largest)
            rank = sum(value > 1e-10 * largest for value in eigenvalues)
        log_rcond = math.log10(rcond) if rcond > 0.0 else float("-inf")
        if rcond < _POOR_LIMIT:
            label = "poor"
        elif rcond < _GOOD_LIMIT:
            label = "marginal"
        else:
            label = "good"
        result = {
            "rcond": rcond,
            "log10Rcond": log_rcond,
            "effectiveRank": rank,
            "conditioning": label,
        }
        if position_values is not None:
            result.update(_collapse_diagnostics(
                sensors, position_values, bearings, frames
            ))
        return result
    except Exception as exc:
        return _failure(exc)
