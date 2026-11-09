# Progress — basement breakers

- Plan: `power-monitor/docs/plan_breakers.md`
- Status: `LIVE READ ONLY`
- Active skin: Skin A
- Last updated: 2026-11-09T21:39:54Z
- Current phase: 4 read the message screen. The queue stays off.
- Next allowed step: none. Pulsar stays off. The page only reads.

## Phase checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed | 2026-11-09T20:27:13Z. Critic approved. |
| 1 Store samples and day row | done | 2026-11-09T20:37:30Z. Temp db tests passed. No page, no poller, no deploy. |
| 2 15-minute poll | done | 2026-11-09T20:45:39Z. Fake HTTP client. No deploy. Live poll waits for server env. |
| 3 Read route and section | done | 2026-11-09T20:58:02Z. Read-only. No button, no form, no deploy. |
| 4 Status messages | listener off | 2026-11-09T21:06:42Z. Screen offers only Pulsar. Switch left off. No webhook. |

## Gate log

| When | Gate | Result |
|---|---|---|
| 2026-11-09T19:55:00Z | Plan | Written. Waiting for review. Implementation not approved. |
| 2026-11-09T20:02:31Z | Lead review | Contracts added. Implementation still not approved. |
| 2026-11-09T20:17:31Z | Critic round 1 | REVISE. Fixes folded. Implementation still not approved. |
| 2026-11-09T20:37:30Z | Phase 1 | Operator yes via Agree & Continue. Writer and tests landed. Production not restarted. |
| 2026-11-09T20:45:39Z | Phase 2 | Operator yes via Agree & Continue. Poller landed. Production not restarted. Env on the server is still empty, so a later deploy would not call Tuya until those values are set. |
| 2026-11-09T20:50:10Z | Observe only | Operator: the page reads and shows. It does not control the breakers. Plan updated. No code. |
| 2026-11-09T20:58:02Z | Phase 3 | Operator yes via Agree & Continue. Section and read route landed. Production not restarted. |
| 2026-11-09T21:06:42Z | Phase 4 | Message Service dialog: Message Queue / Pulsar only, AES-GCM, no HTTP. Cancel pressed. Server Message Log also off, so the monthly count is unknown. Listener not started. |
| 2026-11-09T21:14:48Z | Rate | Type-7 logs since Kyiv midnight. Світло 2 907 rows and still has_next (stop code 40000309): phase_a 1270, phase_b 884, phase_c 742, energy 10, switch 1. Partial projection about 90 000/month. ІТП first page empty. Pulsar not enabled. |
| 2026-11-09T21:39:54Z | Deploy | Operator yes. Server env has the five TUYA names. This commit tag is `#autodeploy`. No page control. |
| 2026-11-09T21:40:19Z | Deploy check | Server is `2997503` and the service is active. The live page has the section, the bar, and no button or form. Sample table is empty until the first 15-minute poll. |

## Log

| When | What |
|---|---|
| 2026-11-09T19:55:00Z | Plan from disk plus the 2026-11-09 cloud reads (one status call carries switch, kWh, and phases). Company KB not used. |
| 2026-11-09T20:02:31Z | Lead review against `database.py`, `power_monitor.py`, `api/dashboard.py`, `static/app.js`. No code. |
| 2026-11-09T20:27:13Z | Review closed. Critic `grok-4.7-xhigh-fast`, three rounds, last verdict APPROVE, 0 critical, 0 high. No code. |
| 2026-11-09T20:37:30Z | Phase 1. `init_db` creates `breaker_sample`, `breaker_day`, `breaker_message`. `apply_breaker_status` is the only writer. Company KB skipped on purpose. `tests.test_breakers` and `tests.test_schedule_board`: 44 tests OK. |
| 2026-11-09T20:45:39Z | Phase 2. Tick fires when `tick * 30` is 900, not 870. Timeout 10s. Breaker errors do not cancel the Deye step. Company KB skipped again. `tests.test_breakers`: 22 OK. |
| 2026-11-09T20:50:10Z | Observe-only rule. Phase 3 may draw the lines and the bar. It may not add a button, a form, or a command route. |
| 2026-11-09T20:58:02Z | Phase 3. `GET /api/breakers` reads `breaker_day` only. Green then red from stored spans. Null today renders `немає бази`. 62 tests OK. A local color fixture was not opened in the browser: the temporary page server did not answer. |
| 2026-11-09T21:06:42Z | Phase 4. `ingest_status_message` accepts a decrypted report for the two ids and ignores any other id. `bg_loop` does not call it. 34 breaker tests OK. |
| 2026-11-09T21:14:48Z | Rate check says the message pack is too small for live phase reports. Listener stays off. Poll HMAC signature is uppercase so a later deploy is not rejected with 1004. Not deployed. |

## Review history

| When | Role | Model | Round | Verdict | Counts | What changed |
|---|---|---|---|---|---|---|
| 2026-11-09T19:55:00Z | self-review | planning agent | 0 | folded into draft | 0 critical, 0 high left open | Day row, null first-day energy, no Pulsar guess, token cache. |
| 2026-11-09T20:02:31Z | lead reviewer | current session | 1 | REVIEW IN PROGRESS | 3 high fixed, 1 medium fixed, 1 medium accepted | Lock + one transaction, midnight from sample ts, role-list append, dropped guessed code 1199. Critic not started. |
| 2026-11-09T20:17:31Z | independent critic | grok-4.7-xhigh-fast | 1 | REVISE | 0 critical, 5 high, 5 medium, 4 low | All accepted. Midnight span, gap base, webhook 503, message-id set, HTTP timeout, null today label, fixture shape, no factOnSegments, UA_TZ, measured message rate. |
| 2026-11-09T20:22:51Z | independent critic | grok-4.7-xhigh-fast | 2 | REVISE | 0 critical, 1 high, 1 medium, 0 low | Both accepted. No-sample today row only if yesterday exists. Late or duplicate payload does not insert a sample. |
| 2026-11-09T20:27:13Z | independent critic | grok-4.7-xhigh-fast | 3 | APPROVE | 0 critical, 0 high, 0 medium, 0 low | Confirmation after the post-approve wording. Local implementation still waits for an explicit yes. |

## Do not touch

- Deye poll interval, `deye_aggregates_refresh`, `deye_voltage_trend`.
- Schedule board and Telegram outage copy.
- Any Tuya command, including `switch` and timer edits.
- Any dashboard control that would send such a command. The page only reads and shows.
- Company knowledge base.
