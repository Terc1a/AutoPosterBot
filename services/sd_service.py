import os
import base64
import logging
import aiohttp
from typing import List, Tuple

SD_URL = os.getenv("SD_URL")

async def interrogate_deepbooru(image_bytes: bytes) -> Tuple[List[str], str]:
    """
    Отправляем в SD WebUI interrogate-модели: deepdanbooru → deepbooru → clip → interrogate
    Возвращаем (список тегов, имя модели)
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        for model_name in ["deepdanbooru", "deepbooru", "clip", "interrogate"]:
            payload = {"image": f"data:image/png;base64,{b64}", "model": model_name}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{SD_URL}/sdapi/v1/interrogate",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        caption = data.get("caption", "")
                        tags = caption.split()
                        return tags, model_name
    except Exception as e:
        logging.error(f"interrogate_deepbooru error: {e}")
    return [], "none"


async def interrogate_with_tagger(image_bytes: bytes) -> Tuple[List[str], str]:
    """
    Если установлен tagger extension в SD WebUI
    Возвращаем (теги, "tagger_extension") или ([], reason)
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload = {"image": f"data:image/png;base64,{b64}", "threshold": 0.35}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SD_URL}/tagger/v1/interrogate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tags_dict = data.get("tags", {})
                    sorted_tags = sorted(tags_dict.items(), key=lambda x: x[1], reverse=True)
                    tags = [tag for tag, weight in sorted_tags if weight > 0.35][:20]
                    if tags:
                        return tags, "tagger_extension"
    except Exception as e:
        logging.debug(f"interrogate_with_tagger error: {e}")
    return [], "tagger_not_available"
