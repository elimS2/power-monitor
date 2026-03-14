# WireGuard VPN: GCP сервер ↔ MikroTik клієнт

Доступ до Deye з GCP через VPN-тунель без third-party сервісів. Працює з сірим IP (CGNAT).

**Схема:** MikroTik підключається до GCP → GCP отримує маршрут до 192.168.88.0/24 → Power Monitor опитує Deye.

---

## Частина 1: GCP (WireGuard сервер)

### 1.1 Встановлення WireGuard

```bash
sudo apt update
sudo apt install -y wireguard
```

### 1.2 Генерація ключів

```bash
cd /etc/wireguard
sudo umask 077
sudo wg genkey | tee server_private.key | wg pubkey > server_public.key
```

Запам'ятай `server_public.key` — він піде в MikroTik як Peer Public Key.

### 1.3 Конфіг `/etc/wireguard/wg0.conf`

```ini
[Interface]
Address = 10.99.0.1/24
ListenPort = 51820
PrivateKey = <вміст server_private.key>
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ens4 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ens4 -j MASQUERADE

[Peer]
# MikroTik (home)
PublicKey = <MikroTik_Public_Key — згенеруємо далі>
AllowedIPs = 10.99.0.2/32, 192.168.88.0/24
```

Важливо: на GCP Ubuntu — `ens4`. Перевір: `ip link show`.

### 1.4 Firewall GCP

У Google Cloud Console → VPC → Firewall створюємо правило:

- **Name:** allow-wireguard
- **Direction:** Ingress
- **Targets:** All instances (або конкретний тег)
- **Source:** 0.0.0.0/0
- **Protocol/Port:** UDP 51820

Або через `gcloud`:

```bash
gcloud compute firewall-rules create allow-wireguard --allow=udp:51820 --source-ranges=0.0.0.0/0
```

### 1.5 IP forwarding

```bash
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 1.6 Запуск (після налаштування MikroTik)

```bash
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
sudo systemctl status wg-quick@wg0
```

---

## Частина 2: MikroTik (WireGuard клієнт)

### 2.1 Генерація ключів на MikroTik

У WinBox або CLI:

```
/interface wireguard add name=wg-gcp listen-port=0 private-key="<генеруй>"
```

Щоб згенерувати ключ: в WinBox System → Certificates, або через CLI:

```
/certificate add name=wg-temp key-size=256 key-type=ec
/certificate print detail
# Скопіюй "private-key" та "public-key"
/certificate remove [find name=wg-temp]
```

Простіший спосіб — згенерувати на GCP:

```bash
# На GCP
wg genkey | tee mikrotik_private.key | wg pubkey > mikrotik_public.key
cat mikrotik_public.key   # → PublicKey для GCP конфігу
cat mikrotik_private.key  # → PrivateKey для MikroTik
```

### 2.2 WireGuard інтерфейс на MikroTik

```
/interface wireguard add name=wg-gcp listen-port=0 private-key="<MikroTik_PrivateKey>"
/ip address add address=10.99.0.2/24 interface=wg-gcp
```

### 2.3 Peer (GCP сервер)

```
/interface wireguard peers add interface=wg-gcp public-key="<GCP_Server_PublicKey>" endpoint-address=35.246.222.183 endpoint-port=51820 allowed-address=10.99.0.0/24 persistent-keepalive=25
```

- `35.246.222.183` — IP твого GCP сервера (підстав свій, якщо інший)
- `allowed-address=10.99.0.0/24` — трафік до VPN-підмережі йде через тунель
- `persistent-keepalive=25` — важливо для CGNAT, щоб тунель не рвався

### 2.4 Маршрут до VPN-підмережі

```
/ip route add dst-address=10.99.0.0/24 gateway=wg-gcp
```

(192.168.88.0/24 залишається локальною мережею MikroTik — не маршрутизуй її в тунель.)

### 2.5 Firewall: дозволити forward з WireGuard до LAN

```
/ip firewall filter add chain=forward in-interface=wg-gcp out-interface=ether1 action=accept place-before=0 comment="WireGuard to LAN"
```

Замість `ether1` — інтерфейс, що веде до локальної мережі (де Deye). Перевір: `/interface print` — зазвичай це `ether1` або `bridge`.

### 2.6 Вмикаємо інтерфейс

```
/interface wireguard enable wg-gcp
```

---

## Частина 3: GCP — додати PublicKey MikroTik

Повернись на GCP. У `/etc/wireguard/wg0.conf` у блоці `[Peer]` підстав **MikroTik Public Key** (з кроку 2.1). Потім:

```bash
sudo systemctl restart wg-quick@wg0
```

---

## Частина 4: Power Monitor

У `/var/www/power-monitor/.env`:

```env
DEYE_POLL_IP=192.168.88.36
DEYE_POLL_PORT=8899
DEYE_POLL_SERIAL=3586536011
DEYE_POLL_INTERVAL_SEC=30
DEYE_BATTERY_KWH=45
```

Перезапуск:

```bash
sudo systemctl restart power-monitor
```

---

## Перевірка

1. **На GCP:** `sudo wg show` — має бути peer з handshake (last handshake: X seconds ago).

2. **З GCP до Deye:**
   ```bash
   ping 192.168.88.36
   nc -zv 192.168.88.36 8899
   ```

3. **Логи Power Monitor:** `journalctl -u power-monitor -f` — не повинно бути "Deye poll failed".

---

## Troubleshooting

| Проблема | Що перевірити |
|----------|----------------|
| Нема handshake | Firewall GCP UDP 51820, endpoint-address правильний, persistent-keepalive на MikroTik |
| Ping не проходить | MikroTik forward rule, AllowedIPs на GCP включає 192.168.88.0/24 |
| Deye poll failed | IP Deye 192.168.88.36, порт 8899, Solarman (DEYE_SERIAL) vs Modbus (порт 502) |

---

## Порядок налаштування (коротко)

1. GCP: apt install wireguard, згенеруй ключі, створ wg0.conf (без Peer поки)
2. GCP: згенеруй ключі для MikroTik, PublicKey → в MikroTik peer, PrivateKey → в MikroTik interface
3. MikroTik: створи wg-gcp, добав peer з endpoint=GCP_IP:51820
4. GCP: додай Peer з MikroTik PublicKey, AllowedIPs=10.99.0.2/32,192.168.88.0/24
5. Запусти wg-quick@wg0 на GCP, enable wg-gcp на MikroTik
6. Перевір handshake, ping 192.168.88.36 з GCP
