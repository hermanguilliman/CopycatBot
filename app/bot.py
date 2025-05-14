import asyncio
from pathlib import Path

from loguru import logger
from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.tl.types import Document, MessageMediaPhoto

from app.config import load_config, setup_logger
from app.database import Database

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
            if message.id <= last_processed_id:
                continue

            if message.media and not self.db.is_message_synced(message.id):
                messages_to_process.append(message)
                if message.grouped_id:
                    grouped_messages.add(message.id)

        messages_to_process.sort(key=lambda x: x.id)

        processed_groups = set()
        for message in messages_to_process:
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
                    await self._process_media_group(
                        media_group,
                        media_group[0].text or "",
                        message.grouped_id,
                    )
                    processed_groups.add(message.grouped_id)
            elif message.id not in grouped_messages:
                logger.info(
                    f"Обработка одиночного медиа с msg_id: {message.id}"
                )
                await self._process_single_media(message)

    async def monitor_new_files(self):
        processed_groups = set()

        @self.client.on(events.NewMessage(chats=self.config.source_chat_id))
        async def handler(event):
            message = event.message
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
                    await self._process_media_group(
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
                logger.info(
                    f"Обработка одиночного медиа с msg_id: {message.id}"
                )
                await self._process_single_media(message)

    def _get_file_name(self, message):
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

    async def _process_single_media(self, message):
        """Обработка одиночного медиа"""
        try:
            file_name = self._get_file_name(message)
            file_path = await self._download_media_with_retry(
                message, file_name
            )
            if not file_path:
                logger.warning(
                    f"Не удалось скачать медиа для сообщения {message.id}"
                )
                return

            sent_message = await self._send_file_with_retry(
                self.config.dest_chat_id, file_path, caption=message.text or ""
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

            logger.info(
                f"Синхронизировано: {file_name} (msg_id: {message.id})"
            )

            await self._cleanup_file(file_path)

        except Exception as e:
            logger.error(f"Ошибка при обработке медиа {message.id}: {str(e)}")

    async def _process_media_group(self, messages, caption, grouped_id):
        """Обработка медиагруппы"""
        files = []
        file_names = []
        try:
            for message in messages:
                file_name = self._get_file_name(message)
                file_path = await self._download_media_with_retry(
                    message, file_name
                )
                if not file_path:
                    logger.warning(
                        f"Не удалось скачать медиа для сообщения {message.id}"
                    )
                    continue
                # Проверка размера файла
                if Path(file_path).stat().st_size == 0:
                    logger.warning(
                        f"Файл {file_name} имеет нулевой размер, пропускаем"
                    )
                    await self._cleanup_file(file_path)
                    continue
                files.append(file_path)
                file_names.append(file_name)
                await asyncio.sleep(0.5)

            if files:
                sent_messages = await self._send_file_with_retry(
                    self.config.dest_chat_id,
                    files,
                    caption=caption,
                    album=True,
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
                        f"Синхронизировано (группа): {file_name} (msg_id: {message.id})"
                    )

        except Exception as e:
            logger.error(
                f"Ошибка при синхронизации медиагруппы {grouped_id}: {str(e)}"
            )
        finally:
            for file_path in files:
                await self._cleanup_file(file_path)
            await self._cleanup_temp_dir()

    async def _download_media_with_retry(
        self, message, file_name, retries=3, delay=2
    ):
        """Скачивание медиа с повторными попытками"""
        for attempt in range(retries):
            try:
                file_path = await message.download_media(
                    file=self.temp_dir / file_name
                )
                if file_path and Path(file_path).exists():
                    return file_path
                logger.warning(
                    f"Попытка {attempt + 1}: Не удалось скачать {file_name}"
                )
            except RPCError as e:
                logger.warning(
                    f"Попытка {attempt + 1}: Ошибка скачивания {file_name}: {str(e)}"
                )
            await asyncio.sleep(delay)
        return None

    async def _send_file_with_retry(
        self, chat_id, file, caption="", album=False, retries=3, delay=2
    ):
        """Отправка файла с повторными попытками"""
        for attempt in range(retries):
            try:
                if isinstance(file, list):
                    for f in file:
                        if not Path(f).exists():
                            raise FileNotFoundError(f"Файл {f} не существует")
                else:
                    if not Path(file).exists():
                        raise FileNotFoundError(f"Файл {file} не существует")
                return await self.client.send_file(
                    chat_id, file, caption=caption, album=album
                )
            except (RPCError, FileNotFoundError) as e:
                logger.warning(
                    f"Попытка {attempt + 1}: Ошибка отправки: {str(e)}"
                )
                if attempt == retries - 1:
                    raise
            await asyncio.sleep(delay)
        raise Exception("Не удалось отправить файл после всех попыток")

    async def _cleanup_file(self, file_path):
        """Безопасное удаление файла с логированием"""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info(f"Удален временный файл: {file_path}")
            else:
                logger.warning(f"Файл не найден для удаления: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")

    async def _cleanup_temp_dir(self):
        """Очистка всех временных файлов в папке data/"""
        try:
            for file_path in self.temp_dir.glob("*"):
                await self._cleanup_file(file_path)
        except Exception as e:
            logger.error(f"Ошибка при очистке папки data/: {str(e)}")

    async def run(self):
        await self.client.start()
        logger.info("Бот запущен")

        await self.sync_existing_files()
        await self.monitor_new_files()

        await self.client.run_until_disconnected()
