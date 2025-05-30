import asyncio
from pathlib import Path

from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom.message import Message
from telethon.tl.types import (
    Document,
    MessageMediaPhoto,
)

from .config import Config
from .database import Database
from .file_handler import FileHandler


class MediaProcessor:
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
        self.file_handler = FileHandler(client, temp_dir)

    def _get_file_name(self, message: Message):
        """Получение имени файла для медиа"""
        if isinstance(message.media, MessageMediaPhoto):
            return f"photo_{message.id}.jpg"
        elif hasattr(message.media, "document") and isinstance(
            message.media.document, Document
        ):
            for attr in message.media.document.attributes:
                if hasattr(attr, "file_name"):
                    return attr.file_name
        return f"media_{message.id}"

    async def process_single_media(self, message: Message):
        """Обработка одиночного медиа"""
        try:
            file_name = self._get_file_name(message)
            file_path = await self.file_handler.download_media_with_retry(
                message, file_name
            )
            if not file_path:
                logger.warning(
                    f"Не удалось скачать медиа для сообщения {message.id}"
                )
                return

            # Проверяем, является ли сообщение ответом
            reply_to = None
            if message.reply_to_msg_id:
                reply_to = self.db.get_dest_message_id(
                    message.reply_to_msg_id, self.config.source_chat_id
                )
                if not reply_to:
                    logger.debug(
                        f"Не найдено dest_message_id для reply_to_msg_id={message.reply_to_msg_id}"
                    )

            sent_message: Message = (
                await self.file_handler.send_file_with_retry(
                    self.config.dest_chat_id,
                    file_path,
                    caption=message.text or "",
                    reply_to=reply_to,
                )
            )

            self.db.save_sync_state(
                message.id,
                self.config.source_chat_id,
                sent_message.id,
                file_name,
            )
            self.db.update_last_processed_id(
                self.config.source_chat_id, message.id
            )

            logger.info(f"Синхронизировано: {file_name} (id: {message.id})")

            await self.file_handler.cleanup_file(file_path)

        except Exception as e:
            logger.error(f"Ошибка при обработке медиа {message.id}: {str(e)}")

    async def process_media_group(
        self, messages: list[Message], caption, grouped_id
    ):
        """Обработка медиагруппы"""
        files = []
        file_names = []
        try:
            for message in messages:
                file_name = self._get_file_name(message)
                file_path = await self.file_handler.download_media_with_retry(
                    message, file_name
                )
                if not file_path:
                    logger.warning(
                        f"Не удалось скачать медиа для сообщения {message.id}"
                    )
                    continue
                if file_path.stat().st_size == 0:
                    logger.warning(
                        f"Файл {file_name} имеет нулевой размер, пропускаем"
                    )
                    await self.file_handler.cleanup_file(file_path)
                    continue
                files.append(file_path)
                file_names.append(file_name)
                await asyncio.sleep(0.5)

            if files:
                # Проверяем, является ли первое сообщение группы ответом
                reply_to = None
                first_message = messages[0]
                if first_message.reply_to_msg_id:
                    reply_to = self.db.get_dest_message_id(
                        first_message.reply_to_msg_id,
                        self.config.source_chat_id,
                    )
                    if not reply_to:
                        logger.debug(
                            f"Не найдено dest_message_id для reply_to_msg_id={first_message.reply_to_msg_id}"
                        )

                sent_messages = await self.file_handler.send_file_with_retry(
                    self.config.dest_chat_id,
                    files,
                    caption=caption,
                    album=True,
                    reply_to=reply_to,
                )
                sent_messages = (
                    sent_messages
                    if isinstance(sent_messages, list)
                    else [sent_messages]
                )

                for message, sent_message, file_name in zip(
                    messages, sent_messages, file_names
                ):
                    self.db.save_sync_state(
                        message.id,
                        self.config.source_chat_id,
                        sent_message.id,
                        file_name,
                    )
                    self.db.update_last_processed_id(
                        self.config.source_chat_id, message.id
                    )
                    logger.info(
                        f"Синхронизировано (группа): {file_name} (id: {message.id})"
                    )

        except Exception as e:
            logger.error(
                f"Ошибка при синхронизации медиагруппы {grouped_id}: {str(e)}"
            )
        finally:
            for file_path in files:
                await self.file_handler.cleanup_file(file_path)
            await self.file_handler.cleanup_temp_dir()
