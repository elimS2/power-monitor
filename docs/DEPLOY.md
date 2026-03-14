# Деплой Power Monitor

## Ручний деплой

```bash
cd /var/www/power-monitor && git pull && sudo systemctl restart power-monitor
```

## Автоматичний деплой

Є два варіанти: **webhook** (рекомендовано) і **polling** (fallback).

### 1. GitHub Webhook (рекомендовано)

При push в `main` з тегом `#autodeploy` GitHub відправляє POST на сервер — deploy через кілька секунд.

**Налаштування GitHub:**

1. Repo → Settings → Webhooks → Add webhook
2. **Payload URL**: `https://power.elims.pp.ua/api/deploy-hook`
3. **Content type**: `application/json`
4. **Secret**: згенеруй (`openssl rand -hex 32`) і додай у `.env` як `GITHUB_WEBHOOK_SECRET`
5. **Events**: тільки `Push events`
6. Save

**На сервері** додай у `.env`:

```bash
GITHUB_WEBHOOK_SECRET=<той самий секрет що в GitHub>
AUTO_DEPLOY=0   # вимкнути polling, якщо використовуєш лише webhook
```

### 2. Polling (fallback)

Сервіс сам перевіряє репо кожні 60 сек. Якщо в повідомленні останнього коміту є тег `#автооновити` або `#autodeploy`, робить pull і restart.

**Налаштування (один раз):**

Sudo для restart без пароля:

```bash
sudo visudo
# додати (заміни elims2 на свого юзера):
elims2 ALL=(ALL) NOPASSWD: /bin/systemctl restart power-monitor
```

Інтервал: `AUTO_DEPLOY_INTERVAL_SEC=60`. Вимкнути: `AUTO_DEPLOY=0` у .env.

### Використання

```bash
git commit -m "Fix admin keys table #autodeploy"
git push origin main
```

З webhook — оновлення через кілька секунд. З polling — до 1 хвилини.
