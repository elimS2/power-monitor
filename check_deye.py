"""One-off script to check deye_log battery data."""
import sqlite3
from datetime import datetime

DB = "power_monitor.db"
# Mar 1 - Mar 9 2026 (Kyiv)
TS_START = 1741046400  # 2026-03-01 00:00 UTC
TS_END = 1741478400    # 2026-03-09 00:00 UTC

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=== power_events (Mar 2026) ===")
for r in conn.execute(
    "SELECT event, ts FROM power_events WHERE ts >= ? ORDER BY ts",
    (TS_START,),
).fetchall():
    dt = datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")
    print(f"  {r['event']} @ {dt}")

print("\n=== deye_log (Mar 7-9, battery_soc, battery_power_w) ===")
rows = conn.execute(
    """SELECT ts, battery_soc, battery_power_w, load_power_w
       FROM deye_log WHERE ts >= ? AND ts <= ? ORDER BY ts""",
    (TS_START, TS_END),
).fetchall()

for r in rows:
    dt = datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")
    soc = r["battery_soc"]
    bat = r["battery_power_w"]
    load = r["load_power_w"]
    print(f"  {dt} | soc={soc} bat_w={bat} load_w={load}")

print(f"\nTotal deye_log rows: {len(rows)}")

# Check NULLs
null_bat = sum(1 for r in rows if r["battery_power_w"] is None)
print(f"Rows with battery_power_w NULL: {null_bat}")
