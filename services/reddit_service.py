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
                    url = src
                    # Обновляем content-type
                    sub_resp = requests.head(url, headers=headers, timeout=10)
                    ctype = sub_resp.headers.get("Content-Type", "video/mp4").lower()
            else:
                # Попробуем найти изображение
                img = soup.find("img")
                if img and img.has_attr("src"):
                    logger.debug("🖼️ Найден тег <img>")
                    src = img["src"]
                    logger.info(f"🔗 Найден прямой URL изображения: {src}")
                    url = src
                    # Обновляем content-type
                    sub_resp = requests.head(url, headers=headers, timeout=10)
                    ctype = sub_resp.headers.get("Content-Type", "image/jpeg").lower()

        # Загружаем файл
        logger.debug(f"⬇️ Скачиваем файл по URL: {url}")
        file_resp = requests.get(url, headers=headers, stream=True, timeout=30)
        file_resp.raise_for_status()

        # Определяем расширение файла
        if "image/jpeg" in ctype or "image/jpg" in ctype:
            ext = "jpeg"
        elif "image/png" in ctype:
            ext = "png"
        elif "image/gif" in ctype:
            ext = "gif"
        elif "video/mp4" in ctype:
            ext = "mp4"
        else:
            # Пытаемся извлечь из URL
            parsed_url = urlsplit(url)
            filename = os.path.basename(unquote(parsed_url.path))
            if "." in filename:
                ext = filename.split(".")[-1].lower()
            else:
                ext = "jpg"  # По умолчанию

        # Генерируем имя файла
        parsed_url = urlsplit(url)
        base_name = os.path.basename(unquote(parsed_url.path))
        if not base_name or "." not in base_name:
            base_name = f"media_{index}.{ext}"
        else:
            # Убираем расширение и добавляем правильное
            base_name = base_name.split(".")[0] + f".{ext}"

        filepath = os.path.join(folder, base_name)
        logger.info(f"💾 Сохраняем как: {filepath}")

        # Скачиваем с прогрессом
        total_size = int(file_resp.headers.get('content-length', 0))
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in file_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        if progress % 25 < 1:  # Логируем каждые 25%
                            logger.debug(f"⏬ Загружено: {progress:.1f}%")

        size_mb = os.path.getsize(filepath) / 1024 / 1024
        logger.info(f"✅ Файл успешно скачан: {filepath} ({size_mb:.2f} MB)")
        return filepath

    except Exception as e:
        logger.error(f"❌ Ошибка при скачивании медиа: {e}")
        raise


def process_reddit_post_data(post: Dict) -> Optional[Dict]:
    """
    Обрабатывает данные одного поста Reddit и возвращает словарь с медиа-информацией.
    
    Args:
        post: данные поста из Reddit API
        
    Returns:
        Optional[Dict]: данные поста с медиа или None если пост не содержит медиа
    """
    post_id = post["name"]
    title = post.get("title", "")
    is_self = post.get("is_self", False)

    logger.debug(f"📰 Обрабатываем пост: {post_id} - {title[:50]}...")

    media_paths = []
    media_type = None
    is_gallery = False

    if not is_self:
        # Проверяем, это галерея?
        if post.get("is_gallery", False):
            logger.debug("🖼️ Обнаружена галерея изображений")
            is_gallery = True
            media_type = "gallery"

            # Получаем метаданные галереи
            gallery_data = post.get("gallery_data", {})
            media_metadata = post.get("media_metadata", {})

            if gallery_data and media_metadata:
                items = gallery_data.get("items", [])
                logger.debug(f"📸 Количество изображений в галерее: {len(items)}")

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
                logger.debug("❌ Отсутствуют данные галереи")
        else:
            # Обычный пост с одним медиа
            url = post.get("url")
            logger.debug(f"📎 Обычный медиа-пост: {url}")

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

                logger.debug(f"📋 Тип медиа: {media_type}")
            except Exception as e:
                logger.debug(f"❌ Не удалось скачать медиа: {e}")

    # Возвращаем результат только если есть медиа-файлы
    if media_paths:
        result = {
            "post_id": post_id,
            "title": title,
            "media_type": media_type,
            "media_paths": media_paths,
            "is_gallery": is_gallery
        }
        logger.debug(f"✅ Пост обработан успешно. Файлов скачано: {len(media_paths)}")
        return result
    else:
        logger.debug("📭 Пост не содержит медиа-файлов")
        return None


def fetch_latest_posts(subreddit: str, limit: int = 5) -> List[Dict]:
    """
    Возвращает список последних постов из subreddit.
    
    Args:
        subreddit: название subreddit
        limit: количество постов для получения (по умолчанию 5)
        
    Returns:
        List[Dict]: список постов в том же формате, что и fetch_latest
    """
    logger.info(f"🔍 Получаем {limit} последних постов из r/{subreddit}")
    api_url = f"https://www.reddit.com/r/{subreddit}.json?limit={limit}"
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        children = data.get("data", {}).get("children", [])
        if not children:
            logger.warning(f"⚠️ Не найдено постов в r/{subreddit}")
            return []

        posts = []
        for child in children:
            post_data = process_reddit_post_data(child["data"])
            if post_data:  # Только если пост содержит медиа
                posts.append(post_data)
        
        logger.info(f"📊 Получено {len(posts)} медиа-постов из {len(children)} всего")
        return posts

    except requests.RequestException as e:
        logger.error(f"❌ Ошибка при запросе к Reddit API: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при парсинге постов: {e}")
        return []


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
    posts = fetch_latest_posts(subreddit, limit=1)
    return posts[0] if posts else None