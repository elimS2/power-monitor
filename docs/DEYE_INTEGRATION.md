# Підключення інвертора Deye до Power Monitor

## Огляд

Інвертор Deye (Deye SUN-20K-SG05LP3 3-фазний) підключається до Power Monitor через локальний скрипт `deye_to_power_monitor.py`. Скрипт має запускатися на комп'ютері **у тій самій мережі**, що й інвертор (домашній ПК, Raspberry Pi тощо). Він читає дані по Modbus і відправляє їх на сервер Power Monitor через HTTPS кожні 30 секунд.

---

## Два способи підключення

| Спосіб | Порт | Бібліотека | Коли використовувати |
|--------|------|------------|----------------------|
| **Solarman V5** | 8899 | `pysolarmanv5` | Інвертор з WiFi-модулем Deye (підключення через хмару Solarman) |
| **Modbus TCP** | 502 | `pymodbus` | Прямий доступ до Modbus по локальній мережі |

Поточна установка використовує **Solarman V5**.

---

## Solarman V5 — поточна конфігурація

Інвертор спілкується через вбудований WiFi-модуль по протоколу Solarman. Доступ до інвертора можливий по IP у локальній мережі.

### Вимоги

1. **Серійний номер WiFi-модуля** (`DEYE_SERIAL`) — його можна взяти:
   - з застосунку Deye Cloud (номер пристрою),
   - з наклейки на WiFi-модулі.

2. **IP інвертора** — статичний DHCP або фіксована адреса в LAN.

### Залежності

```bash
pip install pysolarmanv5 requests python-dotenv
```

### Конфігурація (.env)

```env
DEYE_IP=192.168.88.36
DEYE_SERIAL=3586536011
POWER_MONITOR_URL=https://power.elims.pp.ua
POWER_MONITOR_KEY=<API key з Power Monitor>
```

- `DEYE_PORT` — за замовчуванням 8899 (можна не вказувати)
- `INTERVAL_SEC` — інтервал відправки в секундах (за замовчуванням 30)

### Запуск

```bash
cd power-monitor
python deye_to_power_monitor.py
```

Скрипт працює в нескінченному циклі. Зупинка — Ctrl+C.

---

## Modbus TCP (альтернатива)

Якщо інвертор доступний по Modbus TCP напряму (порт 502):

```env
DEYE_IP=192.168.88.36
DEYE_PORT=502
# DEYE_SERIAL не вказувати
POWER_MONITOR_URL=...
POWER_MONITOR_KEY=...
```

Залежності: `pip install pymodbus requests`

---

## Регістри Modbus (holding)

Використовувані регістри для Deye SUN-20K-SG05LP3 (unit/slave=1):

| Назва | Адреса | Тип | Масштаб | Опис |
|-------|--------|-----|---------|------|
| load_power_w | 653 | signed | — | Сумарне навантаження, Вт |
| load_l1_w, load_l2_w, load_l3_w | 650-652 | signed | — | Навантаження по фазах |
| grid_v_l1, grid_v_l2, grid_v_l3 | 598-600 | unsigned | ×0.1 | Напруга мережі, В |
| battery_soc | 588 | unsigned | — | Заряд батареї, % |
| battery_power_w | 590 | signed | — | Потужність батареї, Вт |
| battery_voltage | 587 | unsigned | ×0.01 | Напруга батареї, В |

---

## API Power Monitor

Ендпоінт: `POST /api/deye-heartbeat?key=<API_KEY>`

Тіло: JSON з полями `load_power_w`, `battery_soc`, `battery_power_w` тощо.

Сервер зберігає дані в таблицю `deye_log` і показує їх на дашборді.

---

## Важливо

- Скрипт **не запускається на сервері Power Monitor** — він у хмарі і не має доступу до домашньої мережі з інвертором.
- Скрипт має працювати постійно (systemd, Task Scheduler, screen тощо), щоб дашборд отримував актуальні дані.
- API-ключ береться з `API_KEYS` у `.env` на сервері Power Monitor (наприклад, `admin:key123` → використовуємо `key123`).
