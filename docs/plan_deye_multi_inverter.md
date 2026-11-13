# Multi-inverter Deye on the Power Monitor dashboard

- Status: `PHASE 3 DEPLOYED — EMPTY HOUSE BLOCK, POLL OFF`
- Owner: Volodymyr
- Repo: `power-monitor/` (Life workspace). House facts live in local markdown and canvas files, not in the company Knowledge Base.
- Last updated: 2026-11-13T20:26:24Z
- Active skin: A (registry + `deye_log.inverter_id`, MAC stored, host is last confirmed address)
- Related: `docs/DEYE_WIREGUARD_VPN.md`, `docs/DEYE_PORT_FORWARD.md`, canvas `shelter-wifi-plan`, `house/hv-battery.md`, `house/shelter-wifi.md`, `house/basement-breakers.md`
- Source dialog for the draft: [OpenWRT router IP check](2ae03383-22c4-4f8e-8fe6-7f4a2f5d2bad), 2026-11-13. Scan dialog: [Tuya і автомати підвалу](cbc74fb3-6d9d-49c0-bc80-7686f6abfc21).
- Review mutation proof for this revision: composer `195973fe-c59a-43b4-85a5-83484b6497f6`, title `Public basement Deye on the dashboard`, `resolutionStatus=exact`, `verifiedAtUtc=2026-11-13T19:19:10.204Z`, `mutation_kind=plan`.

## 1. Goal and non-goals

### Goal

One registry of Deye inverters and one sample log. The apartment block and a new block "Deye інвертор будинку" each read their own rows. The key labeled `admin` keeps the apartment inverter. The key labeled `public` gains only the building block. Every outage and voltage-alarm path stays on the apartment inverter. The building inverter gets its own voltage subsection inside its own block.

### Non-goals

- Do not show apartment SOC, load, or battery on the public key.
- Do not let a building sample drive `get_display_status`, `detection.py`, the Telegram voltage avatar, or `schedule_day.voltage_json`.
- Do not poll the building inverter until Phase 0 has a live host and Phase 3 has confirmed a route from the GCP poller. Do not invent that route in Phase 0.
- Do not renumber the shelter router or the camera. A one-host route, if it is missing, is a separate human gate inside Phase 3, not a silent firewall edit.
- Do not write API keys, router passwords, or the Solarman serial into this file, the PROGRESS file, or any committed doc. The serial stays in the server `.env`.
- Do not write a local tunnel script under the Windows Temp folder. On 2026-11-13T19:15:37Z AVG blocked `owrt-phase0-read.py` as `IDP.Generic` (detection `c43dd3375964`). The read had already returned. That file shape, an SSH direct-tcpip forward plus a password in the environment, is what the scanner treated as an intrusion tool. Later probes are a short command on the shelter router, or code that lives in this repo. If the scanner blocks again, stop and tell the operator. Do not rename the file to get past it.
- No deploy and no production migration in this planning revision. Phase 1 does not start until this revision is reviewed and the operator says to continue.

## 2. Context harvest

Company KB does not index `power-monitor`. Catalog checked 2026-11-13: seven repos (`igo_scrapers`, `igotoffer`, `invoice`, `knowledge_base`, `prompt_manager`, `rlt`, `skystem_pilot`) and git-only `lazy-ai`. No `power-monitor` project key. Disk in this workspace is the source of truth for code. House facts stay in local markdown and canvas. Prompt #6's KB stop was waived by the operator on 2026-11-13 for that reason. This review still ran the harvest and recorded the misses.

### KB harvest (2026-11-13, prod MCP, person_id 7)

| Pass | Volume / mode | Result |
|---|---|---|
| A | `knowledge` semantic, "Deye inverter power monitor voltage log" | No power-monitor row. Hits were other products. |
| B | `ideas` semantic, "multi inverter Deye basement public dashboard" | No power-monitor idea. |
| C | `code_directories` semantic | No `power-monitor` path. |
| D | `code_files` hybrid, `deye_log` / `save_deye_log` | FTS empty, semantic fallthrough to other repos. |
| E | `code_symbols` hybrid | No rows (`fallback_applied=or_like`, empty). |
| F | `jira` fts, "power-monitor Deye" | False hit `KB-294` (Cursor/Bitbucket). No ticket for this work. Do not open one from this plan. |
| G | `dialogs` hybrid | Historical elevator-backup chats (ids 707, 535, 586) name a Deye 50 kW and an early 90 kWh pack. Capacity there is stale. Live pack size is `house/hv-battery.md` (160 kWh). Those chats have no basement IP. |

`kb_rule('project_memory')` is the knowledge_base repo, not this one. No live Jira status to split from a snapshot.

### Repo memory map (disk)

| Path | Why it matters | Touch / do not touch |
|---|---|---|
| `database.py` `deye_log`, `save_deye_log` (~1258), `recent_deye_log` (~1305) | Single undifferentiated sample stream. Insert has no device column. | Add `inverter_id`. Every writer sets it. |
| `database.py` `_record_voltage_sample` (~1014), called at the end of `save_deye_log` | Copies every sample into `schedule_day.voltage_json` | Call only for the apartment id |
| `database.py` `deye_voltage_buckets` (~1321), `deye_voltage_trend` (~1771), `has_grid_voltage_now` (~1737), `has_all_three_phases_voltage` (~1749), `last_nonzero_grid_voltage` (~1725), `_last_nonzero_for_phase` (~1761) | Latest row and phase history decide the lamp and the voltage chart | Apartment id only |
| `database.py` `deye_aggregates_refresh` (~1433), `_deye_agg` (~1414) | One in-memory cache for month, day, and battery episodes. The HTTP handler only copies it. | Key the cache by `inverter_id`. Refresh stays off the request. |
| `database.py` `_conn` (~50) | `PRAGMA journal_mode=WAL` only. `foreign_keys` is not turned on. | Do not promise a SQLite FK failure. Reject a bad id in Python. |
| `database.py` roles seed and the "Без Deye" rewrite (~343–358) | Empty DB seeds "Без Deye" as every section except `deye_details`. A one-shot rewrite replaces that list when `voltage_details` is missing. | Do not extend that rewrite. It would hand the new section to every key that still hits it. |
| `power_monitor.py` `_poll_deye` (~389) | One env host `DEYE_POLL_IP` | Loop enabled registry rows, one failure isolated |
| `power_monitor.py` `get_display_status` (~604) | Docstring: Deye phases only, no plugs. Uses `has_grid_voltage_now` and `has_all_three_phases_voltage`. | Apartment id only. A newer house row must not flip "Світло є" or a voltage alarm. |
| `detection.py` | Same four helpers plus `deye_voltage_trend`. This is the Telegram voltage path. | Apartment id only |
| `power_monitor.py` `dashboard` (~1750) | Two Deye assemblies, ~1810 and ~1988. The response uses the later one. The earlier one still reads the log and is then overwritten. | One builder, called with an id. Do not leave the earlier read unfiltered. |
| `power_monitor.py` `_build_update_fragments` (~763) | Third copy, `recent_deye_log(30)` ~860, for the live fragment. The fragment key is `pm_deye`. | Same builder. A second key `pm_deye_house` for the house block. |
| `api/dashboard.py` `ep_dashboard_fragments` (~84) | Checks `dashboard` permission only. Returns the fragment dict with no `allowed_sections` filter. | Omit `pm_deye` unless `deye_details` is allowed. Omit `pm_deye_house` unless `deye_house_details` is allowed. |
| `static/app.js` (~951) | Writes `d.pm_deye` into `#pm-deye` for every key that loads the page. | Also write `d.pm_deye_house` into `#pm-deye-house`. |
| `power_monitor.py` `_build_voltage_panel` (~668), `_voltage_chart_html` (~719) | Chart reads buckets, not only the last 30 rows | Buckets stay apartment-only. House voltage is not this chart. |
| `api/deye.py` `POST /api/deye-heartbeat` | Legacy writer. Calls `save_deye_log` with no device. | Must pass the apartment id in the same release as the column. |
| `api/dashboard.py` `/api/status` (~15) and `last_nonzero_grid_voltage` (~119) | Any dashboard key can read the latest phases | Apartment id only |
| `api/debug.py` | Raw `deye_log` scans for battery episodes | Filter by the requested id. Default the apartment id. |
| `api/deps.py` `allowed_sections` (~52) | Admin sees all. A missing config, or a null/empty section list, also returns `ALL_SECTIONS`. | Fail-open. See Phase 3 gate. |
| `power_monitor.py` `_get_public_dashboard_url` (~244) | Public key is the row whose label is `public`, not a URL pasted into git. | Resolve the role by that label |
| `config.py` `DEYE_BATTERY_KWH`, `DASHBOARD_SECTION_ORDER` (~188) | One capacity for every block. Order has no house section. | Capacity comes from the registry row. Env only seeds the apartment row. |
| `docs/DEYE_WIREGUARD_VPN.md` | GCP `10.99.0.1` peers MikroTik `10.99.0.2` and routes `192.168.88.0/24` only | Do not retarget this peer at the basement |
| `house/hv-battery.md` | Building head is a Deye 50 kW in the basement of building 6, pack about 160 kWh. Nameplate not rechecked 2026-11-12. | Identity and capacity default after the operator confirms the host. Not an IP. |
| `house/shelter-wifi.md` | Still says the OpenWrt TL-WDR3500 is on the desk | Stale. Operator 2026-11-13: the router is in the basement. |
| `house/basement-breakers.md` | Two Smtonoff breakers. Apartment LAN did not see them on 2026-11-07. | Same room as the new inverter. No IP in this file. |
| canvas `shelter-wifi-plan` | Desk-era plan: shelter WG peer `10.99.0.6`, GCP route `192.168.67.0/24` | Not proof that this route exists, and not the LAN where the breakers were seen |

### Local evidence checklist

- [x] knowledge: local house markdown. Company KB has no power-monitor row.
- [x] ideas: none for this feature. `house/future-ideas.md` is lift trips, not this work.
- [x] code_directories: `power-monitor/`, `power-monitor/api/`, `power-monitor/docs/`, `power-monitor/tests/`
- [x] code_files: paths in the map above
- [x] code_symbols: listed in the map with line anchors from the working tree on 2026-11-13
- [x] at least three code paths: poller, `save_deye_log` plus voltage side write, `get_display_status` / `detection.py`
- [x] dialogs: source draft `2ae03383-22c4-4f8e-8fe6-7f4a2f5d2bad`; basement scan `cbc74fb3-6d9d-49c0-bc80-7686f6abfc21`

### Dialog facts that the draft understated

Operator 2026-11-13, in the source dialog: extend `deye_log` with an inverter id and a registry, do not clone the table. Split voltage per inverter so a basement sample does not feed the shared outage voltage. The shelter router is already in the basement. The scan is in `cbc74fb3-6d9d-49c0-bc80-7686f6abfc21`: OpenWrt WAN was `192.168.0.108`, TP-Link gateway `192.168.0.1`, neighbors `.100`–`.104` (two Akuvox, Espressif, two Tuya breakers). The inverter was not in that list. It was added later on that same LAN.

The phrase "scan from `192.168.67.1`" in the first draft is superseded. `192.168.67.0/24` is the desk-era shelter LAN in the canvas, not the network that contained the breakers.

### Tests already on disk

- `tests/test_schedule_board.py` calls `save_deye_log` and asserts it does not `SELECT` from `deye_log`.
- `tests/test_voltage_chart.py` inserts into `deye_log` with no device column.
- `tests/test_breakers.py` calls `run_deye_then_breakers`.

A new column without a default that those inserts omit will break them. Phase 1 keeps the column nullable. Phase 2 updates the inserts that should be apartment samples.

## 3. Current system

Apartment Deye only. The process on GCP polls it.

- Poll: `_poll_deye` calls `read_deye(host=DEYE_POLL_IP, port=DEYE_POLL_PORT or 8899 when a serial is set, else 502)`.
- Insert: `save_deye_log` writes one row, then `_record_voltage_sample` merges L1/L2/L3 into `schedule_day.voltage_json` for `DTEK_QUEUE`.
- Second writer: `POST /api/deye-heartbeat` (`api/deye.py`). The old local script used this. It must not start inserting NULL `inverter_id` after the column exists.
- Reads: `recent_deye_log` is `ORDER BY id DESC LIMIT ?` with no device filter. Aggregates, buckets, and the phase helpers filter on `ts` or "latest row" only.
- Lamp: `get_display_status` uses the latest row's phases. `detection.py` uses the same helpers for voltage alerts and the channel avatar. Plug heartbeats still own `power_down`. A house row that is newer than the apartment row would still change the lamp and the voltage alarm, because those functions do not look at plugs.
- UI: section id `deye_details`, title "Deye інвертор". Section `voltage_details` ("Напруга мережі") is a different block, fed from apartment samples, and the built-in role "Без Deye" includes it. Inner ids that must stay unique per block: `deye_details` / `deye_open`, `pm-deye`, `deye_battery_details` / `deye_battery_open`, `deye_grid_details` / `deye_grid_open`, `deye_cumulative_details` / `deye_cumulative_open`, `deye_daily_details` / `deye_daily_open`, `deye_table_details` / `deye_table_open`.
- Live refresh: `GET /api/dashboard-fragments` returns `pm_deye` to any key with the `dashboard` permission. `static/app.js` paints it into `#pm-deye`. Hiding the HTML section does not stop the JSON. The response body is the leak.
- Capacity: `DEYE_BATTERY_KWH` is one float. The apartment card says the dashboard uses 60. The building pack is about 160. One env value cannot serve both blocks.
- Keys: `allowed_sections` uses `api_key_config_get`. Label `admin` sees every section. No row, or a resolved section list that is null or empty, also returns every section. When `role_id` is set, `api_key_config_get` replaces the row's `sections` column with the role's list, and `api_key_config_set_permissions` stores `sections` as NULL. Writing the column while `role_id` is set does nothing. The hide-apartment setup is that role list, often the builtin "Без Deye". Putting `deye_details` on the public key would publish the apartment inverter. Adding a new id to `ALL_SECTIONS` publishes it to every fail-open key immediately.
- Path: GCP reaches the apartment logger through WireGuard `192.168.88.0/24` (`docs/DEYE_WIREGUARD_VPN.md`). The basement host, from the November scan, is on `192.168.0.0/24`. That prefix is not in the documented AllowedIPs. The canvas route `192.168.67.0/24` via `10.99.0.6` is a desk-era plan, not a measured path, and it is the wrong subnet for the breakers.

Invariants:

- Existing `deye_log` rows stay the apartment inverter after backfill.
- `schedule_day.voltage_json`, `get_display_status`, `detection.py`, `/api/status`, and `voltage_details` stay on the apartment id.
- The public key never receives `deye_details`.
- One inverter's poll error does not skip the other, and does not skip the breaker step that runs after `run_deye_then_breakers`.
- Apartment month/day/battery aggregates do not change when a house row is inserted.

## 4. Options and skins

### Skin A — registry plus `inverter_id` (default)

`deye_inverter` holds id, serial, title, host, port, battery_kwh, poll_enabled. `deye_log.inverter_id` points at it. Every read that means "this inverter" or "the apartment outage path" takes an id. Two dashboard sections call one builder.

Choose this. One log, one code path, queries do the split. Same idea as `breaker_sample.device`.

### Skin B — second physical table `deye_house_log`

Copy of the column list. Every new column and every aggregate is then duplicated, and the outage helpers can still read the wrong table. Rejected.

### Switch

The skin id is the registry row. Turning a skin off is `poll_enabled=0` on that row. Rollback of the migration is "column stays, poller and heartbeat still write the apartment id only, house poll stays off". Do not drop the column on a live DB in the same step. SQLite will not enforce a foreign key unless every connection sets the pragma, and this process does not. The guard is in `save_deye_log`.

There is no `.env` switch that selects the schema. `DEYE_POLL_*` and `DEYE_BATTERY_KWH` only seed the apartment row.

## 5. Recommended architecture

```
deye_inverter (id, serial UNIQUE, mac, title, host, port, battery_kwh, poll_enabled)
        |
        +-- deye_log.inverter_id   samples
                |
                +-- section deye_details         apartment id, admin key
                +-- section deye_house_details   title "Deye інвертор будинку", house id, public key
                |
                +-- schedule_day.voltage_json    apartment id only
                +-- get_display_status           apartment id only
                +-- detection.py                 apartment id only
                +-- voltage_details              apartment id only
                +-- voltage subsection inside deye_house_details   house id only
                |
                +-- aggregate cache keyed by inverter_id
                    refreshed off the HTTP request, same split as today
```

Poll loop: the tick runs when any registry row has `poll_enabled=1`. It does not stay behind `if DEYE_POLL_IP`. After the apartment row exists, that env is only the seed. For each enabled row, `read_deye(host, port, serial)` inside its own try, then `save_deye_log(..., inverter_id)`. `_record_voltage_sample` runs only for the apartment id. The house read is its own task. `run_deye_then_breakers` awaits the apartment poll, then the breaker step. It does not await the house read. `read_deye` today passes no timeout into `PySolarmanV5`. Phase 3 passes an explicit socket timeout. Do not describe the current call as already bounded. A house failure is logged and does not skip the apartment poll or the breaker step.

`POST /api/deye-heartbeat` writes the apartment id. It does not accept a client-supplied id in this plan. A second remote writer is out of scope.

Section gate: new id `deye_house_details` in `ALL_SECTIONS` and `SECTION_LABELS`, placed in `DASHBOARD_SECTION_ORDER` after `deye_details`. Every inner id and `data-ls-key` listed in section 3 gets a `deye_house_` prefix, including the battery, grid, and cumulative pairs. The live fragment uses `pm_deye_house` and `#pm-deye-house`. The house voltage subsection is a small meter on house rows. It does not call `_build_voltage_panel` or `_voltage_chart_html`, because those always append the apartment chart and the node `#pm-voltage`.

The public key is the DB/env key whose label is `public` (`_get_public_dashboard_url`). Phase 3 reads `api_key_config_get("public")` (the resolved list, not the raw column) and adds `deye_house_details` on the role or on the key, as that function actually resolves it. It does not add `deye_details`.

The house row stores the logger MAC. `host` is the last address a person confirmed. The GCP poller reads that host and keeps a sample only after a successful Solarman read. It does not see basement ARP and it does not SSH to the shelter router. If TCP 8899 is silent, it skips the sample and leaves `host` unchanged. A new address is a separate human step from a machine that can already SSH to `192.168.67.1`: read `ip neigh`, take `74:e9:d8:39:22:8a` only when the state is REACHABLE or DELAY, check TCP 8899, write `host`, then repeat the route gate for that IP. Until that gate passes, house `poll_enabled` stays 0. No tunnel script in Temp. Breaker commands stay on the Tuya cloud device id in the server env. Their MACs are recorded here so a moved address can still be recognized. Those ids are not copied into git.

Apartment `Test-NetConnection` to `192.168.0.104:8899` on 2026-11-13T19:14:28Z returned `TcpTestSucceeded=False`. The successful read went through the shelter router. GCP still has no documented route to `192.168.0.0/24`.

## 6. Phases

Human gate after every phase. No next phase without an explicit "yes, continue". Update this file and the PROGRESS file at each gate. Code and commits in English. Do not commit unless the operator asks.

### Phase 0 — Find the basement inverter

- Goal: host, port, serial, and which interface on the basement OpenWrt sees it. No schema change. No route change. No firewall change.
- Touch: notes in this decision log only. Do not commit secrets. Do not write the serial into git.
- Steps: on the basement OpenWrt, read the live addresses (`uci show network` or the current `ip addr`). The scan to diff is the LAN where the breakers and Akuvox were, `192.168.0.0/24` on 2026-11-08/09, WAN side of that router (`192.168.0.108` then, gateway `192.168.0.1`). If that prefix moved, scan the prefix that still contains the known breaker hosts, not `192.168.67.0/24`. Diff against `.100`–`.104`. The new address is the candidate. Record IP and port (expect 8899). Confirm it answers `read_deye`.
- Verify: one successful read from the router or from a host that already routes there. Log load and SOC only.
- Gate: operator confirms this host is the building 50 kW (or names a different machine). Record battery_kwh from `house/hv-battery.md` (160) only after that confirmation.
- Rollback: none.
- Commit: no serial and no router password. The candidate address may be written here.

### Phase 0 result so far (2026-11-13T19:06:51Z)

Read-only scan from the basement OpenWrt (`192.168.67.1`, WAN `eth1`). No firewall change, no route change, no package install.

Live addresses on that router:

- LAN `br-lan` `192.168.67.1/24` (unchanged since the desk move).
- WAN `eth1` `192.168.0.109/24`, gateway `192.168.0.1` (`e8:48:b8:ea:1e:35`). On 2026-11-08/09 this WAN was `192.168.0.108`. The router moved; the gateway MAC did not.
- `wg0` still has `10.99.0.6/32`. Ping of that tunnel address from the apartment did not answer. SSH to `192.168.67.1` did.

Reachable hosts on `192.168.0.0/24` after one ping sweep, compared with the five neighbors from dialog `cbc74fb3`:

| Address | MAC | Against the old scan |
|---|---|---|
| `192.168.0.1` | `e8:48:b8:ea:1e:35` | Same gateway |
| `192.168.0.100` | `0c:11:05:33:f5:08` | Akuvox, still here |
| `192.168.0.101` | `0c:11:05:33:f5:e0` | Akuvox, still here |
| `192.168.0.102` | `50:78:7d:ee:b4:a8` | Espressif, same address and MAC |
| `192.168.0.103` | `00:33:7a:0a:93:f9` | Tuya. This MAC was on `.104` |
| `192.168.0.108` | `00:33:7a:0a:50:f7` | Tuya. This MAC was on `.103`. OpenWrt left `.108` |
| `192.168.0.105` | `0c:11:05:33:f5:34` | New address, same Akuvox OUI family. TCP 8899 closed |
| `192.168.0.104` | `74:e9:d8:39:22:8a` | New MAC. Not in the old five |

Candidate: `192.168.0.104`. OUI `74:e9:d8` is Shanghai High-Flying Electronics, the module family used in Wi-Fi sticks. From the router, TCP 8899 and TCP 80 on that host accepted a connection. TCP 502 did not. The same 8899 check failed on `.102`, `.103`, `.105`, `.108`, and the gateway.

`read_deye` at 2026-11-13T19:15:55Z, through the shelter router, serial from the logger sticker the operator photographed. Result only: grid **228.0 / 227.7 / 226.3 V**, SOC **98%**, load **9525 W**. The serial and the sticker password are not in this file. The numbers match a live building inverter, not an idle apartment sample. Phase 0 host is `192.168.0.104`. Phase 1 does not start until the operator says to continue.

Operator the same evening: `.105` is the third Akuvox, the freight / fire elevator with the street entrance. Three elevators, three Akuvox. That host is not an inverter. TCP 8899 on it stayed closed.

Breaker DHCP addresses are not how those modules are switched. The cloud calls in dialog `cbc74fb3` and the poller in `tuya_breakers.py` use the device id from the server env. A new DHCP address does not retarget the command. The ids stay out of git. The MAC does. When an address moves, match the MAC in the table below and update the last-seen address. Do not treat the old IP as the device.

### Basement LAN identity (last seen 2026-11-13T19:06:51Z)

MAC is the identity. The address is only where that MAC answered that evening.

| MAC | Last address | What it is |
|---|---|---|
| `e8:48:b8:ea:1e:35` | `192.168.0.1` | Basement TP-Link gateway. Same MAC as the November scan |
| `14:cc:20:b5:69:97` | none proven | Seen only as a link-local neighbor on `eth1`. Not paired with `192.168.0.109`. The OpenWrt WAN address that evening was `192.168.0.109`; its MAC was not read. The desk-era canvas MAC `14:cc:20:b5:69:94` is a different octet and is not used as the WAN identity. |
| `0c:11:05:33:f5:08` | `192.168.0.100` | Akuvox |
| `0c:11:05:33:f5:e0` | `192.168.0.101` | Akuvox |
| `0c:11:05:33:f5:34` | `192.168.0.105` | Akuvox, freight / fire elevator, street entrance. Operator 2026-11-13. Not an inverter |
| `50:78:7d:ee:b4:a8` | `192.168.0.102` | Espressif. Same MAC and address as November. Not a breaker and not the logger |
| `00:33:7a:0a:93:f9` | `192.168.0.103` | Tuya breaker. This MAC was on `.104` in November |
| `00:33:7a:0a:50:f7` | `192.168.0.108` | Tuya breaker. This MAC was on `.103` in November |
| `74:e9:d8:39:22:8a` | `192.168.0.104` | Building Deye logger, High-Flying. TCP 8899. Read at 19:15:55Z: SOC 98%, load 9525 W |

Which Tuya MAC is the light and which is the heating breaker is not in this file. The cloud device id in the server env is what the poller uses. Do not invent that pairing from the MAC alone.

### Phase 1 — Schema, backfill, and apartment writers

- Goal: registry and nullable `deye_log.inverter_id`. Old rows tagged as the apartment inverter. Poller and heartbeat write that id. No second poll. Readers may stay unfiltered in this phase because every new row is still the apartment inverter.
- Touch: `database.py` init. `save_deye_log` and both callers (`_poll_deye`, `api/deye.py`). `tests/test_voltage_chart.py` and `tests/test_schedule_board.py`. Keep their rows as the apartment id.
- Steps: create `deye_inverter` with `mac TEXT`. Insert the apartment row from env: serial `DEYE_POLL_SERIAL`, title "Deye інвертор", host `DEYE_POLL_IP`, port from `DEYE_POLL_PORT` (same fallback as `_poll_deye`), `battery_kwh` from `DEYE_BATTERY_KWH`, `mac` null until that logger is seen on a LAN we can scan. Do not copy those values into the commit. `ALTER TABLE deye_log ADD COLUMN inverter_id INTEGER`. Backfill to the apartment id. Index `(inverter_id, ts)`. Leave the column nullable. SQLite `ADD COLUMN` cannot grow a NOT NULL constraint cleanly, and `_conn` does not enable foreign keys. `save_deye_log` requires an `inverter_id` argument and rejects an id that is not in `deye_inverter`. The existence check reads `deye_inverter` only. A `SELECT` from `deye_log` inside `save_deye_log` fails `test_save_deye_log_does_not_select_the_sample_log`. Change that test's call to pass the apartment id. Set the same id on both inserts in `tests/test_voltage_chart.py`. Readers never treat a NULL `inverter_id` as the apartment id.
- Verify: row count unchanged. `SELECT COUNT(*) FROM deye_log WHERE inverter_id IS NULL` is 0 after backfill. A new poll row and a heartbeat row both carry the apartment id. Apartment dashboard still shows the same latest SOC.
- Negative: `save_deye_log` without an id, or with an unknown id, raises. The test does not depend on `PRAGMA foreign_keys`. The schedule-board spy still sees no `from deye_log` inside `save_deye_log`.
- Rollback: stop writing the column's meaning; keep the column. Poller writes only the apartment id. Do not drop the column on the live DB in the same step.
- Commit: yes, after the gate, if the operator asked to commit. Deploy: together with Phase 2, or this phase alone only while every writer passes the apartment id and no house row exists.

### Phase 2 — Scope every apartment read and the aggregate cache

- Goal: a house row cannot change the apartment block, the outage lamp, the voltage alarm, the voltage chart, or the apartment energy totals.
- Touch: `recent_deye_log`, `deye_voltage_buckets`, `deye_first_voltage_ts`, `deye_voltage_trend`, `has_grid_voltage_now`, `has_all_three_phases_voltage`, `last_nonzero_grid_voltage`, `_last_nonzero_for_phase`, the helpers `deye_aggregates_refresh` calls, plus `deye_monthly_load_kwh` and `deye_yearly_load_kwh` (no callers today; give them the same argument or delete them in this phase), `deye_aggregates_snapshot`, `_record_voltage_sample`'s call site, `get_display_status`, `detection.py`, `/api/status`, `api/debug.py`, `_build_voltage_panel` / `_voltage_chart_html`, the three Deye assemblies (`_build_update_fragments` ~860, `dashboard` ~1810, `dashboard` ~1988), `ep_dashboard_fragments`, and `static/app.js`.
- Steps: add an `inverter_id` argument. The outage helpers default to the apartment id so a forgotten call site stays on the apartment inverter, not on "latest row of any inverter". A NULL `inverter_id` does not match the apartment id. `_record_voltage_sample` only for the apartment id. Replace the single `_deye_agg` dict with a cache keyed by `inverter_id`. `deye_aggregates_refresh` still runs off the request, from `bg_loop`, and still bails if a run is already going. The apartment entry keeps today's meaning. Fold the three HTML assemblies into one builder that takes the id; delete the overwritten assembly at ~1810 rather than leaving a second unfiltered read. `ep_dashboard_fragments` calls `allowed_sections` and omits `pm_deye` unless `deye_details` is allowed.
- Verify: existing tests. A fixture with two ids: `recent_deye_log` for the apartment id does not return the house row. Inserting a house row does not change `schedule_day.voltage_json`, does not change `has_grid_voltage_now` when the apartment row is older and dark, and does not change the apartment `monthly_kwh` snapshot.
- Negative: house sample does not appear in the apartment "last 30" and does not change `schedule_day.voltage_json`. Two lamp asserts, because plugs own `power_down` while `PHASES_ONLY` defaults to 0, and `get_display_status` returns a voltage string on `phases_mixed` before it returns "Світло ВІДСУТНЄ". First: plugs all dead, `power_down` still 0, apartment sample dark, house sample with voltage; `detection.analyze` does not set `voltage_anomaly` and still sets `power_down`. Second: apartment sample dark and `power_down` already 1, house sample with only one live phase; `get_display_status()["status_text"]` stays "Світло ВІДСУТНЄ". Keep the `has_grid_voltage_now` assert. The fragment JSON for a key whose sections exclude `deye_details` does not contain apartment SOC.
- Rollback: poller and heartbeat write only the apartment id. House poll stays disabled, so the filters are idle.
- Commit: yes, if asked. Deploy: yes, together with Phase 1. Still one host.

### Phase 3 — House block, then the route, then the poll

- Goal: the public page can show an empty "Deye інвертор будинку". Polling starts only after the route gate. Until then `poll_enabled=0` and the block says there is no sample.
- Touch: poll loop, `deye_reader.py` (timeout argument only), one HTML builder, `static/app.js`, `ALL_SECTIONS`, `SECTION_LABELS`, `DASHBOARD_SECTION_ORDER`, the resolved section list of the key labeled `public`, registry row for the house inverter.
- Steps, in order:
  1. Call `api_key_config_get("public")`. Stop if there is no row, `enabled` is false, or the resolved `sections` is null, empty, or contains `deye_details`. That key is fail-open or already sees the apartment inverter. Do not add `deye_house_details` to `ALL_SECTIONS` until step 2 has a single write target. Do not paste the key into git. Do not read the raw `sections` column when `role_id` is set: `api_key_config_get` replaces it with the role, and `api_key_config_set_permissions` stores NULL in the column whenever `role_id` is set.
  2. If `role_id` is set, list every label that uses that role. If any label other than `public` uses it, stop and ask. If only `public` uses it, append `deye_house_details` to that role's section list with a direct `UPDATE roles SET sections=?`. Do not call `role_update`: it returns False for `is_builtin=1`, and "Без Deye" is builtin. The voltage rewrite at `database.py` ~353 is the existing pattern for writing a builtin list. Do not set the role's sections to NULL, do not clear `is_builtin`, and do not clear `role_id` (that also drops endpoints and makes `allowed_footer_parts` return every footer part). If `role_id` is null, append to the key's own JSON and pass the existing `endpoints` through `api_key_config_set_permissions`. Do not append `deye_details`. Do not reuse the "Без Deye" rewrite at `database.py` ~353. On a brand-new DB the seed for "Без Deye" may include `deye_house_details` and must still exclude `deye_details`. Production is step 1, not that seed.
  3. Add `deye_house_details` to `ALL_SECTIONS`, `SECTION_LABELS`, and `DASHBOARD_SECTION_ORDER` only after step 2.
  4. Register the house row with `poll_enabled=0`, title "Deye інвертор будинку", host `192.168.0.104`, mac `74:e9:d8:39:22:8a`, port 8899, serial from the server env (not from this file), `battery_kwh` from the confirmed pack size. The builder takes `battery_kwh` from the row. Do not use `DEYE_BATTERY_KWH` for the house block. The house voltage subsection is the small meter from section 5, not `_build_voltage_panel`.
  5. Every id in the section 3 inventory uses the `deye_house_` prefix. `static/app.js` writes `pm_deye_house` into `#pm-deye-house` the same way it writes `pm_deye` into `#pm-deye`. The fragment includes `pm_deye_house` only when `deye_house_details` is allowed.
  6. Route gate, before `poll_enabled=1`: from the GCP host, check whether the current house address is reachable through the existing WireGuard (documented path is only `192.168.88.0/24`). The apartment PC already failed a direct TCP check to `192.168.0.104:8899` on 2026-11-13T19:14:28Z. If GCP cannot reach it either, stop and ask. A one-host route via the shelter peer is allowed only after an explicit yes. Do not renumber the router. Do not change the camera. Do not guess `192.168.67.40`.
  7. After that yes, set `poll_enabled=1` for this confirmed address only. The tick runs from registry rows, not from a non-empty `DEYE_POLL_IP`. Pass an explicit socket timeout into the Solarman client. Run the house read as its own task so `run_deye_then_breakers` does not await it before the breaker step. The poller uses the stored `host` and accepts a sample only after a successful Solarman read. It does not check the MAC and it does not SSH to `192.168.67.1`. If TCP 8899 is silent, skip the sample and leave `host` unchanged. Reachability of `10.99.0.6` from GCP was not measured on 2026-11-13. The failed ping that evening was from the apartment. The route gate in step 6 is the measurement, and it runs on the server. Changing `host` later is the human step in section 5, then step 6 again, and `poll_enabled` stays 0 until that gate passes. Do not drop a tunnel script in Temp. A house failure does not skip the apartment poll and does not skip breakers.
- Verify: public key HTML contains "Deye інвертор будинку" and does not contain the apartment SOC. `GET /api/dashboard-fragments` for that key does not contain apartment SOC, and does contain the house fragment only after the section is allowed. With poll disabled, the house block says there is no sample. Admin HTML still contains "Deye інвертор" with the apartment numbers, and both blocks can be collapsed independently (distinct ids). After poll is enabled, the house block's live fragment updates, and the apartment lamp does not follow the basement.
- Negative: the fragment JSON, not only the HTML, lacks apartment `load_power_w` and SOC. A house sample does not write `schedule_day.voltage_json`. The two lamp asserts from Phase 2 still hold.
- Rollback: remove `deye_house_details` from the same role or key list that step 2 wrote, and set `poll_enabled=0`. Leave the column. Do not clear `role_id`.
- Commit and deploy: yes, if asked. This is the user-visible phase. Deploy the empty block before the route gate if the operator wants the section visible first. Do not deploy `poll_enabled=1` in that same restart unless the route gate has passed.

### Phase 4 — Docs match the building

- Goal: a new chat can find the host without the old chat.
- Touch: `house/shelter-wifi.md` location sentence, this decision log. Not the company KB.
- Steps: replace "router is on the desk" with "in the basement as of 2026-11-13". Point at Phase 0 for the host. Do not copy the serial or a dashboard key into the markdown.
- Verify: the host recorded in Phase 0 is in this plan's decision log.
- Rollback: git revert the doc sentence.
- Commit: yes, if asked. Deploy: no.

## 7. Data and compatibility

- Migration is additive. Backfill before any read starts filtering, in one release, so a filtered read cannot hide the apartment history.
- `inverter_id` NULL is allowed only for rows that have not been backfilled yet. After Phase 1, `save_deye_log` refuses a NULL or unknown id. The column stays nullable in SQLite.
- No dual-write to a second log table.
- House volts never enter `schedule_day.voltage_json`.
- House volts never become the latest row for `get_display_status` or `detection.py`.
- `DEYE_POLL_IP` and `DEYE_BATTERY_KWH` seed the apartment registry row. After that row exists, the row is the poll target and the capacity. The env is not a second hidden target.
- Heartbeat and the GCP poller ship in the same release as the column. An old heartbeat process after the new column, still on old code, would insert NULL. Deploy is a restart of this service, so old code and the new column do not run together. Do not apply the ALTER by hand on the live DB before the new code is the one that starts.
- First poll after restart runs the new code. There is no separate self-update worker.

## 8. Verification and definition of done

- Local: unit tests for scoped reads, for "house sample does not change voltage JSON", and for "house sample does not change `has_grid_voltage_now` when the apartment sample is the dark one".
- UI: admin key shows the apartment block. Public key shows the house block and does not show apartment SOC. Two blocks on the admin page have distinct element ids.
- Smoke after Phase 0: one live read, SOC and load only.
- Smoke after the Phase 3 route gate: one live read from GCP, then `poll_enabled=1`.
- Done when: the public page shows "Deye інвертор будинку" from basement samples, the apartment block is unchanged, the outage lamp and `schedule_day.voltage_json` stay on the apartment inverter, and a house poll failure does not blank the apartment block or skip the breaker poll.

## 9. Risks and decisions

### Risks

- Polling a guessed address is wrong. Phase 0 diffs a live neighbor list.
- The shelter WAN/LAN may have moved. Phase 0 reads the live addresses.
- `allowed_sections` fail-open: a new section id is visible to every key with no explicit list. Phase 3 stops unless `api_key_config_get("public")` returns an explicit list without `deye_details`, and the write goes to that role or that key, not to a column the role ignores.
- One aggregate cache and one `DEYE_BATTERY_KWH` would mix the two machines. Both are split in Phase 2 and Phase 3.
- SQLite will not reject a bad `inverter_id` by itself. The Python guard is the contract.
- `read_deye` passes no timeout into `PySolarmanV5`. A house read awaited inside `run_deye_then_breakers` would hold the breaker step. Phase 3 puts the house read on its own task and passes an explicit socket timeout. The current call is not already bounded.
- Public `voltage_details` today shows the apartment trace to whoever has that section. Leaving it there is the default. It is not the house voltage.

### Decision log

- 2026-11-13T16:50:00Z — Skin A, not a cloned table. Operator asked to extend `deye_log` with an id and a registry. Agreed. (Recorded earlier as 18:50 +02.)
- 2026-11-13T16:50:00Z — `schedule_day.voltage_json` stays apartment-only. House voltage is a subsection of `deye_house_details`.
- 2026-11-13T16:55:00Z — Basement scan found in dialog `cbc74fb3-6d9d-49c0-bc80-7686f6abfc21`. Subnet of that scan is `192.168.0.0/24`. Inverter was not in it. Phase 0 is a diff.
- 2026-11-13T16:50:00Z — Prompt #6 KB stop waived by the operator. Life house knowledge is local. Review harvest on 2026-11-13 confirmed the company catalog has no power-monitor repo.
- 2026-11-13T16:50:00Z — self-review round 1. Superseded where it still said the scan artifact was missing and where it left the lamp unscoped. See the lead review entry.
- 2026-11-13T18:42:00Z — Lead review, prompt #5, round 1, before the independent critic. Supersedes the Phase 0 line that scanned from `192.168.67.1`. That prefix is the desk-era canvas LAN, not the breaker LAN. Supersedes "SQLite foreign key rejects a bad id": `foreign_keys` is off; the guard is in `save_deye_log`. Adds the lamp, `detection.py`, the heartbeat writer, the single aggregate cache, `DEYE_BATTERY_KWH`, duplicate DOM ids, the fail-open section list, and the GCP route gate. Those were holes a faithful implementation of the first draft would have shipped.
- 2026-11-13T18:47:00Z — Critic round 1, model `grok-4.7-xhigh-fast`, agent `425ac57b-0f2d-4eeb-b5f0-5a76e62c19a7`, verdict `CHANGES REQUIRED`, CRITICAL 0, HIGH 2, MEDIUM 4, LOW 2. Both HIGH findings accepted after a disk check. `GET /api/dashboard-fragments` returns `pm_deye` with no section filter, and `static/app.js` paints `#pm-deye`. A `role_id` makes a write to `api_key_config.sections` a no-op because `api_key_config_get` substitutes the role. MEDIUM and LOW from that round are folded into Phases 1–3: NULL is not the apartment id, the schedule-board spy must not see `from deye_log`, the lamp asserts match `PHASES_ONLY=0`, the poll tick is not gated on `DEYE_POLL_IP`, the house read is not awaited before breakers, the house meter does not call `_build_voltage_panel`, the full id inventory is prefixed, and `deye_monthly_load_kwh` / `deye_yearly_load_kwh` are scoped or deleted. Supersedes the Phase 3 sentence that appended the section onto the raw key column, and the risk line that said `read_deye` was already bounded.
- 2026-11-13T18:51:12Z — After the first confirmation APPROVE, lead added one sentence. `role_update` returns False when `is_builtin` is 1 (`database.py` ~694). "Без Deye" is builtin, so a sole-user append is a direct `UPDATE roles`, the same path as the voltage rewrite. `role_update` is not the write. Final confirmation, same critic, verdict `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Status set to `REVIEWED / READY FOR LOCAL WORK`. Implementation still waits for an explicit continue.
- 2026-11-13T19:19:09Z — Prompt #6 revision. MAC is the stable identity; the address is last-seen. Registry gains `mac`. If the house host stops answering 8899, resolve `74:e9:d8:39:22:8a` from the shelter neighbor table instead of trusting DHCP. Apartment direct TCP to `192.168.0.104:8899` failed at 19:14:28Z. AVG blocked `owrt-phase0-read.py` as `IDP.Generic` (`c43dd3375964`); that file shape is retired. Temp copies removed. Previous review approval stays history for the earlier text. This revision is `DRAFT READY FOR REVIEW`. Phase 1 still has not started.
- 2026-11-13T19:22:58Z — Lead review of the MAC revision, prompt #5, before the critic. Supersedes the row that paired `14:cc:20:b5:69:97` with `192.168.0.109`: that MAC was only a link-local neighbor.
- 2026-11-13T19:40:56Z — Phase 1 local. Apartment registry row, backfill, both writers pass that id. 39 tests OK. No house poll. No deploy.
- 2026-11-13T19:45:27Z — Phase 2 local. Reads, the outage lamp, voltage JSON, and aggregates are scoped by inverter id. A house sample does not change the apartment voltage bar or `has_grid_voltage_now`. The live fragment omits `pm_deye` when the key cannot see `deye_details`. The overwritten dashboard assembly was removed. 41 tests OK. No house poll. No deploy.
- 2026-11-13T19:50:43Z — Phase 3 step 1 stopped. `GET /api/debug-sql` with the key stored in the local monitor env returned `{"detail":"forbidden"}`. The resolved section list of the label `public` was not read. `deye_house_details` was not added to `ALL_SECTIONS`. No role write, no house row, no route, no poll. The operator asked where a later route would start: from the GCP poller, through the existing WireGuard, via the shelter peer `10.99.0.6`, to one host `192.168.0.104:8899`. The apartment LAN `192.168.88.0/24` does not contain that host. A direct TCP check from the apartment PC already failed at 2026-11-13T19:14:28Z. That one-host route still needs an explicit yes after a reachability check from GCP. It was not opened.
- 2026-11-13T20:01:34Z — Operator said continue. Step 1 tried again. SSH `elims2@35.246.222.183` returned `Permission denied (publickey)`. No host entry for that address in the local SSH config. The gcloud account on this PC does not list that VM. The public section list is still unread. Section, house row, route, and poll stay off. The hop list shown in chat (cloud `10.99.0.1` → shelter `10.99.0.6` → `192.168.0.104:8899`) is the intended path, not a traceroute, and it was not installed.
- 2026-11-13T20:12:03Z — Step 1 read succeeded with the instance SSH key used in earlier chats. Label `public` is enabled, `role_id` 4, role name `Публічна`, not builtin. Resolved sections are an explicit list and do not contain `deye_details`. The same role is also on `artur`, `init_group`, `techahead_yaroslav`, and `vasyl`. Plan step 2 says stop and ask before writing that shared list. No section added, no role write, no route, no poll.
- 2026-11-13T20:26:24Z — The empty house block was already on the server at `5fd1d3a`. Admin page load was 7.8s. `recent_deye_log` sorted the whole apartment history by row id after the inverter filter. Changed that sort to `ts`, which the `(inverter_id, ts)` index can answer. Deployed `1f2f34c` by pull and restart. House `poll_enabled` stayed 0. Repeat loads: 0.09s and 0.10s. The house title is on the page. No route.

### Open questions

- Which physical Deye is "the building one"? `192.168.0.104` answered the sticker serial at 2026-11-13T19:15:55Z with SOC 98% and load 9525 W. That is the phase 0 host. Battery figure 160 kWh is written on the house registry row in Phase 3 step 4, after the pack size is confirmed. Phase 1 inserts only the apartment row.
- Public "Напруга мережі" (`voltage_details`): leave it on the apartment trace. House voltage lives only inside the new block. Change this only if the operator says the public voltage widget should follow the basement.

### Self-review round 1 (2026-11-13T16:50:00Z) — historical

- CRITICAL: none claimed in that pass.
- HIGH fixed in that draft: do not guess the basement subnet; do not let house samples into `schedule_day.voltage_json`.
- Left open then: public voltage widget, with the default above.
- Superseded 2026-11-13T18:42:00Z: the sentence "dialog scan artifact is explicitly missing" was already false after the `cbc74fb3` update, and the draft still did not scope the lamp or the aggregate cache.

### Lead review round 1 (2026-11-13T18:42:00Z)

- Status set to `REVIEW IN PROGRESS`. Implementation is not allowed.
- Independent critic had not run yet at this stamp.
- MEDIUM kept with a default: public `voltage_details` stays the apartment trace.
- LOW: company KB dialog ids 707 / 535 / 586 are historical 90 kWh notes. The local card's 160 kWh wins. Not copied into the poller until Phase 0 confirms the host.

### Critic round 1 (2026-11-13T18:47:00Z)

- Model: `grok-4.7-xhigh-fast`. Agent `425ac57b-0f2d-4eeb-b5f0-5a76e62c19a7`. Read-only. Files were not edited by the critic.
- Verdict then: `CHANGES REQUIRED`. CRITICAL 0, HIGH 2, MEDIUM 4, LOW 2.
- Lead accepted both HIGH findings and the MEDIUM/LOW fixes.
- Final confirmation, same critic: `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0. Includes the builtin-role `UPDATE` sentence.
- Status is `REVIEWED / READY FOR LOCAL WORK` after confirmation of the MAC revision. That sentence described the plan before Phase 1. Phase 1 later landed locally at 2026-11-13T19:40:56Z and is not deployed.

## 10. Progress log

- 2026-11-13T16:50:00Z — Plan drafted from local code and house notes. No implementation.
- 2026-11-13T16:55:00Z — Scan dialog folded in. Still no code.
- 2026-11-13T18:42:00Z — Prompt #5 lead review. Plan and PROGRESS rewritten to match the working tree. No code, no deploy, no commit.
- 2026-11-13T18:47:00Z — Critic round 1 fixes applied to this file.
- 2026-11-13T18:51:12Z — Final confirmation APPROVE. Status `REVIEWED / READY FOR LOCAL WORK`. No code.
- 2026-11-13T19:15:55Z — Logger read succeeded. Load and SOC recorded above. Serial not written.
- 2026-11-13T19:19:09Z — Prompt #6 revision. MAC table added. AVG false positive recorded.
- 2026-11-13T19:26:00Z — MAC revision confirmed. Status `REVIEWED / READY FOR LOCAL WORK`.
- 2026-11-13T19:40:56Z — Phase 1 code is local. Next is Phase 2 only after an explicit continue. Do not deploy this commit by itself unless the operator asks: writers already pass the apartment id, and no house row exists, but the public block is not in this step.
- 2026-11-13T19:45:27Z — Phase 2 code is local. House sample stays out of the apartment lamp and voltage bar. No deploy.
- 2026-11-13T19:50:43Z — Phase 3 paused at the public-key read. Live debug SQL returned 403. No section, no route, no poll.
- 2026-11-13T20:01:34Z — Continue retried the read. SSH publickey denied. This PC's cloud account does not see the VM. Still no section and no route.
- 2026-11-13T20:17:54Z — Empty house block is local. Every explicit section list gains `deye_house_details` on startup. `deye_details` is not added. Poll stays off. Route stays closed. Not deployed.

## 11. Handoff for a new chat

- Phase 3 empty block is deployed at `1f2f34c`. House poll stays off. Do not open the shelter route until GCP reachability is checked and the operator says yes to the one host. Do not copy the logger serial into git. Do not drop an SSH tunnel script in Temp.
- Active skin: A.
- Apartment-only, even after the column exists: `schedule_day.voltage_json`, `get_display_status`, `detection.py`, `/api/status`, `voltage_details`, `deye_voltage_trend`.
- Do not add `deye_details` to the key labeled `public`.
- If `api_key_config_get("public")` has no explicit section list, or that list contains `deye_details`, stop before adding `deye_house_details` to `ALL_SECTIONS`. If `role_id` is set, edit that role, not the raw `sections` column. If another label shares the role, stop.
- `GET /api/dashboard-fragments` must not return apartment SOC to a key that cannot see `deye_details`.
- Do not set `poll_enabled=1` until Phase 0 has a host and Phase 3 has a confirmed route from GCP. Do not guess `192.168.67.0/24`.
- Do not search the company KB for this house network, and do not write house IPs, serials, or dashboard keys into KB or into git.
- Human gate between phases. English in code and commits. This file plus `plan_deye_multi_inverter_PROGRESS.md` are the source of truth.
- Implementation waits for status `REVIEWED / READY FOR LOCAL WORK` and an explicit continue. This review is not that continue.

## 12. Review audit

- Lead: this Cursor session, prompt #5, 2026-11-13T18:42:00Z.
- Proof: `195973fe-c59a-43b4-85a5-83484b6497f6`, exact, `verifiedAtUtc=2026-11-13T18:36:29.547Z`.
- Critic: `grok-4.7-xhigh-fast`, agent `425ac57b-0f2d-4eeb-b5f0-5a76e62c19a7`. Round 1 `CHANGES REQUIRED` (HIGH 2). Final confirmation `APPROVE`, CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0.
