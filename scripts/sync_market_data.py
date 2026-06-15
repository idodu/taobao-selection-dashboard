from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "market_data.json"
RECOMMENDATIONS_PATH = ROOT / "data" / "recommendations.json"

BEIJING = timezone(timedelta(hours=8))
TAOBAO_ENDPOINT = "https://eco.taobao.com/router/rest"
JD_ENDPOINT = "https://api.jd.com/routerjson"
DOUYIN_ENDPOINT = "https://openapi-fxg.jinritemai.com"
PROVIDERS = ("taobao", "jd", "douyin")


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(BEIJING).isoformat()


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BEIJING)


def freshness(verified_at: object, now: datetime | None = None) -> tuple[str, float | None]:
    parsed = parse_datetime(verified_at)
    if not parsed:
        return "unverified", None
    current = now or datetime.now(BEIJING)
    age_hours = round((current - parsed.astimezone(BEIJING)).total_seconds() / 3600, 1)
    if age_hours <= 24:
        return "fresh", age_hours
    if age_hours <= 72:
        return "aging", age_hours
    return "stale", age_hours


def normalize_text(value: object) -> str:
    text = str(value or "").lower().replace("×", "*").replace("x", "*")
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def required_token_groups(product: dict) -> list[list[str]]:
    configured = product.get("marketSearch", {}).get("requiredTokenGroups")
    if isinstance(configured, list) and configured:
        return configured
    supply_groups = product.get("supply1688Search", {}).get("requiredTokenGroups")
    if isinstance(supply_groups, list) and supply_groups:
        return supply_groups
    return [[product["brand"]], [product["sku"]]]


def title_matches(title: str, groups: list[list[str]]) -> tuple[bool, list[str]]:
    normalized = normalize_text(title)
    evidence: list[str] = []
    for group in groups:
        matched = next((token for token in group if normalize_text(token) in normalized), None)
        if not matched:
            return False, evidence
        evidence.append(matched)
    return True, evidence


def positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return round(float(value), 2)
    match = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return round(float(match.group()), 2) if match else None


def positive_int(value: object) -> int | None:
    number = positive_number(value)
    return int(number) if number is not None else None


def is_http_url(value: object, hosts: tuple[str, ...] | None = None) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return not hosts or any(parsed.netloc == host or parsed.netloc.endswith(f".{host}") for host in hosts)


def absolute_url(value: object, default_scheme: str = "https") -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        return f"{default_scheme}:{text}"
    if text and "://" not in text and "." in text.split("/", 1)[0]:
        return f"{default_scheme}://{text}"
    return text


def retry_json(request_factory, attempts: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = request_factory()
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise RuntimeError(f"network error: {exc}") from exc
        time.sleep(2**attempt)
    raise RuntimeError(str(last_error or "request failed"))


def sign_top_request(params: dict[str, str], secret: str) -> str:
    canonical = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    return hmac.new(secret.encode(), canonical.encode(), hashlib.md5).hexdigest().upper()


def call_taobao(method: str, business: dict[str, object], app_key: str, secret: str) -> dict:
    params = {
        "method": method,
        "app_key": app_key,
        "timestamp": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "sign_method": "hmac",
        "simplify": "false",
        **{key: str(value) for key, value in business.items() if value is not None},
    }
    params["sign"] = sign_top_request(params, secret)
    body = urlencode(params).encode()

    def factory():
        return Request(
            TAOBAO_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )

    payload = retry_json(factory)
    if "error_response" in payload:
        error = payload["error_response"]
        raise RuntimeError(error.get("sub_msg") or error.get("msg") or "Taobao API error")
    return payload


def unwrap_taobao_items(payload: dict) -> list[dict]:
    response = next(
        (value for key, value in payload.items() if key.endswith("_response") and isinstance(value, dict)),
        payload,
    )
    result = response.get("result_list") or response.get("resultList") or response.get("results") or {}
    if isinstance(result, dict):
        result = result.get("map_data") or result.get("mapData") or result.get("items") or []
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def nested(item: dict, *paths: str) -> object:
    for path in paths:
        value: object = item
        for part in path.split("."):
            if isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if index < len(value) else None
            elif isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_taobao(item: dict) -> dict:
    title = nested(item, "item_basic_info.title", "title")
    item_id = nested(item, "item_basic_info.item_id", "item_id", "itemId")
    url = nested(item, "publish_info.click_url", "item_basic_info.item_url", "item_url")
    sale_price = positive_number(nested(item, "price_promotion_info.zk_final_price", "zk_final_price"))
    estimated = positive_number(
        nested(
            item,
            "price_promotion_info.final_promotion_price",
            "price_promotion_info.final_promotion_path_list.0.final_promotion_path_map.final_promotion_price",
            "final_promotion_price",
        )
    )
    coupon = positive_number(
        nested(item, "price_promotion_info.coupon_amount", "coupon_info.coupon_amount", "coupon_amount")
    )
    return {
        "platformItemId": str(item_id) if item_id is not None else None,
        "title": str(title or ""),
        "url": absolute_url(url),
        "listPrice": sale_price,
        "couponAmount": coupon,
        "estimatedPrice": estimated or sale_price,
        "sales30d": positive_int(nested(item, "item_basic_info.volume", "volume")),
        "reviewCount": positive_int(nested(item, "item_basic_info.ratesum", "ratesum")),
        "goodRate": positive_number(nested(item, "item_basic_info.good_rate", "good_rate")),
        "rankSignal": nested(item, "tmall_rank_info.tmall_rank_text", "tmall_rank_text"),
    }


def search_taobao(product: dict, credentials: dict[str, str]) -> dict | None:
    payload = call_taobao(
        "taobao.tbk.dg.material.optional.upgrade",
        {
            "adzone_id": credentials["adzone_id"],
            "q": product.get("marketSearch", {}).get("keywords") or f"{product['brand']} {product['name']} {product['sku']}",
            "page_size": 40,
            "page_no": 1,
            "material_id": 80309,
        },
        credentials["app_key"],
        credentials["app_secret"],
    )
    candidates = [normalize_taobao(item) for item in unwrap_taobao_items(payload)]
    return choose_exact(product, candidates, pinned_id=marketplace_ids(product).get("taobao"))


def sign_jd(params: dict[str, str], secret: str) -> str:
    canonical = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    return hashlib.md5(f"{secret}{canonical}{secret}".encode()).hexdigest().upper()


def call_jd(method: str, request_dto: dict, app_key: str, secret: str) -> dict:
    params = {
        "method": method,
        "app_key": app_key,
        "timestamp": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "param_json": json.dumps(request_dto, ensure_ascii=False, separators=(",", ":")),
    }
    params["sign"] = sign_jd(params, secret)
    url = f"{JD_ENDPOINT}?{urlencode(params)}"
    payload = retry_json(lambda: Request(url, headers={"Accept": "application/json"}))
    if payload.get("error_response"):
        raise RuntimeError(str(payload["error_response"]))
    return payload


def unwrap_jd_items(payload: dict) -> list[dict]:
    response = next(
        (value for key, value in payload.items() if key.endswith("_response") and isinstance(value, dict)),
        payload,
    )
    result = response.get("result")
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, dict):
        result = result.get("data") or result.get("items") or []
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def normalize_jd(item: dict) -> dict:
    sku_id = nested(item, "skuId", "sku_id")
    return {
        "platformItemId": str(sku_id) if sku_id is not None else None,
        "title": str(nested(item, "skuName", "sku_name") or ""),
        "url": absolute_url(
            nested(item, "materialUrl", "material_url")
            or (f"https://item.jd.com/{sku_id}.html" if sku_id else "")
        ),
        "listPrice": positive_number(nested(item, "priceInfo.price", "price_info.price")),
        "couponAmount": positive_number(nested(item, "couponInfo.couponList.0.discount", "coupon_info.coupon_list.0.discount")),
        "estimatedPrice": positive_number(
            nested(item, "priceInfo.lowestPrice", "priceInfo.lowestCouponPrice", "price_info.lowest_price")
        ),
        "sales30d": positive_int(nested(item, "inOrderCount30Days", "in_order_count_30_days")),
        "reviewCount": positive_int(nested(item, "comments", "commentCount", "comment_count")),
        "goodRate": positive_number(nested(item, "goodCommentsShare", "good_comments_share")),
        "rankSignal": nested(item, "bookInfo", "rankInfo"),
    }


def search_jd(product: dict, credentials: dict[str, str]) -> dict | None:
    pinned_id = marketplace_ids(product).get("jd")
    request = {
        "goodsReqDTO": {
            "skuIds": [int(pinned_id)] if pinned_id and pinned_id.isdigit() else None,
            "keyword": None if pinned_id else f"{product['brand']} {product['name']} {product['sku']}",
            "pageIndex": 1,
            "pageSize": 20,
        }
    }
    request["goodsReqDTO"] = {key: value for key, value in request["goodsReqDTO"].items() if value is not None}
    payload = call_jd(
        "jd.union.open.goods.query",
        request,
        credentials["app_key"],
        credentials["app_secret"],
    )
    candidates = [normalize_jd(item) for item in unwrap_jd_items(payload)]
    return choose_exact(product, candidates, pinned_id=pinned_id)


def sign_douyin(params: dict[str, str], secret: str) -> str:
    canonical = "".join(
        f"{key}{params[key]}"
        for key in sorted(params)
        if key not in {"sign", "access_token", "sign_method"}
    )
    pattern = f"{secret}{canonical}{secret}"
    return hmac.new(secret.encode(), pattern.encode(), hashlib.sha256).hexdigest()


def refresh_douyin_token(credentials: dict[str, str]) -> tuple[str, str | None]:
    method = "token.refresh"
    business = {
        "grant_type": "refresh_token",
        "refresh_token": credentials["refresh_token"],
    }
    params = {
        "app_key": credentials["client_key"],
        "method": method,
        "v": "2",
        "timestamp": str(int(time.time())),
        "param_json": json.dumps(business, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        "sign_method": "hmac-sha256",
    }
    params["sign"] = sign_douyin(params, credentials["client_secret"])
    url = f"{DOUYIN_ENDPOINT}/token/refresh?{urlencode(params)}"
    payload = retry_json(lambda: Request(url, headers={"Accept": "application/json"}))
    data = payload.get("data", payload)
    token = data.get("access_token") if isinstance(data, dict) else None
    rotated_refresh_token = data.get("refresh_token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError(str(payload.get("message") or payload.get("msg") or "Douyin token refresh failed"))
    return str(token), str(rotated_refresh_token) if rotated_refresh_token else None


def persist_rotated_douyin_token(token: str | None) -> None:
    output_path = os.getenv("DOUYIN_REFRESH_TOKEN_OUTPUT", "").strip()
    if not token or not output_path:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")


def call_douyin(method: str, business: dict, credentials: dict[str, str], access_token: str) -> dict:
    params = {
        "app_key": credentials["client_key"],
        "method": method,
        "v": "2",
        "timestamp": str(int(time.time())),
        "param_json": json.dumps(business, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        "access_token": access_token,
        "sign_method": "hmac-sha256",
    }
    params["sign"] = sign_douyin(params, credentials["client_secret"])
    url = f"{DOUYIN_ENDPOINT}/{method.replace('.', '/')}?{urlencode(params)}"
    payload = retry_json(lambda: Request(url, headers={"Accept": "application/json"}))
    if str(payload.get("code", "0")) not in {"0", "10000"}:
        raise RuntimeError(str(payload.get("message") or payload.get("msg") or payload))
    return payload


def unwrap_douyin_items(payload: dict) -> list[dict]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        data = data.get("products") or data.get("product_list") or data.get("list") or []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def normalize_douyin(item: dict) -> dict:
    product_id = nested(item, "product_id", "productId")
    price = positive_number(nested(item, "price", "min_price", "discount_price", "coupon_price"))
    return {
        "platformItemId": str(product_id) if product_id is not None else None,
        "title": str(nested(item, "product_name", "title", "name") or ""),
        "url": absolute_url(
            nested(item, "detail_url", "product_url")
            or (
                f"https://haohuo.jinritemai.com/views/product/item2?id={product_id}"
                if product_id
                else ""
            )
        ),
        "listPrice": positive_number(nested(item, "market_price", "cos_price")) or price,
        "couponAmount": positive_number(nested(item, "coupon_amount", "coupon_discount")),
        "estimatedPrice": positive_number(
            nested(item, "coupon_price", "discount_price", "price", "min_price")
        ),
        "sales30d": positive_int(nested(item, "sales30d", "sales_30d", "month_sales")),
        "reviewCount": positive_int(nested(item, "comment_num", "review_count")),
        "goodRate": positive_number(nested(item, "good_rate", "positive_rate")),
        "rankSignal": nested(item, "rank_text", "rank"),
    }


def search_douyin(product: dict, credentials: dict[str, str], access_token: str) -> dict | None:
    payload = call_douyin(
        "buyin.kolMaterialsProductsSearch",
        {
            "search_type": 0,
            "keyword": product.get("marketSearch", {}).get("keywords") or f"{product['brand']} {product['name']} {product['sku']}",
            "page": 1,
            "page_size": 20,
        },
        credentials,
        access_token,
    )
    candidates = [normalize_douyin(item) for item in unwrap_douyin_items(payload)]
    return choose_exact(product, candidates, pinned_id=marketplace_ids(product).get("douyin"))


def marketplace_ids(product: dict) -> dict[str, str | None]:
    configured = product.get("marketplaceIds") or {}
    jd_id = configured.get("jd")
    if not jd_id and "jd.com" in str(product.get("sourceUrl", "")):
        jd_id = str(product.get("sourceSkuId") or "") or None
    return {
        "taobao": str(configured["taobao"]) if configured.get("taobao") else None,
        "jd": str(jd_id) if jd_id else None,
        "douyin": str(configured["douyin"]) if configured.get("douyin") else None,
    }


def choose_exact(product: dict, candidates: list[dict], pinned_id: str | None = None) -> dict | None:
    groups = required_token_groups(product)
    exact: list[dict] = []
    for candidate in candidates:
        item_id = candidate.get("platformItemId")
        if pinned_id and str(item_id) != str(pinned_id):
            continue
        if not item_id or not is_http_url(candidate.get("url")):
            continue
        if not isinstance(candidate.get("estimatedPrice"), (int, float)) or candidate["estimatedPrice"] <= 0:
            continue
        matched, evidence = title_matches(candidate.get("title", ""), groups)
        if matched:
            candidate["matchEvidence"] = evidence
            exact.append(candidate)
    if not exact:
        return None
    exact.sort(
        key=lambda item: (
            item.get("estimatedPrice") is None,
            item.get("estimatedPrice") or float("inf"),
        )
    )
    return exact[0]


def provider_credentials(provider: str) -> dict[str, str] | None:
    if provider == "taobao":
        values = {
            "app_key": os.getenv("TAOBAO_ALLIANCE_APP_KEY", "").strip(),
            "app_secret": os.getenv("TAOBAO_ALLIANCE_APP_SECRET", "").strip(),
            "adzone_id": os.getenv("TAOBAO_ADZONE_ID", "").strip(),
        }
    elif provider == "jd":
        values = {
            "app_key": os.getenv("JD_UNION_APP_KEY", "").strip(),
            "app_secret": os.getenv("JD_UNION_APP_SECRET", "").strip(),
            "union_id": os.getenv("JD_UNION_ID", "").strip(),
        }
    else:
        values = {
            "client_key": os.getenv("DOUYIN_CLIENT_KEY", "").strip(),
            "client_secret": os.getenv("DOUYIN_CLIENT_SECRET", "").strip(),
            "refresh_token": os.getenv("DOUYIN_REFRESH_TOKEN", "").strip(),
        }
    return values if all(values.values()) else None


def blank_market_item(provider: str, product: dict, status: str, error: str | None = None) -> dict:
    query = " ".join(
        part for part in (product.get("brand"), product.get("name"), product.get("sku")) if part
    )
    urls = {
        "taobao": f"https://s.taobao.com/search?{urlencode({'q': query})}",
        "jd": product.get("sourceUrl") if "jd.com" in str(product.get("sourceUrl", "")) else "https://search.jd.com/",
        "douyin": f"https://www.douyin.com/search/{quote_plus(query)}",
    }
    return {
        "platform": provider,
        "platformItemId": marketplace_ids(product).get(provider),
        "title": None,
        "url": urls[provider],
        "listPrice": None,
        "couponAmount": None,
        "estimatedPrice": None,
        "sales30d": None,
        "reviewCount": None,
        "goodRate": None,
        "rankSignal": None,
        "matchStatus": "unverified",
        "verifiedAt": None,
        "ageHours": None,
        "freshnessStatus": "unverified",
        "sourceApi": None,
        "status": status,
        "error": error,
    }


def merge_success(provider: str, match: dict, previous: dict | None = None) -> dict:
    verified_at = now_iso()
    status, age_hours = freshness(verified_at)
    urls = {
        "taobao": "taobao.tbk.dg.material.optional.upgrade",
        "jd": "jd.union.open.goods.query",
        "douyin": "buyin.kolMaterialsProductsSearch",
    }
    return {
        "platform": provider,
        "platformItemId": match.get("platformItemId"),
        "title": match.get("title"),
        "url": match.get("url"),
        "listPrice": match.get("listPrice"),
        "couponAmount": match.get("couponAmount"),
        "estimatedPrice": match.get("estimatedPrice"),
        "sales30d": match.get("sales30d"),
        "reviewCount": match.get("reviewCount"),
        "goodRate": match.get("goodRate"),
        "rankSignal": match.get("rankSignal"),
        "matchEvidence": match.get("matchEvidence", []),
        "matchStatus": "exact",
        "verifiedAt": verified_at,
        "ageHours": age_hours,
        "freshnessStatus": status,
        "sourceApi": urls[provider],
        "status": "verified",
        "error": None,
    }


def preserve_failure(provider: str, product: dict, previous: dict | None, status: str, error: str) -> dict:
    if previous and previous.get("matchStatus") == "exact":
        _, age_hours = freshness(previous.get("verifiedAt"))
        return {
            **previous,
            "ageHours": age_hours,
            "freshnessStatus": "stale",
            "status": status,
            "error": error,
        }
    return blank_market_item(provider, product, status, error)


def preferred_ids(catalog: dict) -> set[str]:
    data = read_json(RECOMMENDATIONS_PATH, {})
    ids = {item.get("id") for item in data.get("products", [])}
    return {item for item in ids if item}


def sync_provider(provider: str, catalog: dict, cache: dict, limit: int | None = None) -> dict:
    credentials = provider_credentials(provider)
    cache.setdefault("providers", {})
    cache.setdefault("items", {})
    provider_state = cache["providers"].setdefault(provider, {})
    provider_state["attemptedAt"] = now_iso()

    if not credentials:
        provider_state.update({"status": "not-configured", "error": None})
        for product in catalog["products"]:
            cache["items"].setdefault(product["id"], {})
            previous = cache["items"][product["id"]].get(provider)
            cache["items"][product["id"]][provider] = preserve_failure(
                provider, product, previous, "not-configured", "official API credentials are not configured"
            )
        return cache

    products = [item for item in catalog["products"] if item.get("catalogStatus", "active") == "active"]
    priority = preferred_ids(catalog)
    products.sort(key=lambda item: (item["id"] not in priority, item["id"]))
    if limit:
        products = products[:limit]

    access_token = None
    if provider == "douyin":
        access_token, rotated_refresh_token = refresh_douyin_token(credentials)
        persist_rotated_douyin_token(rotated_refresh_token)
    errors: list[str] = []
    matched = 0
    for product in products:
        cache["items"].setdefault(product["id"], {})
        previous = cache["items"][product["id"]].get(provider)
        try:
            if provider == "taobao":
                result = search_taobao(product, credentials)
            elif provider == "jd":
                result = search_jd(product, credentials)
            else:
                result = search_douyin(product, credentials, access_token or "")
            if result:
                cache["items"][product["id"]][provider] = merge_success(provider, result, previous)
                matched += 1
            else:
                cache["items"][product["id"]][provider] = preserve_failure(
                    provider, product, previous, "no-exact-match", "no candidate matched brand and all specification tokens"
                )
        except Exception as exc:
            errors.append(f"{product['id']}: {exc}")
            cache["items"][product["id"]][provider] = preserve_failure(
                provider, product, previous, "error", str(exc)
            )

    provider_state.update(
        {
            "status": "partial" if errors else "ok",
            "matchedCount": matched,
            "errorCount": len(errors),
            "error": errors[0] if errors else None,
            "updatedAt": now_iso(),
        }
    )
    return cache


def refresh_freshness(cache: dict) -> None:
    for platforms in cache.get("items", {}).values():
        for item in platforms.values():
            computed, age_hours = freshness(item.get("verifiedAt"))
            item["freshnessStatus"] = (
                computed
                if item.get("matchStatus") == "exact" and item.get("status") == "verified"
                else "stale"
                if item.get("matchStatus") == "exact"
                else "unverified"
            )
            item["ageHours"] = age_hours


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync official marketplace price and sales signals.")
    parser.add_argument("--provider", choices=("all", *PROVIDERS), default="all")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    catalog = read_json(CATALOG_PATH, {"products": []})
    cache = read_json(
        OUTPUT_PATH,
        {
            "updatedAt": None,
            "schemaVersion": 1,
            "sourcePolicy": "Only official APIs and exact brand/specification matches are accepted.",
            "providers": {},
            "items": {},
        },
    )
    selected = PROVIDERS if args.provider == "all" else (args.provider,)
    for provider in selected:
        try:
            sync_provider(provider, catalog, cache, limit=args.limit)
        except Exception as exc:
            cache.setdefault("providers", {}).setdefault(provider, {})
            cache["providers"][provider].update(
                {"status": "error", "attemptedAt": now_iso(), "error": str(exc)}
            )
            print(f"MARKET_SYNC_WARNING[{provider}]: {exc}", file=os.sys.stderr)
    refresh_freshness(cache)
    cache["updatedAt"] = now_iso()
    write_json(OUTPUT_PATH, cache)
    print(
        "market sync completed: "
        + ", ".join(f"{provider}={cache['providers'].get(provider, {}).get('status', 'unknown')}" for provider in selected)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
