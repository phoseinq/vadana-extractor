<div align="center">

# 🎓 Vadana Extractor

[![CI](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

**Recover slides, whiteboard & a synced video from IAU "Vadana" (Adobe Connect) class recordings**
**بازیابیِ اسلاید، وایت‌برد و ویدیوی همگام از ضبط‌های کلاسِ «وادانا» (ادوبی کانکت)**

### ▶️ Try the live bot — [@iau_archive_Bot](https://t.me/iau_archive_Bot)

[English](#english) · [فارسی](#فارسی)

</div>

<div align="center">

<img src="assets/bot.png" alt="ربات آرشیو وادانا" height="240"> <img src="assets/cli.png" alt="vadana CLI" height="240">

</div>

---

## English

### What it does

Pulls study material out of Adobe Connect ("Vadana") class recordings — straight from each recording's own offline package. Works with every IAU branch (`vadavc30`, `vadana14`, `vadana36`, … — the city code changes per branch). Most recordings open directly; some need a login.

It comes as a **Telegram bot** ([@iau_archive_Bot](https://t.me/iau_archive_Bot)) and two **CLI tools**.

- 📄 **Shared files** — the original PDF / Word / PPT from the Share pod, even when the download button was off.
- 📝 **Whiteboard → PDF** — every board page as a clean PDF, strokes smoothed. If the professor drew on a shared PDF, that page stays behind the annotations.
- 🎬 **Synced video** — whiteboard + screen-share + audio on one timeline.
- 🖼️ **Preview + details** — each file arrives with a thumbnail and a short caption (id, date, size, length).
- 🤖 **Telegram bot** — send a link, pick what you want; live progress, Persian UI, a retry button.
- 🇮🇷 **Runs anywhere** — locally or on an Iran server with no proxy; a reverse proxy only when hosted abroad.

### Requirements

- Python **3.11–3.13**
- `ffmpeg` + `ffprobe` on `PATH` (only for video)
- A bot token from [@BotFather](https://t.me/BotFather) (bot mode only)
- No proxy on a personal / Iran machine — only a reverse proxy when hosting abroad

### CLI (Windows or any computer)

Install [Python 3.11–3.13](https://www.python.org/downloads/) (tick **Add to PATH**) and, for video, **ffmpeg** (`winget install ffmpeg`). Then:

```bash
git clone https://github.com/phoseinq/vadana-extractor
cd vadana-extractor
pip install -r requirements.txt
```

```bash
python download_slides.py "https://<branch>.ec.iau.ir/<id>/"   # shared files
python make_video.py "<url>"                                   # synced video
python make_video.py "<url>" --pages-only                      # board pages as a PDF
```

The plain link is usually enough. If a recording asks you to log in, copy the full link including its `session=` value (it expires fast).

### Bot setup

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
bash install.sh
vadana env          # edit the config below, then it restarts
systemctl enable --now vadana-bot
```

`install.sh` sets up ffmpeg, a virtualenv, the dependencies, the systemd service and the `vadana` command.

| Variable | Meaning |
| :-- | :-- |
| `BOT_TOKEN` | token from [@BotFather](https://t.me/BotFather) — **required** |
| `IRAN_PROXY` | HTTP/SOCKS5 proxy, only when hosting abroad; empty otherwise |
| `ADMINS` | comma-separated user ids allowed to build videos |
| `STORAGE_CHANNEL` | private channel id used as a file cache (bot must be admin) |
| `ALLOW_VIDEO` | `1` = everyone can build videos; `0` = admin-only |

### The `vadana` command

| Command | Action |
| :-- | :-- |
| `vadana` | interactive menu |
| `files` / `whiteboard` / `video` | download that output |
| `status` / `logs` | service status / live logs |
| `start` / `stop` / `restart` | control the service |
| `update` | git pull + reinstall + restart |
| `env` | edit `.env`, then restart |
| `uninstall` | remove the service |

### How it works

Each recording exposes an offline ZIP at `/<id>/output/<id>.zip`. Shared documents come from `downloadUrl`s in `mainstream.xml`; the whiteboard is timed vector events in `ftcontent*.xml`, replayed to redraw the board; audio and screen-share are placed on the master timeline from `indexstream.xml` and muxed with FFmpeg.

### HTTP API (optional)

```bash
pip install -r requirements-api.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

`POST /extract` with `{"url": "...", "kind": "files"}` returns a zip of the shared files (or `"kind": "whiteboard"` for the board PDF).

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

---

## فارسی

<div dir="rtl" align="right">

### چه‌کار می‌کند

جزوه و محتوای درسی را از ضبط‌های کلاسِ ادوبی کانکت («وادانا») بیرون می‌کشد — مستقیم از پکیجِ آفلاینِ خودِ هر ضبط. با همهٔ شعبه‌های دانشگاه آزاد کار می‌کند (`vadavc30`، `vadana14`، `vadana36`، … — کدِ شهر در هر شعبه فرق می‌کند). بیشترِ ضبط‌ها مستقیم باز می‌شوند؛ بعضی‌ها به ورود نیاز دارند.

هم رباتِ تلگرام است ([@iau_archive_Bot](https://t.me/iau_archive_Bot))، هم دو ابزارِ خط‌فرمان.

- 📄 **فایل‌های اشتراکی** — همان PDF/Word/PPTِ اصل از Share pod، حتی وقتی دکمهٔ دانلود بسته بوده.
- 📝 **وایت‌برد ← PDF** — هر صفحهٔ تخته به‌صورتِ PDFِ تمیز، با خط‌های صاف‌شده. اگر استاد روی یک PDFِ اشتراکی نوشته باشد، همان صفحه پشتِ نوشته‌ها می‌ماند.
- 🎬 **ویدیوی همگام** — وایت‌برد + اشتراکِ صفحه + صدا روی یک تایم‌لاین.
- 🖼️ **پیش‌نمایش و جزئیات** — هر فایل با تامبنیل و یک کپشنِ کوتاه می‌رسد (شناسه، تاریخ، حجم، مدت).
- 🤖 **رباتِ تلگرام** — لینک را بفرست و انتخاب کن؛ نوارِ پیشرفتِ زنده، رابطِ فارسی، دکمهٔ تلاش مجدد.
- 🇮🇷 **همه‌جا کار می‌کند** — روی سیستمِ شخصی یا سرورِ ایران بدونِ پروکسی؛ پروکسیِ ریورس فقط روی سرورِ خارج.

### پیش‌نیازها

- پایتون **۳.۱۱ تا ۳.۱۳**
- `ffmpeg` و `ffprobe` روی `PATH` (فقط برای ویدیو)
- توکنِ ربات از [@BotFather](https://t.me/BotFather) (فقط حالتِ ربات)
- روی سیستمِ شخصی/ایران پروکسی لازم نیست — فقط روی سرورِ خارج یک پروکسیِ ریورس

### خط‌فرمان (ویندوز یا هر کامپیوتری)

[پایتون ۳.۱۱ تا ۳.۱۳](https://www.python.org/downloads/) را نصب کن (گزینهٔ **Add to PATH** را بزن) و برای ویدیو هم **ffmpeg** را (`winget install ffmpeg`). بعد:

```bash
git clone https://github.com/phoseinq/vadana-extractor
cd vadana-extractor
pip install -r requirements.txt
```

```bash
python download_slides.py "https://<branch>.ec.iau.ir/<id>/"   # فایل‌های اشتراکی
python make_video.py "<url>"                                   # ویدیوی همگام
python make_video.py "<url>" --pages-only                      # فقط صفحه‌های تخته (PDF)
```

معمولاً همین لینکِ ساده کافی است. اگر ضبطی به ورود نیاز داشت، لینکِ کامل همراه با مقدارِ `session=` را کپی کن (زود منقضی می‌شود).

### راه‌اندازیِ ربات

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
bash install.sh
vadana env          # کانفیگِ زیر را ویرایش کن، بعد خودش ری‌استارت می‌شود
systemctl enable --now vadana-bot
```

`install.sh` خودش ffmpeg، یک virtualenv، وابستگی‌ها، سرویسِ systemd و دستورِ `vadana` را نصب می‌کند.

| متغیر | توضیح |
| :-- | :-- |
| `BOT_TOKEN` | توکن از [@BotFather](https://t.me/BotFather) — **اجباری** |
| `IRAN_PROXY` | پروکسیِ HTTP/SOCKS5، فقط روی سرورِ خارج؛ وگرنه خالی |
| `ADMINS` | آی‌دیِ کاربرها (با کاما) که اجازهٔ ساختِ ویدیو دارند |
| `STORAGE_CHANNEL` | آی‌دیِ چنلِ خصوصی برای کشِ فایل‌ها (ربات باید ادمین باشد) |
| `ALLOW_VIDEO` | `۱` = ساختِ ویدیو برای همه؛ `۰` = فقط ادمین |

### دستورِ `vadana`

| دستور | کار |
| :-- | :-- |
| `vadana` | منوی تعاملی |
| `files` / `whiteboard` / `video` | دانلودِ همان خروجی |
| `status` / `logs` | وضعیتِ سرویس / لاگِ زنده |
| `start` / `stop` / `restart` | کنترلِ سرویس |
| `update` | git pull + نصبِ مجدد + ری‌استارت |
| `env` | ویرایشِ `.env` و ری‌استارت |
| `uninstall` | حذفِ سرویس |

### چطور کار می‌کند

هر ضبط یک ZIPِ آفلاین در `/<id>/output/<id>.zip` دارد. اسناد اشتراکی از `downloadUrl`های داخلِ `mainstream.xml` می‌آیند؛ وایت‌برد رویدادهای بُرداریِ زمان‌دار در `ftcontent*.xml` است که بازپخش می‌شود تا تخته دوباره کشیده شود؛ صدا و اشتراکِ صفحه با offsetهای `indexstream.xml` روی تایم‌لاین می‌نشینند و با FFmpeg ترکیب می‌شوند.

### API (اختیاری)

```bash
pip install -r requirements-api.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

`POST /extract` با `{"url": "...", "kind": "files"}` یک zip از فایل‌ها برمی‌گرداند (یا با `"kind": "whiteboard"` همان PDFِ تخته).

### تست

```bash
pip install -r requirements-dev.txt
pytest
```

</div>

---

<div align="center"><sub>MIT · made by <a href="https://github.com/phoseinq">phoseinq</a> · <a href="https://pvboy.dev">pvboy.dev</a></sub></div>
