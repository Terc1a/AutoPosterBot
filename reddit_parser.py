#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import os
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup

USER_AGENT = "python:reddit.parser:v2.0 (by /u/yourusername)"

def download_media(url: str, folder: str = "downloads") -> str:
    """
    Скачивает реальный медиа-файл (изображение, gif, mp4) по любой ссылке:
    - Если URL сразу отдаёт media Content-Type, скачивает его.
    - Иначе парсит HTML, ищет <video>/<source> или <meta property="og:*>.
    Рекурсивно вызывает себя, когда находит прямой media URL.
    Возвращает путь к локальному файлу.
    """
    os.makedirs(folder, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}

    # 1) Первый запрос — чтобы понять, это сразу файл или HTML-страница
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "").lower()

    # Если это HTML — ищем прямой URL на медиа внутри
    if "text/html" in ctype:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Попробуем найти видео
        video = soup.find("video")
        if video:
            src = None
            if video.has_attr("src"):
                src = video["src"]
            else:
                src_tag = video.find("source")
                if src_tag and src_tag.has_attr("src"):
                    src = src_tag["src"]
            if src:
                return download_media(src, folder)

        # Meta Open Graph: og:video или og:image
        og = soup.find("meta", property="og:video") or soup.find("meta", property="og:image")
        if og and og.has_attr("content"):
            return download_media(og["content"], folder)

        raise ValueError(f"Не удалось найти медиа на HTML-странице: {url}")

    # 2) Это файл — определяем расширение
    # Попробуем взять из URL
    path = unquote(urlsplit(resp.url).path)
    base, ext = os.path.splitext(os.path.basename(path) or "file")

    # Если расширения нет, берём из Content-Type
    if not ext:
        if "/" in ctype:
            ext = "." + ctype.split("/")[1].split(";")[0]
        else:
            ext = ""

    filename = base + ext
    filepath = os.path.join(folder, filename)

    # 3) Скачиваем потоково
    with requests.get(resp.url, headers=headers, stream=True) as r2:
        r2.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in r2.iter_content(chunk_size=8192):
                f.write(chunk)

    return filepath

def fetch_latest_post(subreddit="hentai", output_file="latest_post.json"):
    """
    Берёт первый (hot) пост из /r/{subreddit} (через JSON API),
    сохраняет JSON-данные, и если пост — не self, то скачивает media.
    """
    api_url = f"https://www.reddit.com/r/{subreddit}.json?limit=1"
    headers = {"User-Agent": USER_AGENT}

    resp = requests.get(api_url, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    children = payload.get("data", {}).get("children", [])
    if not children:
        print("❗️ Нет доступных постов.")
        return

    post = children[0]["data"]
    is_self = post.get("is_self", False)
    media_url = None

    data = {
        "post_id":     post.get("name"),
        "title":       post.get("title"),
        "author":      post.get("author"),
        "post_url":    "https://reddit.com" + post.get("permalink", ""),
        "created_utc": post.get("created_utc"),
        "content_type": "text" if is_self else "link",
        "content":     post.get("selftext") if is_self else (media_url := post.get("url"))
    }

    # 1) Сохраняем JSON
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"✅ JSON сохранён в «{output_file}»")

    # 2) Если это не текст — скачиваем медиа
    if not is_self and media_url:
        try:
            local_path = download_media(media_url)
            print(f"✅ Медиа сохранено в «{local_path}»")
        except Exception as e:
            print(f"⚠️ Ошибка при скачивании медиа: {e}")

if __name__ == "__main__":
    fetch_latest_post()
