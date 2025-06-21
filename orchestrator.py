import os
import requests
import asyncio
import logging
import yaml
from datetime import datetime
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
from services.telegram_service import send_photo, send_video, send_animation, send_media_group
from services.db_service import init_db, is_reddit_processed, mark_reddit_processed, save_post_to_db

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


def filter_tags(tags: List[str]) -> List[str]:
    """Фильтрует теги, исключая ненужные"""
    filtered = []
    for tag in tags:
        # Нормализуем тег для проверки
        tag_normalized = tag.lower().replace(' ', '_').replace('-', '_')

        # Проверяем точное совпадение
        if tag_normalized not in EXCLUDED_TAGS:
            # Дополнительная проверка на паттерны
            skip = False

            # Пропускаем теги с числами в начале (1girl, 2boys и т.д.)
            if tag_normalized[0].isdigit():
                skip = True

            # Пропускаем базовые цвета + объект (black_hair, blue_eyes и т.д.)
            color_patterns = ['black_', 'white_', 'red_', 'blue_', 'green_', 'brown_', 'grey_', 'pink_', 'purple_',
                              'yellow_']
            for color in color_patterns:
                if tag_normalized.startswith(color) and tag_normalized.endswith(
                        ('_hair', '_eyes', '_shirt', '_dress', '_skirt')):
                    skip = True
                    break

            if not skip:
                filtered.append(tag)

    # Возвращаем только действительно значимые теги
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

    caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in filtered_tags[:10])

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
                tags=",".join(tags),
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
            tags=",".join(tags),
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


async def process_cycle():
    """Основной цикл обработки"""
    logger.info("=" * 60)
    logger.info("🚀 НАЧАЛО НОВОГО ЦИКЛА ОБРАБОТКИ")
    logger.info("=" * 60)

    start_time = datetime.now()

    # Проходим по всем subreddit в порядке приоритета
    for idx, subreddit in enumerate(SUBREDDITS):
        logger.info(f"🔍 Проверяем subreddit #{idx + 1}/{len(SUBREDDITS)}: r/{subreddit}")
        
        if await process_reddit_post(subreddit):
            logger.info(f"✅ Пост из r/{subreddit} обработан успешно")
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"⏱️ Время выполнения цикла: {elapsed:.1f} сек")
            logger.info("=" * 60 + "\n")
            return
        
        logger.info(f"⚠️ Подходящих постов в r/{subreddit} не найдено, переходим к следующему...")

    # Если ни один subreddit не дал результата, переходим к waifu.fm
    logger.info(f"📭 Ни один из {len(SUBREDDITS)} subreddit не дал подходящих постов")
    logger.info("🔄 Переходим к fallback источнику - waifu.fm...")

    try:
        waifus = fetch_images_data(JSON_URL)
        logger.info(f"📊 Получено {len(waifus)} изображений от waifu.fm")

        if not waifus:
            logger.warning("⚠️ Waifu.fm не вернул изображений")
            return

        # Пробуем обработать изображения по очереди, пока одно не получится отправить
        processed_successfully = False
        
        for idx, item in enumerate(waifus):
            try:
                logger.info(f"📥 Скачиваем изображение #{idx + 1}: {item['url'][:50]}...")

                resp = requests.get(item["url"], timeout=15)
                resp.raise_for_status()
                img_bytes = resp.content
                logger.info(f"📊 Размер изображения: {len(img_bytes) / 1024 / 1024:.2f} МБ")

                # Получаем теги от AI
                logger.info("🔮 Анализируем через AI...")
                if USE_TAGGER:
                    tags_ai, method = await interrogate_with_tagger(img_bytes)
                else:
                    tags_ai, method = [], ""

                if not tags_ai:
                    tags_ai, method = await interrogate_deepbooru(img_bytes)

                logger.info(f"🏷️ Получено {len(tags_ai)} тегов от AI через {method}")

                # Объединяем теги для LM Studio
                original_tags = item["tags"]
                all_tags = list(set(original_tags + tags_ai))
                logger.info(f"📊 Всего тегов для LM Studio: {len(all_tags)}")
                logger.debug(f"   - Оригинальных: {len(original_tags)}")
                logger.debug(f"   - От AI: {len(tags_ai)}")

                # Генерируем описание
                logger.info("💭 Генерируем описание через LM Studio...")
                desc, desc_prompt = await process_tags_with_lm(all_tags)
                logger.info(f"✍️ Описание сгенерировано: {len(desc)} символов")

                # В подписи используем только отфильтрованные оригинальные теги
                filtered_tags = filter_tags(original_tags)
                caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in filtered_tags[:10])

                logger.info("📤 Отправляем в Telegram...")
                try:
                    await send_photo(img_bytes, caption)
                    
                    logger.info("💾 Сохраняем в БД...")
                    await save_post_to_db(
                        image_url=item["url"],
                        image_data=img_bytes,
                        description=desc,
                        tags=",".join(all_tags),
                        published_at=datetime.now().isoformat(),
                        interrogate_model=method,
                        interrogate_method=method,
                        interrogate_prompt="waifu_interrogate",
                        description_model=LM_MODEL,
                        description_prompt=desc_prompt
                    )

                    logger.info("✅ Waifu.fm изображение обработано")
                    processed_successfully = True
                    break
                    
                except Exception as send_error:
                    logger.error(f"❌ Ошибка при отправке изображения #{idx + 1}: {send_error}")
                    if idx < len(waifus) - 1:
                        logger.info(f"🔄 Пробуем следующее изображение ({idx + 2}/{len(waifus)})...")
                        continue
                    else:
                        logger.error("❌ Все изображения от waifu.fm не удалось отправить")
                        break
                        
            except Exception as process_error:
                logger.error(f"❌ Ошибка при обработке изображения #{idx + 1}: {process_error}")
                if idx < len(waifus) - 1:
                    logger.info(f"🔄 Пробуем следующее изображение ({idx + 2}/{len(waifus)})...")
                    continue
                else:
                    logger.error("❌ Все изображения от waifu.fm не удалось обработать")
                    break
        
        if not processed_successfully:
            logger.warning("⚠️ Ни одно изображение из waifu.fm не удалось обработать и отправить")

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке waifu.fm: {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"⏱️ Время выполнения цикла: {elapsed:.1f} сек")
    logger.info("=" * 60 + "\n")


async def main():
    """Главная функция"""
    logger.info("🚀 Запуск бота TgPoster")
    logger.info(f"📋 Конфигурация:")
    logger.info(f"   - Subreddits ({len(SUBREDDITS)}): {', '.join(f'r/{s}' for s in SUBREDDITS)}")
    logger.info(f"   - Интервал: {INTERVAL_MIN} минут")
    logger.info(f"   - Tagger: {'включен' if USE_TAGGER else 'выключен'}")
    logger.info(f"   - LM Model: {LM_MODEL}")

    # Инициализация БД
    logger.info("🗄️ Инициализация базы данных...")
    await init_db()

    # Запуск первого цикла
    logger.info("▶️ Запуск первого цикла обработки...")
    await process_cycle()

    # Настройка планировщика
    logger.info(f"⏰ Настройка планировщика (интервал: {INTERVAL_MIN} мин)...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(process_cycle, "interval", minutes=INTERVAL_MIN)
    scheduler.start()

    logger.info("✅ Бот запущен и работает!")
    logger.info("🔄 Ожидание следующего цикла...\n")

    # Вечное ожидание
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())