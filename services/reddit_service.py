import requests
import json
import os
import logging
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

USER_AGENT = "python:reddit.parser:v2.0 (by /u/Yar0v)"

# Настройка логгера для reddit_service
logger = logging.getLogger('reddit_service')
logger.setLevel(logging.DEBUG)


def download_media(url: str, folder: str = "downloads", index: int = 0) -> str:
    """
    Скачивает реальный медиа-файл (изображение, gif, mp4) по любой ссылке.
    Добавлен index для различения множественных файлов из галереи.
    """
    logger.info(f"📥 Начинаем скачивание медиа #{index} с URL: {url}")
    os.makedirs(folder, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}

    try:
        # 1) Первый запрос — чтобы понять, это сразу файл или HTML-страница
        logger.debug(f"🔍 Выполняем GET запрос к {url}")
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "").lower()
        logger.debug(f"📋 Content-Type: {ctype}")

        # Если это HTML — ищем прямой URL на медиа внутри
        if "text/html" in ctype:
            logger.debug("🌐 Обнаружен HTML, парсим страницу...")
            soup = BeautifulSoup(resp.text, "html.parser")

            # Попробуем найти видео
            video = soup.find("video")
            if video:
                logger.debug("🎥 Найден тег <video>")
                src = None
                if video.has_attr("src"):
                    src = video["src"]
                else:
                    src_tag = video.find("source")
                    if src_tag and src_tag.has_attr("src"):
                        src = src_tag["src"]
                if src:
                    logger.info(f"🔗 Найден прямой URL видео: {src}")
                    return download_media(src, folder, index)

            # Meta Open Graph: og:video или og:image
            og = soup.find("meta", property="og:video") or soup.find("meta", property="og:image")
            if og and og.has_attr("content"):
                logger.info(f"🔗 Найден Open Graph URL: {og['content']}")
                return download_media(og["content"], folder, index)

            logger.error(f"❌ Не удалось найти медиа на HTML-странице: {url}")
            raise ValueError(f"Не удалось найти медиа на HTML-странице: {url}")

        # 2) Это файл — определяем расширение
        path = unquote(urlsplit(resp.url).path)
        base, ext = os.path.splitext(os.path.basename(path) or "file")

        # Если расширения нет, берём из Content-Type
        if not ext:
            if "/" in ctype:
                ext = "." + ctype.split("/")[1].split(";")[0]
            else:
                ext = ""

        # Добавляем индекс к имени файла для множественных изображений
        if index > 0:
            filename = f"{base}_{index}{ext}"
        else:
            filename = base + ext

        filepath = os.path.join(folder, filename)
        logger.info(f"💾 Сохраняем как: {filepath}")

        # 3) Скачиваем потоково
        with requests.get(resp.url, headers=headers, stream=True) as r2:
            r2.raise_for_status()
            total_size = int(r2.headers.get('content-length', 0))
            downloaded = 0

            with open(filepath, "wb") as f:
                for chunk in r2.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        if progress % 25 < 0.1:  # Логируем каждые 25%
                            logger.debug(f"⏬ Загружено: {progress:.1f}%")

        file_size = os.path.getsize(filepath) / 1024 / 1024  # MB
        logger.info(f"✅ Файл успешно скачан: {filepath} ({file_size:.2f} MB)")
        return filepath

    except Exception as e:
        logger.error(f"❌ Ошибка при скачивании медиа: {e}")
        raise


def fetch_latest(subreddit: str) -> Optional[Dict]:
    """
    Возвращает dict с информацией о последнем посте.
    Теперь поддерживает галереи Reddit с множественными изображениями.

    Возвращает:
    {
        'post_id': str,
        'title': str,
        'media_type': 'image'|'video'|'gif'|'gallery'|None,
        'media_paths': List[str],  # Список путей к файлам
        'is_gallery': bool
    }
    """
    logger.info(f"🔍 Проверяем последний пост в r/{subreddit}")
    api_url = f"https://www.reddit.com/r/{subreddit}.json?limit=1"
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        children = data.get("data", {}).get("children", [])
        if not children:
            logger.warning(f"⚠️ Не найдено постов в r/{subreddit}")
            return None

        post = children[0]["data"]
        post_id = post["name"]
        title = post.get("title", "")
        is_self = post.get("is_self", False)

        logger.info(f"📰 Найден пост: {post_id} - {title[:50]}...")
        logger.debug(f"📊 is_self: {is_self}, is_gallery: {post.get('is_gallery', False)}")

        media_paths = []
        media_type = None
        is_gallery = False

        if not is_self:
            # Проверяем, это галерея?
            if post.get("is_gallery", False):
                logger.info("🖼️ Обнаружена галерея изображений")
                is_gallery = True
                media_type = "gallery"

                # Получаем метаданные галереи
                gallery_data = post.get("gallery_data", {})
                media_metadata = post.get("media_metadata", {})

                if gallery_data and media_metadata:
                    items = gallery_data.get("items", [])
                    logger.info(f"📸 Количество изображений в галерее: {len(items)}")

                    for idx, item in enumerate(items):
                        media_id = item.get("media_id")
                        if media_id and media_id in media_metadata:
                            media_info = media_metadata[media_id]

                            # Пытаемся получить прямую ссылку на изображение
                            if "s" in media_info:
                                # Получаем URL изображения
                                if "u" in media_info["s"]:
                                    # URL в формате preview, нужно преобразовать
                                    preview_url = media_info["s"]["u"]
                                    # Заменяем preview.redd.it на i.redd.it и убираем параметры
                                    image_url = preview_url.replace("preview.redd.it", "i.redd.it")
                                    image_url = image_url.split("?")[0].replace("&amp;", "&")
                                elif "gif" in media_info["s"]:
                                    image_url = media_info["s"]["gif"]
                                else:
                                    continue

                                logger.debug(f"🔗 URL изображения #{idx}: {image_url}")

                                try:
                                    media_path = download_media(image_url, index=idx)
                                    media_paths.append(media_path)
                                except Exception as e:
                                    logger.error(f"❌ Не удалось скачать изображение #{idx}: {e}")
                else:
                    logger.error("❌ Отсутствуют данные галереи")
            else:
                # Обычный пост с одним медиа
                url = post.get("url")
                logger.info(f"📎 Обычный медиа-пост: {url}")

                try:
                    media_path = download_media(url)
                    media_paths = [media_path]

                    # Определяем тип медиа
                    ext = media_path.lower().split('.')[-1]
                    if ext in ("jpg", "jpeg", "png"):
                        media_type = "image"
                    elif ext == "mp4":
                        media_type = "video"
                    elif ext == "gif":
                        media_type = "gif"

                    logger.info(f"📋 Тип медиа: {media_type}")
                except Exception as e:
                    logger.error(f"❌ Не удалось скачать медиа: {e}")
                    return None

        result = {
            "post_id": post_id,
            "title": title,
            "media_type": media_type,
            "media_paths": media_paths,
            "is_gallery": is_gallery
        }

        logger.info(f"✅ Пост обработан успешно. Файлов скачано: {len(media_paths)}")
        return result

    except Exception as e:
        logger.error(f"❌ Ошибка при получении поста из r/{subreddit}: {e}")
        return None