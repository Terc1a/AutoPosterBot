import requests
import json
import os
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup

USER_AGENT = "python:reddit.parser:v2.0 (by /u/Yar0v)"

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

def fetch_latest(subreddit: str):
    """
    Возвращает dict с {'post_id', 'media_type', 'media_path'} для самого свежего поста (hot=1).
    media_type: 'image', 'video', 'gif' или None.
    """
    api_url = f"https://www.reddit.com/r/{subreddit}.json?limit=1"
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(api_url, headers=headers, timeout=15)
    resp.raise_for_status()
    children = resp.json().get("data", {}).get("children", [])
    if not children:
        return None

    post = children[0]["data"]
    post_id = post["name"]
    is_self = post.get("is_self", False)
    media_path = None
    media_type = None

    if not is_self:
        url = post.get("url")
        media_path = download_media(url)
        ext = media_path.lower().split('.')[-1]
        if ext in ("jpg", "jpeg", "png"): media_type = "image"
        elif ext == "mp4":               media_type = "video"
        elif ext == "gif":               media_type = "gif"

    return {"post_id": post_id, "media_type": media_type, "media_path": media_path}
