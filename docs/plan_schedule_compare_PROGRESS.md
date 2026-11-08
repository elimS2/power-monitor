# Progress — schedule compare board

- Plan: `power-monitor/docs/plan_schedule_compare.md`
- Status: `REVIEWED / READY FOR LOCAL WORK`
- Active skin: Skin A
- Last updated: 2026-11-08T23:07:29Z
- Current phase: 2 complete locally. Waiting for a yes before Phase 3.
- Next allowed step: Phase 3 only after an explicit yes. Do not deploy until asked. Neighbor statistics stay deferred.

## Phase checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed, ready for local work | 2026-11-08T23:05:00Z. Critic round 3 APPROVE, 0 CRITICAL, 0 HIGH. Code waits for an explicit yes. |
| 1 Queue column and scoped reads | done locally | 2026-11-08T22:58:59Z. Tests passed. Pushed as `446887b`. Not deployed. |
| 2 All queues + `schedule_changes` | done locally, gate open | 2026-11-08T23:07:29Z. 18 tests OK. Page unchanged. Not deployed. |
| 3 `GET /api/schedule-board` | not started | Depends on Phase 2. Route is a read of `schedule_day`. No `deye_log` scan. |
| 4 Board UI | not started | Depends on Phase 3. Old grid stays behind kv `schedule_board`. |
| Deploy | not started | Only if the operator asks. No `#автооновити` unless asked. |
| Later: neighbor buildings | not started | Telegram or Svitlobot. Separate from `schedule_changes` and our `power_events`. Not on the request path. |

## Gate log

| When | Gate | Result |
|---|---|---|
| 2026-11-08T22:58:59Z | Phase 1 | Code and tests done. Asking whether to start Phase 2. |
| 2026-11-08T23:07:29Z | Phase 2 | All queues and change rows stored. Asking whether to start Phase 3. |

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
