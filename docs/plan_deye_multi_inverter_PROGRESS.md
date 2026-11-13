# Progress — multi-inverter Deye

Companion of `docs/plan_deye_multi_inverter.md`.

- Status: `REVIEWED / READY FOR LOCAL WORK`
- Active skin: A (registry + `deye_log.inverter_id`)
- Next phase: 0 (find the basement host). Do not start it from this review.
- Last updated: 2026-11-13T18:51:12Z

## Phase board

| Phase | State | Note |
|---|---|---|
| 0 Find basement host | not started | Diff the live breaker LAN (`192.168.0.0/24` on 2026-11-08/09) against `.100`–`.104`. No schema, no route, no firewall. |
| 1 Schema, backfill, apartment writers | not started | Nullable `inverter_id`. Poller and `POST /api/deye-heartbeat` both write the apartment id. No second poll. |
| 2 Scope apartment reads | not started | Lamp, `detection.py`, voltage JSON, the aggregate cache, and `/api/dashboard-fragments` stay apartment-only unless the key may see `deye_details`. |
| 3 Public block, then route, then poll | not started | `poll_enabled` stays 0 until `api_key_config_get("public")` has an explicit list, the role-or-key write has one target, and GCP can reach the host. House poll is its own task. |
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
