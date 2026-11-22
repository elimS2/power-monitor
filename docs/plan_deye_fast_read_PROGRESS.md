# Deye fast register read — progress

Companion to `power-monitor/docs/plan_deye_fast_read.md`.

- Status: `REVIEWED / READY FOR LOCAL WORK`
- Active skin: B for the first enable (1 second). A (2 seconds) only after the 24-hour count in phase 3. Loop is off until `DEYE_FAST_INTERVAL_SEC=1`.
- Current phase: 2 live as `d174ec2`. Phase 3 has not started.
- Last updated: 2026-11-22T16:27:30Z

## Done

- 2026-11-22T13:05:00Z — Living plan written. No code, no commit, no deploy.
- 2026-11-22T13:28:00Z — Lead review pass. Plan now states battery scales, 32-bit word order, HV slice `block[1:10]`, one shared socket from phase 3, and alerts staying on `deye_log`.
- 2026-11-22T13:40:00Z — Critic round 1 (`grok-4.7-xhigh-fast`): CHANGES REQUIRED, 0 CRITICAL, 4 HIGH, 5 MEDIUM, 2 LOW. All accepted and written into the plan.
- 2026-11-22T13:50:00Z — Critic round 2: APPROVE WITH DEFERRED, 0 HIGH. The four medium and two low notes are now in the plan.
- 2026-11-22T14:00:00Z — Confirmation pass, `grok-4.7-xhigh-fast`: APPROVE, CRITICAL 0, HIGH 0. Status `REVIEWED / READY FOR LOCAL WORK`.
- 2026-11-22T14:28:21Z — Operator set the first live interval to 1 second. Two seconds waits for a day of stored rows. The 20-second burst is no longer the reason to start at 2. Proof `verifiedAtUtc=2026-11-22T14:28:21.350Z`.
- 2026-11-22T14:33:08Z — Lead pass before the new review. The 1-second loop sleeps only the leftover time, so the period stays 1 second. A moving hour is a 1000 W load swing. Status `REVIEW IN PROGRESS`.
- 2026-11-22T14:40:00Z — Critic on the 1-second change: 0 CRITICAL, 1 HIGH. Sleep is once after both inverters. Qualifying hour needs 3000 rows and no gap over 15 seconds.
- 2026-11-22T14:45:00Z — Confirmation: APPROVE, CRITICAL 0, HIGH 0. Status `REVIEWED / READY FOR LOCAL WORK`.
- 2026-11-22T15:15:59Z — Operator refused the 14-day delete. `deye_fast` is kept. Proof `verifiedAtUtc=2026-11-22T15:15:59.611Z`.
- 2026-11-22T15:20:03Z — Create Plan refresh. Section 4 no longer says fast rows must expire. Status `DRAFT READY FOR REVIEW`. Proof `verifiedAtUtc=2026-11-22T15:20:03.920Z`.
- 2026-11-22T15:29:00Z — Lead review, prompt #5. Status `REVIEW IN PROGRESS`. Newest fast row must be `ORDER BY ts DESC LIMIT 1`. A socket claim is check-and-add with no await, and `finally` drops it only when this task set `owned`. The 13:40 fast-cutoff sentence is superseded. Proof `verifiedAtUtc=2026-11-22T15:26:25.467Z`.
- 2026-11-22T15:39:00Z — Critic round 1 (`grok-4.7-xhigh-fast`, `b6affc2d-2888-4f13-a70b-ac8f1135ace3`): CHANGES REQUIRED, 0 CRITICAL, 1 HIGH, 1 MEDIUM, 3 LOW. Fixes are in the plan. Round 2 not run.
- 2026-11-22T15:41:00Z — Confirmation, same model, resumed: APPROVE, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. Phase 1 still needs an explicit yes.
- 2026-11-22T16:14:30Z — Phase 1 implemented. Operator yes via Agree & Continue. Proof `verifiedAtUtc=2026-11-22T16:11:21.429Z`. Decoder, table, insert, and `tests/test_deye_fast.py`. `cleanup_old` unchanged. `deye_recent_power` was briefly shortened by a bad edit and restored in the same step; the SOC tests then passed. No deploy, no commit. `config.py`, `detection.py`, and `power_monitor.py` were already dirty with a voltage-alert change and were not part of this phase.
- 2026-11-22T16:18:30Z — Phase 2 implemented. Operator yes via Agree & Continue. Proof `verifiedAtUtc=2026-11-22T16:18:17.733Z`. Solarman slow read is six blocks. Modbus TCP port 502 stays the old loop. 12 tests OK. No deploy, no commit. Company KB still has no `power-monitor` (searches at the start of the step, no repo hit).
- 2026-11-22T16:27:30Z — Phase 2 deployed, commit `d174ec2`, `#autodeploy`. Restart 2026-11-22T16:26:24Z. First new rows match the previous ones: apartment 55.28 V / SOC 91, house 538.0 V / SOC 98. Counters did not jump. Year load was already null. No fallback warning. Phase 3 not started. Proof `verifiedAtUtc=2026-11-22T16:27:09.991Z`.
- Source proof for the phase 2 plan update: composer `1ccc9355-92e4-47a9-90a2-abd5600f6e11`, `verifiedAtUtc=2026-11-22T16:18:17.733Z`.

## Phase status

| Phase | Status | Note |
|---|---|---|
| 1 Decode and table | done locally 2026-11-22T16:14:30Z | Decoder and table only. Poller unchanged. Not deployed. |
| 2 Batched slow read | live `d174ec2` 2026-11-22T16:26:24Z | Six-block Solarman reader. First rows match the previous shape. |
| 3 Fast loop | not started | Ships with interval 0. Enable is a separate yes. |
| 4 Page | not started | After phase 3. |

## Do not touch

- `deye_log` as the home of fast samples
- `deye_aggregates_refresh` queries
- Logger serials in git
- Breakers, Telegram, boiler parser

## Next

Phase 3 only after an explicit yes. The fast loop is not in the running code. Do not enable a one-second poll.
