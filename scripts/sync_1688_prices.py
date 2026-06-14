from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "1688_supply_prices.json"
RECOMMENDATIONS_PATH = ROOT / "data" / "recommendations.json"
TOP_ENDPOINT = "https://eco.taobao.com/router/rest"
TOP_SEARCH_METHOD = "alibaba.open.search.daixiao.offer.get"
ELIM_SEARCH_ENDPOINT = "https://openapi.elim.asia/v1/products/search"
BEIJING = timezone(timedelta(hours=8))


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_1688_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    host = urlparse(value).netloc.lower()
    return host == "1688.com" or host.endswith(".1688.com")


def sign_top_request(params: dict[str, str], secret: str, sign_method: str = "hmac") -> str:
    canonical = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign" and params[key] != "")
    payload = canonical.encode("utf-8")
    secret_bytes = secret.encode("utf-8")
    if sign_method == "hmac":
        return hmac.new(secret_bytes, payload, hashlib.md5).hexdigest().upper()
    if sign_method == "hmac-sha256":
        return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest().upper()
    if sign_method == "md5":
        return hashlib.md5(secret_bytes + payload + secret_bytes).hexdigest().upper()
    raise ValueError(f"unsupported TOP sign method: {sign_method}")


def call_top_api(
    method: str,
    business_params: dict[str, str],
    app_key: str,
    app_secret: str,
    endpoint: str = TOP_ENDPOINT,
) -> dict:
    params = {
        "method": method,
        "app_key": app_key,
        "timestamp": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "sign_method": "hmac",
        "simplify": "false",
        **business_params,
    }
    params["sign"] = sign_top_request(params, app_secret, params["sign_method"])
    body = urlencode(params).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "User-Agent": "taobao-selection-dashboard/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "error_response" in payload:
        error = payload["error_response"]
        detail = error.get("sub_msg") or error.get("msg") or "unknown TOP API error"
        raise RuntimeError(f"{error.get('sub_code') or error.get('code')}: {detail}")
    return payload


def post_json(
    url: str,
    payload: dict,
    *,
    api_key: str | None = None,
    access_token: str | None = None,
) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "taobao-selection-dashboard/1.0",
    }
    if api_key:
        headers["x-api-key"] = api_key
    elif access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    else:
        raise ValueError("ElimAPI API key or access token is required")

    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        if exc.code == 401:
            raise RuntimeError(
                "ElimAPI rejected the credential (401). Generate an active API Key in the "
                "ElimAPI dashboard and configure it as ELIM_API_KEY."
            ) from exc
        if exc.code == 403:
            raise RuntimeError(
                "ElimAPI denied this account or API Key (403). Check account activation "
                "and subscription status in the ElimAPI dashboard."
            ) from exc
        raise RuntimeError(f"ElimAPI HTTP {exc.code}: {detail or exc.reason}") from exc


def normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = text.replace("×", "*").replace("ｘ", "x")
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def title_matches(title: str, required_groups: list[list[str]]) -> tuple[bool, list[str]]:
    normalized_title = normalize_text(title)
    evidence: list[str] = []
    for group in required_groups:
        matched = next((token for token in group if normalize_text(token) in normalized_title), None)
        if not matched:
            return False, evidence
        evidence.append(matched)
    return True, evidence


def parse_lowest_price(value: object) -> float | None:
    if isinstance(value, (int, float)) and value > 0:
        return round(float(value), 2)
    numbers = [
        float(number)
        for number in re.findall(r"(?<!\d)(?:\d{1,6}(?:\.\d{1,2})?)(?!\d)", str(value or ""))
        if float(number) > 0
    ]
    return round(min(numbers), 2) if numbers else None


def as_offer_list(result: dict) -> list[dict]:
    raw = result.get("offer_list") or result.get("offerList") or []
    if isinstance(raw, dict):
        raw = raw.get("isv_offer_model") or raw.get("isvOfferModel") or []
    if isinstance(raw, dict):
        return [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def unwrap_search_response(payload: dict) -> dict:
    response = payload.get("alibaba_open_search_daixiao_offer_get_response", payload)
    success = response.get("is_success", response.get("isSuccess"))
    if str(success).lower() not in {"1", "true"}:
        message = response.get("error_msg") or response.get("errorMsg")
        raise RuntimeError(str(message or "1688 TOP search failed"))
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def offer_url(offer: dict) -> str | None:
    value = offer.get("detail_url") or offer.get("detailUrl")
    if is_1688_url(value):
        return value
    offer_id = offer.get("id") or offer.get("offer_id") or offer.get("offerId")
    if offer_id:
        return f"https://detail.1688.com/offer/{offer_id}.html"
    return None


def search_exact_offer(product: dict, app_key: str, app_secret: str) -> tuple[dict | None, dict]:
    config = product.get("supply1688Search") or {}
    keywords = config.get("keywords")
    required_groups = config.get("requiredTokenGroups")
    if not keywords or not isinstance(required_groups, list) or not required_groups:
        raise ValueError(f"{product['id']}: supply1688Search configuration is incomplete")

    search_request = json.dumps(
        {
            "current_page": 1,
            "descend_order": False,
            "keywords": keywords,
            "page_size": 40,
            "sort_type": "price",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = call_top_api(
        TOP_SEARCH_METHOD,
        {"isv_daixiao_offer_request": search_request},
        app_key,
        app_secret,
    )
    offers = as_offer_list(unwrap_search_response(payload))
    matches: list[tuple[float, dict, list[str]]] = []
    for offer in offers:
        title = offer.get("subject") or offer.get("title") or ""
        matched, evidence = title_matches(title, required_groups)
        price = parse_lowest_price(offer.get("price"))
        url = offer_url(offer)
        if matched and price is not None and url:
            matches.append((price, offer, evidence))

    attempt = {
        "keywords": keywords,
        "returnedOffers": len(offers),
        "exactMatches": len(matches),
        "status": "matched" if matches else "no-exact-match",
    }
    if not matches:
        return None, attempt

    price, offer, evidence = min(matches, key=lambda candidate: candidate[0])
    now = datetime.now(BEIJING).isoformat()
    offer_id = offer.get("id") or offer.get("offer_id") or offer.get("offerId")
    booked_count = offer.get("booked_count") or offer.get("bookedCount")
    return (
        {
            "lowestPrice": price,
            "moq": 1,
            "unit": "件",
            "moqSource": "1688代销市场接口，按一件代发口径",
            "matchStatus": "exact",
            "matchedTitle": offer.get("subject") or offer.get("title"),
            "offerId": str(offer_id) if offer_id is not None else None,
            "offerUrl": offer_url(offer),
            "verifiedAt": now,
            "source": "1688官方TOP代销市场API",
            "priceField": "price",
            "matchEvidence": evidence,
            "bookedCount": booked_count,
        },
        attempt,
    )


def lowest_elim_price(offer: dict) -> tuple[float | None, str | None]:
    fields = ("promotion_price", "price", "whosesale_price", "dropship_price", "retail_price")
    candidates = [
        (price, field)
        for field in fields
        if (price := parse_lowest_price(offer.get(field))) is not None
    ]
    return min(candidates, default=(None, None), key=lambda item: item[0])


def search_exact_elim_offer(
    product: dict,
    *,
    api_key: str | None = None,
    access_token: str | None = None,
) -> tuple[dict | None, dict]:
    config = product.get("supply1688Search") or {}
    keywords = config.get("keywords")
    required_groups = config.get("requiredTokenGroups")
    if not keywords or not isinstance(required_groups, list) or not required_groups:
        raise ValueError(f"{product['id']}: supply1688Search configuration is incomplete")

    payload = post_json(
        ELIM_SEARCH_ENDPOINT,
        {
            "q": keywords,
            "platform": "alibaba",
            "sort": "PRICE_ASC",
            "page": 1,
            "size": 40,
        },
        api_key=api_key,
        access_token=access_token,
    )
    if not payload.get("success"):
        raise RuntimeError(payload.get("message") or "ElimAPI search failed")
    offers = [item for item in payload.get("items", []) if isinstance(item, dict)]
    matches: list[tuple[float, dict, list[str], str]] = []
    for offer in offers:
        matched, evidence = title_matches(str(offer.get("title") or ""), required_groups)
        price, price_field = lowest_elim_price(offer)
        url = offer.get("link")
        if matched and price is not None and price_field and is_1688_url(url):
            matches.append((price, offer, evidence, price_field))

    attempt = {
        "keywords": keywords,
        "returnedOffers": len(offers),
        "exactMatches": len(matches),
        "status": "matched" if matches else "no-exact-match",
    }
    if not matches:
        return None, attempt

    price, offer, evidence, price_field = min(matches, key=lambda candidate: candidate[0])
    one_piece_fields = {"dropship_price", "retail_price"}
    return (
        {
            "lowestPrice": price,
            "moq": 1 if price_field in one_piece_fields else None,
            "unit": offer.get("unit") or "件",
            "moqSource": "代发/零售价按1件口径；批发价需进入商品页确认起订量",
            "matchStatus": "exact",
            "matchedTitle": offer.get("title"),
            "offerId": str(offer.get("id")),
            "offerUrl": offer.get("link"),
            "verifiedAt": datetime.now(BEIJING).isoformat(),
            "source": "ElimAPI 1688授权搜索",
            "priceField": price_field,
            "matchEvidence": evidence,
            "bookedCount": offer.get("sales_volume"),
            "sellerType": offer.get("seller_type"),
        },
        attempt,
    )


def validate_item(product_id: str, item: dict) -> list[str]:
    errors: list[str] = []
    if item.get("matchStatus") != "exact":
        errors.append(f"{product_id}: matchStatus must be exact")
    if not isinstance(item.get("lowestPrice"), (int, float)) or item["lowestPrice"] <= 0:
        errors.append(f"{product_id}: lowestPrice must be positive")
    if item.get("moq") is not None and (
        not isinstance(item.get("moq"), (int, float)) or item["moq"] <= 0
    ):
        errors.append(f"{product_id}: moq must be positive or null")
    if not item.get("matchedTitle"):
        errors.append(f"{product_id}: matchedTitle is required")
    if not is_1688_url(item.get("offerUrl")):
        errors.append(f"{product_id}: offerUrl must be a 1688 URL")
    if not item.get("verifiedAt"):
        errors.append(f"{product_id}: verifiedAt is required")
    return errors


def validate_search_config(product: dict) -> list[str]:
    errors: list[str] = []
    config = product.get("supply1688Search")
    if not isinstance(config, dict):
        return [f"{product.get('id', 'unknown')}: supply1688Search is required"]
    if not str(config.get("keywords", "")).strip():
        errors.append(f"{product['id']}: supply1688Search.keywords is required")
    groups = config.get("requiredTokenGroups")
    if not isinstance(groups, list) or not groups:
        errors.append(f"{product['id']}: requiredTokenGroups must be a non-empty list")
    elif any(not isinstance(group, list) or not group or not all(str(token).strip() for token in group) for group in groups):
        errors.append(f"{product['id']}: every required token group must contain non-empty alternatives")
    return errors


def load_feed(url: str, token: str | None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "taobao-selection-dashboard/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def sync_feed(feed_url: str, token: str | None, catalog_ids: set[str]) -> dict:
    feed = load_feed(feed_url, token)
    items = feed.get("items")
    if not isinstance(items, dict):
        raise ValueError("1688 feed must contain an items object")

    cleaned: dict[str, dict] = {}
    errors: list[str] = []
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
        raise ValueError("\n".join(errors))
    return {
        "updatedAt": feed.get("updatedAt") or datetime.now(BEIJING).isoformat(),
        "provider": "authorized-feed",
        "sourcePolicy": "仅保存同品牌、同规格、单SKU精确匹配且带1688商品链接的已核验报价。",
        "items": cleaned,
        "attempts": {},
    }


def sync_top(catalog: dict, app_key: str, app_secret: str) -> dict:
    items: dict[str, dict] = {}
    attempts: dict[str, dict] = {}
    api_errors: list[str] = []
    config_errors = [
        error
        for product in catalog.get("products", [])
        for error in validate_search_config(product)
    ]
    if config_errors:
        raise ValueError("invalid 1688 search configuration:\n" + "\n".join(config_errors))

    for product in catalog.get("products", []):
        try:
            match, attempt = search_exact_offer(product, app_key, app_secret)
            attempts[product["id"]] = attempt
            if match:
                items[product["id"]] = match
        except Exception as exc:
            attempts[product["id"]] = {"status": "api-error", "error": str(exc)}
            api_errors.append(f"{product['id']}: {exc}")

    if api_errors:
        raise RuntimeError("1688 TOP API refresh failed:\n" + "\n".join(api_errors))
    return {
        "updatedAt": datetime.now(BEIJING).isoformat(),
        "provider": "1688-top-api",
        "sourcePolicy": "官方代销市场按价格升序搜索；仅保留标题同时匹配品牌和全部规格词组的单SKU最低价。",
        "items": items,
        "attempts": attempts,
    }


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BEIJING)


def select_elim_refresh_products(
    products: list[dict],
    existing_cache: dict,
    limit: int,
    full_refresh: bool = False,
    preferred_ids: list[str] | None = None,
) -> list[dict]:
    if full_refresh:
        return products
    attempts = existing_cache.get("attempts", {})
    items = existing_cache.get("items", {})
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def last_checked(product: dict) -> datetime:
        product_id = product["id"]
        attempt_time = parse_datetime(attempts.get(product_id, {}).get("attemptedAt"))
        verified_time = parse_datetime(items.get(product_id, {}).get("verifiedAt"))
        value = attempt_time or verified_time or fallback
        return value.astimezone(timezone.utc)

    preferred_order = {
        product_id: index for index, product_id in enumerate(preferred_ids or [])
    }

    return sorted(
        products,
        key=lambda product: (
            0 if product["id"] in preferred_order else 1,
            preferred_order.get(product["id"], len(preferred_order)),
            last_checked(product),
            product["id"],
        ),
    )[:limit]


def sync_elim(
    catalog: dict,
    *,
    api_key: str | None = None,
    access_token: str | None = None,
    existing_cache: dict | None = None,
    daily_limit: int = 5,
    full_refresh: bool = False,
    preferred_ids: list[str] | None = None,
) -> dict:
    existing_cache = existing_cache or {}
    items: dict[str, dict] = dict(existing_cache.get("items", {}))
    attempts: dict[str, dict] = dict(existing_cache.get("attempts", {}))
    api_errors: list[str] = []
    config_errors = [
        error
        for product in catalog.get("products", [])
        for error in validate_search_config(product)
    ]
    if config_errors:
        raise ValueError("invalid 1688 search configuration:\n" + "\n".join(config_errors))

    products = catalog.get("products", [])
    selected = select_elim_refresh_products(
        products,
        existing_cache,
        daily_limit,
        full_refresh,
        preferred_ids=preferred_ids,
    )
    refreshed_ids: list[str] = []
    for product in selected:
        attempted_at = datetime.now(BEIJING).isoformat()
        try:
            match, attempt = search_exact_elim_offer(
                product,
                api_key=api_key,
                access_token=access_token,
            )
            attempt["attemptedAt"] = attempted_at
            attempts[product["id"]] = attempt
            if match:
                items[product["id"]] = match
            else:
                items.pop(product["id"], None)
            refreshed_ids.append(product["id"])
        except Exception as exc:
            attempts[product["id"]] = {
                "status": "api-error",
                "error": str(exc),
                "attemptedAt": attempted_at,
            }
            api_errors.append(f"{product['id']}: {exc}")
            if "401" in str(exc) or "403" in str(exc):
                break

    if api_errors:
        raise RuntimeError("ElimAPI 1688 refresh failed:\n" + "\n".join(api_errors))
    return {
        "updatedAt": datetime.now(BEIJING).isoformat(),
        "provider": "elim-api",
        "sourcePolicy": "ElimAPI按价格升序搜索1688；每日优先刷新最久未检查的SKU，仅保留标题同时匹配品牌和全部规格词组的最低公开价。",
        "items": items,
        "attempts": attempts,
        "refreshedProductIds": refreshed_ids,
        "dailyRequestLimit": len(selected),
        "fullRefresh": full_refresh,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync audited single-SKU 1688 prices.")
    parser.add_argument("--allow-missing", action="store_true", help="Keep the existing cache when credentials are absent.")
    parser.add_argument("--provider", choices=("auto", "top", "elim", "feed"), default="auto")
    parser.add_argument("--full-refresh", action="store_true", help="Refresh every SKU instead of the daily Elim quota.")
    parser.add_argument("--elim-daily-limit", type=int, default=None, help="Maximum Elim searches in this run.")
    args = parser.parse_args()

    catalog = read_json(CATALOG_PATH)
    catalog_ids = {item["id"] for item in catalog.get("products", [])}
    app_key = os.getenv("TOP_APP_KEY", "").strip()
    app_secret = os.getenv("TOP_APP_SECRET", "").strip()
    elim_token = os.getenv("ELIM_API_KEY", "").strip()
    elim_access_token = os.getenv("ELIM_ACCESS_TOKEN", "").strip()
    elim_daily_limit = args.elim_daily_limit or int(os.getenv("ELIM_DAILY_LIMIT", "5"))
    feed_url = os.getenv("SUPPLY_1688_FEED_URL", "").strip()
    existing_cache = read_json(OUTPUT_PATH, {"items": {}, "attempts": {}})
    recommendations = read_json(RECOMMENDATIONS_PATH, {"products": [], "radarProducts": []})
    preferred_ids = [
        item["id"]
        for item in (
            recommendations.get("products", [])[:3]
            + recommendations.get("radarProducts", [])[:2]
        )
        if isinstance(item, dict) and item.get("id")
    ]

    try:
        use_top = args.provider == "top" or (args.provider == "auto" and app_key and app_secret)
        use_elim = args.provider == "elim" or (
            args.provider == "auto" and (elim_token or elim_access_token) and not use_top
        )
        use_feed = args.provider == "feed" or (
            args.provider == "auto" and feed_url and not use_top and not use_elim
        )
        if use_top:
            if not app_key or not app_secret:
                raise ValueError("TOP_APP_KEY and TOP_APP_SECRET are both required")
            output = sync_top(catalog, app_key, app_secret)
        elif use_elim:
            if not elim_token and not elim_access_token:
                raise ValueError("ELIM_API_KEY or ELIM_ACCESS_TOKEN is required")
            if elim_daily_limit < 1:
                raise ValueError("ELIM_DAILY_LIMIT must be at least 1")
            output = sync_elim(
                catalog,
                api_key=elim_token or None,
                access_token=elim_access_token or None,
                existing_cache=existing_cache,
                daily_limit=elim_daily_limit,
                full_refresh=args.full_refresh,
                preferred_ids=preferred_ids,
            )
        elif use_feed:
            if not feed_url:
                raise ValueError("SUPPLY_1688_FEED_URL is required")
            output = sync_feed(feed_url, os.getenv("SUPPLY_1688_FEED_TOKEN"), catalog_ids)
        else:
            message = "1688 credentials are not configured; keeping the existing audited cache."
            print(message)
            return 0 if args.allow_missing else 2

        write_json(OUTPUT_PATH, output)
        print(f"synced {len(output['items'])} audited 1688 SKU prices via {output['provider']}")
        return 0
    except Exception as exc:
        print(f"1688_SYNC_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
