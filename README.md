<div align="center">

# 🎓 Vadana Extractor

[![CI](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

**Recover slides, whiteboard & a synced video from IAU "Vadana" (Adobe Connect) class recordings**
**بازیابیِ اسلاید، وایت‌برد و ویدیوی همگام از ضبط‌های کلاسِ «وادانا» (ادوبی کانکت)**

[English](#english) · [فارسی](#فارسی)

</div>

---

## English

### 📖 Description

**Vadana Extractor** recovers study material from Adobe Connect ("Vadana", `vadavc30.ec.iau.ir`) class recordings — straight from each recording's own offline package, using your own session. The slides you could view but never download, the whiteboard that vanished with the browser tab, the lecture sealed behind a player that still believes in Flash: it takes all of it back, politely.

It ships both as a **Telegram bot** (Persian, multi-user) and as a pair of standalone **CLI tools**.

**Key Features:**

- 📄 **Original shared files** — downloads the untouched PDF / Word / PPT / any file a professor put in the Share pod (even when the download button was disabled)
- 📝 **Whiteboard → PDF** — replays the board's timed vector events and renders every page to a clean PDF
- 🎬 **Synced archive video** — rebuilds the lecture on one master timeline: whiteboard **+** screen-share **+** the lecturer's audio, in sync
- 🤖 **Telegram bot** — students just send a recording link and pick what they want; colored inline buttons, a live progress bar, formal Persian UI, a "report a problem" button on every result
- 🇮🇷 **Works anywhere** — runs locally or on an Iran server with no proxy; add a reverse proxy only when you host it abroad
- 🗃️ **Telegram-backed cache** — each result is uploaded once to a private channel and re-sent instantly by `file_id` (nothing kept on disk)
- 🛡️ **Server protection** — per-user single job, global concurrency cap, cooldown, daily video quota, systemd resource limits
- 📦 **Large files** — optional local Bot API server for uploads up to 2 GB

---

### 📋 Requirements

- Python **3.11–3.13** (Pillow text rendering can crash on 3.14 alpha)
- `ffmpeg` + `ffprobe` on `PATH` (only for whiteboard → video)
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather) — bot mode only
- A proxy is **not** needed on a personal machine or an Iran server — only when you run on a server abroad (a reverse proxy that reaches `vadavc30.ec.iau.ir`)

---

### 🚀 CLI usage

Install the dependencies (`requests`, `pillow`, `img2pdf`, `pymupdf`):

```bash
pip install -r requirements.txt
```

**1. Download the original shared files**

```bash
python download_slides.py "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"
```

**2. Whiteboard → synced MP4** — add `--pages-only` for just the board pages as a PDF:

```bash
python make_video.py "<url>"
python make_video.py "<url>" --pages-only
```

The session token is the `session=` value in the live recording URL; it expires quickly, so grab a fresh link right before running.

---

### 🤖 Bot setup

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
bash install.sh
vadana env
systemctl enable --now vadana-bot
```

`install.sh` installs ffmpeg, a virtualenv, the dependencies, the systemd service and the `vadana` command. `vadana env` opens the config below and restarts the bot.

```ini
BOT_TOKEN=123456:ABC...
IRAN_PROXY=
ADMINS=11111111
STORAGE_CHANNEL=-1001234567890
ALLOW_VIDEO=0
```

| Variable | Meaning |
| :-- | :-- |
| `BOT_TOKEN` | bot token from [@BotFather](https://t.me/BotFather) — **required** |
| `IRAN_PROXY` | **optional**, only when hosting abroad — an HTTP or SOCKS5 proxy: `http://user:pass@ip:port` or `socks5://user:pass@ip:port`. Leave empty on a personal/Iran machine |
| `ADMINS` | comma-separated Telegram user ids allowed to build videos |
| `STORAGE_CHANNEL` | private channel id used as a file cache (the bot must be an admin there) |
| `ALLOW_VIDEO` | `1` lets everyone build videos (heavy); `0` keeps it admin-only |

---

### 🧰 The `vadana` CLI

`install.sh` installs a `vadana` command — it both **downloads recordings** and **manages the bot service**. Run it with no arguments for an interactive menu, or a subcommand directly:

```bash
vadana
vadana files
vadana whiteboard
vadana video
vadana status
vadana logs
vadana start
vadana stop
vadana restart
vadana update
vadana env
vadana uninstall
```

| Command | Action |
| :-- | :-- |
| `vadana` | interactive menu |
| `files` | download the shared files |
| `whiteboard` | whiteboard as a PDF |
| `video` | synced archive video |
| `status` | service status |
| `logs` | live logs (Ctrl+C to exit) |
| `start` / `stop` / `restart` | control the service |
| `update` | git pull + reinstall deps + restart |
| `env` | edit `.env`, then restart |
| `uninstall` | remove the service (asks before deleting data) |

A download command asks for the recording link if you don't pass one — both `vadana video` (prompts) and `vadana video "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"` work.

---

### ⚙️ How it works

Every recording exposes an offline package at `/<id>/output/<id>.zip?download=zip` (cookie `BREEZESESSION`). Inside:

- **Shared documents** aren't in the package, but `mainstream.xml` records a `downloadUrl` for each → resolved to the untouched source file.
- **Whiteboard** lives in `ftcontent*.xml` as timed vector events on per-page SharedObjects (`set_WB_So_<page>`); strokes are normalized to each shape's bounding box. The events are replayed to redraw the board.
- **Audio & screen-share** segments are placed on the master timeline from `indexstream.xml` offsets and muxed together with FFmpeg.

Concurrency is bounded by asyncio semaphores (a built-in queue): when the server is busy, extra requests wait their turn instead of piling on.

---

### 🌐 HTTP API (optional)

Turn the extractor into a small service:

```bash
pip install -r requirements-api.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST localhost:8000/extract -H "Content-Type: application/json" -d '{"url":"https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true","kind":"files"}' -o files.zip
```

`kind` is `files` (a zip of the shared files) or `whiteboard` (the board as a PDF).

---

### 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs the suite (ruff + pytest on Python 3.11 & 3.12) on every push.

---

## فارسی

<div dir="rtl" align="right">

### 📖 معرفی

**Vadana Extractor** جزوه و محتوای درسی را از ضبط‌های کلاسِ ادوبی کانکت («وادانا»، `vadavc30.ec.iau.ir`) بیرون می‌کشد — مستقیم از پکیجِ آفلاینِ خودِ هر ضبط و با سشنِ خودتان. اسلایدهایی که می‌دیدید اما هرگز دانلود نمی‌شدند، وایت‌بردی که با بستنِ تب ناپدید می‌شد، و درسی که پشتِ پلیری از عهدِ فلش حبس بود: همه را مؤدبانه پس می‌گیرد.

هم به‌صورتِ **رباتِ تلگرام** (فارسی، چندکاربره) عرضه می‌شود و هم دو **ابزارِ خط‌فرمان**.

**امکانات:**

- 📄 **فایل‌های اشتراکیِ اصل** — دانلودِ PDF/Word/PPT یا هر فایلی که استاد توی Share pod گذاشته (حتی وقتی دکمهٔ دانلود غیرفعال بوده)
- 📝 **وایت‌برد ← PDF** — بازپخشِ رویدادهای بُرداریِ تخته و رندرِ همهٔ صفحه‌ها به یه PDFِ تمیز
- 🎬 **ویدیوی همگامِ آرشیو** — بازسازیِ کلاس روی یه تایم‌لاینِ واحد: وایت‌برد **+** اشتراکِ صفحه **+** صدای استاد، همگام
- 🤖 **رباتِ تلگرام** — دانشجو فقط لینکِ ضبط رو می‌فرسته و انتخاب می‌کنه؛ دکمه‌های رنگی، نوارِ پیشرفتِ زنده، رابطِ رسمیِ فارسی، و دکمهٔ «گزارشِ مشکل» زیرِ هر خروجی
- 🇮🇷 **همه‌جا کار می‌کنه** — روی سیستمِ شخصی یا سرورِ ایران بدونِ پروکسی؛ پروکسیِ ریورس فقط وقتی لازمه که روی سرورِ خارج اجراش کنی
- 🗃️ **کشِ مبتنی‌بر تلگرام** — هر خروجی یک‌بار توی یه چنلِ خصوصی آپلود و دفعهٔ بعد با `file_id` فوری ارسال می‌شه
- 🛡️ **محافظت از سرور** — یک کارِ همزمان برای هر کاربر، سقفِ کلیِ همزمانی، کول‌داون، سهمیهٔ روزانهٔ ویدیو، محدودیتِ منابعِ systemd
- 📦 **فایلِ بزرگ** — سرورِ محلیِ Bot API (اختیاری) برای آپلودِ تا ۲ گیگ

---

### 📋 پیش‌نیازها

- پایتون **۳.۱۱ تا ۳.۱۳** (رندرِ متنِ Pillow روی ۳.۱۴ آلفا کرش می‌کنه)
- `ffmpeg` و `ffprobe` روی `PATH` (فقط برای ویدیوسازی)
- توکنِ رباتِ تلگرام از [@BotFather](https://t.me/BotFather) — فقط حالتِ ربات
- روی سیستمِ شخصی یا سرورِ ایران **پروکسی لازم نیست**؛ فقط روی سرورِ خارج یه پروکسیِ ریورس می‌خوای که به `vadavc30.ec.iau.ir` برسه

---

### 🚀 خط‌فرمان

اول وابستگی‌ها (`requests`، `pillow`، `img2pdf`، `pymupdf`):

```bash
pip install -r requirements.txt
```

**۱) دانلودِ فایل‌های اشتراکیِ اصل:**

```bash
python download_slides.py "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"
```

**۲) وایت‌برد ← ویدیوی همگام** — با `--pages-only` فقط صفحه‌های تخته به PDF می‌شه:

```bash
python make_video.py "<url>"
python make_video.py "<url>" --pages-only
```

توکنِ سشن همون مقدارِ `session=` توی لینکِ زندهٔ ضبطه؛ زود منقضی می‌شه، پس درست قبلِ اجرا یه لینکِ تازه بگیر.

---

### 🤖 راه‌اندازیِ ربات

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
bash install.sh
vadana env
systemctl enable --now vadana-bot
```

`install.sh` خودش ffmpeg، یه virtualenv، وابستگی‌ها، سرویسِ systemd و دستورِ `vadana` رو نصب می‌کنه. دستورِ `vadana env` کانفیگِ زیر رو باز می‌کنه و بعد ربات رو ری‌استارت می‌کنه.

```ini
BOT_TOKEN=123456:ABC...
IRAN_PROXY=
ADMINS=11111111
STORAGE_CHANNEL=-1001234567890
ALLOW_VIDEO=0
```

| متغیر | توضیح |
| :-- | :-- |
| `BOT_TOKEN` | توکنِ ربات از [@BotFather](https://t.me/BotFather) — **اجباری** |
| `IRAN_PROXY` | **اختیاری**، فقط روی سرورِ خارج — پروکسیِ HTTP یا SOCKS5: `http://user:pass@ip:port` یا `socks5://user:pass@ip:port`؛ روی سیستمِ شخصی/ایران خالی بذار |
| `ADMINS` | آی‌دیِ کاربرهای تلگرام (با کاما) که اجازهٔ ساختِ ویدیو دارن |
| `STORAGE_CHANNEL` | آی‌دیِ چنلِ خصوصی برای کشِ فایل‌ها (ربات باید ادمینش باشه) |
| `ALLOW_VIDEO` | `۱` ساختِ ویدیو رو برای همه باز می‌کنه (سنگین)؛ `۰` فقط ادمین |

---

### 🧰 ابزارِ `vadana`

`install.sh` یه دستورِ `vadana` نصب می‌کنه که هم **ضبط‌ها رو دانلود می‌کنه** و هم **سرویسِ ربات رو مدیریت می‌کنه**. بدونِ آرگومان منوی تعاملی می‌ده، یا مستقیم با ساب‌کامند:

```bash
vadana
vadana files
vadana whiteboard
vadana video
vadana status
vadana logs
vadana start
vadana stop
vadana restart
vadana update
vadana env
vadana uninstall
```

| دستور | کار |
| :-- | :-- |
| `vadana` | منوی تعاملی |
| `files` | دانلودِ فایل‌های اشتراکی |
| `whiteboard` | وایت‌برد به‌صورتِ PDF |
| `video` | ویدیوی همگامِ آرشیو |
| `status` | وضعیتِ سرویس |
| `logs` | لاگِ زنده (Ctrl+C برای خروج) |
| `start` / `stop` / `restart` | کنترلِ سرویس |
| `update` | git pull + نصبِ مجددِ وابستگی‌ها + ری‌استارت |
| `env` | ویرایشِ `.env` و ری‌استارت |
| `uninstall` | حذفِ سرویس (قبلِ پاکِ داده می‌پرسه) |

اگه لینک ندی، خودش لینک رو می‌پرسه — هم `vadana video` (prompt می‌گیره) و هم `vadana video "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"` کار می‌کنه.

---

### 🌐 API (اختیاری)

تبدیلِ ابزار به یک سرویس:

```bash
pip install -r requirements-api.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

`POST /extract` با بدنهٔ `{"url": "...", "kind": "files"}` یه zip از فایل‌ها برمی‌گردونه (یا با `"kind": "whiteboard"` یه PDF).

---

### 🧪 تست

```bash
pip install -r requirements-dev.txt
pytest
```

CI روی هر push تست‌ها رو اجرا می‌کنه (ruff + pytest روی پایتون ۳.۱۱ و ۳.۱۲).

</div>

---

<div align="center"><sub>MIT · made by <a href="https://github.com/phoseinq">phoseinq</a> · <a href="https://pvboy.dev">pvboy.dev</a></sub></div>
