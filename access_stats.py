"""Dashboard visit counts. The request path only bumps a memory counter.

A background flush writes the counter into access_day. The admin tab reads
one Kyiv day from that table. Journal import uses the same row shape.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from config import UA_TZ

PAGE = "page"
POLL = "poll"
UNKNOWN_LABEL = "невідомий"

_ACCESS_RE = re.compile(
    r"^(?P<ts>\d+(?:\.\d+)?)\b.*? "
    r"(?P<ip>(?:\d{1,3}\.){3}\d{1,3}):\d+ - "
    r"\"(?:GET|HEAD) (?P<target>\S+) HTTP/"
)

_buf: dict[tuple[str, str, str], list] = {}
_lock = threading.Lock()
_labels: dict[str, str] = {}


def classify_target(target: str) -> str | None:
    """Page open or the 10s refresh. Everything else, including the router pulse, is ignored."""
    path = urlsplit(target).path or "/"
    if path == "/":
        return PAGE
    if path == "/api/dashboard-fragments":
        return POLL
    return None


def key_from_target(target: str) -> str:
    vals = parse_qs(urlsplit(target).query, keep_blank_values=False).get("key") or []
    return vals[0] if vals else ""


def client_ip_from_request(request) -> str:
    raw = request.headers.get("x-real-ip") or ""
    ip = raw.split(",")[0].strip()
    if not ip and request.client is not None:
        ip = (request.client.host or "").strip()
    return ip[:64]


def parse_day(day: str) -> str:
    datetime.strptime(day, "%Y-%m-%d")
    return day


def kyiv_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UA_TZ).strftime("%Y-%m-%d")


def label_for(key: str, lookup) -> str:
    if not key:
        return UNKNOWN_LABEL
    found = _labels.get(key)
    if found:
        return found
    found = lookup(key) if lookup else None
    if found:
        if len(_labels) > 4000:
            _labels.clear()
        _labels[key] = found
        return found
    return UNKNOWN_LABEL


def note_access(key: str, ip: str, kind: str, ts: float | None = None) -> None:
    """Count one dashboard hit. No database work."""
    try:
        if kind not in (PAGE, POLL) or not ip:
            return
        from api.deps import get_key_label

        when = time.time() if ts is None else ts
        label = label_for(key, get_key_label)[:64]
        day = kyiv_day(when)
        with _lock:
            row = _buf.get((day, label, ip))
            if row is None:
                _buf[(day, label, ip)] = [1 if kind == PAGE else 0, 1 if kind == POLL else 0, when]
                return
            if kind == PAGE:
                row[0] += 1
            else:
                row[1] += 1
            if when > row[2]:
                row[2] = when
    except Exception:
        return


def flush_access() -> int:
    """Write the memory counter. Safe to call from the 30s loop and on shutdown."""
    global _buf
    with _lock:
        if not _buf:
            return 0
        batch = _buf
        _buf = {}
    rows = [
        (day, label, ip, hits[0], hits[1], hits[2])
        for (day, label, ip), hits in batch.items()
    ]
    try:
        from database import access_day_merge

        access_day_merge(rows)
    except Exception:
        with _lock:
            for key, hits in batch.items():
                cur = _buf.get(key)
                if cur is None:
                    _buf[key] = hits
                    continue
                cur[0] += hits[0]
                cur[1] += hits[1]
                if hits[2] > cur[2]:
                    cur[2] = hits[2]
        raise
    return len(rows)


def parse_access_line(line: str, before: float | None = None) -> dict | None:
    """One journal line. None when it is not a dashboard open or refresh."""
    match = _ACCESS_RE.search(line.strip())
    if match is None:
        return None
    ts = float(match.group("ts"))
    if before is not None and ts >= before:
        return None
    kind = classify_target(match.group("target"))
    if kind is None:
        return None
    return {
        "ts": ts,
        "ip": match.group("ip"),
        "kind": kind,
        "key": key_from_target(match.group("target")),
    }


def add_parsed(acc: dict, hit: dict, lookup) -> None:
    label = label_for(hit["key"], lookup)[:64]
    day = kyiv_day(hit["ts"])
    ip = hit["ip"][:64]
    row = acc.get((day, label, ip))
    if row is None:
        acc[(day, label, ip)] = [1 if hit["kind"] == PAGE else 0, 1 if hit["kind"] == POLL else 0, hit["ts"]]
        return
    if hit["kind"] == PAGE:
        row[0] += 1
    else:
        row[1] += 1
    if hit["ts"] > row[2]:
        row[2] = hit["ts"]


def access_view(day: str) -> dict:
    """Flush, then one day, newest visit first."""
    from database import access_day_for

    flush_access()
    today = datetime.now(UA_TZ).strftime("%Y-%m-%d")
    rows = []
    for rec in access_day_for(day):
        rows.append({
            "label": rec["label"],
            "ip": rec["ip"],
            "page_hits": rec["page_hits"],
            "poll_hits": rec["poll_hits"],
            "last": datetime.fromtimestamp(rec["last_ts"], UA_TZ).strftime("%H:%M:%S"),
        })
    return {"day": day, "today": today, "rows": rows}
