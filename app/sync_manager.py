import asyncio
from pathlib import Path
from typing import cast

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

from .config import Config
from .database import Database
from .media_processor import MediaProcessor


class SyncManager:
    def __init__(
        self,
        client: TelegramClient,
        config: Config,
        db: Database,
        temp_dir: Path,
    ):
        self.client = client
        self.config = config
        self.db = db
        self.temp_dir = temp_dir
        self.media_processor = MediaProcessor(client, config, db, temp_dir)

    async def sync_existing_files(self):
        last_processed_id = self.db.get_last_processed_id(
            self.config.source_chat_id
        )
        logger.info(f"Последнее обработанное сообщение: {last_processed_id}")

        messages_to_process = []
        grouped_messages = set()

        async for message in self.client.iter_messages(
            self.config.source_chat_id, reverse=True, min_id=last_processed_id
        ):
            message = cast(Message, message)
            if message.id <= last_processed_id:
                continue

            if message.media and not self.db.is_message_synced(message.id):
                messages_to_process.append(message)
                if message.grouped_id:
                    grouped_messages.add(message.id)

        messages_to_process.sort(key=lambda x: x.id)

        processed_groups = set()
        for message in messages_to_process:
            message = cast(Message, message)
            if (
                message.id in grouped_messages
                and message.grouped_id not in processed_groups
            ):
                media_group = [
                    msg
                    for msg in messages_to_process
                    if msg.grouped_id == message.grouped_id
                    and msg.id in grouped_messages
                ]
                media_group.sort(key=lambda x: x.id)
                if media_group:
                    logger.info(
                        f"Обработка медиагруппы {message.grouped_id} с сообщениями: {[msg.id for msg in media_group]}"
                    )
                    await self.media_processor.process_media_group(
                        media_group,
                        media_group[0].text or "",
                        message.grouped_id,
                    )
                    processed_groups.add(message.grouped_id)
            elif message.id not in grouped_messages:
                logger.info(f"Обработка одиночного медиа с id: {message.id}")
                await self.media_processor.process_single_media(message)

    async def monitor_new_files(self):
        processed_groups = set()

        @self.client.on(events.NewMessage(chats=self.config.source_chat_id))
        async def handler(event):
            message: Message = event.message
            if not message.media or self.db.is_message_synced(message.id):
                return

            if message.grouped_id:
                if message.grouped_id in processed_groups:
                    logger.info(
                        f"Сообщение {message.id} из медиагруппы {message.grouped_id} уже обработано"
                    )
                    return

                processed_groups.add(message.grouped_id)
                try:
                    media_group = [message]
                    await asyncio.sleep(2)
                    async for msg in self.client.iter_messages(
                        self.config.source_chat_id,
                        limit=20,
                        max_id=message.id + 20,
                        min_id=message.id - 20,
                    ):
                        if (
                            msg.grouped_id == message.grouped_id
                            and msg.id != message.id
                            and msg.media
                            and not self.db.is_message_synced(msg.id)
                        ):
                            media_group.append(msg)

                    media_group.sort(key=lambda x: x.id)
                    logger.info(
                        f"Собрано {len(media_group)} сообщений для медиагруппы {message.grouped_id}: {[msg.id for msg in media_group]}"
                    )
                    await self.media_processor.process_media_group(
                        media_group,
                        media_group[0].text or "",
                        message.grouped_id,
                    )

                except Exception as e:
                    logger.error(
                        f"Ошибка при обработке новой медиагруппы {message.grouped_id}: {str(e)}"
                    )
                finally:
                    processed_groups.discard(message.grouped_id)
            else:
                logger.info(f"Обработка одиночного медиа с id: {message.id}")
                await self.media_processor.process_single_media(message)
