# Керування розумною розеткою Nous (Tuya)

## Огляд

Блок «Розумна розетка» на дашборді дозволяє вмикати й вимикати розетку Nous/Tuya. Потребує локального скрипта `plug_controller.py`.

## Архітектура

- **Дашборд** → натискання кнопки → `POST /api/plug-set?state=on|off`
- **Сервер** зберігає команду в `kv`
- **plug_controller.py** (дома) раз на 15 с запитує `GET /api/plug-pending`, виконує команду через tinytuya, повідомляє стан через `POST /api/plug-done`

## Отримання Device ID та Local Key

```bash
pip install tinytuya
python -m tinytuya wizard
```

Пройди кроки майстра — він покаже Device ID, IP та Local Key для кожної розетки.

## Конфігурація (.env)

```env
PLUG_DEVICE_ID=bfxxxxxxxxxxxxxx
PLUG_IP=192.168.88.XXX
PLUG_LOCAL_KEY=xxxxxxxxxxxxxxxx
PLUG_VERSION=3.3
POWER_MONITOR_URL=https://power.elims.pp.ua
POWER_MONITOR_KEY=<API key>
INTERVAL_SEC=15
```

## Запуск

```bash
cd power-monitor
python plug_controller.py
```

Рекомендовано запускати через systemd або Task Scheduler разом з `deye_to_power_monitor.py`.
