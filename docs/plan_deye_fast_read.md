# Deye fast register read

- Status: `PHASE 4 LIVE`
- Owner: Volodymyr
- Repo: `power-monitor` (public GitHub `elimS2/power-monitor`, live `https://power.elims.pp.ua`)
- Related Jira: none. This repo is not in the company knowledge base. Do not write this plan, logger serials, or API keys there. Disk is the source of truth for the reader.
- Last updated: 2026-11-22T17:48:00Z
- Active skin: **Skin B** is live at 1 second since 2026-11-22T17:07:53Z. **Skin A** (2 seconds) waits for the 24-hour count. The shipped default stays 0. Phase 4 has been on the server since 2026-11-22T17:46:43Z.
- This file is the implementation contract. A new chat must not need the planning conversation.

Companion: `power-monitor/docs/plan_deye_fast_read_PROGRESS.md`

Source proof for the original plan write: composer `1ccc9355-92e4-47a9-90a2-abd5600f6e11`, title `Load metrics analysis`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-22T13:02:54.441Z`, `mutationKind=plan`.

Source proof for this review edit: same composer, title `Deye one-second load proof`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-22T15:26:25.467Z`, `mutationKind=plan`.

## 1. Goal and non-goals

### Goal

Read the live electrical block from each Deye logger with **one** Modbus request, first **every second**, and keep the existing half-minute snapshot for counters, temperatures, and the battery.

The fast series is what can show a short load peak. A 20-second trial on 2026-11-22 looked like the module often repeats the previous frame, but that sample is too short to decide. The first live run stays at 1 second until a day of stored rows shows whether a new frame really arrives only about every 2 seconds. Only then does anyone set the interval to 2.

The dashboard, after the later phase, shows the newest fast load and the three voltages, and the load chart can draw the **maximum** in each minute. Energy totals stay on the slow snapshot.

### Non-goals

- Writing fast samples into `deye_log`.
- Pointing `deye_aggregates_refresh`, `deye_daily_load_kwh`, or `deye_total_load_kwh_integrated` at the fast table.
- Keeping fast rows for a short window and deleting them. `deye_fast` is kept, the same way `deye_log` is kept. Nothing in `cleanup_old` deletes it.
- One request that also includes registers below 598 (temperatures, battery, kWh counters). That span was not the tested read.
- Register 659 (high word of load above 32.7 kW) until a separate quiet-window probe says the longer span answers. Until then the fast load is the signed 16-bit register 653, ceiling 32767 W.
- Changing breaker polling, the schedule board, Telegram, or the boiler parser.
- Pointing `has_grid_voltage_now`, `has_all_three_phases_voltage`, `deye_voltage_trend`, `get_display_status`, or the outage photo at `deye_fast`. Those stay on the newest `deye_log` row. A two-second dip must not send a voltage alert or flip the banner.
- Putting logger serials, dashboard keys, or `.env` into git.
- Commit, push, or `#автооновити` unless the operator asks in the same yes that closes a gate.

## 2. How this plan was adapted

Prompt library card **#6 Create Plan** (id 6, revision 4) is the working method.

- Living plan plus progress file, English, phases, skins, a human gate between phases, self-review, no code in the planning turn.
- Company KB was searched and does not index `power-monitor`. Disk is the source of truth. House facts stay out of that KB.
- This workspace required an explicit composer proof before the plan files were written. The proof is in the header.
- No Jira ticket. Do not create one as part of implementation.

## 3. Context harvest

Company KB catalog (`kb_repo_memory_catalog`, 2026-11-22T13:01:37Z) lists nine code repos. `power-monitor` is not one of them. `git_only_repos` is only `lazy-ai`.

Searches on 2026-11-22T13:02Z, topic "Deye fast register read":

| Volume | Mode | Result |
|---|---|---|
| knowledge | semantic | No power-monitor hit. Top ids are invoice deploy and unrelated notes (540, 308, 940, 922). |
| ideas | semantic | No power-monitor hit. Top ids are KB/orchestrator ideas (244, 352, 39). |
| code_directories | semantic | No `power-monitor` path in the payload. |
| code_files | hybrid | No `deye_reader` or `power_monitor.py`. Hits are other repos (`rpie_event_log.py`, invoice migrations). `_kb_search_meta.total_fts_hits` was 0. |
| code_symbols | hybrid | Empty. `fallback_applied=or_like`. |
| jira | fts `power-monitor Deye poll` | No matching ticket. Returned unrelated keys (KB-104, KB-433, KBNPPTX-1281). |
| dialogs | hybrid | No polling-design dialog. Dialog 707 is an older backup-power conversation, not this read path. |

Review harvest 2026-11-22T15:27Z, catalog generated 2026-11-22T15:27:19Z. Still nine repos. `power-monitor` is still absent. `git_only_repos` is still only `lazy-ai`.

| Volume | Mode | Result |
|---|---|---|
| knowledge | semantic | No power-monitor hit. Top ids 940, 1035, 959 are invoice and KB notes. |
| ideas | semantic | No power-monitor hit. Top ids 522, 28, 542 are invoice, KB, and igotoffer. |
| code_directories | semantic | No `power-monitor` path in the payload. |
| code_files | hybrid | `total_fts_hits` 0. No `deye_reader.py`. |
| code_symbols | hybrid | Empty. `fallback_applied=or_like`. |
| jira | fts `power-monitor Deye poll` | Unrelated keys KB-104, KB-433, KBNPPTX-1281. |
| dialogs | hybrid | No this design. Dialog 707 is the older elevator backup chat. |

Self-check:

- [x] knowledge — executed, no repo hit
- [x] ideas — executed, no repo hit
- [x] code_directories — executed, no repo hit
- [x] code_files — executed, no repo hit
- [x] code_symbols — executed, empty
- [x] at least three real code paths from disk (below)
- [x] drill-down of the reader, the poll loop, `deye_log`, and the minute chart
- [x] jira and dialogs checked; nothing to implement from them

### Repo map

| Path | Why it matters | Touch? |
|---|---|---|
| `deye_reader.py` `read_deye_solarman` | Opens a new Solarman socket and issues about 19 holding-register reads (about 20 when `hv=True`). | Replace the read list with the blocks in section 6. Keep `read_deye` as the entry used by the poller. |
| `power_monitor.py` `_poll_target`, `_inflight_polls`, `bg_loop` | One process, 30-second sleep. House poll is a task beside the awaited apartment poll. | The fast tick skips an inverter whose id is already in `_inflight_polls`. The slow poll waits for that read instead of returning early, because an early return still resets `deye_poll_tick`. Do not shrink `asyncio.sleep(30)` to 1 second. |
| `config.py` `DEYE_POLL_INTERVAL_SEC` | Slow interval, default 30. | Leave it. Add `DEYE_FAST_INTERVAL_SEC` default `0`. Do not add a keep-days setting. |
| `database.py` `deye_log`, `save_deye_log` | Full snapshot, many columns, indexes on `ts` and `(inverter_id, ts)`. | Do not add fast rows here. Add `deye_fast` and `save_deye_fast`. |
| `database.py` `deye_aggregates_refresh` | Every ~5 minutes, loads the current month and the whole history of `deye_log` into Python. | Must keep querying `deye_log` only. |
| `database.py` `deye_voltage_buckets` | Minute `AVG` over one window. Used by the voltage, load, SOC, and temperature charts. | Add a minute `MAX(load_power_w)` helper that reads `deye_fast` for that same window. Do not change the SQL that scans `deye_log`. |
| `database.py` `cleanup_old` | Deletes old `heartbeats` only. `deye_log` is never deleted. | Leave `deye_fast` out of this delete. It is an archive, not a rolling buffer. |
| `voltage_chart.py` | `BUCKET_SEC = 60`, `HISTORY_SEC` is 24 hours. Load trace uses `load_w` from the minute buckets. | Phase 4 may overlay the fast maximum. The 24-hour window stays. |
| `static/app.js` | Dashboard fragments every 10 seconds. | No new timer. The fragment already refreshes the meters. |
| `docs/plan_deye_multi_inverter.md` | How the house logger was found and that its serial stays on the server. | Do not reopen that plan. Do not copy the serial into this file. |
| `tests/test_voltage_chart.py` | Pattern for database tests on a temp file. | New `tests/test_deye_fast.py`. No socket. |

## 4. Current behavior

`bg_loop` sleeps 30 seconds. `DEYE_POLL_INTERVAL_SEC` defaults to 30, and the tick multiplies by 30, so a smaller env value cannot poll faster than the sleep. Measured gaps on 2026-11-22 were 32.4–32.6 seconds for the house inverter.

Each poll calls `read_deye_solarman`, which connects, reads, and disconnects. The apartment path is about 19 Modbus reads. The house path adds one 9-register battery block (`hv=True`). The stick answers one read at a time. A second client in that window gets silence if the wait is short.

`save_deye_log` inserts one full `deye_log` row. The page treats the newest row as the live voltages, load, SOC, and counters. A fast row with null counters would blank those cells.

`deye_voltage_buckets` averages samples inside each minute. A ten-second spike becomes a small average. That is why a faster series is stored separately and reduced with `MAX` for the load chart only.

`cleanup_old` deletes old `heartbeats` only. It does not delete `deye_log` or `deye_fast`. Both are archives. Fast rows stay out of `deye_log` because that table's newest row is a full snapshot and because the 5-minute energy job loads every `deye_log` row into Python. They are not kept out so they can be expired.

### What was measured

Read-only. Function 0x03. No settings were written. Deye's own protocol allows 1–125 registers per read. These reads asked for 56 (598 through 653).

| When | Where | What happened |
|---|---|---|
| 2026-11-21 | Apartment logger from the apartment PC | 56 registers in 0.185 s. A follow-up read of the same voltages and loads matched within a few watts. A short read after that still answered. |
| 2026-11-21 | House logger from the GCP host | Ten reads in a gap between server polls. Socket wait 1.5 s. Eight answers in about 0.2 s. Two came back empty at 1.502 s (the wait expired). Several answers repeated the previous watts exactly. The server poll did not insert a row during the burst. The apartment PC cannot open the house logger. |
| 2026-11-22T13:00Z | House logger from the GCP host | Twenty reads, one per second, socket wait 3 s, connection opened first. Started 2 s after a server sample. Budget before the next poll was 23.5 s. All 20 answers were 56 registers in 0.206–0.223 s. Eleven frames were new and nine were exact copies of the previous frame. The server poll did not insert a row during the burst. |

The two empty replies were the short wait, not a rejected address. With a 3-second wait and an already open socket, the same block did not come back empty.

The stick accepts a question every second. In one 20-second burst, 11 of 20 frames were new and 9 were exact copies. That is a hint, not a decision. The operator on 2026-11-22T14:28:21Z asked to run at 1 second until a longer record proves the refresh.

## 5. Skins

Shared core for every skin: one socket and one in-flight set per inverter, the blocks in section 6, `deye_fast` not `deye_log`, no automatic delete of `deye_fast`, and aggregates that ignore `deye_fast`.

### Skin B — 1-second fast read (first live rate)

`DEYE_FAST_INTERVAL_SEC=1`. One 56-register read per inverter per tick. This is the rate for the first enable. The 20-second sample is not enough to drop to 2 seconds. Same table and same code as Skin A. No schema change to switch later.

### Skin A — 2-second fast read (only after proof)

`DEYE_FAST_INTERVAL_SEC=2`. Same path. Move here only after the phase 3 proof below, and only with a separate yes. The slow snapshot stays at `DEYE_POLL_INTERVAL_SEC` (30) in both skins.

### Skin C — off

`DEYE_FAST_INTERVAL_SEC=0`. Shipped default until the phase 3 enable yes. No fast task is created, and nothing is written to `deye_fast`.

Before phase 3, the slow poll still opens and closes its own client, as in phase 2. After phase 3 is deployed, the slow poll uses the shared client even when the interval is 0. That is not "today's socket". See the phase 3 rollback.

### Rejected — fast rows inside `deye_log`

The 5-minute aggregate loads every history row of `deye_log` into Python. One fast row a second for three years is about 95 million rows per inverter, and those rows would not carry counters or SOC. The newest row would blank the live page. Do not implement this. Keeping `deye_fast` for years does not have that cost, because nothing that integrates energy reads it.

### Switch

The interval env is the switch. `0`, `1`, and `2` are the only values the loop accepts. Anything else is treated as `0` and logged once. Changing it needs a process restart. It does not migrate the table. Rollback is the two steps in phase 3: env `0` stops fast writes, and reverting the phase 3 commit restores the per-poll connect and close. Rows already stored stay. Nothing deletes them.

## 6. Recommended shape

One SQLite file. One process. One long-lived Solarman client per inverter, guarded by the existing `_inflight_polls` set. The slow snapshot and the fast tick both take that set for the whole read. If it is held, the fast tick skips that inverter. The slow poll waits, then claims again. It does not queue a second socket.

A claim is valid only when the check and the add run on the event-loop thread with no `await` between them, and the task sets a local `owned` flag. `finally` discards the id only when `owned` is true. After any `await`, the slow poll looks again. It must not add an id it saw free before that `await`. Two tasks that both believe they own the client will read the same stick at once, and the first `finally` will drop the other's claim.

The client stays connected across fast ticks. The first read of a new connection is the one that was slow on 2026-11-21. Reconnect only after an error, then skip that tick. A complete slow batch is not that error.

Only the task that just set `owned` may construct the client, and only if that inverter does not already have one. Construct it inside the executor, still inside the owned region, and store it before the read. A task that does not own the id must not call `PySolarmanV5` for that inverter.

### 6.1 Fast read

`read_holding_registers(598, 56)`.

| Offset | Register | Field | Scale |
|---|---|---|---|
| 0 | 598 | `grid_v_l1` | × 0.1 |
| 1 | 599 | `grid_v_l2` | × 0.1 |
| 2 | 600 | `grid_v_l3` | × 0.1 |
| 27 | 625 | `grid_power_w` | signed 16-bit, watts |
| 52 | 650 | `load_l1_w` | signed 16-bit, watts |
| 53 | 651 | `load_l2_w` | signed 16-bit, watts |
| 54 | 652 | `load_l3_w` | signed 16-bit, watts |
| 55 | 653 | `load_power_w` | signed 16-bit, watts |

Signed means `value - 65536` when `value > 32767`. A block shorter than 56, or an exception, inserts nothing.

Other registers in the span (currents, inverter power, load voltage) are not stored. They can be decoded later without a new read.

Register 653 saturates at 32767 W. The house inverter can go higher. The high word is register 659, outside this span. Do not guess a 32-bit value from 653 alone. Phase 3 records the ceiling in the poll log when `load_power_w` is above 30000, once per hour per inverter, so the 659 probe is triggered by evidence.

### 6.2 Slow read

Still one full `deye_log` row on the existing interval. Six reads instead of about twenty. Same field names as today. Scales match the code that is already live. Do not swap in a public map that calls the first register of a pair the low word.

| Read | Registers | Indexes and scale |
|---|---|---|
| 1 | 520 × 9 | `[0]` 520 day import × 0.1. `[1]` 521 day export × 0.1. `[2]<<16 \| [3]` total import × 0.000001 (522 is the high word, 523 the low). `[4]<<16 \| [5]` total export, same scale (524 high, 525 low). `[6]` 526 day load × 0.1. `[7]<<16 \| [8]` total load × 0.000001 (527 high, 528 low). |
| 2 | 87 × 2 | `[0]<<16 \| [1]` year load × 0.1. Drop the value when it is above 1000. |
| 3 | 66 × 1 | Month load × 0.1. |
| 4 | 540 × 2 | Index 0 is `temp_dc_c`, index 1 is `temp_rad_c`. Each goes through `decode_temp_c`: raw × 0.1 − 100. Out of range becomes null. |
| 5 | 586 × 5, or 586 × 10 when `hv=True` | See the battery split below. |
| 6 | 598 × 56 | Same decode as section 6.1. This copy is what the slow `deye_log` row stores for voltages and load. |

Apartment battery (`hv=False`), read 5 quantity 5, registers 586–590:

| Index | Register | Field |
|---|---|---|
| 0 | 586 | `temp_batt_c` via `decode_temp_c` |
| 1 | 587 | `battery_voltage` × 0.01, unsigned |
| 2 | 588 | `battery_soc`, unsigned |
| 4 | 590 | `battery_power_w`, signed 16-bit, × 1 |

Do not use `decode_hv_battery_volts` on the apartment. That function multiplies by 0.1 and would show about 537 V for a 53.7 V pack.

House battery (`hv=True`), read 5 quantity 10, registers 586–595. Index 0 is `temp_batt_c` via `decode_temp_c`. Index 2 (register 588) is unsigned `battery_soc`. `_apply_hv_battery` does not write SOC. Pass `block[1:10]` into `_apply_hv_battery`. That slice is nine registers starting at 587, which is what `_apply_hv_battery` already expects: index 0 voltage × 0.1, index 3 and index 8 the two signed powers × 10. Passing the whole 586 block would decode the temperature register as pack voltage. The `hv=True` fixture must include SOC from index 2.

If the apartment quantity-5 read raises an illegal address, log it and read 586, 587, 588, and 590 one at a time with the apartment scales above. If the house quantity-10 read raises, do not use those apartment scales. Fall back to today's house sequence: `586 × 1` through `decode_temp_c`, `588 × 1` as unsigned SOC, then `587 × 9` through `_apply_hv_battery`. A test fails quantity 10, expects the `587 × 9` call, and expects voltage × 0.1.

A failed block other than this battery fallback omits only its own keys. Later blocks still run. `save_deye_log` still runs when any block returned data. Do not abort the whole slow read because `520 × 9` or `598 × 56` raised. Today's per-register loop already saves a partial dict.

Keep the existing guards: `0xFFFFFFFF` on a 32-bit pair is dropped, total grid import/export above 100000 is dropped.

### 6.3 Table `deye_fast`

Created in `init_db` with `CREATE TABLE IF NOT EXISTS`. No `ALTER` on `deye_log`.

| Column | Meaning |
|---|---|
| `id` | Integer primary key |
| `inverter_id` | `deye_inverter.id` |
| `ts` | Unix seconds, UTC, `time.time()` at insert |
| `grid_v_l1`, `grid_v_l2`, `grid_v_l3` | Volts |
| `grid_power_w` | Watts, signed |
| `load_l1_w`, `load_l2_w`, `load_l3_w`, `load_power_w` | Watts, signed |

Index `(inverter_id, ts)`.

`save_deye_fast` inserts one row. It does not update `deye_log`. Unknown `inverter_id` raises, same as `save_deye_log`.

### 6.4 No automatic delete

`cleanup_old()` stays as it is: it deletes old `heartbeats` and does not touch `deye_fast` or `deye_log`. Do not add `DEYE_FAST_KEEP_DAYS`.

At one row a second that is about 31.5 million rows per inverter per year. The row is only the eight live numbers plus time and inverter id, so the file grows by a few gigabytes a year per inverter, not by the fat `deye_log` row. Page and chart queries stay inside the visible day via the `(inverter_id, ts)` index. The 5-minute energy job does not read this table, so keeping the years does not bring back the memory problem.

Each `save_deye_fast` uses a new `_conn()`, the same way `save_deye_log` does. Do not keep one process-wide connection for the fast insert and `deye_aggregates_refresh`. Run `save_deye_fast` inside the executor that just read the registers, before `owned` is cleared.

### 6.5 Page (phase 4 only)

The page reads `deye_fast` only for this live overlay and for the load-chart minute maximum. That page has been on the server since 2026-11-22T17:46:43Z.

Live meters, both the apartment panel and the house panel: copy the newest `deye_log` row and overlay only the three voltages and the four load watts from the newest `deye_fast` row when that row is younger than 15 seconds. Newest means `ORDER BY ts DESC LIMIT 1` for that `inverter_id`. `LIMIT 1` without that order returns an old row, the 15-second check fails, and the page never shows the fast sample. Pass that copy to the meters and to `_battery_panel`. SOC, temperatures, battery power, and kWh counters stay the `deye_log` values on that copy.

`has_grid_voltage_now`, `has_all_three_phases_voltage`, `deye_voltage_trend`, `get_display_status`, and the Telegram outage path keep reading `deye_log`. Do not pass a fast row into them.

Load chart, both panels: for each minute bucket in the visible window, if `deye_fast` has rows, the load value is `MAX(load_power_w)` in that minute. Minutes with no fast rows keep the existing `deye_log` average. The voltage, SOC, and temperature series stay on `deye_log`. The query has the same `ts` bounds as `deye_voltage_buckets`. It does not scan outside the window.

The 10-second fragment stays the refresh. No 1-second browser poll.

### 6.6 Files

| Concern | File |
|---|---|
| Env | `config.py` |
| Block decode, batched slow read | `deye_reader.py` |
| Table, insert, minute max | `database.py` |
| Fast loop, shared in-flight set | `power_monitor.py` |
| Load chart max | `voltage_chart.py` and the voltage panel builder in `power_monitor.py` |
| Tests | `tests/test_deye_fast.py` |

## 7. Phases

Each phase ends with a human gate. The agent stops and, in Ukrainian, says what changed, what was checked, what is risky, and asks whether to go on. The next phase does not start without an explicit yes. Update this file and the progress file at the gate. Timestamps are full DateTime values.

Do not deploy and do not commit unless that same yes includes it. Tests use a temp SQLite file and a fake register list. They do not open port 8899 and do not SSH.

### Phase 1 — decode and table

Goal: a 56-register list becomes one fast row. Nothing on the page. The live poller is unchanged. Nothing deletes fast rows.

Touch: `deye_reader.py` (decode function only), `database.py`, `tests/test_deye_fast.py`.

Steps:

1. `decode_fast_block(registers) -> dict | None`. None when the list is not length 56.
2. Create `deye_fast` and `save_deye_fast`.
3. Do not change `cleanup_old`. The test inserts one `deye_fast` row with `ts` older than `CLEANUP_KEEP_DAYS` and one with `ts` equal to now. Both rows remain after `cleanup_old()`.

Verify: `python -m unittest tests.test_deye_fast`.

Cases: known block decodes the offsets in 6.1; a value 65535 on register 625 becomes -1; a value 4000 stays 4000; length 55 returns None and inserts nothing; `save_deye_fast` writes one row; `cleanup_old` leaves both the older-than-keep-days row and the current row; `deye_log` row count does not change.

Gate: no poll change, no page change, no deploy.

Landed locally 2026-11-22T16:14:30Z. `decode_fast_block` is in `deye_reader.py`. `deye_fast` and `save_deye_fast` are in `database.py`. `cleanup_old` was not changed. The poller does not call the decoder yet. Not deployed. Not committed.

Rollback: stop calling `save_deye_fast`. Leave the table.

### Phase 2 — batched slow read on the existing interval

Goal: the 30-second poll uses section 6.2. Still no `deye_fast` writer in the loop.

Touch: `deye_reader.py` `read_deye_solarman`.

Steps:

1. Add a reader that performs the five slow reads plus one 598 × 56 for the voltages and loads, using a caller-supplied `read_holding_registers`. The production function passes the Solarman client's method. Do not change `read_deye_modbus`. Both live loggers use port 8899, so `read_deye` already calls `read_deye_solarman`. Port 502 stays the old per-register loop.
2. Map those blocks onto the same dict keys `save_deye_log` already accepts.
3. Battery quantity fallback from 6.2.

Verify: `python -m unittest tests.test_deye_fast`.

Cases: a fake client records the `(address, quantity)` pairs and they are exactly the six reads in 6.2 for `hv=False`, and the house quantity 10 on read 5 for `hv=True`; decoded dict matches a fixture built from the old per-register formulas, including house SOC from index 2 and voltage × 0.1; when quantity 5 raises, the fake is called again for 586, 587, 588, and 590 one at a time with apartment scales, and the other blocks are not repeated; when quantity 10 raises, the fake is called for `586 × 1`, `588 × 1`, and `587 × 9`, and the voltage is × 0.1.

This phase changes live behavior only after deploy. The gate asks before deploy. After deploy, compare one fresh `deye_log` row with the previous row's shape: the same keys are non-null when the inverter is answering. Do not deploy inside the phase unless the yes includes it.

Gate: tests pass. Deploy is a separate yes.

Landed locally 2026-11-22T16:18:30Z. Deployed 2026-11-22T16:26:24Z as commit `d174ec2` with `#autodeploy`. The service restarted and the first new polls were 16:26:27Z. `read_deye_modbus` is still the old per-register loop. Nothing writes `deye_fast` from the poller. The 100000 total-grid guard is still in the decoder. A real 16-bit pair cannot reach it before the `0xFFFFFFFF` drop, same as the old loop.

First rows after the restart, compared with the row just before it:

- Apartment: grid about 234/236/227 V, battery 55.28 V, SOC 91, day load 51.6 kWh, total load 2907.44 kWh. Same shape as the previous row. Load moved from 2317 W to 2297 W.
- House: grid about 236/233/233 V, battery 538.0 V then 537.9 V, SOC 98, day load 93.7 kWh, total load 850.26 kWh. Same shape. Load was 4612 W on the first new row and 13349 W on the next, and grid power moved with it, so that is the building, not a scale error.
- `year_load_kwh` was already null before the restart and stayed null. No `Deye block` fallback line in the journal after the restart.

Rollback: restore `read_deye_solarman` to the per-register loop. No table change.

### Phase 3 — fast loop, off by default

Goal: with `DEYE_FAST_INTERVAL_SEC=0`, the process does not write `deye_fast`. With `1`, it writes one row per inverter per second, skipping an inverter whose slow read is in flight. `2` is not the first enable.

Touch: `config.py`, `power_monitor.py`.

Steps:

1. Parse the env. Accept only `0`, `1`, and `2`. Else log once and use `0`.
2. In `lifespan`, when the parsed interval is `1` or `2`, start one fast task. Interval `0` does not start it and does not call `read_holding_registers` for the fast path. Do not create the task inside `bg_loop`. `asyncio.sleep(0)` would spin. Do not hold `_inflight_polls` across the sleep. `bg_loop` still ends the tick with `await asyncio.sleep(30)`.
3. One Solarman client per enabled inverter. Socket timeout is 3 seconds on every `read_holding_registers`, including the slow batch. That replaces the 10-second timeout on this client. Only the task that just set `owned` may construct the client, and only if that inverter does not already have one. Construct it inside the executor, still inside the owned region, and store it before the read. A task that does not own the id must not call `PySolarmanV5` for that inverter. A slow batch where every requested block returned does not call `disconnect()`. If no block returned, skip `save_deye_log`. If at least one block returned and a later block raised, save that partial dict, then disconnect. Disconnect only while this task still has `owned` true, and open the replacement client on the next tick that owns the id. Do not disconnect after a complete batch. From this phase on, `_poll_target` must not construct a second `PySolarmanV5`. Phase 2 may still open and close a client inside `read_deye_solarman`, because the fast loop does not exist yet. Phase 3 deletes that constructor.
4. One fast task, one cycle clock. At the start of a cycle record `time.monotonic()`. Walk every enabled inverter with no sleep between them. For each inverter, on the event loop thread, check `_inflight_polls` and add that id with no `await` between those two lines, and set a local `owned` flag. If the id is held, skip only that inverter and leave `owned` false. Otherwise await one executor call that, while `owned` is still true, constructs `PySolarmanV5` only if this inverter has no client yet, reads 598 × 56, and calls `save_deye_fast` only on a full block before it returns. Discard the id in `finally` only when `owned` is true. After the walk, sleep once: `max(0, interval - (time.monotonic() - cycle_start))`. Do not sleep inside the per-inverter step. Do not start another walk to fill a missed second. If the sleep is zero, log one overrun warning for that cycle. Stored `ts` stays `time.time()`. The sleep clock is `time.monotonic()`, so a wall-clock step does not stretch the proof hour. Do not call `_poll_target`.

The unit test uses a fake clock. Two reads of 0.2 seconds each produce one sleep of about 0.6 seconds when the interval is 1. A walk of 1.2 seconds sleeps zero and does not read again immediately.
5. The slow poll is one executor call for the whole batch. If the id is held, await until this task can claim it. The claim is the same check-and-add as the fast tick: on the event-loop thread, no `await` between the check and the add, and a local `owned` flag. After the await, look again. Do not add an id that was free only before the await. `finally` discards only when `owned` is true. Do not return early from `_poll_target` while waiting: an early return still resets `deye_poll_tick` in `bg_loop` and would skip `deye_log` for another half minute. The fast tick is the only one that skips. The reset after `_poll_due_targets` stays where it is today, at `power_monitor.py` around the `deye_poll_tick = 0` line. Do not `create_task` a second `_poll_target` for an inverter whose previous task has not finished. The wait inside `_poll_target` is only the fast-claim wait for the one task already running. The house row is still started beside the apartment row, once per due tick, and that one task is the one that waits.
6. Log a fast failure as a warning with the inverter title and the exception class. Do not log the serial.
7. When `load_power_w > 30000`, log a one-line ceiling warning at most once per hour per inverter.

Rollback of this phase is two steps. Setting `DEYE_FAST_INTERVAL_SEC=0` and restarting stops fast writes and does not start the fast task. The slow poll still uses the shared client. If that slow poll is unhealthy, revert the phase 3 commit so `read_deye_solarman` again opens and closes its own client on each slow poll. Env `0` alone does not restore that constructor.

Verify: unit test that a fake loop records a skip when the id is already in `_inflight_polls`, and an insert when it is free. A second case awaits, finds the id taken again, and does not set `owned` and does not discard the other task's id. No network.

Smoke, only if the gate's yes includes enabling on the server: set `DEYE_FAST_INTERVAL_SEC=1`, restart, wait two minutes. Expect about 60 `deye_fast` rows per inverter per minute. If either inverter stores fewer than 50 rows in any of those minutes, set the env back to `0` and do not start the 24-hour count. `deye_log` still about two rows per minute, and the existing aggregate log line still finishing in roughly the same time as before. A skip during the slow read is not an empty reply. If empty warnings cluster, set the env back to `0`.

Leave it at 1 second after that smoke. Do not set `2` in the same yes. The proof is the next 24 hours, both inverters. Group hours with `config.UA_TZ`. Apply the same three gates to each enabled inverter: at least 3000 `deye_fast` rows in that hour, no gap between consecutive rows longer than 15 seconds, and `max(load_power_w) - min(load_power_w)` greater than 1000 W. A flat hour or an hour with a multi-minute hole does not qualify. Move to 2 seconds only if every enabled inverter has at least one such hour in that day. One house hour is not enough.

Order rows by `ts`. A repeat is the next row whose eight fields (`grid_v_l1`, `grid_v_l2`, `grid_v_l3`, `grid_power_w`, `load_l1_w`, `load_l2_w`, `load_l3_w`, `load_power_w`) all equal the previous row. Move to 2 seconds only in a later yes, and only if more than half of those pairs in each enabled inverter's qualifying hour are repeats and fast-read warnings in those hours are few. If most pairs on any inverter are new frames, stay at 1. The slow snapshot should keep its ~32 second gap.

Gate: code merged or left local, as the operator says. Enabling `1` on the server is its own yes inside this gate, not implied by "continue". Enabling `2` is a later yes after the 24-hour count.

Landed locally 2026-11-22T16:42:30Z. Deployed 2026-11-22T17:05:23Z as `0672b4a`, with `DEYE_FAST_INTERVAL_SEC` unset on the server so the fast task did not start. `deye_fast` had 0 rows. First polls at 17:05:25Z: apartment battery 54.31 V, SOC 91, day load 54.4 kWh, total load 2909.27 kWh; house battery 535.1 V, SOC 98, day load 97.2 kWh, total load 852.56 kWh. Those counters match the previous row. Grid volts were already 0 before this restart, so that is an outage, not a scale change. No `Deye fast` log line.

Rollback: the two steps in the paragraph above. Env `0` and a restart stop fast writes. Revert the phase 3 commit if the slow poll must open and close its own client again.

### Phase 4 — show the fast sample

Goal: the open page uses the fast row for live load and voltages, and the load chart uses the minute maximum from `deye_fast` inside the visible window.

Touch: `database.py` (bounded max query), `power_monitor.py` voltage panel, `voltage_chart.py` if the load series is built there.

Steps:

1. Latest fast row: `WHERE inverter_id = ? ORDER BY ts DESC LIMIT 1`. Use it only when `now - ts <= 15`. Do not use `LIMIT 1` without `ORDER BY ts DESC`.
2. Copy the newest `deye_log` row and overlay only `grid_v_l1`, `grid_v_l2`, `grid_v_l3`, and the four load watts from that fast row. Pass the copy to the meters and to `_battery_panel`. Do this in `_build_update_fragments`, `dashboard()`, and `house_deye_inner_html`. Do not replace the row with a fast-only dict: `_battery_panel` reads SOC, battery watts, and battery temperature from the same row as the voltmeters. The age label stays on the `deye_log` timestamp.
3. Minute max uses the same `CAST(ts / ? AS INTEGER) * ?` grouping as `deye_voltage_buckets`, with the same `t0`, `t1`, and `inverter_id`. Overwrite `load_w` only for buckets that contain at least one `deye_fast` row. Voltage, SOC, and temperature keys stay the `deye_log` averages. Do not add a second unbounded scan.
4. History tables, `/api/status`, `last_nonzero_grid_voltage`, and `_record_voltage_sample` keep the unmodified `deye_log` row. `get_display_status` keeps calling `has_all_three_phases_voltage` and `has_grid_voltage_now` on `deye_log`.

Verify: a temp database with one fast row newer than 15 seconds changes the load and the three voltages and does not change SOC; a fast row older than 15 seconds is ignored; a minute with fast loads 100, 4000, 100 yields 4000 on the load series and does not change the voltage series.

Gate: no enable of a faster interval than what phase 3 left running.

Rollback: stop reading `deye_fast` in the panel. Leave the table.

Landed locally 2026-11-22T17:16:00Z. Deployed 2026-11-22T17:46:43Z as `b182b3f` by a manual pull and restart. `DEYE_FAST_INTERVAL_SEC` stayed 1. The restart left a gap of about 2.7 seconds in `deye_fast`. About 30 seconds later the open page showed the fast load: apartment 1325 W against a slow row of 1322 W, house 3765 W against a slow row of 3969 W. SOC stayed 86 and 95 from the slow rows. Grid volts were already 0 on both, so the meters showed 0. No fast-read failure in the journal. `latest_deye_fast` is `ORDER BY ts DESC LIMIT 1` and is ignored after 15 seconds. The overlay copies the slow row and replaces only the three voltages and the four load watts. Age stays on the slow timestamp. History tables, grid import and export totals, `/api/status`, and the voltage-status helpers still read `deye_log`. The load chart overwrites `load_w` with `MAX(load_power_w)` for the same minute buckets. `tests.test_deye_fast`: 20 tests OK. Local proof `verifiedAtUtc=2026-11-22T17:15:01.664Z`. Deploy proof `verifiedAtUtc=2026-11-22T17:47:33.522Z`.

## 8. Data and compatibility

No change to `deye_log` columns. Old rows stay. New table is empty until phase 3 is turned on.

`init_db` creates `deye_fast` on startup. A deploy of phase 1 or 2 creates an unused table. That is safe.

Downgrade: stop the fast loop. The table can remain. Do not drop it in code.

The slow reader must keep producing the same dict keys. `save_deye_log` stays the only writer of `deye_log`.

## 9. Verification and definition of done

Done means:

- Phases 1–4 have passed their gates, or a later decision in this file stops at an earlier phase.
- `python -m unittest tests.test_deye_fast` passes.
- With the fast interval at 1, both inverters gain about 60 fast rows a minute and the 5-minute aggregate log does not jump from under a second to many seconds.
- A later move to 2 seconds happens only after the 24-hour count in phase 3, and only with its own yes.
- The load chart's tall minute matches a fast row in that minute, checked once against `deye_fast` for the house inverter.
- No serial or API key in the diff.

Local tests do not prove the stick. The stick proof is the smoke in phase 3, on the server, in a quiet window, and only after a yes.

## 10. Risks, questions, decisions

### Risks

- A slow read that still takes several seconds will skip a few fast ticks. That is intended. Batching in phase 2 is what keeps the hole short.
- Two sockets to one stick collide. From phase 3 there is one client per inverter, shared by the slow read and the fast read. Phase 2 still opens a client only for the half-minute poll, then closes it.
- Register 653 will clip a house peak above 32.7 kW. The hourly log line is the signal to probe register 659. Do not widen the fast read in the same change as phase 3.
- The file grows by a few gigabytes a year per inverter at one row a second. That is accepted. Queries that draw the page must stay inside the visible day. Do not add a cleanup of `deye_fast` later "to be safe" without a new operator decision.
- The public repo must not gain the logger serial. Tests use a literal list of 56 integers.

### Open questions

None that block phase 1. Fast rows are kept. There is no keep-days setting.

### Decision log

- 2026-11-22T15:20:03Z — Create Plan self-review. Section 4 still told the next chat that fast rows must not live forever, against section 6.4. Fixed. Rejected-skin size updated to about 95 million `deye_log` rows in three years at one per second. Previous READY status superseded because keep-forever was not in the last critic pass. No CRITICAL or HIGH left. Proof `verifiedAtUtc=2026-11-22T15:20:03.920Z`.
- 2026-11-22T13:05:00Z — Skin A is 2 seconds, not 1. Evidence: 2026-11-22 house burst, 11 new frames out of 20 one-second reads. Skin B stays available as `DEYE_FAST_INTERVAL_SEC=1`. Superseded by the 2026-11-22T14:28:21Z decision below. The 20-second burst stays in the evidence table. It is no longer the reason to start at 2 seconds.
- 2026-11-22T13:05:00Z — Fast samples go to `deye_fast`, not `deye_log`. Reason: aggregates and the latest-row UI.
- 2026-11-22T13:05:00Z — Fast span stays 598 × 56 until a later probe of 659. Reason: that span is the one that was answered on both loggers. 540–653 was not tested and includes a gap in the map.
- 2026-11-22T13:05:00Z — Shipped interval is 0 until the phase 3 enable yes.
- 2026-11-22T13:05:00Z — self-review round 1. Findings: a new chat could point aggregates at `deye_fast` if the non-goal were only in the chat; the slow tick must also take `_inflight_polls` for the whole batch or the fast tick starts mid-read; phase 3 enable must not be implied by "continue". Fixes are in sections 1, 6, and phase 3. No CRITICAL or HIGH left in the draft.
- 2026-11-22T13:28:00Z — Lead review before the independent critic. Confirmed against `deye_reader.py`: `_apply_hv_battery` treats index 0 as register 587, apartment register 587 is × 0.01, and `REGS_32BIT` stores the high word first. The draft's slow-read table did not say that, so a batched reader could store a 537 V apartment pack or a swapped energy total. Also, phase 3's long-lived client plus phase 2's connect-per-poll would be two sockets once both run. Fixes are in section 6.2 and phase 3. Voltage alerts stay on `deye_log`. Status is `REVIEW IN PROGRESS` until the critic returns. Proof for this edit: composer `1ccc9355-92e4-47a9-90a2-abd5600f6e11`, `verifiedAtUtc=2026-11-22T13:27:53.778Z`.
- 2026-11-22T13:40:00Z — Critic round 1, model `grok-4.7-xhigh-fast`, verdict `CHANGES REQUIRED`, CRITICAL 0, HIGH 4, MEDIUM 5, LOW 2. All accepted. Fixes: house fallback is `587 × 9` through `_apply_hv_battery`, not the apartment × 0.01 reads; fast task starts only for interval 1 or 2 and does not hold the in-flight set while it sleeps; phase 3 rollback says env 0 stops fast writes but the shared client remains until the phase 3 commit is reverted; phase 4 overlays load and volts onto a copy of the `deye_log` row and names `has_all_three_phases_voltage` and `get_display_status`. Medium fixes: house SOC is index 2; the slow batch is one executor call and waits instead of skipping; a failed block omits only its keys; minute max uses the same bucket expression; `cleanup_old()` keeps its no-argument call and a separate fast cutoff. Low fixes: 3-second timeout replaces 10 seconds on the shared client; temp indexes are named. The separate fast cutoff in this bullet is superseded by 2026-11-22T15:15:59Z. Do not add it.
- 2026-11-22T15:29:00Z — Lead review, prompt #5, before the critic. Disk still matches sections 4 and 6.2: `_apply_hv_battery` index 0 is register 587, `REGS_32BIT` stores the high word first, `cleanup_old` deletes heartbeats only, and `deye_aggregates_refresh` reads `deye_log` only. Two contract holes fixed: phase 4 `LIMIT 1` now requires `ORDER BY ts DESC`, and a claim now requires check-and-add with no await plus an `owned` flag so one `finally` cannot drop the other task's claim. `read_deye_modbus` stays the old loop. KB harvest 2026-11-22T15:27Z still has no `power-monitor`. Proof `verifiedAtUtc=2026-11-22T15:26:25.467Z`. Status `REVIEW IN PROGRESS`. Critic not started yet.
- 2026-11-22T15:39:00Z — Critic round 1, model `grok-4.7-xhigh-fast`, agent `b6affc2d-2888-4f13-a70b-ac8f1135ace3`, verdict `CHANGES REQUIRED`, CRITICAL 0, HIGH 1, MEDIUM 1, LOW 3. All accepted. A complete slow batch no longer drops the client. Only the task that set `owned` may construct `PySolarmanV5`, inside the executor. `save_deye_fast` uses a new `_conn()` inside that executor before `owned` is cleared. A second `_poll_target` is not started while the previous one is still running. The 2-second switch needs a qualifying hour on every enabled inverter, not only the house. Status stays `REVIEW IN PROGRESS`.
- 2026-11-22T15:41:00Z — Confirmation, same model `grok-4.7-xhigh-fast`, same agent resumed. Verdict `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. The five round-1 fixes are in the file. Keep-forever and `ORDER BY ts DESC` still hold. Local implementation is allowed after a human yes. Status `REVIEWED / READY FOR LOCAL WORK`. The fast loop still ships off. `deye_fast` is still not deleted.

## 11. Progress log

- 2026-11-22T13:05:00Z — Plan drafted from the disk reader and from the read-only probes on 2026-11-21 and 2026-11-22. No code change. Next step is an independent review, then phase 1 only after a yes.
- 2026-11-22T13:28:00Z — Plan review, lead pass. Scales, HV slice, and one-socket rule written into the plan. Independent critic not started yet.
- 2026-11-22T13:40:00Z — Plan review, critic round 1 (`grok-4.7-xhigh-fast`): CHANGES REQUIRED, 0 CRITICAL, 4 HIGH. Fixes applied in the plan. Round 2 not run yet.
- 2026-11-22T13:50:00Z — Critic round 2, same model, verdict `APPROVE WITH DEFERRED`, CRITICAL 0, HIGH 0, MEDIUM 4, LOW 2. Deferred items applied before the confirmation pass: both short rollback lines name the two steps; the repo map says the fast tick skips and the slow poll waits; one fast task walks every enabled inverter; a partial slow batch is saved before the client is dropped; phase 2 lists the quantity-10 house test; section 6.5 matches the overlay.
- 2026-11-22T14:00:00Z — Confirmation pass, same model `grok-4.7-xhigh-fast`, verdict `APPROVE`, CRITICAL 0, HIGH 0. Local implementation is allowed after a human yes. Status is `REVIEWED / READY FOR LOCAL WORK`. The fast loop still ships off.
- 2026-11-22T14:28:21Z — Operator: start the live fast read at 1 second, and move to 2 seconds only after a longer record shows the module really refreshes about every 2 seconds. The 20-second burst is not that record. Proof: composer `1ccc9355-92e4-47a9-90a2-abd5600f6e11`, `verifiedAtUtc=2026-11-22T14:28:21.350Z`. First enable value is `DEYE_FAST_INTERVAL_SEC=1`. Code still accepts `2`. No poll is turned on by this note.
- 2026-11-22T14:33:08Z — Lead pass on that operator change, before the next critic. A sleep after the walk would turn a 1-second setting into about 1.4 seconds and blur the proof, so the loop now sleeps only the remainder. A moving hour is defined as more than 1000 W between min and max load. A repeat is all eight stored fields equal to the previous row. Status returns to `REVIEW IN PROGRESS`. Proof `verifiedAtUtc=2026-11-22T14:33:08.434Z`.
- 2026-11-22T14:40:00Z — Critic `grok-4.7-xhigh-fast` on the 1-second change: CHANGES REQUIRED, CRITICAL 0, HIGH 1, MEDIUM 1, LOW 1. Accepted. The remainder sleep is once after both inverters, not between them. A qualifying hour needs at least 3000 rows and no gap over 15 seconds. The sleep clock is `time.monotonic()`.
- 2026-11-22T14:45:00Z — Confirmation, same model: APPROVE, CRITICAL 0, HIGH 0. Status `REVIEWED / READY FOR LOCAL WORK`. First live rate remains 1 second. The loop still ships off.
- 2026-11-22T15:15:59Z — Operator: do not delete `deye_fast`. The 14-day cutoff was the planner's caution, not a request. Superseded: section 6.4 no longer deletes fast rows, and `DEYE_FAST_KEEP_DAYS` is not added. `cleanup_old` still deletes only old heartbeats. Proof: composer `1ccc9355-92e4-47a9-90a2-abd5600f6e11`, `verifiedAtUtc=2026-11-22T15:15:59.611Z`. One second for a year is about 31.5 million narrow rows per inverter. Chart queries stay on the day window. The energy job still reads only `deye_log`.
- 2026-11-22T15:20:03Z — Plan refreshed under prompt #6. Self-review removed the sentence that still told the next chat to expire fast rows. Status `DRAFT READY FOR REVIEW` until a new Review plan pass. No code.
- 2026-11-22T15:20:03Z — Create Plan refresh after that keep-forever decision. Self-review: section 4 still said fast rows must not live forever, which contradicted section 6.4 and would have made the next chat delete them. That sentence now says both tables are archives and fast rows stay out of `deye_log` only so the energy job and the latest-row page do not see partial snapshots. The rejected-skin count is updated to about 95 million rows in three years at one per second. Previous `REVIEWED / READY FOR LOCAL WORK` is superseded until a new Review plan pass, because keep-forever landed after the last critic. Status is `DRAFT READY FOR REVIEW`. Proof `verifiedAtUtc=2026-11-22T15:20:03.920Z`. No CRITICAL or HIGH left. No code change.
- 2026-11-22T15:29:00Z — Plan review, lead pass, prompt #5. Status `REVIEW IN PROGRESS`. Fixed the unordered `LIMIT 1` and the inflight claim that could be taken by two tasks. Marked the old fast-cutoff sentence superseded. Independent critic not started yet. Proof `verifiedAtUtc=2026-11-22T15:26:25.467Z`.
- 2026-11-22T15:39:00Z — Plan review, critic round 1 (`grok-4.7-xhigh-fast`): CHANGES REQUIRED, 0 CRITICAL, 1 HIGH, 1 MEDIUM, 3 LOW. All accepted. A full slow batch keeps the socket. Construction and the fast insert stay inside the owned executor call. No stacked house poll. Both inverters must qualify before 2 seconds. Round 2 not run yet.
- 2026-11-22T15:41:00Z — Plan review, confirmation (`grok-4.7-xhigh-fast`): APPROVE, CRITICAL 0, HIGH 0. Status `REVIEWED / READY FOR LOCAL WORK`. No code. Phase 1 waits for an explicit yes.
- 2026-11-22T16:14:30Z — Phase 1 landed locally. Operator yes via Agree & Continue. Proof `verifiedAtUtc=2026-11-22T16:11:21.429Z`. `decode_fast_block` and `save_deye_fast` only. A mistaken edit had dropped `charge_n` from `deye_recent_power`; that function was put back before the gate. `python -m unittest tests.test_deye_fast` passed, 6 tests. The same run plus the SOC and voltage bucket tests passed, 11 tests. No poll change, no page change, no deploy, no commit. Company KB searches at the start of this step still had no `power-monitor` hit. Disk stayed the source of truth.
- 2026-11-22T16:18:30Z — Phase 2 landed locally. Operator yes via Agree & Continue. Proof `verifiedAtUtc=2026-11-22T16:18:17.733Z`. `read_deye_blocks` is what the Solarman poll will use after a deploy. Port 502 is unchanged. `tests.test_deye_fast`: 12 tests OK. No `deye_fast` writer in the loop. No deploy, no commit.
- 2026-11-22T16:27:30Z — Phase 2 deployed. Operator yes to deploy this phase only, not phase 3. Commit `d174ec2`, tag `#autodeploy`. Service `ActiveEnterTimestamp` 2026-11-22T16:26:24Z. First new polls 16:26:27Z: apartment battery 55.28 V / SOC 91, house battery 538.0 V / SOC 98. Counters unchanged from the previous row. `year_load_kwh` was already null. No battery-block fallback in the journal. Proof for the plan note `verifiedAtUtc=2026-11-22T16:27:09.991Z`.
- 2026-11-22T16:42:30Z — Phase 3 landed locally, still off. Operator yes to write the loop, not to enable it and not to deploy. `DEYE_FAST_INTERVAL_SEC` default 0. `read_deye_solarman` no longer opens a socket. 17 tests OK. Proof `verifiedAtUtc=2026-11-22T16:42:14.534Z`.
- 2026-11-22T17:06:00Z — Phase 3 deployed off. Operator yes to publish the shared client and leave the one-second rate at 0. Server restart 2026-11-22T17:05:23Z, commit `0672b4a`. Env `DEYE_FAST_INTERVAL_SEC` unset. First polls 17:05:25Z kept apartment 54.31 V / SOC 91 and house 535.1 V / SOC 98. `deye_fast` count 0. No fast-task log. Grid volts were already 0. Proof `verifiedAtUtc=2026-11-22T17:06:00.739Z`.
- 2026-11-22T17:10:40Z — One-second smoke passed. Operator yes to enable 1, not 2. Server env `DEYE_FAST_INTERVAL_SEC=1`, restart 2026-11-22T17:07:53Z. Over the next minutes each inverter stored 53–54 rows in the two full minutes, max gap 3.74 s, no gap over 15 s. `deye_log` about two rows a minute. Nine overrun warnings, zero fast-read failures, zero block fallbacks. Left at 1 second. Proof `verifiedAtUtc=2026-11-22T17:10:41.809Z`.
- 2026-11-22T17:16:00Z — Phase 4 landed locally and was not deployed. Operator yes via Agree & Continue. Live meters and both text summaries overlay a fresh fast row onto a copy of the newest slow row. History and energy totals stay on `deye_log`. Load chart uses the fast minute maximum. Rate stays 1 second. No restart. 20 tests OK. Proof `verifiedAtUtc=2026-11-22T17:15:01.664Z`.
- 2026-11-22T17:48:00Z — Phase 4 deployed. Operator yes via Agree & Continue. Manual `git pull --ff-only` and `systemctl restart` at 2026-11-22T17:46:43Z, commit `b182b3f`. No `#autodeploy` tag, so this note must not restart the service again. Interval stayed 1. Page load matched the fast rows (apartment 1325 W, house 3765 W) while SOC stayed on the slow rows (86 and 95). Restart gap about 2.7 s. Grid was already at 0 V. Proof `verifiedAtUtc=2026-11-22T17:47:33.522Z`.

## 12. Handoff

Phase 4 is live as `b182b3f` since 2026-11-22T17:46:43Z. Sampling stays at 1 second, from 2026-11-22T17:07:53Z. Do not set 2 until a qualifying hour is counted on each inverter after a full day. Do not delete `deye_fast`. Do not put `#autodeploy` on a commit that also changes the interval.

Read this file and `plan_deye_fast_read_PROGRESS.md` before editing. Do not re-read the planning chat.

Do not touch breaker polling, Telegram, or `deye_aggregates_refresh`'s SQL except to keep it on `deye_log`.

Company KB does not contain this repo. Do not write logger serials or this plan into it. If a later prompt says to stop when KB is down, stop. Do not invent KB ids.

At each gate, update both files with a full DateTime and ask in Ukrainian whether to continue. Code, tests, and commit messages stay English.

Deploy and commit only when the gate's yes includes them.
