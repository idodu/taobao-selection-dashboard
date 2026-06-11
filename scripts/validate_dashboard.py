from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATIONS_PATH = ROOT / "data" / "recommendations.json"

PRODUCT_REQUIRED = {
    "id",
    "brand",
    "name",
    "sku",
    "image",
    "sourcePlatform",
    "sourceSkuId",
    "sourceUrl",
    "suggestedPrice",
    "supplyCostReference",
    "costCeiling",
    "costSource",
    "marginBasis",
    "supply1688",
    "estimatedGrossProfitRate",
    "platformLowestPrice",
    "platforms",
    "statusTag",
    "appearanceCount",
    "score",
}

SCORE_REQUIRED = {
    "platformHeat",
    "priceCompetitiveness",
    "profitFeasibility",
    "salesProof",
    "repeatPurchase",
    "differentiation",
    "operability",
    "riskPenalty",
    "total",
}

AVOID_REQUIRED = {
    "id",
    "brand",
    "name",
    "sku",
    "sourcePlatform",
    "sourceSkuId",
    "sourceUrl",
    "avoidReason",
    "revisitCondition",
    "decision",
}


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_money_range(values: object) -> bool:
    return (
        isinstance(values, list)
        and len(values) == 2
        and all(isinstance(value, (int, float)) and value > 0 for value in values)
        and values[0] <= values[1]
    )


def validate_product(item: dict, index: int) -> list[str]:
    errors: list[str] = []
    label = item.get("id", f"product[{index}]")
    missing = PRODUCT_REQUIRED - set(item)
    if missing:
        errors.append(f"{label}: missing fields {sorted(missing)}")
        return errors

    if any(mark in item["brand"] for mark in ("、", "/", "，", ",")):
        errors.append(f"{label}: brand must be a single brand")
    if not item["name"].strip() or not item["sku"].strip():
        errors.append(f"{label}: name and sku are required")
    if not is_http_url(item["sourceUrl"]):
        errors.append(f"{label}: sourceUrl must be http(s)")
    if not is_http_url(item["image"]):
        errors.append(f"{label}: image must be http(s)")
    if not is_money_range(item["suggestedPrice"]):
        errors.append(f"{label}: suggestedPrice must be a two-number range")
    if not is_money_range(item["supplyCostReference"]):
        errors.append(f"{label}: supplyCostReference must be a two-number range")
    if not is_money_range(item["costCeiling"]):
        errors.append(f"{label}: costCeiling must be a two-number range")
    if not is_money_range(item["estimatedGrossProfitRate"]):
        errors.append(f"{label}: estimatedGrossProfitRate must be a two-number range")
    if item["statusTag"] not in {"新增", "昨日品", "回归品"}:
        errors.append(f"{label}: invalid statusTag {item['statusTag']}")
    if not isinstance(item["appearanceCount"], int) or item["appearanceCount"] < 1:
        errors.append(f"{label}: appearanceCount must be a positive integer")

    supply_1688 = item["supply1688"]
    required_1688 = {"query", "searchUrl", "lowestPrice", "moq", "matchStatus", "offerUrl", "verifiedAt", "source", "note"}
    if not isinstance(supply_1688, dict):
        errors.append(f"{label}: supply1688 must be an object")
    else:
        missing_1688 = required_1688 - set(supply_1688)
        if missing_1688:
            errors.append(f"{label}: supply1688 missing fields {sorted(missing_1688)}")
        if not is_http_url(supply_1688.get("searchUrl", "")):
            errors.append(f"{label}: supply1688.searchUrl must be http(s)")
        if supply_1688.get("matchStatus") not in {"exact", "unverified"}:
            errors.append(f"{label}: invalid supply1688.matchStatus")
        if supply_1688.get("matchStatus") == "exact":
            if not isinstance(supply_1688.get("lowestPrice"), (int, float)) or supply_1688["lowestPrice"] <= 0:
                errors.append(f"{label}: verified 1688 lowestPrice must be positive")
            if supply_1688.get("moq") is not None and (
                not isinstance(supply_1688.get("moq"), (int, float)) or supply_1688["moq"] <= 0
            ):
                errors.append(f"{label}: verified 1688 moq must be positive or null")
            if not is_http_url(supply_1688.get("offerUrl", "")) or "1688.com" not in supply_1688["offerUrl"]:
                errors.append(f"{label}: verified 1688 offerUrl must be a 1688 URL")
            if not supply_1688.get("verifiedAt"):
                errors.append(f"{label}: verified 1688 price requires verifiedAt")
        elif any(supply_1688.get(field) is not None for field in ("lowestPrice", "moq", "offerUrl", "verifiedAt")):
            errors.append(f"{label}: unverified 1688 fields must not contain price or offer claims")

    score = item["score"]
    missing_score = SCORE_REQUIRED - set(score)
    if missing_score:
        errors.append(f"{label}: missing score fields {sorted(missing_score)}")
    for key in SCORE_REQUIRED - {"riskPenalty"}:
        value = score.get(key)
        if not isinstance(value, (int, float)) or not 1 <= value <= 10:
            errors.append(f"{label}: score.{key} must be between 1 and 10")
    risk = score.get("riskPenalty")
    if not isinstance(risk, (int, float)) or not 0 <= risk <= 1.5:
        errors.append(f"{label}: score.riskPenalty must be between 0 and 1.5")

    platforms = item["platforms"]
    if not isinstance(platforms, list) or len(platforms) < 2:
        errors.append(f"{label}: at least two platform signals are required")
    if not any(isinstance(platform.get("lowPrice"), (int, float)) for platform in platforms):
        errors.append(f"{label}: at least one platform lowPrice is required")
    for platform in platforms:
        for field in ("name", "price", "matchType", "salesSignal", "url"):
            if not platform.get(field):
                errors.append(f"{label}: platform missing {field}")
        if platform.get("url") and not is_http_url(platform["url"]):
            errors.append(f"{label}: platform url must be http(s)")

    return errors


def validate_avoid_item(item: dict, product_ids: set[str], index: int) -> list[str]:
    errors: list[str] = []
    label = item.get("id", f"avoidList[{index}]")
    missing = AVOID_REQUIRED - set(item)
    if missing:
        errors.append(f"{label}: missing fields {sorted(missing)}")
        return errors
    if label in product_ids:
        errors.append(f"{label}: avoid SKU must not duplicate a recommended SKU")
    if any(mark in item["brand"] for mark in ("、", "/", "，", ",")):
        errors.append(f"{label}: brand must be a single brand")
    if len(item["avoidReason"].strip()) < 8:
        errors.append(f"{label}: avoidReason is too vague")
    if len(item["revisitCondition"].strip()) < 8:
        errors.append(f"{label}: revisitCondition is too vague")
    if not is_http_url(item["sourceUrl"]):
        errors.append(f"{label}: sourceUrl must be http(s)")
    return errors


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    products = data.get("products")
    if not isinstance(products, list) or len(products) != 10:
        return [f"products must contain exactly 10 items, got {len(products) if isinstance(products, list) else 'non-list'}"]

    product_ids = {item.get("id", "") for item in products}
    for index, item in enumerate(products):
        errors.extend(validate_product(item, index))

    avoid_list = data.get("avoidList")
    if not isinstance(avoid_list, list) or not avoid_list:
        errors.append("avoidList must be a non-empty list")
    else:
        for index, item in enumerate(avoid_list):
            errors.extend(validate_avoid_item(item, product_ids, index))

    if not data.get("operatorGuide"):
        errors.append("operatorGuide is required")
    if not data.get("trialRules"):
        errors.append("trialRules is required")
    return errors


def main() -> int:
    data = json.loads(RECOMMENDATIONS_PATH.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"VALIDATION_ERROR: {error}", file=sys.stderr)
        return 1
    print("dashboard validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
