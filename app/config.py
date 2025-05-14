import json
from sys import stdout

from loguru import logger


class Config:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r") as f:
            config = json.load(f)
        self.api_id: int = config["api_id"]
        self.api_hash: str = config["api_hash"]
        self.source_chat_id: int = config["source_chat_id"]
        self.dest_chat_id: int = config["dest_chat_id"]


def load_config():
    return Config()


def setup_logger():
    logger.remove()
    logger.add(
        "logs/CopycatBot.log", level="DEBUG", rotation="100 MB", enqueue=True
    )
    logger.add(
        stdout,
        colorize=True,
        format="<green>{time}</green> <level>{message}</level>",
        level="DEBUG",
    )
