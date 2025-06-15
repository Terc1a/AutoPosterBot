import requests
from typing import List, Dict

def fetch_images_data(api_url: str) -> List[Dict[str, object]]:
    resp = requests.get(api_url, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("images", [])
    result: List[Dict[str, object]] = []
    for img in data:
        url = img.get("url")
        if not url:
            continue
        tags = [t["name"] for t in img.get("tags", []) if t.get("name")]
        result.append({"url": url, "tags": tags})
    return result
