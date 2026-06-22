import os

def _ids(s: str) -> set[int]:
    return {int(x) for x in s.replace(" ", "").split(",") if x.isdigit()}

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
IRAN_PROXY = os.environ.get("IRAN_PROXY") or None
ADMINS = _ids(os.environ.get("ADMINS", ""))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "3"))
MAX_VIDEO_CONCURRENT = int(os.environ.get("MAX_VIDEO_CONCURRENT", "1"))
MAX_VIDEO_PER_DAY = int(os.environ.get("MAX_VIDEO_PER_DAY", "3"))
USER_COOLDOWN = int(os.environ.get("USER_COOLDOWN", "15"))
ALLOW_VIDEO = os.environ.get("ALLOW_VIDEO", "0") == "1"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "1950"))
WORK_DIR = os.environ.get("WORK_DIR", "bot_work")
CACHE_DIR = os.environ.get("CACHE_DIR", "cache")
_support_file = os.path.join(os.path.dirname(__file__), "support.txt")
SUPPORT_TEXT = (open(_support_file, encoding="utf-8").read().strip()
                if os.path.exists(_support_file)
                else os.environ.get("SUPPORT_TEXT", "").replace("\\n", "\n"))
LOCAL_API_URL = os.environ.get("LOCAL_API_URL") or None
LOG_DIR = os.environ.get("LOG_DIR", "logs")
STORAGE_CHANNEL = int(os.environ.get("STORAGE_CHANNEL", "0")) or None

NODE_API_ENABLE = os.environ.get("NODE_API_ENABLE")
NODE_API_HOST = os.environ.get("NODE_API_HOST", "0.0.0.0")
NODE_API_PORT = int(os.environ.get("NODE_API_PORT", "8443"))
NODE_DIR = os.environ.get("NODE_DIR", "nodes")
HEARTBEAT_TTL = float(os.environ.get("HEARTBEAT_TTL", "30"))
CLAIM_TTL = float(os.environ.get("CLAIM_TTL", "1200"))

if not BOT_TOKEN:
    raise SystemExit("Set BOT_TOKEN (and ideally IRAN_PROXY) in the environment.")
