import os
import logging
from telegram import Bot
from io import BytesIO

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=BOT_TOKEN)


async def send_photo(image_bytes: bytes, caption: str = None):
    logging.info(f"Начинаем отправку фото, размер: {len(image_bytes) / 1024 / 1024:.2f} МБ")
    bio = BytesIO(image_bytes)
    bio.name = "image.png"
    bio.seek(0)

    try:
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=bio,
            caption=caption[:1024] if caption else None,
            read_timeout=120,
            write_timeout=120,
            connect_timeout=60
        )
        logging.info("Фото успешно отправлено")
    except Exception as e:
        logging.error(f"Ошибка при отправке фото: {e}")
        raise


async def send_video(file_path: str):
    try:
        with open(file_path, "rb") as f:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=f,
                read_timeout=300,  # 5 минут на чтение
                write_timeout=300,  # 5 минут на отправку
                connect_timeout=60  # 1 минута на подключение
            )
        logging.info(f"Видео {file_path} успешно отправлено")
    except Exception as e:
        logging.error(f"Ошибка при отправке видео: {e}")
        raise