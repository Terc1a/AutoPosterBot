import os
import requests
import asyncio
import logging
import yaml
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# сначала подгружаем .env
load_dotenv()

from services.reddit_service   import fetch_latest
from services.waifu_service    import fetch_images_data
from services.sd_service       import interrogate_deepbooru, interrogate_with_tagger
from services.lm_service       import process_tags_with_lm
from services.telegram_service import send_photo, send_video
from services.db_service       import init_db, is_reddit_processed, mark_reddit_processed, save_post_to_db

# читаем тайминги и subreddit
with open("vars.yaml", encoding="utf-8") as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
SUBREDDIT    = cfg["reddit"]["subreddit"]
INTERVAL_MIN = cfg["timings"]["time_scope"]
USE_TAGGER   = cfg.get("use_tagger", False)
JSON_URL     = os.getenv("JSON_URL")
LM_MODEL     = os.getenv("LM_MODEL")

async def process_cycle():
    logging.info("=== Новый цикл обработки ===")

    # 1) Reddit
    post = fetch_latest(SUBREDDIT)
    if post and post.get("media_type"):
        if not await is_reddit_processed(post["post_id"]):
            if post["media_type"] in ("video", "gif"):
                await send_video(post["media_path"])
                await mark_reddit_processed(post["post_id"])
                return

            img_bytes = open(post["media_path"], "rb").read()
            if USE_TAGGER:
                tags, method = await interrogate_with_tagger(img_bytes)
            else:
                tags, method = [], ""
            if not tags:
                tags, method = await interrogate_deepbooru(img_bytes)

            desc, desc_prompt = await process_tags_with_lm(tags)
            caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in tags[:10])

            await send_photo(img_bytes, caption)
            await save_post_to_db(
                image_url=post["media_path"],
                image_data=img_bytes,
                description=desc,
                tags=",".join(tags),
                published_at=datetime.now().isoformat(),
                interrogate_model=method,
                interrogate_method=method,
                interrogate_prompt="reddit_interrogate",
                description_model=LM_MODEL,
                description_prompt=desc_prompt
            )
            await mark_reddit_processed(post["post_id"])
            return

    # 2) fallback — waifu.fm
    waifus = fetch_images_data(JSON_URL)
    for item in waifus:
        resp = requests.get(item["url"], timeout=15); resp.raise_for_status()
        img_bytes = resp.content

        if USE_TAGGER:
            tags, method = await interrogate_with_tagger(img_bytes)
        else:
            tags, method = [], ""
        if not tags:
            tags, method = await interrogate_deepbooru(img_bytes)

        desc, desc_prompt = await process_tags_with_lm(tags)
        caption = f"{desc}\n\n" + " ".join(f"#{t}" for t in item["tags"][:10])

        await send_photo(img_bytes, caption)
        await save_post_to_db(
            image_url=item["url"],
            image_data=img_bytes,
            description=desc,
            tags=",".join(item["tags"]),
            published_at=datetime.now().isoformat(),
            interrogate_model=method,
            interrogate_method=method,
            interrogate_prompt="waifu_interrogate",
            description_model=LM_MODEL,
            description_prompt=desc_prompt
        )

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    # запустить первый цикл сразу
    await process_cycle()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(process_cycle, "interval", minutes=INTERVAL_MIN)
    scheduler.start()
    # вечно ждем
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
