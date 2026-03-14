# Проброс порту Deye для опитування з GCP

Коли сервер Power Monitor на Google Cloud опитує інвертор Deye безпосередньо (замість локального скрипта), інвертор повинен бути доступний з інтернету. Для цього потрібен **проброс порту** на MikroTik роутері та (рекомендовано) **файрвол**, щоб доступ мав лише IP сервера GCP.

## Передумови

- Інвертор Deye в локальній мережі (наприклад, 192.168.88.36)
- MikroTik RouterOS 7.x
- Статичний або динамічний публічний IP (для динамічного — використовуйте DynDNS: No-IP, DuckDNS тощо)

## Схема

```
[GCP Server 35.246.222.183] ----internet----> [Твій публічний IP:18899]
                                                       |
                                              [MikroTik NAT]
                                                       v
                                              [192.168.88.36:8899] (Deye)
```

## Крок 1: NAT (Dst-NAT) — проброс порту

У WinBox або CLI MikroTik:

**Solarman (порт 8899):**
```
/ip firewall nat add chain=dstnat dst-port=18899 protocol=tcp action=dst-nat to-addresses=192.168.88.36 to-ports=8899 comment="Deye Solarman"
```

**Або Modbus TCP (порт 502):** якщо 502 заблокований провайдером, використовуй нестандартний зовнішній порт:
```
/ip firewall nat add chain=dstnat dst-port=1502 protocol=tcp action=dst-nat to-addresses=192.168.88.36 to-ports=502 comment="Deye Modbus"
```

Заміни `192.168.88.36` на фактичний IP інвертора в твоїй мережі.

## Крок 2: Firewall — дозволити лише GCP

Щоб не відкривати Deye всьому інтернету, створи правило, яке дозволяє з’єднання **лише з IP Power Monitor на GCP**:

```
/ip firewall filter add chain=input protocol=tcp dst-port=18899 src-address=35.246.222.183 action=accept place-before=0 comment="Deye: allow GCP only"
/ip firewall filter add chain=input protocol=tcp dst-port=18899 action=drop comment="Deye: block others"
```

Якщо в тебе вже є загальний `input` drop для портів з інтернету, можеш додати лише `accept` для 35.246.222.183 перед цим drop.

## Крок 3: DynDNS (якщо IP динамічний)

Якщо провайдер змінює публічний IP, налаштуй DynDNS на MikroTik або на окремому пристрої й використовуй ім'я хоста замість IP:

```env
DEYE_POLL_IP=myhome.duckdns.org
DEYE_POLL_PORT=18899
DEYE_POLL_SERIAL=3586536011
```

## Крок 4: .env на сервері GCP

Додай у `/var/www/power-monitor/.env`:

**Solarman (поточна конфігурація):**
```env
DEYE_POLL_IP=твій_публічний_IP_або_хосту
DEYE_POLL_PORT=18899
DEYE_POLL_SERIAL=3586536011
DEYE_POLL_INTERVAL_SEC=30
DEYE_BATTERY_KWH=45
```

**Modbus TCP (альтернатива):**
```env
DEYE_POLL_IP=твій_публічний_IP_або_хосту
DEYE_POLL_PORT=1502
DEYE_POLL_SERIAL=
DEYE_POLL_INTERVAL_SEC=30
DEYE_BATTERY_KWH=45
```

## Перезапуск сервісу

```bash
cd /var/www/power-monitor && sudo systemctl restart power-monitor
```

## Перевірка

1. Переконайся, що NAT і firewall застосовані:  
   `ip firewall nat print` та `ip firewall filter print`
2. З сервера GCP:  
   `nc -zv твій_публічний_IP 18899` — має показувати успішне з’єднання
3. У логах Power Monitor:  
   `journalctl -u power-monitor -f` — має з’явитися рядок  
   `Deye server-side polling enabled: ... every 30s`

## Примітки

- Після налаштування локальний скрипт `deye_to_power_monitor.py` можна не запускати.
- Якщо змінюється публічний IP, онови `DEYE_POLL_IP` або використовуй DynDNS.
- IP GCP сервера: `35.246.222.183` (з user-memory.mdc).
