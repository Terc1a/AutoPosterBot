import os
import requests
import asyncio
import logging
import yaml
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List, Set
import logging.handlers


# Настройка логирования с цветами и эмодзи
class ColoredFormatter(logging.Formatter):
    """Кастомный форматтер с цветами и эмодзи"""

    grey = "\x1b[38;21m"
    blue = "\x1b[34m"
    green = "\x1b[32m"
    yellow = "\x1b[33m"
    red = "\x1b[31m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: grey + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + reset,
        logging.INFO: green + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + reset,
        logging.WARNING: yellow + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + reset,
        logging.ERROR: red + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + reset,
        logging.CRITICAL: bold_red + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)


# Настройка корневого логгера
logging.basicConfig(level=logging.INFO)
root_logger = logging.getLogger()

# Удаляем старые хендлеры
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Создаем новый хендлер для консоли с цветным форматтером
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter())
root_logger.addHandler(console_handler)

# Создаем папку для логов если её нет
os.makedirs('logs', exist_ok=True)

# Добавляем файловый хендлер с ротацией
file_handler = logging.handlers.RotatingFileHandler(
    'logs/tgposter.log',
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
root_logger.addHandler(file_handler)

# Создаем логгер для orchestrator
logger = logging.getLogger('orchestrator')
logger.info("📝 Логирование настроено. Логи сохраняются в logs/tgposter.log")

# сначала подгружаем .env
load_dotenv()

from services.reddit_service import fetch_latest, fetch_latest_posts
from services.waifu_service import fetch_images_data
from services.sd_service import interrogate_deepbooru, interrogate_with_tagger
from services.lm_service import process_tags_with_lm
from services.telegram_service_pyrogram import send_photo, send_video, send_animation, send_media_group, check_channel_access
from services.db_service import init_db, is_reddit_processed, mark_reddit_processed, save_post_to_db, save_scheduled_post

# читаем тайминги и subreddit
with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

SUBREDDITS = cfg["reddit"]["subreddits"]
INTERVAL_MIN = cfg["timings"]["time_scope"]
USE_TAGGER = cfg.get("use_tagger", False)
JSON_URL = os.getenv("JSON_URL")
LM_MODEL = os.getenv("LM_MODEL")

# Теги, которые не нужно публиковать в Telegram
EXCLUDED_TAGS = {
    # Количественные теги
    '1boy', '2boys', '3boys', '4boys', '5boys', 'multiple_boys', 'male_focus',
    '1girl', '2girls', '3girls', '4girls', '5girls', 'multiple_girls', 'female_focus',
    'solo', 'solo_focus', 'duo', 'group',

    # Технические теги
    'highres', 'absurdres', 'lowres', 'traditional_media', 'scan', 'photo',
    'commentary', 'english_commentary', 'chinese_commentary', 'commentary_request',
    'artist_name', 'watermark', 'signature', 'dated', 'username', 'web_address',

    # ID теги
    'bad_id', 'bad_pixiv_id', 'bad_twitter_id', 'bad_tumblr_id',
    'pixiv_id', 'twitter_username', 'tumblr_username',

    # Фоны
    'simple_background', 'white_background', 'transparent_background',
    'gradient_background', 'grey_background', 'black_background',

    # Базовые описательные теги
    'black_hair', 'brown_hair', 'blonde_hair', 'blue_hair', 'red_hair',
    'green_hair', 'purple_hair', 'pink_hair', 'white_hair', 'grey_hair',
    'short_hair', 'long_hair', 'medium_hair', 'very_long_hair',

    # Цвета глаз
    'black_eyes', 'brown_eyes', 'blue_eyes', 'red_eyes', 'green_eyes',
    'purple_eyes', 'yellow_eyes', 'pink_eyes', 'grey_eyes',

    # Базовая одежда
    'shirt', 'black_shirt', 'white_shirt', 'blue_shirt', 'red_shirt',
    't-shirt', 'dress', 'skirt', 'pants', 'shorts', 'jacket',
    'clothes', 'clothing', 'uniform', 'school_uniform',

    # Общие теги
    'blush', 'smile', 'open_mouth', 'closed_mouth', 'teeth',
    'looking_at_viewer', 'looking_at_another', 'looking_away',
    'breasts', 'small_breasts', 'medium_breasts', 'large_breasts',
    'cleavage', 'collarbone', 'bare_shoulders', 'midriff',

    # Мета-теги
    'duplicate', 'image_sample', 'md5_mismatch', 'revision',
    'translated', 'hard_translated', 'partially_translated',
    'translation_request', 'english', 'japanese', 'chinese',

    # Прочие общие
    'hair', 'eyes', 'face', 'head', 'body', 'skin', 'lips',
    'standing', 'sitting', 'lying', 'kneeling', 'squatting',
    'indoors', 'outdoors', 'day', 'night', 'sky', 'cloud'
}


def calculate_publish_times(num_posts: int = 8) -> List[datetime]:
    """
    Рассчитывает времена публикации для постов.
    Первый пост - в следующий час, остальные через каждые 3 часа.
    
    Args:
        num_posts: количество постов для расчета времени
        
    Returns:
        List[datetime]: список времен публикации
    """
    now = datetime.now()
    
    # Первый пост в следующий час (округляем к следующему часу)
    first_post_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    
    publish_times = [first_post_time]
    
    # Остальные посты через каждые 3 часа
    for i in range(1, num_posts):
        next_time = first_post_time + timedelta(hours=3 * i)
        publish_times.append(next_time)
    
    return publish_times


def filter_tags(tags: List[str]) -> List[str]:
    """Фильтрует теги, исключая ненужные"""
    logger = logging.getLogger(__name__)
    logger.info(f"🔍 Фильтрация тегов: входные теги ({len(tags)}): {tags[:20]}")
    
    filtered = []
    for tag in tags:
        # Очищаем тег от лишних символов
        clean_tag = tag.strip()
        
        # Удаляем смайлики и специальные символы в начале тега
        clean_tag = clean_tag.lstrip('#:').strip()
        if not clean_tag or len(clean_tag) < 2:
            logger.debug(f"❌ Пропускаем слишком короткий тег: '{tag}'")
            continue
            
        # Нормализуем тег для проверки
        tag_normalized = clean_tag.lower().replace(' ', '_').replace('-', '_')

        # Минимальные исключения (только самые общие и бессмысленные)
        minimal_excluded = {
            'solo', '1girl', '2girls', 'multiple_girls', '1boy', '2boys', 'multiple_boys',
            'highres', 'absurdres', 'lowres', 'simple_background', 'white_background',
            'looking_at_viewer', 'standing', 'sitting', 'lying'
        }
        
        # Проверяем только минимальные исключения
        if tag_normalized not in minimal_excluded:
            # Пропускаем теги с числами в начале (1girl, 2boys и т.д.)
            if not (len(tag_normalized) > 1 and tag_normalized[0].isdigit()):
                filtered.append(clean_tag)
                logger.debug(f"✅ Принят тег: '{clean_tag}'")
            else:
                logger.debug(f"❌ Пропускаем тег с цифрой в начале: '{tag}'")
        else:
            logger.debug(f"❌ Пропускаем исключенный тег: '{tag}'")

    logger.info(f"✅ Результат фильтрации: {len(filtered)} тегов из {len(tags)}: {filtered[:10]}")
    return filtered[:10]  # Ограничиваем максимум 10 тегами


async def process_reddit_post(subreddit: str) -> bool:
    """
    Обрабатывает посты из указанного subreddit, пока один не будет успешно отправлен.
    Возвращает True если хотя бы один пост был обработан, False если не найдено новых постов.
    """
    return await process_reddit_posts(subreddit, max_posts=3)


async def process_reddit_posts(subreddit: str, max_posts: int = 3) -> bool:
    """
    Обрабатывает несколько постов из указанного subreddit, пока один не будет успешно отправлен.
    Возвращает True если хотя бы один пост был обработан, False если не найдено новых постов.
    """
    logger.info(f"🔍 Проверяем Reddit r/{subreddit}...")

    posts = fetch_latest_posts(subreddit, limit=max_posts)
    if not posts:
        logger.info(f"📭 Новых медиа-постов в r/{subreddit} не найдено")
        return False

    for idx, post in enumerate(posts):
        logger.info(f"📰 Пост #{idx + 1}/{len(posts)}: {post['post_id']}")
        logger.info(f"📋 Тип: {post['media_type']}, файлов: {len(post['media_paths'])}")

        if await is_reddit_processed(post["post_id"]):
            logger.info(f"⏭️ Пост {post['post_id']} уже был обработан ранее")
            continue

        # Пытаемся обработать пост
        try:
            success = await process_single_reddit_post(post)
            if success:
                logger.info(f"✅ Пост #{idx + 1} из Reddit r/{subreddit} обработан успешно")
                return True
            else:
                logger.warning(f"⚠️ Пост #{idx + 1} не удалось отправить, пробуем следующий...")
                continue
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке поста #{idx + 1}: {e}")
            continue

    logger.info(f"📭 Ни один пост из r/{subreddit} не удалось обработать")
    return False


async def process_single_post_for_scheduling(post: dict, scheduled_time: datetime) -> bool:
    """
    Обрабатывает один пост и отправляет его в отложку Telegram.
    Возвращает True если пост был успешно обработан и отправлен в отложку, False если возникла ошибка.
    """
    
    # Определяем источник поста
    is_waifu = 'waifu_data' in post
    source = 'waifu' if is_waifu else 'reddit'
    
    logger.info(f"🔄 Обрабатываем {source} пост для отложенной публикации: {post['post_id']}")
    logger.info(f"⏰ Время публикации: {scheduled_time}")

    # Обработка видео - отправляем с "Отправить позже"
    if post["media_type"] == "video":
        logger.info(f"🎥 Отправляем видео в отложку через USER API")
        try:
            await send_video(post["media_paths"][0], schedule_date=scheduled_time)
            logger.info("✅ Видео добавлено в отложку Telegram")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке видео в отложку: {e}")
            return False
    
    # Обработка GIF - отправляем с "Отправить позже"
    if post["media_type"] == "gif":
        logger.info(f"🎞️ Отправляем GIF в отложку через USER API")
        try:
            await send_animation(post["media_paths"][0], schedule_date=scheduled_time)
            logger.info("✅ GIF добавлен в отложку Telegram")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке GIF в отложку: {e}")
            return False

    # Обработка изображений (одиночных или галереи)
    logger.info(f"🖼️ Обрабатываем {'галерею' if post.get('is_gallery') else 'изображение'}...")

    try:
        # Получаем изображение для AI анализа
        if is_waifu:
            # Для waifu загружаем изображение по URL
            resp = requests.get(post["media_paths"][0], timeout=15)
            resp.raise_for_status()
            img_bytes = resp.content
            logger.info(f"📥 Загружено waifu изображение: {len(img_bytes) / 1024 / 1024:.2f} МБ")
        else:
            # Для Reddit используем первое изображение из галереи/поста
            first_image_path = post["media_paths"][0]
            logger.info(f"🔍 Читаем файл: {first_image_path}")
            
            # Проверяем существование файла
            if not os.path.exists(first_image_path):
                logger.error(f"❌ Файл не существует: {first_image_path}")
                return False
            
            with open(first_image_path, "rb") as f:
                img_bytes = f.read()
            logger.info(f"📊 Размер изображения: {len(img_bytes) / 1024 / 1024:.2f} МБ")
            
            # Дополнительная проверка размера
            if len(img_bytes) < 1024:  # Менее 1KB - подозрительно мало
                logger.error(f"❌ Изображение слишком маленькое ({len(img_bytes)} байт), возможно файл поврежден")
                # Покажем содержимое файла для диагностики
                logger.error(f"🔍 Первые 100 байт файла: {img_bytes[:100]}")
                return False
            
            # Проверим заголовок файла
            header = img_bytes[:10]
            logger.debug(f"🔍 Заголовок файла: {header.hex()}")
            
            # Проверяем на HTML (возможна ошибка скачивания)
            if img_bytes.startswith(b'<html') or img_bytes.startswith(b'<!DOCTYPE'):
                logger.error(f"❌ Файл содержит HTML вместо изображения, возможно ошибка при скачивании")
                logger.error(f"🔍 Начало файла: {img_bytes[:200].decode('utf-8', errors='ignore')}")
                return False

        # Получаем теги от AI
        logger.info("🔮 Запускаем анализ через AI...")
        if USE_TAGGER:
            tags, method = await interrogate_with_tagger(img_bytes)
        else:
            tags, method = [], ""

        if not tags:
            tags, method = await interrogate_deepbooru(img_bytes)

        # Если AI не дал тегов, используем фоллбэк теги
        if not tags:
            logger.warning("🚫 AI не дал тегов! Используем фоллбэк теги...")
            if is_waifu:
                tags = ["anime", "waifu", "girl", "art", "manga", "kawaii"]
            else:
                # Пытаемся извлечь теги из названия поста
                title = post.get("title", "").lower()
                # Определяем категорию по subreddit
                subreddit = post.get('subreddit', '').lower()
                
                if 'hentai' in subreddit:
                    fallback_tags = ["anime", "hentai", "girl", "manga", "art", "sexy"]
                elif 'ecchi' in subreddit:
                    fallback_tags = ["anime", "ecchi", "girl", "manga", "cute", "kawaii"]
                else:
                    fallback_tags = ["anime", "girl", "manga", "art"]
                
                # Добавляем теги на основе названия
                if "beach" in title or "pool" in title or "water" in title:
                    fallback_tags.extend(["beach", "water", "swimsuit"])
                if "bikini" in title:
                    fallback_tags.append("bikini")
                if "nude" in title or "naked" in title:
                    fallback_tags.append("nude")
                if "school" in title:
                    fallback_tags.append("schoolgirl")
                if "maid" in title:
                    fallback_tags.append("maid")
                    
                tags = list(set(fallback_tags))  # Убираем дубликаты
            method = "fallback"
            logger.info(f"🔄 Используем фоллбэк теги: {tags}")
        
        # Дополнительная проверка, что теги не потерялись
        if not tags:
            logger.error("❌ Теги полностью отсутствуют! Добавляем базовые теги...")
            tags = ["anime", "art", "picture"]

        logger.info(f"🏷️ Получено {len(tags)} тегов через {method}")
        logger.info(f"📝 Теги: {tags}")

        # Для waifu объединяем теги
        if is_waifu:
            original_tags = post['waifu_data']["tags"]
            all_tags = list(set(original_tags + tags))
            logger.info(f"📊 Всего тегов для LM Studio: {len(all_tags)}")
        else:
            all_tags = tags

        # Генерируем описание
        logger.info("💭 Генерируем описание через LM Studio...")
        desc, desc_prompt = await process_tags_with_lm(all_tags)
        logger.info(f"✍️ Описание сгенерировано: {len(desc)} символов")

        # Фильтруем теги для публикации (используем теги от AI, а не waifu)
        filtered_tags = filter_tags(tags)
        
        logger.info(f"🏷️ После фильтрации: {len(filtered_tags)} тегов из {len(tags)}")
        logger.info(f"🔍 Исходные AI теги: {tags[:10]}")
        logger.info(f"✅ Отфильтрованные теги: {filtered_tags}")

        # Создаем caption
        hashtags = [f"#{t.replace(' ', '_').replace('-', '_')}" for t in filtered_tags[:10] if t.strip()]
        logger.info(f"📝 Создано хештегов: {len(hashtags)}")
        logger.info(f"📝 Хештеги: {hashtags}")
        
        hashtag_string = " ".join(hashtags) if hashtags else ""
        caption = f"{desc}\n\n{hashtag_string}"
        
        logger.info(f"📄 Итоговый caption длиной {len(caption)} символов:")
        logger.info(f"📄 Caption: {caption[:200]}{'...' if len(caption) > 200 else ''}")

        # Отправляем через USER API с "Отправить позже"!
        logger.info("📤 Отправляем в отложку Telegram через USER API...")
        await send_photo(img_bytes, caption=caption, schedule_date=scheduled_time)

        # Сохраняем в обычную БД постов для истории
        logger.info("💾 Сохраняем в БД для истории...")
        await save_post_to_db(
            image_url=post["post_id"],
            image_data=img_bytes,
            description=desc,
            tags="|".join(tag.strip() for tag in all_tags if tag.strip()),
            published_at=scheduled_time.isoformat(),
            interrogate_model=method,
            interrogate_method=method,
            interrogate_prompt=f"{source}_interrogate",
            description_model=LM_MODEL,
            description_prompt=desc_prompt
        )

        logger.info("✅ Пост добавлен в отложку Telegram через USER API")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке поста для отложки: {e}")
        return False


async def process_single_reddit_post(post: dict) -> bool:
    """
    Обрабатывает один пост Reddit.
    Возвращает True если пост был успешно отправлен, False если возникла ошибка.
    """

    # Обработка видео - отправляем без анализа
    if post["media_type"] == "video":
        logger.info(f"🎥 Отправляем видео без AI-обработки")
        await send_video(post["media_paths"][0])
        await mark_reddit_processed(post["post_id"])
        logger.info("✅ Видео отправлено и помечено как обработанное")
        return True
    
    # Обработка GIF - отправляем как анимацию без анализа
    if post["media_type"] == "gif":
        logger.info(f"🎞️ Отправляем GIF как анимацию без AI-обработки")
        await send_animation(post["media_paths"][0])
        await mark_reddit_processed(post["post_id"])
        logger.info("✅ GIF отправлен как анимация и помечен как обработанный")
        return True

    # Обработка изображений (одиночных или галереи)
    logger.info(f"🖼️ Обрабатываем {'галерею' if post['is_gallery'] else 'изображение'}...")

    # Для AI анализа используем только первое изображение
    first_image_path = post["media_paths"][0]
    logger.info(f"🤖 Анализируем первое изображение через AI: {first_image_path}")

    img_bytes = open(first_image_path, "rb").read()
    logger.info(f"📊 Размер изображения: {len(img_bytes) / 1024 / 1024:.2f} МБ")

    # Получаем теги от AI
    logger.info("🔮 Запускаем анализ через AI...")
    if USE_TAGGER:
        tags, method = await interrogate_with_tagger(img_bytes)
    else:
        tags, method = [], ""

    if not tags:
        tags, method = await interrogate_deepbooru(img_bytes)

    logger.info(f"🏷️ Получено {len(tags)} тегов через {method}")
    if tags:
        logger.debug(f"📝 Примеры тегов: {tags[:5]}")

    # Генерируем описание
    logger.info("💭 Генерируем описание через LM Studio...")
    desc, desc_prompt = await process_tags_with_lm(tags)
    logger.info(f"✍️ Описание сгенерировано: {len(desc)} символов")

    # Фильтруем теги для публикации
    filtered_tags = filter_tags(tags)
    logger.info(f"🏷️ После фильтрации: {len(filtered_tags)} тегов из {len(tags)}")
    logger.debug(f"📝 Отфильтрованные теги: {filtered_tags}")

    # Убираем пустые теги и создаем хештеги
    hashtags = [f"#{t.replace(' ', '_').replace('-', '_')}" for t in filtered_tags[:10] if t.strip()]
    caption = f"{desc}\n\n" + " ".join(hashtags)

    # Отправляем в Telegram
    if post['is_gallery'] and len(post['media_paths']) > 1:
        logger.info(f"📤 Отправляем галерею из {len(post['media_paths'])} изображений...")

        # Подготавливаем все изображения для отправки группой
        media_items = []
        for i, path in enumerate(post['media_paths']):
            with open(path, 'rb') as f:
                media_bytes = f.read()
                # Добавляем подпись только к первому изображению
                media_items.append({
                    'media': media_bytes,
                    'caption': caption if i == 0 else None
                })

        try:
            await send_media_group(media_items)
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке галереи: {e}")
            logger.info("🔄 Галерея не может быть отправлена, пропускаем этот пост")
            return False

        # Сохраняем каждое изображение в БД
        for i, path in enumerate(post['media_paths']):
            with open(path, 'rb') as f:
                img_data = f.read()

            logger.info(f"💾 Сохраняем изображение #{i + 1} в БД...")
            await save_post_to_db(
                image_url=f"{post['post_id']}_image_{i}",
                image_data=img_data,
                description=desc if i == 0 else f"Изображение {i + 1} из галереи",
                tags="|".join(tag.strip() for tag in tags if tag.strip()),
                published_at=datetime.now().isoformat(),
                interrogate_model=method if i == 0 else "gallery_item",
                interrogate_method=method if i == 0 else "gallery_item",
                interrogate_prompt="reddit_gallery_interrogate",
                description_model=LM_MODEL if i == 0 else "gallery_item",
                description_prompt=desc_prompt if i == 0 else "gallery_item"
            )
    else:
        # Одиночное изображение
        logger.info("📤 Отправляем одиночное изображение...")
        try:
            await send_photo(img_bytes, caption)
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке изображения: {e}")
            logger.info("🔄 Изображение не может быть отправлено, пропускаем этот пост")
            return False

        # Сохраняем в БД
        logger.info("💾 Сохраняем в БД...")
        await save_post_to_db(
            image_url=post["post_id"],
            image_data=img_bytes,
            description=desc,
            tags="|".join(tag.strip() for tag in tags if tag.strip()),
            published_at=datetime.now().isoformat(),
            interrogate_model=method,
            interrogate_method=method,
            interrogate_prompt="reddit_interrogate",
            description_model=LM_MODEL,
            description_prompt=desc_prompt
        )

    await mark_reddit_processed(post["post_id"])
    logger.info("✅ Reddit пост полностью обработан")
    return True


async def schedule_batch_posts():
    """Новый цикл обработки - создает 8 отложенных постов"""
    logger.info("=" * 60)
    logger.info("🚀 НАЧАЛО СОЗДАНИЯ ОТЛОЖЕННЫХ ПОСТОВ")
    logger.info("=" * 60)

    start_time = datetime.now()
    
    # Рассчитываем времена публикации для 8 постов
    publish_times = calculate_publish_times(8)
    logger.info(f"⏰ Рассчитанные времена публикации:")
    for i, time in enumerate(publish_times):
        logger.info(f"   Пост #{i + 1}: {time.strftime('%Y-%m-%d %H:%M')}")

    processed_posts = 0
    target_posts = 8

    # Проходим по всем subreddit в порядке приоритета
    for idx, subreddit in enumerate(SUBREDDITS):
        if processed_posts >= target_posts:
            break
            
        logger.info(f"🔍 Обрабатываем subreddit #{idx + 1}/{len(SUBREDDITS)}: r/{subreddit}")
        
        # Получаем больше постов чем нужно, на случай дубликатов или ошибок
        posts = fetch_latest_posts(subreddit, limit=15)
        if not posts:
            logger.info(f"📭 Новых медиа-постов в r/{subreddit} не найдено")
            continue

        # Обрабатываем посты последовательно
        for post_idx, post in enumerate(posts):
            if processed_posts >= target_posts:
                break
                
            logger.info(f"📰 Обрабатываем пост #{post_idx + 1}: {post['post_id']}")
            
            if await is_reddit_processed(post["post_id"]):
                logger.info(f"⏭️ Пост {post['post_id']} уже был обработан ранее")
                continue

            try:
                # Обрабатываем пост для отложенной публикации
                success = await process_single_post_for_scheduling(post, publish_times[processed_posts])
                if success:
                    await mark_reddit_processed(post["post_id"])
                    processed_posts += 1
                    logger.info(f"✅ Пост #{processed_posts} запланирован на {publish_times[processed_posts-1].strftime('%H:%M %d.%m')}")
                else:
                    logger.warning(f"⚠️ Пост {post['post_id']} не удалось обработать, пропускаем...")
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при обработке поста {post['post_id']}: {e}")
                continue

        logger.info(f"📊 Из r/{subreddit} обработано {processed_posts} постов")

    # Если не хватает постов из Reddit, пробуем waifu.fm
    if processed_posts < target_posts:
        logger.info(f"📭 Недостаточно постов из Reddit ({processed_posts}/{target_posts})")
        logger.info("🔄 Пробуем получить недостающие посты от waifu.fm...")
        
        try:
            waifus = fetch_images_data(JSON_URL)
            logger.info(f"📊 Получено {len(waifus)} изображений от waifu.fm")

            for idx, item in enumerate(waifus):
                if processed_posts >= target_posts:
                    break
                    
                try:
                    logger.info(f"📥 Обрабатываем waifu изображение #{idx + 1}")
                    
                    # Создаем псевдо-пост для waifu
                    waifu_post = {
                        'post_id': f"waifu_{idx}_{int(datetime.now().timestamp())}",
                        'title': f"Waifu #{idx + 1}",
                        'media_type': 'image',
                        'media_paths': [item['url']],  # URL вместо локального пути
                        'is_gallery': False,
                        'waifu_data': item  # Сохраняем оригинальные данные
                    }
                    
                    scheduled_post_data = await process_single_post_for_scheduling(waifu_post, publish_times[processed_posts])
                    if scheduled_post_data:
                        processed_posts += 1
                        logger.info(f"✅ Waifu пост #{processed_posts} запланирован на {publish_times[processed_posts-1].strftime('%H:%M %d.%m')}")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка при обработке waifu изображения #{idx + 1}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке waifu.fm: {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"⏱️ Время создания {processed_posts} отложенных постов: {elapsed:.1f} сек")
    logger.info(f"📈 Статистика: {processed_posts}/{target_posts} постов запланировано")
    logger.info("=" * 60 + "\n")


async def process_cycle():
    """Основной цикл обработки - теперь только создает отложенные посты"""
    await schedule_batch_posts()



async def main():
    """Главная функция"""
    logger.info("🚀 Запуск системы создания отложенных постов TgPoster")
    logger.info(f"📋 Конфигурация:")
    logger.info(f"   - Subreddits ({len(SUBREDDITS)}): {', '.join(f'r/{s}' for s in SUBREDDITS)}")
    logger.info(f"   - Tagger: {'включен' if USE_TAGGER else 'выключен'}")
    logger.info(f"   - LM Model: {LM_MODEL}")

    # Инициализация БД
    logger.info("🗄️ Инициализация базы данных...")
    await init_db()

    # Проверяем доступ к каналу
    logger.info("📡 Проверяем подключение к Telegram...")
    if not await check_channel_access():
        logger.error("❌ Нет доступа к каналу! Проверьте, что бот добавлен в канал как администратор")
        return

    # Запуск создания отложенных постов
    logger.info("▶️ Запуск создания отложенных постов...")
    await process_cycle()

    logger.info("✅ Создание отложенных постов завершено!")
    logger.info("💡 Посты добавлены в отложку Telegram и будут автоматически опубликованы по расписанию")


if __name__ == "__main__":
    asyncio.run(main())