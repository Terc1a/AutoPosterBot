#!/usr/bin/env python3
# bot_async_json_with_sd_lm.py

import os
import asyncio
import logging
import base64
from io import BytesIO
from urllib.parse import urlparse
import requests
import aiohttp
from dotenv import load_dotenv
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 1) Загрузка настроек из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
JSON_URL = os.getenv("JSON_URL")
content = os.getenv("content")

# Добавляем новые настройки
SD_URL = os.getenv("SD_URL", "http://127.0.0.1:7860")
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234")
LM_MODEL = os.getenv("LM_MODEL", "saiga_nemo_12b_gguf")  # название модели в LM Studio

if not BOT_TOKEN or not CHANNEL_ID or not JSON_URL:
    raise RuntimeError("Укажите в .env BOT_TOKEN, CHANNEL_ID и JSON_URL")

bot = Bot(token=BOT_TOKEN)


# 2) Функция для получения изображений из API
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


# 3) Функция для Interrogate через Stable Diffusion API
async def interrogate_deepbooru(image_bytes: bytes) -> list[str]:
    """
    Отправляет изображение в SD для анализа через Deepbooru
    Возвращает список тегов
    """
    try:
        # Конвертируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Формируем запрос к SD API
        payload = {
            "image": f"data:image/png;base64,{image_base64}",
            "model": "deepbooru"  # или "deepdanbooru" в зависимости от вашей конфигурации
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{SD_URL}/sdapi/v1/interrogate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # SD возвращает строку с тегами через запятую
                    tags_string = result.get("caption", "")
                    # Разбиваем на отдельные теги и очищаем от пробелов
                    tags = [tag.strip() for tag in tags_string.split(",") if tag.strip()]
                    return tags
                else:
                    logging.error(f"SD API error: {response.status}")
                    return []

    except Exception as e:
        logging.error(f"Ошибка при interrogate: {e}")
        return []


# 4) Функция для обработки тегов через LM Studio
async def process_tags_with_lm(tags: list[str]) -> str:
    """
    Отправляет теги в LM Studio для обработки
    Возвращает обработанный текст
    """
    try:
        # Формируем промпт для LM
        tags_str = ", ".join(tags)
        prompt = f"""Ты - помощник для создания описаний изображений. 
На основе следующих тегов создай краткое, но информативное описание изображения на русском языке.
Теги: {tags_str}

Описание:"""

        # Запрос к LM Studio API (формат OpenAI-совместимый)
        payload = {
            "model": LM_MODEL,
            "messages": [
                {"role": "system", "content":content},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 150
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{LM_STUDIO_URL}/v1/chat/completions",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Извлекаем текст ответа
                    description = result["choices"][0]["message"]["content"].strip()
                    return description
                else:
                    logging.error(f"LM Studio API error: {response.status}")
                    return ""

    except Exception as e:
        logging.error(f"Ошибка при обработке через LM Studio: {e}")
        return ""


# 5) Обновленная функция отправки изображений
async def post_images_async():
    try:
        images = fetch_images_data(JSON_URL)

        for item in images:
            img_url = item["url"]
            original_tags = item["tags"]

            # Скачиваем изображение
            resp = requests.get(img_url)
            resp.raise_for_status()
            image_bytes = resp.content

            # 1. Получаем теги от Deepbooru
            deepbooru_tags = await interrogate_deepbooru(image_bytes)
            logging.info(f"Deepbooru tags: {deepbooru_tags}")

            # 2. Объединяем оригинальные теги и теги от Deepbooru
            all_tags = list(set(original_tags + deepbooru_tags))

            # 3. Обрабатываем теги через LM Studio
            description = await process_tags_with_lm(all_tags)
            logging.info(f"LM Studio description: {description}")

            # 4. Формируем финальную подпись
            caption_parts = []

            # Добавляем описание от LM
            if description:
                caption_parts.append(description)

            # Добавляем хештеги
            if all_tags:
                hashtags = [f"#{tag.replace(' ', '_').replace('-', '_')}" for tag in
                            all_tags[:10]]  # Ограничиваем количество тегов
                caption_parts.append("\n\n" + " ".join(hashtags))

            caption = "\n".join(caption_parts) if caption_parts else None

            # 5. Отправляем в Telegram
            bio = BytesIO(image_bytes)
            bio.name = os.path.basename(urlparse(img_url).path)
            bio.seek(0)

            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=bio,
                caption=caption[:1024] if caption else None  # Telegram ограничение на длину подписи
            )

            # Небольшая задержка между отправками
            await asyncio.sleep(2)

        logging.info("Успешно отправили все картинки с обработанными описаниями.")

    except Exception as e:
        logging.error("Ошибка при отправке изображений: %s", e)


# 6) Главная функция
async def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(message)s",
        level=logging.INFO
    )

    # Проверяем доступность сервисов
    try:
        # Проверка SD
        resp = requests.get(f"{SD_URL}/sdapi/v1/options")
        if resp.status_code == 200:
            logging.info("Stable Diffusion API доступен")
        else:
            logging.warning("Stable Diffusion API недоступен")
    except:
        logging.warning("Не удалось подключиться к Stable Diffusion")

    try:
        # Проверка LM Studio
        resp = requests.get(f"{LM_STUDIO_URL}/v1/models")
        if resp.status_code == 200:
            logging.info("LM Studio API доступен")
        else:
            logging.warning("LM Studio API недоступен")
    except:
        logging.warning("Не удалось подключиться к LM Studio")

    # Один раз сразу после старта
    await post_images_async()

    # И затем каждые 30 минут (можно изменить интервал)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_images_async, "interval", minutes=120)
    scheduler.start()

    # Держим приложение живым
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())