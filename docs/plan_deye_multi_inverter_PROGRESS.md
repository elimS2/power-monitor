# Progress — multi-inverter Deye

Companion of `docs/plan_deye_multi_inverter.md`.

- Status: `PHASE 3 PAUSED — PUBLIC KEY NOT READ`
- Active skin: A (registry + `deye_log.inverter_id`, MAC stored, host is last confirmed address)
- Next phase: 3 step 1 still open. The live `public` label was not read. The route is not open.
- Last updated: 2026-11-13T20:01:34Z

## Phase board

| Phase | State | Note |
|---|---|---|
| 0 Find basement host | read ok | MAC `74:e9:d8:39:22:8a`, last address `192.168.0.104`. SOC 98%, load 9525 W. Serial not stored. |
| 1 Schema, backfill, apartment writers | local, not deployed | 2026-11-13T19:40:56Z. Apartment row seeded. Old samples backfilled. Poller and heartbeat write that id. 39 tests OK. |
| 2 Scope apartment reads | local, not deployed | 2026-11-13T19:45:27Z. Lamp, voltage JSON, aggregates, and the fragment are scoped. 41 tests OK. |
| 3 Public block, then route, then poll | paused at step 1 | 2026-11-13T20:01:34Z. Debug SQL 403, then SSH publickey denied. Section not added. Route not opened. Poll stays off. |
| 4 Doc location fix | not started | `house/shelter-wifi.md` still says the router is on the desk. |

## Review

| When (UTC) | Who | Verdict | Counts | What changed |
|---|---|---|---|---|
| 2026-11-13T18:42:00Z | Lead, prompt #5, round 1 | in progress, critic not run yet | plan holes closed in the text | Lamp, detection, heartbeat, aggregate cache, battery kWh, DOM ids, fail-open sections, route gate. Phase 0 no longer scans `192.168.67.1`. |
| 2026-11-13T18:47:00Z | Critic `grok-4.7-xhigh-fast`, agent `425ac57b-0f2d-4eeb-b5f0-5a76e62c19a7` | `CHANGES REQUIRED` | CRITICAL 0, HIGH 2, MEDIUM 4, LOW 2 | Both HIGH accepted: fragment JSON leaks apartment SOC; `role_id` ignores a raw sections write. Fixes written. |
| 2026-11-13T18:51:12Z | Critic `grok-4.7-xhigh-fast`, same agent, final confirmation | `APPROVE` | CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0 | Builtin role write is `UPDATE roles`, not `role_update`. Local work is allowed only after an explicit continue. |

## Log

- 2026-11-13T16:55:00Z — Dialog `cbc74fb3` read. Basement scan is there: OpenWrt WAN `192.168.0.108`, TP-Link `192.168.0.1`, no inverter yet. Phase 0 is a diff against `.100`–`.104`. Still no code. (Earlier PROGRESS line "scan artifact missing" is superseded.)
- 2026-11-13T18:42:00Z — Lead review. No code.
- 2026-11-13T18:47:00Z — Critic round 1 fixes applied. No code. Implementation still blocked.
- 2026-11-13T18:51:12Z — Final confirmation APPROVE. Status `REVIEWED / READY FOR LOCAL WORK`. No code. Next phase is still 0, and it waits for an explicit continue.
- 2026-11-13T19:06:51Z — Prompt #2 continue. Read-only scan. Candidate `192.168.0.104`. Tuya MACs moved to `.103` and `.108`. New Akuvox-family host `.105` has no port 8899. Serial not read. Phase 1 not started.
- 2026-11-13T19:15:55Z — Sticker serial answered. SOC 98%, load 9525 W, grid about 227 V. Operator named `.105` as the freight-elevator Akuvox. Breaker commands use the cloud device id. Phase 1 still not started.
- 2026-11-13T19:19:09Z — Plan revision. MAC table is the device list. AVG `IDP.Generic` on `owrt-phase0-read.py` (`c43dd3375964`); those Temp scripts were deleted. Status `DRAFT READY FOR REVIEW`. No code, no commit.
- 2026-11-13T19:22:58Z — Lead review. OpenWrt MAC is not tied to `.109`. Stale logger IP is not reused. Critic not run yet.
- 2026-11-13T19:25:00Z — Critic HIGH accepted. GCP does not look up MAC and does not erase `host`. Confirmation pending.
- 2026-11-13T19:26:00Z — Confirmation APPROVE. CRITICAL 0, HIGH 0. Status `REVIEWED / READY FOR LOCAL WORK`. No code.
- 2026-11-13T19:40:56Z — Phase 1 local. No house poll. No deploy. 39 tests OK.
- 2026-11-13T19:45:27Z — Phase 2 local. House sample does not move the apartment voltage bar or the lamp. No deploy. 41 tests OK.
- 2026-11-13T19:50:43Z — Phase 3 step 1 paused. The local monitor key is not accepted by the live debug route. No section, no route, no poll. Route, if later approved, starts at the GCP poller and ends at one basement host via the shelter WireGuard peer.
- 2026-11-13T20:01:34Z — Continue retried step 1. SSH to the server was rejected for want of a key. The VM is not in the cloud projects this PC can list. Public sections still unknown. No code, no route.
