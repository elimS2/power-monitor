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

LOAD_COLOR = "#38bdf8"
SOC_COLOR = "#a78bfa"
SOC_MIN = 0.0
SOC_MAX = 100.0
_PLOT_W = 600.0
_PLOT_H = 168.0
_STRIP_H = 10.0

_PHASES = (
    ("l1", "#facc15"),
    ("l2", "#4ade80"),
    ("l3", "#f87171"),
)
_WD = ("пн", "вт", "ср", "чт", "пт", "сб", "нд")
_MON = ("", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру")


def chart_window(wall: float, shift_days: int) -> tuple[float, float, bool]:
    """Live view is the rolling day. Older views are Kyiv calendar days."""
    shift_days = max(0, int(shift_days))
    if shift_days == 0:
        return wall - HISTORY_SEC, wall + FUTURE_SEC, True
    day = datetime.fromtimestamp(wall, UA_TZ).date() - timedelta(days=shift_days)
    start = datetime(day.year, day.month, day.day, tzinfo=UA_TZ)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp(), False


def clamp_chart_shift(shift_days: int, wall: float, oldest: float | None) -> int:
    shift = max(0, min(int(shift_days), 120))
    if oldest is None:
        return 0
    while shift > 0:
        _t0, t1, _live = chart_window(wall, shift)
        if t1 > oldest:
            return shift
        shift -= 1
    return 0


def prev_day_available(shift_days: int, wall: float, oldest: float | None) -> bool:
    if oldest is None:
        return False
    _t0, t1, _live = chart_window(wall, max(0, int(shift_days)) + 1)
    return t1 > oldest


def build_voltage_chart(
    *,
    now: float,
    buckets: list[dict],
    today: dict | None,
    tomorrow: dict | None,
    queue: str,
    history_sec: int = HISTORY_SEC,
    future_sec: int = FUTURE_SEC,
    shift_days: int = 0,
    prev_enabled: bool = True,
    fold_key: str = "",
) -> str:
    shift_days = max(0, int(shift_days))
    if shift_days == 0:
        t0 = now - history_sec
        t1 = now + future_sec
        live = True
    else:
        t0, t1, live = chart_window(now, shift_days)
    schedule_from = now if live else t1

    def x_of(ts: float) -> float:
        return (ts - t0) / (t1 - t0) * _PLOT_W

    def y_of(value: float) -> float:
        clamped = min(Y_MAX, max(Y_MIN, value))
        return (Y_MAX - clamped) / (Y_MAX - Y_MIN) * _PLOT_H

    meta = (
        f' data-t0="{t0:.0f}" data-t1="{t1:.0f}" data-ymin="{Y_MIN:.0f}" data-ymax="{Y_MAX:.0f}"'
        f' data-w="{_PLOT_W:.0f}" data-ploth="{_PLOT_H:.0f}" data-striph="{_STRIP_H:.0f}"'
    )
    plot: list[str] = [
        f'<svg class="vchart-main" viewBox="0 0 {_PLOT_W:.0f} {_PLOT_H:.0f}" preserveAspectRatio="none"{meta} role="img" '
        f'aria-label="Напруга за добу і графік черги {queue}">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_PLOT_H:.0f}" fill="#0c121c"/>'
    ]
    strip: list[str] = [
        f'<svg class="vchart-strip" viewBox="0 0 {_PLOT_W:.0f} {_STRIP_H:.0f}" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_STRIP_H:.0f}" fill="#0c121c"/>'
    ]
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "off"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#7c4a32", 0.95))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#7c4a32", 0.95))
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "maybe"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#4b5563", 0.8))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#4b5563", 0.8))
    for tick in (180, 200, 220, 240, 260):
        y = y_of(float(tick))
        plot.append(
            f'<line x1="0" y1="{y:.1f}" x2="{_PLOT_W:.0f}" y2="{y:.1f}" '
            f'stroke="#1e293b" stroke-width="1" vector-effect="non-scaling-stroke"/>'
        )
    for limit in (LIMIT_LO, LIMIT_HI):
        y = y_of(limit)
        plot.append(
            f'<line x1="0" y1="{y:.1f}" x2="{_PLOT_W:.0f}" y2="{y:.1f}" '
            f'stroke="#c2410c" stroke-width="1" stroke-dasharray="4 3" opacity="0.85" '
            f'vector-effect="non-scaling-stroke"/>'
        )
    for key, color in _PHASES:
        plot.extend(_phase_paths(buckets, key, color, x_of, y_of))
    show_now = t0 <= now <= t1
    if show_now:
        now_x = x_of(now)
        plot.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_PLOT_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/>'
        )
        strip.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_STRIP_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" vector-effect="non-scaling-stroke"/>'
        )
    else:
        now_x = 0.0
    for start, end, kind in _fact_spans(buckets, now):
        color = "#22c55e" if kind == "on" else "#fb923c"
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, color, 1))
    plot.append("</svg>")
    strip.append("</svg>")

    y_labels = []
    for tick in (180, 200, 220, 240, 260):
        top = y_of(float(tick)) / _PLOT_H * 100
        y_labels.append(f'<span style="top:{top:.2f}%">{tick}</span>')
    x_labels = []
    for ts, label in _time_ticks(t0, t1):
        left = x_of(ts) / _PLOT_W * 100
        if left < -1 or left > 101:
            continue
        x_labels.append(f'<span style="left:{left:.2f}%">{label}</span>')
    now_html = ""
    if show_now:
        now_pct = max(0.0, min(100.0, now_x / _PLOT_W * 100))
        now_html = f'<div class="vchart-now" style="left:{now_pct:.2f}%">зараз</div>'
    span = _ten_minute_span(buckets, now) if live else ""
    span_html = f'<span class="vchart-span">{span}</span>' if span else ""
    title = "Остання доба і графік відключень" if live else _day_title(t0)
    prev_attr = "" if prev_enabled else " disabled"
    next_attr = " disabled" if live else ""
    fold_attr = f' data-ls-key="{fold_key}" data-default-open="1"' if fold_key else ""
    return (
        f'<details class="vchart" data-shift="{shift_days}" open{fold_attr}>'
        '<summary class="vchart-head">'
        f'<div>{title} <span class="vchart-queue">черга {queue}</span></div>'
        '<div class="vchart-head-side">'
        f"{span_html}"
        '<button type="button" class="vchart-reset" hidden>Скинути</button>'
        '<button type="button" class="vchart-full" aria-label="На весь екран">'
        '<svg class="vchart-full-enter" viewBox="0 0 16 16" aria-hidden="true">'
        '<path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
        '<svg class="vchart-full-exit" viewBox="0 0 16 16" aria-hidden="true" hidden>'
        '<path d="M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg></button>'
        '<span class="vchart-help-wrap">'
        '<button type="button" class="vchart-help" aria-label="Як керувати графіком" aria-expanded="false">i</button>'
        '<div class="vchart-help-pop" hidden>'
        "<p>Колесо збільшує лише час до точки під курсором. На телефоні те саме робить щипок двома пальцями. Шкала вольт не змінюється.</p>"
        "<p>Затиснута ліва кнопка або палець зрушує графік вліво і вправо.</p>"
        "<p>Подвійний дотик наближає до пальця. Ще один подвійний дотик, подвійний клік або «Скинути» повертає всю добу.</p>"
        "<p>Біля курсора видно час і напругу.</p>"
        "<p>Стрілки гортають попередні доби. Жива доба — останні 24 години і ще 6 годин графіка вперед.</p>"
        "<p>Кнопка з кутами розгортає цей графік на весь екран. На телефоні в портреті він лягає боком. Стрілки знизу, свайп або крапки перемикають напругу, споживання і заряд. Esc згортає.</p>"
        "</div></span>"
        "</div></summary>"
        '<div class="vchart-nav">'
        f'<button type="button" class="vchart-day vchart-prev" data-dir="-1" aria-label="Попередня доба"{prev_attr}>‹</button>'
        f'<span class="vchart-day-label">{_nav_label(t0, t1, live)}</span>'
        f'<button type="button" class="vchart-day vchart-next" data-dir="1" aria-label="Наступна доба"{next_attr}>›</button>'
        "</div>"
        '<div class="vchart-frame">'
        f'<div class="vchart-yaxis">{"".join(y_labels)}</div>'
        '<div class="vchart-plot">'
        + "".join(plot)
        + now_html
        + '<div class="vchart-tip" hidden></div>'
        "</div>"
        + "".join(strip)
        + f'<div class="vchart-xaxis">{"".join(x_labels)}</div>'
        "</div>"
        + _legend()
        + "</details>"
    )


def _load_ymax(buckets: list[dict]) -> float:
    peak = 0.0
    for row in buckets:
        value = row.get("load_w")
        if value is not None:
            peak = max(peak, float(value))
    if peak <= 0:
        return 1000.0
    step = 500.0 if peak <= 5000 else 1000.0
    return max(step, ((int(peak * 1.15) + step - 1) // step) * step)


def build_load_chart(
    *,
    now: float,
    buckets: list[dict],
    today: dict | None,
    tomorrow: dict | None,
    queue: str,
    history_sec: int = HISTORY_SEC,
    future_sec: int = FUTURE_SEC,
    shift_days: int = 0,
    prev_enabled: bool = True,
    fold_key: str = "",
) -> str:
    """Same day window as the voltage chart. The line is consumption. The strip is light."""
    shift_days = max(0, int(shift_days))
    if shift_days == 0:
        t0 = now - history_sec
        t1 = now + future_sec
        live = True
    else:
        t0, t1, live = chart_window(now, shift_days)
    schedule_from = now if live else t1
    y_max = _load_ymax(buckets)

    def x_of(ts: float) -> float:
        return (ts - t0) / (t1 - t0) * _PLOT_W

    def y_of(value: float) -> float:
        clamped = min(y_max, max(0.0, value))
        return (y_max - clamped) / y_max * _PLOT_H

    meta = (
        f' data-t0="{t0:.0f}" data-t1="{t1:.0f}" data-ymin="0" data-ymax="{y_max:.0f}"'
        f' data-w="{_PLOT_W:.0f}" data-ploth="{_PLOT_H:.0f}" data-striph="{_STRIP_H:.0f}"'
    )
    plot: list[str] = [
        f'<svg class="vchart-main" viewBox="0 0 {_PLOT_W:.0f} {_PLOT_H:.0f}" preserveAspectRatio="none"{meta} role="img" '
        f'aria-label="Споживання за добу і графік черги {queue}">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_PLOT_H:.0f}" fill="#0c121c"/>'
    ]
    strip: list[str] = [
        f'<svg class="vchart-strip" viewBox="0 0 {_PLOT_W:.0f} {_STRIP_H:.0f}" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_STRIP_H:.0f}" fill="#0c121c"/>'
    ]
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "off"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#7c4a32", 0.95))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#7c4a32", 0.95))
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "maybe"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#4b5563", 0.8))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#4b5563", 0.8))
    plot.extend(_phase_paths(buckets, "load_w", LOAD_COLOR, x_of, y_of))
    show_now = t0 <= now <= t1
    if show_now:
        now_x = x_of(now)
        plot.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_PLOT_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/>'
        )
        strip.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_STRIP_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" vector-effect="non-scaling-stroke"/>'
        )
    else:
        now_x = 0.0
    for start, end, kind in _fact_spans(buckets, now):
        color = "#22c55e" if kind == "on" else "#fb923c"
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, color, 1))
    plot.append("</svg>")
    strip.append("</svg>")

    y_labels = []
    step = 500 if y_max <= 5000 else 1000
    tick = step
    while tick <= y_max + 0.01:
        top = y_of(float(tick)) / _PLOT_H * 100
        y_labels.append(f'<span style="top:{top:.2f}%">{int(tick)}</span>')
        tick += step
    x_labels = []
    for ts, label in _time_ticks(t0, t1):
        left = x_of(ts) / _PLOT_W * 100
        if left < -1 or left > 101:
            continue
        x_labels.append(f'<span style="left:{left:.2f}%">{label}</span>')
    now_html = ""
    if show_now:
        now_pct = max(0.0, min(100.0, now_x / _PLOT_W * 100))
        now_html = f'<div class="vchart-now" style="left:{now_pct:.2f}%">зараз</div>'
    span = _load_span(buckets, now) if live else ""
    span_html = f'<span class="vchart-span">{span}</span>' if span else ""
    title = "Остання доба, споживання" if live else _day_title(t0)
    prev_attr = "" if prev_enabled else " disabled"
    next_attr = " disabled" if live else ""
    fold_attr = f' data-ls-key="{fold_key}" data-default-open="1"' if fold_key else ""
    return (
        f'<details class="vchart vchart-load" data-shift="{shift_days}" open{fold_attr}>'
        '<summary class="vchart-head">'
        f'<div>{title} <span class="vchart-queue">черга {queue}</span></div>'
        '<div class="vchart-head-side">'
        f"{span_html}"
        '<button type="button" class="vchart-reset" hidden>Скинути</button>'
        '<button type="button" class="vchart-full" aria-label="На весь екран">'
        '<svg class="vchart-full-enter" viewBox="0 0 16 16" aria-hidden="true">'
        '<path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
        '<svg class="vchart-full-exit" viewBox="0 0 16 16" aria-hidden="true" hidden>'
        '<path d="M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg></button>'
        "</div></summary>"
        '<div class="vchart-nav">'
        f'<button type="button" class="vchart-day vchart-prev" data-dir="-1" aria-label="Попередня доба"{prev_attr}>‹</button>'
        f'<span class="vchart-day-label">{_nav_label(t0, t1, live)}</span>'
        f'<button type="button" class="vchart-day vchart-next" data-dir="1" aria-label="Наступна доба"{next_attr}>›</button>'
        "</div>"
        '<div class="vchart-frame">'
        f'<div class="vchart-yaxis">{"".join(y_labels)}</div>'
        '<div class="vchart-plot">'
        + "".join(plot)
        + now_html
        + '<div class="vchart-tip" hidden></div>'
        "</div>"
        + "".join(strip)
        + f'<div class="vchart-xaxis">{"".join(x_labels)}</div>'
        "</div>"
        + _load_legend()
        + "</details>"
    )


def _load_span(buckets: list[dict], now: float) -> str:
    values = []
    for row in buckets:
        if now - 600 <= float(row["bucket"]) <= now and row.get("load_w") is not None:
            values.append(float(row["load_w"]))
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if abs(hi - lo) < 1:
        return f"за 10 хв {hi:.0f} Вт"
    return f"за 10 хв {lo:.0f}–{hi:.0f} Вт"


def _load_legend() -> str:
    items = (
        (LOAD_COLOR, "line", "споживання"),
        ("#7c4a32", "box", "без світла за графіком"),
        ("#4b5563", "box", "можливе за графіком"),
        ("#22c55e", "bar", "світло було"),
        ("#fb923c", "bar", "світла не було"),
    )
    html = []
    for color, kind, label in items:
        if kind == "line":
            mark = f'<span class="vchart-mark vchart-line" style="background:{color}"></span>'
        else:
            mark = f'<span class="vchart-mark vchart-box" style="background:{color}"></span>'
        html.append(f'<span class="vchart-key">{mark}{label}</span>')
    return '<div class="vchart-legend">' + "".join(html) + "</div>"


def build_soc_chart(
    *,
    now: float,
    buckets: list[dict],
    today: dict | None,
    tomorrow: dict | None,
    queue: str,
    history_sec: int = HISTORY_SEC,
    future_sec: int = FUTURE_SEC,
    shift_days: int = 0,
    prev_enabled: bool = True,
    fold_key: str = "",
) -> str:
    """Same day window as the voltage chart. The line is battery charge. The strip is light."""
    shift_days = max(0, int(shift_days))
    if shift_days == 0:
        t0 = now - history_sec
        t1 = now + future_sec
        live = True
    else:
        t0, t1, live = chart_window(now, shift_days)
    schedule_from = now if live else t1

    def x_of(ts: float) -> float:
        return (ts - t0) / (t1 - t0) * _PLOT_W

    def y_of(value: float) -> float:
        clamped = min(SOC_MAX, max(SOC_MIN, value))
        return (SOC_MAX - clamped) / (SOC_MAX - SOC_MIN) * _PLOT_H

    meta = (
        f' data-t0="{t0:.0f}" data-t1="{t1:.0f}" data-ymin="{SOC_MIN:.0f}" data-ymax="{SOC_MAX:.0f}"'
        f' data-w="{_PLOT_W:.0f}" data-ploth="{_PLOT_H:.0f}" data-striph="{_STRIP_H:.0f}"'
    )
    plot: list[str] = [
        f'<svg class="vchart-main" viewBox="0 0 {_PLOT_W:.0f} {_PLOT_H:.0f}" preserveAspectRatio="none"{meta} role="img" '
        f'aria-label="Заряд батареї за добу і графік черги {queue}">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_PLOT_H:.0f}" fill="#0c121c"/>'
    ]
    strip: list[str] = [
        f'<svg class="vchart-strip" viewBox="0 0 {_PLOT_W:.0f} {_STRIP_H:.0f}" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect x="0" y="0" width="{_PLOT_W:.0f}" height="{_STRIP_H:.0f}" fill="#0c121c"/>'
    ]
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "off"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#7c4a32", 0.95))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#7c4a32", 0.95))
    for start, end in _schedule_spans(schedule_from, t1, today, tomorrow, "maybe"):
        plot.append(_hrect(x_of(start), x_of(end), 0, _PLOT_H, "#4b5563", 0.8))
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, "#4b5563", 0.8))
    plot.extend(_phase_paths(buckets, "soc", SOC_COLOR, x_of, y_of))
    show_now = t0 <= now <= t1
    if show_now:
        now_x = x_of(now)
        plot.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_PLOT_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/>'
        )
        strip.append(
            f'<line x1="{now_x:.1f}" y1="0" x2="{now_x:.1f}" y2="{_STRIP_H:.0f}" '
            f'stroke="#e2e8f0" stroke-width="1" vector-effect="non-scaling-stroke"/>'
        )
    else:
        now_x = 0.0
    for start, end, kind in _fact_spans(buckets, now):
        color = "#22c55e" if kind == "on" else "#fb923c"
        strip.append(_hrect(x_of(start), x_of(end), 0, _STRIP_H, color, 1))
    plot.append("</svg>")
    strip.append("</svg>")

    y_labels = []
    tick = 0
    while tick <= SOC_MAX + 0.01:
        top = y_of(float(tick)) / _PLOT_H * 100
        y_labels.append(f'<span style="top:{top:.2f}%">{int(tick)}</span>')
        tick += 25
    x_labels = []
    for ts, label in _time_ticks(t0, t1):
        left = x_of(ts) / _PLOT_W * 100
        if left < -1 or left > 101:
            continue
        x_labels.append(f'<span style="left:{left:.2f}%">{label}</span>')
    now_html = ""
    if show_now:
        now_pct = max(0.0, min(100.0, now_x / _PLOT_W * 100))
        now_html = f'<div class="vchart-now" style="left:{now_pct:.2f}%">зараз</div>'
    span = _soc_span(buckets, now) if live else ""
    span_html = f'<span class="vchart-span">{span}</span>' if span else ""
    title = "Остання доба, заряд" if live else _day_title(t0)
    prev_attr = "" if prev_enabled else " disabled"
    next_attr = " disabled" if live else ""
    fold_attr = f' data-ls-key="{fold_key}" data-default-open="1"' if fold_key else ""
    return (
        f'<details class="vchart vchart-soc" data-shift="{shift_days}" open{fold_attr}>'
        '<summary class="vchart-head">'
        f'<div>{title} <span class="vchart-queue">черга {queue}</span></div>'
        '<div class="vchart-head-side">'
        f"{span_html}"
        '<button type="button" class="vchart-reset" hidden>Скинути</button>'
        '<button type="button" class="vchart-full" aria-label="На весь екран">'
        '<svg class="vchart-full-enter" viewBox="0 0 16 16" aria-hidden="true">'
        '<path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
        '<svg class="vchart-full-exit" viewBox="0 0 16 16" aria-hidden="true" hidden>'
        '<path d="M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg></button>'
        "</div></summary>"
        '<div class="vchart-nav">'
        f'<button type="button" class="vchart-day vchart-prev" data-dir="-1" aria-label="Попередня доба"{prev_attr}>‹</button>'
        f'<span class="vchart-day-label">{_nav_label(t0, t1, live)}</span>'
        f'<button type="button" class="vchart-day vchart-next" data-dir="1" aria-label="Наступна доба"{next_attr}>›</button>'
        "</div>"
        '<div class="vchart-frame">'
        f'<div class="vchart-yaxis">{"".join(y_labels)}</div>'
        '<div class="vchart-plot">'
        + "".join(plot)
        + now_html
        + '<div class="vchart-tip" hidden></div>'
        "</div>"
        + "".join(strip)
        + f'<div class="vchart-xaxis">{"".join(x_labels)}</div>'
        "</div>"
        + _soc_legend()
        + "</details>"
    )


def _soc_span(buckets: list[dict], now: float) -> str:
    values = []
    for row in buckets:
        if now - 600 <= float(row["bucket"]) <= now and row.get("soc") is not None:
            values.append(float(row["soc"]))
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if abs(hi - lo) < 0.5:
        return f"за 10 хв {hi:.0f} %"
    return f"за 10 хв {lo:.0f}–{hi:.0f} %"


def _soc_legend() -> str:
    items = (
        (SOC_COLOR, "line", "заряд"),
        ("#7c4a32", "box", "без світла за графіком"),
        ("#4b5563", "box", "можливе за графіком"),
        ("#22c55e", "bar", "світло було"),
        ("#fb923c", "bar", "світла не було"),
    )
    html = []
    for color, kind, label in items:
        if kind == "line":
            mark = f'<span class="vchart-mark vchart-line" style="background:{color}"></span>'
        else:
            mark = f'<span class="vchart-mark vchart-box" style="background:{color}"></span>'
        html.append(f'<span class="vchart-key">{mark}{label}</span>')
    return '<div class="vchart-legend">' + "".join(html) + "</div>"


# Shared with the basement charge lane. Green only near a full pack, so 75% and 98% differ.
SOC_STOPS = (
    (0.0, (127, 29, 29)),
    (25.0, (220, 38, 38)),
    (50.0, (234, 88, 12)),
    (75.0, (250, 204, 21)),
    (90.0, (132, 204, 22)),
    (100.0, (34, 197, 94)),
)


def soc_color(percent: float) -> str:
    """Color of one charge percent on the meter scale."""
    level = max(0.0, min(100.0, float(percent)))
    for index in range(1, len(SOC_STOPS)):
        left_pct, left_rgb = SOC_STOPS[index - 1]
        right_pct, right_rgb = SOC_STOPS[index]
        if level > right_pct:
            continue
        span = right_pct - left_pct or 1.0
        mix = (level - left_pct) / span
        rgb = tuple(
            round(left_rgb[channel] + (right_rgb[channel] - left_rgb[channel]) * mix)
            for channel in range(3)
        )
        return "#{:02x}{:02x}{:02x}".format(*rgb)
    return "#22c55e"


_GRID_ON_V = 50.0
_CHARGE_W = 100.0
_LOAD_IDLE_W = 50.0
_AVG_SAMPLES = 3


def _eta_text(hours: float | None) -> str | None:
    if hours is None:
        return None
    seconds = int(round(hours * 3600))
    if seconds < 60:
        return "менше хвилини"
    days, rem = divmod(seconds, 86400)
    hrs, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hrs:
        parts.append(f"{hrs} год")
    if mins or not parts:
        parts.append(f"{mins} хв")
    return " ".join(parts)


def _run_hours(energy_kwh: float, watts: float | None) -> float | None:
    if energy_kwh <= 0 or watts is None or watts < _LOAD_IDLE_W:
        return None
    return energy_kwh / (watts / 1000.0)


def _eta_pair(now_h: float | None, avg_h: float | None, have_avg: bool) -> str:
    now_s = _eta_text(now_h) or "дуже довго"
    if not have_avg:
        return f"зараз {now_s}"
    avg_s = _eta_text(avg_h) or "дуже довго"
    return f"зараз {now_s}, за 10 хв {avg_s}"


def _power_parts(watts: float | None) -> tuple[str, str, str, str]:
    if watts is None:
        return "---", "888", "", "none"
    value = max(0.0, float(watts))
    if value >= 1000:
        return f"{value / 1000:.1f}", "88.8", "кВт", "ok"
    return f"{value:.0f}", "8888", "Вт", "ok"


def _power_words(watts: float) -> str:
    digits, _ghost, unit, _band = _power_parts(watts)
    return f"{digits} {unit}".strip()


def _cap_caption(cap: float) -> str:
    rounded = round(float(cap), 1)
    if abs(rounded - round(rounded)) < 0.05:
        text = str(int(round(rounded)))
    else:
        text = f"{rounded:.1f}"
    return f"з {text} кВт·год"


def _b_meter(label: str, digits: str, unit: str, state: str, band: str, bar_pct: float | None = None) -> str:
    bar = ""
    if bar_pct is not None:
        width = max(0.0, min(100.0, bar_pct))
        # The gradient is the full 0–100 scale. The span only reveals the part up to this percent.
        size = 10000.0 / width if width > 0.05 else 100.0
        bar = (
            f'<div class="bbar" aria-hidden="true">'
            f'<span style="width:{width:.1f}%;background-size:{size:.2f}% 100%"></span>'
            f"</div>"
        )
    unit_html = f'<span class="vmeter-unit">{unit}</span>' if unit else ""
    return (
        f'<div class="vmeter vmeter-{band}">'
        f'<div class="vmeter-phase">{label}</div>'
        '<div class="vmeter-window">'
        '<div class="vmeter-readout">'
        f'<span class="vmeter-digits">{digits}</span>'
        f"</div>{unit_html}</div>"
        f"{bar}"
        f'<div class="vmeter-state">{state}</div>'
        "</div>"
    )


def build_battery_board(
    *,
    soc: float | None,
    cap_kwh: float,
    load_w: float | None,
    load_avg_w: float | None,
    bat_w: float | None,
    bat_avg_w: float | None,
    avg_samples: int,
    grid_v: tuple[float | None, float | None, float | None],
) -> str:
    """Charge panel under the voltmeter. Averages are the last 10 minutes."""
    known = [float(v) for v in grid_v if isinstance(v, (int, float))]
    grid_on = any(v >= _GRID_ON_V for v in known) if known else None
    have_avg = avg_samples >= _AVG_SAMPLES
    cap = max(0.0, float(cap_kwh or 0))

    if soc is None:
        soc_meter = _b_meter("ЗАРЯД", "---", "%", "немає", "none", 0)
    else:
        pct = max(0.0, min(100.0, float(soc)))
        if pct < 15:
            band, word = "dead", "майже порожньо"
        elif pct < 30:
            band, word = "low", "низький"
        else:
            band, word = "ok", "норма"
        soc_meter = _b_meter("ЗАРЯД", f"{pct:.0f}", "%", word, band, pct)

    if soc is None or cap <= 0:
        energy = _b_meter("ЗАПАС", "---", "кВт·год", "немає ємності", "none")
        left = 0.0
        room = 0.0
    else:
        left = cap * max(0.0, min(100.0, float(soc))) / 100.0
        room = cap - left
        energy = _b_meter("ЗАПАС", f"{left:.1f}", "кВт·год", _cap_caption(cap), "ok")

    now_digits, _now_ghost, now_unit, now_band = _power_parts(load_w)
    avg_digits, _avg_ghost, avg_unit, avg_band = _power_parts(load_avg_w if have_avg else None)
    load_meter = _b_meter("ЗАРАЗ", now_digits, now_unit, "споживання", now_band)
    avg_meter = _b_meter("10 ХВ", avg_digits, avg_unit, "середнє", avg_band)

    notes: list[str] = []
    charging = bat_w is not None and bat_w <= -_CHARGE_W and soc is not None and cap > 0
    if grid_on is False and soc is not None and cap > 0 and not charging:
        now_h = _run_hours(left, load_w)
        avg_h = _run_hours(left, load_avg_w) if have_avg else None
        notes.append("Без світла вистачить " + _eta_pair(now_h, avg_h, have_avg))
    if charging:
        if float(soc) >= 99.5 or room < 0.05:
            notes.append("Заряд повний")
        else:
            now_h = _run_hours(room, abs(float(bat_w)))
            avg_h = None
            if have_avg and bat_avg_w is not None and bat_avg_w <= -_CHARGE_W:
                avg_h = _run_hours(room, abs(float(bat_avg_w)))
            notes.append(f"Заряд {_power_words(abs(float(bat_w)))}, до повної " + _eta_pair(now_h, avg_h, have_avg and avg_h is not None))
    elif grid_on is True:
        notes.append("Мережа є")
    if not notes:
        notes.append("Немає даних про батарею" if soc is None else "")
    note_html = "".join(f'<p class="bboard-note">{line}</p>' for line in notes if line)
    return (
        '<div class="bboard">'
        '<div class="bboard-meters">'
        + soc_meter + energy + load_meter + avg_meter
        + "</div>"
        + note_html
        + "</div>"
    )


def _day_title(t0: float) -> str:
    day = datetime.fromtimestamp(t0, UA_TZ)
    return f"{day.day} {_MON[day.month]}, {_WD[day.weekday()]}"


def _nav_label(t0: float, t1: float, live: bool) -> str:
    if not live:
        return _day_title(t0)
    start = datetime.fromtimestamp(t0, UA_TZ)
    end = datetime.fromtimestamp(t1, UA_TZ)
    return f"{start.day} {_MON[start.month]} {start:%H:%M} – {end.day} {_MON[end.month]} {end:%H:%M}"


def _hrect(x1: float, x2: float, y: float, height: float, color: str, opacity: float) -> str:
    if x2 - x1 < 0.6:
        x2 = x1 + 0.6
    extra = "" if opacity >= 1 else f' opacity="{opacity}"'
    return (
        f'<rect x="{x1:.1f}" y="{y:.1f}" width="{x2 - x1:.1f}" height="{height:.1f}" '
        f'fill="{color}"{extra}/>'
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
            f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
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
        ("#facc15", "line", "L1"),
        ("#4ade80", "line", "L2"),
        ("#f87171", "line", "L3"),
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
