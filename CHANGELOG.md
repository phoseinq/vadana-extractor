# Changelog

## v1.5.1
+ Reworded the bot's Persian messages — dropped the AI-flavored / over-casual phrasing (and stray signature emoji) for a cleaner, more natural tone

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
