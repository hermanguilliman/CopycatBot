from pathlib import Path

from loguru import logger
from telethon import TelegramClient

from .config import load_config, setup_logger
from .database import Database
from .sync_manager import SyncManager

setup_logger()


class CopycatBot:
    def __init__(self):
        self.config = load_config()
        self.client = TelegramClient(
            "sessions/CopycatBot",
            self.config.api_id,
            self.config.api_hash,
            system_lang_code="ru",
            system_version="copycat-bot-from-the-outer-space",
            device_model="beta-the-naked-one",
            app_version="0.1.0",
        )
        self.db = Database()
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        self.sync_manager = SyncManager(
            self.client, self.config, self.db, self.temp_dir
        )

    async def run(self):
        await self.client.start()
        logger.info("Бот запущен")

        await self.sync_manager.sync_existing_files()
        await self.sync_manager.monitor_new_files()

        await self.client.run_until_disconnected()
