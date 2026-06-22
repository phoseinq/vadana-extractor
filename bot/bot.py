#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import date
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from bot import config, node_ca
from bot.nodes import NodeRegistry, should_offload
from bot.node_api import start_node_api
from vadana.connect import parse_recording_url, ConnectClient, Recording, is_valid_recording
from vadana.slides import download_slides, category_of
from vadana import audio as audio_mod
from vadana import video as video_mod
from vadana import whiteboard as wb_mod

os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(os.path.join(config.LOG_DIR, "bot.log"),
                            maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("vadana.bot")

STORE_PATH = os.path.join(config.CACHE_DIR, "store.json")

def _store_load():
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    for k in ("video", "wb", "files", "video_day", "stats", "meta", "retry"):
        data.setdefault(k, {})
    return data

STORE = _store_load()

def _store_save():
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STORE, f, ensure_ascii=False)
    os.replace(tmp, STORE_PATH)

def _store_get(kind, rec_id):
    return STORE.get(kind, {}).get(rec_id)

def _store_put(kind, rec_id, val):
    STORE.setdefault(kind, {})[rec_id] = val
    _store_save()

LINK_RE = re.compile(r"https?://[\w.-]+\.[\w-]{2,}/\S*")

WELCOME = (
    "سلام 👋 به رباتِ آرشیوِ کلاس‌های وادانا خوش آمدید.\n\n"
    "🔹 *روشِ دریافتِ لینک:*\n"
    "وارد آرشیوِ وادانا شوید، روی کلاسِ موردنظر بزنید، سپس لینکِ بالای مرورگر را به‌طور کامل "
    "کپی کرده و همین‌جا ارسال کنید.\n\n"
    "🔹 *یکی از گزینه‌ها را انتخاب کنید، سپس لینک را ارسال کنید:*\n"
    "📄 فایل‌ها — اسلایدهای PDF\n"
    "📝 وایت‌برد — نوشته‌های استاد به‌صورت PDF\n"
    "🎬 ویدیوی آرشیو — وایت‌برد/اسلاید همراه با صدا"
)
MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📂 دانلود فایل‌ها", callback_data="mode:files", style="success")],
    [InlineKeyboardButton(text="📝 دانلود وایت‌برد (PDF)", callback_data="mode:wb", style="success")],
    [InlineKeyboardButton(text="🎬 ساخت ویدیوی آرشیو", callback_data="mode:video", style="primary")],
    [InlineKeyboardButton(text="👤 پروفایل", callback_data="menu:profile"),
     InlineKeyboardButton(text="💬 پشتیبانی", callback_data="menu:support")],
])
FILES_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📄 اسناد (PDF/Word/PPT)", callback_data="ft:doc", style="success")],
    [InlineKeyboardButton(text="🎵 صدا", callback_data="ft:audio", style="success"),
     InlineKeyboardButton(text="🎞 ویدیو", callback_data="ft:video", style="success")],
    [InlineKeyboardButton(text="🖼 تصاویر", callback_data="ft:image", style="success"),
     InlineKeyboardButton(text="📦 همهٔ فایل‌ها", callback_data="ft:all", style="primary")],
    [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:main")],
])
CANCEL_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="لغو", callback_data="job_cancel", style="danger")]])
BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ بازگشت به منو", callback_data="menu:main")]])
RETRY_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data="job_retry", style="primary")],
    [InlineKeyboardButton(text="⬅️ بازگشت به منو", callback_data="menu:main")]])

def _report_kb(rec_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 گزارشِ مشکل", callback_data=f"report:{rec_id}", style="danger")]])

SUPPORT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🛑 گزارشِ مشکل", callback_data="report:support", style="danger")],
    [InlineKeyboardButton(text="⬅️ بازگشت به منو", callback_data="menu:main")],
])

FT_LABEL = {"doc": "سند", "audio": "صدا", "video": "ویدیو", "image": "تصویر", "all": "فایل"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}

FRESH = ("در صورتِ تکرارِ مشکل، احتمالاً لینک منقضی شده است. لطفاً دوباره وارد آرشیو شوید، "
         "روی همان کلاس بزنید و لینکِ تازهٔ بالای مرورگر را کپی و ارسال کنید.")

def _friendly_error(exc: Exception) -> str:
    """Map a job exception to a clear Persian message (session / timeout / disk / corrupt)."""
    s = str(exc).lower()
    if "not a package" in s or "login" in s or "session" in s or "expired" in s or "401" in s or "403" in s:
        return ("❌ این کلاس برای دانلود به ورود نیاز دارد (یا سشنِ لینک منقضی شده).\n"
                "لطفاً داخلِ آرشیو وارد شوید، روی همان کلاس بزنید و لینکِ کاملِ بالای مرورگر "
                "(همراه با ‎session=‎) را کپی و ارسال کنید.")
    if isinstance(exc, zipfile.BadZipFile):
        return "❌ فایلِ ضبط ناقص دریافت شد. لطفاً چند لحظه بعد دوباره تلاش کنید."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "❌ فضای دیسکِ سرور موقتاً پر است؛ لطفاً کمی بعد دوباره تلاش کنید."
    if "timed out" in s or "timeout" in s or "connection" in s or "proxy" in s:
        return ("❌ ارتباط با وادانا چند بار قطع شد (اختلالِ شبکه).\n"
                "چند لحظه صبر کن، بعد دکمهٔ «🔄 تلاش مجدد» را بزن تا کار از همین‌جا ادامه پیدا کند.")
    return f"❌ متأسفانه مشکلی پیش آمد. لطفاً همان لینک را دوباره ارسال کنید.\n{FRESH}"

def _is_transient(exc: Exception) -> bool:
    """True for faults a plain retry can fix (network blip / incomplete download),
    False for ones it can't (needs login, expired session, disk full)."""
    if isinstance(exc, zipfile.BadZipFile):
        return True
    s = str(exc).lower()
    if any(k in s for k in ("not a package", "login", "session", "expired", "401", "403")):
        return False
    return any(k in s for k in ("timed out", "timeout", "connection", "proxy",
                                "aborted", "disconnect", "reset"))

STAGE = {
    "parse": "🔍 در حال بررسیِ نوعِ ضبط…",
    "audio": "🎧 در حال جداسازیِ صدا…",
    "render": "🎨 در حال رندرِ وایت‌برد…",
    "encode": "🎬 در حال آماده‌سازیِ ویدیو…",
    "done": "✅ آماده",
}
STAGE_MEDIA = dict(STAGE, render="🖼 در حال آماده‌سازیِ اسلایدها…")
L_FETCH = "📥 در حال دریافتِ ضبط از وادانا… (از مسیرِ ایران 🇮🇷)"
L_WB_RENDER = "📝 در حال آماده‌سازیِ صفحاتِ وایت‌برد…"
L_PREP = "📄 در حال آماده‌سازیِ فایل‌ها…"

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

USER_MODE: dict[int, str] = {}
USER_FILETYPE: dict[int, str] = {}
ACTIVE_USERS: set[int] = set()
PENDING_REPORT: dict[int, str] = {}
ACTIVE_TASKS: dict[int, asyncio.Task] = {}
ACTIVE_STOP: dict[int, asyncio.Event] = {}
ACTIVE_STATUS: dict[int, Message] = {}
LAST_USED: dict[int, float] = {}
SLIDES_SEM = asyncio.Semaphore(config.MAX_CONCURRENT)
VIDEO_SEM = asyncio.Semaphore(config.MAX_VIDEO_CONCURRENT)
REG = None
NODE_EVENTS: dict[str, asyncio.Event] = {}

_session = AiohttpSession(api=TelegramAPIServer.from_base(config.LOCAL_API_URL)) \
    if config.LOCAL_API_URL else None
bot = Bot(config.BOT_TOKEN, session=_session)
dp = Dispatcher()

class ThrottleMiddleware(BaseMiddleware):
    """Per-user flood guard. At most BURST updates per WINDOW seconds; anything over
    that is dropped before any handler runs — so one user can't pin the server or
    push the bot past Telegram's send limits (a dropped update sends nothing). The
    user is told once per window, then ignored until they ease off. Admins exempt."""
    WINDOW = 8.0
    BURST = 10

    def __init__(self):
        self._hits: dict[int, deque] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and user.id not in config.ADMINS:
            now = time.monotonic()
            dq = self._hits[user.id]
            while dq and now - dq[0] > self.WINDOW:
                dq.popleft()
            if len(dq) >= self.BURST:
                if now - self._warned.get(user.id, 0) > self.WINDOW:
                    self._warned[user.id] = now
                    await self._warn(event)
                return
            dq.append(now)
        return await handler(event, data)

    @staticmethod
    async def _warn(event):
        try:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ کمی آرام‌تر؛ چند لحظه صبر کنید.")
            elif isinstance(event, Message):
                await event.reply("⏳ پیام‌های زیادی پشتِ‌هم فرستادید؛ چند لحظه صبر کنید.")
        except Exception:
            pass

_throttle = ThrottleMiddleware()
dp.message.outer_middleware(_throttle)
dp.callback_query.outer_middleware(_throttle)

def _fmt(s) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"

def _bar(pct: float) -> str:
    pct = max(0, min(100, int(round(pct))))
    return "█" * round(pct / 10) + "░" * (10 - round(pct / 10)) + f"  {pct}%"

def _stat(uid, key):
    d = STORE["stats"].setdefault(str(uid), {"files": 0, "wb": 0, "videos": 0})
    d[key] = d.get(key, 0) + 1
    _store_save()

def _jalali(gy, gm, gd):
    """Gregorian -> Jalali (Solar Hijri). Pure, no dependency."""
    gdm = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    g_y2 = gy - 1600
    days = 365 * g_y2 + (g_y2 + 3) // 4 - (g_y2 + 99) // 100 + (g_y2 + 399) // 400
    days += sum(gdm[:gm - 1]) + gd - 1
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        days += 1
    days -= 79
    j_np = days // 12053
    days %= 12053
    jy = 979 + 33 * j_np + 4 * (days // 1461)
    days %= 1461
    if days >= 366:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd

def _today_fa() -> str:
    t = date.today()
    jy, jm, jd = _jalali(t.year, t.month, t.day)
    return f"{jy}/{jm:02d}/{jd:02d}"

def _hms_fa(sec) -> str:
    sec = int(sec or 0)
    h, mnt = sec // 3600, (sec % 3600) // 60
    return f"{h} ساعت و {mnt} دقیقه" if h else f"{mnt} دقیقه"

def _meta_put(rec_id, **kw):
    m = STORE.setdefault("meta", {}).get(rec_id, {})
    m.update(kw)
    STORE["meta"][rec_id] = m
    _store_save()

def _retry_put(uid, chat_id, rec, mode, ftype):
    """Remember a failed job so the 🔄 button can re-run it — persisted, so it
    survives a bot restart (the user can still retry after one)."""
    STORE.setdefault("retry", {})[str(uid)] = {
        "chat": chat_id, "host": rec.host, "rec_id": rec.rec_id,
        "token": rec.token, "mode": mode, "ftype": ftype}
    _store_save()

def _retry_pop(uid):
    if STORE.get("retry", {}).pop(str(uid), None) is not None:
        _store_save()

def _caption(title, rec_id, *, with_size=True, with_dur=False) -> str:
    meta = STORE.get("meta", {}).get(rec_id, {})
    lines = [title, f"🆔 {rec_id}", f"📅 تاریخِ ساخت: {meta.get('date') or _today_fa()}"]
    if with_size and meta.get("size"):
        lines.append(f"📦 حجم: {meta['size'] / 1024 / 1024:.1f} مگابایت")
    if with_dur and meta.get("dur"):
        lines.append(f"⏱ مدتِ کلاس: {_hms_fa(meta['dur'])}")
    return "\n".join(lines)

def _video_thumb(mp4_path, out_jpg):
    """First frame of the video as a Telegram thumbnail (<=320px). None on failure."""
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4_path,
                        "-vf", "scale=320:-1", "-frames:v", "1", out_jpg],
                       check=True, timeout=60)
        return out_jpg if os.path.exists(out_jpg) else None
    except Exception:
        return None

VIDEO_ETA_SEC = 900

class _Prog:
    def __init__(self):
        self.label, self.pct = "در حال آماده‌سازی…", 0.0
        self.min_total = None
        self.queued = False

    def set(self, label, pct):
        self.label, self.pct, self.queued = label, pct, False

async def _poll(status: Message, prog: _Prog, stop: asyncio.Event):
    start, i, last = time.time(), 0, ""
    shown, last_el = None, 0.0
    while not stop.is_set():
        i += 1
        el = time.time() - start
        dt, last_el = el - last_el, el
        if prog.queued:
            txt = (f"🕐 در صفِ پردازش\n{prog.label}\n"
                   f"⏱ {_fmt(el)} در صف {SPIN[i % len(SPIN)]}")
            if txt != last:
                try:
                    await status.edit_text(txt, reply_markup=CANCEL_KB)
                    last = txt
                except Exception:
                    pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            continue
        pct = prog.pct
        if pct >= 97:
            tail = "در حال اتمام…"
        elif el >= 10 and pct >= 15:
            rem = el * (100 - pct) / pct
            if prog.min_total:
                rem = max(rem, prog.min_total - el)
            shown = rem if shown is None else max(0.0, min(shown - dt, rem))
            tail = f"تقریباً {_fmt(shown)} باقی‌مانده" if shown >= 1 else "در حال اتمام…"
        else:
            tail = "در حال آماده‌سازی…"
        txt = (f"{prog.label}\n{_bar(pct)}\n"
               f"⏱ {_fmt(el)} سپری‌شده · {tail} {SPIN[i % len(SPIN)]}")
        if txt != last:
            try:
                await status.edit_text(txt, reply_markup=CANCEL_KB)
                last = txt
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

def _video_used_today(uid):
    d = STORE["video_day"].get(str(uid))
    return d[1] if d and d[0] == date.today().isoformat() else 0

def _video_inc(uid):
    today = date.today().isoformat()
    d = STORE["video_day"].get(str(uid))
    STORE["video_day"][str(uid)] = [today, 1] if not d or d[0] != today else [today, d[1] + 1]
    _store_save()

def _full_link(rec) -> str:
    """The full recording link as the user sent it — with the session token if there
    was one — so the channel caption lets an admin re-open the exact class."""
    base = f"{rec.host}/{rec.rec_id}/"
    return f"{base}?session={rec.token}" if rec.token else base

async def _archive(path, thumb=None, uid=None, link=None):
    """Upload a local file to the storage channel once; return (file_id, is_video).
    The thumbnail (first page/frame) is baked in here, so it rides along with the
    file_id on every later re-send — no need to re-attach it.

    When uid/link are given, the channel copy is captioned with who requested it
    (username + numeric id) and the recording link — for the admin's reference.
    Sent as plain text (no parse_mode), so user-controlled values can't inject."""
    name = os.path.basename(path)
    caption = name
    if uid is not None:
        try:
            ch = await bot.get_chat(uid)
            who = f"@{ch.username}" if ch.username else (ch.full_name or "—")
        except Exception:
            who = "—"
        caption = f"{name}\n👤 {who}\n🆔 {uid}"
        if link:
            caption += f"\n🔗 {link}"
    th = FSInputFile(thumb) if thumb and os.path.exists(thumb) else None
    if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
        msg = await bot.send_video(config.STORAGE_CHANNEL, FSInputFile(path),
                                   caption=caption, supports_streaming=True, thumbnail=th)
        return msg.video.file_id, True
    msg = await bot.send_document(config.STORAGE_CHANNEL, FSInputFile(path), caption=caption, thumbnail=th)
    return msg.document.file_id, False

async def _send_fid(m, fid, is_video, caption, markup=None) -> bool:
    """Send a previously-stored Telegram file by its file_id (instant, no disk)."""
    try:
        if is_video:
            await m.answer_video(fid, caption=caption, supports_streaming=True, reply_markup=markup)
        else:
            await m.answer_document(fid, caption=caption, reply_markup=markup)
        return True
    except Exception:
        logging.error("send_fid failed [%s]:\n%s", fid, traceback.format_exc())
        return False

async def _show(cb: CallbackQuery, text: str, markup=MENU):
    """Edit the menu message in place (keeping its buttons) instead of sending a new one."""
    try:
        await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        try:
            await cb.message.answer(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass

@dp.message(CommandStart())
async def start(m: Message):
    USER_MODE.pop(m.from_user.id, None)
    await m.answer(WELCOME, parse_mode="Markdown", reply_markup=MENU)

@dp.callback_query(F.data == "menu:profile")
async def profile(cb: CallbackQuery):
    uid = cb.from_user.id
    s = STORE["stats"].get(str(uid), {"files": 0, "wb": 0, "videos": 0})
    quota = ("🎟 سهمیهٔ ویدیو: نامحدود (ادمین)" if uid in config.ADMINS else
             f"🎟 سهمیهٔ ویدیوی امروز: {config.MAX_VIDEO_PER_DAY - _video_used_today(uid)} از {config.MAX_VIDEO_PER_DAY}")
    await _show(cb,
                f"👤 *پروفایلِ شما*\n\n"
                f"🆔 شناسه: `{uid}`\n"
                f"📄 فایل‌های دریافت‌شده: {s['files']}\n"
                f"📝 وایت‌بردهای دریافت‌شده: {s['wb']}\n"
                f"🎬 ویدیوهای ساخته‌شده: {s['videos']}\n"
                f"{quota}",
                BACK_KB)
    await cb.answer()

@dp.callback_query(F.data == "menu:support")
async def support(cb: CallbackQuery):
    await _show(cb, config.SUPPORT_TEXT or "💬 *پشتیبانی*\n\nبه‌زودی تکمیل می‌شود…", SUPPORT_KB)
    await cb.answer()

@dp.callback_query(F.data == "job_cancel")
async def job_cancel(cb: CallbackQuery):
    uid = cb.from_user.id
    stop = ACTIVE_STOP.get(uid)
    if stop:
        stop.set()
    task = ACTIVE_TASKS.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await cb.message.edit_text("❌ عملیات لغو شد. می‌توانید لینکِ بعدی را ارسال کنید.")
        except Exception:
            pass
        await cb.answer("لغو شد")
    else:
        await cb.answer("عملیاتی برای لغو وجود ندارد.")

@dp.callback_query(F.data == "job_retry")
async def job_retry(cb: CallbackQuery):
    uid = cb.from_user.id
    job = STORE.get("retry", {}).get(str(uid))
    if not job:
        await cb.answer("درخواستی برای تلاش مجدد نیست؛ لطفاً لینک را دوباره بفرستید.", show_alert=True)
        return
    if uid in ACTIVE_USERS:
        await cb.answer("یک کارِ شما در حال انجام است؛ کمی صبر کنید.")
        return
    rec = Recording(host=job["host"], rec_id=job["rec_id"], token=job.get("token", ""))
    USER_FILETYPE[uid] = job.get("ftype", "all")
    LAST_USED[uid] = time.time()
    await cb.answer("در حال تلاش مجدد…")
    ACTIVE_USERS.add(uid)
    ACTIVE_TASKS[uid] = asyncio.create_task(_run_job(cb.message, rec, job["mode"], uid))

@dp.callback_query(F.data == "menu:main")
async def back_main(cb: CallbackQuery):
    await _show(cb, "منوی اصلی — لطفاً یک گزینه را انتخاب کنید:", MENU)
    await cb.answer()

@dp.callback_query(F.data.startswith("ft:"))
async def choose_filetype(cb: CallbackQuery):
    uid, ft = cb.from_user.id, cb.data.split(":", 1)[1]
    USER_MODE[uid] = "files"
    USER_FILETYPE[uid] = ft
    label = "همهٔ فایل‌ها" if ft == "all" else FT_LABEL.get(ft, "فایل")
    await _show(cb, f"📂 *دانلودِ {label}* انتخاب شد. لطفاً لینکِ ضبط را ارسال کنید.", BACK_KB)
    await cb.answer()

@dp.callback_query(F.data.startswith("mode:"))
async def choose_mode(cb: CallbackQuery):
    uid, mode = cb.from_user.id, cb.data.split(":", 1)[1]
    if mode == "files":
        await _show(cb, "📂 *دانلودِ فایل‌ها*\nلطفاً نوعِ فایلِ موردنظر را انتخاب کنید:", FILES_MENU)
        await cb.answer()
        return
    if mode == "video" and not (config.ALLOW_VIDEO or uid in config.ADMINS):
        await _show(cb, "🎬 ساختِ ویدیو در حال حاضر غیرفعال است؛ لطفاً از «📂 دانلود فایل‌ها» استفاده کنید.", BACK_KB)
        await cb.answer()
        return
    USER_MODE[uid] = mode
    if mode == "wb":
        msg = ("📝 حالتِ *دانلود وایت‌برد* انتخاب شد. لطفاً لینکِ ضبطِ وایت‌بردی را ارسال کنید؛ "
               "نوشته‌های استاد به PDF تبدیل می‌شود.")
    else:
        left = config.MAX_VIDEO_PER_DAY - _video_used_today(uid)
        msg = (f"🎬 حالتِ *ساخت ویدیوی آرشیو* انتخاب شد. لطفاً لینکِ ضبط را ارسال کنید.\n"
               f"⚠️ ساخت ویدیو چند دقیقه زمان می‌برد. سهمیهٔ امروزِ شما: {left} از {config.MAX_VIDEO_PER_DAY}.")
    await _show(cb, msg, BACK_KB)
    await cb.answer()

@dp.callback_query(F.data.startswith("report:"))
async def report_start(cb: CallbackQuery):
    uid = cb.from_user.id
    PENDING_REPORT[uid] = cb.data.split(":", 1)[1]
    await cb.message.answer(
        "🛑 *گزارشِ مشکل*\n\nاگر مایل بودید، خلاصهٔ مشکل را در یک پیام بنویسید (اختیاری).\n"
        "برای ثبتِ بدونِ توضیح، /skip را بفرستید.", parse_mode="Markdown")
    await cb.answer()

@dp.message(lambda m: m.from_user and m.from_user.id in PENDING_REPORT)
async def handle_report_text(m: Message):
    uid = m.from_user.id
    rec_id = PENDING_REPORT.pop(uid, "?")
    summary = (m.text or "").strip()[:1000]
    if not summary or summary == "/skip":
        summary = "— (بدونِ توضیح)"
    u = m.from_user
    who = f"@{u.username}" if u.username else (u.full_name or "—")
    text = (f"#Boy 🛑 گزارشِ مشکل\n"
            f"👤 {who}  ({uid})\n"
            f"🎬 ضبط: {rec_id}\n"
            f"────────\n{summary}")
    try:
        if config.STORAGE_CHANNEL:
            await bot.send_message(config.STORAGE_CHANNEL, text)
    except Exception:
        logging.error("report forward failed:\n%s", traceback.format_exc())
    await m.reply("✅ گزارشِ شما ثبت و برای بررسی ارسال شد.")

@dp.message(F.text.regexp(LINK_RE.pattern))
async def handle_link(m: Message):
    uid = m.from_user.id
    if uid in ACTIVE_USERS:
        await m.reply("⚠️ یک درخواستِ شما در حال انجام است؛ لطفاً تا پایانِ آن صبر کنید "
                      "(یا با دکمهٔ «لغو» متوقفش کنید).")
        return
    if uid not in USER_MODE:
        await m.answer("ℹ️ ابتدا نوعِ خروجیِ موردنظر را از منو انتخاب کنید، سپس لینک را ارسال کنید:",
                       reply_markup=MENU)
        return
    wait = config.USER_COOLDOWN - (time.time() - LAST_USED.get(uid, 0))
    if wait > 0:
        await m.reply(f"⏳ لطفاً کمی صبر کنید؛ {int(wait)+1} ثانیهٔ دیگر دوباره ارسال کنید.")
        return
    rec = parse_recording_url(LINK_RE.search(m.text).group(0))
    if not is_valid_recording(rec):
        await m.reply("❌ لینکِ معتبرِ ضبطِ ادوبی کانکت بفرستید — آدرسِ کاملِ جلسه را از مرورگر کپی کنید.")
        return
    mode = USER_MODE[uid]
    if mode == "video" and not (config.ALLOW_VIDEO or uid in config.ADMINS):
        mode = "slides"
    LAST_USED[uid] = time.time()
    ACTIVE_USERS.add(uid)
    ACTIVE_TASKS[uid] = asyncio.create_task(_run_job(m, rec, mode, uid))

async def _run_job(m, rec, mode, uid):
    ok = False
    log.info("job start: uid=%s mode=%s rec=%s", uid, mode, rec.rec_id)
    try:
        if mode == "video":
            await do_video(m, rec, uid)
        elif mode == "wb":
            await do_whiteboard(m, rec, uid)
        else:
            await do_files(m, rec, USER_FILETYPE.get(uid, "all"), uid)
        ok = True
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error("job failed [rec=%s mode=%s uid=%s]\n%s",
                  rec.rec_id, mode, uid, traceback.format_exc())
        markup = None
        if _is_transient(e):
            _retry_put(uid, m.chat.id, rec, mode, USER_FILETYPE.get(uid, "all"))
            markup = RETRY_KB
        text = _friendly_error(e)
        status = ACTIVE_STATUS.get(uid)
        try:
            if status:
                await status.edit_text(text, reply_markup=markup)
            else:
                await m.answer(text, reply_markup=markup)
        except Exception:
            try:
                await m.answer(text, reply_markup=markup)
            except Exception:
                pass
    finally:
        log.info("job done: uid=%s mode=%s rec=%s ok=%s", uid, mode, rec.rec_id, ok)
        ACTIVE_USERS.discard(uid)
        ACTIVE_TASKS.pop(uid, None)
        ACTIVE_STOP.pop(uid, None)
        ACTIVE_STATUS.pop(uid, None)
        if ok:
            USER_MODE.pop(uid, None)
            _retry_pop(uid)

async def do_files(m, rec, ftype, uid):
    status = await m.reply("🔎 در حال بررسی…")
    ACTIVE_STATUS[uid] = status
    manifest = _store_get("files", rec.rec_id)

    if manifest is None:
        prog, stop = _Prog(), asyncio.Event()
        if SLIDES_SEM.locked():
            prog.queued = True
            prog.label = "یک دانلودِ دیگر روی سرور در حال انجام است؛ به‌نوبت شروع می‌شود."
        ACTIVE_STOP[uid] = stop
        poller = asyncio.create_task(_poll(status, prog, stop))
        tmp = os.path.join(config.WORK_DIR, f"{rec.rec_id}_files")
        try:
            async with SLIDES_SEM:
                shutil.rmtree(tmp, ignore_errors=True)
                client = ConnectClient(rec.host, rec.token, proxy=config.IRAN_PROXY)
                prog.set(L_FETCH, 0)
                zf = await asyncio.to_thread(client.open_package, rec.rec_id,
                                             lambda g, t: prog.set(L_FETCH, (g / t * 70) if t else 35))
                prog.set(L_PREP, 75)
                saved = await asyncio.to_thread(download_slides, client, rec.rec_id, tmp, zf,
                                                lambda i, t: prog.set(L_PREP, 75 + i / t * 20))
            stop.set(); await poller
            if not saved:
                await status.edit_text("ℹ️ این جلسه هیچ فایلِ اشتراکی‌ای نداشت.\n"
                                       "اگر استاد روی وایت‌برد نوشته است، «📝 دانلود وایت‌برد» را انتخاب کنید. (/start)")
                return
            manifest = []
            allf = sorted(saved)
            for i, p in enumerate(allf, 1):
                await status.edit_text(f"📤 در حال ذخیره‌سازی در آرشیو… {i} از {len(allf)}")
                fid, isv = await _archive(p, uid=uid, link=_full_link(rec))
                manifest.append({"name": os.path.basename(p), "cat": category_of(p), "fid": fid, "v": isv})
            _store_put("files", rec.rec_id, manifest)
            _meta_put(rec.rec_id, date=_today_fa())
        finally:
            stop.set()
            if not poller.done():
                await poller
            shutil.rmtree(tmp, ignore_errors=True)

    items = manifest if ftype == "all" else [it for it in manifest if it["cat"] == ftype]
    if not items:
        label = "همهٔ فایل‌ها" if ftype == "all" else FT_LABEL.get(ftype, "فایل")
        await status.edit_text(f"ℹ️ فایلی از نوعِ «{label}» در این جلسه پیدا نشد.\n"
                               "می‌توانید نوعِ دیگری انتخاب کنید یا /start را بزنید.")
        return
    await status.edit_text(f"📤 در حال ارسال… ({len(items)} فایل)")
    sent = sum([await _send_fid(m, it["fid"], it.get("v", False),
                                _caption(it["name"], rec.rec_id, with_size=False))
                for it in items])
    for _ in range(sent):
        _stat(uid, "files")
    await status.edit_text(f"✅ {sent} فایل ارسال شد.\nبرای ضبطِ بعدی /start را بزنید.",
                           reply_markup=_report_kb(rec.rec_id))

async def do_whiteboard(m, rec, uid):
    status = await m.reply("🔎 در حال بررسی…")
    ACTIVE_STATUS[uid] = status

    fid = _store_get("wb", rec.rec_id)
    if fid:
        await status.edit_text("📤 در حال ارسال… (از آرشیو)")
        if await _send_fid(m, fid, False, _caption("📝 وایت‌بردِ کلاس", rec.rec_id),
                           markup=_report_kb(rec.rec_id)):
            _stat(uid, "wb")
            await status.edit_text("✅ فایلِ PDFِ وایت‌برد ارسال شد. (/start)")
            return
        STORE["wb"].pop(rec.rec_id, None)
        _store_save()

    prog, stop = _Prog(), asyncio.Event()
    if SLIDES_SEM.locked():
        prog.queued = True
        prog.label = "یک دانلودِ دیگر روی سرور در حال انجام است؛ به‌نوبت شروع می‌شود."
    ACTIVE_STOP[uid] = stop
    poller = asyncio.create_task(_poll(status, prog, stop))
    work = os.path.join(config.WORK_DIR, f"{rec.rec_id}_wb")
    tmp = os.path.join(work, "wb.pdf")
    thumb = os.path.join(work, "thumb.jpg")
    try:
        async with SLIDES_SEM:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            client = ConnectClient(rec.host, rec.token, proxy=config.IRAN_PROXY)
            prog.set(L_FETCH, 0)
            zf = await asyncio.to_thread(client.open_package, rec.rec_id,
                                         lambda g, t: prog.set(L_FETCH, (g / t * 72) if t else 35))
            prog.set(L_WB_RENDER, 80)
            pdfs = await asyncio.to_thread(download_slides, client, rec.rec_id,
                                           os.path.join(work, "pdfs"), zf, None, {".pdf"})
            result = await asyncio.to_thread(wb_mod.make_pdf, zf, tmp, 2, thumb, pdfs or None)
        stop.set(); await poller
        if result is None:
            await status.edit_text("ℹ️ این ضبط، وایت‌برد نداشت.\n"
                                   "احتمالاً اسلاید بوده است — لطفاً «📂 دانلود فایل‌ها» را انتخاب کنید. (/start)")
            return
        await status.edit_text("📤 در حال ذخیره و ارسال…")
        _meta_put(rec.rec_id, date=_today_fa(), size=os.path.getsize(tmp))
        fid, _ = await _archive(tmp, thumb, uid, _full_link(rec))
        _store_put("wb", rec.rec_id, fid)
        await _send_fid(m, fid, False, _caption("📝 وایت‌بردِ کلاس", rec.rec_id),
                        markup=_report_kb(rec.rec_id))
        _stat(uid, "wb")
        await status.edit_text("✅ فایلِ PDFِ وایت‌برد ارسال شد. (/start)")
    finally:
        stop.set()
        if not poller.done():
            await poller
        shutil.rmtree(work, ignore_errors=True)

def _write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)

def _load_allowlist(reg):
    try:
        with open(os.path.join(config.NODE_DIR, "allowlist.json"), encoding="utf-8") as f:
            reg.load_allowlist(json.load(f))
    except FileNotFoundError:
        pass

async def _offload_video(rec, prog, stop):
    """Download the recording package and hand the heavy build to a worker node.
    Returns the mp4 path the node produced, or None to fall back to a local render
    (node timed out, failed, or the user cancelled). Never raises through to the
    caller's local path."""
    job_id = f"{rec.rec_id}-{uuid.uuid4().hex[:8]}"
    jobs_dir = os.path.join(config.NODE_DIR, "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    pkg_path = os.path.join(jobs_dir, f"{job_id}.zip")
    client = ConnectClient(rec.host, rec.token, proxy=config.IRAN_PROXY)
    prog.set(L_FETCH, 0)
    data = await asyncio.to_thread(client.download_package_bytes, rec.rec_id,
                                   lambda g, t: prog.set(L_FETCH, (g / t * 25) if t else 12))
    await asyncio.to_thread(_write_file, pkg_path, data)
    ev = asyncio.Event()
    NODE_EVENTS[job_id] = ev
    REG.enqueue(job_id, pkg_path, rec.rec_id)
    prog.set("🛰 به نودِ کارگر سپرده شد؛ در حال پردازش…", 30)
    try:
        deadline = time.monotonic() + config.CLAIM_TTL
        while not ev.is_set() and not stop.is_set() and time.monotonic() < deadline:
            try:
                await asyncio.wait_for(ev.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            p = REG.get_progress(job_id)
            if p:
                prog.set(STAGE.get(p[0], p[0]), 30 + min(p[1], 100) * 0.6)
        REG.pop_failed(job_id)
        return REG.pop_result(job_id)
    finally:
        NODE_EVENTS.pop(job_id, None)
        try:
            os.remove(pkg_path)
        except OSError:
            pass

async def do_video(m, rec, uid):
    status = await m.reply("🔎 در حال بررسی…")
    ACTIVE_STATUS[uid] = status

    fid = _store_get("video", rec.rec_id)
    if fid:
        await status.edit_text("📤 در حال ارسال… (از آرشیو)")
        if await _send_fid(m, fid, True, _caption("🎬 ویدیوی آرشیوِ کلاس", rec.rec_id, with_dur=True),
                           markup=_report_kb(rec.rec_id)):
            await status.edit_text("✅ ویدیو ارسال شد. (/start)")
            return
        STORE["video"].pop(rec.rec_id, None)
        _store_save()

    if uid not in config.ADMINS and _video_used_today(uid) >= config.MAX_VIDEO_PER_DAY:
        await status.edit_text(f"⛔ سقفِ روزانهٔ ساختِ ویدیو ({config.MAX_VIDEO_PER_DAY} عدد) تکمیل شده است. "
                               "لطفاً فردا دوباره تلاش کنید. (ویدیوهای ساخته‌شدهٔ قبلی همچنان رایگان از آرشیو ارسال می‌شوند.)")
        return

    prog, stop = _Prog(), asyncio.Event()
    prog.min_total = VIDEO_ETA_SEC
    ACTIVE_STOP[uid] = stop
    poller = asyncio.create_task(_poll(status, prog, stop))
    work = os.path.join(config.WORK_DIR, f"{rec.rec_id}_video")
    tmp_out = os.path.join(work, "out.mp4")
    thumb = os.path.join(work, "thumb.jpg")
    node_mp4 = None
    try:
        if config.NODE_API_ENABLE and REG is not None and should_offload(VIDEO_SEM.locked(), REG):
            node_mp4 = await _offload_video(rec, prog, stop)
        if node_mp4:
            tmp_out = node_mp4
        elif not stop.is_set():
            if VIDEO_SEM.locked():
                prog.queued = True
                prog.label = "یک ویدیوی دیگر در حال ساخت است؛ به‌نوبت شروع می‌شود."
            async with VIDEO_SEM:
                shutil.rmtree(work, ignore_errors=True)
                os.makedirs(work, exist_ok=True)
                client = ConnectClient(rec.host, rec.token, proxy=config.IRAN_PROXY)
                prog.set(L_FETCH, 0)
                zf = await asyncio.to_thread(client.open_package, rec.rec_id,
                                             lambda g, t: prog.set(L_FETCH, (g / t * 30) if t else 15))
                prog.set(STAGE["parse"], 32)
                sl = os.path.join(work, "pdfs")
                pdfs = await asyncio.to_thread(download_slides, client, rec.rec_id, sl, zf, None, {".pdf"})
                result = await asyncio.to_thread(video_mod.make_full_video, zf, work, tmp_out, 2, 4.0,
                                                 lambda s, p: prog.set(STAGE.get(s, s), 32 + p * 0.6),
                                                 pdfs or None)
                if result is None:
                    result = await asyncio.to_thread(video_mod.make_media_video, zf, work, tmp_out, pdfs or None, 2,
                                                     lambda s, p: prog.set(STAGE_MEDIA.get(s, s), 52 + p * 0.45))
        stop.set(); await poller
        if not os.path.exists(tmp_out):
            return
        await status.edit_text("📤 در حال ذخیره و ارسال…")
        os.makedirs(work, exist_ok=True)
        dur = await asyncio.to_thread(audio_mod.duration_seconds, tmp_out)
        _meta_put(rec.rec_id, date=_today_fa(), size=os.path.getsize(tmp_out), dur=dur)
        th = await asyncio.to_thread(_video_thumb, tmp_out, thumb)
        fid, _ = await _archive(tmp_out, th, uid, _full_link(rec))
        _store_put("video", rec.rec_id, fid)
        if uid not in config.ADMINS:
            _video_inc(uid)
        await _send_fid(m, fid, True, _caption("🎬 ویدیوی آرشیوِ کلاس", rec.rec_id, with_dur=True),
                        markup=_report_kb(rec.rec_id))
        _stat(uid, "videos")
        quota = ("بدونِ محدودیت (ادمین)" if uid in config.ADMINS else
                 f"سهمیهٔ امروز: {config.MAX_VIDEO_PER_DAY - _video_used_today(uid)} از {config.MAX_VIDEO_PER_DAY}")
        await status.edit_text(f"✅ ویدیوی آرشیو ارسال شد. ({quota}) (/start)")
    finally:
        stop.set()
        if not poller.done():
            await poller
        shutil.rmtree(work, ignore_errors=True)
        if node_mp4:
            try:
                os.remove(node_mp4)
            except OSError:
                pass

@dp.message()
async def fallback(m: Message):
    await m.answer("برای شروع، /start را بزنید، یک گزینه انتخاب کنید و سپس لینکِ ضبط را ارسال کنید.",
                   reply_markup=MENU)

async def main():
    global REG
    shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    if config.NODE_API_ENABLE:
        try:
            REG = NodeRegistry(config.HEARTBEAT_TTL, config.CLAIM_TTL)
            node_ca.create_ca(config.NODE_DIR)
            if not os.path.exists(os.path.join(config.NODE_DIR, "server.crt")):
                node_ca.issue_cert(config.NODE_DIR, "master", server=True, out_prefix="server")
            _load_allowlist(REG)

            async def on_result(jid, _path):
                ev = NODE_EVENTS.get(jid)
                if ev:
                    ev.set()

            async def on_fail(jid, reason):
                log.info("node job failed: %s (%s)", jid, reason)
                ev = NODE_EVENTS.get(jid)
                if ev:
                    ev.set()

            await start_node_api(REG, config.NODE_DIR, config.NODE_API_HOST,
                                 config.NODE_API_PORT, on_result, on_fail)
            log.info("node API listening on %s:%s", config.NODE_API_HOST, config.NODE_API_PORT)
        except Exception:
            log.error("node API failed to start; running local-only:\n%s", traceback.format_exc())
            REG = None
    print("bot running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
