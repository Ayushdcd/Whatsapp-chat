import logging
import os
from pathlib import Path

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
WEBHOOK_LOG_FILE = Path(os.getenv("WEBHOOK_LOG_FILE", LOG_DIR / "webhook.txt"))


def _ensure_log_file():
    WEBHOOK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEBHOOK_LOG_FILE.touch(exist_ok=True)

    try:
        WEBHOOK_LOG_FILE.chmod(0o600)
    except OSError:
        pass


_ensure_log_file()

webhook_logger = logging.getLogger("whatsapp_webhook")
webhook_logger.setLevel(logging.INFO)
webhook_logger.propagate = False

if not webhook_logger.handlers:
    handler = logging.FileHandler(WEBHOOK_LOG_FILE, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    webhook_logger.addHandler(handler)
