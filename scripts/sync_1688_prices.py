from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "1688_supply_prices.json"
BEIJING = timezone(timedelta(hours=8))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_1688_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    host = urlparse(value).netloc.lower()
    return host == "1688.com" or host.endswith(".1688.com")


def validate_item(product_id: str, item: dict) -> list[str]:
    errors: list[str] = []
    if item.get("matchStatus") != "exact":
        errors.append(f"{product_id}: matchStatus must be exact")
    if not isinstance(item.get("lowestPrice"), (int, float)) or item["lowestPrice"] <= 0:
        errors.append(f"{product_id}: lowestPrice must be positive")
    if not isinstance(item.get("moq"), (int, float)) or item["moq"] <= 0:
        errors.append(f"{product_id}: moq must be positive")
    if not item.get("matchedTitle"):
        errors.append(f"{product_id}: matchedTitle is required")
    if not is_1688_url(item.get("offerUrl")):
        errors.append(f"{product_id}: offerUrl must be a 1688 URL")
    if not item.get("verifiedAt"):
        errors.append(f"{product_id}: verifiedAt is required")
    return errors


def load_feed(url: str, token: str | None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "taobao-selection-dashboard/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync audited single-SKU 1688 prices from an authorized JSON feed.")
    parser.add_argument("--allow-missing", action="store_true", help="Exit successfully when no feed URL is configured.")
    args = parser.parse_args()

    feed_url = os.getenv("SUPPLY_1688_FEED_URL", "").strip()
    if not feed_url:
        message = "SUPPLY_1688_FEED_URL is not configured; keeping the existing audited cache."
        print(message)
        return 0 if args.allow_missing else 2

    feed = load_feed(feed_url, os.getenv("SUPPLY_1688_FEED_TOKEN"))
    catalog_ids = {item["id"] for item in read_json(CATALOG_PATH).get("products", [])}
    items = feed.get("items")
    if not isinstance(items, dict):
        print("1688 feed must contain an items object", file=sys.stderr)
        return 1

    errors: list[str] = []
    cleaned: dict[str, dict] = {}
    for product_id, item in items.items():
        if product_id not in catalog_ids:
            continue
        if not isinstance(item, dict):
            errors.append(f"{product_id}: item must be an object")
            continue
        errors.extend(validate_item(product_id, item))
        cleaned[product_id] = {
            **item,
            "lowestPrice": round(float(item.get("lowestPrice", 0)), 2),
            "source": item.get("source", "authorized-1688-feed"),
        }

    if errors:
        for error in errors:
            print(f"1688_FEED_ERROR: {error}", file=sys.stderr)
        return 1

    output = {
        "updatedAt": feed.get("updatedAt") or datetime.now(BEIJING).isoformat(),
        "sourcePolicy": "仅保存同品牌、同规格、单SKU精确匹配且带1688商品链接的已核验报价。",
        "items": cleaned,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"synced {len(cleaned)} audited 1688 SKU prices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
