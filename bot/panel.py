from __future__ import annotations

import datetime
import html as _html

from aiogram import F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent,
)

from bot import config

_PENDING_MSG: dict[int, int] = {}
_PENDING_REPLY: dict[int, int] = {}
_LAST_SENT: dict[int, int] = {}   # recipient uid -> message_id of the bot's last panel message (for two-way delete)

def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))

def _is_admin(uid: int) -> bool:
    return uid in config.ADMINS

def _btn(text, data, style=None):
    kw = {"text": text, "callback_data": data}
    if style:
        kw["style"] = style
    return InlineKeyboardButton(**kw)

def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def _fmt_bytes(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024

def _idlink(uid) -> str:
    """Numeric id plus tap-to-open links — iOS (t.me/@id…) and Android (tg://openmessage…)."""
    return (f'<code>{uid}</code> '
            f'<a href="https://t.me/@id{uid}">iOS</a>·'
            f'<a href="tg://openmessage?user_id={uid}">Android</a>')

def setup(dp, bot, db, store, save, video_used_today, video_inc) -> None:

    def _who(uid: int) -> str:
        u = db.get_user(uid)
        if u and u["username"]:
            return "@" + u["username"]
        if u and u["name"]:
            return u["name"]
        return str(uid)

    def _card(uid: int):
        u = db.get_user(uid)
        used = video_used_today(uid)
        quota = config.MAX_VIDEO_PER_DAY
        name = (u["name"] if u else "") or "—"
        uname = u["username"] if u else ""
        banned = bool(u and u["banned"])
        links = u["links"] if u else 0
        ok = u["ok"] if u else 0
        dl = u["dl"] if u else 0
        ul = u["ul"] if u else 0
        first = u["first_ts"] if u else None
        last = u["last_ts"] if u else None
        head = (" @" + _esc(uname)) if uname else ""
        lines = [
            "🔧 <b>پنل ادمین — کاربر</b>",
            f"👤 {_esc(name)}{head}",
            f"🆔 {_idlink(uid)}",
            f"📅 اولین: {_fmt_ts(first)} · آخرین: {_fmt_ts(last)}",
            f"📊 درخواست‌ها: {links} (موفق {ok})",
            f"📦 دانلود {_fmt_bytes(dl)} · آپلود {_fmt_bytes(ul)}",
            f"🎬 ویدیوی امروز: {used}/{quota}",
            ("🚫 <b>وضعیت: مسدود</b>" if banned else "✅ وضعیت: فعال"),
        ]
        rl = db.recent_links(uid, 4)
        if rl:
            lines.append("\n🔗 <b>آخرین لینک‌ها:</b>")
            for r in rl:
                link = f"{r['host']}/{r['rec_id']}/"
                if r["token"]:
                    link += f"?session={r['token']}"
                lines.append(f"{'✅' if r['ok'] else '❌'} <code>{_esc(link)}</code>")
        rows = [[_btn("✉️ پیام به کاربر", f"pmsg:{uid}", "primary")]]
        if _LAST_SENT.get(uid):
            rows.append([_btn("🗑 حذف آخرین پیامِ ربات", f"pdel:{uid}", "danger")])
        rows += [
            [_btn(("✅ آنبن" if banned else "🚫 بن"), f"pban:{uid}", "danger"),
             _btn("♻️ ریست سهمیه", f"prl:{uid}", "success")],
            [InlineKeyboardButton(text="🔍 جستجوی کاربرِ دیگر", switch_inline_query_current_chat="")],
            [_btn("✖️ بستن", "pclose")],
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        return "\n".join(lines), kb

    async def _edit(cb: CallbackQuery, text, kb):
        try:
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)

    @dp.message(Command("panel"))
    async def cmd_panel(m: Message):
        if not _is_admin(m.from_user.id):
            return
        st = db.stats()
        v = st["modes"].get("video", 0)
        w = st["modes"].get("wb", 0)
        f = st["links"] - v - w
        text = ("📊 <b>پنل ادمین — آمار کلی</b>\n\n"
                f"👥 کاربرها: <b>{st['users']}</b>"
                + (f" · 🚫 مسدود: {st['banned']}" if st["banned"] else "") + "\n"
                f"🔗 درخواست‌ها: <b>{st['links']}</b>  (✅ {st['ok']} · ❌ {st['fail']})\n"
                f"   🎬 ویدیو {v} · 📝 وایت‌برد {w} · 📂 فایل {f}\n"
                f"⬇️ حجم دانلود: <b>{_fmt_bytes(st['dl'])}</b>\n"
                f"⬆️ حجم آپلود: <b>{_fmt_bytes(st['ul'])}</b>\n\n"
                "برای دیدنِ یک کاربر دکمهٔ زیر را بزنید و آیدیِ عددی یا @یوزرنیم را تایپ کنید.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 جستجوی کاربر", switch_inline_query_current_chat="")],
            [_btn("✖️ بستن", "pclose")],
        ])
        await m.answer(text, parse_mode="HTML", reply_markup=kb)

    @dp.message(Command("u"))
    async def cmd_u(m: Message):
        if not _is_admin(m.from_user.id):
            return
        parts = (m.text or "").split()
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            await m.reply("استفاده: <code>/u &lt;uid&gt;</code>", parse_mode="HTML")
            return
        text, kb = _card(int(parts[1]))
        await m.answer(text, parse_mode="HTML", reply_markup=kb)

    @dp.inline_query()
    async def inline_search(q: InlineQuery):
        if not _is_admin(q.from_user.id):
            await q.answer([], cache_time=2, is_personal=True)
            return
        results = []
        for r in db.search_users(q.query, 12):
            uid = r["uid"]
            title = ("@" + r["username"]) if r["username"] else (r["name"] or str(uid))
            desc = f"🆔 {uid}" + ("  🚫 مسدود" if r["banned"] else "")
            results.append(InlineQueryResultArticle(
                id=str(uid), title=title, description=desc,
                input_message_content=InputTextMessageContent(message_text=f"/u {uid}")))
        if not results:
            results.append(InlineQueryResultArticle(
                id="none", title="کاربری پیدا نشد",
                description="آیدیِ عددی یا @یوزرنیم را امتحان کنید",
                input_message_content=InputTextMessageContent(message_text="/panel")))
        await q.answer(results, cache_time=2, is_personal=True)

    @dp.callback_query(F.data == "pclose")
    async def cb_close(cb: CallbackQuery):
        try:
            await cb.message.delete()
        except Exception:
            try:
                await cb.message.edit_text("بسته شد.")
            except Exception:
                pass
        await cb.answer()

    @dp.callback_query(F.data.startswith("pban:"))
    async def cb_ban(cb: CallbackQuery):
        if not _is_admin(cb.from_user.id):
            return await cb.answer()
        uid = int(cb.data.split(":")[1])
        u = db.get_user(uid)
        new = not (u and u["banned"])
        db.set_ban(uid, new)
        await cb.answer("🚫 کاربر مسدود شد." if new else "✅ کاربر آزاد شد.")
        text, kb = _card(uid)
        await _edit(cb, text, kb)

    @dp.callback_query(F.data.startswith("prl:"))
    async def cb_reset_limit(cb: CallbackQuery):
        if not _is_admin(cb.from_user.id):
            return await cb.answer()
        uid = int(cb.data.split(":")[1])
        store["video_day"].pop(str(uid), None)
        save()
        await cb.answer("♻️ سهمیهٔ روزانه ریست شد.")
        text, kb = _card(uid)
        await _edit(cb, text, kb)

    @dp.callback_query(F.data.startswith("pmsg:"))
    async def cb_message(cb: CallbackQuery):
        if not _is_admin(cb.from_user.id):
            return await cb.answer()
        uid = int(cb.data.split(":")[1])
        _PENDING_MSG[cb.from_user.id] = uid
        await _edit(cb,
                    f"✏️ متنِ پیام برای <b>{_esc(_who(uid))}</b> ({_idlink(uid)}) را بفرستید.\n\n"
                    "بولد/مونو/ایتالیکِ تلگرام را همان‌جا استفاده کنید؛ خودم به HTML تبدیل و ارسال می‌کنم — "
                    "لازم نیست با تگ‌ها ور بروید.\nبرای لغو: /cancel",
                    None)
        await cb.answer()

    @dp.message(lambda m: m.from_user and m.from_user.id in _PENDING_MSG)
    async def on_admin_compose(m: Message):
        aid = m.from_user.id
        uid = _PENDING_MSG.get(aid)
        if (m.text or "").strip() == "/cancel":
            _PENDING_MSG.pop(aid, None)
            text, kb = _card(uid)
            await m.answer("لغو شد.\n\n" + text, parse_mode="HTML", reply_markup=kb)
            return
        if not m.text:
            await m.reply("فعلاً فقط متن پشتیبانی می‌شود. متن را بفرستید یا /cancel.")
            return
        _PENDING_MSG.pop(aid, None)
        body = m.html_text
        reply_kb = InlineKeyboardMarkup(inline_keyboard=[
            [_btn("💬 پاسخ", f"ureply:{aid}", "primary")]])
        try:
            sent = await bot.send_message(uid, body, parse_mode="HTML", reply_markup=reply_kb)
            _LAST_SENT[uid] = sent.message_id
            note = "✅ پیام ارسال شد. (برای حذفِ دوطرفه، دکمهٔ «🗑 حذف آخرین پیامِ ربات» را بزنید.)"
        except Exception as e:
            note = f"❌ ارسال نشد ({type(e).__name__}) — احتمالاً کاربر ربات را بلاک کرده."
        text, kb = _card(uid)
        await m.answer(note + "\n\n" + text, parse_mode="HTML", reply_markup=kb)

    @dp.callback_query(F.data.startswith("pdel:"))
    async def cb_del_msg(cb: CallbackQuery):
        if not _is_admin(cb.from_user.id):
            return await cb.answer()
        uid = int(cb.data.split(":")[1])
        mid = _LAST_SENT.get(uid)
        if not mid:
            return await cb.answer("پیامی برای حذف ثبت نشده.", show_alert=True)
        try:
            await bot.delete_message(uid, mid)            # private chat -> revokes for both sides
            _LAST_SENT.pop(uid, None)
            note = "✅ پیامِ ربات دوطرفه حذف شد."
        except Exception as e:
            note = f"❌ حذف نشد ({type(e).__name__}) — شاید بیش از ۴۸ ساعت گذشته یا قبلاً حذف شده."
        text, kb = _card(uid)
        await _edit(cb, note + "\n\n" + text, kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("ureply:"))
    async def cb_user_reply(cb: CallbackQuery):
        aid = int(cb.data.split(":")[1])
        _PENDING_REPLY[cb.from_user.id] = aid
        await cb.message.answer("✏️ پاسخِ خود را در یک پیام بنویسید (یا /cancel).")
        await cb.answer()

    @dp.message(lambda m: m.from_user and m.from_user.id in _PENDING_REPLY)
    async def on_user_reply(m: Message):
        uid = m.from_user.id
        aid = _PENDING_REPLY.pop(uid, None)
        if (m.text or "").strip() == "/cancel":
            await m.reply("لغو شد.")
            return
        if not m.text:
            await m.reply("فقط متن. دوباره دکمهٔ پاسخ را بزنید.")
            return
        who = ("@" + m.from_user.username) if m.from_user.username else (m.from_user.full_name or str(uid))
        head = f"💬 <b>پاسخ از</b> {_esc(who)} ({_idlink(uid)}):\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[[_btn("✉️ پاسخ", f"pmsg:{uid}", "primary")]])
        targets = [aid] + [a for a in config.ADMINS if a != aid]
        sent = False
        for admin in targets:
            try:
                await bot.send_message(admin, head + m.html_text, parse_mode="HTML", reply_markup=kb)
                sent = True
            except Exception:
                pass
        await m.reply("✅ پاسخِ شما برای پشتیبانی ارسال شد." if sent else "❌ ارسال نشد، بعداً تلاش کنید.")
