import os
import requests
import asyncio
import logging
import yaml
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# сначала подгружаем .env
load_dotenv()

from services.reddit_service import fetch_latest
from services.waifu_service import fetch_images_data
from services.sd_service import interrogate_deepbooru, interrogate_with_tagger
from services.lm_service import process_tags_with_lm
from services.telegram_service import send_photo, send_video
from services.db_service import init_db, is_reddit_processed, mark_reddit_processed, save_post_to_db

# читаем тайминги и subreddit
with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
SUBREDDIT = cfg["reddit"]["subreddit"]
INTERVAL_MIN = cfg["timings"]["time_scope"]
USE_TAGGER = cfg.get("use_tagger", False)
JSON_URL = os.getenv("JSON_URL")
LM_MODEL = os.getenv("LM_MODEL")


async def process_cycle():
    logging.info("=== Новый цикл обработки ===")

    # 1) Reddit
    logging.info("Проверяем Reddit...")
    post = fetch_latest(SUBREDDIT)
    if post and post.get("media_type"):
        logging.info(f"Найден пост: {post['post_id']}, тип: {post['media_type']}")
        if not await is_reddit_processed(post["post_id"]):
            logging.info(f"Пост новый, обрабатываем...")

            if post["media_type"] in ("video", "gif"):
                logging.info(f"Отправляем {post['media_type']} без обработки")
                await send_video(post["media_path"])
                await mark_reddit_processed(post["post_id"])
                logging.info(f"Видео/гиф отправлен и помечен как обработанный")
                return

            logging.info("Обрабатываем изображение...")
            img_bytes = open(post["media_path"], "rb").read()
            logging.info(f"Размер изображения: {len(img_bytes) / 1024 / 1024:.2f} МБ")

            # Получаем теги от AI
            logging.info("Запускаем анализ через AI...")
            if USE_TAGGER:
                tags, method = await interrogate_with_tagger(img_bytes)
            else:
                tags, method = [], ""
            if not tags:
                tags, method = await interrogate_deepbooru(img_bytes)

            logging.info(f"Получено {len(tags)} тегов через {method}")

            # Генерируем описание
            logging.info("Отправляем в LM Studio...")
            desc, desc_prompt = await process_tags_with_lm(tags)
            logging.info(f"Описание сгенерировано: {len(desc)} символов")

            caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in tags[:10])

            # Отправляем в Telegram
            logging.info("Отправляем в Telegram...")
            await send_photo(img_bytes, caption)

            # Сохраняем в БД
            logging.info("Сохраняем в БД...")
            await save_post_to_db(
                image_url=post["media_path"],
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
            logging.info("Reddit пост полностью обработан")
            return
        else:
            logging.info(f"Пост {post['post_id']} уже был обработан ранее, пропускаем")
    else:
        logging.info("Новых постов Reddit не найдено")

    # 2) fallback — waifu.fm
    logging.info("Переходим к waifu.fm...")
    waifus = fetch_images_data(JSON_URL)
    logging.info(f"Получено {len(waifus)} изображений от waifu.fm")

    for item in waifus:
        logging.info(f"Скачиваем изображение: {item['url']}")
        resp = requests.get(item["url"], timeout=15)
        resp.raise_for_status()
        img_bytes = resp.content
        logging.info(f"Размер изображения: {len(img_bytes) / 1024 / 1024:.2f} МБ")

        # Получаем теги от AI
        logging.info("Анализируем через AI...")
        if USE_TAGGER:
            tags_ai, method = await interrogate_with_tagger(img_bytes)
        else:
            tags_ai, method = [], ""
        if not tags_ai:
            tags_ai, method = await interrogate_deepbooru(img_bytes)

        logging.info(f"Получено {len(tags_ai)} тегов от AI через {method}")

        # ИСПРАВЛЕНИЕ: объединяем теги для LM Studio
        original_tags = item["tags"]
        all_tags = list(set(original_tags + tags_ai))
        logging.info(f"Всего тегов для LM Studio: {len(all_tags)} (оригинал: {len(original_tags)}, AI: {len(tags_ai)})")

        # Отправляем ВСЕ теги в LM Studio
        logging.info("Генерируем описание через LM Studio...")
        desc, desc_prompt = await process_tags_with_lm(all_tags)
        logging.info(f"Описание сгенерировано: {len(desc)} символов")

        # В подписи используем только оригинальные теги
        caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in original_tags[:10])

        logging.info("Отправляем в Telegram...")
        await send_photo(img_bytes, caption)

        logging.info("Сохраняем в БД...")
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
        logging.info("Waifu.fm изображение обработано")
        break  # Отправляем только одну картинку за цикл

    logging.info("=== Цикл обработки завершен ===\n")


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    # запустить первый цикл сразу
    await process_cycle()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(process_cycle, "interval", minutes=INTERVAL_MIN)
    scheduler.start()
    # вечно ждем
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())