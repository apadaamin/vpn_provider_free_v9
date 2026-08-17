# FreeGate v4 — Community Config Intelligence

نسخه v4 پروژه را از یک referral bot ساده به یک **Collector + Quality Engine + Telegram Distribution Platform** نزدیک می‌کند.

## تفاوت مهم v4
در سمت کاربر هیچ Source یا نام منبعی نمایش داده نمی‌شود. Sourceها و کیفیت آنها فقط در پنل ادمین دیده می‌شوند.

## Quality Engine
قبل از تحویل:
1. Collector استخر عمومی را می‌خواند.
2. Duplicateها حذف می‌شوند.
3. Nodeها parse می‌شوند.
4. Health Engine روی آنها probe انجام می‌دهد.
5. Nodeهای مرده وارد بسته تحویل نمی‌شوند.
6. Feedback واقعی کاربران بعد از استفاده، به کیفیت تاریخی Node و Source اضافه می‌شود.

در محیط فعلی اگر `sing-box`/`mihomo` نصب باشد تشخیص می‌شود؛ در غیر این صورت TCP baseline استفاده می‌شود. این نسخه عمداً هیچ binary یا کانفیگ اجرایی ناشناخته‌ای را خودکار دانلود و اجرا نمی‌کند. برای runtime validation واقعی هر protocol باید adapter امن و محدودشده خودش را داشته باشد.

## پنل ادمین
- 📊 Dashboard
- 👥 Users + direct Telegram profile
- 📢 Forced Join
- 🎁 Reward / Replacement settings
- 📈 Source Quality
- 🧪 Top Configs
- 📝 Brand / Welcome
- 🔌 Collector sources
- 🛒 Purchase URL
- `/refresh` برای تازه‌سازی Collector

### Source Quality
ادمین می‌تواند ببیند:
- تعداد Nodeهای جمع‌آوری‌شده از هر Source
- Health pass rate
- نرخ Feedback موفق
- میانگین latency
- تعداد fail
- Top configs بر اساس Feedback/latency

## ایده‌های معماری اضافه‌شده
- Quality score
- Health state
- Latency tracking
- Feedback history
- Source reputation
- Config reputation
- Rotation در استخر
- Pre-delivery filtering
- Replacement pool
- ضد تکرار Referral
- محدودیت replacement
- event logging
- health-check concurrency limit
- cache Collector

## ارتقای بعدی برای مقیاس بالا
برای هزاران کاربر:
- PostgreSQL
- Redis
- Worker جداگانه برای Collector/Health
- Prometheus/Grafana
- SQLAdmin یا Web Dashboard
- queue-based delivery
- rate limiting
- abuse scoring
- backup و migration
- localization

این نوع معماری در پروژه‌های مدرن Aiogram معمولاً با PostgreSQL/Redis/FastAPI و observability جدا پیاده می‌شود. نمونه‌های عمومی مشابه نیز همین الگو را به‌کار می‌برند. 

## نصب روی VPS

### 1. نصب
```bash
sudo apt update
sudo apt install -y python3 python3-venv
mkdir -p ~/freegate
cd ~/freegate
```

ZIP را Upload و Extract کن.

### 2. محیط Python
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. تنظیم
```bash
cp .env.example .env
nano .env
```

```env
BOT_TOKEN=TOKEN_FROM_BOTFATHER
BOT_USERNAME=YourBotUsername
BASE_URL=https://your-domain.example
PORT=8080
ADMIN_IDS=123456789
```

### 4. اجرا
```bash
source venv/bin/activate
python -m app.main
```

### 5. تست
در VPS:
```bash
curl http://127.0.0.1:8080/health
```

باید:
```json
{"ok":true}
```

## اجرای دائمی با systemd

`/etc/systemd/system/freegate.service`:

```ini
[Unit]
Description=FreeGate Collector Telegram Bot
After=network.target

[Service]
User=YOUR_LINUX_USER
WorkingDirectory=/home/YOUR_LINUX_USER/freegate
EnvironmentFile=/home/YOUR_LINUX_USER/freegate/.env
ExecStart=/home/YOUR_LINUX_USER/freegate/venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

سپس:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now freegate
sudo systemctl status freegate
journalctl -u freegate -f
```

## Reverse proxy
برای production بهتر است FastAPI روی localhost بماند و Nginx/Caddy HTTPS را terminate کند.

## Telegram setup
Bot باید در کانال‌های Forced Join دسترسی لازم برای `getChatMember` داشته باشد. برای هر کانال بهتر است لینک عمومی یا invite link معتبر تنظیم شود.

## ملاحظات عملی
- عمومی بودن یک feed به معنی سالم بودن Node نیست.
- TCP open به معنی VPN usable نیست.
- Runtime validation واقعی باید protocol-specific باشد.
- Feedback کاربران سیگنال تکمیلی است، نه تضمین.
- منابع عمومی ممکن است بدون اطلاع شما تغییر کنند.

## منابع الهام معماری
- Aiogram برای Bot framework
- FastAPI برای HTTP/API
- sing-box برای protocol/runtime tooling
- PostgreSQL/Redis برای scale


## Replacement دقیقاً چگونه کار می‌کند؟
هر بسته ۵ سرویس یک سهمیه مستقل دارد و حداکثر **۵ جایگزین** می‌تواند دریافت کند. بعد از پنجمین جایگزین، همان بسته قفل می‌شود و دیگر برای آن جایگزین ارسال نمی‌شود. کاربر باید با Referralهای موفق به milestone بعدی برسد تا بسته جدید صادر شود؛ بسته جدید سهمیه ۵ جایگزین خودش را دارد.

## Turso Cloud
این نسخه با `libsql` می‌تواند مستقیماً به Turso Cloud متصل شود. برای Python، مستندات رسمی Turso برای Remote Access استفاده از `libsql` و متغیرهای `TURSO_DATABASE_URL` و `TURSO_AUTH_TOKEN` را توضیح می‌دهد. citeturn1search1turn1search2

ساخت نمونه: `turso db create freegate`، سپس URL و token را بگیر و در `.env` قرار بده. توکن را در GitHub یا کد commit نکن.

## پیام همگانی
پنل ادمین یک گزینه «📣 پیام همگانی» دارد. ادمین پیام را می‌نویسد، preview می‌گیرد و بعد تأیید می‌کند؛ سپس پیام برای کاربران ثبت‌شده ارسال می‌شود و تعداد موفق/ناموفق گزارش می‌شود.


## v6 — upgrades

- Replacement quota is stored per package, not per user.
- 5 replacements are the hard limit for each package.
- A new package is created only at the next referral milestone.
- Project Analytics: DAU, 7-day acquisition, qualified referrals and feedback.
- Source Quality Score combines health, user feedback and latency.
- Referral event logging for auditing and anti-abuse extensions.
- Broadcast pacing is kept below Telegram's free bulk-broadcast ceiling; Telegram documents roughly 30 messages/sec for free broadcasts, with higher paid limits available.
- The codebase is prepared for Redis/worker queues in the next scale step.

### Suggested next upgrades

1. **Redis + worker queue** for collector, health checks and broadcast jobs.
2. **Protocol-specific validation adapters** using a sandboxed local runtime; never execute arbitrary downloaded binaries.
3. **Source quarantine**: automatically quarantine sources whose quality score collapses.
4. **Config lifecycle**: new → checked → active → degraded → dead → archived.
5. **Fraud scoring** for referral patterns, repeated device-independent behavior signals, and impossible referral velocity.
6. **A/B testing** for onboarding copy and referral milestones.
7. **Admin audit log** for every setting change and broadcast.
8. **Scheduled broadcasts** and audience segments (active, inactive, rewarded, high-feedback).
9. **Exportable analytics** (CSV/JSON) for admins.
10. **Mini App dashboard** for a richer user-facing interface; Telegram Mini Apps support full web interfaces inside Telegram.


## v7 Production Hardening

- **Config Lifecycle:** `checking → active → degraded → stale → dead`
- **Source Quarantine:** افت شدید کیفیت Source باعث توقف موقت استفاده از آن در تصمیم‌گیری‌های مدیریتی می‌شود.
- **Referral Anti-Fraud:** رفتارهای غیرعادی Flag می‌شوند؛ یک سیگنال به‌تنهایی باعث Ban نمی‌شود.
- **Broadcast Queue abstraction:** آماده انتقال Workerها به Redis.
- **Quality Score:** health + user feedback + latency + freshness.
- **Admin monitoring:** Source Monitor و Anti-Fraud در پنل.

### پیشنهادات v8
1. Redis distributed workers
2. Circuit breaker و exponential backoff
3. Daily analytics snapshots
4. Admin audit log
5. Role-based admin permissions
6. Backup/restore automation
7. Alert هنگام افت شدید کیفیت
8. Cohort analytics برای Referral
9. Export CSV/JSON
10. Maintenance mode
11. Protocol-specific health adapters با sandbox


## مدیریت Sourceها از پنل ادمین

ادمین اکنون می‌تواند:
- Source جدید اضافه کند
- نوع Source را انتخاب کند (`url`, `api`, `file`)
- Endpoint را تعیین کند
- Priority تعیین کند
- Source را فعال/غیرفعال کند
- Source را حذف کند
- Health و Success Rate ثبت‌شده را ببیند

Sourceها فقط در پنل ادمین نمایش داده می‌شوند و اطلاعات Source در پیام تحویل سرویس به کاربر نمایش داده نمی‌شود.

نکته: این بخش مدیریت رکوردهای Source را فراهم می‌کند؛ Collector باید هنگام اجرا Sourceهای `enabled=1` را از دیتابیس بخواند و بر اساس `kind` مربوطه پردازش کند.

## Render / Flask deployment

This Render-ready build includes a Flask health server served by Waitress alongside the Telegram bot. Render uses `/health` for its health check. For Render Free, configure an external uptime monitor to request `/health` every 5–10 minutes; the internal watchdog is only a secondary layer and cannot wake a sleeping instance.
