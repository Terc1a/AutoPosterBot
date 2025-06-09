#!/usr/bin/env python3
# bot_async_json_with_tags.py

import os
import asyncio
import logging
from io import BytesIO
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 1) Загрузка настроек из .env
load_dotenv()
BOT_TOKEN  = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
JSON_URL   = os.getenv("JSON_URL")

if not BOT_TOKEN or not CHANNEL_ID or not JSON_URL:
    raise RuntimeError("Укажите в .env BOT_TOKEN, CHANNEL_ID и JSON_URL")

bot = Bot(token=BOT_TOKEN)

# 2) Теперь функция возвращает список словарей с URL и списком тегов
def fetch_images_data(api_url: str) -> list[dict]:
    resp = requests.get(api_url)
    resp.raise_for_status()
    data = resp.json()
    images = data.get("images", [])
    result = []
    for img in images:
        url = img.get("url")
        if not url:
            continue
        # достаём все имена тегов
        tags = [t.get("name") for t in img.get("tags", []) if t.get("name")]
        result.append({
            "url": url,
            "tags": tags
        })
    return result

# 3) Асинхронная задача отправки картинок с подписями
async def post_images_async():
    try:
        images = fetch_images_data(JSON_URL)
        for item in images:
            img_url = item["url"]
            tags = item["tags"]
            if tags:
                hashtags = [f"#{t.replace(' ', '_')}" for t in tags]
                caption = " ".join(hashtags)
            else:
                caption = None

            # скачиваем картинку
            resp = requests.get(img_url)
            resp.raise_for_status()
            bio = BytesIO(resp.content)
            # имя файла — последний сегмент URL
            bio.name = os.path.basename(urlparse(img_url).path)
            bio.seek(0)

            # шлём картинку с подписью
            await bot.send_photo(chat_id=CHANNEL_ID, photo=bio, caption=caption)

        logging.info("Успешно отправили все картинки с тегами.")
    except Exception as e:
        logging.error("Ошибка при отправке изображений: %s", e)

# 4) Главная функция: запускаем сразу и по расписанию
async def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(message)s",
        level=logging.INFO
    )

    # один раз сразу после старта
    await post_images_async()

    # и затем каждый 30 минут
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_images_async, "interval", minutes=1)
    scheduler.start()

    # держим приложение живым
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
