import os
import logging
from telegram import Bot, InputMediaPhoto
from io import BytesIO
from typing import List, Dict

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=BOT_TOKEN)

# Создаем логгер для telegram_service
logger = logging.getLogger('telegram_service')
logger.setLevel(logging.DEBUG)


async def send_photo(image_bytes: bytes, caption: str = None):
    """Отправляет одиночное фото в канал"""
    logger.info(f"📤 Начинаем отправку фото, размер: {len(image_bytes) / 1024 / 1024:.2f} МБ")
    bio = BytesIO(image_bytes)
    bio.name = "image.png"
    bio.seek(0)

    try:
        message = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=bio,
            caption=caption[:1024] if caption else None,
            read_timeout=120,
            write_timeout=120,
            connect_timeout=60
        )
        logger.info(f"✅ Фото успешно отправлено (message_id: {message.message_id})")
        return message
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке фото: {e}")
        raise


async def send_video(file_path: str):
    """Отправляет видео в канал"""
    logger.info(f"📤 Начинаем отправку видео: {file_path}")

    try:
        file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
        logger.info(f"📊 Размер видео: {file_size:.2f} МБ")

        with open(file_path, "rb") as f:
            message = await bot.send_video(
                chat_id=CHANNEL_ID,
                video=f,
                read_timeout=300,  # 5 минут на чтение
                write_timeout=300,  # 5 минут на отправку
                connect_timeout=60  # 1 минута на подключение
            )
        logger.info(f"✅ Видео успешно отправлено (message_id: {message.message_id})")
        return message
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке видео: {e}")
        raise


async def send_media_group(media_items: List[Dict]):
    """
    Отправляет группу медиа-файлов (альбом) в канал

    Args:
        media_items: Список словарей с ключами:
            - 'media': bytes - содержимое файла
            - 'caption': str - подпись (только для первого элемента)
    """
    logger.info(f"📤 Начинаем отправку медиа-группы из {len(media_items)} элементов")

    try:
        # Подготавливаем медиа для отправки
        media_group = []

        for i, item in enumerate(media_items):
            bio = BytesIO(item['media'])
            bio.name = f"image_{i}.png"
            bio.seek(0)

            media_size = len(item['media']) / 1024 / 1024
            logger.debug(f"   📸 Изображение #{i + 1}: {media_size:.2f} МБ")

            # Добавляем подпись только к первому элементу
            if i == 0 and item.get('caption'):
                media = InputMediaPhoto(
                    media=bio,
                    caption=item['caption'][:1024]  # Ограничение Telegram
                )
            else:
                media = InputMediaPhoto(media=bio)

            media_group.append(media)

        # Отправляем группу
        messages = await bot.send_media_group(
            chat_id=CHANNEL_ID,
            media=media_group,
            read_timeout=300,
            write_timeout=300,
            connect_timeout=60
        )

        logger.info(f"✅ Медиа-группа успешно отправлена. Сообщений: {len(messages)}")
        logger.debug(f"   Message IDs: {[m.message_id for m in messages]}")

        return messages

    except Exception as e:
        logger.error(f"❌ Ошибка при отправке медиа-группы: {e}")
        raise