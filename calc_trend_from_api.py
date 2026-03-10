"""Compute voltage trend from API data (L2+L3 merged by ts)."""
import json
import statistics
import urllib.request

KEY = "-cFFZ8W13_RAD9BxNOt1oj727F2XdeGV"
BASE = "https://power.elims.pp.ua"

def fetch(query, limit=500):
    url = f"{BASE}/api/debug-sql?key={KEY}&query={urllib.parse.quote(query)}&limit={limit}"
    with urllib.request.urlopen(url) as r:
        return json.load(r)["rows"]

# L2 and L3 (absent phases)
l2 = [(r["grid_v_l2"], r["ts"]) for r in fetch("SELECT grid_v_l2,ts FROM deye_log WHERE grid_v_l2>0 ORDER BY id DESC LIMIT 500")]
l3 = [(r["grid_v_l3"], r["ts"]) for r in fetch("SELECT grid_v_l3,ts FROM deye_log WHERE grid_v_l3>0 ORDER BY id DESC LIMIT 500")]

merged = sorted(l2 + l3, key=lambda x: x[1], reverse=True)

for n in [100, 200, 500, 1000]:
    vals = [v for v, _ in merged[:n]]
    if len(vals) < 4:
        print(f"n={n}: only {len(vals)} values")
        continue
    half = len(vals) // 2
    new_med = statistics.median(vals[:half])
    old_med = statistics.median(vals[half:])
    diff = new_med - old_med
    span_h = (merged[0][1] - merged[len(vals)-1][1]) / 3600
    trend = "high" if diff >= 5 else ("low" if diff <= -5 else "neutral")
    print(f"n={n}: {len(vals)} values, span ~{span_h:.1f}h | newer_med={new_med:.1f} older_med={old_med:.1f} diff={diff:+.1f}V -> {trend}")
