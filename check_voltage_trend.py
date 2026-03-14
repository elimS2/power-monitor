"""Check deye_log voltage data and trend for n=100, 200, 500."""
import statistics
from datetime import datetime

from config import DB_PATH
from database import _last_nonzero_for_phase, recent_deye_log

print(f"DB: {DB_PATH}")
print(f"Exists: {DB_PATH.exists()}\n")

# Total and per-phase counts
import sqlite3
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

total = conn.execute("SELECT COUNT(*) as c FROM deye_log").fetchone()["c"]
l1 = conn.execute("SELECT COUNT(*) as c FROM deye_log WHERE grid_v_l1 > 0").fetchone()["c"]
l2 = conn.execute("SELECT COUNT(*) as c FROM deye_log WHERE grid_v_l2 > 0").fetchone()["c"]
l3 = conn.execute("SELECT COUNT(*) as c FROM deye_log WHERE grid_v_l3 > 0").fetchone()["c"]
conn.close()

print("=== deye_log rows ===")
print(f"Total: {total}")
print(f"L1 > 0: {l1} | L2 > 0: {l2} | L3 > 0: {l3}")

# Latest row
rows = recent_deye_log(1)
if not rows:
    print("\nNo deye_log rows.")
    exit()

latest = rows[0]
phase_keys = [("grid_v_l1", latest.get("grid_v_l1")), ("grid_v_l2", latest.get("grid_v_l2")), ("grid_v_l3", latest.get("grid_v_l3"))]
absent = [k for k, v in phase_keys if v is None or v == 0]
present = [k for k, v in phase_keys if v is not None and v > 0]

print(f"\nLatest: L1={latest.get('grid_v_l1')} L2={latest.get('grid_v_l2')} L3={latest.get('grid_v_l3')}")
print(f"Absent phases: {absent}")
print(f"Present phases: {present}")

if not absent:
    print("\nAll phases present — trend N/A.")
    exit()

# For each n, compute trend
for n in [100, 200, 500]:
    all_val_ts = []
    for key in absent:
        all_val_ts.extend(_last_nonzero_for_phase(key, limit=n))
    all_val_ts.sort(key=lambda x: x[1], reverse=True)
    values = [v for v, _ in all_val_ts[:n]]

    if len(values) < 4:
        print(f"\nn={n}: only {len(values)} values, trend N/A")
        continue

    half = len(values) // 2
    newer_med = statistics.median(values[:half])
    older_med = statistics.median(values[half:])
    diff = newer_med - older_med

    ts_newest = all_val_ts[0][1]
    ts_oldest = all_val_ts[len(values)-1][1]
    span_hr = (ts_newest - ts_oldest) / 3600 if values else 0

    trend = "high" if diff >= 5 else ("low" if diff <= -5 else "neutral")
    print(f"\nn={n}: {len(values)} values, span ~{span_hr:.1f}h")
    print(f"  newer_med={newer_med:.1f} older_med={older_med:.1f} diff={diff:+.1f}V → {trend}")
