<div align="center">

# 🎓 Vadana Extractor

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

**Vadana Extractor** recovers study material from Adobe Connect ("Vadana", `vadavc30.ec.iau.ir`) class recordings you are **authorized to watch** — straight from each recording's own offline package, using your own session token. No server intrusion, no authentication bypass.

It ships both as a **Telegram bot** (Persian, multi-user) and as a pair of standalone **CLI tools**.

**Key Features:**

- 📄 **Original shared files** — downloads the untouched PDF / Word / PPT / any file a professor put in the Share pod (even when the download button was disabled)
- 📝 **Whiteboard → PDF** — replays the board's timed vector events and renders every page to a clean PDF
- 🎬 **Synced archive video** — rebuilds the lecture on one master timeline: whiteboard **+** screen-share **+** the lecturer's audio, in sync
- 🤖 **Telegram bot** — students just send a recording link and pick what they want; colored inline buttons, a live progress bar, formal Persian UI
- 🇮🇷 **Iran-proxy aware** — runs on a server abroad and reaches the Iran-only Vadana host through your proxy
- 🗃️ **Telegram-backed cache** — each result is uploaded once to a private channel and re-sent instantly by `file_id` (nothing kept on disk)
- 🛡️ **Server protection** — per-user single job, global concurrency cap, cooldown, daily video quota, systemd resource limits
- 📦 **Large files** — optional local Bot API server for uploads up to 2 GB

---

### 📋 Requirements

- Python **3.11–3.13** (Pillow text rendering can crash on 3.14 alpha)
- `ffmpeg` + `ffprobe` on `PATH` (only for whiteboard → video)
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather) — bot mode only
- An Iran SOCKS5/HTTP proxy that can reach `vadavc30.ec.iau.ir` — if you run abroad

---

### 🚀 CLI usage

```bash
pip install -r requirements.txt        # requests, pillow, img2pdf, pymupdf

# 1) download the original shared files
python download_slides.py "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"

# 2) whiteboard -> synced MP4  (or just the board pages as a PDF)
python make_video.py "<url>"
python make_video.py "<url>" --pages-only
```

The session token is the `session=` value in the live recording URL; it expires quickly, so grab a fresh link right before running.

---

### 🤖 Bot setup (server abroad)

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
pip install -r requirements.txt -r bot/requirements.txt
cp bot/.env.example bot/.env        # then fill it in
```

Minimal `.env`:

```ini
BOT_TOKEN=123456:ABC...
IRAN_PROXY=socks5://user:pass@IRAN_IP:1080
ADMINS=11111111
ALLOW_VIDEO=0
```

Run it as a service:

```bash
cp bot/systemd/vadana-bot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vadana-bot
journalctl -u vadana-bot -f
```

---

### ⚙️ How it works

Every recording exposes an offline package at `/<id>/output/<id>.zip?download=zip` (cookie `BREEZESESSION`). Inside:

- **Shared documents** aren't in the package, but `mainstream.xml` records a `downloadUrl` for each → resolved to the untouched source file.
- **Whiteboard** lives in `ftcontent*.xml` as timed vector events on per-page SharedObjects (`set_WB_So_<page>`); strokes are normalized to each shape's bounding box. The events are replayed to redraw the board.
- **Audio & screen-share** segments are placed on the master timeline from `indexstream.xml` offsets and muxed together with FFmpeg.

---

### ⚖️ Scope & ethics

For students extracting their **own** course material that they can already watch. It only uses your authenticated session and the recording's own files — it does **not** break into the server or bypass any access control.

---

## فارسی

<div dir="rtl" align="right">

### 📖 معرفی

**Vadana Extractor** جزوه و محتوای درسی رو از ضبط‌های کلاسِ ادوبی کانکت («وادانا»، `vadavc30.ec.iau.ir`) که **اجازهٔ تماشاشون رو داری** بیرون می‌کشه — مستقیم از پکیجِ آفلاینِ خودِ هر ضبط و با سشنِ خودت. نه نفوذ به سرور، نه دورزدنِ احراز هویت.

هم به‌صورتِ **رباتِ تلگرام** (فارسی، چندکاربره) عرضه می‌شه و هم دو تا **ابزارِ خط‌فرمان**.

**امکانات:**

- 📄 **فایل‌های اشتراکیِ اصل** — دانلودِ PDF/Word/PPT یا هر فایلی که استاد توی Share pod گذاشته (حتی وقتی دکمهٔ دانلود غیرفعال بوده)
- 📝 **وایت‌برد ← PDF** — بازپخشِ رویدادهای بُرداریِ تخته و رندرِ همهٔ صفحه‌ها به یه PDFِ تمیز
- 🎬 **ویدیوی همگامِ آرشیو** — بازسازیِ کلاس روی یه تایم‌لاینِ واحد: وایت‌برد **+** اشتراکِ صفحه **+** صدای استاد، همگام
- 🤖 **رباتِ تلگرام** — دانشجو فقط لینکِ ضبط رو می‌فرسته و انتخاب می‌کنه؛ دکمه‌های رنگی، نوارِ پیشرفتِ زنده، رابطِ رسمیِ فارسی
- 🇮🇷 **سازگار با پروکسیِ ایران** — رو سرورِ خارج اجرا می‌شه و از طریقِ پروکسیِ تو به هاستِ فقط-ایرانِ وادانا می‌رسه
- 🗃️ **کشِ مبتنی‌بر تلگرام** — هر خروجی یک‌بار توی یه چنلِ خصوصی آپلود و دفعهٔ بعد با `file_id` فوری ارسال می‌شه
- 🛡️ **محافظت از سرور** — یک کارِ همزمان برای هر کاربر، سقفِ کلیِ همزمانی، کول‌داون، سهمیهٔ روزانهٔ ویدیو، محدودیتِ منابعِ systemd
- 📦 **فایلِ بزرگ** — سرورِ محلیِ Bot API (اختیاری) برای آپلودِ تا ۲ گیگ

---

### 📋 پیش‌نیازها

- پایتون **۳.۱۱ تا ۳.۱۳** (رندرِ متنِ Pillow روی ۳.۱۴ آلفا کرش می‌کنه)
- `ffmpeg` و `ffprobe` روی `PATH` (فقط برای ویدیوسازی)
- توکنِ رباتِ تلگرام از [@BotFather](https://t.me/BotFather) — فقط حالتِ ربات
- یه پروکسیِ SOCKS5/HTTP ایران که به `vadavc30.ec.iau.ir` برسه — اگه خارج اجرا می‌کنی

---

### 🚀 خط‌فرمان

```bash
pip install -r requirements.txt        # requests, pillow, img2pdf, pymupdf

# ۱) دانلودِ فایل‌های اشتراکیِ اصل
python download_slides.py "https://vadavc30.ec.iau.ir/<id>/?session=...&proto=true"

# ۲) وایت‌برد ← ویدیوی همگام (یا فقط صفحه‌های تخته به‌صورتِ PDF)
python make_video.py "<url>"
python make_video.py "<url>" --pages-only
```

توکنِ سشن همون مقدارِ `session=` توی لینکِ زندهٔ ضبطه؛ زود منقضی می‌شه، پس درست قبلِ اجرا یه لینکِ تازه بگیر.

---

### 🤖 راه‌اندازیِ ربات (سرورِ خارج)

```
دانشجو ──تلگرام──► ربات (سرورِ خارج) ──پروکسیِ ایران──► vadavc30.ec.iau.ir
                          └── خروجی رو برمی‌گردونه به دانشجو
```

```bash
git clone https://github.com/phoseinq/vadana-extractor.git /opt/vadana-extractor
cd /opt/vadana-extractor
pip install -r requirements.txt -r bot/requirements.txt
cp bot/.env.example bot/.env        # بعد پُرش کن

cp bot/systemd/vadana-bot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vadana-bot
```

نمونهٔ پروکسیِ ایران با `gost` روی یه VPS ایران: `gost -L "socks5://user:pass@:1080"` و بعد توی `.env`: `IRAN_PROXY=socks5://user:pass@IRAN_IP:1080`.

---

### ⚖️ محدوده و اخلاق

برای دانشجوهایی که محتوای **درسِ خودشون** رو — که همین الان هم اجازهٔ دیدنش رو دارن — استخراج می‌کنن. فقط از سشنِ احرازشدهٔ خودت و فایل‌های خودِ ضبط استفاده می‌کنه؛ به سرور نفوذ نمی‌کنه و هیچ کنترلِ دسترسی‌ای رو دور نمی‌زنه.

</div>

---

<div align="center"><sub>MIT · made by <a href="https://github.com/phoseinq">phoseinq</a> · <a href="https://pvboy.dev">pvboy.dev</a></sub></div>
