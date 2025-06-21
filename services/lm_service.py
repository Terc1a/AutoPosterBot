import os
import yaml
import aiohttp
import logging
from typing import List, Tuple
from .db_service import get_marked_posts

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
LM_MODEL = os.getenv("LM_MODEL")

with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
SYSTEM_PROMPT = cfg["prompts"]["content"]

async def process_tags_with_lm(tags: List[str]) -> Tuple[str, str]:
    tags_str = ", ".join(tags)
    
    # Получаем негативные примеры
    marked_posts = await get_marked_posts()
    negative_examples = ""
    if marked_posts:
        negative_examples = "\n\n❌ НЕУДАЧНЫЕ ПРИМЕРЫ (ИЗБЕГАЙ ТАКОГО СТИЛЯ):\n"
        for i, bad_desc in enumerate(marked_posts[:3], 1):  # Ограничиваем до 3 примеров для экономии токенов
            # Обрезаем длинные примеры
            short_desc = bad_desc[:150] + "..." if len(bad_desc) > 150 else bad_desc
            negative_examples += f"❌ Плохо: {short_desc}\n"
        negative_examples += "\n⚠️ НЕ повторяй ошибки из этих примеров!"
    
    prompt = (
        f"Ты - аниме персонаж на изображении. Напиши ПОДРОБНОЕ и РАЗВЕРНУТОЕ описание от ПЕРВОГО ЛИЦА.\n"
        f"Теги: {tags_str}\n"
        f"{negative_examples}\n\n"
        f"ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:\n"
        f"• МИНИМУМ 150 символов, лучше 180-200\n"
        f"• Пиши от первого лица (я, мне, мои)\n"
        f"• Опиши ПОДРОБНО свои ощущения, мысли, желания\n"
        f"• Раскрой что ты делаешь и как это чувствуешь\n"
        f"• Используй эротическую лексику\n"
        f"• Передай эмоции и характер персонажа\n\n"
        f"Напиши ПОЛНОЕ развернутое описание (не менее 150 символов!):"
    )
    
    payload = {
        "model": LM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.9,  # Повышаем для более разнообразного и длинного текста
        "max_tokens": 300,    # Увеличиваем для гарантии 150+ символов
        "stop": None  # Не используем stop-слова, пусть модель завершает сама
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
                    
                    # Умное обрезание текста
                    def smart_truncate(text, max_length=250):
                        if len(text) <= max_length:
                            return text
                        
                        # Поиск последнего полного предложения
                        sentence_endings = ['. ', '! ', '? ', '.\n', '!\n', '?\n']
                        best_cut = -1
                        
                        for ending in sentence_endings:
                            pos = text.rfind(ending, 0, max_length)
                            if pos > best_cut and pos > 150:  # Минимум 150 символов
                                best_cut = pos + len(ending) - 1
                        
                        if best_cut > 150:
                            return text[:best_cut + 1].rstrip()
                        
                        # Если нет полных предложений, ищем пробел после слова
                        space_pos = text.rfind(' ', 150, max_length - 3)
                        if space_pos > 150:
                            return text[:space_pos] + "..."
                        
                        # Крайний случай - обрезаем по лимиту
                        return text[:max_length - 3] + "..."
                    
                    desc = smart_truncate(desc)
                    
                    # Проверка на минимальную длину после обрезания
                    if not desc or len(desc.strip()) < 100:  # Снижаем минимум, чтобы не отклонять нормальные тексты
                        logging.warning(f"Описание слишком короткое ({len(desc)} симв.): {desc}")
                        return "", f"{prompt}\n\n[ОТКЛОНЕНО: слишком короткое описание - {len(desc)} символов]"
                    
                    logging.info(f"Сгенерированное описание ({len(desc)} симв.): {desc}")
                        
                    return desc, prompt
                logging.error(f"LM Studio API returned {resp.status}")
    except Exception as e:
        logging.error(f"process_tags_with_lm error: {e}")
    return "", prompt
