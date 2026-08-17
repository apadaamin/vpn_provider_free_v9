# FreeGate v7 — Render + Flask

## Architecture

Telegram bot (aiogram polling) and a production Flask HTTP server run in the same Render Web Service process. Waitress serves Flask on Render's `$PORT`.

Endpoints:

- `/` — service status
- `/health` — Render health check and external keepalive target
- `/sub/<token>` — service link endpoint

## Render settings

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
python -m app.main
```

Health Check Path:

```text
/health
```

## Environment variables

Required:

- `BOT_TOKEN`
- `BOT_USERNAME`
- `BASE_URL` = `https://YOUR-SERVICE.onrender.com`
- `ADMIN_IDS`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

Optional:

- `KEEPALIVE_ENABLED=false`
- `KEEPALIVE_INTERVAL=180`
- `KEEPALIVE_URL=https://YOUR-SERVICE.onrender.com`

## Important: Render Free sleep

Flask gives the service a real HTTP endpoint, but Flask itself does not prevent Render Free from suspending an idle service.

The most useful setup is an **external uptime monitor / cron** that sends a request to:

```text
https://YOUR-SERVICE.onrender.com/health
```

Use **5 minutes** for maximum margin, or **10 minutes** to reduce request frequency. This creates inbound traffic while the service is awake and substantially reduces idle suspension.

The internal `KEEPALIVE_*` feature is only an additional watchdog. It cannot wake a process that Render has already suspended.

## Verify after deploy

Open:

```text
https://YOUR-SERVICE.onrender.com/health
```

Expected:

```json
{"ok":true,"service":"freegate"}
```

Then check Render logs for the bot polling startup.

## Reliability

This setup improves resilience but cannot guarantee 24/7 uptime on Render Free. A paid always-on service is required for a true no-sleep guarantee.
