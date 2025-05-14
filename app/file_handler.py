import asyncio
from pathlib import Path

from loguru import logger
from telethon.errors import RPCError


class FileHandler:
    def __init__(self, client, temp_dir):
        self.client = client
        self.temp_dir = temp_dir

    async def download_media_with_retry(
        self, message, file_name, retries=3, delay=2
    ):
        """Скачивание медиа с повторными попытками"""
        for attempt in range(retries):
            try:
                file_path = await message.download_media(
                    file=self.temp_dir / file_name
                )
                if file_path and Path(file_path).exists():
                    return Path(file_path)
                logger.warning(
                    f"Попытка {attempt + 1}: Не удалось скачать {file_name}"
                )
            except RPCError as e:
                logger.warning(
                    f"Попытка {attempt + 1}: Ошибка скачивания {file_name}: {str(e)}"
                )
            await asyncio.sleep(delay)
        return None

    async def send_file_with_retry(
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

    async def cleanup_file(self, file_path):
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

    async def cleanup_temp_dir(self):
        """Очистка всех временных файлов в папке data/"""
        try:
            for file_path in self.temp_dir.glob("*"):
                await self.cleanup_file(file_path)
        except Exception as e:
            logger.error(f"Ошибка при очистке папки data/: {str(e)}")
