#!/usr/bin/env python3
# bot_async_json_with_sd_lm_sqlite.py

import os
import asyncio
import logging
import base64
import yaml
import json
from io import BytesIO
from urllib.parse import urlparse
from datetime import datetime
import requests
import aiohttp
import aiosqlite
from dotenv import load_dotenv
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 1) Загрузка настроек из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
JSON_URL = os.getenv("JSON_URL")

# Загрузка настроек из yaml
options = 'vars.yaml'
with open(options, encoding="utf-8") as f:
    yaml_data = yaml.load(f, Loader=yaml.FullLoader)


# Настройки для SD и LM Studio
SD_URL = os.getenv("SD_URL", "http://127.0.0.1:7860")
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234")
LM_MODEL = os.getenv("LM_MODEL", "saiga_nemo_12b_gguf")

# Настройки SQLite
DATABASE_PATH = os.getenv("DATABASE_PATH", "telegram_bot.db")

if not BOT_TOKEN or not CHANNEL_ID or not JSON_URL:
    raise RuntimeError("Укажите в .env BOT_TOKEN, CHANNEL_ID и JSON_URL")

bot = Bot(token=BOT_TOKEN)


# Инициализация базы данных SQLite
async def init_database():
    """Создает таблицу для хранения данных о публикациях"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Создаем таблицу если её нет
            create_table_query = yaml_data['queries']["create_table_q"]
            await db.execute(create_table_query)

            # Создаем индексы для быстрого поиска
            await db.execute("CREATE INDEX IF NOT EXISTS idx_published_at ON post_logs(published_at);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_interrogate_model ON post_logs(interrogate_model);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_description_model ON post_logs(description_model);")

            await db.commit()
            logging.info("База данных SQLite инициализирована успешно")

    except Exception as e:
        logging.error(f"Ошибка при инициализации базы данных: {e}")


# 3) Сохранение данных в SQLite
async def save_post_to_db(
        image_url: str,
        image_data: bytes,
        description: str,
        tags: list,
        interrogate_model: str,
        interrogate_method: str,
        interrogate_prompt: str,
        description_model: str,
        description_prompt: str
):
    """Сохраняет данные о публикации в базу данных"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            insert_query = yaml_data['queries']["insert_q"]

            # Преобразуем теги в JSON строку
            tags_json = json.dumps(tags, ensure_ascii=False)

            cursor = await db.execute(insert_query, (
                image_url,
                image_data,
                description,
                tags_json,
                datetime.now().isoformat(),
                interrogate_model,
                interrogate_method,
                interrogate_prompt,
                description_model,
                description_prompt
            ))

            await db.commit()
            post_id = cursor.lastrowid
            logging.info(f"Данные сохранены в БД с ID: {post_id}")
            return post_id

    except Exception as e:
        logging.error(f"Ошибка при сохранении в базу данных: {e}")
        return None


# 4) Функция для получения статистики из БД
async def get_database_stats():
    """Возвращает статистику по базе данных"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Общее количество записей
            cursor = await db.execute(yaml_data['queries']['logs_count_q'])
            total_posts = (await cursor.fetchone())[0]

            # Количество записей за последние 24 часа
            cursor = await db.execute(yaml_data['queries']['str_count_q'])
            posts_24h = (await cursor.fetchone())[0]

            # Топ моделей
            cursor = await db.execute(yaml_data['queries']['top_models_q'])
            top_models = await cursor.fetchall()

            logging.info(f"📊 Статистика БД: всего постов: {total_posts}, за 24ч: {posts_24h}")
            logging.info(f"📊 Топ моделей: {top_models}")

            return {
                'total_posts': total_posts,
                'posts_24h': posts_24h,
                'top_models': top_models
            }

    except Exception as e:
        logging.error(f"Ошибка при получении статистики: {e}")
        return None


# 5) Функция для получения изображений из API
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
        tags = [t.get("name") for t in img.get("tags", []) if t.get("name")]
        result.append({
            "url": url,
            "tags": tags
        })
    return result


# 6) Функция для Interrogate через Stable Diffusion API
async def interrogate_deepbooru(image_bytes: bytes) -> tuple[list[str], str]:
    """
    Отправляет изображение в SD для анализа через доступные interrogate модели
    Возвращает (список тегов, промпт для interrogate)
    """
    interrogate_prompt = "deepbooru"

    try:
        # Конвертируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Сначала пробуем deepdanbooru (часто установлен вместо deepbooru)
        for model_name in ["deepdanbooru", "deepbooru", "clip", "interrogate"]:
            try:
                payload = {
                    "image": f"data:image/png;base64,{image_base64}",
                    "model": model_name
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                            f"{SD_URL}/sdapi/v1/interrogate",
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=aiohttp.ClientTimeout(total=120)
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            caption = result.get("caption", "")

                            # Проверяем, что получили валидный результат
                            if caption and caption not in ["<error>", "", "None"]:
                                logging.info(f"Успешно использована модель: {model_name}")

                                # Обработка результата в зависимости от модели
                                if model_name in ["deepbooru", "deepdanbooru"]:
                                    # Теги через запятую
                                    tags = [tag.strip() for tag in caption.split(",") if tag.strip()]
                                else:
                                    # CLIP возвращает описание, извлекаем ключевые слова
                                    # Разбиваем по пробелам и берем существенные слова
                                    words = caption.replace(",", " ").replace(".", " ").split()
                                    tags = [word.strip() for word in words
                                            if len(word.strip()) > 3 and not word.strip().lower() in
                                                                             ["with", "that", "this", "from", "have",
                                                                              "been", "were", "are"]]

                                logging.info(f"Получено {len(tags)} тегов от {model_name}")
                                return tags[:20], f"{model_name}_interrogate"  # Ограничиваем количество
                            else:
                                logging.warning(f"Модель {model_name} вернула пустой/ошибочный результат: {caption}")

                        elif response.status == 404:
                            logging.debug(f"Модель {model_name} не найдена, пробуем следующую...")
                        else:
                            error_text = await response.text()
                            logging.debug(f"Ошибка с моделью {model_name}: {response.status} - {error_text}")

            except Exception as e:
                logging.debug(f"Ошибка при попытке использовать модель {model_name}: {e}")
                continue

        # Если ни одна модель не сработала
        logging.error("Ни одна модель interrogate не доступна")
        return [], "no_interrogate"

    except Exception as e:
        logging.error(f"Критическая ошибка при interrogate: {e}")
        return [], "error"


# Функция для получения доступных interrogate моделей
async def get_available_interrogate_models():
    """
    Пытается определить, какие модели interrogate доступны
    """
    available_models = []

    try:
        # Создаем тестовое изображение (1x1 белый пиксель)
        test_image = base64.b64encode(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f'
            b'\x00\x00\x01\x01\x00\x05\x00\x00\x00\x00IEND\xaeB`\x82'
        ).decode('utf-8')

        for model in ["deepdanbooru", "deepbooru", "clip", "interrogate"]:
            try:
                payload = {
                    "image": f"data:image/png;base64,{test_image}",
                    "model": model
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                            f"{SD_URL}/sdapi/v1/interrogate",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            available_models.append(model)

            except:
                pass

        return available_models

    except Exception as e:
        logging.error(f"Ошибка при проверке моделей: {e}")
        return []


# Альтернативная функция с использованием tagger (если установлен)
async def interrogate_with_tagger(image_bytes: bytes) -> tuple[list[str], str]:
    """
    Использует расширение Tagger для SD WebUI (если установлено)
    """
    try:
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Эндпоинт для Tagger extension
        payload = {
            "image": f"data:image/png;base64,{image_base64}",
            "threshold": 0.35  # Порог уверенности
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{SD_URL}/tagger/v1/interrogate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Tagger возвращает словарь с тегами и их весами
                    tags_dict = result.get("tags", {})
                    # Сортируем по весу и берем топ теги
                    sorted_tags = sorted(tags_dict.items(), key=lambda x: x[1], reverse=True)
                    tags = [tag for tag, weight in sorted_tags if weight > 0.35][:20]

                    if tags:
                        logging.info(f"Tagger вернул {len(tags)} тегов")
                        return tags, "tagger_extension"

        return [], "tagger_not_available"

    except Exception as e:
        logging.debug(f"Tagger extension недоступен: {e}")
        return [], "tagger_error"


# 7) Функция для обработки тегов через LM Studio
async def process_tags_with_lm(tags: list[str]) -> tuple[str, str]:
    """
    Отправляет теги в LM Studio для обработки
    Возвращает (обработанный текст, промпт)
    """
    tags_str = ", ".join(tags)
    print(tags_str)
# переписать промпт так чтобы вместо тега подставлялся ? как в SQL-запросах
    prompt = f"""Ты - пишешь текст для хентай-манги. 
На основе следующих тегов создай краткое, но информативное описание изображения на русском языке.
Теги: {tags_str}

Описание:"""

    try:
        payload = {
            "model": LM_MODEL,
            "messages": [
                {"role": "system", "content": yaml_data['prompts']['content']},
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
                    description = result["choices"][0]["message"]["content"].strip()
                    return description, prompt
                else:
                    logging.error(f"LM Studio API error: {response.status}")
                    return "", prompt

    except Exception as e:
        logging.error(f"Ошибка при обработке через LM Studio: {e}")
        return "", prompt


# 8) Обновленная функция отправки изображений
# Обновленная часть post_images_async:

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

            # 1. Сначала пробуем Tagger extension (обычно дает лучшие результаты)
            tags_from_ai, interrogate_method = await interrogate_with_tagger(image_bytes)

            # 2. Если Tagger не сработал, пробуем стандартный interrogate
            if not tags_from_ai:
                tags_from_ai, interrogate_method = await interrogate_deepbooru(image_bytes)

            # Логируем результат
            if tags_from_ai:
                logging.info(f"Получено {len(tags_from_ai)} тегов через {interrogate_method}")
                logging.info(f"Примеры тегов: {tags_from_ai[:5]}")
            else:
                logging.warning("Не удалось получить теги от AI, используем только оригинальные")

            # 3. Объединяем оригинальные теги и теги от AI
            all_tags = list(set(original_tags + tags_from_ai))

            # 4. Обрабатываем теги через LM Studio (используем ВСЕ теги для лучшего описания)
            description, description_prompt = await process_tags_with_lm(all_tags)
            logging.info(f"LM Studio description: {description}")

            # 5. Формируем финальную подпись
            caption_parts = []

            if description:
                caption_parts.append(description)

            # В подписи используем ТОЛЬКО оригинальные теги с waifu.fm
            if original_tags:
                # Ограничиваем количество хештегов
                hashtags = [f"#{tag.replace(' ', '_').replace('-', '_')}"
                            for tag in original_tags[:10]]
                caption_parts.append("\n\n" + " ".join(hashtags))

            caption = "\n".join(caption_parts) if caption_parts else None

            # 6. Отправляем в Telegram
            bio = BytesIO(image_bytes)
            bio.name = os.path.basename(urlparse(img_url).path)
            bio.seek(0)

            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=bio,
                caption=caption[:1024] if caption else None
            )

            # 7. Сохраняем данные в базу
            post_id = await save_post_to_db(
                image_url=img_url,
                image_data=image_bytes,
                description=description,
                tags=all_tags,
                interrogate_model=interrogate_method.split('_')[0] if interrogate_method else "none",
                interrogate_method=interrogate_method,
                interrogate_prompt="auto_interrogate",
                description_model=LM_MODEL,
                description_prompt=description_prompt
            )

            if post_id:
                logging.info(f"Пост успешно сохранен в БД с ID: {post_id}")

            # Небольшая задержка между отправками
            await asyncio.sleep(2)

        logging.info("Успешно отправили все картинки с обработанными описаниями.")

        # Показываем статистику после обработки
        await get_database_stats()

    except Exception as e:
        logging.error("Ошибка при отправке изображений: %s", e)


# 9) Главная функция
async def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(message)s",
        level=logging.INFO
    )

    # Инициализируем базу данных
    await init_database()

    # Показываем начальную статистику
    await get_database_stats()

    # Проверяем доступность сервисов
    try:
        resp = requests.get(f"{SD_URL}/sdapi/v1/options")
        if resp.status_code == 200:
            logging.info("✅ Stable Diffusion API доступен")

            # Проверяем доступные модели interrogate
            available_models = await get_available_interrogate_models()
            if available_models:
                logging.info(f"✅ Доступные модели interrogate: {', '.join(available_models)}")
            else:
                logging.warning("⚠️ Модели interrogate не обнаружены")

            # Проверяем Tagger extension
            try:
                tagger_resp = requests.get(f"{SD_URL}/tagger/v1/")
                if tagger_resp.status_code in [200, 404]:  # 404 означает что эндпоинт есть, но нужен POST
                    logging.info("✅ Tagger extension возможно доступен")
            except:
                logging.info("ℹ️ Tagger extension не установлен")

        else:
            logging.warning("⚠️ Stable Diffusion API недоступен")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось подключиться к Stable Diffusion: {e}")

    try:
        resp = requests.get(f"{LM_STUDIO_URL}/v1/models")
        if resp.status_code == 200:
            logging.info("✅ LM Studio API доступен")
            models = resp.json().get("data", [])
            if models:
                logging.info(f"   Доступные модели: {[m['id'] for m in models]}")
        else:
            logging.warning("⚠️ LM Studio API недоступен")
    except:
        logging.warning("⚠️ Не удалось подключиться к LM Studio")

    # Проверяем базу данных
    if os.path.exists(DATABASE_PATH):
        size = os.path.getsize(DATABASE_PATH) / 1024 / 1024  # MB
        logging.info(f"✅ База данных SQLite: {DATABASE_PATH} ({size:.2f} MB)")
    else:
        logging.info(f"✅ Создана новая база данных: {DATABASE_PATH}")

    # Один раз сразу после старта
    await post_images_async()

    # И затем каждые N минут
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_images_async, "interval", minutes=yaml_data['timings']['time_scope'])
    scheduler.start()

    # Держим приложение живым
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

# ToDo
# Сделать отдельный ямл-файл для текста описания логов и по ошибке просто вываливать нужную строку
# Сделать интерфейс, в котором можно настраивать все поля из ямлов
# Сделать дашборд
# Сделать парсинг данных из нескольких источников
# Подумать как можно прикрутить парсинг видео, а не только фото
# Сделать сервис аналитики постов в канале(количество просмотров/лайков/комментариев)
# Сделать сервис аналитики самого канала(можно потом будет прикрутить интеграцию с TGStats и искать подписчиков моего канала в других каналах/чатах для того чтобы понимать интересы аудитории)