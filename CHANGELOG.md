# Changelog

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
