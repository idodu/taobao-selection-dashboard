from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "recommendations.json"
HISTORY_PATH = ROOT / "data" / "selection_history.json"
DAILY_DIR = ROOT / "docs" / "daily"

BEIJING = timezone(timedelta(hours=8))

WEIGHTS = {
    "platformHeat": 0.35,
    "priceCompetitiveness": 0.25,
    "profitFeasibility": 0.20,
    "salesProof": 0.15,
    "operability": 0.05,
}

RULES = {
    "summary": "总分=跨平台热度35%+价格竞争力25%+利润可行性20%+销量/评论信号15%+上架可操作性5%-风险扣分。供货价参考暂按建议售价*78%倒推，待替换真实成本。",
    "items": [
        {
            "name": "跨平台热度",
            "weight": "35%",
            "description": "淘宝/天猫、京东、抖音、小红书出现榜单、热词、内容种草或行业报告信号越多，得分越高。",
        },
        {
            "name": "价格竞争力",
            "weight": "25%",
            "description": "建议售价越接近同品牌同规格或近似规格的主流低价带，且不牺牲毛利，得分越高。",
        },
        {
            "name": "利润可行性",
            "weight": "20%",
            "description": "供货价参考按建议售价*78%倒推，预留约22%毛利空间；真实供货价低于该参考值时优先上架。",
        },
        {
            "name": "销量/评论信号",
            "weight": "15%",
            "description": "公开评论量、榜单名次、销量口径、达人带货或内容互动信号越强，得分越高。",
        },
        {
            "name": "上架可操作性",
            "weight": "5%",
            "description": "经销现货、标准品牌SKU、组合装/赠品差异空间越大，得分越高。",
        },
        {
            "name": "风险扣分",
            "weight": "0-1.5分",
            "description": "控价、重货运费、液体破损、资质/功效合规、品控投诉等会扣分。",
        },
    ],
}


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_catalog() -> dict:
    return read_json(CATALOG_PATH, {"products": []})


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
        "operability": inputs["operability"],
        "riskPenalty": inputs["riskPenalty"],
        "total": total,
    }


def gross_margin_range(prices: list[float], costs: list[float]) -> list[float]:
    return [round(((price - cost) / price) * 100, 1) for price, cost in zip(prices, costs)]


def platform_lowest_price(platforms: list[dict]) -> float | None:
    prices = [item.get("lowPrice") for item in platforms if isinstance(item.get("lowPrice"), (int, float))]
    return min(prices) if prices else None


def enrich_product(product: dict, date_key: str, focus_category: str) -> dict:
    item = dict(product)
    suggested = item["suggestedPrice"]
    supply_reference = [round(value * 0.78, 1) for value in suggested]
    item["supplyCostReference"] = supply_reference
    item["costCeiling"] = supply_reference
    item["costSource"] = "成本上限代替，待替换真实供货价"
    item["estimatedGrossProfitRate"] = gross_margin_range(suggested, supply_reference)
    item["platformLowestPrice"] = platform_lowest_price(item.get("platforms", []))
    item["score"] = score_product(product, date_key, focus_category)
    item.pop("scoreInputs", None)
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


def generate() -> tuple[dict, dict]:
    now = datetime.now(BEIJING)
    date_key = now.strftime("%Y-%m-%d")
    catalog = load_catalog()
    history = read_json(HISTORY_PATH, {"dates": {}})
    categories = sorted({item["category"] for item in catalog["products"]})
    focus_category = categories[now.timetuple().tm_yday % len(categories)] if categories else ""

    products = [enrich_product(item, date_key, focus_category) for item in catalog["products"]]
    products.sort(key=lambda item: item["score"]["total"], reverse=True)
    selected = products[:10]

    for index, item in enumerate(selected, start=1):
        item["rank"] = index

    apply_history_labels(selected, history, date_key)
    generated_at = now.isoformat()

    data = {
        "generatedAt": generated_at,
        "generatedAtBeijing": now.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "date": date_key,
        "timezone": "Asia/Shanghai",
        "catalogVersion": catalog["catalogVersion"],
        "mode": catalog.get("mode", "single-sku"),
        "selectionPolicy": "每日选出综合热度分最高的10个具体单品SKU，并将前3个标记为最建议当天上架。",
        "focusCategory": focus_category,
        "scoreRules": RULES,
        "products": selected,
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
        "- 供货价口径：当前按建议售价*78%倒推成本上限，后续替换为真实供货价。",
        "",
        "| 排名 | 上榜标签 | 品牌/SKU | 规格 | 类型 | 平台最低参考 | 建议售价 | 供货价参考 | 预计毛利率 | 热度分 | 源商品 |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]

    for item in data["products"]:
        lowest = f"￥{item['platformLowestPrice']}" if item.get("platformLowestPrice") else "内容参考"
        source = f"[{item['sourcePlatform']} {item['sourceSkuId']}]({item['sourceUrl']})"
        lines.append(
            "| {rank} | {status} | {brand} {name} | {sku} | {type} | {lowest} | {price} | {cost} | {margin} | {score} | {source} |".format(
                rank=item["rank"],
                status=f"{item['statusTag']} / {item['historyNote']}",
                brand=item["brand"],
                name=item["name"],
                sku=item["sku"],
                type=item["type"],
                lowest=lowest,
                price=money_range(item["suggestedPrice"]),
                cost=money_range(item["supplyCostReference"]),
                margin=percent_range(item["estimatedGrossProfitRate"]),
                score=item["score"]["total"],
                source=source,
            )
        )

    lines.extend(["", "## 今日最建议上架", ""])
    for item in data["products"][:3]:
        lines.append(f"- {item['brand']} {item['name']}（{item['sku']}）：{item['listingAdvice']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    data, history = generate()
    write_json(OUTPUT_PATH, data)
    write_json(HISTORY_PATH, history)
    write_daily_markdown(data)


if __name__ == "__main__":
    main()
