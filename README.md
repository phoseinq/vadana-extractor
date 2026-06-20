<div align="center">

# 🎓 Vadana Extractor

[![Adobe Connect](https://img.shields.io/badge/Adobe%20Connect-FF0000?style=for-the-badge&logo=adobe&logoColor=white)](https://www.adobe.com/products/adobeconnect.html)
[![CI](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/phoseinq/vadana-extractor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

**Recover slides, whiteboard & a synced video from any Adobe Connect recording — IAU "Vadana" included**
**بازیابیِ اسلاید، وایت‌برد و ویدیوی همگام از هر ضبطِ ادوبی کانکت — از جمله «وادانا»ی دانشگاه آزاد**

### ▶️ Try the live bot — [@iau_archive_Bot](https://t.me/iau_archive_Bot)

[English](#english) · [فارسی](#فارسی)

</div>

<div align="center">

<img src="assets/bot.png" alt="ربات آرشیو وادانا" height="240"> <img src="assets/cli.png" alt="vadana CLI" height="240">

</div>

---

## English

### What it does

Pulls study material out of any Adobe Connect recording — straight from the recording's own offline package. It was built for IAU's "Vadana" servers (works with every branch — `vadavc30`, `vadana14`, `vadana36`, …), but that package layout is standard Adobe Connect, so any server works: just paste the full recording link. Most recordings open directly; some need a login.

It comes as a **Telegram bot** ([@iau_archive_Bot](https://t.me/iau_archive_Bot)) and two **CLI tools**.

- 📄 **Shared files** — the original PDF / Word / PPT from the Share pod, even when the download button was off.
- 📝 **Whiteboard → PDF** — every board page as a clean PDF, strokes smoothed. If the professor drew on a shared PDF, that page stays behind the annotations.
- 🎬 **Synced video** — whiteboard + screen-share + audio on one timeline.
- 🖼️ **Preview + details** — each file arrives with a thumbnail and a short caption (id, date, size, length).
- 🤖 **Telegram bot** — send a link, pick what you want; live progress, Persian UI, a retry button.
- 🇮🇷 **Runs anywhere** — locally or on an Iran server with no proxy; a reverse proxy only when hosted abroad.

**Example** — one recording link, three possible outputs:

| You send | You get back |
| :-- | :-- |
| a link + 📄 **files** | the original slide PDFs (`Chapter 1.pdf`, `notes.docx`, …) |
| a link + 📝 **whiteboard** | one PDF of the board — the professor's notes laid over the slides |
| a link + 🎬 **video** | an MP4: whiteboard + screen-share + audio, page-synced |

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
python cli/download_slides.py "https://<connect-host>/<id>/"   # shared files
python cli/make_video.py "<url>"                               # synced video
python cli/make_video.py "<url>" --pages-only                  # board pages as a PDF
```

The plain link is usually enough. If a recording asks you to log in, copy the full link including its `session=` value (it expires fast).

### Bot setup

One command on the server. It asks Docker or native, installs everything (ffmpeg, the dependencies, the systemd service, the `vadana` command), then prints the next step.

```bash
curl -fsSL https://raw.githubusercontent.com/phoseinq/vadana-extractor/main/install.sh | bash
```

Then fill in `bot/.env` (run `vadana env`, or edit it for Docker) and start. The settings:

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

### Architecture (for contributors)

The bot is one `aiogram` event loop. Every heavy step (download, whiteboard render, FFmpeg) runs in a worker thread via `asyncio.to_thread`, so the loop itself never blocks and stays responsive to other users.

**One job per user.** Each request becomes an `asyncio.Task` tracked in `ACTIVE_TASKS[uid]`; sending a second link while one is running is refused ("wait, or press Cancel"). Cancel sets an `asyncio.Event` the job polls, so it stops cleanly and frees its slot.

**Two semaphores cap the whole server** (not per-user):

- `SLIDES_SEM = Semaphore(MAX_CONCURRENT)` — default **3** — file / whiteboard downloads.
- `VIDEO_SEM = Semaphore(MAX_VIDEO_CONCURRENT)` — default **1** — video builds, which are the expensive ones (render + encode).

**Two people build a video at the same time:** the first `async with VIDEO_SEM:` takes the only slot and runs. The second sees `VIDEO_SEM.locked()`, switches its status message to "another video is building — yours starts next", and `await`s the semaphore. asyncio wakes waiters in arrival order, so it behaves as a FIFO queue — nobody is dropped, they just wait their turn. On a bigger box, raise `MAX_VIDEO_CONCURRENT`.

**Rate limits & anti-spam:** a per-user cooldown (`USER_COOLDOWN`, 15 s between requests) and a daily video quota (`MAX_VIDEO_PER_DAY`, 3 for non-admins, tracked in memory per day). A `ThrottleMiddleware` (outer middleware, ~10 updates per 8 s sliding window) drops floods *before* any handler or work runs; admins are exempt.

**Caching skips all of the above.** Every finished result is uploaded once to a storage channel and its Telegram `file_id` saved in `store.json`; a repeat request resends instantly from there — it never takes a semaphore or touches the source server.

Where to look: `bot/bot.py` (handlers, the two semaphores, the live-progress poller), `vadana/connect.py` (auth + package download), `vadana/whiteboard.py` + `vadana/video.py` (reconstruction), `vadana/slides.py` (shared files).

### HTTP API (optional)

```bash
pip install -r requirements-api.txt
uvicorn cli.api:app --host 0.0.0.0 --port 8000
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

جزوه و محتوای درسی را از هر ضبطِ ادوبی کانکت بیرون می‌کشد — مستقیم از پکیجِ آفلاینِ خودِ ضبط. برای سرورهای «وادانا»ی دانشگاه آزاد ساخته شده (با همهٔ شعبه‌ها کار می‌کند — `vadavc30`، `vadana14`، `vadana36`، …)، ولی این ساختارِ پکیج استانداردِ ادوبی کانکت است، پس روی هر سروری کار می‌کند: فقط لینکِ کاملِ ضبط را بفرست. بیشترِ ضبط‌ها مستقیم باز می‌شوند؛ بعضی‌ها به ورود نیاز دارند.

هم رباتِ تلگرام است ([@iau_archive_Bot](https://t.me/iau_archive_Bot))، هم دو ابزارِ خط‌فرمان.

- 📄 **فایل‌های اشتراکی** — همان PDF/Word/PPTِ اصل از Share pod، حتی وقتی دکمهٔ دانلود بسته بوده.
- 📝 **وایت‌برد ← PDF** — هر صفحهٔ تخته به‌صورتِ PDFِ تمیز، با خط‌های صاف‌شده. اگر استاد روی یک PDFِ اشتراکی نوشته باشد، همان صفحه پشتِ نوشته‌ها می‌ماند.
- 🎬 **ویدیوی همگام** — وایت‌برد + اشتراکِ صفحه + صدا روی یک تایم‌لاین.
- 🖼️ **پیش‌نمایش و جزئیات** — هر فایل با تامبنیل و یک کپشنِ کوتاه می‌رسد (شناسه، تاریخ، حجم، مدت).
- 🤖 **رباتِ تلگرام** — لینک را بفرست و انتخاب کن؛ نوارِ پیشرفتِ زنده، رابطِ فارسی، دکمهٔ تلاش مجدد.
- 🇮🇷 **همه‌جا کار می‌کند** — روی سیستمِ شخصی یا سرورِ ایران بدونِ پروکسی؛ پروکسیِ ریورس فقط روی سرورِ خارج.

**نمونه** — یک لینکِ ضبط، سه خروجیِ ممکن:

| می‌فرستی | می‌گیری |
| :-- | :-- |
| لینک + 📄 **فایل‌ها** | همان PDFهای اصلِ اسلاید (`Chapter 1.pdf`، …) |
| لینک + 📝 **وایت‌برد** | یک PDF از تخته — نوشته‌های استاد روی اسلایدها |
| لینک + 🎬 **ویدیو** | یک MP4: وایت‌برد + اشتراکِ صفحه + صدا، هماهنگ با صفحه‌ها |

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
python cli/download_slides.py "https://<connect-host>/<id>/"   # فایل‌های اشتراکی
python cli/make_video.py "<url>"                               # ویدیوی همگام
python cli/make_video.py "<url>" --pages-only                  # فقط صفحه‌های تخته (PDF)
```

معمولاً همین لینکِ ساده کافی است. اگر ضبطی به ورود نیاز داشت، لینکِ کامل همراه با مقدارِ `session=` را کپی کن (زود منقضی می‌شود).

### راه‌اندازیِ ربات

یک دستور روی سرور. می‌پرسد با داکر یا مستقیم، همه‌چیز را نصب می‌کند (ffmpeg، وابستگی‌ها، سرویسِ systemd و دستورِ `vadana`) و بعد قدمِ بعدی را نشان می‌دهد.

```bash
curl -fsSL https://raw.githubusercontent.com/phoseinq/vadana-extractor/main/install.sh | bash
```

بعد `bot/.env` را پر کن (با `vadana env`، یا برای داکر دستی ویرایشش کن) و راه بینداز. تنظیمات:

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
uvicorn cli.api:app --host 0.0.0.0 --port 8000
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
