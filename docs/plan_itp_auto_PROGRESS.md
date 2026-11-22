# Progress — automatic ITP control

- Plan: `power-monitor/docs/plan_itp_auto.md`
- Status: Part 1 and Part 2 stay `LIVE`. Part 3 phase L1 is `LIVE` at `f764d9b`.
- Active skin: control Skin A (edge). Journal skin J-G is live. Legend skin L-A is live: one legend per lane, hidden until that lane or its info mark is opened.
- Last updated: 2026-11-22T23:53:00Z
- Current phase: L1 is on the site. There is no L2.
- Next allowed step: none. A keyed click of the lanes was not driven.
- Commands: on since 2026-11-22T21:33:00Z. The value is in the server `.env`, not in git.

Source proof: composer `85ba10c3-3110-479d-ac13-0dddaf1132bc`, title `Write the ITP on-off rule`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-22T22:04:58.446Z`, `mutationKind=plan`. Earlier proof `2026-11-22T18:43:35.564Z` remains the Part 1 write.

## Phase checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed | 2026-11-22T19:32:00Z. Critic APPROVE, 0 CRITICAL, 0 HIGH. |
| 1 Pure desired state | done | 2026-11-22T20:07:00Z. `itp_auto.desired_itp` and 15 tests. No network, no sqlite. |
| 2 Pure step | done | 2026-11-22T20:31:00Z. `step_itp`, flap guard, follow-up window, arm/disarm, temp sqlite. No HTTP. |
| 3 Local tick and card line | done | 2026-11-22T20:45:00Z. Minute decision and heat-card line. Commands hard-off. |
| 4 Admin arm | done | 2026-11-22T20:54:00Z. Admin flag only. No Tuya call. Armed card uses the admin sentence. |
| 5 Command path | done | 2026-11-22T21:06:00Z. Fake client covers read, post, confirm, and one timer delete. Env default remains off. |

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
| 2026-11-22T21:00:00Z | Card wording | Operator: the line should read like automatic control on or off. `в адмінці` sounded like a way of switching the breaker. Card now says `Автоматичне керування: увімкнено` or `вимкнено`. |
| 2026-11-22T21:00:00Z | Phase 5 yes | Operator: Agree & Continue. Prompt 2. |
| 2026-11-22T21:06:00Z | Phase 5 | Command path landed behind `ITP_AUTO_COMMANDS`. Default stays off. Fake client: 100 tests OK across the three modules. No deploy. Proof `verifiedAtUtc=2026-11-22T21:06:20.892Z`. |
| 2026-11-22T21:09:00Z | Shorter card | Operator: `Керування: автоматичне` or `Керування: ручне`. `tests.test_itp_auto` — 53 tests OK. Not deployed. Proof `verifiedAtUtc=2026-11-22T21:09:18.899Z`. |
| 2026-11-22T21:13:00Z | Deploy yes | Operator: update the site. |
| 2026-11-22T21:17:00Z | Deploy | Commit `a025d5d` is live. Footer hash matches. Heat card: `Керування: ручне. За правилом зараз увімкнути: котельня.` One `brk-auto` line. Commands were not turned on. Proof `verifiedAtUtc=2026-11-22T21:17:50.570Z`. |
| 2026-11-22T21:28:00Z | Meter row | Operator: put the mode in the meter list. `ручне` is red, `автоматичне` is green. Deploy with this commit. Proof `verifiedAtUtc=2026-11-22T21:28:08.851Z`. |
| 2026-11-22T21:32:00Z | Commands yes | Operator: do not wait. Turn cloud commands on now. |
| 2026-11-22T21:33:00Z | Commands on | `ITP_AUTO_COMMANDS=1` written only in the server `.env`. Service restarted. Heat breaker was already on, and the boiler window also wants it on, so the card note became `Котельня.` The sentence about commands being off disappeared. Proof `verifiedAtUtc=2026-11-22T21:35:19.505Z`. |
| 2026-11-22T21:52:00Z | Journal request | Operator: record automatic heat on/off and manual/automatic mode changes. Suggested the `Події` block. Asked to update this plan with prompt 6. |
| 2026-11-22T21:53:00Z | Part 2 draft | Skin J-A: table `itp_journal`, list under the breaker cards. `Події` stays city light. Self-review round 1, 0 CRITICAL, 0 HIGH. Status `DRAFT READY FOR REVIEW`. No code. Proof `verifiedAtUtc=2026-11-22T21:53:10.797Z`. |
| 2026-11-22T21:59:00Z | Journal place | Operator asked for a light UI on the existing day lanes. Default was marks on `Обігрів`. Empty-lane tap rejected. Self-review round 2 fixed the `paintBreakers` wipe. Still `DRAFT READY FOR REVIEW`. No code. Proof `verifiedAtUtc=2026-11-22T21:59:06.870Z`. Superseded 2026-11-22T22:08:00Z. |
| 2026-11-22T22:08:00Z | Journal place | Operator: a tap on the `Обігрів` line shows the whole day. Marks removed. Skin J-G. List lives outside `#pm-breakers-board`. Self-review round 3, 0 CRITICAL, 0 HIGH. Still `DRAFT READY FOR REVIEW`. No code. Proof `verifiedAtUtc=2026-11-22T22:04:58.446Z`. |
| 2026-11-22T22:12:00Z | Plan review | Lead, before the critic. Proof `verifiedAtUtc=2026-11-22T22:10:44.991Z`. Map live `pause.reason=manual` to journal `hand`. Confirm both `_confirm_itp_command` and `settle_itp_after_sample`. Day key is Kyiv, not UTC. `journal_truncated` is on the payload. Status `REVIEW IN PROGRESS`. No code. |
| 2026-11-22T22:18:00Z | Critic round 1 | `grok-4.7-xhigh-fast`. CHANGES REQUIRED. CRITICAL 0, HIGH 2, MEDIUM 4, LOW 2. Fixes are in the plan. Re-review not back. No code. |
| 2026-11-22T22:22:00Z | Critic round 2 | Same model, resumed. APPROVE. CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. J1 waits for an explicit yes. No code. |
| 2026-11-22T22:34:00Z | Phase J1 | Operator yes, prompt 2. Table `itp_journal`, `append_itp_journal`, `itp_journal_for_day`, and `itp_journal_line`. No page and no live writer. `JournalStoreTests` passed with the breaker and lighting suites after the info-button assertion was narrowed to the one existing `brk-help`. No deploy. Proof `verifiedAtUtc=2026-11-22T22:32:17.637Z`. J2 not started. |
| 2026-11-22T22:40:00Z | Phase J2 | Operator yes, prompt 2. `mutate_itp_auto` writes a switch row at `confirmed=0`, then a mode row when `enabled` changes. Confirm is `mark_itp_journal_confirmed` from `_confirm_itp_command` and `settle_itp_after_sample`. A journal error does not undo the document. 115 tests OK. No deploy. Proof `verifiedAtUtc=2026-11-22T22:37:09.536Z`. J3 not started. |
| 2026-11-22T23:02:00Z | Phase J3 | Operator yes, prompt 2. The heat lane opens that day's sentences. No marks. The list is outside the board and uses text nodes. 116 tests OK. Browser tap waits for a deploy. Proof `verifiedAtUtc=2026-11-22T23:02:12.921Z`. |
| 2026-11-22T23:04:00Z | Deploy | Operator: deploy. `git pull` from `21c8ab0` to `c5bdc4b`, service restarted, status active. Public script has the heat-lane button and the empty-day sentence. Public stylesheet has the list panel. No mark class. Table `itp_journal` exists. The keyed click was not driven. Proof `verifiedAtUtc=2026-11-22T23:05:22.381Z`. |
| 2026-11-22T23:16:00Z | Part 3 draft | Operator: hide the shared legend until a lane click. Each lane has its own legend, and a small info mark opens the same text. Skin L-A. Self-review round 1, 0 CRITICAL, 0 HIGH. Status `DRAFT READY FOR REVIEW`. No code. Proof `verifiedAtUtc=2026-11-22T23:13:52.524Z`. |
| 2026-11-22T23:25:00Z | Plan review | Lead, before the critic. Five lanes go through `_lane_html` and `breakerLane`. Script tests count rendered buttons, not template copies. Status `REVIEW IN PROGRESS`. No code. |
| 2026-11-22T23:32:00Z | Critic round 1 | `grok-4.7-xhigh-fast`. CHANGES REQUIRED. CRITICAL 0, HIGH 3, MEDIUM 2, LOW 1. No code. |
| 2026-11-22T23:33:00Z | Critic fixes | Slice ends before `paintAlertDay`. One fill, lane id, help/Esc/outside click, four named tests, shared label width, charge «зараз», pin top. Round 2 not back. No code. |
| 2026-11-22T23:38:00Z | Critic round 2 | Same model, resumed. APPROVE. CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status `REVIEWED / READY FOR LOCAL WORK`. L1 waits for an explicit yes. No code. |
| 2026-11-22T23:46:00Z | Phase L1 yes | Operator: Agree & Continue. Prompt 2. Proof `verifiedAtUtc=2026-11-22T23:46:15.449Z`. Deploy was not included. |
| 2026-11-22T23:51:00Z | Phase L1 | Shared legend removed. Each lane and its info mark open one pop. Heat keeps the day list under its colors. 127 tests OK, including the alert-day module. `node --check static/app.js` passed. Not deployed. The site stays at `c5bdc4b`. |
| 2026-11-22T23:53:00Z | Deploy | Operator yes. Pull `c5bdc4b..f764d9b`, restart, active, HEAD `f764d9b`. Public script and stylesheet match. Keyed click not driven. Proof `verifiedAtUtc=2026-11-22T23:53:20.351Z`. No deploy tag, so this record commit must not be pulled by the poller. |

## Part 2 checklist

| Phase | State | Note |
|---|---|---|
| Plan | reviewed | 2026-11-22T22:22:00Z. Critic round 2 APPROVE, 0 CRITICAL, 0 HIGH. J1 waits for an explicit yes. |
| J1 Table | done | 2026-11-22T22:34:00Z. Helpers only. The page does not read them. |
| J2 Writers | done | 2026-11-22T22:40:00Z. Rows are written. The page does not show them. |
| J3 Day list | live | 2026-11-22T23:04:00Z. Running commit `c5bdc4b`. |
| L1 Per-lane legend | live | 2026-11-22T23:53:00Z. Running commit `f764d9b`. |

## Decisions mirrored from the plan

- 2026-11-22T18:40:00Z — minute Tuya polling stays rejected. The minute tick reads SQLite only.
- 2026-11-22T18:46:30Z — one extra ITP status GET per real edge, no per-minute retry, no repeated 20s/60s pair.
- 2026-11-22T18:54:00Z — after a direct POST, one `itp` status GET in the existing timer follow-up window. Not both breakers.
- 2026-11-22T18:46:30Z — public page has no direct breaker switch. Admin arms the policy only.

## Do not touch

- `docs/plan_breakers.md` (closed, read-only poll).
- `LIGHT_SCHEDULE_PAUSED` and any POST/DELETE aimed at the lighting breaker.
- Company knowledge base. No device ids, secrets, or house notes there.
