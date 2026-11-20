"""Eased keyframes in CapCut drafts.

CapCut desktop (checked in 9.8.0) stores the speed curve of a keyframe segment as a cubic bezier, the
same shape as CSS cubic-bezier(x1, y1, x2, y2). For a segment from keyframe A to keyframe B, lasting D
microseconds and changing the value by dv:

    A.right_control = {x: x1 * D,       y: y1 * dv}
    B.left_control  = {x: (x2 - 1) * D, y: (y2 - 1) * dv}

Both keyframes get "curveType": "FreeCurveInOut" (a keyframe with no eased segment on either side
stays "Line"). When the curve is one of CapCut's preset curves, B's "graphID" names an entry of the
draft's top-level "keyframe_graph_list": {id, resource_id, resource_name, source_platform: 1,
graph_points: []}. The table below was read from drafts CapCut saved after each preset was picked
from a keyframe's "Show all presets" panel.
"""
from __future__ import annotations

import uuid

from pycapcut.keyframe import Keyframe

# spec name -> (CSS cubic-bezier, CapCut preset name, CapCut resource id)
PRESETS = {
    "ease_in": ((0.42, 0.0, 1.0, 1.0), "Ease In", "7002056185805279746"),
    "ease_out": ((0.0, 0.0, 0.58, 1.0), "Ease Out", "7002056258991690241"),
    "ease_in_out": ((0.42, 0.0, 0.58, 1.0), "Ease", "7418178875479298577"),
    "quad_in": ((0.26, 0.0, 0.6, 0.2), "Quad In", "7034098736649212417"),
    "quad_out": ((0.4, 0.8, 0.74, 1.0), "Quad Out", "7034098855750668802"),
    "quad_in_out": ((0.48, 0.04, 0.52, 0.96), "Quad Ease", "7418179015053152769"),
    "cubic_in": ((0.4, 0.0, 0.68, 0.06), "Cubic In", "7034098790596350465"),
    "cubic_out": ((0.32, 0.94, 0.6, 1.0), "Cubic Out", "7034098919583781377"),
    "cubic_in_out": ((0.66, 0.0, 0.34, 1.0), "Cubic Ease", "7418179096141632017"),
    "circ_in_out": ((0.88, 0.14, 0.12, 0.86), "Circular Ease", "7418179193537565185"),
    "back_in": ((0.6, -0.28, 0.73, 0.04), "Rebound In", "7418179307631022593"),
    "back_out": ((0.17, 0.89, 0.32, 1.27), "Rebound Out", "7418179396713845249"),
}
NAMES = ["linear", *PRESETS]


class EaseError(ValueError):
    pass


def parse(value, ctx):
    """A spec ease -> None (linear) or (bezier, preset name or None).

    Accepts a name from NAMES or a custom curve [x1, y1, x2, y2] (x1 and x2 between 0 and 1)."""
    if value is None or value == "linear":
        return None
    if isinstance(value, str):
        if value not in PRESETS:
            raise EaseError(f"{ctx}: unknown ease {value!r}. Eases: {NAMES}, or a curve [x1, y1, x2, y2]")
        return PRESETS[value][0], value
    if (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        x1, y1, x2, y2 = map(float, value)
        if not (0 <= x1 <= 1 and 0 <= x2 <= 1):
            raise EaseError(f"{ctx}: in a curve [x1, y1, x2, y2], x1 and x2 must be between 0 and 1, got {list(value)}")
        if max(abs(y1), abs(y2)) > 4:
            raise EaseError(f"{ctx}: curve y values must be between -4 and 4, got {list(value)}")
        return (x1, y1, x2, y2), None
    raise EaseError(f"{ctx}: an ease is a name ({', '.join(NAMES)}) or a curve [x1, y1, x2, y2], got {value!r}")


def bezier_at(curve, u):
    """Eased progress (0..1, may overshoot) at linear progress u (0..1) along a cubic-bezier curve."""
    x1, y1, x2, y2 = curve
    if u <= 0 or u >= 1:
        return min(max(u, 0.0), 1.0)

    def b(p1, p2, s):
        return 3 * (1 - s) ** 2 * s * p1 + 3 * (1 - s) * s * s * p2 + s ** 3

    lo, hi = 0.0, 1.0
    for _ in range(50):  # x(s) is monotonic since x1, x2 are in [0, 1]
        mid = (lo + hi) / 2
        if b(x1, x2, mid) < u:
            lo = mid
        else:
            hi = mid
    return b(y1, y2, (lo + hi) / 2)


def sample(points, n=6):
    """Points [[t, v, ease?], ...] -> plain linear points, each eased segment sampled n times.

    The linear fallback, for drafts that must not carry curves."""
    out = []
    for i, p in enumerate(points):
        if i == 0:
            out.append([p[0], p[1]])
            continue
        prev = points[i - 1]
        parsed = parse(p[2], "ease") if len(p) > 2 else None
        if parsed is None:
            out.append([p[0], p[1]])
            continue
        curve = parsed[0]
        for k in range(1, n + 1):
            u = k / n
            out.append([round(prev[0] + (p[0] - prev[0]) * u, 4),
                        round(prev[1] + (p[1] - prev[1]) * bezier_at(curve, u), 5)])
    return out


def value_at(points, t):
    """Value at time t through points [[t, v, ease?], ...] (sorted), following each segment's curve."""
    if t <= points[0][0]:
        return points[0][1]
    for a, b in zip(points, points[1:]):
        if a[0] <= t <= b[0]:
            if b[0] == a[0]:
                return a[1]
            u = (t - a[0]) / (b[0] - a[0])
            parsed = parse(b[2], "ease") if len(b) > 2 else None
            return a[1] + (b[1] - a[1]) * (bezier_at(parsed[0], u) if parsed else u)
    return points[-1][1]


# ---------- writing curves into pycapcut keyframes ----------

def _export(self):
    """Keyframe.export_json that also writes the bezier handles CapCut reads."""
    left = getattr(self, "_left", None)
    right = getattr(self, "_right", None)
    out = {
        "curveType": "FreeCurveInOut" if (left or right) else "Line",
        "graphID": getattr(self, "_graph", ""),
        "left_control": {"x": float(left[0]), "y": float(left[1])} if left else {"x": 0.0, "y": 0.0},
        "right_control": {"x": float(right[0]), "y": float(right[1])} if right else {"x": 0.0, "y": 0.0},
        "id": self.kf_id,
        "time_offset": self.time_offset,
        "values": self.values,
    }
    return out


def install():
    """Make pycapcut write eased keyframes (a linear keyframe exports exactly as before)."""
    if Keyframe.export_json is not _export:
        Keyframe.export_json = _export


class Graphs:
    """The draft's keyframe_graph_list: one entry per eased segment that uses a CapCut preset."""

    def __init__(self):
        self.items: list = []

    def add(self, preset: str) -> str:
        _, name, resource = PRESETS[preset]
        gid = str(uuid.uuid4()).upper()
        self.items.append({"id": gid, "resource_id": resource, "resource_name": name,
                           "source_platform": 1, "graph_points": []})
        return gid


def apply(kf_list, eases: dict, graphs: Graphs):
    """Shape the segments of one pycapcut KeyframeList.

    eases: {time_offset_us: parsed ease} for the keyframe that ENDS each eased segment (the same keyframe
    CapCut attaches a preset to). A keyframe with no segment before it has nothing to shape."""
    kfs = kf_list.keyframes
    for a, b in zip(kfs, kfs[1:]):
        parsed = eases.get(b.time_offset)
        if not parsed:
            continue
        (x1, y1, x2, y2), preset = parsed
        d = b.time_offset - a.time_offset
        dv = b.values[0] - a.values[0]
        if d <= 0:
            continue
        a._right = (x1 * d, y1 * dv)
        b._left = ((x2 - 1) * d, (y2 - 1) * dv)
        if preset:
            b._graph = graphs.add(preset)
