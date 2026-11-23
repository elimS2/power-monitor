# Automatic ITP control

- Status: Part 1 stays `LIVE`. Part 2, the heat journal, stays `LIVE`. Part 3 phase L1 is `LIVE` at `f764d9b`.
- Last updated: 2026-11-22T23:59:00Z
- Owner: Volodymyr
- Repo: `power-monitor` (public GitHub `elimS2/power-monitor`, live `https://power.elims.pp.ua`)
- Related Jira: none. This repo is not in the company knowledge base. Do not write this plan, device ids, access secrets, or house notes there.
- Part 2 proof: composer `85ba10c3-3110-479d-ac13-0dddaf1132bc`, title `Write the ITP on-off rule`, `verifiedAtUtc=2026-11-22T22:04:58.446Z`. The earlier proof `2026-11-22T21:53:10.797Z` still covers the first Part 2 draft.
- Active skin: **Skin A** (local decision every minute, one extra ITP status read and one command only when the desired state changes, then one ITP status read about a minute later). Skin B is the quarter-hour fallback for the decision. Skin C is rejected and must not be implemented.
- This file is the implementation contract. A new chat must not need the planning conversation.
- Commands ship off. `ITP_AUTO_COMMANDS` defaults to `0`. Arming the rule in admin does not by itself POST a switch.

Companion: `power-monitor/docs/plan_itp_auto_PROGRESS.md`

Source proof for this plan write: composer `85ba10c3-3110-479d-ac13-0dddaf1132bc`, title `Automatic ITP control logic`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-22T18:43:35.564Z`, `mutationKind=plan`.

Closed predecessor: `power-monitor/docs/plan_breakers.md`, status `CLOSED — LIVE READ ONLY`. Do not reopen it. This plan adds a server-side heat policy. It does not add a public on/off button, and it does not change the lighting breaker.

## 1. Goal and non-goals

### Goal

Keep the basement heat breaker (device name `itp`, card title `Обігрів`) in the state the building rule asks for:

- Turn it on when city power has been present for 15 continuous minutes, or when the boiler is in a generator window. The boiler window starts the heat breaker at once. The 15 minutes apply only to city power.
- Turn it off when city power has been absent for 15 continuous minutes and the boiler window is not open.
- Otherwise hold the last state.
- If a later sample shows the heat breaker left the state this loop confirmed, treat that as a hand change: disarm the loop and leave the breaker where the hand put it.
- If this program has sent 4 or more switch commands in the last 60 minutes, write one log line and disarm. Do not send a fifth. Section 6.3.
- Show one short line on the heat card: armed or not, and why the rule currently wants on, off, or hold.
- Let the admin key arm and disarm that loop from `/admin`. Disarming does not send a switch command.

City power means `power_events` rows `up` and `down` from the two plugs. It does not mean the DTEK grid, and it does not mean a missing Deye sample.

The boiler window is today's latest `boiler_schedule` row. No row for today means 18:00–24:00 Europe/Kyiv. A row with an empty interval list means the boiler is off all day.

### Non-goals

- Polling Tuya every minute. A second confirm read at 20 seconds plus another at 60 seconds, repeated until the watts match, is also out. One confirm read in the same once-only window the timer follow-up already uses is in section 6.5.
- Turning on Device Status Notification, Pulsar, or any message listener. `plan_breakers.md` section 6.5 already measured that above the message pack.
- A public button, switch, or form that sets the heat breaker on or off. `/admin` arms the policy. It does not contain "turn ITP on now".
- Writing the lighting breaker (`svitlo`). `LIGHT_SCHEDULE_PAUSED` in `light_schedule.py` stays `True`. `align_light_breakers` is not called by this loop.
- Following the DTEK queue, including treating `maybe` as darkness.
- Treating a stale Deye poll (`max_age_sec` 300) as an outage. A router reboot must not turn the heat breaker off.
- Changing `TUYA_POLL_INTERVAL_SEC` (default 900) or the Kyiv marks `:00`, `:15`, `:30`, `:45`.
- A new table, a second process, or a second database.
- Telegram text when the loop switches the breaker.
- Parsing a notice that says the boiler is not running today. Until a row with an empty interval list exists, a missing row stays the 18:00–24:00 default. Do not change `parse_boiler_schedule` in this plan.
- Copying device ids, access secrets, or neighbor names into git.
- Commit, push, or `#автооновити` unless the operator asks in the same yes that closes a gate.
- Creating a Jira ticket.

## 2. How this plan was adapted

Prompt library card **#6 Create Plan** (id 6, revision 4) is the working method.

- Living plan plus progress file, English, phases, skins, a human gate between phases, self-review, no code in the planning turn.
- Company KB was searched on 2026-11-22. It does not index `power-monitor`. Disk is the source of truth. House facts stay out of that KB.
- This workspace required an explicit composer proof before the plan files were written. The proof is in the header.
- No Jira ticket. Do not create one as part of implementation.
- `kb_rule('project_memory')` was not loaded. That rule is for the `knowledge_base` repo. This repo is not in `kb_repo_memory_catalog`.

## 3. Context harvest

Catalog read at 2026-11-22T18:42:32Z: nine code repos. `power-monitor` is not one of them. `git_only_repos` is only `lazy-ai`.

Searches at 2026-11-22T18:43Z, topic "ITP automatic control from city power and the boiler window":

| Volume | Mode | Result |
|---|---|---|
| knowledge | semantic | No power-monitor hit. Top ids 950, 953, 1091, 452, 308, 688 are other products. |
| ideas | semantic | No power-monitor hit. Ids 64 and 65 are a different Tuya cloud project (an apartment plug). Do not reuse that project, its device id, or its credentials for these breakers. |
| code_directories | semantic | No `power-monitor` path. Top dirs are invoice `src/Service/Tc201` and `src/Service/Tc107`. |
| code_files | hybrid | `total_fts_hits` 0. No `tuya_breakers.py`. |
| code_symbols | hybrid | Empty. `fallback_applied=or_like`. |
| jira | fts `power-monitor ITP breaker Tuya` | No ticket for this repo. Returned unrelated keys KB-294, KB-385, RLT-40, KB-387. |
| dialogs | hybrid | `total_fts_hits` 0. No breaker-quota dialog. Dialog 8143 is an invoice fetcher inventory. |

The quota decision and the live poll live on disk: `power-monitor/docs/plan_breakers.md` sections 5 and 6.4, and `power-monitor/docs/plan_breakers_PROGRESS.md` gate `2026-11-09T21:14:48Z`.

Review harvest at 2026-11-22T18:57Z repeated knowledge, ideas, code_files, code_symbols, jira, and dialogs. Still no `power-monitor` path. `code_files` hybrid `total_fts_hits` was 0. `code_symbols` was empty with `fallback_applied=or_like`. Jira fts returned unrelated KB-294. Dialogs had no breaker-poll chat. `code_directories` was not re-run; the 18:43Z result still stands. Ideas 64 and 65 remain a different Tuya project. Do not copy credentials from those rows into this repo.

### Repo memory map

| Path | Why it matters | Touch? |
|---|---|---|
| `tuya_breakers.py` | Quarter-hour poll, `breaker_shown_on`, `_breaker_lock`, timer list. | Add one switch POST and one future-timer delete for `itp` only. Do not change the poll interval. |
| `power_monitor.py` `_breaker_step`, `_breaker_lines_html` | 30-second loop and the heat card. | Call the decision tick from `_breaker_step`. Add one line on the `itp` card. |
| `power_monitor.py` `admin_page` | Admin page already has a voltage-notify toggle. | Add an arm/disarm control in that same page. |
| `api/admin.py` `ep_admin_voltage_notify_set` | `check_admin` plus `kv_set` pattern. | Add `/api/admin/itp-auto` GET and POST beside it. |
| `api/deps.py` `check_admin` | Admin key only. | Call it. Do not add a new role. |
| `database.py` `kv_get` / `kv_set`, `boiler_schedule_for_dates`, `save_boiler_schedule` | Flag storage and today's boiler row. | One JSON value under key `itp_auto`. No new table. Do not change the boiler parser. |
| `config.py` `TUYA_POLL_INTERVAL_SEC`, `STALE_THRESHOLD_SEC`, `UA_TZ` | 900-second poll, 300-second heartbeat silence, Kyiv clock. | Add `ITP_AUTO_COMMANDS` default `0` and `ITP_AUTO_SLOT` default `edge`. |
| `light_schedule.py` | Lighting timers, paused. Shows the DELETE batch path and that heat rows must not be passed in. | Do not call it. Do not clear `LIGHT_SCHEDULE_PAUSED`. |
| `detection.py` `watchdog` | Heartbeat silence already uses `STALE_THRESHOLD_SEC`. | Read the same threshold. Do not send a new Telegram message. |
| `tests/test_breakers.py` | Poll clock and `breaker_shown_on` tests. | Leave those tests green. New cases go in `tests/test_itp_auto.py`. |
| `docs/plan_breakers.md` | Closed read-only contract and the quota numbers. | Do not edit it in this work. |

### Self-check

- [x] knowledge — executed, no repo hit
- [x] ideas — executed, no repo hit; ids 64 and 65 are a different project
- [x] code_directories — executed, no repo hit
- [x] code_files — executed, no repo hit
- [x] code_symbols — executed, empty
- [x] at least three real paths from disk: `tuya_breakers.py`, `power_monitor.py`, `database.py`, `api/admin.py`, `light_schedule.py`
- [x] drill-down of those files plus `config.py`, `api/deps.py`, `detection.py`
- [x] jira and dialogs searched, no matching ticket or dialog

## 4. Current system reality

On 2026-11-22 the live section is still read-only. `poll_breakers` in `tuya_breakers.py` does two things at each due slot: `GET /v1.0/devices/{id}/status` for each configured breaker, then `sync_breaker_timers` (`GET /v2.0/cloud/timer/device/{id}` for each). The token is cached. `TUYA_POLL_INTERVAL_SEC` defaults to 900. `breaker_clock_due` lands on Kyiv `:00`, `:15`, `:30`, `:45`. A timer follow-up may run one extra full poll about 60 seconds after a one-shot fires. The page does not call Tuya.

`breaker_shown_on(switch, phases)` is the display rule and the rule this plan uses for "what the breaker is doing". Any reported watts other than a sum of exact zeros means on. A sum of exact zeros means off. With no watt fields, the switch bit is used.

`apply_breaker_status` is the only writer of `breaker_sample` and `breaker_day`. It holds `_breaker_lock`.

`bg_loop` wakes about every 30 seconds. `_breaker_step` returns immediately unless the clock slot or a timer follow-up is due.

City power is `power_events` with `event IN ('up','down')`. `_grid_events` and `_grid_state_at` in `tuya_breakers.py` already read that. They are private. `GRID_UP_RESET_SEC` is 15 minutes and is used only to reset the "since charge" counter. This plan uses the same 15 minutes for a different question: how long the present up or down has lasted.

`watchdog` in `detection.py` treats heartbeats older than `STALE_THRESHOLD_SEC` (default 300) as a silent router. That silence is not an `up` or a `down`.

`boiler_schedule_for_dates` returns a date only when a row exists. `parse_boiler_schedule` skips a date that has no clock range, so a notice with no times does not create a row. Stored ranges are `["HH:MM","HH:MM"]`. `_clock_minutes` maps `24:00` to minute 1440. The boiler lane draws start inclusive and end exclusive in the sense that a zero-width range is dropped (`end_m <= start_m` is skipped).

`save_boiler_schedule` appends a row when the JSON changed. The latest row for the date wins.

Lighting automation is paused: `LIGHT_SCHEDULE_PAUSED = True`. Future lighting timers are deleted with `DELETE /v2.0/cloud/timer/device/{id}/batch`. That function refuses heat rows (`plan_light_changes` docstring). One-shot commands today are operator scripts under `tmp/` at the Life workspace root, not part of the service. They POST `{"commands":[{"code":"switch","value":true|false}]}`. Those scripts are not a second architecture to extend. The service gets its own one-call helper.

`/admin` is rendered by `admin_page`. Voltage notifications are `kv` key `tg_voltage_notify`, read and written by `ep_admin_voltage_notify_get` and `ep_admin_voltage_notify_set` after `check_admin`. `check_admin` allows only the key whose label is `admin`.

`kv_get` / `kv_set` store one string per key. No migration is required for a new key.

Invariants that must keep working:

- The quarter-hour poll still samples both breakers.
- A Tuya error still logs and waits for the next interval. It must not tight-loop, and it must not skip the Deye poll, the schedule fetch, or the alert fetch.
- The public page and `GET /api/breakers` still do not POST.
- Device ids and the access secret stay in the server environment. Tests use fakes. Logs include Tuya error codes, not secrets or ids.

### Quota, already measured

From `plan_breakers.md` section 6.4, pricing page updated 2026-07-28, and the project screen read on 2026-11-09:

- Trial pack: about 26 000 API calls and 68 000 messages a month. Past that the trial stops until next month. It is not billed extra. The screen shows the same pack as 0.2 USD / month.
- Two status calls a minute is about 86 000 calls in 30 days. Rejected there as Skin C.
- Two status calls every 15 minutes is about 5 800 calls in 30 days, plus rare token refreshes.
- The live poll also lists timers, so the steady call count is higher than 5 800 and still inside 26 000.
- Message listener: one partial day of the lighting breaker already had 2 907 log rows with `has_next` still true. Left off.

This plan's extra calls are bounded in section 6. They are not a new poll interval.

## 5. Options and skins

Shared core for A and B: `desired_itp` and `step_itp` in a new module `itp_auto.py`. The heat card, the admin flag, the `kv` document, and the manual-pause rule do not change with the skin. The skin chooses only when an extra status GET and a POST are allowed to run.

### Skin A — edge command (default)

Every minute the loop computes the desired state from local data. No Tuya call on that tick.

When the desired state becomes `on` or `off` and it differs from the last confirmed state, and the loop is armed, and `ITP_AUTO_COMMANDS=1`:

1. At most one `GET /v1.0/devices/{id}/status` for `itp`.
2. If that read shows a hand, disarm only when step 6 in section 6.3 says so (`commands_on`, `timers_cleared_at` set, `pending` empty, `warn` empty). Otherwise do not disarm and do not POST.
3. If the read already matches the desired state, confirm it. Do not POST.
4. Otherwise one POST of `switch`. Do not chain a second URL in the same attempt.
5. About one minute after that POST, one status GET for `itp` only. Section 6.5. The quarter-hour sample is the backup if that window is missed or the watts have not fallen yet.

`ITP_AUTO_SLOT=edge` selects this skin. It is the default when the variable is unset.

Why this is the default: the 15 minutes are counted from the `up` or `down` timestamp, so the command can go at that minute. Waiting for the next quarter mark would add up to 15 more minutes. The pre-command GET, the POST, and the one-minute confirm stay inside the pack (section 6.4).

### Skin B — decide on the quarter-hour sample

`ITP_AUTO_SLOT=quarter`. The pre-command GET never runs. A POST is considered only inside the poll that already fetched `itp`, using that payload as the actual state. The same `desired_itp` and `step_itp` functions run. The command can lag until the next `:00`, `:15`, `:30`, or `:45`. The one-minute confirm in 6.5 still runs after that POST.

Choose B only if a month's call counter shows the pre-command GET is the wrong spend. Switching skin is an env change and a restart. No migration. An in-flight command is still confirmed by 6.5, and by the next stored sample if that confirm window was missed.

### Skin C — rejected

Do not implement either of these:

- Status every minute (about 86 000 calls / 30 days for two devices).
- A status read at 20 seconds and again at 60 seconds after each command, repeated until it matches. The single confirm in 6.5 is not this.
- The message listener.

A failed extra GET must not be retried every minute. That retry would become Skin C while the cloud is deaf. Section 6 caps it.

### What does not switch with the skin

- Desired-state table.
- Manual disarm.
- `ITP_AUTO_COMMANDS=0` means no POST and no extra GET, on either skin.
- Lighting breaker, poll interval, message listener.

## 6. Recommended architecture

One new module, `itp_auto.py`, holds the policy. `tuya_breakers.py` holds the HTTP. `power_monitor.py` holds the card line and the admin control. `api/admin.py` holds the two routes. `kv` key `itp_auto` holds the document. No second subsystem.

### 6.1 Desired state

```
desired_itp(now_kyiv, light, boiler) -> {state: on|off|hold, reason: str, boiler_source: "default"|"row"|"none"}
```

`boiler_source` is `default` when the row is missing and the clock is inside 18:00–24:00, `row` when a stored interval matches, and `none` otherwise.

`now_kyiv` is a timezone-aware datetime in `config.UA_TZ`.

`light` is one of:

- `{kind: "up", since: datetime}` — last `up`/`down` event is `up`, and the newest heartbeat is not older than `STALE_THRESHOLD_SEC`
- `{kind: "down", since: datetime}` — last event is `down`, same heartbeat rule
- `{kind: "unknown"}` — no up/down event, or the newest heartbeat is older than `STALE_THRESHOLD_SEC`

`boiler` is one of:

- `{kind: "missing"}` — `boiler_schedule_for_dates` has no row for this Kyiv date
- `{kind: "intervals", intervals: [["HH:MM","HH:MM"], ...]}` — latest row, including `[]`

Window test, same clock as `_clock_minutes`:

- Minute of day is `hour * 60 + minute` in Kyiv.
- `24:00` is minute 1440.
- A pair counts when `start <= minute < end`.
- `missing` is the single pair `18:00`–`24:00`.
- `intervals: []` matches nothing.

`stable` means `now - since >= 15 minutes`. Use `timedelta(minutes=15)`, not a fixed 900 added to a UTC timestamp by hand, so the Kyiv date is the datetime's date.

| Condition | State | Reason text |
|---|---|---|
| Boiler window is open | `on` | `boiler` |
| Light is `up` and stable | `on` | `light-on` |
| Light is `down` and stable, and the boiler window is closed | `off` | `light-off` |
| Anything else | `hold` | `settling` if light is up or down but not yet stable; `unknown` if light is unknown |

`on` is tested first, so an open boiler window does not wait 15 minutes, and it does not turn off at the end of a short outage inside the window.

`hold` sends nothing. The breaker stays where it was.

Examples the tests must lock:

- Light up for 14 minutes, no boiler window: `hold`.
- Light up for 15 minutes, no boiler window: `on`.
- Light down for 15 minutes, no boiler window: `off`.
- Light down for 20 minutes, clock is 18:00, boiler missing: `on`.
- Light down for 20 minutes, clock is 17:59, boiler missing: `off`.
- Light up for 20 minutes, clock is 00:00, boiler missing: `on` because the light is stable. The default window does not cover the new day until 18:00, and it does not need to.
- Light down for 20 minutes, clock is 00:00, boiler missing: `off`.
- Explicit intervals `19:00–24:00`, light down, clock 18:30: `off`.
- Explicit intervals `[]`, clock 19:00, light down for 20 minutes: `off`.
- Light unknown, boiler window open: `on`.
- Light unknown, boiler window closed: `hold`.

Do not read `schedule_history` inside `desired_itp`.

### 6.2 Stored document

`kv` key `itp_auto`. One JSON object. Version `1`. Missing key means the defaults below.

| Field | Meaning |
|---|---|
| `v` | `1` |
| `enabled` | Admin arm. Default `false`. |
| `applied` | `on`, `off`, or `null`. The state this loop last confirmed. |
| `pending` | `null` or `{state, sent_at, followup_done}`. `sent_at` is unix seconds. `followup_done` is true after the one confirm attempt in 6.5. |
| `pause` | `null` or `{at, reason, was, now}`. `reason` is `manual` or `flap`. |
| `command_times` | Unix seconds of switch POSTs this program emitted. Prune entries older than 3600 seconds. Arm does not clear this list. |
| `last` | `{state, reason, at}` from the latest `desired_itp`. Always updated. |
| `warn` | `null` or `{at, kind, code}`. `kind` is `rejected`, `transport`, or `unconfirmed`. A rejected or transport warn is not a hand change. |
| `timers_cleared_at` | Unix seconds, or empty. Set only after the one-shot delete in 6.6 succeeds. |
| `timer_delete_attempted` | False until the one delete attempt in 6.7. A failed attempt stays true so the next wake does not call Tuya again. Only arm sets it false. Disarm leaves it unchanged. |
| `slot_spent` | Quarter index `int(now // 900)` of the last extra ITP status GET. Kyiv `:00`, `:15`, `:30`, `:45` fall on these buckets because the offset from UTC is a whole number of hours. Stops a second extra GET inside the same quarter. |

`mutate_itp_auto(update)` in `itp_auto.py` holds `_breaker_lock`, reads the JSON, runs `update` on the dict, and writes it back. HTTP runs outside that lock.

Admin disarm sets `enabled` false and clears `pending`. It does not change `applied`, it does not change `timer_delete_attempted`, and it does not POST.

Admin arm sets `enabled` true, clears `pause`, `warn`, and `timer_delete_attempted`, and sets `applied` from the latest `itp` row via `breaker_shown_on`. If that row is missing, `applied` stays `null`. Arming does not POST. The loop does.

A hand pause also sets `enabled` false. The operator arms it again from admin. That is the same flag, not a second switch.

### 6.3 Step

```
step_itp(doc, desired, actual, now, commands_on, slot) -> doc, action
```

`actual` is `on`, `off`, or `unknown`. `unknown` means this tick has no fresh sample.

`action` is `none`, `read`, or `post`.

`commands_on` is true only when `ITP_AUTO_COMMANDS` is `1`.

Order:

1. Write `last` from `desired` every time.
2. If `enabled` is false: action `none`. Leave the breaker alone.
3. If `desired.state` is `hold`: action `none`.
4. If `commands_on` is false: action `none`. The card still shows `last`.
5. If `pending` is set: action `none`. Do not POST again. The confirm read is not this step. Section 6.5 runs it from the wake before `step_itp`, including when this step would return `hold`.
6. If `commands_on` is true and `timers_cleared_at` is set, and `actual` is `on` or `off`, and `applied` is `on` or `off`, and `actual != applied`, and `pending` is empty, and `warn` is empty: set `enabled` false, fill `pause` (`reason=manual`, `was=applied`, `now=actual`), action `none`. While commands are off, or `timers_cleared_at` is still empty, do not disarm. A quarter sample in that mode may copy `applied` from `breaker_shown_on` of the stored `itp` row and must leave `enabled` unchanged.
7. If `desired.state == applied`: action `none`.
8. If `timers_cleared_at` is empty, return `none`. Do not `read` and do not `post` while future heat one-shots may still be in the cloud. If `flap_blocks` is already true, return `none`, set `enabled` false, set `pause.reason` to `flap` and `pause.at` to now, and log `itp-auto: flap stop, 4 commands in 60 minutes`. Do not POST. This check is the same for `slot=edge` and `slot=quarter`. Otherwise the edge is real. Skin A returns `read` when `slot` is `edge` and this quarter is not yet in `slot_spent`. If `slot` is `edge` and `slot_spent` is already this quarter, return `none`. Do not fall through to `post` with `actual=unknown`. Skin B (`slot=quarter`) returns `post` only when `actual` is known, it is the opposite of `desired`, `timers_cleared_at` is set, and `flap_blocks` is false. Skin B returns `none` when `actual` is unknown.
9. A second call after a successful read: if `actual == desired`, set `applied`, action `none`. If `actual` disagrees with `applied`, apply step 6 and return. Do not use a wider disarm. If step 6 does not disarm and `actual` matches `applied` and differs from `desired`, action `post` only when `timers_cleared_at` is set and the flap guard below allows it. If `timers_cleared_at` is empty, action `none`.

Flap guard, separate from the hand check. `flap_blocks(times, now)` is true when 4 or more timestamps in `command_times` are still inside the last 3600 seconds. Constants: `FLAP_LIMIT = 4`, `FLAP_WINDOW_SEC = 3600`.

- A switch POST counts only when we emit it: body `success: true`, or a transport failure. A body `success: false` does not count. A status GET, a confirm GET, a timer delete, and a dry-run decision do not count.
- Before emitting a POST, if `flap_blocks` is already true, do not POST. Set `enabled` false, `pause.reason` to `flap`, and `pause.at` to now. Log `itp-auto: flap stop, 4 commands in 60 minutes`.
- After a counted POST, append `now` and drop timestamps older than 3600 seconds. If `flap_blocks` is then true, disarm the same way. That fourth command has already gone out. A fifth must not.
- Arm does not erase `command_times`. If four stamps are still inside the hour, the next edge trips the guard again and sends nothing.
- This is not a hand change. `pause.reason` is `flap`, not `manual`. The breaker stays where the last command left it.

`read` spends the pre-command status GET. The caller sets `slot_spent` before the request leaves the lock, so a second tick in the same quarter cannot spend another pre-command GET. If that GET fails, leave `slot_spent` set. The next chance to decide is the ordinary poll. Do not GET again at the next minute for the same edge. The confirm GET in 6.5 is a different spend, gated by `followup_done`, and only after a POST.

`post` is one POST. Three outcomes:

- Body `success: true`: write `pending` with `followup_done` false. The confirm in 6.5 is scheduled.
- Body `success: false`: do not write `pending`. Set `warn` with `kind=rejected` and the Tuya code. The breaker did not move. Do not schedule a confirm GET. A later sample that equals `applied` clears this warn. A sample that differs does not disarm and does not POST while `warn.kind` is `rejected`.
- Transport failure (timeout, connection error, non-JSON, HTTP status without a Tuya body): write `pending` anyway, `followup_done` false, and set `warn.kind=transport`. The cloud may already have switched the breaker. The confirm GET and the quarter sample decide. This is not a hand change.

`slot_spent` stays set in all three, so another pre-command GET waits for the next quarter. Do not POST again inside the same quarter. The client timeout is the existing 10 seconds on the Tuya call. Do not shorten it and do not retry inside that call.

### 6.4 Calls that count

Steady poll, unchanged: 2 status + 2 timer lists, 4 times an hour. About 11 500 calls in 30 days, plus rare token refreshes and timer follow-ups.

Skin A extra, only while armed and `ITP_AUTO_COMMANDS=1`, only when `desired` changes to a different `on` or `off`:

- 1 status GET for `itp` before the command
- 1 POST
- 1 status GET for `itp` about a minute after the POST, once
- If the pre-command GET fails, 0 POST and 0 confirm GET

A heavy day is well under 12 edges. 12 × 3 × 30 days is about 1 100 calls. The pack still has room. A deaf cloud does not multiply this: `slot_spent` blocks another pre-command GET in the same quarter, and `followup_done` blocks a second confirm inside the window.

Turning the loop on may also delete future `itp` one-shots once (6.6): one timer list (or reuse the list just stored) and one DELETE batch. Not every tick.

Skin B skips the pre-command GET. It still pays the POST and the one confirm GET.

Do not list timers, delete timers, or GET `svitlo` from this loop's minute tick.

### 6.5 Confirm the command, then keep the quarter sample as backup

This copies the timer follow-up, not the whole poll.

`breaker_timer_followup_due` is true once, from 60 seconds after a one-shot's fire time through the next 90 seconds (`BREAKER_TIMER_FOLLOWUP_SEC` and `BREAKER_TIMER_FOLLOWUP_WINDOW_SEC`). The wake then calls `poll_breakers_http`, which reads both breakers and both timer lists. That path stays for timers.

A direct switch POST has no timer id, so that path does not run for it. After a POST that the cloud accepted, `pending.sent_at` is set and `followup_done` is false. On a later wake, before `step_itp`:

- Due when `followup_done` is false and `sent_at + 60 <= now <= sent_at + 60 + 90`. Use those two constants. Do not invent a second window.
- Then one `GET /v1.0/devices/{id}/status` for `itp` only. Do not call `poll_breakers`. Do not read `svitlo`. Do not list timers.
- Set `followup_done` true under the lock before the GET leaves, so the next wake in the same 90 seconds does not send a second GET. A failed GET stays done. The quarter sample below is the backup.
- Parse the confirm body the same way `apply_breaker_status` does: `_status_fields`, then `_switch_bit`, then `decode_phase` for `phase_a`, `phase_b`, and `phase_c`. Pass that switch and the decoded phase map to `breaker_shown_on`. Do not pass the raw status dict. `breaker_shown_on` only sums watts when the phase map has keys `a`, `b`, and `c`. A raw result dict has none, and a truthy dict would be read as on. Apply the result only when `pending` is still present and `sent_at` is the timestamp this GET was issued for. If the quarter sample already cleared `pending`, the body changes nothing. If it matches `pending.state`, set `applied`, clear `pending` and `warn`. If it does not match, leave `pending`. That mismatch is not a hand change while `pending` is set.
- If the process sleeps through the whole window, `followup_done` stays false and no confirm GET is sent. The next quarter sample still settles the command.

There is no read at 20 seconds, and no second confirm if the first one still shows the old watts.

Call the quarter-hour settle function only after `apply_breaker_status` has returned. That function releases `_breaker_lock` before it returns. Acquire the lock again inside settle. Do not call settle from inside the locked body of `apply_breaker_status`: `threading.Lock` is not reentrant, and a nested acquire deadlocks the poll.

On that second hold, if `itp_auto` has `pending` or `enabled`:

- `actual` comes from the switch and `phase_json` just stored by `apply_breaker_status`, passed through `breaker_shown_on`. Do not pass the raw status dict. A no-sample midnight carry is not a settle input.
- If `pending` is set and `actual` equals `pending.state`: set `applied` to that state, clear `pending` and `warn`.
- If `pending` is set, `actual` differs, and `now - sent_at >= 20 minutes`: clear `pending`, set `warn` (`code=unconfirmed`). Leave `enabled` true. The next time `desired` differs from `applied`, 6.3 may try one new edge. It must not POST every minute while the warn is up.
- If `pending` is clear, `enabled` is true, `commands_on` is true, `timers_cleared_at` is set, `warn` is empty, `applied` is set, and `actual != applied`: manual disarm, as in 6.3 step 6. A rejected-command warn or a still-open `pending` blocks this branch.

Twenty minutes is one missed quarter plus slack. Phase C residue that is still non-zero watts means `breaker_shown_on` is still on. That is not a successful off, and it is not a hand change while `pending` is set.

A sample that arrives with `enabled` false does not re-arm and does not POST.

### 6.6 Future heat timers, once, when commands are allowed

The only caller is section 6.7 item 2. It runs once per arm: the wake where `ITP_AUTO_COMMANDS` becomes `1`, or where `enabled` flips to true while commands are already `1`. It does not run again on the next 30-second wake.

- Set `timer_delete_attempted` true before the request leaves, so a crash or a failure cannot schedule another try.
- Read `itp` timers with the existing timer GET.
- Delete one-shots whose fire time is still in the future. Use one DELETE batch, the same path shape as `light_schedule.py` (`/v2.0/cloud/timer/device/{id}/batch`). Skip rows whose `loops` contain `1`.
- Do not delete `svitlo` timers.
- If the list or the delete fails: leave `timers_cleared_at` empty, set `warn` with `kind=timer-delete` and the code that came back, do not POST, leave `enabled` true. The card shows the warn. The operator disarms and arms again to allow one new attempt. Disarm does not clear `timer_delete_attempted`. Arm does. A matching power sample does not clear this warn and does not set `timers_cleared_at`.
- On success, store `timers_cleared_at` and clear a `timer-delete` warn.

That is one timer list and, when there is something to delete, one DELETE batch. Not every tick. Two calls every 30 seconds would be about 5 760 calls a day and would exhaust the trial pack. The attempt flag exists to stop that.

If `ITP_AUTO_COMMANDS` is `0`, arming does not delete timers and does not POST. A quarter sample may refresh `applied` and must not disarm. Dry arming is safe while old one-shots remain. Say that on the admin control: commands are still off, cloud timers can still fire. The separate yes that sets `ITP_AUTO_COMMANDS=1` begins with a fresh copy of `applied` from the latest `itp` day row, then the timer delete above. Hand checks stay off until `timers_cleared_at` is set. If the delete fails, `timers_cleared_at` stays empty, so there is still no POST and no disarm.

### 6.7 Where the loop sits

`_breaker_step` already runs about every 30 seconds. Today it returns immediately unless the quarter-hour clock or a timer follow-up is due, and that return is what keeps the steady poll at 15 minutes. Do not put the new work after that return. The new work runs first, on every wake where `poll_is_enabled` is true:

1. Command confirm from 6.5, if the window is due. One `itp` status GET, inside its own try. A failure is logged and does not skip the later steps. This wake still continues.
2. If `ITP_AUTO_COMMANDS` is `1`, `timers_cleared_at` is empty, and `timer_delete_attempted` is false: copy `applied` from the latest `itp` day row, set `timer_delete_attempted` true, then run the section 6.6 delete once. Do this before `step_itp`. This branch runs on the wake where commands become `1`, or where `enabled` flips to true while commands are already `1`. A failed delete leaves `timers_cleared_at` empty. Later wakes see `timer_delete_attempted` and must not call the timer list or the DELETE again. Only arm sets the flag false, so the wake after disarm still makes zero timer calls. While the flag is true and `timers_cleared_at` is empty, this wake and later wakes do not call `step_itp` for a `read` or `post`.
3. Decide tick, if at least 60 seconds have passed since `last_decision_at` in memory (a restart decides once immediately). Local SQLite only, unless the read step below returns `read` or `post`.
4. Only then the existing clock/timer check. If neither is due, return without `poll_breakers_http`.

That split is the whole quota guard. A decide tick after the early return would never run between quarter marks, and the one-minute confirm would never run either.

Decide tick, Skin A:

1. Load today's boiler row, the latest `up`/`down`, and the newest heartbeat age. Local SQLite only. `recent_heartbeats(1)` is the heartbeat read. Compare its age with `STALE_THRESHOLD_SEC`.
2. `desired_itp`.
3. Under the lock, `step_itp` with `actual=unknown`. A minute tick must not GET the breaker just to discover a hand. Hands are seen by the pre-command read below, or by the quarter-hour settle in 6.5.
4. If the action is `none`, release the lock. Do not return from the wake: the quarter-hour poll may still be due. Log only when `last.state`, `last.reason`, `enabled`, `pause`, or `warn` changed. English, prefix `itp-auto:`.
5. If the action is `read`: set `slot_spent` under the lock, release the lock, then one status GET inside its own try. A timeout or Tuya error is logged with the public code and does not leave `_breaker_step`. Then the clock check in item 4 of this section still runs on that same wake. `breaker_clock_due` is only true for about 90 seconds after the mark, so a raised exception that skips `poll_breakers_http` would drop the backup sample. Parse a successful body the same way as the confirm GET (`_status_fields`, `_switch_bit`, `decode_phase`, then `breaker_shown_on`). Under the lock, call `step_itp` again with that `actual`. Only that second call may return `post`. If it returns `post`, the flap guard in 6.3 runs before any bytes leave: when `flap_blocks` is already true, do not POST, disarm with `pause.reason=flap`, and log the flap line. Otherwise POST once inside the same kind of try. A counted result (`success: true` or a transport failure) appends `now` to `command_times`. If that append makes `flap_blocks` true, disarm the same way. The fourth command has already gone out. Write `pending` from the three outcomes in 6.3. If the GET fails, do not call `step_itp` again and do not POST. `slot_spent` stays set.
6. A minute tick never returns `post` on the first call when the slot is `edge`.

Skin B does not use that minute-tick HTTP. The minute tick still stores `last`, with `actual=unknown`, and gets `none` from 6.3 while `timers_cleared_at` is empty. The POST is decided in `poll_breakers` after the `itp` status payload is already in hand and `apply_breaker_status` has returned: call `step_itp` with that `actual` and `slot=quarter`. If that call returns `post` and `flap_blocks` is already true, do not POST, disarm with `pause.reason=flap`, and log the flap line. Otherwise, when it returns `post` and `timers_cleared_at` is set and `flap_blocks` is false, POST once. After a counted POST (`success: true` or a transport failure), append `now`, drop stamps older than 3600 seconds, and if `flap_blocks` is then true, disarm the same way. `success: false` does not append. The one-minute confirm in 6.5 still runs on a later wake. The minute tick must not POST in Skin B.

The quarter-hour poll stays the owner of `apply_breaker_status`. The decide tick must not call `poll_breakers` and must not call `sync_breaker_timers`. The confirm GET must not call them either. Phase 3 tests call the decide function directly, so they do not need `poll_is_enabled`.

Deye, schedule, weather, and alert fetches stay in their own steps. A 10-second Tuya timeout on the rare edge may delay the rest of that 30-second wake, the same way the existing poll timeout may. It must not cancel those later steps, and it must not repeat inside the wake.

### 6.8 Card line

In `_breaker_lines_html`, for `name == "itp"` only, one line under the state word. It reads `itp_auto` and does not call Tuya.

Ukrainian, one sentence, no device id:

| Document | Line |
|---|---|
| `enabled` false, no `pause` | `Керування: ручне.` plus the would-be clause from `last` |
| `pause.reason == manual` | `Керування: ручне. О HH:MM перемкнули вручну.` |
| `pause.reason == flap` | `Керування: ручне. За годину вже 4 перемикання.` |
| `enabled` true, commands off | `Керування: автоматичне. Команди ще вимкнені.` plus the would-be clause |
| `enabled` true, commands on, `pending` | `Керування: автоматичне. Команда ще не підтверджена.` |
| `enabled` true, commands on, in sync | `Керування: автоматичне.` plus why (`світло` or `котельня`) |
| `warn` set | append `Хмара не підтвердила команду.` |

Would-be clause:

- `on` / `boiler` → `За правилом зараз увімкнути: котельня.`
- `on` / `light-on` → `За правилом зараз увімкнути: світло вже 15 хв.`
- `off` → `За правилом зараз вимкнути.`
- `hold` / `settling` → `За правилом ще чекати.`
- `hold` / `unknown` → `За правилом тримати: немає свіжого факту світла.`
- `last.reason` for a missing boiler window is still `boiler` or `light-off`. When the reason is `boiler` and the row was missing, add `Графік котельні не приходив, вікно 18:00–24:00.`

`desired_itp` must return `boiler_source: "default"` or `"row"` so the card can add that sentence without reading the table again. Put `boiler_source` on `last`.

The mode sits in the heat meter's list, after the battery row: label `Керування`, value `ручне` in red or `автоматичне` in green, the same row style as voltage and power. The extra sentence stays under the list in muted text. On 2026-11-22T21:28:00Z the operator asked for that place and those colors. Proof `verifiedAtUtc=2026-11-22T21:28:08.851Z`.

The line is inside `_breaker_lines_html`, which `_breaker_live_html` already uses, so the 10-second fragment updates it. Do not duplicate it in the static shell.

Phase 4 used one temporary armed sentence, `Авто увімкнено в адмінці, без команд.` On 2026-11-22T21:00:00Z the operator said that sounded like a way of switching the breaker. The line names the program. On 2026-11-22T21:09:00Z the operator shortened it to `Керування: автоматичне` or `Керування: ручне`. Phase 5 uses the table above. Proof `verifiedAtUtc=2026-11-22T21:09:18.899Z`.

The lighting card gets no such line.

### 6.9 Admin

`GET /api/admin/itp-auto` and `POST /api/admin/itp-auto?enabled=0|1`, both `check_admin`.

POST with `enabled=1` runs the arm update in 6.2. POST with `enabled=0` disarms. Neither route calls Tuya.

On `/admin`, a block next to the voltage-notify control:

- The same sentence the card shows.
- `last` state, reason, and time.
- `warn` code if any.
- Whether `ITP_AUTO_COMMANDS` is on. The page reads that from the process env. It cannot turn the env on. The button only arms or disarms.
- Button text `Увімкнути авто` / `Вимкнути авто`.

No other key sees the button. The heat card line is visible to whoever can see the breaker section.

### 6.10 Log line

`log.info("itp-auto: %s", text)` when the visible decision changes.

Examples:

- `would on light-on commands-off`
- `would off light-off boiler-default`
- `hold settling`
- `read status before on`
- `post on`
- `confirmed on`
- `manual pause was on now off`
- `flap stop, 4 commands in 60 minutes`
- `command unconfirmed code 1199` (use the real code that came back; do not invent one in production)

Do not log the access secret, the token, or the device id.

## 7. Phased implementation

Each phase stops for a human end-gate. The agent writes what changed, what was verified, what the plan now says, and the risks, then asks whether to continue. The next phase does not start without an explicit yes.

No phase commits or deploys unless that same yes asks for it.

### Phase 1 — pure desired state

Goal: `desired_itp` and the boiler window test, with no I/O.

Touched: `itp_auto.py` (new), `tests/test_itp_auto.py` (new).

Steps: implement 6.1. Tests cover every row in the example list, plus a window that ends at `24:00` and a pair the clock cannot parse (ignored, not a crash).

Landed 2026-11-22T20:07:00Z. `python -m unittest tests.test_itp_auto` passed, 15 tests. The module imports only `datetime`. Phase 2 has not started.

Verification: `python -m unittest tests.test_itp_auto`. No network. No sqlite. Grep the new module for `httpx`, `tuya`, `kv_`, and `power_events` and confirm none are imported.

Rollback: delete the two new files.

Deploy: no.

### Phase 2 — pure step and document

Goal: `step_itp` and `mutate` against a temp sqlite `kv`, still no HTTP.

Touched: `itp_auto.py`, `tests/test_itp_auto.py`.

Steps: implement 6.2 and 6.3 except the real GET/POST. Tests:

- disabled document returns `none` and does not change `applied`
- `hold` returns `none` while enabled
- `commands_on` false returns `none` and still stores `last`
- `command_followup_due` is false at 30 seconds, true at 60 seconds, true at 150 seconds, and false at 151 seconds. Use `BREAKER_TIMER_FOLLOWUP_SEC` and `BREAKER_TIMER_FOLLOWUP_WINDOW_SEC`. The live predicate is inclusive at both ends.
- first edge with `slot=edge` returns `read` and sets `slot_spent`
- a second step in the same quarter does not return `read` and does not return `post`
- after a fake read that matches `applied` and not `desired`, the next step returns `post` and leaves `pending` null. A separate caller test writes `pending` only after a fake body with `success: true`. A fake transport failure writes `pending` with `followup_done` false. A fake body with `success: false` leaves `pending` null, sets `warn.kind=rejected`, and the next step in that same quarter returns `none`.
- `actual != applied` disarms only when `commands_on` is true, `timers_cleared_at` is set, `pending` is empty, and `warn` is empty. Commands off does not disarm. An empty `timers_cleared_at` does not disarm. A set `warn` does not disarm.
- `actual != applied` while `pending` is set does not disarm
- an edge with `timers_cleared_at` empty returns `none`, not `read` and not `post`
- three counted commands inside 3600 seconds, `slot=quarter`, and a known opposite `actual` still return `post`. Four stamps already inside that window, with the same Skin B input, return `none`, set `enabled` false, and set `pause.reason` to `flap`. The caller does not POST.
- a counted command whose timestamp is 3601 seconds old does not count. A `success: false` body does not count. Arm does not clear `command_times`.
- Skin B (`slot=quarter`) with `actual=unknown` returns `none`
- Skin B with a known opposite `actual` returns `post` only when `flap_blocks` is false and `timers_cleared_at` is set.

Verification: the same unittest. Grep `itp_auto.py` for `httpx` and confirm it is still absent.

Rollback: revert this phase's functions. Phase 1 tests still pass.

Deploy: no.

Landed 2026-11-22T20:31:00Z. `python -m unittest tests.test_itp_auto` passed, 36 tests. No HTTP. `httpx` is not imported. The follow-up window uses the same 60 and 90 seconds as `BREAKER_TIMER_FOLLOWUP_SEC` and `BREAKER_TIMER_FOLLOWUP_WINDOW_SEC`; the numbers live in this module so the file does not import the Tuya client. The document lock is also here, separate from `_breaker_lock`. Phase 5 must release the breaker lock before `mutate_itp_auto`. Phase 3 has not started. Proof `verifiedAtUtc=2026-11-22T20:30:42.938Z`.

### Phase 3 — local tick and card line

Goal: the running service computes the decision every minute and shows the line. Commands stay off. No extra GET.

Touched: `power_monitor.py` (`_breaker_step`, `_breaker_lines_html`), `itp_auto.py` (loader for events, heartbeat, boiler), `tests/test_itp_auto.py`.

Steps:

- Load light from `up`/`down` events and `recent_heartbeats(1)` compared with `STALE_THRESHOLD_SEC`.
- Load boiler through `boiler_schedule_for_dates` for today's Kyiv date.
- Call the decide function at the start of `_breaker_step`, before `if not clock and not follow`. Leave that return in place so a quiet wake does not call `poll_breakers_http`. Phase 5 adds the confirm in that same prefix, each HTTP call in its own try, so a confirm error still reaches the clock check.
- Call `step_itp` with `commands_on` forced false in this phase even if someone set the env. Phase 5 is what honors the env. Hard-code the call argument `False` until Phase 5 replaces that argument with the env read. A test fails if Phase 3's tick function can return `read` or `post`.
- Render 6.8 from the stored document. Commands-off copy is the one used, because commands are not honored yet.
- Log on change.

Verification:

- unittest with a temp db: heartbeat older than 300 seconds and no boiler window stores `hold` / `unknown`; a missing boiler row at 18:00 Kyiv stores `on` / `boiler` / `boiler_source=default`; an `up` event 16 minutes ago stores `on` / `light-on`.
- The tick test's fake HTTP client, if one is even constructed, has zero calls.
- `python -m unittest tests.test_breakers tests.test_itp_auto tests.test_light_schedule`.
- After the operator asks to deploy: the heat card shows `Авто вимкнено.` and a would-be clause. The lighting card does not. The page has no new button. A minute of service log contains at most the change line, not a Tuya status line caused by this tick.

Rollback: remove the tick call and the card line. `kv` row may remain. No breaker command was sent.

Deploy: only if the gate yes includes deploy. Default env is still no commands. `#автооновити` only if that yes asks for it.

Landed 2026-11-22T20:45:00Z. The decide tick runs at the start of `_breaker_step`, before the quarter-hour return, and passes `commands_on=False` as a literal. A stale heartbeat stores `hold` / `unknown`. A missing boiler row at 18:00 Kyiv stores `on` / `boiler` / `default`. An `up` event 16 minutes ago with a fresh heartbeat stores `on` / `light-on`. The heat card shows the disabled sentence plus the would-be clause. The lighting card has no auto line. The tick test constructs no HTTP client. `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule` passed, 90 tests. One pre-existing failure was the bar test still expecting 6 lanes after the alert lane had already made 7; the expected count is now 23×7. The chart itself was not changed. No deploy. Phase 4 has not started. Proof `verifiedAtUtc=2026-11-22T20:45:01.057Z`.

### Phase 4 — admin arm

Goal: the admin key can set `enabled`. Arming still does not POST and does not delete timers, because Phase 3's tick still passes `commands_on=False`.

Touched: `api/admin.py`, `power_monitor.py` admin block, `itp_auto.py` arm/disarm helpers, tests.

Steps: routes in 6.9. Arm copies `breaker_shown_on` of the latest `itp` day row into `applied`. A non-admin key gets 403. The button is not on the public card.

Verification:

- unittest: arm then disarm round-trip. A non-admin key is a browser check after deploy: `GET /api/admin/itp-auto` returns 403. There is no existing route-test harness to copy.
- After deploy, if the yes includes it: the public heat card, while armed, says `Авто увімкнено в адмінці, без команд.` It must not say `Авто увімкнено.` and it must not say `команди ще вимкнені` until Phase 5 replaces the sentence with the table in 6.8.
- Browser: arm, disarm, arm again. No Tuya command in the log from the click.

Rollback: disarm, remove the routes and the block. Public card returns to the Phase 3 line.

Deploy: only with the gate yes.

Landed 2026-11-22T20:54:00Z. `GET` and `POST /api/admin/itp-auto` require the admin key. A stranger key gets 403 from a direct call. Arm copies `breaker_shown_on` of the newest `itp` day: a bit that is still on with zero watts is stored as `off`. No day row leaves `applied` empty. Arm clears pause, warn, and `timer_delete_attempted`, and keeps `command_times`. Disarm keeps `applied`, `command_times`, and `timer_delete_attempted`. Neither call constructs an HTTP client. The public heat card, while armed, says `Авто увімкнено в адмінці, без команд.` The admin block sits on the notifications tab next to the voltage switch. The button text is `Увімкнути авто` / `Вимкнути авто`. The cloud-commands line is read from `ITP_AUTO_COMMANDS` and the page cannot set it. `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule` passed, 94 tests. No deploy. The click path was not exercised in a browser because this yes did not include deploy. Phase 5 has not started. Proof `verifiedAtUtc=2026-11-22T20:53:49.287Z`.

### Phase 5 — commands, still default off

Goal: honor `ITP_AUTO_COMMANDS` and `ITP_AUTO_SLOT`. Default remains `0` and `edge`.

Touched: `config.py`, `tuya_breakers.py` (POST helper, one-shot delete helper), `itp_auto.py`, `power_monitor.py` tick, tests.

Steps:

- Replace the hard-coded `False` with the env read.
- POST body `{"commands":[{"code":"switch","value": true or false}]}` to `/v1.0/devices/{id}/commands` exactly once per `post` action. Do not also call `/v1.0/iot-03/...` in the same attempt.
- Status GET uses the existing `_device_status` path, `itp` id only.
- Confirm hook in 6.5: one `itp` status GET in the timer follow-up window after a POST. The quarter-hour sample still settles a command the window missed. Do not call `poll_breakers` for that confirm.
- Timer delete in 6.6 only on the arm transition while commands are on.
- Card copy becomes the table in 6.8.
- A test with a fake client: a hold tick and a disabled tick issue zero requests; an edge issues one GET; a matching read issues zero POST; a differing read issues one POST; `svitlo` is absent from every path; a failed pre-command GET does not POST and the next minute issues zero GETs; `ITP_AUTO_COMMANDS=0` issues zero GETs and zero POSTs while `enabled` is true.
- The same fake client: 30 seconds after a POST, zero GETs; 60 seconds after, one `itp` status GET and no `svitlo` GET; a second wake inside the following 90 seconds, zero GETs; a wake after the window, zero confirm GETs. A confirm body that matches `pending` clears it. A body that does not match leaves `pending` and does not disarm.
- The same fake client, after a failed timer delete: `timer_delete_attempted` is true, `timers_cleared_at` is empty, and the next wake issues zero timer lists, zero DELETEs, and zero POSTs. Disarm leaves the flag true, and the wake after disarm also issues zero timer lists, zero DELETEs, and zero POSTs. Arm sets the flag false and allows one new attempt.

Verification: `python -m unittest tests.test_breakers tests.test_itp_auto tests.test_light_schedule`.

Deploy only with the gate yes, and only while the server env leaves `ITP_AUTO_COMMANDS` unset or `0`. Confirm in the log that an armed dry tick prints `commands-off` and does not print `post`.

Turning `ITP_AUTO_COMMANDS` to `1` on the server is not part of this phase. It is a separate operator yes after at least one evening of armed dry lines that match what the operator would have done by hand. That yes is out of this plan's implementation phases. Record it in the progress file when it happens. Do not set it inside a deploy commit.

Landed 2026-11-22T21:06:00Z. The minute tick reads `ITP_AUTO_COMMANDS` and `ITP_AUTO_SLOT`. Missing or any value other than `1` stays off, so an armed dry tick still logs `commands-off` and does not GET or POST. With commands on, a fake client shows one heat status GET on an edge, one POST only when that read differs, no lighting id, no second path, no retry in the same quarter after a failed read, one confirm GET inside 60–150 seconds, and one timer-delete attempt that is not repeated until the next arm. A read that already matches the rule is remembered and does not disarm. The card says `Автоматичне керування: увімкнено` or `вимкнено`. `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule` passed, 100 tests. No deploy. `ITP_AUTO_COMMANDS` was not set on the server. Proof `verifiedAtUtc=2026-11-22T21:06:20.892Z`.

Rollback: set `ITP_AUTO_COMMANDS=0`, disarm, restart. Pending cloud state is whatever the last command did; the loop will not send another. Revert the commit if the POST helper itself mis-fires. Do not delete `breaker_sample` rows.

## 8. Data, migrations, compatibility

No new table. No `ALTER`. `init_db` is unchanged.

`kv` key `itp_auto` appears on first write. Old servers without the key behave as disabled.

`ITP_AUTO_COMMANDS` missing or any value other than `1` is off. `ITP_AUTO_SLOT` missing or any value other than `quarter` is `edge`.

Existing `breaker_day` rows stay. Arming reads the latest `itp` row and does not rewrite it.

`boiler_schedule` is read-only for this plan.

Rollback does not need a down migration. Delete the `kv` row only if a bad document must be forgotten. Disarm is enough for a normal rollback.

The public dashboard keeps working when the document is missing or invalid JSON. Invalid JSON is treated as the default disabled document, and one error line is logged. The card then shows `Керування: ручне.`

## 9. Verification strategy

Local, before any deploy:

- `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule`
- Phase 5 fake client counts, including the negative "no minute retry" and "no lighting POST"

On the server, after a deploy the operator asked for:

- Footer commit hash matches the deployed commit.
- Service is active.
- Heat card shows the line. Lighting card does not gain one.
- `/admin` arm and disarm work for the admin key.
- A non-admin dashboard key does not get the admin control.
- While `ITP_AUTO_COMMANDS` is not `1`, the log has no `itp-auto: post` and the heat breaker's switch does not change because of this deploy.
- Quarter-hour samples for both breakers still arrive.

Definition of done for this plan's code: Phases 1–5 landed, commands env still off on the server, tests green, card and admin match section 6, lighting path untouched. Live commands are a later operator yes, not a silent default.

Browser: after each deploy that changes the card or `/admin`, open the dashboard and the admin page and use the arm control. A screenshot of the card alone is not the check. Confirm disarm stops at the document and does not POST.

## 10. Risks, open questions, decisions

### Risks

- A hand change between minute ticks is invisible until the next sample or until the single pre-command GET. A desired edge in that gap can still POST once and undo the hand. The pre-command GET exists to see the hand first. If that GET fails, the loop does not POST (6.3). The hand wins until the next paid sample, which then disarms if it disagrees with `applied`.
- `breaker_shown_on` treats any non-zero watt sum as on. A phase that stays at hundreds of watts after an off command keeps the breaker "on" until it falls to a zero sum. `pending` covers that. It is not a manual pause.
- The pumps can still move four times in one hour before this guard turns the program off. The fifth command is the one that must not be sent.
- A command that is still pending after the confirm window is not a hand. At 20 minutes, clear pending, set an unconfirmed warn, and leave the program enabled. A deaf cloud is not a flap and is not a hand.
- The default 18:00–24:00 window turns the heat breaker on during an outage when no notice arrived. The card must say the window is the default. That spend is the operator's rule from 2026-11-22, not an accident.
- Cloud timers that are left in place during dry arming can still move the breaker. The card says commands are off. Timer delete waits until commands are actually enabled.
- `check_admin` is the env/db label `admin` only. Another resident key cannot arm the loop. That is intentional.

### Open questions

None that block Phases 1–5. The notice "boiler is off today" is a non-goal until the operator wants the parser changed. Recommended default stays: no row means 18:00–24:00.

### Decision log

| When | Decision |
|---|---|
| 2026-11-18T10:20:00Z | Operator rule, restated in this chat on 2026-11-22: heat follows actual city power with 15 minutes, or an open boiler window. A missing boiler notice means 18:00–24:00. A hand change disarms the loop. The card shows the mode. Admin can arm and disarm. |
| 2026-11-09T19:55:00Z | Quarter-hour poll is the steady Tuya read. Minute polling does not fit the trial pack. Inherited from `plan_breakers.md`. Not reopened. |
| 2026-11-22T18:40:00Z | The minute loop is local arithmetic only. An extra status read is allowed once per real edge, not once per minute, and not as a 20s/60s pair. A failed read is not retried before the next paid sample. |
| 2026-11-22T18:46:30Z | Skin A is the default. Skin B is `ITP_AUTO_SLOT=quarter`. Skin C is rejected. `ITP_AUTO_COMMANDS` defaults to `0`. The public page gets no direct switch. |
| 2026-11-22T18:48:00Z | self-review round 1. Two contract holes fixed in this same draft: settle must take `_breaker_lock` only after `apply_breaker_status` has released it, and Skin B may POST only from the poll that already holds the `itp` payload. `slot_spent` is a quarter index, not a minute index. No CRITICAL or HIGH left. |
| 2026-11-22T18:54:00Z | Operator: confirm a direct switch the way a one-shot timer is already confirmed. One `itp` status GET, once, from 60 seconds after the POST through the next 90 seconds. Same constants as `breaker_timer_followup_due`. Not a full poll of both breakers. The quarter-hour sample stays the backup. Proof `verifiedAtUtc=2026-11-22T18:53:43.452Z`. |
| 2026-11-22T18:58:00Z | Lead review, before the critic. The existing `_breaker_step` returns unless a quarter mark or a timer follow-up is due. Decide and confirm now run before that return, or they would never run. Status `REVIEW IN PROGRESS`. Proof `verifiedAtUtc=2026-11-22T18:56:27.456Z`. |
| 2026-11-22T19:05:00Z | Critic round 1, model `grok-4.7-xhigh-fast`, verdict CHANGES REQUIRED, CRITICAL 0, HIGH 3, MEDIUM 4, LOW 2. All three HIGH and all four MEDIUM fixed. LOW 8 fixed (Phase 3 names the early-return site). LOW 9 rejected: a sample that still equals the old `applied` after 20 minutes means the command did not land. Clearing `pending` and leaving `enabled` true is the deaf-cloud rule. Disarming there would stop the loop on every lost command. |
| 2026-11-22T19:12:00Z | Critic round 2, same model, CHANGES REQUIRED, CRITICAL 0, HIGH 2. An empty `timers_cleared_at` now returns `none` from step 8, and the commands-on wake copies `applied` and deletes timers before `step_itp`. Phase 2 disarm matches step 6, including the three negatives. |
| 2026-11-22T19:16:00Z | Critic round 3, same model, CHANGES REQUIRED, CRITICAL 0, HIGH 1. A failed timer delete must not run again every 30 seconds. `timer_delete_attempted` stops the retry until the next arm. This fix is not re-reviewed. Status `BLOCKED AT REVIEW CAP`. |
| 2026-11-22T19:24:00Z | Operator authorized a new review cycle. Proof `verifiedAtUtc=2026-11-22T19:23:19.013Z`. Section 6.6 now matches 6.7: one timer-list and one DELETE per arm, attempt flag set before the call, a failure does not retry on the next wake. Status `REVIEW IN PROGRESS`. |
| 2026-11-22T19:28:00Z | Critic round 1 of the new cycle, model `grok-4.7-xhigh-fast`, CHANGES REQUIRED, CRITICAL 0, HIGH 1. Disarm was clearing `timer_delete_attempted`, so the next wake called the timer API without a new arm. Only arm clears the flag. |
| 2026-11-22T19:32:00Z | Critic round 2, same model, APPROVE, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Disarm leaves the attempt flag set. The wake after disarm makes no timer call and no switch POST. Status `REVIEWED / READY FOR LOCAL WORK`. Local implementation is allowed only after an explicit phase yes. |
| 2026-11-22T19:51:00Z | Operator, after that approve: if the program has sent 4 or more switch commands in the last 60 minutes, log it and disarm. Do not send a fifth. Status reads, confirm reads, timer deletes, rejected commands, and dry-run lines do not count. Arm does not wipe the timestamps. Proof `verifiedAtUtc=2026-11-22T19:50:06.085Z`. |
| 2026-11-22T19:58:00Z | Flap-guard review, model `grok-4.7-xhigh-fast`. Round 1 CHANGES REQUIRED, HIGH 1: Skin B could still POST a fifth command. Step 8 now refuses both skins when four stamps are already in the hour. Round 2 APPROVE, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. |

## 11. Progress log

| When | What |
|---|---|
| 2026-11-22T18:42:32Z | Catalog: power-monitor is not indexed. |
| 2026-11-22T18:43:35Z | Plan mutation proof exact for this composer. |
| 2026-11-22T18:43Z | Harvest A–G. No repo hits. Disk drill-down of the breaker poll, the card, admin kv, boiler rows, and the paused lighting timers. |
| 2026-11-22T18:46:30Z | Plan and progress written. Status set after the self-review below. No code. |
| 2026-11-22T18:48:00Z | self-review round 1. Fixed a non-reentrant lock deadlock if settle ran inside `apply_breaker_status`, a missing Skin B POST site, and the `slot_spent` unit. Phase 4 card sentence stays pointed at from section 6.8. No second round. Independent review has not run. |
| 2026-11-22T18:54:00Z | Command confirm. Section 6.5 now uses the timer follow-up window for one `itp` status read after a POST. |
| 2026-11-22T18:58:00Z | Lead review. Early-return hole, failed-POST pending, and confirm/settle race fixed in sections 6.3, 6.5, and 6.7. Status `REVIEW IN PROGRESS`. Critic not yet run. |
| 2026-11-22T19:05:00Z | Critic round 1 (`grok-4.7-xhigh-fast`): CHANGES REQUIRED, 0 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW. Fixes in the plan. LOW 9 rejected in the decision log. |
| 2026-11-22T19:12:00Z | Critic round 2, same model: CHANGES REQUIRED, 0 CRITICAL, 2 HIGH. Step 8 returns `none` while `timers_cleared_at` is empty. Phase 2 disarm uses step 6. |
| 2026-11-22T19:16:00Z | Critic round 3, same model: CHANGES REQUIRED, 0 CRITICAL, 1 HIGH. Failed timer delete is one attempt, then `timer_delete_attempted` blocks another Tuya call until the next arm. Not re-reviewed. Status `BLOCKED AT REVIEW CAP`. |
| 2026-11-22T19:28:00Z | Critic round 1 of the new cycle, model `grok-4.7-xhigh-fast`, CHANGES REQUIRED, CRITICAL 0, HIGH 1. Disarm was clearing `timer_delete_attempted`. Only arm clears the flag. |
| 2026-11-22T19:32:00Z | Critic round 2, same model: APPROVE, 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW. Status `REVIEWED / READY FOR LOCAL WORK`. |
| 2026-11-22T19:58:00Z | Flap-guard review (`grok-4.7-xhigh-fast`). Round 1 HIGH 1: Skin B could POST a fifth command. Step 8 now refuses both skins. Round 2 APPROVE, 0 CRITICAL, 0 HIGH. |
| 2026-11-22T20:07:00Z | Phase 1 landed. `desired_itp` decides on, off, or hold from the light fact and the boiler window. 15 tests passed. No HTTP and no database. Phase 2 waits for an explicit yes. |

## 12. Handoff for a new Cursor dialog

Start at Phase 1. Do not start Phase 2 in the same turn as Phase 1. Stop at the human gate.

Read this file and `plan_itp_auto_PROGRESS.md` completely before editing. Disk wins over this chat. Company KB does not contain this repo. If the KB MCP is down, do not block Phase 1: the harvest above is the record, and this repo must not be written into that KB. If a later phase seems to need a KB write, stop and ask.

Active skin: Skin A. Do not implement Skin C. Do not set `ITP_AUTO_COMMANDS=1` unless the operator says so in a separate yes after Phase 5 is deployed with commands still off.

Do not edit `plan_breakers.md`. Do not clear `LIGHT_SCHEDULE_PAUSED`. Do not POST to `svitlo`. Do not put secrets or device ids in git, logs, or the KB.

Code, tests, and commit messages stay English. The card and admin sentences stay the Ukrainian in section 6.8.

Update both this file and the progress file at every gate, with a DateTime.

Known blockers: none. Part 1 is already live. The next new work is Part 2 below. Do not restart Part 1.

## Part 2 — Heat journal

Status of this part: `REVIEWED / READY FOR LOCAL WORK`. Do not start J1 without an explicit yes.

### 2.1 Goal and non-goals

Goal: keep two facts, and show the whole selected day when the operator taps the `Обігрів` lane.

- The program turned the heat breaker on or off.
- Control changed between manual and automatic, and why.

Non-goals:

- Do not add these rows to the city-power table `power_events` or to the block titled `Події`. That block stays `Пропало` / `З'явилось` plus voltage, with the schedule column and the duration column.
- Do not log a row on every minute decision, every status GET, a rejected POST, a timer delete, or a lighting-breaker action.
- Do not send Telegram for these rows.
- Do not backfill history from the service journal. The list starts empty.
- Do not change `ITP_AUTO_COMMANDS`. It is already `1` in the server `.env` only. Do not copy that value into git.
- Do not add a public switch button. Do not clear `LIGHT_SCHEDULE_PAUSED`. Do not POST to `svitlo`.
- Do not draw marks on the lane. Class `brk-journal-pin` must not exist. The colored bar already shows on and off.
- Do not make `Графік 5.1`, `Фактично`, `Заряд`, `Освітлення`, `Котельня`, or `Тривога` open this list. Only `Обігрів` does.

### 2.2 Context harvest

Repo Memory catalog at 2026-11-22T21:52:57Z has nine repos. `power-monitor` is absent. Disk is the source of truth. Company KB searches were run and did not return this repo. No ids from those searches are used as implementation paths. Do not copy unrelated tokens from those hits into this file.

Self-check:

- [x] knowledge search ran. No power-monitor path.
- [x] ideas search ran. No power-monitor path. Idea 279 (one ledger, do not invent a second events table) is a KB product rule, not this SQLite app. Here a second table is required because `power_events` is the city-light timeline.
- [x] code_directories search ran. No power-monitor path.
- [x] code_files search ran. No power-monitor path.
- [x] code_symbols search ran. No power-monitor path.
- [x] jira and dialogs searches ran. No ticket and no dialog for this journal.
- [x] Disk drill-down of the files below.
- [x] 2026-11-22T22:05:52Z catalog again: nine repos, `power-monitor` absent, `git_only_repos` is only `lazy-ai`. `kb_rule('project_memory')` was not loaded. That rule is for the `knowledge_base` repo.

Place revision, searches at 2026-11-22T22:05Z, topic "click the heat lane to show that day's journal":

| Volume | Mode | Result |
|---|---|---|
| knowledge | semantic | 12 hits, none this repo. Top ids 1041, 1039, 1024, 1054, 1037, 1040 are the daily secretary briefing. |
| ideas | semantic | 12 hits, none this repo. Top ids 293, 310, 368, 516, 321, 311 are other products. Do not copy them. |
| code_directories | semantic | 10 hits, none this repo. Top paths are invoice `templates/admin` and knowledge-base `apps/web/src/app/(app)/admin`. |
| code_files | hybrid | `total_fts_hits` 0, then semantic fallthrough. No `paintBreakers` and no `power-monitor` path. |
| code_symbols | hybrid | No `paintBreakers`. Returned `_read`, `readJumpClip`, `read_widgets` in other repos. |
| jira | fts | No ticket. Returned KB-336, KB-348, HEED-2, KB-13, KB-195, KB-325. |
| dialogs | hybrid | `total_fts_hits` 0. Top ids 7858, 2016, 7377, 8231, 6383, 8142 are other products. |

Disk drill-down for this revision: `static/app.js` `paintBreakers` (replaces `#pm-breakers-board`), `pmRefreshBreakers` (called when `#pm-breakers-live` changes, and every 60 seconds for today), `.brk-help` capture listener, `breakerTimerPins`. `power_monitor.py` `_breaker_bars_html` and `_breaker_section_html`. `database.py` `read_breaker_board`. `static/style.css`: `.brk-lane` is 16px with `overflow: hidden`. `.brk-when-pin` is an `<i>` on `.brk-lane-wrap`, `top: -4px`, `height: 26px`, `z-index: 4`. It is not a button.

| Path | Why it matters | Touch |
|---|---|---|
| `power-monitor/database.py` `init_db`, `save_event`, `recent_events`, `read_breaker_board` | `power_events` is the city-light table. The board payload is the day the chart already loads. | Add `itp_journal`, `append_itp_journal`, and `itp_journal_for_day`. Put that day's rows on the payload. Do not change `save_event`. |
| `power-monitor/power_monitor.py` `_build_update_fragments` around the `Події` table | Events block must stay untouched. | Do not append a journal list in the live fragment. |
| `power-monitor/power_monitor.py` `_breaker_bars_html`, `_breaker_section_html` | First paint of the lanes, and the node `paintBreakers` does not replace. | Heat lane becomes the button. The day list sits after `#pm-breakers-board`. Do not move the help text. |
| `power-monitor/static/app.js` `paintBreakers`, `pmRefreshBreakers` | The board the operator sees. `innerHTML` replace wipes anything inside the board. | Same heat-lane button. Refill the outside list when it is open. |
| `power-monitor/static/style.css` `.brk-lane`, `.brk-when-pin`, `.brk-help-pop` | 16px bar, timer pins, the info panel. | Hit box on the heat lane only. New class `brk-journal-pop` in normal flow. Do not reuse `brk-help-pop`. |
| `power-monitor/itp_auto.py` `mutate_itp_auto`, `apply_post_result` | Mode flips and post results already happen here. | Call the journal writer after a real transition. |
| `power-monitor/tuya_breakers.py` `_confirm_itp_command`, `settle_itp_after_sample` | These two are the only places a pending command becomes a matched sample. | Call `mark_itp_journal_confirmed` from each, in its own try. Do not write the switch row from `_emit_post`. |
| `power-monitor/api/admin.py` `set_itp_armed` | Arm and disarm already mutate `enabled`. | No extra route. The shared writer sees the flip. |
| `power-monitor/tests/test_itp_auto.py`, `tests/test_breakers.py` | Temp sqlite pattern already exists. | Add journal tests. |

### 2.3 Current reality

The control loop is live. `ITP_AUTO_COMMANDS=1` is in the server `.env` only, since 2026-11-22T21:33:00Z. The heat card shows `Керування` as `ручне` (red, class `brk-mode-off`) or `автоматичне` (green, class `brk-mode-on`). A muted note under the meters says why.

Service logs such as `itp-auto: post on` and `itp-auto: admin arm` are not stored in SQLite and disappear when the journal rotates. The dashboard cannot show them.

`recent_events` reads `power_events`. The `Події` table labels are only `down`, `up`, and the voltage events. A new event name there would get a schedule cell and a duration cell that do not mean anything for the heat breaker.

### 2.4 Skins

Skin J-G, default since 2026-11-22T22:08:00Z. The same append-only table `itp_journal`. The `Обігрів` lane is one button. A tap opens the list of that selected day. No marks. No second list under the cards.

Skin J-A. Marks on the `Обігрів` lane, one popover per mark or per cluster. Superseded 2026-11-22T22:08:00Z. The operator asked why the marks exist when a tap on the heat line can show the whole day. The colored bar already shows on and off.

Skin J-B. Insert new event names into `power_events` and render them in `Події`. Rejected. It mixes the city-light timeline with the heat breaker and breaks the schedule and duration columns.

Skin J-C. Append a JSON list onto the `itp_auto` kv document. Rejected. That document is the control state. An unbounded list races with the command lock and is the wrong place for history.

Skin J-D. A text section `Журнал обігріву` under the cards. Superseded 2026-11-22T21:59:00Z. It repeats what the colored lane already shows and adds a second thing to read.

Skin J-E. Tap anywhere on the time lanes, or tap one minute. Rejected. Six of the seven lanes are not this journal. A finger cannot hit one minute on a 16px bar. This skin is not "tap the heat lane". That is J-G.

Switch: implement J-G only. There is no env flag. Removing the feature is removing the heat-lane button and the list, and leaving the table in place.

### 2.5 Recommended architecture

```sql
CREATE TABLE IF NOT EXISTS itp_journal (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL,
    reason    TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_itp_journal_ts ON itp_journal(ts);
```

`kind` is `switch-on`, `switch-off`, `mode-auto`, or `mode-manual`.

`reason` is `boiler`, `light-on`, `light-off`, `admin`, `hand`, or `flap`.

`confirmed` on a switch row stays 0 until a sample matches `pending.state`. A POST body `success: true` is not that match. `apply_post_result` still sets `pending` on success and on transport, and it does not set `applied`. The card already says `Команда ще не підтверджена.` while `pending` is set. The journal uses the same meaning: the suffix `ще не підтверджено` stays until the match. A rejected POST writes no row. A 20-minute unconfirmed warn does not delete the row and does not set `confirmed=1`.

Mode rows pass `confirmed=1`. They are a fact about the flag, not a cloud sample. `mutate_itp_auto` compares the document before and after `update`. `kv_set` runs first. Journal inserts run after that write, in this order, each in its own try. A journal error is logged and the saved document is still returned. Do not insert before `kv_set`.

1. Switch row, only when `pending` goes from empty to a state. `confirmed=0`. Kind is `switch-on` or `switch-off` from that state. Reason is `last.reason` when it is `boiler`, `light-on`, or `light-off`. Otherwise store `admin`. `_emit_post` does not write a second switch row.
2. Mode row, when `enabled` changed, after the switch row if both happened.

The live pause reason is `manual` or `flap` (`itp_auto.py` `_manual_disarm` and `_disarm_flap`). The journal does not store `manual`. Map the document after the update:

- `enabled` false to true: `mode-auto` / `admin`. `arm_itp` is this path.
- `enabled` true to false and `pause.reason == "manual"`: `mode-manual` / `hand`.
- `enabled` true to false and `pause.reason == "flap"`: `mode-manual` / `flap`. `_disarm_flap` can run inside `apply_post_result` on the fourth counted command, in the same update that sets `pending`. The switch row is inserted first, then this mode row. `itp_journal_for_day` orders by `ts ASC, id ASC`, so the switch sentence stays above the flap sentence.
- `enabled` true to false otherwise: `mode-manual` / `admin`. `disarm_itp` leaves `pause` as it was. After an arm, `pause` is null, so an admin disarm is `admin`.
- `enabled` unchanged: no mode row.

Do not pass `pause.reason` straight into `append_itp_journal`. `manual` is not a journal reason. `itp_journal_line` never raises on a stored row.

Confirm sets `confirmed=1` only when a pending command matches the sample, and only after that `kv_set`. Both match sites call `mark_itp_journal_confirmed(state)` from their own try. A raise there must not escape `settle_itp_after_sample`, because that function runs inside `poll_breakers` with no local try of its own.

- `tuya_breakers.py` `_confirm_itp_command`, the `apply` callback, when `shown == pending.state`.
- `tuya_breakers.py` `settle_itp_after_sample`, when `actual == pending.state`.

The helper loads the newest row of that switch kind (`switch-on` for `on`, `switch-off` for `off`). If that row has `confirmed=0`, set it to 1. If that newest row is already 1, do nothing. Do not walk back to an older unconfirmed row. It does not touch mode rows. Clearing `pending` is not itself a confirm. `disarm_itp` clears `pending` and must leave `confirmed` alone. The 20-minute branch in `settle_itp_after_sample` clears `pending`, sets `warn.kind` to `unconfirmed`, and does not set `confirmed=1`.

A journal insert runs after the control write, in its own short connection. On failure, log `itp-auto: journal <ExceptionName>` and continue. A journal error must not skip the switch, the confirm, or the quarter poll.

Ukrainian, one line, no device id:

| kind | reason | confirmed | Line |
|---|---|---|---|
| switch-on | boiler | 1 | Обігрів увімкнено автоматично, котельня |
| switch-on | light-on | 1 | Обігрів увімкнено автоматично, світло вже 15 хв |
| switch-on | admin | 1 | Обігрів увімкнено автоматично |
| switch-off | light-off | 1 | Обігрів вимкнено автоматично, світла немає 15 хв |
| switch-off | admin | 1 | Обігрів вимкнено автоматично |
| switch-on or switch-off | any | 0 | the same line plus ` ще не підтверджено` |
| mode-auto | admin | 1 | Керування стало автоматичним |
| mode-manual | admin | 1 | Керування стало ручним |
| mode-manual | hand | 1 | Керування стало ручним, перемкнули руками |
| mode-manual | flap | 1 | Керування стало ручним, за годину вже 4 перемикання |

One function, `itp_journal_line(kind, reason, confirmed)`, lives in `itp_auto.py` and returns the Ukrainian sentence. It does not include the clock and it does not import HTTP. `read_breaker_board` calls it. JavaScript does not keep a second copy of the sentences. A stored switch row whose reason is not in the table uses the `admin` sentence for that kind. The function does not raise on a stored row.

`itp_journal_for_day(day)` returns `(rows, truncated)`. A row belongs to `day` when `kyiv_date_str(ts)` is that date. Use `config.UA_TZ`, the same clock as `kyiv_day_bounds`. Do not use `datetime.utcfromtimestamp` and do not slice on the UTC date. A row at 00:30 Europe/Kyiv belongs to that Kyiv chart day. `rows` is `ORDER BY ts ASC, id ASC`, at most 200. `truncated` is true only when older rows of that same Kyiv day were left out. The page then adds one last line, `Старіші записи цієї доби не показано.` A normal day stays under the cap because the flap guard stops the program at 4 switch commands an hour.

`read_breaker_board` adds `journal` and `journal_truncated` for the requested day. `ep_breakers` already returns that dict as JSON, so `api/dashboard.py` needs no new route. Call `itp_journal_line` from inside `read_breaker_board`, the same way it already imports `tuya_breakers` inside the function. Do not import `itp_auto` at the top of `database.py`. The journal read has its own try. On failure, log `itp-auto: journal <ExceptionName>` and return `journal: []` with `journal_truncated: false`. Do not let that exception leave `read_breaker_board`. `_breaker_live_html` turns any exception from this function into an empty fragment, which blanks the meter cards. Each item is `{ts, clock, text}`. `clock` is `HH:MM` in Europe/Kyiv. `text` is `itp_journal_line`. The page prints `clock`, a space, then `text`, through DOM text nodes. Do not put `text` into `innerHTML`. Rows outside the selected day stay in the table and are not sent. `journal_truncated` true adds the cut line after the rows.

The button. In `_breaker_bars_html` and in `paintBreakers`, the `itp` track is the only one with `<button type="button" class="brk-journal-hit">` wrapping `.brk-lane`. `aria-label` is `Події обігріву за цю добу`. `aria-controls` is `brk-journal-pop`. `Освітлення` and the other lanes stay plain divs. The visible `.brk-lane` stays 16px tall with `overflow: hidden`. The button is in normal flow: `display: flex; align-items: center; width: 100%; min-height: 32px`, transparent, `cursor: pointer`, no negative offset. The heat row grows. The button must not cover `Котельня`. The heat pin stays a sibling of the button, not a child of `.brk-lane`, because that lane clips overflow. Set the pin `top` so the 26px pin stays centered on the 16px bar inside the grown wrap. `pointer-events: none` on that pin, so a tap still hits the button. Lighting pins are unchanged. Do not add `brk-journal-pin`.

The list. `#brk-journal-pop` is the next sibling of `#pm-breakers-board`, inside `#breaker_details`, hidden until a tap. It is in normal flow under the chart. Its class is `brk-journal-pop`, not `brk-help-pop`. Copy the dark colors from `.brk-help-pop`. Do not copy `position: absolute`. The help listener in `static/app.js` treats every `.brk-help-pop` as the info panel. `paintBreakers` sets `breakerBoard.innerHTML`, and `pmRefreshBreakers` runs when `#pm-breakers-live` changes and again every 60 seconds for today. A list inside the board would close on that replace.

Open and close. One capture-phase click listener, the same pattern as `.brk-help`: `preventDefault` and `stopPropagation`. A tap on `.brk-journal-hit` toggles. A tap on `.brk-help` closes this list. A tap on this list closes `.brk-help-pop`. Esc closes this list first when it is open, then the help pop. A tap outside closes it, except `#brk-prev` and `#brk-next`. A module flag `journalOpen` survives the board replace. At the end of `paintBreakers`, if the flag is set, refill `#brk-journal-pop` from `data.journal` and set the new button's `aria-expanded` to true. If the flag is clear, the repaint leaves the list hidden. Before the first payload arrives, a tap does nothing.

Order and the empty day. Sentences are oldest first, one paragraph each. An empty `journal` still leaves the heat lane clickable, because the colored bar is there. The list then says `За цю добу записів немає.` Changing day with `‹` `›` while the list is open keeps it open and shows that day.

### 2.6 Phases

Human gate after each phase. Do not start the next phase in the same turn. Do not deploy unless that same yes includes deploy. Do not put `#автооновити` in a commit unless the yes includes deploy.

#### Phase J1 — table and helpers

Goal: create the table and the read/write helpers. No page change. No new log line from the live loop.

Touched: `database.py` (`init_db`), `tests/test_itp_auto.py`.

Steps: `CREATE TABLE IF NOT EXISTS` inside `init_db`. `append_itp_journal(ts, kind, reason, confirmed=0)` and `itp_journal_for_day(day) -> (rows, truncated)`, ordered by `ts ASC, id ASC`, cap 200. Mode callers pass `confirmed=1`. Switch callers pass `confirmed=0`. Reject an unknown kind or reason without writing. `itp_journal_line` covers every row of the sentence table, including the unconfirmed suffix and the `admin` switch lines. A stored switch reason outside the table still returns the `admin` sentence and does not raise.

Verification: temp sqlite. Two rows on the same Kyiv day come back oldest first with `truncated` false. A row whose UTC date is the previous day but whose Kyiv time is 00:30 is included. A row on the next Kyiv day is absent. Row 201 of one Kyiv day sets `truncated` true and the returned rows are the latest 200, still oldest first. An unknown kind raises and leaves the table unchanged. `power_events` stays empty.

Landed 2026-11-22T22:34:00Z. `JournalStoreTests` passed. The table is created by `init_db` and nothing in the live loop calls it. `itp_journal_line` lives in `itp_auto.py` and is not wired to a writer yet. One pre-existing failure in `test_hidden_flag_removes_the_section` rejected every `<button`, including the info button that has been on the page since 2026-11-22. That assertion now allows exactly that one button. No deploy. Phase J2 has not started. Proof `verifiedAtUtc=2026-11-22T22:32:17.637Z`.

Rollback: stop calling the helpers. The empty table may remain.

Deploy: no.

#### Phase J2 — write the rows

Goal: the live transitions create rows. The page still does not show them.

Touched: `itp_auto.py` (`mutate_itp_auto`), `tuya_breakers.py` (`_confirm_itp_command` and `settle_itp_after_sample`), tests.

Steps: after `kv_set`, write the switch row and then the mode row as in 2.5. `_emit_post` does not insert a journal row. `mark_itp_journal_confirmed` runs from both match sites, each in its own try.

Verification, temp sqlite, no network:

- arm then disarm writes `mode-auto` then `mode-manual` / `admin`. A second arm while already armed writes nothing.
- a disarm whose saved `pause.reason` is `manual` writes `mode-manual` / `hand`. The test must not store the journal reason `hand` in `pause`. A flap disarm writes `mode-manual` / `flap`.
- `success` and `transport` each write one switch row with `confirmed=0`. `rejected` writes none. A matching confirm in `_confirm_itp_command` sets that row to 1. The same row is also set to 1 when only `settle_itp_after_sample` sees the match. `disarm_itp` clearing `pending` leaves `confirmed` at 0. The 20-minute unconfirmed branch leaves `confirmed` at 0.
- an older transport row with `confirmed=0`, then a newer success row of the same kind with `confirmed=0`, then a match: only the newer row becomes 1. The older row stays 0.
- the fourth counted command writes the switch row and then the flap mode row. `itp_journal_for_day` returns the switch sentence first.
- a hold tick and a disabled tick write nothing.
- a test that plants `enabled` through `mutate_itp_auto` is a real transition and does write a mode row. A fixture that must not write uses `kv_set` directly.
- a raised insert is caught. The document update still sticks. A raised confirm update does not leave `settle_itp_after_sample`.

Landed 2026-11-22T22:40:00Z. `JournalWriteTests` and the three modules passed, 115 tests. A switch row is written after `kv_set` with `confirmed=0`. A mode row follows only when `enabled` changed. `manual` in the document becomes `hand` in the journal. Both match sites call `mark_itp_journal_confirmed`, and a failure there does not leave `settle_itp_after_sample`. The page still does not read the table. No deploy, so the running service is unchanged. Phase J3 has not started. Proof `verifiedAtUtc=2026-11-22T22:37:09.536Z`.

Rollback: remove the journal calls in `mutate_itp_auto`, `_confirm_itp_command`, and `settle_itp_after_sample`. Existing rows stay. Each of those calls is already inside its own try, so a partial revert cannot throw out of the quarter poll.

Deploy: no.

#### Phase J3 — day list on the heat lane

Goal: a tap on the `Обігрів` lane opens that day's sentences. The lane has no marks.

Touched: `database.py` `read_breaker_board`, `power_monitor.py` `_breaker_bars_html` and `_breaker_section_html`, `static/app.js` `paintBreakers`, `static/style.css`. `api/dashboard.py` only if `GET /api/breakers` does not already return `read_breaker_board` unchanged. Tests.

Steps: add `journal` as in 2.5. Put `brk-journal-hit` on the heat lane in the server HTML and in `paintBreakers`. Put `#brk-journal-pop` after `#pm-breakers-board`. Wire the toggle, the outside click, Esc, and the repaint refill. Do not edit the `Події` builder. Do not add an eighth lane. Do not add `brk-journal-pin`.

Verification: the heat track HTML contains `brk-journal-hit`. The lighting track does not. `#brk-journal-pop` is outside `#pm-breakers-board` and its class is `brk-journal-pop`, not `brk-help-pop`. A fixture at 09:15 and one at 18:00 produce `journal` oldest first, with `clock` `09:15` then `18:00`, and `journal_truncated` false. An empty day has `journal: []`, `journal_truncated` false, and the heat button is still present. A raised journal read still returns that empty payload and `_breaker_live_html` still renders the meter cards. `app.js` contains `brk-journal-hit`, fills the popover with text nodes, and does not contain `brk-journal-pin`. `tests/test_breakers.py` `test_bars_are_green_then_red_and_the_other_breaker_is_empty` and `test_page_script_does_not_reuse_the_fact_lane` today reject every `<button`. Update those two assertions so `brk-journal-hit` is the only new button. Any other `<button` in the bars HTML, on the lighting track, or in that script chunk still fails. `test_hidden_flag_removes_the_section` allows exactly one button, `brk-help`, since 2026-11-22T22:34:00Z. J3 makes that two: the info button and `brk-journal-hit`. The `Події` HTML does not contain `Обігрів увімкнено`. The info button still has `brk-help-pop` hidden. After a later deploy, the browser check is: tap the heat lane, read both sentences, tap `‹`, see that day, tap outside, the list closes, and a board refresh while the list is open does not close it.

Landed 2026-11-22T23:02:00Z. The heat lane is the only new button. The list sits after `#pm-breakers-board` and is filled with text nodes. An empty day and a failed journal read still leave the meter cards. 116 tests passed. Deployed 2026-11-22T23:04:00Z by pull and restart. The running commit is `c5bdc4b`. The public `app.js` and `style.css` contain `brk-journal-hit` and `brk-journal-pop`, and not `brk-journal-pin`. Table `itp_journal` exists. The keyed page tap was not driven from here. Proof `verifiedAtUtc=2026-11-22T23:05:22.381Z`. No further journal phase.

Rollback: remove the button and the pop. Rows remain in the table.

Deploy: no, unless the operator asks in the same yes.

### 2.7 Data and compatibility

No `ALTER` of `power_events`. `CREATE TABLE IF NOT EXISTS` runs from `init_db` on the next process start. Old servers gain an empty table. The control document `itp_auto` is unchanged.

Rollback does not delete rows. A bad sentence is a render change, not a data migration.

### 2.8 Verification and definition of done

Local: `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule`.

Done when J1–J3 have landed, a tap on the `Обігрів` lane lists that day's Ukrainian sentences from oldest to newest, an empty day says `За цю добу записів немає.`, and `Події` still shows only city light and voltage. Live commands stay as they are. Do not turn them off to test the list.

### 2.9 Risks and decisions

- A transport row can say the breaker switched before the confirm. The words `ще не підтверджено` are the honest state. Do not delete that row if the confirm disagrees. The mode row for a hand is a separate fact.
- Writing the mode row inside `mutate_itp_auto` sees every enabled flip, including ones added later. That is the point. It must not write when `enabled` is unchanged.
- The visible chart is `paintBreakers`. The heat-lane button must be in that function and in `_breaker_bars_html`. The list must stay outside `#pm-breakers-board`, or the next replace closes it.
- A 16px bar is a small thumb target. The heat row grows to at least 32px in normal flow. A negative offset would cover `Котельня`. The other lanes stay 16px.
- Timer pins on the heat lane are not buttons. `pointer-events: none` on those pins keeps the tap on the journal button. Lighting pins are unchanged.

| When | Decision |
|---|---|
| 2026-11-22T21:52:00Z | Operator: record automatic heat on/off and manual/automatic mode changes. Suggested the `Події` block. |
| 2026-11-22T21:53:00Z | Plan answer: a separate `itp_journal` list under the breaker cards. `Події` stays the city-light timeline. Skin J-A default. J-B and J-C rejected. |
| 2026-11-22T21:53:10Z | self-review round 1. Findings: a journal error must not block a switch; no backfill; no device id in the sentence; `CREATE TABLE IF NOT EXISTS` is the only migration. All four are written into 2.5 and 2.7. No second round. 0 CRITICAL, 0 HIGH left in this draft. |
| 2026-11-22T21:58:00Z | Operator: the journal should look light and easy. Pointed at the existing day lanes and asked whether a tap on the time bar should show the day. |
| 2026-11-22T21:59:00Z | Supersedes the list under the cards. Marks on the `Обігрів` lane, popover on tap. A tap on empty lane is rejected. Proof `verifiedAtUtc=2026-11-22T21:59:06.870Z`. |
| 2026-11-22T21:59:06Z | self-review round 2. HIGH if marks lived only in server HTML, because `paintBreakers` replaces the board. Fixed in 2.5. Cluster rule added. 0 CRITICAL, 0 HIGH left. |
| 2026-11-22T22:04:00Z | Operator: do not use marks. A tap on the `Обігрів` line should show the whole day. |
| 2026-11-22T22:08:00Z | Skin J-G replaces J-A. One button, the heat lane. The list is that day, oldest first. Empty day still opens and says there are no rows. Proof `verifiedAtUtc=2026-11-22T22:04:58.446Z`. |
| 2026-11-22T22:08:00Z | self-review round 3. HIGH if the list lived inside `#pm-breakers-board`: `paintBreakers` and `pmRefreshBreakers` would close it. HIGH if the reader kept only the newest 20: the morning of a long day would disappear. Both fixed in 2.5. The heat row grows in normal flow to at least 32px. It does not use a negative offset, because that would cover `Котельня`. `‹` `›` do not count as an outside tap. 0 CRITICAL, 0 HIGH left in that draft. |
| 2026-11-22T22:12:00Z | Lead review, before the critic. Proof `verifiedAtUtc=2026-11-22T22:10:44.991Z`. The live pause string is `manual`, not `hand`. A direct store of `manual` would be rejected and the hand row would vanish. Map `manual` to journal reason `hand`. Confirm is two sites: `_confirm_itp_command` and `settle_itp_after_sample`. `disarm_itp` and the 20-minute warn must not set `confirmed=1`. Day membership is `kyiv_date_str`, not the UTC date. Payload field `journal_truncated`. Popover text uses DOM text nodes. Review harvest at 22:11Z still has no `power-monitor` path: knowledge 1041, ideas 310, code_directories `assets/AdminComponents/BookeeperDashboard`, code_files `total_fts_hits` 0, code_symbols `read_widgets`, jira KB-336, dialogs 2953. Status `REVIEW IN PROGRESS`. |
| 2026-11-22T22:18:00Z | Critic round 1, model `grok-4.7-xhigh-fast`, CHANGES REQUIRED, CRITICAL 0, HIGH 2, MEDIUM 4, LOW 2. Both HIGH accepted. A success POST is `confirmed=0` until a sample matches, and the match updates only the newest row of that kind when that row is still 0. Switch row is written inside `mutate_itp_auto` before the mode row. `brk-journal-pop` is its own in-flow panel. Journal read failures stay inside `read_breaker_board`. The two button bans in `tests/test_breakers.py` allow only `brk-journal-hit`. |
| 2026-11-22T22:22:00Z | Critic round 2, same model `grok-4.7-xhigh-fast`, resumed, APPROVE, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. The eight round-1 fixes are in Part 2. Status `REVIEWED / READY FOR LOCAL WORK`. Local work starts at J1 only after an explicit yes. |

Open questions: none. The selected day already has `‹` `›`.

### 2.10 Handoff

Start at Phase J1 only after an explicit yes. Read this Part 2 and the progress file. Active journal skin is J-G. Do not implement J-A marks. Do not reopen Part 1. Do not edit `plan_breakers.md`. Do not set or clear `ITP_AUTO_COMMANDS` in git or on the server as part of these phases.

If the company KB MCP is down, do not block J1. The harvest in 2.2 is the record. Do not write this repo into that KB.

Code and commits stay English. The journal sentences stay the Ukrainian in 2.5.

Update this file and `plan_itp_auto_PROGRESS.md` at every gate, with a DateTime.

Status of Part 2 is live. Part 3 phase L1 is live at `f764d9b`.

## Part 3 — One legend per lane

Status of this part: phase L1 is `LIVE` at `f764d9b`. Parts 1 and 2 stay as they are.

Proof: composer `85ba10c3-3110-479d-ac13-0dddaf1132bc`, title `Write the ITP on-off rule`, `verifiedAtUtc=2026-11-22T23:13:52.524Z`.

### 3.1 Goal and non-goals

Goal: the shared color key under the seven lanes is hidden until a lane is opened. Each lane explains only its own colors. A small info mark beside the lane opens that same explanation. The heat lane still lists the day's journal under its colors.

Non-goals:

- Do not change how the heat breaker is switched. `ITP_AUTO_COMMANDS` stays as it is.
- Do not draw `brk-journal-pin` marks.
- Do not change the separate legend inside the Тривоги block. `paintAlertDay` in `static/app.js` keeps its own three words.
- Do not add a public on/off button.
- Do not write this part into the company knowledge base.

### 3.2 Context harvest

Catalog still has nine repos. `power-monitor` is not one of them. Disk is the source of truth.

Searches at 2026-11-22T23:14Z, topic "per-lane legend hidden until click":

| Volume | Mode | Result |
|---|---|---|
| knowledge | semantic | No power-monitor path. Top ids 994, 667, 455, 1047, 1035, 850, 885, 1007 are other products. |
| ideas | semantic | No power-monitor path. Top ids 516, 101, 352, 135, 335, 333, 244, 490. |
| code_directories | semantic | No power-monitor path. Top dir `assets/AdminComponents/BookeeperDashboard`. |
| code_files | hybrid | `total_fts_hits` 0. No `paintBreakers`. |
| code_symbols | hybrid | Empty. `fallback_applied=or_like`. |
| jira | fts | No ticket for this chart. Returned REFUND-11, KBNPPTX-451, KB-294, KB-385, RLT-40. |
| dialogs | hybrid | `total_fts_hits` 0. Top id 7830 is a different calendar legend. |

Disk drill-down: the shared key is the `.brk-legend` block at the end of `_breaker_bars_html` in `power_monitor.py` and the same block inside `paintBreakers` in `static/app.js`. `paintBreakers` replaces `#pm-breakers-board`, so a legend that exists only in the server HTML comes back on the next load. The heat lane is already `brk-journal-hit` and fills `#brk-journal-pop` outside that board. The section info button is `.brk-help`. The charge color is `soc_color` in `voltage_chart.py`, stops at 0, 25, 50, 75, 90, and 100. The alert-day legend is a different chart.

Self-check:

- [x] knowledge, ideas, code_directories, code_files, code_symbols
- [x] jira and dialogs
- [x] at least three disk paths: `power_monitor.py`, `static/app.js`, `static/style.css`, `voltage_chart.py`
- [x] `kb_rule('project_memory')` not loaded. That rule is for the knowledge_base repo.

### 3.3 Current reality

Under the seven lanes, one legend lists every color at once: light on with grid, light on from the battery, off, the 5.1 plan, the fact, the boiler, the three alert colors, and the now mark. `Заряд` is not in that list. Its bar is a gradient from `soc_color`.

Only `Обігрів` is a button. Its popover is the journal for the selected day. The other six lanes are not buttons. The section `i` explains the meter cards, not one lane.

### 3.4 Skins

Skin L-A, default. Remove the shared `.brk-legend` from both painters. Every lane is a button, and a small `i` beside the name is the same button. One popover shows that lane's colors. For `Обігрів`, the journal list stays under those colors.

Skin L-B. Leave the shared legend on the page and also add per-lane pops. Rejected. The operator asked for the legend to stay hidden until a lane is opened.

Skin L-C. Only the `i` opens the legend. The lane itself stays inert, except the heat journal. Rejected. The lane and the `i` do the same thing.

Switch: implement L-A only. There is no env flag. Removing it puts the shared legend back and restores `brk-journal-hit` as the only lane button.

### 3.5 Recommended architecture

One popover, `#brk-lane-pop`, class `brk-lane-pop`, the next sibling of `#pm-breakers-board`. It replaces `#brk-journal-pop`. Do not keep both, or two panels can open at once. It uses text nodes, not `innerHTML`, for the words. Named color swatches use the existing `.brk-key` classes. Pop rows may keep `brk-legend-item`. The charge swatches do not use a class per stop: `soc_color` in `voltage_chart.py` and `socColor` in `static/app.js` return a hex. Draw those six as inline backgrounds.

The seven lanes are not built in one loop. On the server, `Графік 5.1`, `Фактично`, `Заряд`, `Котельня`, and `Тривога` all go through `_lane_html`. `Освітлення` and `Обігрів` are the loop in `_breaker_bars_html`. In `static/app.js`, the first five go through `breakerLane`. The last two are the `svitlo` / `itp` branch inside `paintBreakers`. Both builders must emit the buttons. Editing only the heat branch leaves five lanes without a legend.

Every lane from those builders:

- The bar is `<button type="button" class="brk-lane-hit" data-lane="...">`. The visible bar stays 16px. The button is 16px tall, the same as the bar, in normal flow, with no negative offset. `aria-controls` is `brk-lane-pop`.
- The name and the info mark share one wrapper, and that wrapper is the first grid cell: `<button type="button" class="brk-lane-info" data-lane="...">i</button>`. The glyph is small. The box is 16 by 16, the same height as the bar, and it sits on the right edge of the label cell so the seven marks form one column beside the bars. The name stays on the left. It is not `.brk-help`. Do not add a third grid child. A third child drops the bar onto the next row.
- `data-lane` is `plan`, `fact`, `charge`, `light`, `heat`, `boiler`, or `alert`.

The label column stays aligned with the hour pad. One custom property, `calc(5.2rem + 16px + 0.25rem)`, is on `.brk-track`, on `.brk-chart:not(.alert-day) > .brk-hours`, and on `.brk-hours-pad`. The name and the button sit in that first cell. The name keeps the left side. The 16px info mark is pushed to the right edge, next to the bar. Do not change `.alert-day .brk-hours`. Under 640px the track is already one column and the pad is hidden; the name stays left and the `i` stays on the right of that row.

`brk-journal-hit` goes away. The heat bar uses `brk-lane-hit` with `data-lane="heat"`. The capture listener that today matches `.brk-journal-hit` matches `.brk-lane-hit` and `.brk-lane-info` instead.

Timer pins exist only on `Освітлення` and `Обігрів`. They are `<i class="brk-when-pin">`, not buttons. Each pin is a sibling of the lane button, outside `.brk-lane`, because that lane is `overflow: hidden`. Set `pointer-events: none` on the pins in `.brk-lane-slot`. The hit is 16px, the same as the bar, so the 26px pin uses `top: -5px` and stays centered on that bar. Hour lines and `.brk-now` already ignore the pointer.

Opening. Store the open lane id on `#pm-breakers-board` as `_laneOpen`: `plan`, `fact`, `charge`, `light`, `heat`, `boiler`, `alert`, or `""`. A boolean cannot choose the words once seven lanes share one pop, and `querySelector('.brk-lane-hit')` would mark the first bar. A click on `.brk-lane-hit` or `.brk-lane-info` toggles that `data-lane`. The same lane's `i` and bar are one control. A second click on either clears the id. Opening another lane replaces the id. Set `aria-expanded="true"` on both buttons whose `data-lane` is that id, and `false` on the others.

One fill, not the journal-only `fillHeatJournal`. It `replaceChildren()` once, then writes that lane's color lines with text nodes and `.brk-key` swatches. For `heat` only, append the journal in the same pass, still with text nodes, oldest first. Do not call a journal-only fill for any other lane. Do not `replaceChildren()` again after the colors are in. `paintBreakers` assigns `breakerBoard.innerHTML` and then, if `_laneOpen` is set, calls this same fill. A 60-second refresh or `‹` / `›` must not wipe the color lines and must not show the heat journal under another lane. If the open lane is `heat`, those arrows keep the id and refill the journal for the new day. The color words do not change with the day.

The help listener near `static/app.js` 1204, the Esc listener near 1225, and the outside-click guard near 1752 still name `#brk-journal-pop`, `_journalOpen`, and `.brk-journal-hit`. Point all three at `#brk-lane-pop` and `_laneOpen`. Opening `.brk-help` clears the lane id, empties the pop, and sets `aria-expanded="false"` on the lane buttons. Esc does that first, before the meter help, then returns. A click inside `#brk-lane-pop` does not close it. `#brk-prev` and `#brk-next` do not close it either.

Words, Ukrainian, only the colors that lane paints. Every lane includes «зараз» with `brk-key-now`, because `_lane_html`, `breakerLane`, and the light and heat branches already draw `.brk-now`. Charge is one of those lanes.

| Lane | Lines |
|---|---|
| plan | green key «графік: є світло»; gray key «немає»; the now mark «зараз» |
| fact | «фактично: було»; «фактично: не було»; «зараз» |
| charge | «Колір — заряд батареї будинку.» Then six inline swatches from `soc_color` / `socColor` at 0, 25, 50, 75, 90, and 100, labeled with those percents. Then «зараз». Do not call the swatches separate modes. Do not add a seventh stop or a class per stop. |
| light | «увімкнено, було світло»; «увімкнено, не було світла»; «вимкнено»; «зараз» |
| heat | the same three light lines and «зараз», then the journal already specified in 2.5, oldest first. An empty day still says `За цю добу записів немає.` A truncated day still ends with `Старіші записи цієї доби не показано.` |
| boiler | «котельня»; «зараз» |
| alert | «без тривоги»; «жовта»; «червона»; «зараз» |

`paintAlertDay` is not one of these seven lanes. Leave its function and its legend. That function still contains one `<div class="brk-legend">` with «без тривоги», «жовта», and «червона». `tests/test_alert_level.py` keeps that legend. Its slice `script[script.index("pm-breakers-board"):]` only checks that `breakerBoilerLane` comes before `breakerAlertLane`. Do not add a ban on `class="brk-legend"` to that full slice.

The breaker-script slice used by `tests/test_breakers.py` starts at `pm-breakers-board` and ends before `function paintAlertDay`. Require `class="brk-legend"` to be absent only in that slice. The first `pm-breakers-board` in `static/app.js` is near line 1205, and `paintAlertDay` is later in the same file, so a slice that runs to the end of the file still contains the Тривоги legend.

Rendered checks, all in `tests/test_breakers.py` unless named otherwise:

- `_breaker_bars_html` has no `class="brk-legend"`, no `brk-journal-hit`, exactly seven `brk-lane-hit`, and exactly seven `brk-lane-info`. `Освітлення` is one of those buttons. `test_bars_are_green_then_red_and_the_other_breaker_is_empty` drops the exact count of one `<button`, the ban on a button in the lighting track, and the requirement that «увімкнено, було світло», `brk-key-now`, and `зараз</span>` appear in the server bars HTML. Those phrases move to the script that fills the pop. The bar-class order, `brk-batt`, the fact classes, and the 23×7 hour lines stay.
- `test_hidden_flag_removes_the_section` counts fifteen `<button` in the rendered section: one `brk-help` plus the fourteen lane buttons. The hidden flag still returns an empty section.
- `test_page_script_does_not_reuse_the_fact_lane` uses the slice that ends before `function paintAlertDay`. That slice contains `brk-lane-hit`, `brk-lane-info`, and `textContent`. It does not contain `brk-journal-hit`, `brk-journal-pin`, or `class="brk-legend"`. Do not require seven copies of `<button`, and do not keep the old count of one. `brk-legend-item` may remain on pop rows. The existing checks that are not the shared legend stay: no `factOnSegments`, lane order, `brk-batt`, the boiler class, hour marks, no `brk-plan-maybe`, one `/api/breakers` route, no poller POST, and the fragment still updates `pm_breakers` without `breaker_sample`.
- `test_heat_lane_lists_the_day_and_events_stay_city_light` looks for `data-lane="heat"` and `#brk-lane-pop` after `#pm-breakers-board`. The class is `brk-lane-pop`, not `brk-journal-pop brk-help-pop`. The heat phrase «увімкнено, було світло» is asserted in the script slice, not in the bars HTML. Journal clocks `09:15` then `18:00`, the empty day, the failed journal read, and the absence of `Обігрів увімкнено` from the `Події` fragment stay.

### 3.6 Phase

One phase. Server HTML and `paintBreakers` change together. A human gate after it. Do not deploy unless that same yes includes deploy. Do not put `#автооновити` in a commit unless the yes includes deploy.

#### Phase L1 — per-lane legend

Goal: the shared legend is gone. Each lane, and the `i` beside it, opens only that lane's colors. Heat still lists the day under its colors.

Touched: `power_monitor.py` `_lane_html`, the light/heat branch of `_breaker_bars_html`, and the pop in `_breaker_section_html`. `static/app.js` `breakerLane`, the light/heat branch of `paintBreakers`, the fill that replaces `fillHeatJournal`, the `.brk-help` listener, the Esc listener, and the outside-click guard. `static/style.css` for the label column, the lane hit, the pop, and `.brk-when-pin`. `tests/test_breakers.py`. Do not edit `paintAlertDay`. Do not edit `tests/test_alert_level.py` except to keep its boiler-before-alert order green. Do not edit the `Події` builder.

Steps: delete both shared `.brk-legend` blocks on this chart, the one at the end of `_breaker_bars_html` and the one at the end of `paintBreakers`. Leave the legend inside `paintAlertDay`. Add the buttons through `_lane_html` and `breakerLane`, and through the light/heat branches, as in 3.5. Replace `#brk-journal-pop` with `#brk-lane-pop`. Replace the boolean `_journalOpen` and `fillHeatJournal` with the lane id and the one fill in 3.5. Widen the label column and the hour pad together. Set `pointer-events: none` and `top: 3px` on `.brk-when-pin`. Update the four breaker tests named in 3.5. Do not edit `paintAlertDay`. Do not edit the `Події` builder.

Verification: `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule`. The negative checks in 3.5 are part of that run. No network.

Rollback: restore the shared legend and `brk-journal-hit`. Journal rows stay.

Deploy: no, unless the operator asks in the same yes.

### 3.7 Data and compatibility

No table and no `kv` change. The journal read from Part 2 is unchanged. A bad sentence is a render change.

Old pages that still have the shared legend in a cached `app.js` are replaced by the `?v=` commit query already on the script tag. No second cache key.

### 3.8 Verification and definition of done

Local tests in L1 are green.

Done when the chart shows no shared legend, each of the seven lanes opens only its own colors from the bar and from the `i`, the heat pop still lists the day, the Тривоги block keeps its own legend, and `Події` is unchanged. Live commands stay as they are.

After a deploy the operator asks for: open the dashboard, confirm the shared key is absent and the hour numbers still line up with the bars, open `Фактично` from the bar and from the `i`, open `Заряд` and see six stops plus «зараз», open `Обігрів` and read both the colors and the day list, press Esc, and check that a board refresh while a lane is open refills that lane's colors. A refresh with `Фактично` open must not show the heat journal.

### 3.9 Risks and decisions

- `paintBreakers` will put the shared legend back if only the server HTML changes.
- An info button with class `brk-help` toggles the meter help instead of the lane.
- Two popovers, journal and legend, can both stay open. One pop avoids that.
- Five lanes never pass through the light/heat loop. `_lane_html` and `breakerLane` are the other builders.
- A timer pin on the light lane swallows the tap unless its pointer events are off. The same pin sits above the bar unless its top matches the heat pin.
- The script builds buttons from templates. Count fourteen buttons on the rendered chart, not fourteen copies in the source.
- A script slice from `pm-breakers-board` to the end of `app.js` still contains the Тривоги legend. End that slice before `function paintAlertDay`.
- `fillHeatJournal` writes only the journal and `replaceChildren()` on every paint. The shared fill must write colors first and append the journal only for `heat`.
- Help, Esc, and the outside click still name `#brk-journal-pop`. After the id changes they must name `#brk-lane-pop`, or Esc closes the meter help first and a click inside the new pop counts as outside.
- Three live tests still require one heat button and the shared legend. Updating only `test_hidden_flag_removes_the_section` leaves `Освітлення` inert.
- A 32px info button in a `5.2rem` column grows the labels without the hour pad. Widen both by the same amount, and keep the name and the button in one cell.
- Growing every lane button to 32px makes the chart taller. That is the thumb target. Do not cover the next lane with a negative offset.
- The charge legend is a scale of inline `soc_color` stops plus «зараз». Six labeled swatches are enough. Do not invent extra colors.

| When | Decision |
|---|---|
| 2026-11-22T23:13:00Z | Operator: hide the legend until a lane is clicked. Each lane has its own legend. A small info mark beside the lane opens the same text as the lane. |
| 2026-11-22T23:16:00Z | Skin L-A. Shared legend removed. One pop. Heat keeps the journal under its colors. `paintAlertDay` stays. Proof `verifiedAtUtc=2026-11-22T23:13:52.524Z`. |
| 2026-11-22T23:16:00Z | self-review round 1. HIGH if the legend lived only in server HTML, because `paintBreakers` replaces the board. HIGH if the info button used `.brk-help`. HIGH if the journal pop and a legend pop could both be open. All three are written into 3.5. Charge is described as `soc_color`, not as a new scale. 0 CRITICAL, 0 HIGH left in that draft. |
| 2026-11-22T23:25:00Z | Lead review, before the critic. Proof `verifiedAtUtc=2026-11-22T23:13:52.524Z`. Five lanes are built by `_lane_html` and `breakerLane`, not by the light/heat loop. The script test must not expect seven copies of a template. Timer pins on the light lane need `pointer-events: none`. Charge swatches are inline hex from `soc_color`. Status of Part 3 is `REVIEW IN PROGRESS`. |
| 2026-11-22T23:33:00Z | Critic round 1, `grok-4.7-xhigh-fast`, agent `2e6f8a2c-c7b6-484b-85e7-18b5763ebb4d`. CHANGES REQUIRED. CRITICAL 0, HIGH 3, MEDIUM 2, LOW 1. The breaker-script slice now ends before `paintAlertDay`. One fill keeps the lane id and appends the journal only for heat. Help, Esc, and the outside click name `#brk-lane-pop`. Four breaker tests are named. The label column and the hour pad widen together. Charge includes «зараз». Both pins use `top: 3px` and `pointer-events: none`. Status stays `REVIEW IN PROGRESS` until round 2. |
| 2026-11-22T23:38:00Z | Critic round 2, same model, resumed. APPROVE. CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. L1 waits for an explicit yes. No code. |
| 2026-11-22T23:46:00Z | Operator yes for Phase L1. Prompt 2. Proof `verifiedAtUtc=2026-11-22T23:46:15.449Z`. Deploy was not in that yes. |
| 2026-11-22T23:51:00Z | Phase L1 landed locally. Both painters drop the shared legend. One pop, lane id on the board, heat journal appended after that lane's colors. Label column and hour pad share `--brk-label`. 127 tests OK. Not deployed. |
| 2026-11-22T23:53:00Z | Deploy yes. Manual pull `c5bdc4b..f764d9b`, service restarted, `systemctl is-active` is `active`, server HEAD `f764d9b`. Public `/app.js?v=f764d9b` has `brk-lane-hit`, the empty-day sentence, and the charge sentence. `brk-journal-hit` is gone. The only `class="brk-legend"` left is inside `paintAlertDay`. Public stylesheet has `--brk-label` and `brk-lane-pop`. The keyed lane click was not driven. Proof `verifiedAtUtc=2026-11-22T23:53:20.351Z`. No `#автооновити`. |
| 2026-11-22T23:59:00Z | Operator, looking at the live chart: the info marks sit against the names and are taller than the bars. They must sit on the right, in one column beside the bars, and be 16px, the bar height. Proof `verifiedAtUtc=2026-11-22T23:59:38.677Z`. |

Open questions: none.

### 3.10 Handoff

Phase L1 landed locally at 2026-11-22T23:51:00Z. The shared legend is gone from both painters. Each lane and the `i` beside its name open `#brk-lane-pop`. Heat still lists the day under its colors. `paintAlertDay` was not edited. `python -m unittest tests.test_itp_auto tests.test_breakers tests.test_light_schedule tests.test_alert_level` — 127 tests OK. `node --check static/app.js` passed. The keyed lane click was not driven on this deploy. The public script and stylesheet match `f764d9b`.

Code and commits stay English. The legend words stay the Ukrainian in 3.5.

Update this file and `plan_itp_auto_PROGRESS.md` at the gate, with a DateTime.

Status of Part 3 phase L1 is `LIVE` at `f764d9b`.

