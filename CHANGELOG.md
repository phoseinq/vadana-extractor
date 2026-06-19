# Changelog

## v2.2.1
+ Annotated-PDF video: the PDF page now switches at the midpoint of a long talk-gap instead of waiting for the next stroke, so the page tracks the audio more closely (the package records strokes, not page flips, so this is a best-effort estimate)

## v2.2.0
+ **Annotated PDFs**: when the professor draws on a shared PDF, the whiteboard PDF and the video now show the PDF page behind the strokes (matched 1:1 by page count) instead of the annotations floating on a blank white page

## v2.1.4
+ When a job fails (e.g. a recording that needs login), the error now replaces the live progress message in place and the progress stops — no more leftover "0% در حال دریافت…" bar with the error as a separate message

## v2.1.3
+ A request waiting behind another job now clearly shows "🕐 در صفِ پردازش" (in queue) instead of a frozen 0% progress bar that looked stuck

## v2.1.2
+ The 🔄 retry button now survives a bot restart — the failed job is remembered on disk, so you can still tap retry after the bot updates instead of re-sending the link

## v2.1.1
+ The "approximate time remaining" now only counts down — it never creeps up when progress plateaus, and switches to "finishing up" once it runs past the estimate
+ Raised the video time estimate to ~15 min (the whiteboard smoothing made renders heavier)

## v2.1.0
+ The download now retries up to **3 times** on a dropped connection (backing off a little longer each time), instead of once
+ If it still fails after that, the error comes with a **🔄 retry button** — wait a moment, tap it, and the same job runs again without re-pasting the link

## v2.0.1
+ Retry the recording download once when the connection drops mid-transfer (the Iran link blips now and then) — fewer spurious "try again" errors

## v2.0.0
+ Works with every IAU branch host, not just `vadavc30` — `vadavc30`, `vadana14` (Zanjan), `vadana36`, and the rest. Links from other branches no longer get ignored.
+ The session is now optional — recordings that open directly (most older terms) download without a `?session=`; you're only asked to log in when one actually needs it
+ Smoother whiteboard strokes — sparse, shaky handwriting renders as clean curves instead of crooked segments
+ Sent files carry a thumbnail (first page / first video frame) and a short details caption: recording id, date, size, and class length for videos

## v1.5.3
+ One-line installer (`install.sh` self-clones the repo)
+ Windows setup steps in the README

## v1.5.2
+ Formal README wording
+ Admins are exempt from the daily video quota

## v1.5.1
+ Cleaner wording in the bot's Persian messages

## v1.5.0
+ **Test suite** (`pytest`) — URL parser, file extractor, and whiteboard / timeline converters, all on synthetic fixtures (no real recording needed)
+ **CI** — GitHub Actions runs ruff + pytest on Python 3.11 & 3.12 and byte-compiles, on every push
+ **Logging** — rotating, levelled, timestamped logs (`logs/bot.log`) instead of bare prints
+ **Error handling** — clear messages for expired session/link, network/proxy failure, low disk, and corrupt packages
+ **HTTP API** (optional) — `POST /extract` returns the shared files (zip) or the whiteboard PDF
+ **Interactive CLI** — the `vadana` command gained a colored menu and download actions (files / whiteboard / video) alongside service control
+ **Security** — filename sanitization hardened against path traversal; SOCKS5 proxy support (PySocks)

## v1.1.0
+ `vadana` management CLI + `install.sh`
+ "Report a problem" button under every result, forwarded to the storage channel (tagged `#Boy`)
+ Comment-free codebase and a cleaned-up bilingual README

## v1.0.0
+ First public release — shared files, whiteboard PDF, and a synced archive video; Persian Telegram bot + CLI tools
