from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATIONS_PATH = ROOT / "data" / "recommendations.json"
MARKET_DATA_PATH = ROOT / "data" / "market_data.json"
INDEX_PATH = ROOT / "index.html"
MOTION_PATH = ROOT / "assets" / "motion.js"
GSAP_PATH = ROOT / "assets" / "vendor" / "gsap.min.js"
DESIGN_PATH = ROOT / "DESIGN.md"

PRODUCT_REQUIRED = {
    "id",
    "brand",
    "name",
    "sku",
    "image",
    "sourcePlatform",
    "sourceSkuId",
    "sourceUrl",
    "marketplaceIds",
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
    "rotation",
    "selectionReason",
    "lifecycleStatus",
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

MARKET_CODES = {"taobao", "jd", "douyin"}
MARKET_STATUSES = {"verified", "not-configured", "no-exact-match", "error", "pending"}
MARKET_FRESHNESS = {"fresh", "aging", "stale", "unverified"}

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
    required_1688 = {"query", "searchUrl", "lowestPrice", "moq", "matchStatus", "offerUrl", "verifiedAt", "ageHours", "freshnessStatus", "source", "note"}
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
        if supply_1688.get("freshnessStatus") not in {"fresh", "aging", "stale", "unverified"}:
            errors.append(f"{label}: invalid supply1688.freshnessStatus")
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

    marketplace_ids = item["marketplaceIds"]
    if not isinstance(marketplace_ids, dict) or set(marketplace_ids) != MARKET_CODES:
        errors.append(f"{label}: marketplaceIds must contain taobao, jd and douyin")

    platforms = item["platforms"]
    if not isinstance(platforms, list) or len(platforms) != 3:
        errors.append(f"{label}: exactly three official marketplace rows are required")
        platforms = []
    elif {platform.get("code") for platform in platforms} != MARKET_CODES:
        errors.append(f"{label}: platform rows must be taobao, jd and douyin")
    for platform in platforms:
        for field in (
            "name",
            "code",
            "url",
            "matchStatus",
            "freshnessStatus",
            "status",
            "price",
            "matchType",
            "salesSignal",
        ):
            if platform.get(field) in (None, ""):
                errors.append(f"{label}: platform missing {field}")
        if platform.get("url") and not is_http_url(platform["url"]):
            errors.append(f"{label}: platform url must be http(s)")
        if platform.get("matchStatus") not in {"exact", "unverified"}:
            errors.append(f"{label}: invalid platform matchStatus")
        if platform.get("freshnessStatus") not in MARKET_FRESHNESS:
            errors.append(f"{label}: invalid platform freshnessStatus")
        if platform.get("status") not in MARKET_STATUSES:
            errors.append(f"{label}: invalid platform status")
        if platform.get("matchStatus") == "exact":
            if not platform.get("platformItemId"):
                errors.append(f"{label}: verified platform requires platformItemId")
            if not platform.get("title"):
                errors.append(f"{label}: verified platform requires title")
            if not platform.get("verifiedAt") or not platform.get("sourceApi"):
                errors.append(f"{label}: verified platform requires verifiedAt and sourceApi")
            if not isinstance(platform.get("estimatedPrice"), (int, float)) or platform["estimatedPrice"] <= 0:
                errors.append(f"{label}: verified platform estimatedPrice must be positive")
        elif any(
            platform.get(field) is not None
            for field in (
                "title",
                "listPrice",
                "couponAmount",
                "estimatedPrice",
                "sales30d",
                "reviewCount",
                "goodRate",
                "rankSignal",
                "verifiedAt",
                "sourceApi",
            )
        ):
            errors.append(f"{label}: unverified platform must not contain official market claims")

    rotation = item["rotation"]
    for field in (
        "valueScore",
        "freshness",
        "dataConfidence",
        "repeatPenalty",
        "selectionBucket",
        "rotationScore",
    ):
        if field not in rotation:
            errors.append(f"{label}: rotation missing {field}")
    if item["selectionReason"] not in {"稳定跟踪款", "轮换机会款", "当日新发现", "季节机会款"}:
        errors.append(f"{label}: invalid selectionReason")

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
    if not isinstance(data.get("catalogSize"), int) or data["catalogSize"] < 40:
        errors.append("catalogSize must be at least 40")
    if not data.get("changeSummary"):
        errors.append("changeSummary is required")
    if not isinstance(data.get("trackingProducts"), list):
        errors.append("trackingProducts must be a list")
    if not isinstance(data.get("radarProducts"), list):
        errors.append("radarProducts must be a list")
    return errors


def validate_market_cache() -> list[str]:
    errors: list[str] = []
    if not MARKET_DATA_PATH.is_file():
        return ["data/market_data.json is required"]
    data = json.loads(MARKET_DATA_PATH.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        errors.append("market cache schemaVersion must be 1")
    providers = data.get("providers")
    if not isinstance(providers, dict) or set(providers) != MARKET_CODES:
        errors.append("market cache providers must contain taobao, jd and douyin")
    items = data.get("items")
    if not isinstance(items, dict):
        errors.append("market cache items must be an object")
        return errors
    for product_id, platform_map in items.items():
        if not isinstance(platform_map, dict):
            errors.append(f"{product_id}: market cache row must be an object")
            continue
        for code, item in platform_map.items():
            label = f"{product_id}/{code}"
            if code not in MARKET_CODES:
                errors.append(f"{label}: unsupported market provider")
                continue
            if item.get("matchStatus") not in {"exact", "unverified"}:
                errors.append(f"{label}: invalid matchStatus")
            if item.get("freshnessStatus") not in MARKET_FRESHNESS:
                errors.append(f"{label}: invalid freshnessStatus")
            if item.get("status") not in MARKET_STATUSES:
                errors.append(f"{label}: invalid status")
            if item.get("matchStatus") == "exact":
                if not item.get("platformItemId") or not item.get("title"):
                    errors.append(f"{label}: exact match requires platformItemId and title")
                if not is_http_url(item.get("url", "")):
                    errors.append(f"{label}: exact match requires an http(s) URL")
                if not isinstance(item.get("estimatedPrice"), (int, float)) or item["estimatedPrice"] <= 0:
                    errors.append(f"{label}: exact match requires a positive estimatedPrice")
                if not item.get("verifiedAt") or not item.get("sourceApi"):
                    errors.append(f"{label}: exact match requires verifiedAt and sourceApi")
    return errors


def validate_frontend() -> list[str]:
    errors: list[str] = []
    for path in (INDEX_PATH, MOTION_PATH, GSAP_PATH, DESIGN_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"frontend asset missing or empty: {path.relative_to(ROOT)}")
    if errors:
        return errors

    index = INDEX_PATH.read_text(encoding="utf-8")
    motion = MOTION_PATH.read_text(encoding="utf-8")
    gsap = GSAP_PATH.read_text(encoding="utf-8")
    has_gsap = "assets/vendor/gsap.min.js" in index
    has_motion = "assets/motion.js" in index
    if not has_gsap or not has_motion:
        errors.append("index.html must load local GSAP before motion.js")
    elif index.index("assets/vendor/gsap.min.js") > index.index("assets/motion.js"):
        errors.append("local GSAP must load before motion.js")
    if 'id="flowCanvas"' not in index or 'id="motionToggle"' not in index:
        errors.append("dynamic dashboard requires flowCanvas and motionToggle")
    if "cdn.jsdelivr.net" in index or "unpkg.com" in index:
        errors.append("animation runtime must not depend on a public CDN")
    for required in ("prefers-reduced-motion", "localStorage", "visibilitychange", "dashboard:ready"):
        if required not in motion:
            errors.append(f"motion.js missing required behavior: {required}")
    app = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    if "官方预估最低到手价" not in app or "30天销量" not in app:
        errors.append("frontend must label official estimated price and 30-day sales explicitly")
    if "实际成交价" in app:
        errors.append("frontend must not label alliance estimates as actual transaction prices")
    if "GSAP 3.15.0" not in gsap[:200]:
        errors.append("vendored GSAP version header is missing")
    return errors


def main() -> int:
    data = json.loads(RECOMMENDATIONS_PATH.read_text(encoding="utf-8"))
    errors = validate(data) + validate_market_cache() + validate_frontend()
    if errors:
        for error in errors:
            print(f"VALIDATION_ERROR: {error}", file=sys.stderr)
        return 1
    print("dashboard validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
