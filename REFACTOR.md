# Power Monitor — план рефакторингу

Поточний `power_monitor.py` — ~2400 рядків. Нижче варіант розбиття за best practices.

## Рекомендована структура

```
power-monitor/
├── power_monitor/
│   ├── __init__.py       # app, lifespan — точковий вхід
│   ├── config.py        # константи, env (≈100 рядків)
│   ├── database.py      # init_db, kv_*, heartbeat, events, deye, boiler (≈250)
│   ├── dtek.py          # schedule, weather, alert (≈350)
│   ├── telegram_.py     # tg_send, webhook, photo, bot setup (≈200)
│   ├── detection.py     # analyze, watchdog (≈100)
│   ├── dashboard.py     # _build_dashboard_data, template render (≈900)
│   └── routes.py        # усі @app.get/post (≈250)
├── templates/           # опціонально — Jinja2
│   └── dashboard.html
├── power_monitor.py     # thin wrapper: from power_monitor import app
├── deye_reader.py
└── ...
```

## Що куди винести

| Модуль      | Зміст                                                                 |
|-------------|-----------------------------------------------------------------------|
| **config**  | API_KEYS, DB_PATH, STALE_THRESHOLD_SEC, DTEK_*, _WMO_EMOJI, UA_TZ тощо |
| **database**| init_db, _conn, kv_get/set, save/recent_heartbeats, events, deye, boiler, schedule |
| **dtek**    | _day_slots_to_48, _schedule_deviation, fetch_dtek_schedule, fetch_weather, fetch_alert |
| **telegram_**| save_tg_log, tg_send, update_chat_photo, setup_tg_bot, tg_webhook |
| **detection**| analyze, watchdog |
| **dashboard**| _build_dashboard_data, _build_update_fragments, HTML-шаблон (або Jinja2) |
| **routes**  | ep_heartbeat, ep_status, ep_dashboard_fragments, ep_dashboard, serve_icon, PWA, sw.js |

## Варіанти для HTML-шаблону

1. **Залишити в коді** — один великий f-string у `dashboard.py`, як зараз.
2. **Jinja2** — окремий `templates/dashboard.html`, можна перевикористовувати для fragments.
3. **Окремий .html** — статичний файл, підміняти плейсхолдери через `str.replace`.

## Переваги

- менший розмір кожного модуля (100–400 рядків),
- простіший пошук і навігація,
- зручніше тестувати окремі частини,
- менше ризиків при зміні одного домену (db, telegram, schedule).

## Мінімальний перший крок (без Jinja2) ✓ ЗРОБЛЕНО

1. `config.py` — перенести константи. ✓
2. `database.py` — перенести роботу з БД. ✓
3. Оновити імпорти в `power_monitor.py`. ✓
4. `detection.py` — analyze(), watchdog(), _voltage_* винесено. ✓

**Результат:** power_monitor.py ~1900 рядків, detection.py ~370, config.py має VOLTAGE_STATUS.
Потім можна винести telegram, dashboard і routes.
