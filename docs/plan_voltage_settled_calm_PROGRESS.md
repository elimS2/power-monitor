# House light from the basement inverter — progress

Companion to `docs/plan_voltage_settled_calm.md`.

- Status: `PHASE 2 DEPLOYED`
- Active skin: A (one basement-phase decision; `analyze` runs every 10 seconds from its own task; the plug branch and `PHASES_ONLY` are deleted; a stale basement sample is unknown; the calm mark is kept only while the anomaly is set and all three phases are normal; «усі фази зникли» is the third confirm while the anomaly is unset; an open anomaly with trend high sends no line and the lamp stays «Висока напруга»; the old router letter is the apartment inverter link)
- Current phase: deployed. Server `1964065`, restarted `2026-11-23T17:06:27Z`. Rollback `cef1f6d2fcbfe7ecd783b812e848d5b9ef8ad302`.
- Last updated: `2026-11-23T18:44:00Z`
- Source proof: composer `195973fe-c59a-43b4-85a5-83484b6497f6`, `verifiedAtUtc=2026-11-23T13:49:47.015Z`

## Done

- `2026-11-22T16:58:00Z` — Calm letter deployed as `28a93a1`. The calm mark still survives a blackout.
- `2026-11-23T12:44:00Z` — Implementation review `NO-GO`, 1 HIGH. A blackout left `voltage_normal_since` in place.
- `2026-11-23T13:08:00Z` — Plug-based plan `APPROVE`. Superseded when the operator said the plugs are not the building light.
- `2026-11-23T13:18:00Z` — Draft `DRAFT READY FOR REVIEW` that said the live path was plugs (`PHASES_ONLY=0`). Superseded. The server flag was already `1`.
- `2026-11-23T13:42Z` — Live check. `PHASES_ONLY=1`. Down letters at 03:36, 07:06, and 15:36 Kyiv went out with plug175 at 3 and basement phases at 0/0/0. Both-dead heartbeats in the last day: 0.
- `2026-11-23T13:50:00Z` — Plan rewritten. Phase 1 deletes the spare plug branch, `PHASES_ONLY`, and `OUTAGE_CONFIRM_COUNT`. First clock was the 30-second loop. Superseded.
- `2026-11-23T13:52:00Z` — Lead review. Clock is `GRID_CHECK_SEC` 10. ITP keeps event `since`. Critic not run yet at that stamp.
- `2026-11-23T14:20:00Z` — Critic round 1, `grok-4.7-xhigh-fast`, agent `1e0a5846-8242-4f7c-8883-b81a5f4fd6b6`. `CHANGES REQUIRED`, CRITICAL 0, HIGH 2, MEDIUM 3, LOW 2. All accepted in the plan. Status stays `REVIEW IN PROGRESS`. No code.
- `2026-11-23T14:35:00Z` — Critic round 2, same agent. `CHANGES REQUIRED`, CRITICAL 0, HIGH 1, MEDIUM 2, LOW 0. Calm mark moved off `up` onto the anomaly-set normal-trend step. No code.
- `2026-11-23T14:45:00Z` — Critic round 3, same agent. `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. No code.
- `2026-11-23T15:45:53Z` — Phase 1 implemented locally. No deploy. No server `.env` edit. `_fast_loop` not edited. Unit tests named in the plan passed (99).
- `2026-11-23T16:58:30Z` — Phase 2 page change. Operator yes via Agree & Continue. Repo Memory has no `power-monitor`. Plug section removed. 100 tests OK. Deploy not run.
- `2026-11-23T16:59:43Z` — Pushed `9041629`. SSH publickey denied. gcloud cannot see the VM. Server not restarted.
- `2026-11-23T17:06:27Z` — Deployed with the instance key and `IdentitiesOnly`. Before: `cef1f6d2fcbfe7ecd783b812e848d5b9ef8ad302`. After: `1964065`. Service active. Plug table gone. Lamp «Світло ВІДСУТНЄ». No new light letter. `.env` untouched.
- `2026-11-23T18:44:00Z` — Operator asked to clear the three leftovers. Status field and dead page script removed. `PHASES_ONLY` line to be deleted from the server `.env` in the same step. Router ping storage stays.

## Phase status

| Phase | Status | Note |
|---|---|---|
| 1 Delete the spare path | deployed | Inside `9041629`, live since `2026-11-23T17:06:27Z`. |
| 2 Page table and deploy | deployed | Plug table gone on the live page. Rollback `cef1f6d`. |

## Do not touch

- The fast-read plan, `_fast_loop`, and `DEYE_FAST_INTERVAL_SEC`
- The battery board and the 98% rule
- `VOLTAGE_EPISODE_MIN_INTERVAL_SEC`
- Old `heartbeats` rows, the table, and `GET /api/heartbeat` storage. The router still posts.

## Next

Both phases are on the server. No further step in this plan. A later change still uses the key in the local canvas `power-monitor-deploy.canvas.tsx`.
