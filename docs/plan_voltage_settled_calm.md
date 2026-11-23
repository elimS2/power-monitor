# House light from the basement inverter

- Status: `PHASE 2 DEPLOYED`
- Owner: Volodymyr Demyanovich
- Repo: `power-monitor/` (git repo `elimS2/power-monitor`, branch `main`)
- This file replaces the plug-based calm-letter plan and the 2026-11-23T13:18:00Z draft that still described the plug branch as the live path. The one-second Deye read stays in `docs/plan_deye_fast_read.md`. Do not edit that file or its progress companion.
- Related Jira: none. Related KB ids: none. `power-monitor` is not in `kb_repo_memory_catalog` (catalog generated `2026-11-23T13:44:59Z`).
- Last updated: `2026-11-23T18:44:00Z`
- Source proof: composer `195973fe-c59a-43b4-85a5-83484b6497f6`, title `Public basement Deye on the dashboard`, `mutationKind=plan`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-23T13:49:47.015Z`, workspace `4c1fa1b840e12ac3c666c8ec38a21207`.

## 1. Goal and non-goals

### Goal

One decision reads the basement inverter phases. The top lamp and the Telegram letters «Світло зникло» and «Світло з'явилось» both use it.

The spare plug decision is deleted, and so is the `PHASES_ONLY` switch that hides it. A checkout without the server environment must not fall back to plugs. Plug 175 being always powered must not be able to block or start a light letter.

The letter «Напруга стабілізувалась» still waits 30 minutes of real calm. A dark or missing basement reading throws that wait away.

The letter that today says the router is silent is sent when the apartment inverter sample is stale. It is the apartment link. It is not a building outage.

### Non-goals

- Do not change `VOLTAGE_EPISODE_MIN_INTERVAL_SEC` (already `1800`).
- Do not change the battery board, the 98% full rule, or `bat_hour_charge_w`.
- Do not change `DEYE_FAST_INTERVAL_SEC`, `deye_fast`, `_fast_loop`, `read_fast_sample`, or the fast-read plan. Do not call `analyze` from the one-second loop.
- Do not edit the server `.env`. The leftover `PHASES_ONLY=1` line becomes ignored. Do not set `DEYE_FAST_INTERVAL_SEC` to `0`.
- Do not delete old `heartbeats` rows, the `heartbeats` table, `POST`/`GET /api/heartbeat`, or `GET /api/heartbeats`.
- Do not remove the `heartbeats` field from `GET /api/status`.
- Do not add a table or a flag.
- Do not turn ITP commands on.
- Do not deploy in the planning step.

## 2. Context harvest

Repo Memory does not index this repository. Disk is the source of truth. Catalog generated `2026-11-23T13:44:59Z` lists nine code repos and does not list `power-monitor`.

### Repo Memory map

| Path | Why it matters | Touch |
|---|---|---|
| `detection.py` `analyze` lines 195–363 | Live letter path while `PHASES_ONLY` is true. Already reads basement phases via `_grid_id()` / `notify_grid_inverter_id()`. Still returns when fewer than 3 heartbeat rows exist | Yes. Keep this behavior, drop the heartbeat gate |
| `detection.py` `analyze` lines 365–529 | Spare path. `all_dead` needs both plugs at 0 for 18 rows. `latest_alive` is true when plug 175 is up. Sends «Світло зникло» only inside `all_dead` | Delete. Do not leave it behind a flag |
| `config.py` lines 60–69 | `PHASES_ONLY` defaults to `0`. Server `.env` is `1`. `OUTAGE_CONFIRM_COUNT = 18` is the spare-path counter | Delete both names |
| `api/heartbeat.py` lines 10–25 | Only caller of `analyze`. Also sets `stale_alerted` to `0` on every ping | Stop calling `analyze`. Stop clearing `stale_alerted`. Keep storing the ping |
| `power_monitor.py` `lifespan` / `bg_loop` | `watchdog` runs inside the 30-second loop. `analyze` does not. Voltage confirm is 3 calls, and today those calls arrive with the ~10-second ping | Start a 10-second task next to `bg_loop`. Do not slow confirm to 90 seconds |
| `power_monitor.py` `get_display_status` line 829 | Lamp. Reads basement phases, then `power_down` | Call the shared decision |
| `power_monitor.py` `_power_status_text` line 1392 | Duration falls back to `first_heartbeat_ts()` when no event exists | Use the light event only |
| `detection.py` `watchdog` line 532 | «Роутер не відповідає» from heartbeat age | Apartment inverter sample age |
| `itp_auto.py` `load_itp_context` line 302 | Light unknown when the newest heartbeat is older than 300 seconds | Basement sample via `house_grid_now()` |
| `power_monitor.py` dashboard HTML line 2535 and `_build_update_fragments` line 1042 | Section «Роутер / Heartbeats», Plug 204 / Plug 175. `static/app.js` writes `#pm-hb-tbody` | Phase 2 removes the section and the fragment |
| `database.py` section catalog `hb_details` and `config.py` role section list | Same section name | Phase 2 removes the catalog row |
| `api/dashboard.py` `ep_status` | Returns the last 20 heartbeat rows beside phases | Do not touch |
| `docs/plan_deye_fast_read.md` | Another dialog | Do not touch |

### Harvest log (2026-11-23T13:44Z)

| Step | Volume | Mode | Result |
|---|---|---|---|
| A | `knowledge` | semantic | No power-monitor card. Top hit knowledge `#446` is a KB deploy note, not this house. |
| B | `ideas` | semantic | No neighbor of this letter. Idea `#64` is a different Nous plug on another host (`192.168.88.176`). Do not use it as plug 175. |
| C | `code_directories` | semantic | This repo is not indexed. Hits are other products. |
| D | `code_files` | hybrid | No `detection.py` for this repo. `fallback_applied` was empty of this path. |
| E | `code_symbols` | hybrid | `fallback_applied=or_like`. Hits are `analyze_gaps_deterministic` and other products, not `analyze` in this repo. |
| F | `jira` | fts `power-monitor` | Rechecked `2026-11-23T13:49Z`. No ticket for this work. Only unrelated `KB-294` (Done). |
| G | `dialogs` | hybrid | Rechecked `2026-11-23T13:49Z`. Dialog `#707` is the old elevator-battery chat. Not this split. |

Self-check:

- [x] knowledge
- [x] ideas
- [x] code_directories (volume exists; this repo is absent)
- [x] code_files
- [x] code_symbols
- [x] at least three disk paths (`detection.py`, `api/heartbeat.py`, `power_monitor.py`, `config.py`, `itp_auto.py`)
- [x] drill-down of `analyze`, `watchdog`, `get_display_status`, `bg_loop`, `ep_heartbeat`, `load_itp_context`
- [x] jira and dialogs checked

### Live evidence (2026-11-23T13:42Z)

Server `.env` has `PHASES_ONLY=1`. Git default is `0`. With the server value, `analyze` returns at line 363 and never reaches `all_dead`.

`power_events` / `tg_log` versus the row at that timestamp:

| Kyiv time | Event | plug204 | plug175 | Basement L1/L2/L3 |
|---|---|---|---|---|
| 2026-11-23 15:36:34 | `down`, letter «Світло зникло» | 0 | 3 | 0 / 0 / 0 |
| 2026-11-23 07:06:14 | `down` | 0 | 3 | 0 / 0 / 0 |
| 2026-11-23 03:36:55 | `down` | 0 | 3 | 0 / 0 / 0 |

In the 24 hours before that read, heartbeat rows with both plugs at 0: 0. Rows with either plug up: 8637. The letters already follow the basement phases. Plug 175 answering does not hold them back on this server.

The spare path is still dangerous. `PHASES_ONLY` defaults to `0` in `config.py`. A process started without that `.env` line would require both plugs dead before «Світло зникло». Plug 175 is always powered, so that spare path would never send the letter.

## 3. Current system reality

Two decisions exist in one function. Only one of them runs on the server.

The live branch (`PHASES_ONLY` true) uses `has_all_three_phases_voltage` and `has_grid_voltage_now` on `notify_grid_inverter_id()`. `NOTIFY_GRID_SOURCE` is `house`, so that id is the basement inverter. All three phases present and a normal trend can send «Світло з'явилось» when `power_down` is set. All phases absent and no voltage trend sends «Світло зникло» and sets `power_down`. That is what the channel did today.

Before that branch, `analyze` loads `OUTAGE_CONFIRM_COUNT` heartbeats (18) and returns if fewer than 3 rows exist. The only caller is `GET /api/heartbeat`, which the apartment router hits about every 10 seconds. The plugs are not the light sensor anymore, but the ping is still the clock. If those HTTP calls stop, `analyze` is not called, and the 3-row check would also return.

The spare branch starts at `all_dead`. It sends «Світло зникло» only when every one of 18 rows has `plug204 == 0` and `plug175 == 0`. If the newest row has either plug above 0, it takes `latest_alive` and does not start that letter. This branch does not run while the server env stays `1`.

`get_display_status` reads the same basement phases and then `power_down`. The lamp and the channel match today because the live branch writes `power_down` from phases.

`watchdog` sends «Роутер не відповідає» when the newest heartbeat is older than `STALE_THRESHOLD_SEC` (300). Every heartbeat request clears `stale_alerted`, so a leftover ping hides that alert.

`load_itp_context` treats light as unknown when that heartbeat is stale. Unknown light makes the ITP decision hold. ITP commands stay off.

`voltage_normal_since` is cleared on some live-phase branches and not when the grid reading disappears. The review at `2026-11-23T12:44Z` named that hole. This plan keeps the fix.

## 4. Options and skins

Shared core: one function, basement inverter only, no plug values, no `PHASES_ONLY`.

### Skin A — one phase decision, woken every 10 seconds (default)

`house_grid_now(now)` returns `up`, `down`, `voltage`, or `unknown`.

- `unknown`: no sample, or older than 300 seconds. No light letter. Do not set or clear `power_down`. Do not start the calm wait. Lamp text «Немає свіжого заміру підвалу».
- `up`: fresh, all three phases present, trend neither high nor low, and `voltage_anomaly` is unset. Lamp «Світло є». `up` does not call `_maybe_send_recovery`. It sends «Світло з'явилось» only when `power_down` is already set.
- `voltage`: fresh, and the live branch sends a voltage letter. Lamp uses the existing `VOLTAGE_STATUS` text for a live high or low, and that text wins over «Світло ВІДСУТНЄ». A normal trend is not this state.
- `down`: fresh, no live phase, and the live branch sends «Світло зникло». Lamp «Світло ВІДСУТНЄ».

`down` is not “every phase is zero”. Keep the live order in `detection.py` lines 212–362. Do not replace it with “all zeros means the outage letter” or “an open anomaly means no Telegram”.

On a fresh sample, in this order:

1. All three phases, trend high or low, `power_down` unset: voltage letter, return. No «Світло з'явилось». (`detection.py` lines 216–218.)
2. All three phases, trend neither high nor low, `voltage_anomaly` set: this is the only step that keeps the calm mark and calls `_maybe_send_recovery`. It is not `up`. No «Світло з'явилось» on that call. (`detection.py` lines 219–221.) Lamp: «Світло є» when `power_down` is unset, «Світло ВІДСУТНЄ» when it is still set. Do not use `VOLTAGE_STATUS` for this normal trend.
3. All three phases, `power_down` set, and step 2 did not return: «Світло з'явилось» and clear the flag. This includes trend high or low, and a normal trend while the anomaly is unset. If the trend is still high or low, the voltage letter may follow, as the live body does. (`detection.py` lines 222–244.)
4. Anomaly set, mixed phases: return, no light letter. (`detection.py` lines 246–248.)
5. Anomaly set, no live phase, trend not `None`: set `power_down`, no new Telegram line. (`detection.py` lines 257–259.) Lamp: trend `"high"` shows «Висока напруга»; trend `"low"` shows the existing none-status voltage text, the same branch as `power_monitor.py` lines 855–861. `deye_voltage_trend` returns `None` for an all-absent row when `is_scheduled is not False` (`database.py` line 2418), so a scheduled slot takes step 6, not this step.
6. Anomaly set, no live phase, trend `None`: «Світло зникло», set `power_down`, clear `voltage_anomaly`. (`detection.py` lines 260–280.)
7. `power_down` already set, no live phase, and none of the above sent a letter: return. (`detection.py` line 282.) This is still `down`. The lamp stays «Світло ВІДСУТНЄ» on later page loads, including calls that send no new letter.
8. Not alerted yet. All phases absent and trend `"high"`: the «усі фази зникли» letter on the third confirm only (`VOLTAGE_CONFIRM_COUNT` is 3). It does not set `power_down`. (`detection.py` lines 327–343.) All phases absent and trend not `"high"`: «Світло зникло» on that call. (`detection.py` lines 344–362.) Do not delete the confirm counter to make a one-call test pass.

`apartment_link_fresh(now)` is true when the newest apartment `deye_log` row is at most 300 seconds old. `watchdog` sends «Немає зв'язку з інвертором квартири» when it is false, and «Зв'язок з інвертором квартири відновився» when it returns. Not a building outage.

`lifespan` starts one task that calls `analyze` every `GRID_CHECK_SEC` (10). That matches today’s ping cadence, so `VOLTAGE_CONFIRM_COUNT` of 3 stays about 30 seconds. The task does not read plugs. `GET /api/heartbeat` only stores the row. It does not call `analyze` and does not write `stale_alerted`.

`PHASES_ONLY` and `OUTAGE_CONFIRM_COUNT` are deleted from `config.py`. `GRID_CHECK_SEC = 10` is added. It is a period, not a switch.

Why this is the default: the channel already follows the basement phases. The spare branch and the switch are what confused the last reading of the code. A stopped plug ping must not freeze the letters, and the voltage confirm must not stretch to 90 seconds. The one-second loop stays out of this.

Switch: no environment flag. Rollback is checking out the recorded server SHA and restarting.

### Skin B — delete the spare branch, keep the heartbeat request as the only clock

Rejected. `GET /api/heartbeat` would still be the only caller, and its query names would still look like the decision. A stopped router script would stop the letters even after the plug values were ignored. Calling `analyze` only from the 30-second `bg_loop` is also rejected: three voltage confirms would take about 90 seconds instead of about 30.

### Skin C — keep `PHASES_ONLY` and delete only the `else` branch

Rejected. Git default `0` would then run neither branch, so a process without the server `.env` line would send no light letters. The flag would remain a second architecture.

## 5. Recommended architecture

Add `house_grid_now(now)` and `apartment_link_fresh(now)` in `database.py` next to the existing phase helpers. Both take `now` so tests can freeze time. They read `recent_deye_log` for the house id and the apartment id. They do not read `heartbeats`.

`get_display_status` and `analyze` both call `house_grid_now()`. `analyze` is the only writer of `power_down` and of the light letters.

`analyze` does not load heartbeats and does not return when they are missing. The plug branch (lines 365–529) is deleted, not wrapped. The `PHASES_ONLY` condition is deleted. The body that is live today (lines 208–363) stays, including unstable voltage, mixed phases, live high and low, «усі фази зникли», and the quiet `power_down` write when an anomaly was already open. `house_grid_now()` is the gate in front of that body: `unknown` returns before it. Do not replace that body with a shorter `if state == down: send outage` that drops the high-before-blackout letter.

Calm wait:

- Start or keep `voltage_normal_since` only on step 2: anomaly set, all three phases, trend neither high nor low. `up` does not call `_maybe_send_recovery`.
- Every other fresh result clears the mark before any letter is built. That includes the outage letter in step 6, the quiet `power_down` write in step 5, the mixed-phase return, and the confirm holds.
- `unknown` clears the mark and does not remember a start.
- A stored mark older than `last_voltage_problem_ts()` is ignored. The wait starts over.
- `_send_voltage_recovery` returns before any `kv_set` or `save_event("up")` when the mark is missing or not positive. An `up` event closes the outage bar, so it must not be written by a skipped settled letter. `_maybe_send_recovery` returns immediately when the anomaly is unset (`detection.py` lines 109–111), so a test with the anomaly unset must not expect the settled letter.

`watchdog` calls `apartment_link_fresh()`. The heartbeat route must not clear `stale_alerted`, or a ping would cancel the apartment letter.

`load_itp_context` uses `house_grid_now()` only as the freshness gate. `unknown` stays `{"kind": "unknown"}` and the ITP decision holds. A fresh sample still takes `kind` and `since` from the newest `up` or `down` event, because `desired_itp` turns the light off or on only after `_stable` sees `since` (`itp_auto.py` lines 42–48 and 55–58). A phase kind with no `since` would hold forever as `settling`. Do not drop `since`.

Duration text uses the newest light event. If there is no event, omit the «how long» line. Do not call `first_heartbeat_ts()`.

`GET /api/heartbeat` still inserts the row so the router script does not get an error. Nothing in the light decision reads that row.

## 6. Phases

### Phase 1 — delete the spare path, no deploy

Goal: one phase decision. Plugs cannot start, block, or wake a light letter. The calm mark dies when the basement reading is dark or missing.

Touched paths:

- `database.py` — `house_grid_now`, `apartment_link_fresh`
- `detection.py` — `analyze`, `watchdog`, calm helpers
- `config.py` — delete `PHASES_ONLY` and `OUTAGE_CONFIRM_COUNT`; add `GRID_CHECK_SEC = 10`
- `api/heartbeat.py` — store the ping only
- `power_monitor.py` — `get_display_status`, `_power_status_text`, `lifespan` starts the 10-second task
- `itp_auto.py` — `load_itp_context`
- `tests/test_voltage_settled.py` — new
- `tests/test_itp_auto.py` — heartbeat freshness cases become basement-sample cases

Do not edit `tests/test_deye_fast.py` unless a failure there is caused by this phase. Do not edit `_fast_loop`.

Steps:

1. Add the two helpers. A sample older than 300 seconds is `unknown` for the house and not fresh for the apartment. One live phase is not `up`.
2. Delete the heartbeat length check, the `PHASES_ONLY` branch wrapper, and the whole `all_dead` / `latest_alive` block. Do not keep a dead copy.
3. Delete `PHASES_ONLY` and `OUTAGE_CONFIRM_COUNT` and every import of them. `rg PHASES_ONLY` and `rg OUTAGE_CONFIRM_COUNT` in `*.py` return nothing.
4. `unknown` sends neither light letter and does not change `power_down`. On a fresh sample, keep the eight live outcomes in section 4. Do not collapse steps 5 and 6 into “no Telegram”. Do not send «Світло з'явилось» from step 2.
5. Keep the other voltage letters the live branch sends today (live high, live low, mixed, unstable). They are not light on/off letters. Leave `VOLTAGE_CONFIRM_COUNT` at 3.
6. Call `_maybe_send_recovery` only from step 2. Every other fresh result clears `voltage_normal_since` before any letter is built, so the outage letter in step 6 still goes out. That includes the mixed-phase return at lines 246–248, both arms of lines 249–281, and the confirm holds around lines 287–295 and 328–336. The mark is stored only while `voltage_anomaly` is set (`_maybe_send_recovery`). A test that never sets that flag does not prove the clear.
7. In `lifespan`, start a task that awaits `detection.analyze()` every `GRID_CHECK_SEC` (10), then sleeps. On shutdown, cancel that task next to `fast_task.cancel()` and `task.cancel()` (`power_monitor.py` lines 799–801). Do not call it from `bg_loop`’s 30-second pass and do not add a call in `_fast_loop`. Import `house_grid_now` at the top of `detection.py` and patch `detection.house_grid_now` in tests. Patching `database.house_grid_now` after that import does nothing.
8. In `api/heartbeat.py`, keep `save_heartbeat`. Remove `await detection.analyze()` and remove `kv_set("stale_alerted", "0")`.
9. Point `watchdog` at `apartment_link_fresh()`. Texts in the goal section. Do not say the building lost power.
10. Point the freshness check in `load_itp_context` at `house_grid_now()`. `unknown` keeps today's hold. A fresh sample keeps `kind` and `since` from the newest light event.
11. `_power_status_text` uses the newest light event only.
12. `get_display_status` calls `house_grid_now`. `unknown` returns «Немає свіжого заміру підвалу» for a missing row and for a sample older than 300 seconds, including a row that still holds 230 V. The fragment title (`power_monitor.py` line 1306) uses that same status text. It does not keep a second sentence based only on `power_down`.

Tests use a temporary SQLite file. They must not open Telegram or port 8899. Patch `power_monitor.update_chat_photo` and `power_monitor.tg_send`. Patch names on `detection` that were bound at import (`has_grid_voltage_now` and the other phase helpers, if the test replaces them). Insert basement and apartment `deye_log` rows. Light tests do not insert heartbeats.

Negative cases:

- Basement phases all 0, age 10 seconds, trend not `"high"`, `power_down` unset, anomaly unset, no heartbeat rows: one «Світло зникло».
- Same rows, `deye_voltage_trend` returns `"high"`, anomaly unset: the first two calls send nothing and leave `power_down` unset; the third sends «усі фази зникли» and still leaves `power_down` unset. No «Світло зникло».
- Anomaly `"1"`, fresh all-zero, trend not `None`: `power_down` becomes `"1"`, and the stub receives no new light text.
- Anomaly `"1"`, fresh all-zero, trend `None`: one «Світло зникло».
- `power_down` `"1"`, anomaly unset, three fresh phases, trend `"high"`: one «Світло з'явилось».
- `power_down` `"1"`, anomaly `"1"`, three fresh phases, trend neither high nor low, mark younger than 1800 seconds: no «Світло з'явилось».
- Phases 230/230/230, age 301 seconds, `power_down` already `"1"`: no light letter, `power_down` unchanged, lamp text «Немає свіжого заміру підвалу».
- No basement row, and a basement row of age 301 seconds: `get_display_status` returns «Немає свіжого заміру підвалу». The fragment title uses that same text.
- Same all-zero rows, basement age 301 seconds, `power_down` unset: no light letter, `power_down` unchanged.
- Apartment age 301 seconds, basement fresh `up`: apartment-link letter, no light letter.
- Heartbeat rows with plug175 at 3 and plug204 at 0, basement fresh and all phases 0: still one «Світло зникло». The plug row does not block it.
- Second `analyze` while `power_down` is already `1` and the basement is still `down`: no second light letter.
- Anomaly `"1"`, mark 600 seconds old, then a fresh all-zero reading: the mark is empty both when the trend is `"high"` and when it is `None`. The `None` case still sends one «Світло зникло». The `"high"` trend case sends no outage letter.
- Mark older than `last_voltage_problem_ts()`: the first calm call stores a new start and does not send.
- Fresh `up`, mark 1800 seconds old: no settled letter, because `up` has the anomaly unset and `_maybe_send_recovery` returns before sending.
- Anomaly `"1"`, three fresh phases, trend neither high nor low, mark 1800 seconds old and after the problem event: settled letter once. Lamp «Світло є» if `power_down` is unset.
- `unknown` (no basement row): mark cleared, `power_down` unchanged, no light letter.

Human gate: stop. Say the spare branch and the switch are gone, the site was not restarted, and the fast-read loop was not edited. Ask before Phase 2.

Rollback: revert the Python files. Old heartbeats are untouched.

This phase is code-only. No commit unless the operator asks.

### Phase 2 — page table, then deploy

Goal: the dashboard no longer shows Plug 204 and Plug 175. The server runs Phase 1.

Touched paths: the `hb_details` block in `dashboard` and in `_build_update_fragments`, the `pm_hb_tbody` and `pm_mk` fragment keys, the `#pm-hb-tbody` and `#pm-mk-wrap` writes in `static/app.js` (the wrap is filled from `app.js` around line 1391), the `hb_details` catalog rows in `database.py` and `config.py`, plus the Phase 1 files.

Steps:

1. Remove the section, the fragment HTML, and the catalog row. If `app.js` still assigns `#pm-hb-tbody`, that assignment must no-op because the element is gone. Do not drop the `heartbeats` table.
2. Commit Phase 1 and Phase 2 together, in English, with no `#autodeploy` and no `#автооновити`. Push only if the yes includes push.
3. On the server, record `git rev-parse HEAD` before pull. Then `git pull --ff-only` and restart `power-monitor`. Rollback is checkout of that recorded SHA and restart, not a reverse pull. Do not edit the server environment.
4. Confirm the service is active, the lamp matches a fresh basement reading, and the plug table is gone. A leftover `PHASES_ONLY=1` in `.env` must not matter: the process no longer reads that name.

Human gate: report the server SHA before and after. Do not claim a live light letter was sent unless one was.

## 7. Data and compatibility

No migration. Old `heartbeats` rows stay. `power_down` already in `kv` stays. The first fresh basement `down` after deploy can send «Світло зникло» if the flag is still `0`. The first fresh `up` can send «Світло з'явилось» if the flag is still `1`. That is the same edge the live phase branch has today.

The router may keep calling `/api/heartbeat`. Those rows are history. They do not change `power_down`.

Server `.env` is not edited. After deploy the `PHASES_ONLY` line is unused. `DEYE_FAST_INTERVAL_SEC=1` stays as the other dialog set it.

## 8. Verification and definition of done

Done when:

- The negative cases in Phase 1 pass.
- `python -m unittest tests.test_voltage_settled tests.test_itp_auto tests.test_voltage_chart.BatteryBoardTests tests.test_voltage_chart.OutdoorSampleTests` passes.
- `rg PHASES_ONLY` and `rg OUTAGE_CONFIRM_COUNT` find no Python matches.
- `rg "detection.analyze"` finds the call in the 10-second lifespan task only.
- After the deploy yes, the server SHA matches the pushed commit and the plug table is gone.
- This work did not change the fast-read plan, `_fast_loop`, or `DEYE_FAST_INTERVAL_SEC`.

## 9. Risks, questions, decisions

### Risks

- A basement sample that freezes at the last voltages would keep the old light. The 300-second age check stops that. Tests must use an old timestamp, not only an empty table.
- The apartment letter and the building light letter can both be true. The texts must not use the same sentence.
- Calling `analyze` from both the 10-second task and the heartbeat route would double-count voltage confirm steps. Phase 1 leaves only the 10-second task.
- `VOLTAGE_CONFIRM_COUNT` is 3 calls. At the old ~10-second ping that is about 30 seconds. A 30-second loop would make it about 90 seconds. `GRID_CHECK_SEC` stays 10 so that wait does not change. Do not hook the one-second loop to go faster.
- `GET /api/status` returned plug rows until `2026-11-23T18:44:00Z`. The operator asked to remove that field so it would not look like an unfinished light sensor. `GET /api/heartbeat` still stores the router ping.

### Open questions

None. Building light is the basement inverter. The apartment letter is the apartment inverter link. The spare plug branch and `PHASES_ONLY` are deleted.

### Decision log

- `2026-11-23T12:49:56Z` — First plan was only the calm letter, and its tests still drove plug heartbeats. Superseded.
- `2026-11-23T13:08:00Z` — Plug-based plan `APPROVE`, 0 CRITICAL, 0 HIGH. Superseded. The operator said the plugs are not the light source.
- `2026-11-23T13:17:05Z` — Building light is the basement phases. Lamp and letters share that decision. A stale sample is `unknown`. The old router letter is the apartment link. Superseded in part by the next entry: that draft said the live path was `PHASES_ONLY=0` and that flipping the flag to `1` was not the change. The live server already had the flag at `1`.
- `2026-11-23T13:18:00Z` — Self-review of that draft. One live phase is not `up`. This rule stays.
- `2026-11-23T13:44:21Z` — Log check. Today's down letters went out while plug 175 answered 3/3 and basement phases were 0/0/0. `PHASES_ONLY=1` on the server, so the spare branch did not send them. The operator asked to remove that spare path so it stops confusing the next reading. Decision: delete the plug branch and delete `PHASES_ONLY` and `OUTAGE_CONFIRM_COUNT`. The heartbeat route only stores rows. Skin B and Skin C are rejected. Do not edit server `.env`.
- `2026-11-23T13:52:00Z` — Lead review. The 30-second wake is rejected because it stretches `VOLTAGE_CONFIRM_COUNT`. Wake is `GRID_CHECK_SEC` 10. Review source proof `verifiedAtUtc=2026-11-23T13:49:47.015Z`.
- `2026-11-23T14:20:00Z` — Critic round 1 accepted in full. The eight live letter outcomes replace the short `up`/`down` sentences. Confirmation review not run yet.
- `2026-11-23T14:35:00Z` — Critic round 2, same model `grok-4.7-xhigh-fast`, same agent `1e0a5846-8242-4f7c-8883-b81a5f4fd6b6`, `CHANGES REQUIRED`, CRITICAL 0, HIGH 1, MEDIUM 2, LOW 0. All accepted. The calm mark stays only on step 2, where the anomaly is set. `up` does not call `_maybe_send_recovery`. Step 2 lamp is «Світло є» or «Світло ВІДСУТНЄ», not the voltage-problem sentence. Step 5 lamp is the high-voltage text when the trend is high. Step 7 with no live phase stays «Світло ВІДСУТНЄ». The progress skin line no longer says every all-zero high trend is an outage-free voltage letter. Status stayed `REVIEW IN PROGRESS` until round 3. No code.
- `2026-11-23T14:45:00Z` — Critic round 3, same model, same agent, verdict `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. Local work starts only after an explicit yes. No code.
- `2026-11-23T15:45:53Z` — Phase 1 implemented locally after an explicit yes. Spare plug branch, `PHASES_ONLY`, and `OUTAGE_CONFIRM_COUNT` are gone. `analyze` runs from `_grid_check_loop` every `GRID_CHECK_SEC` (10). Heartbeat route only stores the row. Site was not restarted. `_fast_loop` was not edited. 99 tests passed: `tests.test_voltage_settled`, `tests.test_itp_auto`, `tests.test_voltage_chart.BatteryBoardTests`, `tests.test_voltage_chart.OutdoorSampleTests`. Awaiting a yes before Phase 2.
- `2026-11-23T16:58:30Z` — Operator yes for Phase 2 via Agree & Continue (prompt 2). Knowledge, ideas, code directories, code files, and code symbols were searched. `power-monitor` is still absent from Repo Memory. Idea `#64` is a different Nous plug on `192.168.88.176` and was not used. The dashboard section `hb_details`, the fragment keys `pm_hb_tbody` and `pm_mk`, and the catalog rows in `database.py` and `config.py` are removed. `static/app.js` still assigns those ids only when the element exists, so a missing node is a no-op. The `heartbeats` table and `GET /api/status` field stay. 100 tests passed, the same set plus `test_fragments_do_not_include_the_plug_table`. No `#autodeploy`. Deploy is the next step of this phase, not done in this note.
- `2026-11-23T16:59:43Z` — Pushed `9041629` to `origin/main` (`0396c0b..9041629`). No `#autodeploy`. SSH `elims2@35.246.222.183` returned `Permission denied (publickey)`. `gcloud compute instances list` has no visible VM (permission denied on project `lexora-kb`). Server SHA before pull was not read. Service was not restarted. `.env` was not edited. Deploy remains open.
- `2026-11-23T17:06:27Z` — Deployed with the key file `elims2_instance-2_private.priv`, flags `BatchMode`, `IdentitiesOnly`, and an explicit `-i`. Bare SSH and `gcloud` on project `lexora-kb` are the wrong door. Server was `cef1f6d2fcbfe7ecd783b812e848d5b9ef8ad302`. `git pull --ff-only` moved `cef1f6d..1964065`. Restart at `2026-11-23T17:06:27Z`. Service `active`. Local page has no `Plug 204`, no `hb_details`, no `pm-hb-tbody`. Lamp text «Світло ВІДСУТНЄ», matching the 15:36 Kyiv letter. No new light letter at restart. `.env` not edited. Rollback is checkout of `cef1f6d2fcbfe7ecd783b812e848d5b9ef8ad302` and restart. Three older doc-only commits (`e6afca4`, `c5ee725`, `0396c0b`) rode along because the server was behind; they do not change the light decision.

## 10. Progress log

- `2026-11-22T16:58:00Z` — Calm letter deployed as `28a93a1`. The mark still survives a blackout.
- `2026-11-23T12:44:00Z` — Implementation review `NO-GO`, 1 HIGH: a blackout did not clear `voltage_normal_since`.
- `2026-11-23T13:08:00Z` — Plug-based plan approved. Superseded the same hour.
- `2026-11-23T13:10Z` — Live heartbeats: plug 204 silent, plug 175 answering 3/3.
- `2026-11-23T13:18:00Z` — Draft said the plug path was live. That sentence was wrong.
- `2026-11-23T13:42Z` — Server `PHASES_ONLY=1`. Three down letters today matched basement phases while plug 175 was up. No both-dead heartbeat in the last day.
- `2026-11-23T13:50:00Z` — Plan rewritten. Spare path and the switch are in Phase 1 to delete. First draft woke `analyze` from the 30-second loop. Superseded the same hour.
- `2026-11-23T13:52:00Z` — Lead review before the critic. Two defects fixed in this file. All phases at zero is not automatically «Світло зникло»: trend `"high"` stays the «усі фази зникли» letter and does not set `power_down`. The clock is a 10-second task. The sentence “an open anomaly that goes dark sends no line” was too wide. Superseded by the critic round below.
- `2026-11-23T14:20:00Z` — Critic round 1, model `grok-4.7-xhigh-fast`, agent `1e0a5846-8242-4f7c-8883-b81a5f4fd6b6`, verdict `CHANGES REQUIRED`, CRITICAL 0, HIGH 2, MEDIUM 3, LOW 2. All accepted. Section 4 now lists the eight live outcomes, including «Світло зникло» when an open anomaly meets trend `None`, and «Світло з'явилось» when power is down and the trend is still high or low. The calm clear covers lines 246–281, and the test sets `voltage_anomaly`. A 301-second row of 230 V is `unknown`. The high-before-blackout letter is the third confirm. The lamp and the tab title share one sentence. Phase 2 also drops `pm_mk` / `#pm-mk-wrap`. The 10-second task is cancelled in `lifespan`. Status stays `REVIEW IN PROGRESS` until the confirmation review. No code.
- `2026-11-23T15:45:53Z` — Phase 1 local. Spare path and the switch are gone. Site not restarted. Fast-read loop not edited.
- `2026-11-23T16:58:30Z` — Phase 2 page change is local. Plug table is gone from the dashboard and from the section catalog.
- `2026-11-23T17:06:27Z` — Deployed. Server moved `cef1f6d` to `1964065` and restarted. Service active. Plug table gone. Lamp «Світло ВІДСУТНЄ». No new light letter. `.env` not edited in that step.
- `2026-11-23T18:44:00Z` — Operator asked to remove the three leftovers that would look like unfinished work. `GET /api/status` no longer returns `heartbeats`. The dead `#pm-hb-tbody` and `#pm-mk-wrap` assignments are deleted. The unused `PHASES_ONLY` line was removed from the server `.env` after `35ec406` restarted; a read of that file no longer contains the name. `GET /api/heartbeat` still stores the router ping so that script does not start receiving errors. Live status keys: `deye`, `events`, `power_down`, `voltage_anomaly`.

## 11. Handoff

Phase 2 is on the server as `1964065`, restarted `2026-11-23T17:06:27Z`. Rollback SHA is `cef1f6d2fcbfe7ecd783b812e848d5b9ef8ad302`. Use the key file named in the local canvas `power-monitor-deploy.canvas.tsx`, with `IdentitiesOnly` and `-i`. Do not edit the server `.env`. Do not add `#autodeploy`.

Do not touch `docs/plan_deye_fast_read.md`, `docs/plan_deye_fast_read_PROGRESS.md`, `deye_fast`, `DEYE_FAST_INTERVAL_SEC`, `_fast_loop`, `read_fast_sample`, the battery board, or `VOLTAGE_EPISODE_MIN_INTERVAL_SEC`.

Do not edit the server `.env`.

If the Knowledge Base MCP is down, stop.

Read this file and `docs/plan_voltage_settled_calm_PROGRESS.md` before editing. After the phase, update both with a DateTime and stop for a human yes.

## 12. Self-review

### Round 1 of this rewrite (`2026-11-23T13:50:00Z`)

Checked before handoff. Findings fixed in this file:

- Deleting only the `else` branch and leaving `if PHASES_ONLY` would make git default `0` send no letters. The plan deletes the flag and always runs the phase decision.
- Leaving `analyze` only on `/api/heartbeat` would keep the ping as the clock. The plan moves the call to a 10-second lifespan task and removes the route’s `analyze` call and its `stale_alerted` clear. A 30-second `bg_loop` call was rejected in the lead review because it stretches voltage confirm.
- A second call from `_fast_loop` is forbidden in non-goals and in the phase steps.
- `OUTAGE_CONFIRM_COUNT` is deleted with the flag so the number 18 does not look like a remaining plug rule.
- The page has two plug-table builders (`dashboard` and `_build_update_fragments`) plus `app.js`. Phase 2 names all three.
- `GET /api/status` still returns heartbeats. That is an explicit non-goal, not a forgotten consumer.
- One live phase is not `up`. Carried forward from `2026-11-23T13:18:00Z`.

No CRITICAL or HIGH left after critic round 3. Status is `REVIEWED / READY FOR LOCAL WORK`. That is not a yes to start Phase 1.
