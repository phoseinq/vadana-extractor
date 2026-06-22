# Changelog

## v3.0.0
+ **Worker nodes.** When the master's single video slot is busy, it can offload the heavy build to a remote worker node over mutually-authenticated TLS, so fewer jobs wait in the queue. The node is pure CPU + ffmpeg (no Iran proxy, no Telegram token) — the master bundles the recording package with the shared PDFs, the node renders and returns the mp4. **Off by default (`NODE_API_ENABLE=0`); with no node connected the master builds everything itself, exactly as before, and no job is ever stranded.**
+ New `vadana node` CLI: `init` (create the CA), `add` (issue a node cert + print a bundle), `list` / `status` / `remove`.
+ The worker side ships as its own repo, [vadana-node](https://github.com/phoseinq/vadana-node) (worker + Docker).

## v2.5.0
+ Video audio gets a speech-cleanup pass — a high-pass to cut low rumble, an FFT denoiser for steady background hiss/hum, then level-evening so a quiet professor and a louder student sit closer. On by default; tune the ffmpeg chain or turn it off with the `AUDIO_DENOISE` env var.

## v2.4.1
+ README: an architecture section for contributors — the concurrency model, the two semaphores (downloads vs. video builds), and what happens when two people build a video at the same time.

## v2.4.0
+ Works with any Adobe Connect server now, not just IAU "Vadana". Send the full recording link from any Connect host — the input filter accepts any public host (and still blocks internal/private addresses, so the SSRF guard is intact) and the package layout is the standard Connect format.
+ Docker support: a `Dockerfile` + `docker-compose.yml`. One installer command (`curl … | bash`) that asks Docker or native, fills `bot/.env`, and starts the bot.
+ The three entry scripts moved into a `cli/` package (`cli/download_slides.py`, `cli/make_video.py`, `cli/api.py`) to keep the repo root clean.
+ README: an input→output example and an Adobe Connect badge.

## v2.3.1
+ Annotated-PDF output: the page is no longer squished into the 4:3 board — it's restored to the PDF's real (usually landscape) aspect, so text and shapes aren't distorted. Applies to both the synced video and the whiteboard PDF; the strokes ride along and stay aligned. Pure whiteboard (no PDF) is unchanged.

## v2.3.0
**Security & hardening**
+ One input filter (`is_valid_recording`) on every entry point — bot, API, and both CLIs. The host must be under `ec.iau.ir`, the recording id alphanumeric, and the session token alphanumeric, so a crafted link can't point at another host (SSRF), traverse paths, or smuggle URL/header tricks through the session value.
+ A crafted `downloadUrl` inside a package can no longer redirect the authenticated request off-host — only same-host relative paths are followed, and the session token is never sent to a non-IAU URL.
+ The "report a problem" text is forwarded as plain text (user input is no longer parsed as Markdown) and length-capped.

**Anti-spam**
+ Per-user flood guard: at most ~10 updates per 8s; bursts are dropped before any work runs or any message is sent — protecting the server and keeping the bot under Telegram's send limits. Admins are exempt.

**Cleanup**
+ Orphaned work dirs from a crashed job are cleared on startup (results already live on Telegram by `file_id`).
+ Removed dead code (`make_whiteboard_video`, `_send_with_bar`, unused labels/imports).

## v2.2.2
+ Annotated-PDF video: the PDF page now follows the recording's **real page-flip timeline** (the `currentPage` events), so it switches exactly when the professor flipped — exact, deterministic sync, replacing the v2.2.1 midpoint estimate

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
