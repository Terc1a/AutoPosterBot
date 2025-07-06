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
    logger = logging.getLogger(__name__)
    logger.info(f"🔍 Пытаемся получить теги через SD WebUI: {SD_URL}")
    
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        for model_name in ["deepdanbooru", "deepbooru", "clip", "interrogate"]:
            logger.info(f"🔮 Пробуем модель: {model_name}")
            payload = {"image": f"data:image/png;base64,{b64}", "model": model_name}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{SD_URL}/sdapi/v1/interrogate",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    logger.info(f"📡 SD WebUI ответ: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        caption = data.get("caption", "")
                        logger.info(f"📡 SD API ответ: {data}")
                        logger.info(f"📝 Полная caption: '{caption}'")
                        logger.info(f"📝 Получена caption: {caption[:100]}...")
                        
                        # Правильно парсим теги - SD может возвращать теги через запятую
                        if "," in caption:
                            tags = [tag.strip() for tag in caption.split(",") if tag.strip()]
                        else:
                            tags = [tag.strip() for tag in caption.split() if tag.strip()]
                        
                        # Проверяем, что получили осмысленные теги
                        if not tags or tags == ['<error>'] or (len(tags) == 1 and '<' in tags[0]):
                            logger.warning(f"⚠️ SD WebUI вернул ошибку или пустые теги: '{caption}'")
                            continue  # Пробуем следующую модель
                        
                        logger.info(f"🏷️ Распарсили {len(tags)} тегов: {tags[:10]}")
                        logger.info(f"🔍 Все теги: {tags}")
                        return tags, model_name
                    else:
                        logger.warning(f"❌ Модель {model_name} не сработала: {resp.status}")
    except Exception as e:
        logger.error(f"❌ interrogate_deepbooru error: {e}")
    
    logger.warning("🚫 SD WebUI не дал тегов, возвращаем пустой список")
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
