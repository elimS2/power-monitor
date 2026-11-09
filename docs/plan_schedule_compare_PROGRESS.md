# Progress — schedule compare board

- Plan: `power-monitor/docs/plan_schedule_compare.md`
- Status: `REVIEWED / READY FOR LOCAL WORK`
- Active skin: Skin A
- Last updated: 2026-11-09T16:37:16Z
- Current phase: fact lane and now line are on the live site, script `34734dd`.
- Next allowed step: confirm the live match line, then stop. Neighbor buildings stay skipped.

## Phase checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed, ready for local work | 2026-11-08T23:05:00Z. Critic round 3 APPROVE, 0 CRITICAL, 0 HIGH. Code waits for an explicit yes. |
| 1 Queue column and scoped reads | done locally | 2026-11-08T22:58:59Z. Tests passed. Pushed as `446887b`. Not deployed. |
| 2 All queues + `schedule_changes` | done locally | 2026-11-08T23:07:29Z. 18 tests OK. Pushed as `32aa109`. Not deployed. |
| 3 `GET /api/schedule-board` | done locally | 2026-11-08T23:27:27Z. 30 tests OK. Route is a read. Not deployed. |
| 4 Board UI | done locally, gate open | 2026-11-09T13:00:34Z. Board is outside the 10s fragment. Live browser pass waits for deploy. |
| Deploy | done | 2026-11-09T13:07:30Z. Commit `af15747` with `#autodeploy`. Live page shows the Ukrainian board. |
| Later: neighbor buildings | skipped for now | 2026-11-09T13:50:11Z. Still a future idea. Telegram or Svitlobot. Not on the request path. Elevator trips are a separate local idea, not this phase. |

## Gate log

| When | Gate | Result |
|---|---|---|
| 2026-11-08T22:58:59Z | Phase 1 | Code and tests done. Asking whether to start Phase 2. |
| 2026-11-08T23:07:29Z | Phase 2 | All queues and change rows stored. Asking whether to start Phase 3. |
| 2026-11-08T23:27:27Z | Phase 3 | Read route and writers done. Asking whether to start Phase 4. |
| 2026-11-09T13:00:34Z | Phase 4 | Board UI done locally. Asking whether to deploy. |
| 2026-11-09T13:06:11Z | Deploy | Operator asked to ship. Slot words ok/off/maybe on the board are shown as світло/відключення/можливе. Commit carries #autodeploy. |
| 2026-11-09T13:07:30Z | Deploy check | Live dashboard has `#pm-sched-board`. Visible text is Ukrainian: date 09.11.2026, weekday, наша, layer names, emergency banner, match line. Power-monitor has no separate deploy page; shipping is the `#autodeploy` commit, which the server pulled. |
| 2026-11-09T13:16:00Z | Layout | The hour grid used a 980px minimum and the actual/voltage bars sat outside that scroller, so the bars did not move with the hours. Bars are now a row inside the same table, over the 48 hour columns only. The table is 100% of the card. |
| 2026-11-09T13:16:30Z | Layout check | Live script `/app.js?v=b8700e4`. The hour scroller overflow is 0. The bar cell starts and ends on the same pixels as the first and last hour cells of row 5.1. |
| 2026-11-09T13:19:34Z | Now marker | Planned, not built. Our current cell should blink again and show whether that slot agrees with `data-pm-down`. No new request. See plan section 6.8a. |
| 2026-11-09T13:24:48Z | Now marker | Operator said yes. Built in `static/app.js` and `static/style.css`. Our current cell blinks yellow when the slot agrees with `data-pm-down`, red when it does not. `maybe` while the light is on stays yellow. No new request. A local four-cell fixture showed the lightning and both animations. Live site not updated. |
| 2026-11-09T13:26:16Z | Deploy | Operator asked to ship the marker. Commit `f7b9af7` carries `#autodeploy`. |
| 2026-11-09T13:27:30Z | Deploy check | Live page loads `/app.js?v=f7b9af7` and `/style.css?v=f7b9af7`. The note about yellow and red is visible. Queue 5.1, slot 30, plan `ok`, light on, class `sb-now-yes`, lightning glyph, animation `sg-glow`. |
| 2026-11-09T13:32:21Z | Fact lane and now line | Proposed, not built. Same fact row: green `#22c55e` where the light was on, red where it was not, green stops at now. A dashed minute line crosses every group. Our lightning stays. See plan 6.8b. |
| 2026-11-09T13:41:37Z | Fact lane and now line | Operator said yes. One fact row: green `#22c55e` in the gaps, red `#f87171` on the outages, green stops at the clock. A dashed line sits on the current minute through the hour label and every group. Our cell still blinks; other groups do not. A local board showed one lane, the 02:00–03:00 outage in red, green up to the line, hour 15 lit, the line inside slot 31. Live site not updated. |
| 2026-11-09T13:44:14Z | Deploy | Operator asked to ship the fact lane and the minute line. Commit `34734dd` carries `#autodeploy`. |
| 2026-11-09T13:45:03Z | Deploy check | Live page loads `/app.js?v=34734dd` and `/style.css?v=34734dd`. The green/red note is visible. Green `#22c55e` ends on the dashed line, red `#f87171` is on the same row, hour 15 is bright, queue 5.1 blinks yellow, other groups do not. |
| 2026-11-09T13:50:11Z | Later ideas | Operator skipped neighbor buildings. Both that idea and elevator trips for the basement-battery forecast are written in the local card, not started. |
| 2026-11-09T16:34:02Z | Match line | A possible slot now counts as an outage. Dark minutes there are a hit, light minutes are a miss. The read rescores the loaded row so the old stored zero does not stick. Not deployed. |
| 2026-11-09T16:37:16Z | Deploy | Operator asked to ship that score. This commit carries `#autodeploy`. |

## Log

| When | What |
|---|---|
| 2026-11-08T22:19:51Z | Company KB searched (knowledge, ideas, code_directories, code_files, code_symbols, jira). No power-monitor code and no ticket. Disk is the source of truth. |
| 2026-11-08T22:22:00Z | Proxy payload: 12 queues in `kiivska-oblast`, region `emergency` bool, no transfers array. Queue `5.1` had only `2026-11-09`. |
| 2026-11-08T22:24:28Z | Plan written. Skin A. Self-review round 1: fragment wipe, `updScheduleNow` row index, queue filter before multi-queue writes, missing snapshot ≠ all-ok, emergency flag flip, voltage bar ≠ 3600s pause. All folded into the plan. Status set to `DRAFT READY FOR REVIEW`. |
| 2026-11-08T22:32:13Z | Lead review (prompt #5). The draft GET scanned a day of `deye_log` (~2880 rows) and walked events. That repeats the bug fixed by `deye_aggregates_snapshot` / `_refresh_deye_aggregates`. Plan now: writers update one `schedule_day` row; GET only reads it and fills a null `end` from the clock. One-time actual-bar backfill uses `power_events` only, off the request, guarded by kv `schedule_day_actual_backfill_done`. Voltage history is not backfilled. Status `REVIEW IN PROGRESS`. |
| 2026-11-08T22:44:32Z | Critic round 1, model `grok-4.7-xhigh-fast`. CHANGES REQUIRED. Lead accepted every finding and wrote the fixes into the plan. |
| 2026-11-08T22:55:00Z | Critic round 2 confirmed the first CRITICAL and eight HIGHs closed, then found the midnight carry still keyed off `date_rolled`. Lead retargeted it to clock dates and a process-start pass. |
| 2026-11-08T23:05:00Z | Critic round 3 APPROVE. 0 CRITICAL, 0 HIGH. Kv flag stops only the `power_events` backfill. Status `REVIEWED / READY FOR LOCAL WORK`. No code written. |
| 2026-11-08T22:58:59Z | Phase 1. `schedule_history.queue` and `emergency` added. Old rows become `5.1` / `0`. `schedule_history_for_date` requires a queue. The three dashboard callers and `fetch_dtek_schedule` pass `DTEK_QUEUE`. Fetch still keeps only today and tomorrow in `schedule_cache` and still returns early when our queue is missing. `python -m unittest tests.test_schedule_board` — 4 OK in 0.278s. Not deployed. |
| 2026-11-08T23:07:29Z | Phase 2. `store_published_schedule` writes every published queue and date. `classify_grid_changes` runs inside the snapshot transaction. Missing our queue does not clear `schedule_cache` and does not invent an all-ok grid. `python -m unittest tests.test_schedule_board` — 18 OK. Neighbor-building overlay deferred (Telegram or Svitlobot). Not deployed. |
| 2026-11-08T23:27:27Z | Phase 3. `schedule_day` holds the outage bar, the voltage bar, and the match. `save_event` still inserts every event and only `down`/`up` touch the outage columns. `save_deye_log` updates voltage from the one sample it just stored. `GET /api/schedule-board` reads those rows and fills an open end from the clock. `bg_loop` carries an open outage across midnight and runs the one-time `power_events` backfill. 30 tests OK. Not deployed. |
| 2026-11-09T13:00:34Z | Phase 4. `#pm-sched-board` is a sibling of `#pm-sched-content`. While the flag is on, the fragment is only today's text from `schedule_cache`. The browser loads `/api/schedule-board` on day change, tab focus, and every 60s for today. Group and layer toggles do not fetch. `updScheduleNow` does not paint the old row index when the board exists. Flag `0` restores the old grid. Live site not opened. Not deployed. |
| 2026-11-09T13:24:48Z | Now marker. The static inset is replaced by a blinking lightning on our current half-hour. Yellow agrees with the live light, red contradicts it. The plan is read from `data-sb-plan`, so turning off the outage colors does not blank the marker. Checked on a local fixture, not on power.elims.pp.ua. |
| 2026-11-09T13:41:37Z | Fact lane and now line. The browser paints green from the stored outage gaps. No new request and no scan. The minute line is placed from the label width plus the fraction of the day, on the same 10-second timer as the lightning. |

## Review history

| When | Role | Model | Round | Verdict | Counts |
|---|---|---|---|---|---|
| 2026-11-08T22:32:13Z | lead | session author | 0 | request budget folded | — |
| 2026-11-08T22:44:32Z | critic | grok-4.7-xhigh-fast | 1 | CHANGES REQUIRED | CRITICAL 1, HIGH 8, MEDIUM 5, LOW 3 |
| 2026-11-08T22:44:32Z | lead | session author | 1 | all of those folded into the plan | awaiting round 2 |
| 2026-11-08T22:50:00Z | critic | grok-4.7-xhigh-fast | 2 | CHANGES REQUIRED | CRITICAL 0, HIGH 1, MEDIUM 2, LOW 1 |
| 2026-11-08T22:55:00Z | lead | session author | 2 | round 2 folded | awaiting round 3 |
| 2026-11-08T23:05:00Z | critic | grok-4.7-xhigh-fast | 3 | APPROVE | CRITICAL 0, HIGH 0 |

## Do not touch

- `schedule_cache` consumers: `current_slot_status`, `schedule_deviation`, `next_schedule_transition`, Telegram copy.
- Voltage notification timing (`VOLTAGE_EPISODE_MIN_INTERVAL_SEC`, recovery backdate).
- `deye_aggregates_refresh` and `deye_voltage_trend`. Do not call them from the board, and do not move them in this work.
- Company KB. No house data, no keys, no dashboard URL key in git.
