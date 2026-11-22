# Progress — automatic ITP control

- Plan: `power-monitor/docs/plan_itp_auto.md`
- Status: `REVIEWED / READY FOR LOCAL WORK`
- Active skin: Skin A (edge). Skin B is `ITP_AUTO_SLOT=quarter`. Skin C rejected.
- Last updated: 2026-11-22T20:54:00Z
- Current phase: 4 done. Waiting for an explicit yes before Phase 5.
- Next allowed step: Phase 5 only after an explicit operator yes. Do not start it in the same turn.
- Commands: not implemented. `ITP_AUTO_COMMANDS` must stay off through deploy.

Source proof: composer `85ba10c3-3110-479d-ac13-0dddaf1132bc`, title `Automatic ITP control logic`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-22T18:43:35.564Z`, `mutationKind=plan`.

## Phase checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed | 2026-11-22T19:32:00Z. Critic APPROVE, 0 CRITICAL, 0 HIGH. |
| 1 Pure desired state | done | 2026-11-22T20:07:00Z. `itp_auto.desired_itp` and 15 tests. No network, no sqlite. |
| 2 Pure step | done | 2026-11-22T20:31:00Z. `step_itp`, flap guard, follow-up window, arm/disarm, temp sqlite. No HTTP. |
| 3 Local tick and card line | done | 2026-11-22T20:45:00Z. Minute decision and heat-card line. Commands hard-off. |
| 4 Admin arm | done | 2026-11-22T20:54:00Z. Admin flag only. No Tuya call. Armed card uses the admin sentence. |
| 5 Command path | not started | Env default remains `0`. Turning it on is a later yes. |

## Gate log

| When | Gate | Result |
|---|---|---|
| 2026-11-22T18:43:35Z | Plan proof | Exact composer proof. Files not written yet. |
| 2026-11-22T18:46:30Z | Plan | Draft written. Implementation not approved. |
| 2026-11-22T18:48:00Z | Self-review | Round 1. Lock nesting, Skin B POST site, and `slot_spent` unit fixed in the plan. No CRITICAL or HIGH left. |
| 2026-11-22T18:48:00Z | Review | Not run. Status stays `DRAFT READY FOR REVIEW`. |
| 2026-11-22T18:54:00Z | Command confirm | Operator yes. One `itp` status GET about a minute after a direct POST, same 60–150 second window as a timer. Quarter-hour sample remains the backup. Proof `verifiedAtUtc=2026-11-22T18:53:43.452Z`. |
| 2026-11-22T18:58:00Z | Lead review | Early return in `_breaker_step` would skip decide and confirm. Proof `verifiedAtUtc=2026-11-22T18:56:27.456Z`. |
| 2026-11-22T19:05:00Z | Critic round 1 | `grok-4.7-xhigh-fast`. CHANGES REQUIRED. CRITICAL 0, HIGH 3, MEDIUM 4, LOW 2. HIGH and MEDIUM fixed. LOW 9 rejected: a failed command is not a hand. |
| 2026-11-22T19:12:00Z | Critic round 2 | Same model. CHANGES REQUIRED. CRITICAL 0, HIGH 2. Empty `timers_cleared_at` now blocks POST. Phase 2 disarm uses the step 6 predicate. |
| 2026-11-22T19:16:00Z | Critic round 3 | Same model. CHANGES REQUIRED. CRITICAL 0, HIGH 1. Failed timer delete is now one attempt. Fix not re-reviewed. Status was `BLOCKED AT REVIEW CAP`. |
| 2026-11-22T19:24:00Z | New cycle | Operator yes. Proof `verifiedAtUtc=2026-11-22T19:23:19.013Z`. Status `REVIEW IN PROGRESS`. |
| 2026-11-22T19:28:00Z | Critic round 1 | `grok-4.7-xhigh-fast`. CHANGES REQUIRED. CRITICAL 0, HIGH 1. Disarm no longer clears `timer_delete_attempted`. Only arm does. |
| 2026-11-22T19:32:00Z | Critic round 2 | Same model. APPROVE. CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. |
| 2026-11-22T19:51:00Z | Flap guard | Operator: 4 switch commands in 60 minutes log and disarm. Fifth is not sent. |
| 2026-11-22T19:58:00Z | Flap review | `grok-4.7-xhigh-fast`. Round 1 HIGH 1 fixed. Round 2 APPROVE. CRITICAL 0, HIGH 0. |
| 2026-11-22T20:06:00Z | Phase 1 yes | Operator: Agree & Continue. Prompt 2. |
| 2026-11-22T20:07:00Z | Phase 1 | `desired_itp` landed. `python -m unittest tests.test_itp_auto` — 15 tests OK. No deploy. Phase 2 not started. |
| 2026-11-22T20:28:00Z | Phase 2 yes | Operator: Agree & Continue. Prompt 2. |
| 2026-11-22T20:31:00Z | Phase 2 | `step_itp` and the kv document landed. Same unittest — 36 tests OK. No HTTP, no deploy. Phase 3 not started. Proof `verifiedAtUtc=2026-11-22T20:30:42.938Z`. |
| 2026-11-22T20:41:00Z | Context | Company KB still does not index power-monitor. The five-volume search from the earlier session was not repeated: it returned unrelated credentials. Disk plan and code are the source. |
| 2026-11-22T20:41:00Z | Phase 3 yes | Operator: Agree & Continue. Prompt 2. |
| 2026-11-22T20:44:00Z | Stale lane count | `test_bars_are_green_then_red_and_the_other_breaker_is_empty` already failed on `main` before this phase: 161 hour marks, test expected 138. The alert lane was already drawn. Expected count is now 23×7. The chart was not changed. |
| 2026-11-22T20:45:00Z | Phase 3 | Local minute tick and the heat-card line landed. Commands stay hard-off. Three unittest modules — 90 tests OK. No deploy. Phase 4 not started. Proof `verifiedAtUtc=2026-11-22T20:45:01.057Z`. |
| 2026-11-22T20:51:00Z | Phase 4 yes | Operator: Agree & Continue. Prompt 2. |
| 2026-11-22T20:54:00Z | Phase 4 | Admin arm and disarm landed. Stranger key returns 403. Newest heat-breaker day supplies `applied`. No HTTP client, no deploy. Browser click is waiting for a deploy yes. Phase 5 not started. Proof `verifiedAtUtc=2026-11-22T20:53:49.287Z`. |

## Decisions mirrored from the plan

- 2026-11-22T18:40:00Z — minute Tuya polling stays rejected. The minute tick reads SQLite only.
- 2026-11-22T18:46:30Z — one extra ITP status GET per real edge, no per-minute retry, no repeated 20s/60s pair.
- 2026-11-22T18:54:00Z — after a direct POST, one `itp` status GET in the existing timer follow-up window. Not both breakers.
- 2026-11-22T18:46:30Z — public page has no direct breaker switch. Admin arms the policy only.

## Do not touch

- `docs/plan_breakers.md` (closed, read-only poll).
- `LIGHT_SCHEDULE_PAUSED` and any POST/DELETE aimed at the lighting breaker.
- Company knowledge base. No device ids, secrets, or house notes there.
