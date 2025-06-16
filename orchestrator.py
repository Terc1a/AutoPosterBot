import os
import requests
import asyncio
import logging
import yaml
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List, Set


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

# Создаем новый хендлер с цветным форматтером
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter())
root_logger.addHandler(console_handler)

# Создаем логгер для orchestrator
logger = logging.getLogger('orchestrator')

# сначала подгружаем .env
load_dotenv()

from services.reddit_service import fetch_latest
from services.waifu_service import fetch_images_data
from services.sd_service import interrogate_deepbooru, interrogate_with_tagger
from services.lm_service import process_tags_with_lm
from services.telegram_service import send_photo, send_video, send_media_group
from services.db_service import init_db, is_reddit_processed, mark_reddit_processed, save_post_to_db

# читаем тайминги и subreddit
with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

SUBREDDIT = cfg["reddit"]["subreddit"]
SUBREDDIT2 = cfg["reddit"].get("subreddit2", "")
INTERVAL_MIN = cfg["timings"]["time_scope"]
USE_TAGGER = cfg.get("use_tagger", False)
JSON_URL = os.getenv("JSON_URL")
LM_MODEL = os.getenv("LM_MODEL")

# Теги, которые не нужно публиковать в Telegram
EXCLUDED_TAGS = {
    '1boy', '2boys', '3boys', '4boys', '5boys', 'multiple_boys',
    '1girl', '2girls', '3girls', '4girls', '5girls', 'multiple_girls',
    'solo', 'solo_focus', 'highres', 'absurdres', 'commentary',
    'english_commentary', 'artist_name', 'watermark', 'signature',
    'dated', 'bad_id', 'bad_pixiv_id', 'bad_twitter_id',
    'duplicate', 'image_sample', 'md5_mismatch', 'simple_background',
    'white_background', 'transparent_background'
}


def filter_tags(tags: List[str]) -> List[str]:
    """Фильтрует теги, исключая ненужные"""
    filtered = []
    for tag in tags:
        tag_lower = tag.lower().replace(' ', '_')
        if tag_lower not in EXCLUDED_TAGS:
            filtered.append(tag)
    return filtered


async def process_reddit_post(subreddit: str) -> bool:
    """
    Обрабатывает пост из указанного subreddit.
    Возвращает True если пост был обработан, False если не найден новый пост.
    """
    logger.info(f"🔍 Проверяем Reddit r/{subreddit}...")

    post = fetch_latest(subreddit)
    if not post or not post.get("media_type"):
        logger.info(f"📭 Новых медиа-постов в r/{subreddit} не найдено")
        return False

    logger.info(f"📰 Найден пост: {post['post_id']}")
    logger.info(f"📋 Тип: {post['media_type']}, файлов: {len(post['media_paths'])}")

    if await is_reddit_processed(post["post_id"]):
        logger.info(f"⏭️ Пост {post['post_id']} уже был обработан ранее")
        return False

    # Обработка видео/гиф - отправляем без анализа
    if post["media_type"] in ("video", "gif"):
        logger.info(f"🎥 Отправляем {post['media_type']} без AI-обработки")
        await send_video(post["media_paths"][0])
        await mark_reddit_processed(post["post_id"])
        logger.info(f"✅ {post['media_type'].capitalize()} отправлен и помечен как обработанный")
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

        await send_media_group(media_items)

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
        await send_photo(img_bytes, caption)

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

    # Сначала проверяем основной subreddit
    if await process_reddit_post(SUBREDDIT):
        logger.info("✅ Пост из основного subreddit обработан успешно")
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"⏱️ Время выполнения цикла: {elapsed:.1f} сек")
        logger.info("=" * 60 + "\n")
        return

    # Если в основном не нашли, проверяем второй subreddit
    if SUBREDDIT2:
        logger.info(f"🔄 Проверяем запасной subreddit r/{SUBREDDIT2}...")
        if await process_reddit_post(SUBREDDIT2):
            logger.info("✅ Пост из запасного subreddit обработан успешно")
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"⏱️ Время выполнения цикла: {elapsed:.1f} сек")
            logger.info("=" * 60 + "\n")
            return

    # Fallback на waifu.fm
    logger.info("🔄 Переходим к fallback источнику - waifu.fm...")

    try:
        waifus = fetch_images_data(JSON_URL)
        logger.info(f"📊 Получено {len(waifus)} изображений от waifu.fm")

        if not waifus:
            logger.warning("⚠️ Waifu.fm не вернул изображений")
            return

        # Обрабатываем первое изображение
        item = waifus[0]
        logger.info(f"📥 Скачиваем изображение: {item['url'][:50]}...")

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

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке waifu.fm: {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"⏱️ Время выполнения цикла: {elapsed:.1f} сек")
    logger.info("=" * 60 + "\n")


async def main():
    """Главная функция"""
    logger.info("🚀 Запуск бота TgPoster")
    logger.info(f"📋 Конфигурация:")
    logger.info(f"   - Основной subreddit: r/{SUBREDDIT}")
    logger.info(f"   - Запасной subreddit: r/{SUBREDDIT2}" if SUBREDDIT2 else "   - Запасной subreddit: не указан")
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