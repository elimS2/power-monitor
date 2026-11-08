"""Day-long voltage chart: our Deye samples, actual outages, queue schedule ahead."""
from __future__ import annotations

from datetime import datetime, timedelta

from config import UA_TZ

Y_MIN = 180.0
Y_MAX = 260.0
LIMIT_LO = 195.0
LIMIT_HI = 245.0
HISTORY_SEC = 24 * 3600
FUTURE_SEC = 6 * 3600
BUCKET_SEC = 60

_W = 640.0
_H = 236.0
_LEFT = 34.0
_RIGHT = 8.0
_TOP = 16.0
_PLOT_H = 168.0
_STRIP_GAP = 7.0
_STRIP_H = 11.0

_PHASES = (
    ("l1", "#fb7185"),
    ("l2", "#facc15"),
    ("l3", "#60a5fa"),
)


def build_voltage_chart(
    *,
    now: float,
    buckets: list[dict],
    today: dict | None,
    tomorrow: dict | None,
    queue: str,
    history_sec: int = HISTORY_SEC,
    future_sec: int = FUTURE_SEC,
) -> str:
    t0 = now - history_sec
    t1 = now + future_sec
    plot_w = _W - _LEFT - _RIGHT
    strip_y = _TOP + _PLOT_H + _STRIP_GAP

    def x_of(ts: float) -> float:
        return _LEFT + (ts - t0) / (t1 - t0) * plot_w

    def y_of(value: float) -> float:
        clamped = min(Y_MAX, max(Y_MIN, value))
        return _TOP + (Y_MAX - clamped) / (Y_MAX - Y_MIN) * _PLOT_H

    parts: list[str] = []
    parts.append(
        f'<svg class="vchart-svg" viewBox="0 0 {_W:.0f} {_H:.0f}" role="img" '
        f'aria-label="Напруга за добу і графік черги {queue}">'
    )
    parts.append(
        f'<rect x="{_LEFT:.1f}" y="{_TOP:.1f}" width="{plot_w:.1f}" height="{_PLOT_H:.1f}" '
        f'fill="#0c121c" rx="4"/>'
    )

    for start, end in _schedule_spans(now, t1, today, tomorrow, "off"):
        parts.append(_column(x_of(start), x_of(end), strip_y + _STRIP_H, "#7c4a32", 0.95))
    for start, end in _schedule_spans(now, t1, today, tomorrow, "maybe"):
        parts.append(_column(x_of(start), x_of(end), strip_y + _STRIP_H, "#4b5563", 0.8))

    for tick in (180, 200, 220, 240, 260):
        y = y_of(float(tick))
        parts.append(
            f'<line x1="{_LEFT:.1f}" y1="{y:.1f}" x2="{_LEFT + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="#1e293b" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_LEFT - 4:.1f}" y="{y + 3:.1f}" text-anchor="end" '
            f'fill="#64748b" font-size="10">{tick}</text>'
        )
    for limit in (LIMIT_LO, LIMIT_HI):
        y = y_of(limit)
        parts.append(
            f'<line x1="{_LEFT:.1f}" y1="{y:.1f}" x2="{_LEFT + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="#c2410c" stroke-width="1" stroke-dasharray="4 3" opacity="0.85"/>'
        )

    for key, color in _PHASES:
        parts.extend(_phase_paths(buckets, key, color, x_of, y_of))

    now_x = x_of(now)
    parts.append(
        f'<line x1="{now_x:.1f}" y1="{_TOP:.1f}" x2="{now_x:.1f}" y2="{strip_y + _STRIP_H:.1f}" '
        f'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="2 2"/>'
    )
    anchor = "end" if now_x > _W - 36 else "middle"
    parts.append(
        f'<text x="{now_x:.1f}" y="{_TOP - 4:.1f}" text-anchor="{anchor}" '
        f'fill="#e2e8f0" font-size="10">зараз</text>'
    )

    parts.append(
        f'<rect x="{_LEFT:.1f}" y="{strip_y:.1f}" width="{plot_w:.1f}" height="{_STRIP_H:.1f}" '
        f'fill="#0c121c" rx="2"/>'
    )
    for start, end, kind in _fact_spans(buckets, now):
        color = "#22c55e" if kind == "on" else "#fb923c"
        x1, x2 = x_of(start), x_of(end)
        if x2 - x1 < 0.6:
            x2 = x1 + 0.6
        parts.append(
            f'<rect x="{x1:.1f}" y="{strip_y:.1f}" width="{x2 - x1:.1f}" height="{_STRIP_H:.1f}" '
            f'fill="{color}"/>'
        )

    label_y = strip_y + _STRIP_H + 14
    for ts, label in _time_ticks(t0, t1):
        parts.append(
            f'<text x="{x_of(ts):.1f}" y="{label_y:.1f}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="10">{label}</text>'
        )
    parts.append("</svg>")

    span = _ten_minute_span(buckets, now)
    span_html = f'<span class="vchart-span">{span}</span>' if span else ""
    return (
        '<div class="vchart">'
        '<div class="vchart-head">'
        f'<div>Остання доба і графік відключень <span class="vchart-queue">черга {queue}</span></div>'
        f"{span_html}"
        "</div>"
        + "".join(parts)
        + _legend()
        + "</div>"
    )


def _column(x1: float, x2: float, bottom: float, color: str, opacity: float) -> str:
    if x2 - x1 < 0.6:
        x2 = x1 + 0.6
    return (
        f'<rect x="{x1:.1f}" y="{_TOP:.1f}" width="{x2 - x1:.1f}" height="{bottom - _TOP:.1f}" '
        f'fill="{color}" opacity="{opacity}"/>'
    )


def _phase_paths(buckets, key, color, x_of, y_of) -> list[str]:
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    prev_ts: float | None = None
    for row in buckets:
        value = row.get(key)
        ts = float(row["bucket"])
        if value is None:
            if current:
                segments.append(current)
                current = []
            prev_ts = None
            continue
        if prev_ts is not None and ts - prev_ts > BUCKET_SEC * 2.5:
            if current:
                segments.append(current)
                current = []
        current.append((x_of(ts), y_of(float(value))))
        prev_ts = ts
    if current:
        segments.append(current)
    out = []
    for segment in segments:
        if len(segment) == 1:
            x, y = segment[0]
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.5" fill="{color}"/>')
            continue
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in segment)
        out.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    return out


def _fact_spans(buckets: list[dict], now: float) -> list[tuple[float, float, str]]:
    raw: list[tuple[float, float, str]] = []
    for i, row in enumerate(buckets):
        start = float(row["bucket"])
        if start >= now:
            continue
        end = float(buckets[i + 1]["bucket"]) if i + 1 < len(buckets) else start + BUCKET_SEC
        end = min(end, now)
        if end <= start:
            continue
        alive = any(row.get(key) is not None for key, _ in _PHASES)
        if alive:
            kind = "on"
        elif (row.get("dead") or 0) > 0:
            kind = "off"
        else:
            continue
        raw.append((start, end, kind))
    return _merge(raw)


def _schedule_spans(t_from: float, t_to: float, today, tomorrow, want: str) -> list[tuple[float, float]]:
    raw: list[tuple[float, float, str]] = []
    t = t_from
    guard = 0
    while t < t_to - 0.5 and guard < 96:
        guard += 1
        dt = datetime.fromtimestamp(t, tz=UA_TZ)
        minute_end = 30 if dt.minute < 30 else 60
        boundary = dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute_end)
        end = min(boundary.timestamp(), t_to)
        if end <= t:
            t += 60
            continue
        status = _grid_status(t, today, tomorrow)
        if status == want:
            raw.append((t, end, want))
        t = end
    return [(a, b) for a, b, _ in _merge(raw)]


def _grid_status(ts: float, today, tomorrow) -> str | None:
    dt = datetime.fromtimestamp(ts, tz=UA_TZ)
    day = dt.strftime("%Y-%m-%d")
    slot = dt.hour * 2 + (1 if dt.minute >= 30 else 0)
    for day_info in (today, tomorrow):
        if not day_info or day_info.get("date") != day:
            continue
        grid = day_info.get("grid") or []
        if not grid:
            return None
        return grid[min(slot, len(grid) - 1)]
    return None


def _merge(spans: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    if not spans:
        return []
    out = [list(spans[0])]
    for start, end, kind in spans[1:]:
        if kind == out[-1][2] and start <= out[-1][1] + 1.5:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end, kind])
    return [(a, b, c) for a, b, c in out]


def _time_ticks(t0: float, t1: float) -> list[tuple[float, str]]:
    dt = datetime.fromtimestamp(t0, tz=UA_TZ).replace(minute=0, second=0, microsecond=0)
    hour = ((dt.hour // 3) + 1) * 3
    if hour >= 24:
        dt = (dt + timedelta(days=1)).replace(hour=0)
    else:
        dt = dt.replace(hour=hour)
    ticks = []
    while dt.timestamp() < t1:
        label = dt.strftime("%d.%m") if dt.hour == 0 else dt.strftime("%H:%M")
        ticks.append((dt.timestamp(), label))
        dt += timedelta(hours=3)
    return ticks


def _ten_minute_span(buckets: list[dict], now: float) -> str:
    values = []
    for row in buckets:
        if now - 600 <= float(row["bucket"]) <= now:
            for key, _ in _PHASES:
                value = row.get(key)
                if value is not None:
                    values.append(float(value))
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if abs(hi - lo) < 0.5:
        return f"за 10 хв {hi:.0f} В"
    return f"за 10 хв {lo:.0f}–{hi:.0f} В"


def _legend() -> str:
    items = (
        ("#fb7185", "line", "L1"),
        ("#facc15", "line", "L2"),
        ("#60a5fa", "line", "L3"),
        ("#7c4a32", "box", "без світла за графіком"),
        ("#4b5563", "box", "можливе за графіком"),
        ("#22c55e", "bar", "світло було"),
        ("#fb923c", "bar", "світла не було"),
        ("#c2410c", "dash", "межі 195–245 В"),
    )
    html = []
    for color, kind, label in items:
        if kind == "dash":
            mark = f'<span class="vchart-mark vchart-dash" style="color:{color}"></span>'
        elif kind == "line":
            mark = f'<span class="vchart-mark vchart-line" style="background:{color}"></span>'
        else:
            mark = f'<span class="vchart-mark vchart-box" style="background:{color}"></span>'
        html.append(f'<span class="vchart-key">{mark}{label}</span>')
    return '<div class="vchart-legend">' + "".join(html) + "</div>"
