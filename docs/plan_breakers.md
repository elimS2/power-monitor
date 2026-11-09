# Basement breakers

- Status: `PHASE 1 DONE`
- Owner: Volodymyr
- Repo: `power-monitor` (public GitHub `elimS2/power-monitor`, live `https://power.elims.pp.ua`)
- Related Jira: none. This repo is not in the company knowledge base. Do not search it and do not write there.
- Last updated: 2026-11-09T20:37:30Z
- Active skin: **Skin A** (15-minute status sample + stored day row + switch messages)
- This file is the implementation contract. A new chat must not need the planning conversation.

Companion: `power-monitor/docs/plan_breakers_PROGRESS.md`

## 1. Goal and non-goals

### Goal

On the existing dashboard, for the two basement breakers labeled **Світло** and **ІТП**:

- Show the latest switch, the three phase voltages, the three phase currents, the three phase powers, and today's energy in kWh.
- Draw one day, Kyiv time, as a bar: green `#22c55e` while the breaker was on, red `#f87171` while it was off. Same colors as the schedule fact lane.
- Record when the switch turned on or off, tight to the device message, not to the poll.
- Keep a 15-minute sample of the meter and the phases so a missed message is corrected and the energy total still moves.

The page reads stored rows. It does not call Tuya.

### Non-goals

- Turning a breaker on or off from the dashboard. The one-shot **Світло** off at 22:30 on 2026-11-09 is already stored in Tuya. This work only observes it.
- Polling faster than 15 minutes. The trial pack is the limit. See section 6.4.
- A chart library, a second database, a second process.
- Scanning `breaker_sample` inside an HTTP handler.
- Backfilling days from before the first sample after deploy.
- Copying Tuya secrets, device ids, or house notes into git or into the company knowledge base.
- Deploy, commit, or `#автооновити` unless the operator asks in a later chat.
- The schedule board, Deye polling, Telegram outage text, or the boiler parser.

## 2. How this plan was adapted

Prompt library card **#6 Create Plan** is the working method. Applied here:

- Living plan + progress file, English, phases, skins, human gate between phases, self-review, no code in the planning turn.
- Disk is the source of truth. Company KB was not queried: the operator said this repo is not connected to it, and house facts must not be written there.
- This workspace has no living-plan mutation-proof rule. None was required.
- No Jira ticket exists for this repo. Do not create one as part of implementation.

## 3. Context harvest

Company KB: not searched. Skipped on purpose on 2026-11-09T19:55:00Z.

Self-check:

- [x] knowledge — skipped on purpose
- [x] ideas — skipped on purpose
- [x] code_directories — skipped on purpose
- [x] code_files — skipped on purpose
- [x] code_symbols — skipped on purpose
- [x] jira — skipped on purpose
- [x] at least three real code paths from disk (below)
- [x] drill-down of the poll loop, `deye_log`, and the dashboard section
- [ ] dialogs — skipped on purpose

### What was already proven outside this repo

On 2026-11-09, against the EU cloud project, one `GET /v1.0/devices/{id}/status` returned the switch, `total_forward_energy`, and `phase_a` / `phase_b` / `phase_c` together. A second call is not required for volts or amps. The statistics routes (`/statistics/hours`, `/all-statistic-type`) answered `28841101` (not subscribed). Do not subscribe to them for this feature.

`total_forward_energy` is an integer with `scale` 2 and unit `kW·h` (`GET /v1.0/devices/{id}/specifications`). Divide by 100. The meter steps by 0.1 kWh.

Device Status Notification is already authorized on the project, next to IoT Core. Device Timer was authorized the same day so the one-shot 22:30 task could be created. The listener in this process does not exist yet.

### Repo map

| Path | Why it matters | Touch? |
|---|---|---|
| `power_monitor.py` `bg_loop` (~430) | 30-second tick. Deye poll is `DEYE_POLL_INTERVAL_SEC` (default 30) counted in those ticks. | Add a 15-minute breaker tick. Do not change the Deye tick. |
| `config.py` `DEYE_POLL_INTERVAL_SEC` | Pattern for an env interval. | Add breaker env names. No secret defaults. |
| `database.py` `init_db`, `deye_log` (~157), `save_deye_log` (~1103) | `CREATE TABLE IF NOT EXISTS` plus `ALTER` in `try/except`. A sample insert updates a projection from that one sample. | New tables and one save function in the same style. |
| `database.py` `deye_aggregates_snapshot` / `deye_aggregates_refresh` | The 10s fragment must not scan a month of rows. | Copy the split. The breaker GET reads one stored day row. |
| `power_monitor.py` Deye section (~1699) | A dashboard `<details>` block with a summary line and a table. | New sibling section. Do not edit the Deye markup except to leave it alone. |
| `static/app.js` `pm_section_order` (~97), fragment poll 10s | Section order is local. The schedule board stays outside the 10s replace. | Breaker bar stays outside `#pm-breakers-live`. |
| `api/dashboard.py` `/api/dashboard-fragments` | Key check, then JSON. | New read route uses the same key check. |
| `docs/DEPLOY.md` | Pull and restart. Schema runs in `init_db()` at startup. | No new migrate command. |

## 4. Current behavior

There is no breaker table, no Tuya client, and no breaker section. The live site shows Deye from `deye_log`, written about every 30 seconds by `_poll_deye` inside `bg_loop`.

The cloud already has both breakers as read-only devices. One status call per id returns the fields in section 6.3. Switch changes are not stored here. The 22:30 off, when it happens, will be visible to the next poll or to a message, whichever lands first. This plan does not send `switch`.

## 5. Skins

### Skin A — 15-minute sample plus messages (default)

Every 15 minutes, two status calls (one per breaker) insert a sample and update that breaker's day row. A Device Status Notification message for one of these two ids inserts a sample immediately and, when `switch` flipped, closes and opens a span. The bar and the "today kWh" line read the day row. The latest volts and amps read the latest sample columns on that same row.

### Skin B — poll only

No message listener. The bar moves only on the 15-minute sample. Rejected as the default because the operator asked for the on/off edge to arrive with the message, and for the poll to be the meter check.

### Skin C — poll the switch every minute

Rejected. Two status calls a minute is about 86 000 calls in 30 days. The published trial allowance is about 26 000 API calls a month, and the project screen shows a **0.2 USD** monthly pack. Past that, the trial stops until next month. It is not billed extra. Five calls a second is the documented per-project cap on the v2 status route and is not the binding limit.

## 6. Recommended shape

One SQLite file. One poller in `bg_loop`. One message listener in the same process. One read route. One new dashboard section. No new service.

### 6.1 Tables

Follow `init_db`: `CREATE TABLE IF NOT EXISTS`, then `ALTER` inside `try/except sqlite3.OperationalError`.

`breaker_sample` — append-only history. Not read by the page.

| Column | Meaning |
|---|---|
| `id` | Integer primary key |
| `ts` | Unix seconds, UTC |
| `device` | `svitlo` or `itp` |
| `switch` | 1 on, 0 off |
| `energy_raw` | Integer `total_forward_energy` |
| `energy_kwh` | `energy_raw / 100` |
| `v_a` `i_a` `p_a` | Phase A volts, amps, watts. Null if the blob does not decode |
| `v_b` `i_b` `p_b` | Phase B |
| `v_c` `i_c` `p_c` | Phase C |
| `fault` | Integer bitfield, 0 means none |
| `source` | `poll` or `message` |

Index `(device, ts)`.

`breaker_message` — one row per accepted message id. GET and the 10-second fragment do not read it.

| Column | Meaning |
|---|---|
| `message_id` | Primary key. The id from the transport |
| `device` | `svitlo` or `itp` |
| `ts` | Event time from the message, unix seconds |

`breaker_day` — one row per device per Kyiv date. This is what GET reads.

| Column | Meaning |
|---|---|
| `device`, `day` | Primary key. `day` is `YYYY-MM-DD` in Europe/Kyiv |
| `energy_base_kwh` | Last counter at or before local midnight. Null until a sample exists before that midnight |
| `energy_kwh` | Latest counter |
| `energy_today_kwh` | `energy_kwh - energy_base_kwh`, or null when the base is null |
| `switch` | Latest switch |
| `span_json` | JSON list of `{start, end, switch}` for that local day. `end` null means still open |
| `phase_json` | Latest decoded phases and `fault` |
| `updated_at` | Unix seconds |

Do not rebuild `span_json` or `energy_today_kwh` inside GET. The writer that just inserted the sample updates this one row, in the same transaction. See 6.6.

### 6.2 Phase blob

`phase_a`, `phase_b`, `phase_c` are base64. After decode, 8 or 10 bytes, big-endian:

| Bytes | Field |
|---|---|
| 0–1 | volts × 10 |
| 2–4 | amps × 1000 |
| 5–7 | watts |

A 10-byte blob has two extra bytes. Ignore them. A blob that is not 8 or 10 bytes leaves that phase null and still stores switch and energy.

Confirmed on 2026-11-09 against a live **Світло** sample: `09 24` → 234.0 V, then current and watts in the same blob. Do not invent a second scale.

### 6.3 Poll

- Host: `https://openapi.tuyaeu.com`
- Token: `GET /v1.0/token?grant_type=1`. Cache it until shortly before `expire_time`. A poll that already holds a token does not spend a second call on a token.
- Status: `GET /v1.0/devices/{id}/status` once per breaker.
- Ids and the access secret come from the server environment: `TUYA_ACCESS_ID`, `TUYA_ACCESS_SECRET`, `TUYA_BREAKER_SVITLO`, `TUYA_BREAKER_ITP`. `TUYA_POLL_INTERVAL_SEC` defaults to `900`. Empty id disables that breaker. Empty secret disables the poller. Never log the secret or the token.
- Sign with HMAC-SHA256 as in the current Tuya cloud docs (method, body hash, empty headers line, path). Sort query parameters.
- On HTTP or Tuya error: log the code that came back, keep the previous day row, try again next interval. Do not retry in a tight loop. The token GET and each status GET use a 10 second timeout. They sit in their own try, after the Deye tick, and they do not hold `_breaker_lock`. A timeout or error must not skip `_poll_deye`, the schedule fetch, or the alert fetch, and must not retry before the next breaker interval. `apply_breaker_status` stays synchronous. A 10 second wait may delay the rest of that tick. It must not cancel it.
- The live status body on 2026-11-09 was `{"success": true, "result": [ {"code", "value"}, ... ]}`. `switch` is a boolean. `total_forward_energy` is an integer. `fault` is an integer. `phase_a`, `phase_b`, and `phase_c` are base64 strings. Other codes may be present. Ignore unknown codes. Do not store `breaker_number`. The test fixture is this shape with a synthetic phase blob, not a reconstructed guess and not a live blob from the house.
- Do not call `/statistics/*`. Those routes are not subscribed.
- Do not POST commands. `switch` is only read.

### 6.4 Quota

Published trial pack, [pricing](https://developer.tuya.com/en/docs/iot/membership-service?id=K9m8k45jwvg9j), updated 2026-07-28: about 26 000 API calls and 68 000 messages a month. The trial does not bill past that. The service pauses until the next month. The project screen shows the same pack as **0.2 USD / month**.

Two status calls every 15 minutes for 30 days is about 5 800 calls, plus a token refresh a few times a day. That fits. Every minute does not (about 86 000).

The per-project cap on `GET /v2.0/cloud/thing/{device_id}/state` is 5 per second ([frequency](https://developer.tuya.com/en/docs/iot/frequency-control?id=Kcojz2r2dg1f6)). The monthly pack runs out first.

Status messages for these two ids only. Ignore every other device on the queue. One energy step of 0.1 kWh at about 1.4 kW is roughly four minutes. That pace is inferred from the step, not from a counted stream. Phase 4 records the real message interval before the listener is left on. If that rate would pass 68 000 in a month, do not enable the listener; the 15-minute poll remains the only writer.

### 6.5 Messages

Device Status Notification is already authorized. Before writing a client, read the project's Message Service screen and record which transport it offers.

- If it can POST to our host, add `POST /api/tuya-webhook`. If `TUYA_WEBHOOK_SECRET` is empty, return 503 and write nothing. A missing or wrong secret header returns 403 and writes nothing. An empty header must not match an empty secret. Do not accept the dashboard key as a substitute. Prefer this. No new native library. The pattern is `api/deploy.py` (empty secret is 503), not `api/telegram.py` (empty secret matches an empty header).
- If it is only the Tuya Pulsar endpoint, run that consumer in-process and filter to the two ids.

A message that carries `switch` or `total_forward_energy` or a phase blob is one sample with `source=message`, then the same day-row update as a poll, unless the next paragraph says the event is a duplicate or older than the latest sample. A message with no new switch and no new counter still refreshes `phase_json` and `updated_at`, unless it is a duplicate or older than the latest sample.

Persist every accepted message id in `breaker_message`. Ignore an id that is already stored, including after restart. A transport cursor, if one is required, does not replace that set. Use the event time inside the message as `ts`. If that `ts` is older than the latest stored sample `ts` for that device, record the message id and do not insert a sample and do not change `breaker_day`.

### 6.6 Spans, midnight, and the one writer

`database._conn()` opens a new SQLite connection. The only lock in that file today is `_deye_agg_lock`, and it covers Deye aggregates only. The 15-minute poll and a switch message can call the writer at the same time. `apply_breaker_status` is the only writer of `breaker_sample`, `breaker_day`, and `breaker_message`. It holds one `threading.Lock` (`_breaker_lock`) and uses one connection and one transaction:

1. Insert the sample only when a payload is passed. The no-sample entry inserts nothing. A payload is not inserted when its message id is already in `breaker_message`, or when its event `ts` is older than the latest `breaker_sample.ts` for that device. A duplicate id or an older ts stops before steps 2–5. A duplicate writes nothing new. Only the older-ts reject writes `breaker_message` on that stop path. An accepted message still writes its id, then continues. A poll has no message id and never writes that table.
2. Take the Kyiv calendar day and that day's midnight from the sample timestamp, or from the clock when there is no sample. Compute both with `config.UA_TZ` through `kyiv_date_str` and `kyiv_day_bounds` in `schedule_board.py`. Do not use a fixed UTC+2, a fixed 86400, or `Europe/Kiev`. Do not trust a day string that `bg_loop` computed on an earlier tick.
3. If the latest `breaker_day` row before this Kyiv date still has an open span, close that span at that row's own Kyiv midnight. Do not create rows for the skipped dates. Do not extend that span to now.
4. Update today's `breaker_day` row: base, lifetime energy, today, switch, phases, spans. Skip this step on a no-sample call when yesterday's row does not exist.
5. Commit once.

On that day row, after the midnight close:

1. If there is no open span, open one at this `ts` with this switch. A no-sample call opens today's span at midnight only when yesterday's row exists, using yesterday's switch. If yesterday's row does not exist, do not create today's row and do not open a span.
2. If the switch equals the open span, leave the span. Still update energy and phases when a payload was passed.
3. If the switch differs, set the open span's `end` to this `ts` and open a new one.

`bg_loop`, and also process start, may call the same locked function with no payload when the Kyiv date changes. That path does not insert a `breaker_sample` row. For each device, under the same lock and the same transaction: if an older row still has an open span, close it at that row's own Kyiv midnight. If yesterday's row exists and today has no span, open one at yesterday's midnight with yesterday's switch, copy yesterday's `energy_kwh` into today's `energy_kwh` and `energy_base_kwh`, and set `energy_today_kwh` to 0. If yesterday's row does not exist, do not create today's row. If today already has a span, do not add another. It reads `breaker_day`, not `breaker_sample`. A sample that arrives just after midnight does not wait for this pass. There is no second close path in `bg_loop`.

`energy_base_kwh` is copied only from the row whose `day` is this Kyiv date minus one calendar day. If that exact date has no row, `energy_base_kwh` and `energy_today_kwh` stay null. Do not subtract from an older row. If today's base is already set, keep it. The base can be up to 15 minutes before midnight on poll-only gaps, or about one meter step (0.1 kWh) when messages are flowing. Say that on the card in one short line. Do not pretend the total starts at 00:00:00 exactly.

No backfill before the first sample. A day with no row is an empty state, not a green bar.

### 6.7 Read route

`GET /api/breakers?day=YYYY-MM-DD`. `check_permission(key, "dashboard")`, the same check as `GET /api/schedule-board` in `api/dashboard.py`. Do not add a new permission name.

Omitted `day` is today in `UA_TZ`. A bad `day` is 400. The board fetch sends the same `key` query as `/api/schedule-board`.

Returns, for `svitlo` and `itp`, the stored day row. If `span_json` has a null `end` and `day` is today, the response fills that end with the clock. A null `end` on a day that is not today is not filled with now. It does not write. Missing row: `{ready: false}` for that device.

The handler does not import the Tuya client and does not query `breaker_sample`.

### 6.8 Page

New section id `breaker_details`, Ukrainian title **Автомати підвалу**. In the HTML it sits after the Deye block. `ALL_SECTIONS` and `SECTION_LABELS` in `database.py` must include it. `_wrap_dashboard_section` (`power_monitor.py`) returns an empty string when the id is missing from a role's stored list. `init_db` already appends `collections_details` to every explicit role list and to `api_key_config` rows that keep their own list (`database.py` around the `_append_collections` helper). Phase 3 does the same for `breaker_details`, including the built-in lists "Без Deye" and "Базове". The built-in role "Усі" stores NULL and already means every section. Adding the id only to `ALL_SECTIONS` would hide the block for every key whose role was saved earlier.

`pm_section_order` may move it. When a saved order does not contain the new id, `static/app.js` appends that section at the end of the list (the loop that appends unknown ids). That is the existing behaviour. Do not special-case an insert after Deye. The operator can drag it. Drag handle stays. `DASHBOARD_SECTION_ORDER` in `config.py` is unused. Do not treat it as the allow-list.

The 10-second fragment key `pm_breakers` replaces only `#pm-breakers-live`. Those two lines read today's `breaker_day` rows (one per device), not `breaker_sample`. `#pm-breakers-board` is a sibling outside that node. `static/app.js` replaces `pm_deye` into `#pm-deye` wholesale; do not put either breaker node inside that string, or the date control is destroyed on the next 10-second tick. The schedule split is the pattern: `pm_sched` goes into `#pm-sched-content`, and `#pm-sched-board` stays outside.

Inside `#pm-breakers-live`: two lines, one per breaker.

- Name, **увімкнено** or **вимкнено**, today's kWh, age of the sample. When `energy_today_kwh` is null, show `немає бази` and do not print `energy_kwh`.
- Three phases: volts and amps. Watts in the same line, smaller.
- Fault, only when non-zero, as the integer. The specification lists these labels in order: `short_circuit_alarm`, `surge_alarm`, `overload_alarm`, `leakagecurr_alarm`, `temp_dif_fault`, `fire_alarm`, `high_power_alarm`, `self_test_alarm`, `ov_cr`, `unbalance_alarm`, `ov_vol`, `undervoltage_alarm`, `miss_phase_alarm`, `outage_alarm`, `magnetism_alarm`, `credit_alarm`, `no_balance_alarm`, `temp_alarm`, `temp_cut_off`. Do not render those names. The live fault value was 0, so bit order is not confirmed. Zero shows nothing.

Outside the fragment, `#pm-breakers-board`:

- Date control, default today, previous and next day. Same idea as the schedule board: changing the day fetches once.
- The green/red bar for that day, from `span_json`. Paint only stored spans, green for switch 1 and red for switch 0. Do not use `factOnSegments`: it paints gaps green and drops a null end (`static/app.js`). A null end on today stops at now. A null end on any other day is not drawn to now.
- A one-line list of switch changes: time and on or off. From the same spans. Not a second query.

Refresh the board for today every 60 seconds, and when the tab becomes visible. Other days do not poll. The 10-second fragment may replace `#pm-breakers-live` only.

Empty: **ще немає знімка**. Do not draw a full green day.

### 6.9 Files

| Concern | File |
|---|---|
| Env | `config.py` |
| Tables, save, day update | `database.py` |
| Poll tick, midnight carry, message task | `power_monitor.py` |
| Sign and GET status | new `tuya_breakers.py` |
| `GET /api/breakers` | `api/dashboard.py` |
| Live lines | the dashboard HTML builder in `power_monitor.py` |
| Bar, date, 60s refresh | `static/app.js` |
| Bar colors | `static/style.css` |
| Tests | `tests/test_breakers.py` |

## 7. Phases

Each phase ends with a human gate. The agent stops, says in plain language what changed, what was checked, what is risky, and asks whether to go on. The next phase does not start without an explicit yes. Update this file and the progress file at the gate. Timestamps are full DateTime values.

Do not deploy and do not commit unless that same yes includes it. Do not put secrets in the commit. Production schema applies on process start via `init_db()`. Tests use a temporary SQLite file. They do not call Tuya and do not SSH.

### Phase 1 — store samples and the day row

Goal: a poll can be simulated by passing a status payload in. The database holds the day row. Nothing is on the page. The live poller is behind the env switch and is not required for the tests.

Touch: `database.py`, `tuya_breakers.py` (decode + payload apply only), `tests/test_breakers.py`.

Steps:

1. Create the tables in 6.1.
2. `apply_breaker_status(device, ts, payload, source)` is the locked single transaction in 6.6. It inserts one sample only when a payload is passed; the no-sample entry inserts nothing. It closes an older open span at that row's own midnight, and it updates today's row.
3. Tests use a temp db. The fixture is the recorded shape in 6.3, not a reconstructed guess. No network.

Verify: `python -m unittest tests.test_breakers`. Cases: first sample opens a span and leaves `energy_base_kwh` null; a later sample with the same switch does not add a span and updates volts; a flipped switch closes and opens; energy scale 1000000 → 10000.00; a sample at 00:01 Kyiv closes yesterday at midnight inside that same transaction and sets today's base from yesterday's counter; a no-sample call at 00:10 Kyiv opens today's span at midnight, sets `energy_today_kwh` to 0, inserts no sample, and a second call does not open a second span; a gap of two days closes the old span at that old midnight and leaves today's base null; a no-sample call after a two-day gap closes the old span at that old midnight, inserts nothing, creates no today row, and leaves the base null; a bad phase blob stores null volts and still stores the switch; two devices do not share a row. The lock is part of the function, so a test that runs two applies in overlapping threads still ends with both spans.

Gate: no page change, no live poll, no deploy.

Rollback: stop calling `apply_breaker_status`. Leave the tables. Do not drop them.

### Phase 2 — live 15-minute poll

Goal: the server writes rows. The page still does not show them.

Touch: `config.py`, `tuya_breakers.py` HTTP, `power_monitor.py` `bg_loop` and the midnight carry.

Steps:

1. Read env. Disabled when the secret or both ids are empty.
2. Every `TUYA_POLL_INTERVAL_SEC`, one token if needed, then one status GET per configured id. Apply through the Phase 1 function.
3. On process start and when the Kyiv date changes, call the same locked function with no payload, as in 6.6. Do not close yesterday from `bg_loop` with a second code path.

Verify: unit test of the tick math. The counter fires when `tick * 30` is 900 and not when it is 870. Wall time of that tick is 29 sleeps after start, because the check runs before `sleep(30)`, the same way `deye_poll_tick` does. A fake HTTP client returns one fixture and asserts a single sample. The fake client has a 10 second timeout and a failure does not skip the Deye call in that tick. Do not hit `openapi.tuyaeu.com` from tests.

Gate: operator can confirm rows exist after a deploy, but this phase itself does not deploy. Poll errors are logged with the Tuya code only.

Rollback: clear `TUYA_ACCESS_SECRET` and restart. Writers stop. Rows remain.

### Phase 3 — read route and the section

Goal: the dashboard shows the two lines, today's kWh, the phases, and the green/red bar.

Touch: `api/dashboard.py`, dashboard HTML, `static/app.js`, `static/style.css`, tests that the route does not select from `breaker_sample`.

Steps:

1. `GET /api/breakers` as in 6.7.
2. Add `breaker_details` to `ALL_SECTIONS` and `SECTION_LABELS`, and append it to stored explicit role lists the way `_append_collections` appends `collections_details`.
3. Live lines inside `#pm-breakers-live`. Board outside it, as in 6.8. Fragment key `pm_breakers` only.
4. Flag kv `breakers_board`. Missing means on. `0` hides the section and skips the board fetch. The poller keeps writing.

Verify: unittest with a temp db and a request double. A local page fixture shows green then red from a two-span JSON, and the empty state when the row is missing. A null `energy_today_kwh` renders `немає бази` and not the lifetime counter. The route test and a test of the fragment builder fail if SQL against `breaker_sample` is issued.

Gate: local UI only, unless the operator also asks to deploy.

Rollback: kv `breakers_board` = `0`. Writers stay.

### Phase 4 — messages

Goal: a switch flip becomes a span without waiting for the poll.

Touch: message client, `POST /api/tuya-webhook` only if section 6.5 chose HTTP, `apply_breaker_status` already from Phase 1.

Steps:

1. Read the Message Service screen. Record the transport in the progress file. Do not guess.
2. Accept messages for the two ids only. Apply as `source=message`.
3. Ignore duplicates.

Verify: a fixture message with the opposite switch appends a span. A second copy of the same id does not. An older `ts` than the latest sample does not change `breaker_day`. That older message id is present in `breaker_message`. A message for any other id does not write. An empty webhook secret returns 503 and writes nothing. A wrong secret returns 403 and writes nothing. Before the listener is left on, record the real message interval. If it would pass 68 000 messages in a month, leave the listener off.

Gate: ask before deploy. After deploy, flip is proven by the next real message or by the already scheduled 22:30 off, whichever is first. Do not send a switch command to test it.

Rollback: stop the listener. Poll remains.

## 8. Data and compatibility

- New tables only. `deye_log`, `power_events`, and `schedule_day` stay as they are.
- No backfill. The first day starts at the first sample.
- `energy_today_kwh` is null until the exact previous calendar day has a row. A midnight carry from that exact day sets today to 0, not to the lifetime total. The line shows `немає бази` when the value is null. It never prints `energy_kwh` as today.
- Flag `breakers_board` hides the UI only.
- Secrets stay in the server env. Device ids stay in env. This file names the variables and not the values.

## 9. Verification and done

Done means:

- Phases 1–4 accepted, or Phase 4 explicitly skipped by the operator.
- `python -m unittest tests.test_breakers` passes.
- The poll interval is 900 seconds unless env overrides it.
- `GET /api/breakers` and the 10-second fragment do not read `breaker_sample`.
- The bar is green for on and red for off, stops at now on today, and is empty before the first sample.
- No code path sends a breaker command.
- Production browser pass after deploy, or listed as not done.

## 10. Risks, questions, decisions

### Risks

- A GET that scans the day's samples will be copied into the 10-second fragment next. The route stays a read even when `breaker_day` is missing.
- The trial pack pauses the poller for the rest of the month if something else starts calling Tuya in a loop. Log the Tuya error code that came back and wait for the next interval. Do not retry immediately. Do not invent a code in this plan; the expired-trial code already seen on this project is `28841002`.
- Message transport is unread. Phase 4 must look at the screen before adding Pulsar. A wrong client is a new dependency on a small VM.
- `Europe/Kyiv` is not what the existing timer rows use. They use `Europe/Kiev`. The poller does not set timers. Do not "fix" those rows.
- Lifetime energy is about 10 000 kWh on **Світло** and about 3 600 kWh on **ІТП**. Showing that number as today is a product bug. Section 8 forbids it.
- Public repository. Do not commit `.env` or a token.

### Open questions

None blocking.

- Phase 4 transport: read it, do not invent it.
- If the operator skips Phase 4, the bar is 15-minute steps. That is allowed. Say so on the card.

### Decision log

| When | Decision | Why |
|---|---|---|
| 2026-11-09T19:55:00Z | Skin A. 15-minute status GET plus status messages. | One status call already returns switch, kWh, and all three phases. Faster polling spends the trial pack. Messages cover the on/off edge. |
| 2026-11-09T19:55:00Z | Do not subscribe to statistics APIs. | They returned `28841101`. The counter difference is enough for "today". |
| 2026-11-09T19:55:00Z | `breaker_day` is updated in the writer. GET only reads it. | Same bug class as the Deye aggregate scan on each page request. |
| 2026-11-09T19:55:00Z | Board DOM sits outside the 10s fragment. | The schedule board lost controls when they lived inside the replaced node. |
| 2026-11-09T19:55:00Z | Company KB is not consulted and not written. | Operator: this repo is not on that KB. House data stays out of it. |
| 2026-11-09T19:55:00Z | No commands, no backfill, ids in env. | The dashboard observes. History before deploy does not exist here. |
| 2026-11-09T19:55:00Z | Self-review round 1 | See below. Findings folded into this text before status was raised. |
| 2026-11-09T20:02:31Z | Lead review, before the critic. | Disk check of `_conn`, `_deye_agg_lock`, `_wrap_dashboard_section`, `_append_collections`, `app.js` fragment replace, and `pm_section_order`. Three missing contracts added in 6.6 and 6.8. Guessed quota code `1199` removed. Status `REVIEW IN PROGRESS`. No code. |
| 2026-11-09T20:17:31Z | Critic round 1, `grok-4.7-xhigh-fast`, verdict REVISE. All 5 HIGH, 5 MEDIUM, and 4 LOW accepted. | Midnight carry now opens today's span and sets today to 0 without inserting a sample. A gap does not invent days or borrow an older counter. Webhook empty secret is 503. Message ids are a set, and a late event does not move the day row. Status HTTP has a 10 second timeout in its own try after the Deye tick. Null today renders `немає бази`. The fixture shape is recorded. The bar does not use `factOnSegments`. Days use `UA_TZ`. Message rate is measured before the listener stays on. |
| 2026-11-09T20:22:51Z | Critic round 2, same model, verdict REVISE. 1 HIGH and 1 MEDIUM accepted. | A no-sample call creates today only when yesterday's row exists. A duplicate or late message does not insert a sample. |
| 2026-11-09T20:27:13Z | Critic round 3, same model, verdict APPROVE. 0 CRITICAL, 0 HIGH. Post-approve wording confirmed in the same pass. | A duplicate or late message stops before the day update. An older id is stored. Status `REVIEWED — READY FOR LOCAL WORK`. Phase 1 still needs an explicit yes. |
| 2026-11-09T20:37:30Z | Phase 1 implemented. Operator said yes via Agree & Continue. | Tables and `apply_breaker_status` only. No page, no poller, no deploy. Company KB was not queried: this repo is not on it. Disk patterns used: `init_db`, `kyiv_date_str` / `kyiv_day_bounds`, temporary SQLite tests. `python -m unittest tests.test_breakers tests.test_schedule_board` passed, 44 tests. |

#### Self-review round 1 (2026-11-09T19:55:00Z)

Hat: critic of the draft.

- HIGH, fixed here: a day view that selects every 15-minute sample will be called every 60 seconds and then every 10. `breaker_day.span_json` and `phase_json` are the only page reads.
- HIGH, fixed here: the first day's counter is thousands of kWh. `energy_today_kwh` stays null until a previous-day base exists.
- HIGH, fixed here: Phase 4 must not add a Pulsar library before the Message Service screen is read.
- MEDIUM, fixed here: token on every poll would double the call count. Cache until `expire_time`.
- MEDIUM, fixed here: a bad phase blob must not drop the switch sample.
- MEDIUM, accepted: midnight energy can include up to one poll gap or one meter step. The card says so. Not a second estimator.
- LOW: KB search omitted on purpose. The map lists disk paths.

No CRITICAL left. No HIGH left open in that pass. Status was set to `DRAFT READY FOR REVIEW`. That status is superseded by the lead review below. This is not an approval to implement.

#### Lead review (2026-11-09T20:02:31Z)

Checked against disk, not against the company KB. The operator said this repo is not connected, and house facts must not be written there.

- HIGH, fixed here: `_conn()` has no process lock, so a poll and a message can interleave the day-row update. `apply_breaker_status` is now one lock and one transaction.
- HIGH, fixed here: a sample just after midnight must close yesterday itself. Waiting for `bg_loop` to notice the date change races the sample. The day comes from the sample timestamp.
- HIGH, fixed here: a new section id that is not appended to stored role JSON is omitted by `_wrap_dashboard_section`. Phase 3 copies the `collections_details` migration.
- MEDIUM, fixed here: the plan named Tuya code `1199`. That code was not seen. The plan now says to log the code that comes back, and names only `28841002`, which this project already returned.
- MEDIUM, accepted: a saved `pm_section_order` appends an unknown section at the end (`static/app.js`). The HTML default is after Deye. No special insert.

Critic round 1 (`grok-4.7-xhigh-fast`, 2026-11-09) returned REVISE: 0 CRITICAL, 5 HIGH, 5 MEDIUM, 4 LOW. Every finding was checked against disk or against the 2026-11-09 status body and accepted. Fixes are in 6.3–6.8 and in the phase checks. No finding was rejected. Implementation is still not allowed.

## 11. Progress log

| When | Event |
|---|---|
| 2026-11-09T19:55:00Z | Plan written from the live status payload, the specification scale, the quota page, and the repo's Deye poll. Skin A. Self-review folded. No code. |
| 2026-11-09T20:02:31Z | Lead plan review. Writer lock, midnight-from-timestamp, and role-list migration added. No code. Critic next. |
| 2026-11-09T20:17:31Z | Critic round 1 folded. No code. Confirmation review next. |
| 2026-11-09T20:22:51Z | Critic round 2, `grok-4.7-xhigh-fast`, verdict REVISE: 0 CRITICAL, 1 HIGH, 1 MEDIUM. Both accepted. A no-sample call creates today only when yesterday's row exists. A late or duplicate message does not insert a sample. |
| 2026-11-09T20:27:13Z | Critic round 3 approved 0/0. Post-approve edits (duplicate stops before the day update; older id is stored) were confirmed in the same session, also 0/0. Status `REVIEWED — READY FOR LOCAL WORK`. Phase 1 still needs an explicit yes. |
| 2026-11-09T20:37:30Z | Phase 1 done. Samples and the day row write through one lock. Live site was not restarted. Phase 2 waits for an explicit yes. |

## 12. Handoff for a new chat

Read this file and `plan_breakers_PROGRESS.md`. Phase 1 is done. Do not start Phase 2 without an explicit yes. Do not call the company knowledge base. Do not send a breaker command. Do not print `TUYA_ACCESS_SECRET`. Tests stay on a temp database. Skin A stays the default. The writer is `apply_breaker_status` in `tuya_breakers.py`. It does not open a network connection.
