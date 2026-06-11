from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "recommendations.json"
HISTORY_PATH = ROOT / "data" / "selection_history.json"
SUPPLY_1688_PATH = ROOT / "data" / "1688_supply_prices.json"
DAILY_DIR = ROOT / "docs" / "daily"

BEIJING = timezone(timedelta(hours=8))

WEIGHTS = {
    "platformHeat": 0.30,
    "priceCompetitiveness": 0.20,
    "profitFeasibility": 0.20,
    "salesProof": 0.10,
    "repeatPurchase": 0.10,
    "differentiation": 0.05,
    "operability": 0.05,
}

RULES = {
    "summary": "总分=跨平台热度30%+价格竞争力20%+利润可行性20%+销量/评论信号10%+复购率10%+差异化空间5%+上架可操作性5%-风险扣分。1688价仅在单SKU精确匹配并核验后参与毛利计算。",
    "items": [
        {
            "name": "跨平台热度",
            "weight": "30%",
            "description": "淘宝/天猫、京东、抖音、小红书出现榜单、热词、内容种草或行业报告信号越多，得分越高。",
        },
        {
            "name": "价格竞争力",
            "weight": "20%",
            "description": "建议售价越接近同品牌同规格或近似规格的主流低价带，且不牺牲毛利，得分越高。",
        },
        {
            "name": "利润可行性",
            "weight": "20%",
            "description": "优先使用已核验的1688单SKU最低价计算；未核验时只显示建议售价*78%的成本上限，不冒充真实供货价。",
        },
        {
            "name": "销量/评论信号",
            "weight": "10%",
            "description": "公开评论量、榜单名次、销量口径、达人带货或内容互动信号越强，得分越高。",
        },
        {
            "name": "复购率",
            "weight": "10%",
            "description": "纸品、清洁剂、洗护等消耗速度快、复购周期短的 SKU 得分更高。",
        },
        {
            "name": "差异化空间",
            "weight": "5%",
            "description": "能通过组合装、赠品、标题场景、主图卖点避开官方同款硬碰的 SKU 得分更高。",
        },
        {
            "name": "上架可操作性",
            "weight": "5%",
            "description": "经销现货、标准品牌 SKU、履约稳定、资质风险低、售后可控的 SKU 得分更高。",
        },
        {
            "name": "风险扣分",
            "weight": "0-1.5分",
            "description": "控价、重货运费、液体破损、资质/功效合规、品控投诉等会扣分。",
        },
    ],
}

OPERATOR_GUIDE = [
    "看：先看今日 Top3 和热度分，只处理具体 SKU，不处理泛品类。",
    "核：核对真实供货价、运费模板、保质期、品牌授权/进货凭证。",
    "上：真实成本低于供货价参考时再上架；高于参考值则暂缓或改组合装。",
    "72小时：看曝光、点击、收藏加购；无曝光先改标题和主图。",
    "7天：看转化、退款、毛利；低效 SKU 淘汰或降为活动品。",
]

TRIAL_RULES = [
    "单 SKU 首批试款成本建议控制在 ￥200-￥500。",
    "液体和纸品重货必须先核算快递阶梯价、破损率和偏远地区策略。",
    "不具备授权、凭证、保质期可控条件的 SKU 不进入上架池。",
]


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_catalog() -> dict:
    return read_json(CATALOG_PATH, {"products": [], "avoidList": []})


def load_1688_supply() -> dict:
    return read_json(SUPPLY_1688_PATH, {"updatedAt": None, "items": {}})


def deterministic_adjustment(product_id: str, date_key: str) -> float:
    digest = hashlib.sha256(f"{product_id}:{date_key}".encode("utf-8")).hexdigest()
    bucket = int(digest[:4], 16) % 31
    return (bucket - 15) / 100


def score_product(product: dict, date_key: str, focus_category: str) -> dict:
    inputs = product["scoreInputs"]
    weighted = sum(inputs[key] * weight for key, weight in WEIGHTS.items())
    focus_bonus = 0.22 if product["category"] == focus_category else 0
    adjusted = weighted - inputs["riskPenalty"] + deterministic_adjustment(product["id"], date_key) + focus_bonus
    total = round(max(1, min(10, adjusted)), 1)

    return {
        "platformHeat": inputs["platformHeat"],
        "priceCompetitiveness": inputs["priceCompetitiveness"],
        "profitFeasibility": inputs["profitFeasibility"],
        "salesProof": inputs["salesProof"],
        "repeatPurchase": inputs["repeatPurchase"],
        "differentiation": inputs["differentiation"],
        "operability": inputs["operability"],
        "riskPenalty": inputs["riskPenalty"],
        "total": total,
    }


def gross_margin_range(prices: list[float], costs: list[float]) -> list[float]:
    margins = [round(((price - cost) / price) * 100, 1) for price, cost in zip(prices, costs)]
    return [min(margins), max(margins)]


def platform_lowest_price(platforms: list[dict]) -> float | None:
    prices = [item.get("lowPrice") for item in platforms if isinstance(item.get("lowPrice"), (int, float))]
    return min(prices) if prices else None


def build_1688_supply(product: dict, supply_cache: dict) -> dict:
    cached = supply_cache.get("items", {}).get(product["id"], {})
    query = product.get("supply1688Search", {}).get("keywords") or f"{product['brand']} {product['name']} {product['sku']}"
    search_url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote_plus(query)}"
    lowest_price = cached.get("lowestPrice")
    match_status = cached.get("matchStatus", "unverified")
    is_verified = (
        isinstance(lowest_price, (int, float))
        and lowest_price > 0
        and match_status == "exact"
        and isinstance(cached.get("offerUrl"), str)
        and "1688.com" in cached["offerUrl"]
    )

    return {
        "query": query,
        "searchUrl": search_url,
        "lowestPrice": round(lowest_price, 2) if is_verified else None,
        "moq": cached.get("moq") if is_verified else None,
        "unit": cached.get("unit", "件"),
        "matchStatus": "exact" if is_verified else "unverified",
        "matchedTitle": cached.get("matchedTitle") if is_verified else None,
        "offerId": cached.get("offerId") if is_verified else None,
        "offerUrl": cached.get("offerUrl") if is_verified else None,
        "verifiedAt": cached.get("verifiedAt") if is_verified else None,
        "source": cached.get("source") if is_verified else "1688待核验",
        "note": (
            "已核验为同品牌、同规格的单SKU最低公开阶梯价；下单前仍需确认起订量、运费和库存。"
            if is_verified
            else "尚无可审计的1688单SKU报价，不展示推测价格；可点击搜索链接人工核对。"
        ),
    }


def enrich_product(product: dict, date_key: str, focus_category: str, supply_cache: dict) -> dict:
    item = dict(product)
    suggested = item["suggestedPrice"]
    cost_ceiling = [round(value * 0.78, 1) for value in suggested]
    supply_1688 = build_1688_supply(product, supply_cache)
    verified_price = supply_1688["lowestPrice"]
    if verified_price is not None:
        actual_costs = [verified_price, verified_price]
        item["supplyCostReference"] = actual_costs
        item["costSource"] = "1688单SKU已核验最低公开阶梯价"
        item["estimatedGrossProfitRate"] = gross_margin_range(suggested, actual_costs)
        item["marginBasis"] = "1688已核验价"
    else:
        item["supplyCostReference"] = cost_ceiling
        item["costSource"] = "成本上限参考，不是1688真实报价"
        item["estimatedGrossProfitRate"] = gross_margin_range(suggested, cost_ceiling)
        item["marginBasis"] = "成本上限估算"
    item["costCeiling"] = cost_ceiling
    item["supply1688"] = supply_1688
    item["platformLowestPrice"] = platform_lowest_price(item.get("platforms", []))
    item["trialBudgetRule"] = "首批试款成本建议控制在￥200-￥500"
    item["score"] = score_product(product, date_key, focus_category)
    item.pop("scoreInputs", None)
    item.pop("supply1688Search", None)
    return item


def history_counts(history: dict, before_date: str) -> tuple[dict[str, int], set[str]]:
    dates = sorted(date for date in history.get("dates", {}) if date < before_date)
    counts: dict[str, int] = {}
    for date in dates:
        for product_id in history["dates"][date].get("productIds", []):
            counts[product_id] = counts.get(product_id, 0) + 1

    previous_ids: set[str] = set()
    if dates:
        previous_ids = set(history["dates"][dates[-1]].get("productIds", []))

    return counts, previous_ids


def apply_history_labels(products: list[dict], history: dict, date_key: str) -> None:
    counts, previous_ids = history_counts(history, date_key)
    for item in products:
        previous_count = counts.get(item["id"], 0)
        item["appearanceCount"] = previous_count + 1
        item["wasInPreviousDay"] = item["id"] in previous_ids
        item["isNew"] = previous_count == 0

        if item["wasInPreviousDay"]:
            item["statusTag"] = "昨日品"
        elif previous_count > 0:
            item["statusTag"] = "回归品"
        else:
            item["statusTag"] = "新增"

        if previous_count > 0:
            item["historyNote"] = f"累计上榜{previous_count + 1}次"
        else:
            item["historyNote"] = "首次进入每日推荐"


def update_history(history: dict, date_key: str, products: list[dict], generated_at: str) -> dict:
    next_history = dict(history)
    next_history.setdefault("dates", {})
    next_history["updatedAt"] = generated_at
    next_history["dates"][date_key] = {
        "generatedAt": generated_at,
        "productIds": [item["id"] for item in products],
    }
    return next_history


def enrich_avoid_list(items: list[dict]) -> list[dict]:
    return [
        {
            **item,
            "statusTag": "暂缓",
            "decision": "今日不建议上架",
        }
        for item in items
    ]


def generate() -> tuple[dict, dict]:
    now = datetime.now(BEIJING)
    date_key = now.strftime("%Y-%m-%d")
    catalog = load_catalog()
    supply_cache = load_1688_supply()
    history = read_json(HISTORY_PATH, {"dates": {}})
    categories = sorted({item["category"] for item in catalog["products"]})
    focus_category = categories[now.timetuple().tm_yday % len(categories)] if categories else ""

    products = [enrich_product(item, date_key, focus_category, supply_cache) for item in catalog["products"]]
    products.sort(key=lambda item: item["score"]["total"], reverse=True)
    selected = products[:10]

    for index, item in enumerate(selected, start=1):
        item["rank"] = index

    apply_history_labels(selected, history, date_key)
    generated_at = now.isoformat()
    verified_1688_count = sum(item["supply1688"]["matchStatus"] == "exact" for item in selected)

    data = {
        "generatedAt": generated_at,
        "generatedAtBeijing": now.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "date": date_key,
        "timezone": "Asia/Shanghai",
        "catalogVersion": catalog["catalogVersion"],
        "supply1688UpdatedAt": supply_cache.get("updatedAt"),
        "supply1688Provider": supply_cache.get("provider", "not-configured"),
        "supply1688VerifiedCount": verified_1688_count,
        "supply1688PendingCount": len(selected) - verified_1688_count,
        "mode": catalog.get("mode", "single-sku"),
        "selectionPolicy": "每日选出综合热度分最高的10个具体单品SKU，并将前3个标记为最建议当天上架；同时输出今日暂缓上架SKU，避免新店误踩高风险品。",
        "focusCategory": focus_category,
        "scoreRules": RULES,
        "operatorGuide": OPERATOR_GUIDE,
        "trialRules": TRIAL_RULES,
        "products": selected,
        "avoidList": enrich_avoid_list(catalog.get("avoidList", [])),
    }
    next_history = update_history(history, date_key, selected, generated_at)
    return data, next_history


def money_range(values: list[float]) -> str:
    return f"￥{values[0]}-￥{values[1]}"


def percent_range(values: list[float]) -> str:
    if len(values) == 2 and values[0] == values[1]:
        return f"{values[0]}%"
    return f"{values[0]}%-{values[1]}%"


def write_daily_markdown(data: dict) -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{data['date']}.md"
    lines = [
        f"# {data['date']} 每日单品SKU推荐",
        "",
        f"- 生成时间：{data['generatedAtBeijing']}",
        f"- 今日轮换关注：{data['focusCategory']}",
        f"- 评分规则：{data['scoreRules']['summary']}",
        "- 供货价口径：1688单SKU精确匹配并核验后显示真实最低公开阶梯价；否则仅显示成本上限参考。",
        "",
        "## 店主每日10分钟操作流程",
        "",
    ]
    lines.extend(f"- {step}" for step in data["operatorGuide"])
    lines.extend(["", "## 试款资金与履约约束", ""])
    lines.extend(f"- {rule}" for rule in data["trialRules"])
    lines.extend(
        [
            "",
            "## 今日10个候选SKU",
            "",
            "| 排名 | 上榜标签 | 品牌/SKU | 规格 | 类型 | 平台最低参考 | 建议售价 | 1688最低价 | 成本上限 | 预计毛利率 | 热度分 | 源商品 |",
            "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )

    for item in data["products"]:
        lowest = f"￥{item['platformLowestPrice']}" if item.get("platformLowestPrice") else "内容参考"
        supply_1688 = item["supply1688"]
        supply_price = (
            f"[￥{supply_1688['lowestPrice']}]({supply_1688['offerUrl']})"
            if supply_1688["lowestPrice"] is not None
            else f"[待核验]({supply_1688['searchUrl']})"
        )
        source = f"[{item['sourcePlatform']} {item['sourceSkuId']}]({item['sourceUrl']})"
        lines.append(
            "| {rank} | {status} | {brand} {name} | {sku} | {type} | {lowest} | {price} | {supply_price} | {ceiling} | {margin} | {score} | {source} |".format(
                rank=item["rank"],
                status=f"{item['statusTag']} / {item['historyNote']}",
                brand=item["brand"],
                name=item["name"],
                sku=item["sku"],
                type=item["type"],
                lowest=lowest,
                price=money_range(item["suggestedPrice"]),
                supply_price=supply_price,
                ceiling=money_range(item["costCeiling"]),
                margin=percent_range(item["estimatedGrossProfitRate"]),
                score=item["score"]["total"],
                source=source,
            )
        )

    lines.extend(["", "## 今日最建议上架", ""])
    for item in data["products"][:3]:
        lines.append(f"- {item['brand']} {item['name']}（{item['sku']}）：{item['listingAdvice']}")

    lines.extend(["", "## 今日暂缓/回避SKU", ""])
    lines.append("| 品牌/SKU | 规格 | 回避原因 | 后续观察条件 | 源商品 |")
    lines.append("|---|---|---|---|---|")
    for item in data["avoidList"]:
        source = f"[{item['sourcePlatform']} {item['sourceSkuId']}]({item['sourceUrl']})"
        lines.append(
            f"| {item['brand']} {item['name']} | {item['sku']} | {item['avoidReason']} | {item['revisitCondition']} | {source} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    data, history = generate()
    write_json(OUTPUT_PATH, data)
    write_json(HISTORY_PATH, history)
    write_daily_markdown(data)


if __name__ == "__main__":
    main()
