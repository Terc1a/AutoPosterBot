import os
import yaml
import aiohttp
import logging
from typing import List, Tuple
from .db_service import get_marked_posts
import random

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
LM_MODEL = os.getenv("LM_MODEL")

with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
SYSTEM_PROMPT = cfg["prompts"]["content"]

STARTERS = [
    "Опиши, что ты чувствуешь **внутри**, не упоминая внешность.",
    "Погрузись в свои желания, не отвлекаясь на детали вокруг.",
    "Опиши своё возбуждение, не рассказывая о том, как ты выглядишь.",
    "Передай внутреннее состояние, будто ты шепчешь это на ухо.",
    "Ты — девушка, которая вот-вот сорвётся от желания. Что у тебя в голове?"
]

starter_instruction = random.choice(STARTERS)


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
        f"{starter_instruction}\n"
        f"Теги ситуации: {tags_str}\n"
        f"{negative_examples}\n\n"
        f"КАК НУЖНО ПИСАТЬ:\n"
        f'Каждое движение внутри сводит меня с ума...'
        f'Так горячо... я больше не могу терпеть...'
        f'Мне хочется сорваться прямо сейчас...'
        f"✓ 'Мне так хочется, чтобы ты трахнул меня...'\n"
        f"✓ 'Ох, я не могу сдержать свои стоны...'\n\n"
        f"КАК НЕЛЬЗЯ ПИСАТЬ:\n"
        f"✗ 'Мои длинные волосы...' / 'Я красивая...'\n"
        f"✗ 'Комната освещена...' / 'На мне платье...'\n"
        f"✗ 'Моя силуэт...' / 'Мое тело...'\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"• 150-200 символов\n"
        f"• ТОЛЬКО от первого лица (я, мне, моя)\n"
        f"• ТОЛЬКО ощущения и желания, НИКАКОЙ внешности!\n"
        f"• Маты разрешены и приветствуются\n\n"
        f"Напиши КАК ТЫ ЧУВСТВУЕШЬ сейчас:"
    )

    payload = {
        "model": LM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.9,  # Повышаем для более разнообразного и длинного текста
        "max_tokens": 300,  # Увеличиваем для гарантии 150+ символов
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
