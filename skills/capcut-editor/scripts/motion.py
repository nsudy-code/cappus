"""Eased entrance and exit presets, written out as keyframes.

Each preset is one or two keyframe segments, each with a CapCut ease curve (easing.py): points are
[time, value] or [time, value, ease], the ease shaping the segment that ends at that point. In CapCut
the curve shows on the keyframe and can be changed there. A spec with "linear_keyframes": true gets
the old form instead: every curve sampled into several linear keyframes. Every preset ends exactly on
the item's resting state (its transform or style), so the item looks the same as without the preset
once it has played.
"""
from __future__ import annotations

import easing

# name -> (default duration, kinds it works on)
ENTER = {
    "pop": (0.35, {"overlay", "text"}),        # scale 1% -> 108% -> 100% (overlays also fade in)
    "punch": (0.25, {"overlay", "text"}),      # scale 125% -> 100%, a hard hit on a beat
    "rise": (0.35, {"overlay", "text"}),       # moves up into place (overlays also fade in)
    "drop": (0.4, {"overlay", "text"}),        # falls into place and settles
    "slide_left": (0.35, {"overlay", "text"}),   # comes in from the right, moving left
    "slide_right": (0.35, {"overlay", "text"}),  # comes in from the left, moving right
    "fade": (0.3, {"overlay"}),                # opacity 0 -> 1
    "grow_left": (0.45, {"overlay"}),          # width grows from the left edge (bars, underlines)
    "grow_right": (0.45, {"overlay"}),         # width grows from the right edge
    # kinetic typography: fast, hard entrances that land on a beat
    "slam": (0.12, {"overlay", "text"}),       # scale 190% -> 100%: the word hits the screen
    "slam_tilt": (0.13, {"overlay", "text"}),  # slam from 210% while untwisting 9 degrees
    "whip_left": (0.15, {"overlay", "text"}),  # flies in from beyond the right edge
    "whip_right": (0.15, {"overlay", "text"}), # flies in from beyond the left edge
    "fall": (0.14, {"overlay", "text"}),       # drops in from above
    "jump": (0.14, {"overlay", "text"}),       # shoots up from below
    "spin": (0.18, {"overlay", "text"}),       # spins in from -120 degrees while growing
}
EXIT = {
    "fade": (0.3, {"overlay"}),
    "shrink": (0.3, {"overlay", "text"}),
    "sink": (0.3, {"overlay", "text"}),        # moves down out of place (overlays also fade out)
    "slide_left": (0.3, {"overlay", "text"}),
    "slide_right": (0.3, {"overlay", "text"}),
    "zoom_through": (0.26, {"overlay", "text"}),  # scales to 14x: the camera flies through the word
}


# The curves the presets use (CapCut's own "Cubic Out" / "Cubic In" / "Cubic Ease" presets).
ease_out, ease_in, ease_in_out = "cubic_out", "cubic_in", "cubic_in_out"


def curve(a, b, t0, t1, ease=ease_out):
    """One eased segment from a to b between t0 and t1: [[t0, a], [t1, b, ease]]."""
    return [[round(t0, 4), round(a, 5)], [round(t1, 4), round(b, 5), ease]]


def _overshoot(a, peak, b, t0, t1, split=0.65):
    mid = t0 + (t1 - t0) * split
    return curve(a, peak, t0, mid, ease_out) + curve(peak, b, mid, t1, ease_in_out)[1:]


def enter_points(name, dur, rest, kind, width=0.0):
    """Keyframes for an entrance over [0, dur]. rest: {"x", "y", "scale", "opacity"} at rest.
    width: the item's width in half-canvas units (grow presets only)."""
    x, y, s, o = rest["x"], rest["y"], rest["scale"], rest["opacity"]
    r = rest.get("rotation", 0.0)
    fade = kind == "overlay"
    out = {}
    if name == "slam":
        out["scale"] = curve(1.9 * s, s, 0, dur, ease_out)
    elif name == "slam_tilt":
        out["scale"] = curve(2.1 * s, s, 0, dur, ease_out)
        out["rotation"] = curve(r - 9, r, 0, dur, ease_out)
    elif name in ("whip_left", "whip_right"):
        out["x"] = curve(x + (1.3 if name == "whip_left" else -1.3), x, 0, dur, ease_out)
    elif name in ("fall", "jump"):
        out["y"] = curve(y + (0.35 if name == "fall" else -0.35), y, 0, dur, ease_out)
    elif name == "spin":
        out["rotation"] = curve(r - 120, r, 0, dur, ease_out)
        out["scale"] = curve(0.3 * s, s, 0, dur, ease_out)
    elif name == "pop":
        out["scale"] = _overshoot(0.01 * s, 1.08 * s, s, 0, dur)
        if fade:
            out["opacity"] = curve(0, o, 0, dur * 0.4, ease_out)
    elif name == "punch":
        out["scale"] = curve(1.25 * s, s, 0, dur, ease_out)
    elif name == "rise":
        out["y"] = curve(y - 0.06, y, 0, dur)
        if fade:
            out["opacity"] = curve(0, o, 0, dur, ease_out)
    elif name == "drop":
        out["y"] = _overshoot(y + 0.08, y - 0.012, y, 0, dur, 0.7)
    elif name in ("slide_left", "slide_right"):
        start = x + (0.4 if name == "slide_left" else -0.4)
        out["x"] = curve(start, x, 0, dur)
        if fade:
            out["opacity"] = curve(0, o, 0, dur * 0.6, ease_out)
    elif name == "fade":
        out["opacity"] = curve(0, o, 0, dur, ease_out)
    elif name in ("grow_left", "grow_right"):
        pts = curve(0.01, 1.0, 0, dur)
        edge = x - width / 2 if name == "grow_left" else x + width / 2
        sign = 1 if name == "grow_left" else -1
        out["scale_x"] = [[p[0], p[1] * s, *p[2:]] for p in pts]
        out["x"] = [[p[0], round(edge + sign * p[1] * width / 2, 5), *p[2:]] for p in pts]
    else:
        raise ValueError(name)
    return out


def exit_points(name, dur, total, rest, kind):
    """Keyframes for an exit over [total - dur, total]."""
    x, y, s, o = rest["x"], rest["y"], rest["scale"], rest["opacity"]
    t0, fade = total - dur, kind == "overlay"
    out = {}
    if name == "zoom_through":
        out["scale"] = curve(s, 14 * s, t0, total, ease_in)
    elif name == "fade":
        out["opacity"] = curve(o, 0, t0, total, ease_in)
    elif name == "shrink":
        out["scale"] = curve(s, 0.01 * s, t0, total, ease_in)
    elif name == "sink":
        out["y"] = curve(y, y - 0.06, t0, total, ease_in)
        if fade:
            out["opacity"] = curve(o, 0, t0, total, ease_in)
    elif name in ("slide_left", "slide_right"):
        out["x"] = curve(x, x + (-0.4 if name == "slide_left" else 0.4), t0, total, ease_in)
        if fade:
            out["opacity"] = curve(o, 0, t0 + dur * 0.4, total, ease_in)
    else:
        raise ValueError(name)
    return out


def value_at(points, t):
    """Value at t through [[time, value, ease?], ...] (sorted), following each segment's ease."""
    return easing.value_at(points, t)


def merge(base, added, window, where):
    """Combine preset keyframes with keyframes the spec already has on the same property.

    base points inside the preset's window [w0, w1] are replaced; the preset's end that touches the
    rest of the curve is moved onto that curve, so a slow drift (or a motion preset) carries on from
    where the entrance ends without a jump. Returns the merged, sorted points."""
    w0, w1 = window
    if not base:
        return added
    outside = [p for p in base if not (w0 <= p[0] <= w1)]
    added = [list(p) for p in added]
    if where == "enter":
        added[-1][1] = round(value_at(base, w1), 5)
    else:
        added[0][1] = round(value_at(base, w0), 5)
    return sorted(outside + added, key=lambda p: p[0])
