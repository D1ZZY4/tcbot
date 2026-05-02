# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps


import logging
from datetime import datetime


class BotLogFormatter(logging.Formatter):
    """
    [HH:MM] [DD-MM-YYYY] | <project> | <L> - <module>:<line> - <message>

    Level indicators: I=INFO, W=WARNING, E=ERROR, C=CRITICAL, D=DEBUG.
    """

    LEVEL_MAP = {
        logging.DEBUG: "D",
        logging.INFO: "I",
        logging.WARNING: "W",
        logging.ERROR: "E",
        logging.CRITICAL: "C",
    }

    def __init__(self, project_name: str):
        super().__init__()
        self.project_name = project_name

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.utcnow()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%d-%m-%Y")
        level = self.LEVEL_MAP.get(record.levelno, "?")
        module = record.name
        lineno = record.lineno
        message = record.getMessage()
        return f"[{time_str}] [{date_str}] | {self.project_name} | {level} - {module}:{lineno} - {message}"


def setup(level: int = logging.INFO) -> None:
    from tcbot.config import cfg
    formatter = BotLogFormatter(cfg.community_name)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
