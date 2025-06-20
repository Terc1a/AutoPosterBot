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
        f"🚨 КРИТИЧЕСКИ ВАЖНО: СТРОГО ЗАПРЕЩЕНО описывать внешность!\n\n"
        f"ЗАДАЧА: Создай КОРОТКОЕ эротическое описание по тегам.\n"
        f"Теги: {tags_str}\n"
        f"{negative_examples}\n\n"
        f"🔥 ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:\n"
        f"✅ МАКСИМУМ 200 СИМВОЛОВ (включая пробелы)\n"
        f"✅ Максимум 35 слов\n"
        f"✅ Фокус ТОЛЬКО на действиях и процессе\n"
        f"✅ ТОЛЬКО ощущения и эмоции\n\n"
        f"🚫 КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:\n"
        f"❌ Любые описания лица, волос, глаз, телосложения\n"
        f"❌ Любые описания одежды, белья, аксессуаров\n"
        f"❌ Любые описания окружения, мебели, локаций\n"
        f"❌ Слова: красивая, длинные, короткие, большие, маленькие (о внешности)\n\n"
        f"⚡ ПОМНИ: Описывай ТОЛЬКО что ДЕЛАЮТ, НЕ как ВЫГЛЯДЯТ!\n\n"
        f"Описание (до 200 символов, только действия):"
    )
    
    payload = {
        "model": LM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6,  # Снижаем температуру для лучшего следования инструкциям
        "max_tokens": 80,    # Жестко ограничиваем токены (примерно 200 символов)
        "stop": ["\n\n", "200", "символов"]  # Стоп-слова для принудительной остановки
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
                    
                    # Принудительное обрезание если нейросеть не соблюдает лимит
                    if len(desc) > 200:
                        desc = desc[:197] + "..."
                    
                    # Фильтрация только критических слов о внешности (смягченный подход)
                    forbidden_appearance = [
                        'красив', 'прекрасн', 'великолепн', 'привлекательн', 
                        'блондин', 'брюнет', 'рыж', 'светлые волос', 'темные волос',
                        'голубые глаза', 'карие глаза', 'зеленые глаза', 'большие глаза',
                        'длинные волос', 'короткие волос', 'кудрявые волос', 'прямые волос',
                        'стройн', 'полн', 'худ', 'толст', 'высок', 'низк', 'миниатюрн',
                        'платье', 'юбка', 'блузка', 'рубашка', 'джинсы', 'брюки',
                        'комната', 'спальня', 'гостиная', 'кухня', 'ванная', 'офис', 'школа'
                    ]
                    
                    desc_lower = desc.lower()
                    contains_forbidden = any(word in desc_lower for word in forbidden_appearance)
                    
                    # Добавляем логирование для отладки
                    logging.info(f"Сгенерированное описание: {desc}")
                    if contains_forbidden:
                        found_words = [word for word in forbidden_appearance if word in desc_lower]
                        logging.warning(f"Описание отклонено, найдены запрещенные слова: {found_words}")
                        return "", f"{prompt}\n\n[ОТКЛОНЕНО: содержит описания внешности: {found_words}]"
                        
                    return desc, prompt
                logging.error(f"LM Studio API returned {resp.status}")
    except Exception as e:
        logging.error(f"process_tags_with_lm error: {e}")
    return "", prompt
