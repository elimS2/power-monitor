# Деплой Power Monitor

## Ручний деплой

```bash
cd /var/www/power-monitor && git pull && sudo systemctl restart power-monitor
```

## Автоматичний деплой (#автооновити)

Сервіс сам перевіряє репо кожні ~5 хвилин. Якщо в повідомленні останнього коміту є тег `#автооновити` або `#autodeploy`, робить pull і restart.

### Налаштування (один раз)

Sudo для restart без пароля:

```bash
sudo visudo
# додати (заміни elims2 на свого юзера):
elims2 ALL=(ALL) NOPASSWD: /bin/systemctl restart power-monitor
```

Інтервал перевірки: `AUTO_DEPLOY_INTERVAL_SEC=60` (за замовчуванням 60 сек = 1 хв).  
Вимкнути: `AUTO_DEPLOY=0` у .env або середовищі.

### Використання

```bash
git commit -m "Fix admin keys table #автооновити"
git push origin main
```

Протягом ~5 хвилин сервер оновиться.
