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


_PRIVATE_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|0\.|169\.254\.|172\.(1[6-9]|2\d|3[0-1])\.)"
)
_OK_AGE = 30 * 86400
_FAIL_AGE = 6 * 3600


def is_public_ip(ip: str) -> bool:
    return bool(ip) and _PRIVATE_RE.match(ip) is None and ":" not in ip


def place_label(city: str, region: str) -> str:
    city = city or ""
    region = region or ""
    if city and region and city != region:
        return f"{city}, {region}"
    return city or region


def kind_label(hosting: int, proxy: int) -> str:
    if hosting:
        return "датацентр"
    if proxy:
        return "проксі"
    return ""


def lookup_hostname(ip: str) -> str:
    """Reverse name, or an empty string when the address has none. Bounded wait."""
    import socket
    import threading

    box: dict[str, str] = {}

    def run():
        try:
            box["name"] = socket.gethostbyaddr(ip)[0] or ""
        except Exception:
            box["name"] = ""

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(1.2)
    return (box.get("name") or "")[:200]


def _stale(info: dict, now: float) -> bool:
    age = now - float(info.get("looked_up") or 0)
    if info.get("ok"):
        return age > _OK_AGE
    return age > _FAIL_AGE


def fetch_ip_batch(ips: list[str]) -> list[dict]:
    """One request for up to 100 addresses. Empty list if the service does not answer."""
    import json
    import urllib.request

    payload = json.dumps(ips[:100]).encode()
    req = urllib.request.Request(
        "http://ip-api.com/batch?fields=status,country,regionName,city,isp,org,as,hosting,proxy,query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=4) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _hostname_due(info: dict | None, now: float) -> bool:
    if not info or info.get("hostname_at") is None:
        return True
    return now - float(info["hostname_at"]) > _OK_AGE


def _resolve_names(ips: list[str], lookup) -> list[tuple[str, str]]:
    import concurrent.futures

    if not ips:
        return []
    done = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(lookup, ip): ip for ip in ips}
        finished, _pending = concurrent.futures.wait(futures, timeout=4)
        for fut in finished:
            ip = futures[fut]
            try:
                done.append((ip, (fut.result() or "")[:200]))
            except Exception:
                done.append((ip, ""))
    return done


def enrich_rows(rows: list[dict], fetch, now: float | None = None, host_lookup=None) -> None:
    """Fill country, city, provider and network from the cache. Look up only the gaps."""
    from database import ip_hostname_save, ip_info_for, ip_info_save

    now = time.time() if now is None else now
    if host_lookup is None:
        host_lookup = lookup_hostname
    ips = []
    for row in rows:
        ip = row.get("ip") or ""
        if ip and ip not in ips:
            ips.append(ip)
    cached = ip_info_for(ips)
    missing = [
        ip for ip in ips
        if is_public_ip(ip) and (ip not in cached or _stale(cached[ip], now))
    ]
    if missing:
        try:
            found = fetch(missing[:100])
        except Exception:
            found = []
        by_ip = {item.get("query"): item for item in found if item.get("query")}
        saving = []
        for ip in missing[:100]:
            item = by_ip.get(ip)
            if item and item.get("status") == "success":
                saving.append((
                    ip,
                    (item.get("country") or "")[:80],
                    (item.get("regionName") or "")[:80],
                    (item.get("city") or "")[:80],
                    (item.get("isp") or "")[:120],
                    (item.get("org") or "")[:120],
                    (item.get("as") or "")[:120],
                    1 if item.get("hosting") else 0,
                    1 if item.get("proxy") else 0,
                    1,
                    now,
                ))
            else:
                saving.append((ip, "", "", "", "", "", "", 0, 0, 0, now))
        if saving:
            ip_info_save(saving)
            cached = ip_info_for(ips)
    need_names = [
        ip for ip in ips
        if is_public_ip(ip) and _hostname_due(cached.get(ip), now)
    ]
    if need_names:
        named = _resolve_names(need_names[:20], host_lookup)
        ip_hostname_save([(ip, name, now) for ip, name in named])
        cached = ip_info_for(ips)
    for row in rows:
        info = cached.get(row.get("ip") or "") or {}
        row["country"] = info.get("country") or ""
        row["place"] = place_label(info.get("city") or "", info.get("region") or "")
        row["isp"] = info.get("isp") or ""
        row["org"] = info.get("org") or ""
        row["asn"] = info.get("asn") or ""
        row["net"] = kind_label(int(info.get("hosting") or 0), int(info.get("proxy") or 0))
        row["hostname"] = info.get("hostname") or ""
        row["alias"] = info.get("alias") or ""
        row["note"] = info.get("note") or ""
        looked = info.get("looked_up")
        row["updated"] = (
            datetime.fromtimestamp(float(looked), UA_TZ).strftime("%d.%m.%Y") if looked else ""
        )


def access_view(day: str) -> dict:
    """Flush, then one day, newest visit first. Address details come from the cache."""
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
    enrich_rows(rows, fetch_ip_batch)
    return {"day": day, "today": today, "rows": rows}
