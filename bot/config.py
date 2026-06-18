"""
Bot configuration — all from environment variables (12-factor style).

Required:
  BOT_TOKEN        Telegram bot token
Recommended:
  IRAN_PROXY       proxy to reach the Iran-only Vadana server from abroad,
                   e.g. socks5://user:pass@1.2.3.4:1080  or  http://1.2.3.4:8080
Optional:
  ADMINS           comma-separated Telegram user ids (allowed to make videos)
  MAX_CONCURRENT   global parallel jobs (default 3) — protects the server
  USER_COOLDOWN    seconds a user must wait between jobs (default 20)
  ALLOW_VIDEO      "1" to allow whiteboard->video for admins (heavy; default 0)
  MAX_UPLOAD_MB    skip files larger than this when sending (default 49)
  WORK_DIR         scratch dir for downloads (default ./bot_work)
"""
import os


def _ids(s: str) -> set[int]:
    return {int(x) for x in s.replace(" ", "").split(",") if x.isdigit()}


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
IRAN_PROXY = os.environ.get("IRAN_PROXY") or None
ADMINS = _ids(os.environ.get("ADMINS", ""))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "3"))        # parallel slide jobs
MAX_VIDEO_CONCURRENT = int(os.environ.get("MAX_VIDEO_CONCURRENT", "1"))  # parallel video builds (heavy)
MAX_VIDEO_PER_DAY = int(os.environ.get("MAX_VIDEO_PER_DAY", "3"))   # per-user daily video builds
USER_COOLDOWN = int(os.environ.get("USER_COOLDOWN", "15"))
ALLOW_VIDEO = os.environ.get("ALLOW_VIDEO", "0") == "1"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "1950"))   # try big files; Telegram errors are handled
WORK_DIR = os.environ.get("WORK_DIR", "bot_work")
CACHE_DIR = os.environ.get("CACHE_DIR", "cache")                    # rec_id-keyed result cache
SUPPORT_TEXT = os.environ.get("SUPPORT_TEXT", "")                   # shown in the Support section
LOCAL_API_URL = os.environ.get("LOCAL_API_URL") or None             # local Bot API server -> 2GB uploads
LOG_DIR = os.environ.get("LOG_DIR", "logs")                         # error logs go here
STORAGE_CHANNEL = int(os.environ.get("STORAGE_CHANNEL", "0")) or None  # store files in Telegram, reuse file_id

if not BOT_TOKEN:
    raise SystemExit("Set BOT_TOKEN (and ideally IRAN_PROXY) in the environment.")
