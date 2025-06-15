import os
import yaml
import aiohttp
import logging
from typing import List, Tuple

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
LM_MODEL = os.getenv("LM_MODEL")

with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
SYSTEM_PROMPT = cfg["prompts"]["content"]

async def process_tags_with_lm(tags: List[str]) -> Tuple[str, str]:
    tags_str = ", ".join(tags)
    prompt = (
        f"Ты – пишешь текст для хентай-манги.\n"
        f"На основе следующих тегов создай краткое, но информативное описание изображения на русском языке.\n"
        f"Теги: {tags_str}\n\nОписание:"
    )
    payload = {
        "model": LM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    desc = data["choices"][0]["message"]["content"].strip()
                    return desc, prompt
                logging.error(f"LM Studio API returned {resp.status}")
    except Exception as e:
        logging.error(f"process_tags_with_lm error: {e}")
    return "", prompt
