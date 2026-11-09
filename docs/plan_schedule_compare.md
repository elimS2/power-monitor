# Schedule compare board

- Status: `REVIEWED / READY FOR LOCAL WORK`
- Owner: Volodymyr
- Repo: `power-monitor` (public GitHub `elimS2/power-monitor`, live `https://power.elims.pp.ua`)
- Related Jira: none. Company KB does not index this repo.
- Last updated: 2026-11-09T13:24:48Z
- Active skin: **Skin A** (stored snapshots + stored change rows + one JSON board)
- This file is the implementation contract. A new chat must not need the planning conversation.

Companion: `power-monitor/docs/plan_schedule_compare_PROGRESS.md`

## 1. Goal and non-goals

### Goal

On the existing outage-schedule section, for one Kyiv calendar day at a time:

- Show the published 30-minute grid for our queue and, when asked, for the other queues of the same oblast.
- Mark our queue row so it stays obvious among the others.
- Show a transfers table for that day: added, cancelled, moved, severity change. Persist those rows.
- Overlay our real outages on the same day axis.
- Optionally overlay active voltage problems from inverter samples.
- Say, in minutes, how the published `off` slots matched our real outages.

Controls are checkboxes, remembered in the browser:

| Checkbox | Default | Effect |
|---|---|---|
| Відключення | on | Color `off` and `maybe` cells |
| Змінені | on | Outline slots touched by the latest revision |
| Скасовані | on | Draw slots that used to be `off`/`maybe` and are now `ok` |
| Наші фактичні | on | Bar of confirmed `down`→`up` intervals |
| Проблеми напруги | off | Bar of live high/low samples |

### Non-goals

- Other oblasts, Yasno city groups, the boiler schedule.
- Changing Telegram text, outage detection, or the 60-minute voltage notification pause.
- A chart library, a second database, a second fetcher.
- Scanning `deye_log` or `power_events` inside an HTTP handler. The page read is a stored row.
- Moving or retuning `deye_aggregates_refresh` / `deye_voltage_trend`. Those stay as they are. The board must not call them.
- Inventing history for queues we never stored. A missing snapshot is not a day of light.
- Backfilling old voltage bars by replaying `deye_log`. Voltage bars start from the first sample after deploy.
- Writing this feature, the house, or keys into the company knowledge base.
- Deploy, commit, or `#автооновити` unless the operator asks in a later chat.
- Neighbor-building outage statistics. Noted below so it is not forgotten. Not part of phases 1–4.

### Later: neighbor buildings

After our board is in use, collect observed outages from neighboring buildings and overlay them the same way as our own actual outages. Sources to use then: their Telegram bots or channels, and Svitlobot. Store that feed separately from `schedule_changes` (those rows are only DTEK plan diffs) and separately from our `power_events`. Do not start this during phases 2–4, and do not scan those chats on a dashboard request.

## 2. How this plan was adapted

Prompt library card **#6 Create Plan** is the working method. Applied here:

- Living plan + progress file, English, phases, skins, human gate between phases, self-review, no code in the planning turn.
- Disk is the source of truth. Company search on 2026-11-08T22:19:51Z did not find this repo (section 3). Do not block on that, and do not copy house facts into that KB.
- This workspace has no living-plan mutation-proof rule. None was required.
- No Jira ticket exists for this repo. Do not create one as part of implementation.

The operator's screenshot of the transfers table was not in the message payload. The column set in section 6 is the default. Correct it before Phase 4 if the picture differs.

## 3. Context harvest

Checked `user-knowledge-base-kb` on 2026-11-08T22:19:51Z. None of these hits are power-monitor. Do not treat them as design input.

| Volume | Query | What came back |
|---|---|---|
| knowledge, semantic | power monitor DTEK outage schedule dashboard | KB deploy, orchestrator, activity calendar. No power-monitor card. |
| ideas, semantic | power monitor outage schedule comparison chart | Unrelated cron and model ideas. |
| code_directories, semantic | power-monitor dtek schedule | invoice, RLT, scrapers. |
| code_files, hybrid | power-monitor dtek.py schedule_history | 0 FTS hits; semantic fallthrough was unrelated. |
| code_symbols, hybrid | fetch_dtek_schedule schedule_history_for_date | empty (`fallback_applied=or_like`). |
| jira, fts | power-monitor | KB-294 only, a Cursor workstation ticket. Not this repo. |

Dialogs were not searched. This repo is outside that KB, and house notes do not belong there.

Self-check:

- [x] knowledge searched, nothing relevant
- [x] ideas searched, nothing relevant
- [x] code_directories searched, nothing relevant
- [x] code_files searched, nothing relevant
- [x] code_symbols searched, nothing relevant
- [x] at least three real code paths from disk (below)
- [x] drill-down of the schedule, detection, and dashboard files
- [x] jira checked, no ticket
- [ ] dialogs — skipped on purpose, see above

### Repo map

| Path | Why it matters | Touch? |
|---|---|---|
| `dtek.py` `fetch_dtek_schedule` | Downloads the whole oblast, keeps only our queue, today and tomorrow | Yes. Keep `schedule_cache` as it is. Also save every queue and every date. |
| `dtek.py` `_day_slots_to_48`, `describe_grid_diff` | 1/2/3 → `ok`/`maybe`/`off`. Text diff already exists. | Extend with a structured classifier. Keep the text helper. |
| `dtek.py` `current_slot_status`, `schedule_deviation`, `next_schedule_transition` | Telegram and the status line. They read `schedule_cache` for our queue only. | Do not retarget them onto other queues. |
| `database.py` `init_db`, `_save_schedule_if_changed`, `schedule_history_for_date` | `schedule_history` has no queue column. Latest row for a date is "the" grid. | Yes, before any other queue is inserted. |
| `power_monitor.py` ~697 and ~1318 | Event table "Графік" column loads history for the event's date. | Must keep filtering our queue. |
| `power_monitor.py` `_build_schedule_inner` (~970), `_build_schedule_html` (~1072) | Today/tomorrow grid, text, history `<details>`. | Phase 4 chooses old vs new. |
| `power_monitor.py` `_build_update_fragments` key `pm_sched` (~891) | Every 10s the browser replaces `#pm-sched-content`. | The new controls must sit outside that node. |
| `static/app.js` `updScheduleNow` (~39), fragment handler (~223), poll 10s (~292) | "Now" marker assumes desktop row 1 is today, and mobile table 0 is today. | Rewrite the marker with the new board. |
| `static/style.css` `.sg-*` (~44–76) | The current cell colors. | Add classes. Do not restyle the rest of the page. |
| `config.py` `DTEK_REGION`, `DTEK_QUEUE`, `DTEK_API_URL` | `kiivska-oblast`, `5.1`, proxy URL. | Read them. Do not hardcode a second copy. |
| `power_monitor.py` `_voltage_band` (~565) | `<50` dead, `<198` low, `>240` high. | Reuse these numbers for the voltage bar. |
| `config.py` `VOLTAGE_EPISODE_MIN_INTERVAL_SEC = 3600`, `detection.py` `_send_voltage_recovery` | Notification pause. Recovery text ends the problem 60 minutes early (`stable_start = now - 3600`). | Do not use this window as the painted interval. Do not change the notifier. |
| `database.py` `deye_aggregates_snapshot` (~976), `deye_aggregates_refresh` (~984) | The recent fix: the 10s fragment reads a cached dict. The month-long `deye_log` scan runs in the background, about every 5 minutes, and bails if a run is already going (`power_monitor.py` `_refresh_deye_aggregates`, ~400). | Copy this split. Do not put a new scan on the fragment. |
| `database.py` `save_deye_log` (~860), `save_event` (~785), `deye_voltage_trend` (~1322) | A sample is already inserted every ~30s. `deye_voltage_trend(1000)` still scans up to 1000 rows per phase and is used by the lamp. | Hook the voltage bar on the single new sample inside `save_deye_log`. Do not call `deye_voltage_trend` from the board. |
| `api/dashboard.py` `/api/dashboard-fragments` | Key check + fragment JSON. | New read route follows the same key check. |
| `docs/DEPLOY.md` | Pull and restart. Schema changes run inside `init_db()` at process start (`power_monitor.py` ~467). | No new migrate command. |

There is no test package today. Phase 1 adds stdlib `unittest` only. Do not add pytest.

## 4. Current behavior

`fetch_dtek_schedule` (`dtek.py`) runs about every 30 minutes. It GETs `DTEK_API_URL`. A wrapper `{body: "<json string>"}` is unwrapped. The region is the object whose `cpu` equals `DTEK_REGION`.

Live payload observed 2026-11-08T22:22Z (User-Agent required for a raw urllib call; production `httpx` already updates the schedule, so do not change the client as part of this work):

- Top keys: `date_today`, `date_tomorrow`, `regions`.
- Region keys: `cpu`, `emergency` (bool), names, `schedule`. No transfers array.
- `kiivska-oblast`: `emergency` false, 12 queues: `1.1 1.2 2.1 2.2 3.1 3.2 4.1 4.2 5.1 5.2 6.1 6.2`.
- Queue `5.1` that hour had only `2026-11-09`, 48 slots, values `{1, 2}`. Tomorrow was not inside the queue. The code must not invent a missing date.

Slot map, already in `_day_slots_to_48`: `1 → ok`, `2 → maybe`, `3 → off`. Unknown values stay `ok` only if the key is absent; a present unknown value must be stored as `ok` and logged once, not dropped. The current function already treats anything other than 2 or 3 as `ok`. Keep that.

`schedule_cache` is only `today` and `tomorrow` for `DTEK_QUEUE`. Dates that are neither are ignored. `_save_schedule_if_changed` inserts a row when the JSON differs from the latest row for that date. There is no queue column, so the latest row is implicitly our queue. Callers:

- `schedule_history_for_date` in the event tables (`power_monitor.py` ~697 and ~1318) and in the history `<details>` (~1027).

The dashboard grid is 48 half-hour cells, two days, our queue only. History text comes from `describe_grid_diff`. Mobile CSS splits the day into two rows of 12 hours. `updScheduleNow` paints the "now" cell by row index.

Real outages are `power_events.event` of `down` and `up`. Voltage notifications are separate events (`voltage_high`, `voltage_low`, `voltage_issue`). They are sent after 3 confirming samples and then not again for 3600 seconds. The recovery message shortens the told duration by that hour. The chart must not copy either behavior.

`deye_log` has `grid_v_l1/l2/l3` and `ts`, polled about every 30 seconds (`DEYE_POLL_INTERVAL_SEC`).

Invariants that must still hold after every phase:

1. Telegram, the status lamp, and `schedule_deviation` keep using our queue's `schedule_cache` only.
2. A date we never saved is not drawn as 48 green cells.
3. The voltage bar is the sample interval, not the notification hour.
4. Confirmed outages are `down`/`up` only. A zero-volt sample that never became `down` is neither bar.
5. Europe/Kyiv day bounds, including DST. Use `UA_TZ`. No fixed UTC+2.
6. The dashboard key stays in the query string. Do not write it into docs, logs, or this plan.
7. This repo is public. The plan and the code must not gain personal notes or secrets.
8. An HTTP handler does not scan `deye_log` and does not walk the day's `power_events`. That work already happened on the write that stored the row. Same split as `deye_aggregates_snapshot` (cheap copy) versus `deye_aggregates_refresh` (the scan, off the request, from `bg_loop` via `_refresh_deye_aggregates`).

## 5. Skins

### Skin A — stored projection (default)

Each fetch writes one snapshot per queue per published date, and, when the grid or the emergency flag changed, the change rows for that step. The board reads those rows. Snapshots stay the source. Change rows are a projection written once, so a later tweak of the pairing rule does not silently relabel old days.

Switch to Skin B later without a new UI: stop inserting `schedule_changes` on the fetch, rebuild those rows in the same background write from consecutive snapshots, and keep GET as a read of the stored rows. Do not move that rebuild into the HTTP handler. Do not drop the table until a reviewed cleanup says so.

Rollback of the UI is kv `schedule_board` set to `0`. That restores `_build_schedule_inner`. It does not restore a `schedule_history_for_date` that ignores `queue`. After Phase 2 has inserted any other queue, the three callers (`power_monitor.py` ~697, ~1027, ~1318) must keep `queue = DTEK_QUEUE`. Do not git-revert Phase 1 on top of Phase 2 data. Do not drop the columns. Do not `DELETE` history. Stopping the extra writes is enough for new rows. Old other-queue rows stay and are ignored by the filtered readers.

### Skin B — rebuild the projection in the background

No live `schedule_changes` insert on each fetch. A background pass rebuilds the rows from snapshots, still off the HTTP path. Rejected as the default because the operator asked to store the transfers as they arrive, and because the move rule should be frozen per revision. Also rejected: recomputing that projection inside GET. That is the failure this review is closing.

### Skin C — browser calls DTEK itself

Rejected. The proxy returns only the currently published dates. Past days exist only in our SQLite. A day scrubber needs our rows.

## 6. Recommended shape

One SQLite file, the existing fetcher, one new read route, one board in the existing schedule section. No new service.

### 6.1 Tables

Follow the `init_db` style: `CREATE TABLE IF NOT EXISTS`, then `ALTER TABLE` inside `try/except sqlite3.OperationalError`.

`schedule_history` gains:

- `queue TEXT NOT NULL DEFAULT '5.1'` — existing rows become our current queue. That matches every row written so far.
- `emergency INTEGER NOT NULL DEFAULT 0` — the region flag on that fetch.

Index: `(queue, target_date, id)`.

`_save_schedule_if_changed(target_date, grid, queue, emergency)` compares the latest row **of that queue and date**. Insert when `grid_json` differs **or** `emergency` differs. Return the new row id, or `None` when unchanged. A flag flip with the same grid must still be stored, or the banner is lost.

`schedule_history_for_date(target_date, queue)` requires the queue. Every current caller passes `DTEK_QUEUE`. Do this in Phase 1, before Phase 2 inserts other queues. If Phase 2 landed first, the event "Графік" column would mix groups.

New table `schedule_changes`:

| Column | Meaning |
|---|---|
| `id` | integer pk |
| `queue`, `target_date` | which grid |
| `fetched_at` | unix time of the new snapshot |
| `history_id` | the new `schedule_history.id` |
| `kind` | `added`, `removed`, `moved`, `severity` |
| `start_slot`, `end_slot` | half-hour indexes, `end` exclusive, same as `describe_grid_diff` |
| `from_status`, `to_status` | `ok` / `maybe` / `off` |
| `peer_start_slot`, `peer_end_slot` | set only for `moved` (the new interval) |
| `emergency`, `previous_emergency` | 0/1, so a cancel during an emergency is marked |

Index: `(target_date, queue, id)`.

The first snapshot of a queue+date has no previous grid. It inserts history and **zero** change rows. That matches today's "Перший графік".

### 6.2 Classifier

New pure function next to `describe_grid_diff`, for example `classify_grid_changes(old, new) -> list[dict]`. Both grids are length 48.

Walk slots the way `describe_grid_diff` does: a block is a maximal run with the same `(old, new)` pair.

- `old` in (`off`, `maybe`) and `new == ok` → candidate **removed**
- `old == ok` and `new` in (`off`, `maybe`) → candidate **added**
- both not `ok` and `old != new` → **severity** (not a cancel, not a move)
- same status → ignore

Then pair removed with added:

- Duration may differ by at most 1 slot (30 minutes).
- Greedy: smallest duration difference, then smallest distance between starts, then the smaller start of the removed block, then the smaller start of the added block. Each block once. Ties do not depend on walk order.
- A pair becomes one `moved` row. `start/end` are the old changed run. `peer_*` are the new changed run. `from_status` is the old block's status, `to_status` is the new block's status. Slots that stay `off` in both grids are not part of the row. A four-hour block shifted two hours therefore records the leading edge moving onto the trailing edge, still as one `moved` row.
- Unpaired removed → `removed` (UI: скасовано).
- Unpaired added → `added` (UI: додано).

This is our reading of two snapshots, not a field DTEK sent. The table caption says that in one line: «За різницею знімків, не окреме поле ДТЕК».

Do not emit 48 cancels when a queue key is absent. Absence means "no snapshot", not an all-`ok` grid.

`region.emergency` is stored on the snapshot. The board shows a banner when the **latest** snapshot for the selected day has `emergency=1`: «Екстрені відключення: опублікований графік не діє». Slot diffs are still stored. The banner explains them. There is no separate `emergency` kind.

### 6.3 Fetch

Today `fetch_dtek_schedule` returns before the date loop when our queue object is missing (`dtek.py` ~312), and it assigns `schedule_cache = result` even when today is absent (~334). Phase 2 replaces that order.

- First, for every queue in `region["schedule"]`, for every date key that queue actually has, convert with `_day_slots_to_48` and save in the same transaction as that snapshot's change rows. A missing queue key writes nothing. Do not invent an all-`ok` grid.
- Remove the "skip unless today or tomorrow" filter for **storage**.
- Update `schedule_cache` only for `DTEK_QUEUE` and only for a today or tomorrow key that is present. If today is absent, leave the previous `schedule_cache["today"]` in place. If our queue object is absent, leave the whole cache in place and still save the other queues from this payload.
- One emergency bool is copied onto every snapshot of that fetch.
- Still only `DTEK_REGION`. The queue list is whatever that region published, not a hardcoded twelve.

### 6.4 Read route — stored rows only

`GET /api/schedule-board?date=YYYY-MM-DD&key=`

Same permission as the dashboard (`check_permission(key, "dashboard")` in `api/dashboard.py`). 403 uses the existing key-expired behavior. No anonymous access.

This handler is a few indexed reads. It does not classify grids, does not scan `deye_log`, and does not walk `power_events`. If `schedule_day` is missing, it returns `overlay_ready: false` and empty `actual`, `voltage`, and `match`. It does not build them on the spot.

Allowed queries, and nothing else:

1. Latest `schedule_history` row per queue for that date. One row per queue that has a snapshot that day. Index `(queue, target_date, id)`. No fixed cap of 12.
2. `schedule_changes` for that date. Index `(target_date, queue, id)`.
3. The one `schedule_day` row for `DTEK_QUEUE` and that date.
4. `SELECT DISTINCT target_date FROM schedule_history WHERE queue=? ORDER BY target_date`. The handler then adds today (`UA_TZ`) if it is not already in that list. That add is a clock read, not a `power_events` query.
5. `SELECT DISTINCT queue FROM schedule_history` with no date filter, plus `DTEK_QUEUE` always. A queue with no row on the selected date is still listed, with `has_snapshot: false` and `grid: null`.

An open **actual** interval is stored with `end: null`. The handler fills that `end` with `min(now, day_end)` from the clock. For voltage, if `last_ts` is at most 90 seconds old, `end` is `min(now, day_end)` of that interval's own Kyiv day, and it does not spill into the next day. If `last_ts` is older than 90 seconds, `end` is `last_ts`. The JSON body never contains `end: null`. `null` exists only in SQLite. Filling it is not a query.

Response (slot indexes and unix times; the browser formats Europe/Kyiv):

```json
{
  "date": "2026-11-09",
  "our_queue": "5.1",
  "overlay_ready": true,
  "available_dates": ["2026-11-08", "2026-11-09"],
  "emergency": false,
  "groups": {
    "5.1": {"has_snapshot": true, "grid": ["ok", "off"], "fetched_at": 0, "emergency": false},
    "1.1": {"has_snapshot": false, "grid": null, "fetched_at": null, "emergency": false}
  },
  "changes": [],
  "changed_slots": {"5.1": [16, 17]},
  "cancelled_slots": {"5.1": [10, 11]},
  "actual": [{"start": 1762646400, "end": 1762650000}],
  "voltage": [{"start": 0, "end": 0, "band": "high"}],
  "match": {"hit_min": 0, "miss_min": 0, "unplanned_min": 0, "scored_until": 0}
}
```

`our_queue` is `DTEK_QUEUE` from config, not a hardcoded 5.1 in the UI. The scrubber opens on today in `UA_TZ`, even when today has no snapshot. `available_dates` is our queue's stored dates plus that today. A queue with no row for the selected date returns `has_snapshot: false` and no cells, not 48 green cells. `actual` and `voltage` come from `schedule_day` when that row exists. If our queue has `has_snapshot: false`, `match` is null even when `schedule_day` exists. Do not call `recompute_match` without a stored grid, and do not invent 48×`ok`. GET does not extend match minutes unless that grid was loaded.

`changed_slots` and `cancelled_slots` are not columns. After the reads above, the handler builds the maps in memory from the change rows and the latest grids it already loaded. No second grid replay, no `deye_log`, no `power_events`. For each queue, `changed_slots` is the slots named by the latest revision only, both edges of a `moved` row included. `cancelled_slots` is every `removed` slot and the old edge of every `moved` row that is `ok` in the latest grid. A later revision that does not touch those slots does not erase them, because the handler reads the whole day's change list, not the last diff alone. The `changes` array is every stored revision that day.

`grid` in the JSON is the latest snapshot only.

Two identical GETs do not write. `schedule_day.updated_at` stays put.

### 6.5 Actual outages — written when the event is saved

Pure function `apply_power_event(actual_json, event, ts, day_start, day_end)`, used from `save_event` and from the one startup fill. Not used from GET.

`save_event` always INSERTs the `power_events` row first, for every event name, with one timestamp. That insert is what the 3600-second voltage pause and the recovery text already read (`last_voltage_problem_ts`). After the insert, if the name is not `down` and not `up`, return. Do not touch `schedule_day`. Do not use `DOWN_LIKE_EVENTS` for the bar. A test must show `voltage_high` present in `power_events` and absent from `actual_json`.

One helper, `apply_power_event`, is used by `save_event`, by the midnight branch, and by the startup fill. GET does not call it.

Rules:

- The list is closed intervals plus at most one open interval (`end: null` in SQLite).
- A `down` opens at its timestamp, clipped to that Kyiv day.
- An `up` closes the open interval. If yesterday's row is still open, close it at yesterday's `day_end` and write today as `[day_start, up_ts]`.
- GET only substitutes `now` for a null `end` on an actual interval.

Carry an open outage across midnight from the clock, not from `schedule_cache`. `date_rolled` (`power_monitor.py` ~436) is true only while the cache date is still yesterday and `now` is already today. After `lifespan` fetches (~468), the cache is already today, so `date_rolled` stays false until the next midnight. The carry must not depend on that flag.

`ended` is yesterday in `UA_TZ`. `started` is today in `UA_TZ`. In `bg_loop`, once per process start and again whenever the clock day changes, even if the DTEK fetch failed: two reads of `schedule_day`, no `power_events` read. If `ended` has an actual interval with `end: null`, close it at that day's `day_end` and recompute match through `day_end`. On `started`, write an open interval from `day_start` only when that row does not already have an open interval, so a `down` after midnight is not overwritten. If the `started` row exists, update only the actual columns and set `overlay_ready = 1`. Do not replace `voltage_json`. If `ended` has nothing open, do not invent an interval on `started`.

Voltage is not part of this carry. A voltage sample writes only the Kyiv day of its own `ts`. A stale voltage interval keeps `end = last_ts` when that stamp is older than 90 seconds.

Startup fill runs in `bg_loop` beside `_refresh_deye_aggregates`, never inside a request. Kv `schedule_day_actual_backfill_done` makes it once per database, not once per process. `power_events` is one row per confirmed change. Reading it once is allowed. Reading `deye_log` for history is not.

For each distinct `target_date` already in `schedule_history` for our queue, plus today: if that `schedule_day` row has `overlay_ready = 0` or does not exist, write `actual_json` from the last `down`/`up` before midnight plus the `down`/`up` inside the day. Do not overwrite a row `save_event` has already marked `overlay_ready = 1`. Then set the kv flag. Voltage JSON for those past days stays empty. The kv flag stops only this `power_events` pass. The clock carry from `ended` to `started` still runs at process start and when the Kyiv day changes. Set `overlay_ready = 1` on `started` only when that carry actually closed or wrote an interval, not when the row holds voltage alone. Otherwise the one-time fill would skip today.

### 6.6 Voltage bar — one sample at a time

Pure function `apply_voltage_sample(voltage_json, ts, v1, v2, v3)`, called at the end of `save_deye_log` with the values just inserted. It does not SELECT `deye_log`.

Bands are the numbers in `_voltage_band`: present means `>= 50`. Below that is `dead` and ends an open interval. No present phase ends it too. Otherwise `high` if any present phase is `> 240`, else `low` if any present phase is `< 198`, else the sample is healthy and ends the open interval.

Do not merge `low` and `high`. A band change closes one interval and opens the next. The gap rule uses the stored `last_ts` on the open interval: same band and `ts - last_ts <= 90` seconds extends it. A larger gap closes the old one at `last_ts` and opens a new one. Do not apply `VOLTAGE_CONFIRM_COUNT`, `VOLTAGE_EPISODE_MIN_INTERVAL_SEC`, or `stable_start = now - 3600`.

There is no `deye_samples_between`. A day of samples is about 2880 rows; reading them on a request, or again on every 30-second poll, is the bug this plan refuses. History from before deploy is not backfilled.

Do not call `deye_voltage_trend`. That function still serves the lamp and can scan 1000 rows per phase. The board has its own incremental state.

### 6.7 Match line — O(intervals), stored, extended on read

Our queue only. `maybe` is drawn and is not scored.

`recompute_match(grid, actual_json, scored_until)` runs when a snapshot for our queue is saved and when `actual_json` changes. It walks the stored intervals, not the sample log. Per minute up to `scored_until`: planned `off` and down → hit; planned `off` and up → miss; planned `ok` and down → unplanned. Store the three counts and `scored_until`.

On GET, if an actual interval is still open, add only the minutes from the stored `scored_until` to `min(now, day_end)` using that one open interval and the 48-slot grid. That loop is a handful of intervals, not 2880 rows, and it does not write. A past day whose interval was closed at midnight already has `scored_until` at `day_end`, so GET returns those counts unchanged. Voltage does not enter the match.

No snapshot for our queue → `match` is null, the UI says «Немає знімка», and it does not score a green day. A `schedule_day` row without a grid does not supply match numbers.

UI line: `Збіглось {hit} хв · Світло було всупереч графіку {miss} хв · Позапланово не було {unplanned} хв`.

### 6.7a `schedule_day`

One row per our queue per date. Other queues do not get this row.

| Column | Meaning |
|---|---|
| `queue`, `target_date` | primary key |
| `actual_json` | closed intervals and at most one open `down` |
| `voltage_json` | closed intervals and at most one open `{band, start, last_ts}` |
| `match_json` | `{hit_min, miss_min, unplanned_min, scored_until}` |
| `overlay_ready` | 1 after the actual-bar fill or the first `down`/`up` writer |
| `updated_at` | unix, changes only on a writer |

Changed and cancelled slot maps are not stored here. Section 6.4 builds them from `schedule_changes`.

Index is the primary key. Each writer, in one transaction, updates only its own columns. A missing row is one INSERT of those columns, not a read-modify-write of every JSON field.

- `save_deye_log`: `voltage_json` and `updated_at` only. No `SELECT` from `deye_log`. No `recompute_match`. This hook runs from the poller and from `POST /api/deye-heartbeat`. It must stay a single-row update.
- `save_event` after the insert, and only for `down`/`up`: `actual_json`, `match_json`, `overlay_ready`, `updated_at`.
- Our queue's snapshot save: `match_json` from the new grid plus the stored `actual_json`. It does not create a `schedule_day` row for any other queue.
- Startup fill and the midnight branch: actual columns only, as in 6.5. The midnight branch does not stretch a voltage interval to `day_end`.

`_conn()` opens a new connection per call. Two writers must not read the whole row and write every column back. That race drops either the outage bar or the voltage bar.

### 6.8 Board UI

The interactive shell is a sibling of `#pm-sched-content`, inside `#sched_details`, with its own id `#pm-sched-board`. `app.js` must not assign `innerHTML` on that node during the 10s fragment refresh. If it does, the day cursor and the checkboxes reset. That is a defect.

The flag is on when `kv_get("schedule_board") != "0"`. A missing key is `""` from `kv_get` (`database.py` ~318), and that means the board is on. Do not test the value for truthiness.

Both the full page (`dashboard` ~1526, via `_build_schedule_html`) and the fragment key `pm_sched` use that one test. When the board is on, `#pm-sched-content` is only today's text from `schedule_cache` through the existing `grid_text_summary`. That text counts `maybe` as dark (`dtek.py` ~219). Leave the function alone. Its percentages are not the match line. The fragment does not call `schedule_history_for_date`, does not read `schedule_day`, and does not call the board route. When the flag is `0`, `pm_sched` and the full page are today's `_build_schedule_inner`, and `#pm-sched-board` stays hidden. One grid is visible. The rest of `_build_update_fragments` (events at ~697 and ~1318, the lamp) keeps running and does not call `/api/schedule-board`.

The flag is the rollback. Deleting the old renderer is **not** in this plan. It stays until a later cleanup after the board has been used.

Board contents:

- Opens on today (`UA_TZ`). Prev/next move through `available_dates`. Buttons disable at the ends. The label is the Kyiv date and weekday (`UA_WEEKDAYS`).
- Queue checkboxes from every queue ever stored, plus our queue always (section 6.4 query 5). Our queue is checked and disabled, with a "наша" badge and class `sg-ours` (left border, not color alone). Other queues default off. A queue with no row on the selected day still appears, labeled «Немає знімка». Selection key `pm_sched_groups` in `localStorage`.
- The five layer checkboxes. Keys `pm_sched_show_off`, `pm_sched_show_changed`, `pm_sched_show_cancelled`, `pm_sched_show_actual`, `pm_sched_show_voltage`.
- One 24-hour table. Its own class, not `sg-desktop` and not `sg-mobile`. `.sg-table` is `width:100%` and `table-layout:fixed` (`style.css` ~52), and under 768px `.sg-desktop` is `display:none`. A board table with those classes would squash or vanish. Give the board table a `min-width` so the existing `.sg-wrap` scrolls. Do not restyle the old grid.
- The board paints "now" on our row for today only, with `sb-now-yes` or `sb-now-no`, not `.sg-now` inside `.sg-table`. `updScheduleNow` returns on its first line when `#pm-sched-board` is visible, before `querySelectorAll('.sg-now')`. Otherwise the 10-second timer strips the marker and then paints desktop row 1. The two classes and the match rule are in 6.8a.
- A queue with `has_snapshot: false` shows the label and «Немає знімка» instead of cells.
- When `overlay_ready` is false, do not draw an empty actual bar as "no outage". One line: «Фактичні ще не зведені». The grid still shows.
- Cells use the existing `.sg-ok`, `.sg-off`, `.sg-maybe`. Add `.sg-changed` (outline) and `.sg-cancelled` (hatch). Unchecking «Відключення» removes off/maybe color but does not remove the row. «Скасовані» is the only way a now-`ok` slot shows that it was planned before.
- Under our row, two bars positioned by `(minute / 1440) * width`: `.sg-bar-actual`, `.sg-bar-voltage-low`, `.sg-bar-voltage-high`. They are not snapped to the 30-minute cell. Other queues do not get these bars. We have no measurements for them.
- The transfers table for the selected day, rows whose queue is visible (ours always). Columns: «Коли побачили», «Група», «Що сталося», «Було», «Стало». Kinds: додано, скасовано, перенесено, змінено. Our group name is bold. Times are Kyiv `%Y-%m-%d %H:%M`. A move shows `08:00–12:00 → 14:00–18:00`. Caption as in 6.2.
- The match line under the table.
- Empty change list on the first snapshot: «Змін ще не було».

Data load: one `fetch('/api/schedule-board?...')` when the selected day changes, when the tab becomes visible, and every 60 seconds while the selected day is today. That response is the stored JSON from section 6.4. Checkbox and group toggles filter it in the browser and do not fetch again. The 10-second fragment URL is not `/api/schedule-board`. A fragment tick does not rebuild the board.

`updScheduleNow` keeps working for the old grid when the flag is `0` and `#pm-sched-board` is hidden. When the board is visible it returns immediately and calls `pmPaintBoardNow`.

### 6.8a Now marker and live match

Recorded 2026-11-09T13:19:34Z. Built 2026-11-09T13:24:48Z after an explicit yes. Not on the live site until a later deploy.

What was weak: `pmPaintBoardNow` only added `.sb-now`, a thin yellow inset. The old grid used `.sg-now-on` / `.sg-now-off` with the lightning glyph and the `sg-glow` / `sg-flash` animations.

Only our row, and only when the selected day is today. Other groups stay plain. No new request and no scan. Each cell stores `data-sb-plan` (`ok` / `off` / `maybe`) so the marker still works when the «Відключення» layer is off and the `sg-*` color classes are absent. The live light is `document.body.dataset.pmDown`, which the 10-second fragment already updates. `renderBoard` calls `pmPaintBoardNow` after it writes the table, and `updScheduleNow` calls it every 10 seconds. Neither call refetches `/api/schedule-board`.

| Planned slot | Light now | Marker |
|---|---|---|
| `off` or `maybe` | down | agrees — `.sb-now-yes`, yellow lightning, reuses `sg-glow` / `sg-flash` |
| `ok` | up | agrees — `.sb-now-yes` |
| `off` | up | disagrees — `.sb-now-no`, red lightning, `sb-glow-no` / `sb-flash-no` |
| `ok` | down | disagrees — `.sb-now-no` |
| `maybe` | up | not a firm miss — `.sb-now-yes` |

Today's board also shows one line: «Жовте блимання — графік і світло сходяться. Червоне — ні.» A local fixture of the four cells (2026-11-09T13:24:04Z) showed the lightning glyph, yellow `sg-glow` on agree, and red `sb-glow-no` on disagree. That fixture is not the live dashboard.

Not in this slice: coloring the whole day by match, a vertical line through every group, or a second bar. The red actual-outage bar stays as it is. The old `.sb-now` rule is gone; the painter still strips that class so a cached script cannot leave it behind.

### 6.9 What lives where

| Piece | Place |
|---|---|
| Slot convert, classifier | `dtek.py`. Runs on fetch, not on GET. |
| Schema, `schedule_day` writers | `database.py` (`save_event`, `save_deye_log`, `_save_schedule_if_changed`) |
| Thresholds 50 / 198 / 240 | `config.py`. `_voltage_band` and `apply_voltage_sample` both read them. |
| Pure interval and match functions | `schedule_board.py`. Import direction: `config` ← `schedule_board` ← `database` ← `power_monitor`. `apply_voltage_sample` does not import `power_monitor` or `database`. |
| Startup actual-bar fill | `bg_loop`, beside `_refresh_deye_aggregates`. Once per database, kv `schedule_day_actual_backfill_done`. |
| Fetch loop | `dtek.py` `fetch_dtek_schedule` |
| JSON route, reads only | `api/dashboard.py` |
| Shell markup | `power_monitor.py` `_build_schedule_html` |
| Behavior | `static/app.js` |
| Classes | `static/style.css` |
| Tests | `tests/test_schedule_board.py` |

`schedule_cache` stays a process global for our queue. The board GET does not read it. The fragment text summary, when the flag is on, does.

## 7. Phases

Each phase ends with a human gate. The agent stops, says in plain language what changed, what was checked, what is risky, and asks whether to go on. The next phase does not start without an explicit yes. Update this file and the progress file at the gate. Timestamps are full DateTime values.

Do not deploy and do not commit unless that same yes includes it. Production schema applies on process start via `init_db()`. A local test uses a temporary SQLite file, never the server db and never SSH.

### Phase 1 — queue column, readers still see only us

Goal: old history still means our queue, and a second queue cannot be compared by accident.

Touch: `database.py` (`init_db`, `_save_schedule_if_changed`, `schedule_history_for_date`), call sites in `power_monitor.py` (~697, ~1027, ~1318), `dtek.py` save call. Tests for "two queues do not share a latest row".

Steps:

1. Add `queue` and `emergency` as in 6.1. Default fills old rows.
2. Thread `queue` through save and read. Callers pass `DTEK_QUEUE`.
3. Fetch still saves only our queue, still only today and tomorrow. `schedule_cache` unchanged.

Verify: `python -m unittest tests.test_schedule_board`. On a temp db, insert two queues for one date and assert `schedule_history_for_date(date, our)` does not return the other grid. Negative: omitting the queue filter in a throwaway query would mix them — the production function must not do that.

Gate checklist: existing dashboard history text for our queue is unchanged; no other queue is written; no deploy yet.

Rollback while no other queue has been inserted: the new columns have defaults. Reverting this phase's code leaves them unused. Do not drop columns. After Phase 2 has written other queues, this revert is forbidden. See section 5.

This phase is code plus a startup migration. It does not change the live site until a later deploy.

### Phase 2 — store every published queue, and the change rows

Goal: the database holds the transfers table. The page does not show it yet.

Touch: `dtek.py` fetch loop and `classify_grid_changes`; `database.py` insert of `schedule_changes`. Tests for the classifier.

Steps:

1. Implement the classifier from 6.2, including the move rule and the "missing queue is not all-ok" rule.
2. One function inserts the snapshot and its change rows before the connection commits, and returns the new id or `None`. `None` means the grid and the emergency flag were unchanged, and no change rows are written. Do not classify after that function returns. `_save_schedule_if_changed` today commits when the `with _conn()` block ends and returns nothing (`database.py` ~1482). Splitting the change insert into a second call drops the transfer rows, and the next fetch will not recreate them.
3. Save every queue and every date key present in the payload. Keep `schedule_cache` limited to our today/tomorrow.
4. Also insert when only `emergency` flipped.

Verify: unit cases — first snapshot has no changes; `off→ok` is `removed`; `ok→off` is `added`; `off→maybe` is `severity`; a 4-hour block shifted by 2 hours with duration within 1 slot is one `moved`; two blocks whose durations differ by 2 slots stay `removed` + `added`; absent queue writes nothing. A temp-db fetch fixture (saved JSON, no network) writes 12 queues and does not change a second call when the grid is the same.

Gate checklist: `schedule_cache['today']` is still our queue; event history queries pass the queue; row counts logged, not guessed.

Rollback: stop the extra writes. Extra rows sit unread. Do not delete them.

Code and migration only. Live collection starts at deploy, which is not this phase.

### Phase 3 — writers fill `schedule_day`; GET only reads it

Goal: the endpoint returns grids, changes, actual intervals, voltage intervals, and the match, with no HTML and no scan.

Touch: `schedule_board.py`, `database.py` (`save_event`, `save_deye_log`, `_save_schedule_if_changed`, `init_db`), `api/dashboard.py`, the startup hook in `bg_loop`.

Steps:

1. Add `schedule_day` as in 6.7a.
2. `apply_power_event` and `apply_voltage_sample` as in 6.5 and 6.6. Hook them on the writes named there. `apply_voltage_sample` takes the three volts as arguments and does not query.
3. `recompute_match` on snapshot save and on actual-json change.
4. Startup fill as in 6.5: every stored date for our queue, plus today, once per database, skip rows already `overlay_ready = 1`, no voltage backfill, not inside the route.
5. Route as in 6.4. A missing row returns `overlay_ready: false` and does not compute.

Verify, all on fixtures, no network:

- A `down` before the day and an `up` at 01:00 Kyiv, applied through the writer, stores midnight–01:00. GET does not issue that query.
- A `voltage_high` event does not appear in `actual` and does not write `schedule_day`.
- Samples at t, t+30s high, t+120s high stay two intervals if the gap is `> 90` and one interval if the gap is `90`. The function sees one sample per call.
- A 3600-second notification gap is not filled in.
- A `<50` sample ends a voltage interval and is not itself voltage.
- `off` + down = hit; `off` + up = miss; `ok` + down = unplanned; `maybe` + up adds nothing.
- No snapshot → `has_snapshot: false` and null match.
- Wrong or missing key is rejected the same way as `/api/dashboard-fragments`.
- Negative: a test double raises if the route calls `deye_voltage_trend`, `deye_aggregates_refresh`, `events_in_range`, `recent_events`, or any `SELECT` from `deye_log` or `power_events`. The route still returns 200.
- Negative: `_build_update_fragments` does not call the route.
- Negative: two GETs leave `updated_at` unchanged.
- Negative: one `save_deye_log` performs no `SELECT` against `deye_log` for the board (the insert itself remains).
- Negative: `voltage_high` is inserted into `power_events` and does not write `schedule_day`.

Gate checklist: route is read-only; our queue in the JSON equals `DTEK_QUEUE`; the 10-second fragment function does not call the new route.

Rollback: remove the route and the hooks. `schedule_day` can stay unread. Do not drop it in the same revert.

### Phase 4 — the board

Goal: the dashboard shows the scrubber, the group rows, the checkboxes, the bars, the table, and the match line.

Touch: `power_monitor.py`, `static/app.js`, `static/style.css`, kv flag read.

Steps:

1. Markup and classes from 6.8. Flag default on. Flag `0` restores the old inner HTML and hides the board.
2. `localStorage` for groups and checkboxes. Our queue always on.
3. Fetch the stored JSON on day change, on tab visibility, and on the 60s today-tick. Checkbox and group toggles do not fetch. Fragment replace must not touch `#pm-sched-board` and must not request `/api/schedule-board`.
4. `updScheduleNow` must not use row index on the new table.

Verify:

- Unit tests from Phases 1–3 still pass.
- Local page: open today, step to a day with no data, see «Немає знімка», not a green row.
- Toggle each checkbox and reload: the choice sticks.
- Turn the flag to `0`: the old today/tomorrow grid returns, and only one grid is on screen.
- With the flag on, wait through one 10s fragment refresh: the selected day and the checkbox state stay, and the fragment request is not `/api/schedule-board`.
- Toggle a checkbox and a group: no new request.
- "Now" sits on our row only, and only for today.
- A voltage fixture whose samples last 4 minutes paints about 4 minutes, not an hour, and the paint does not query `deye_log`.
- Desktop width and a narrow viewport: the table scrolls sideways; the controls wrap; nothing covers the day buttons.

Browser check of production is part of the deploy gate, not of this phase's local work. If the local server cannot run, say exactly which clicks were not done.

Gate checklist: operator looks at one real day and says the our-row mark, the table, and the actual bar match what they expect.

Rollback: set kv `schedule_board` to `0`. No data delete. Old renderer is still in the code.

### Deploy

Not a phase and not automatic. After the operator accepts a phase and asks to ship: commit (English message, no secrets), push, then the usual `git pull` and restart from `docs/DEPLOY.md`. `init_db()` applies the columns. Do not add `#автооновити` unless they ask. After restart, confirm the footer commit hash and that Phase 2 has written more than one queue. Then do the production browser pass from Phase 4.

## 8. Data and compatibility

- Old `schedule_history` rows gain `queue='5.1'` and `emergency=0`. That is the correct backfill. There is no other historical queue to reconstruct.
- New writes are additive. Readers of our queue stay valid only while they pass `queue = DTEK_QUEUE`. The pre-Phase-1 reader does not. Do not put that reader back after other queues exist.
- Dual-read: the old grid function remains behind the flag. The board reads the new JSON. They do not both render.
- No backfill job for other groups. Their first day is the first successful fetch after deploy.
- The change table can be rebuilt later from snapshots in the background (Skin B) if a bug in the classifier is found. Do not hand-edit rows. Do not rebuild them inside GET.
- `schedule_day` is the overlay cache. It is empty until the writers run. Missing means `overlay_ready: false`, not a request-time scan.
- Feature flag: kv `schedule_board`. Missing means on, so a fresh db shows the board after Phase 4. Set `0` to roll back the UI only. The flag does not change the writers. They stay cheap either way.

## 9. Verification and done

Done means:

- Phases 1–4 accepted at their gates.
- `python -m unittest tests.test_schedule_board` passes.
- Our queue's Telegram path was not pointed at another queue (code read of `schedule_cache` writers).
- The board shows our row marked, other queues on request, transfers stored and listed, actual bars from `down`/`up`, voltage bars from samples, and the match line.
- The 60-minute notification rule is unchanged and is not what the voltage bar draws.
- `GET /api/schedule-board` and `_build_update_fragments` do not scan `deye_log` or `power_events` for this feature. A test double proves the route.
- A missing snapshot is labeled, not painted green.
- Flag `0` restores the previous grid.
- Production browser pass done after deploy, or explicitly listed as not done.

Local checks use a temp database and, for the UI, the local process. Do not point tests at `https://power.elims.pp.ua`.

## 10. Risks, questions, decisions

### Risks

- The move rule can pair a real cancel with an unrelated new outage of similar length. The caption states it is a diff, and the duration guard is 1 slot. A wrong pair is visible in the table and can be rebuilt from snapshots.
- Until deploy, other queues have no past. The empty state must be obvious.
- `updScheduleNow` will mark the wrong cell if someone leaves it on row index 1 after adding group rows. Phase 4 forbids that.
- Putting controls inside `#pm-sched-content` resets them every 10 seconds. Phase 4 forbids that.
- An emergency all-`ok` grid will look like a mass cancel. The banner is what stops that from being read as an ordinary edit. Do not suppress the rows.
- Public repository. Do not commit `.env`, keys, or this plan's companion if someone later pastes a key into it.
- A GET that "just this once" scans the day will be called every 60 seconds, and the 10-second fragment will be the next place someone puts it. The route must stay a read even when `schedule_day` is missing.
- `save_deye_log` runs about every 30 seconds. If that hook selects the day's samples, the poller becomes the heavy job. The hook takes the sample it just inserted and updates one row.

### Open questions

None blocking. Defaults are already chosen.

- Screenshot columns, if the unseen picture differs: say so before Phase 4. Default is section 6.8.
- Voltage checkbox default off, so the first view is the outage comparison. Turn it on when wanted.
- `maybe` is not a miss when the light stays on.

### Decision log

| When | Decision | Why |
|---|---|---|
| 2026-11-08T22:24:28Z | Skin A. Snapshots canonical, change rows stored once. | The operator asked to keep the transfers. The API has no such table. Recomputing later would relabel history. |
| 2026-11-08T22:24:28Z | Other queues are stored for the whole oblast. The highlighted row is `DTEK_QUEUE`. Detection stays on `schedule_cache`. | Comparison was requested. Mixing queues into the lamp would be a behavior change. |
| 2026-11-08T22:24:28Z | Voltage bar uses samples and the 50/198/240 bands. It ignores the 3600s pause. | The operator asked for the active problem, not the hour that waits for the next message. |
| 2026-11-08T22:24:28Z | Outage bar is `down`/`up` only. | Those are the confirmed cuts. Zero volts without `down` is neither layer. |
| 2026-11-08T22:24:28Z | Phase 1 filters by queue before Phase 2 writes other queues. | Otherwise the event "Графік" column mixes groups. |
| 2026-11-08T22:24:28Z | Board DOM is outside the 10s fragment. Old grid remains behind kv `schedule_board`. | Fragment replace would wipe the scrubber. The old view is the rollback. |
| 2026-11-08T22:24:28Z | Company KB is evidence of absence only. No KB writes. | This repo is not indexed there, and house data stays local. |
| 2026-11-08T22:24:28Z | self-review round 1 | See below. Findings folded into this text before status was raised. |
| 2026-11-08T22:32:13Z | Request path stays a read. Supersedes the sentence in the old 6.6 that said a day is ~2880 rows and needs no cache table. | Operator review: do not repeat the bug where each page request ran the heavy Deye scan. Precedent already in tree: `deye_aggregates_snapshot` vs `deye_aggregates_refresh` / `_refresh_deye_aggregates`. Voltage advances one sample inside `save_deye_log`. Actual bars advance inside `save_event`. GET fills only a null `end` from the clock. |
| 2026-11-08T22:44:32Z | Critic round 1 fixes. Midnight uses one helper. Slot hatch is derived from stored change rows at read, in memory. Fetch saves other queues even when ours is missing and does not replace a good `schedule_cache`. | The critic showed the draft contradicted itself on overnight outages, backfill scope, and rollback. Those are now one rule each. |
| 2026-11-08T22:55:00Z | Critic round 2. Carry the open outage by the clock (`ended` = yesterday, `started` = today), including once at process start, without reading `power_events` and without replacing `voltage_json`. | `date_rolled` is false after the startup fetch, so a rule that says "today's row" looks at an empty day and drops the live bar. |
| 2026-11-08T23:05:00Z | Final confirmation APPROVE. The kv flag stops only the `power_events` backfill. The clock carry still runs. `overlay_ready` on the new day is set only when that carry wrote an interval. | Critic round 3, same model, 0 CRITICAL, 0 HIGH. Status `REVIEWED / READY FOR LOCAL WORK`. Implementation still waits for an explicit yes. |
| 2026-11-08T22:58:59Z | Phase 1 implemented. History rows carry `queue` and `emergency`. Readers pass `DTEK_QUEUE`. Fetch still stores only our queue, today and tomorrow. | Operator said yes via Agree & Continue. Four unittest cases passed on a temporary database, including a legacy table without the new columns. Live site was not restarted. |
| 2026-11-08T23:07:29Z | Phase 2 implemented. Every published queue and date is stored. Change rows are written in the same transaction as the snapshot. `schedule_cache` is updated only for our queue's today/tomorrow keys that the payload contains. Neighbor-building statistics are deferred. | Operator said yes. 18 unittest cases passed. The page was not changed. Not deployed. |
| 2026-11-08T23:27:27Z | Phase 3 implemented. `GET /api/schedule-board` only reads stored rows. Outage bars update inside `save_event` for down/up. Voltage bars update inside `save_deye_log` from the sample just inserted. Backfill and midnight carry run in `bg_loop`. | Operator said yes. 30 unittest cases passed. The page still does not draw the board. Not deployed. |

#### Self-review round 1 (2026-11-08T22:24:28Z)

Hat: critic of the draft.

- HIGH, fixed here: `updScheduleNow` uses desktop row 1 and mobile table 0. The board section now says the marker is our row + today's slot, and the old function no-ops when the old grid is absent.
- HIGH, fixed here: 10s `innerHTML` on `#pm-sched-content`. Controls live in `#pm-sched-board`.
- HIGH, fixed here: save/read without `queue` would corrupt history once twelve queues exist. Phase 1 is a hard predecessor of Phase 2.
- HIGH, fixed here: a missing payload must not become 48×`ok`, and an emergency flag flip must insert even when the grid string is unchanged.
- HIGH, fixed here: voltage painting must not use `stable_start` or the 3600s gate. A test locks that.
- MEDIUM, fixed here: `events_in_range` misses a cut that started yesterday. The read uses the last `down`/`up` before midnight.
- MEDIUM, accepted: move pairing can be wrong. Caption + 1-slot rule + rebuild-from-snapshots. Not a second algorithm in the UI.
- MEDIUM, accepted: the screenshot was not attached. Columns are specified. Open, not blocking.
- LOW: no company code paths exist. The map lists disk paths instead of inventing KB ids.

No CRITICAL left. No HIGH left open. Status set to `DRAFT READY FOR REVIEW`. This is not an approval to implement.

## 11. Progress log

| When | Event |
|---|---|
| 2026-11-08T22:19:51Z | Harvest started. Company KB has no power-monitor index. |
| 2026-11-08T22:22:00Z | Live proxy read: 12 queues, no transfers field, `emergency` bool, queue dates only where published. |
| 2026-11-08T22:24:28Z | Plan and progress file written. Skin A. Self-review round 1 folded in. Status `DRAFT READY FOR REVIEW`. |
| 2026-11-08T22:32:13Z | Lead review, prompt #5. Folded the request-budget rule into sections 4, 6.4–6.7a, 6.8, phase 3, and the decision log. Status `REVIEW IN PROGRESS`. |
| 2026-11-08T22:44:32Z | Critic round 1 (`grok-4.7-xhigh-fast`, agent 41da51f5). Verdict CHANGES REQUIRED. 1 CRITICAL, 8 HIGH, 5 MEDIUM, 3 LOW. All folded. |
| 2026-11-08T22:55:00Z | Critic round 2, same model. Previous CRITICAL and HIGHs confirmed fixed. One new HIGH on the midnight carry, two MEDIUM, one LOW. All folded. |
| 2026-11-08T23:05:00Z | Critic round 3, same model. APPROVE. 0 CRITICAL, 0 HIGH. The kv-flag sentence is in section 6.5. Status `REVIEWED / READY FOR LOCAL WORK`. |
| 2026-11-08T22:58:59Z | Phase 1 done locally. `python -m unittest tests.test_schedule_board` — 4 tests OK. Windows holds the temp WAL open because `sqlite3`'s context manager does not close the connection; the test ignores that cleanup error. Production `_conn()` is unchanged. Next is the human gate before Phase 2. No deploy. |
| 2026-11-08T23:07:29Z | Phase 2 done locally. Same test module, 18 OK. A four-hour block shifted by two hours is one `moved` row of the edges that actually changed (16–20 onto 24–28), because the overlap stays `off`. Neighbor outages from Telegram or Svitlobot are written into the plan as later work, not this phase. Human gate before Phase 3. No deploy. |
| 2026-11-08T23:27:27Z | Phase 3 done locally. `python -m unittest tests.test_schedule_board` — 30 OK. The route test rejects a bad key with 403 and a spy connection rejects any `deye_log` or `power_events` read. Human gate before Phase 4. No deploy. |
| 2026-11-09T13:00:34Z | Phase 4 done locally. The board shell is outside `#pm-sched-content`. The 10s fragment is only today's text summary and does not request `/api/schedule-board`. `updScheduleNow` returns immediately when the board element exists. Checkbox and group changes stay in the browser. Flag test: missing kv shows the board, `0` hides it. Browser click-through of the live site was not done because this phase is not deployed. |

## 12. Handoff for a new chat

- Phases 1–4 are done locally (phase 4 at 2026-11-09T13:00:34Z). The page draws the board when `schedule_board` is not `0`. Deploy has not happened. Neighbor-building statistics stay deferred. Do not deploy until the operator asks.
- Skin A is active.
- Read this file and the progress file first. Obey the invariants in section 4.
- Do not deploy, commit, or push unless the operator asks.
- At each gate, update both files with a full DateTime, then stop and ask.
- Company KB will not contain this code. Do not stall on it, and do not write house data there.
- UI strings are Ukrainian, as specified above. Code, comments that an agent must maintain, and commit messages are English.
- Known trap: `static/app.js` `updScheduleNow` and the `#pm-sched-content` replace.
- Known trap: do not scan `deye_log` from `GET /api/schedule-board`, from `_build_update_fragments`, or from `save_deye_log`. Copy `deye_aggregates_snapshot`. One sample updates one `schedule_day` row.
- The dashboard key in the operator's browser URL is not documentation. Do not copy it into the repo.
