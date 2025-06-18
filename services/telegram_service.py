import os
import logging
from telegram import Bot, InputMediaPhoto
from io import BytesIO
from typing import List, Dict
from PIL import Image

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=BOT_TOKEN)

# Создаем логгер для telegram_service
logger = logging.getLogger('telegram_service')
logger.setLevel(logging.DEBUG)

# Константы для сжатия изображений
MAX_FILE_SIZE_MB = 50  # максимальный размер файла для Telegram
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def validate_image_dimensions(image_bytes: bytes) -> tuple[bool, str]:
    """Проверяет размеры изображения на соответствие ограничениям Telegram"""
    try:
        bio = BytesIO(image_bytes)
        with Image.open(bio) as img:
            width, height = img.size
            
            # Ограничения Telegram
            max_resolution = 10000
            max_total_size = 10000
            
            if width > max_resolution or height > max_resolution:
                return False, f"Разрешение {width}x{height} превышает максимум {max_resolution}x{max_resolution}"
            
            if width + height > max_total_size:
                return False, f"Общий размер {width + height} превышает лимит {max_total_size}"
            
            return True, f"Размеры {width}x{height} корректны"
            
    except Exception as e:
        return False, f"Ошибка при проверке размеров: {e}"


def compress_image(image_bytes: bytes, max_size_mb: float = MAX_FILE_SIZE_MB) -> bytes:
    """
    Сжимает изображение до указанного размера в МБ
    
    Args:
        image_bytes: исходные байты изображения
        max_size_mb: максимальный размер в МБ
        
    Returns:
        bytes: сжатое изображение
    """
    try:
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # Если изображение уже меньше лимита, возвращаем как есть
        if len(image_bytes) <= max_size_bytes:
            logger.debug(f"📏 Изображение уже подходящего размера: {len(image_bytes) / 1024 / 1024:.2f} МБ")
            return image_bytes
        
        logger.info(f"🗜️ Начинаем сжатие изображения: {len(image_bytes) / 1024 / 1024:.2f} МБ -> {max_size_mb} МБ")
        
        bio = BytesIO(image_bytes)
        with Image.open(bio) as img:
            # Конвертируем в RGB если необходимо
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Сохраняем оригинальные размеры
            original_width, original_height = img.size
            
            # Начальное качество
            quality = 95
            
            while quality > 10:
                # Создаем копию изображения для сжатия
                temp_img = img.copy()
                
                # Если качество меньше 70, начинаем уменьшать разрешение
                if quality < 70:
                    scale_factor = quality / 70
                    new_width = int(original_width * scale_factor)
                    new_height = int(original_height * scale_factor)
                    temp_img = temp_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Сжимаем
                output = BytesIO()
                temp_img.save(output, format='JPEG', quality=quality, optimize=True)
                compressed_bytes = output.getvalue()
                
                current_size_mb = len(compressed_bytes) / 1024 / 1024
                logger.debug(f"   🎛️ Качество {quality}%, размер: {current_size_mb:.2f} МБ")
                
                # Если размер подходит, возвращаем результат
                if len(compressed_bytes) <= max_size_bytes:
                    logger.info(f"✅ Изображение сжато: {len(image_bytes) / 1024 / 1024:.2f} МБ -> {current_size_mb:.2f} МБ (качество {quality}%)")
                    return compressed_bytes
                
                # Уменьшаем качество
                quality -= 10
            
            # Если даже минимальное качество не помогло, возвращаем что есть
            logger.warning(f"⚠️ Не удалось сжать изображение до {max_size_mb} МБ, возвращаем с минимальным качеством")
            return compressed_bytes
            
    except Exception as e:
        logger.error(f"❌ Ошибка при сжатии изображения: {e}")
        return image_bytes


async def send_photo(image_bytes: bytes, caption: str = None):
    """Отправляет одиночное фото в канал"""
    logger.info(f"📤 Начинаем отправку фото, размер: {len(image_bytes) / 1024 / 1024:.2f} МБ")
    
    # Сжимаем изображение если необходимо
    compressed_bytes = compress_image(image_bytes)
    
    # Проверяем размеры изображения
    is_valid, validation_msg = validate_image_dimensions(compressed_bytes)
    logger.info(f"📏 {validation_msg}")
    
    if not is_valid:
        logger.error(f"❌ Изображение не прошло проверку: {validation_msg}")
        raise ValueError(f"Invalid image dimensions: {validation_msg}")
    
    bio = BytesIO(compressed_bytes)
    bio.name = "image.jpg"  # Изменили на jpg так как сжимаем в JPEG
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


async def send_animation(file_path: str, caption: str = None):
    """Отправляет GIF анимацию в канал"""
    logger.info(f"📤 Начинаем отправку анимации: {file_path}")

    try:
        file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
        logger.info(f"📊 Размер анимации: {file_size:.2f} МБ")

        with open(file_path, "rb") as f:
            message = await bot.send_animation(
                chat_id=CHANNEL_ID,
                animation=f,
                caption=caption[:1024] if caption else None,
                read_timeout=300,  # 5 минут на чтение
                write_timeout=300,  # 5 минут на отправку
                connect_timeout=60  # 1 минута на подключение
            )
        logger.info(f"✅ Анимация успешно отправлена (message_id: {message.message_id})")
        return message
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке анимации: {e}")
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
            # Сжимаем изображение если необходимо
            compressed_media = compress_image(item['media'])
            
            # Проверяем размеры изображения
            is_valid, validation_msg = validate_image_dimensions(compressed_media)
            logger.debug(f"   📏 Изображение #{i + 1}: {validation_msg}")
            
            if not is_valid:
                logger.warning(f"⚠️ Пропускаем изображение #{i + 1}: {validation_msg}")
                continue
            
            bio = BytesIO(compressed_media)
            bio.name = f"image_{i}.jpg"  # Изменили на jpg так как сжимаем в JPEG
            bio.seek(0)

            media_size = len(compressed_media) / 1024 / 1024
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