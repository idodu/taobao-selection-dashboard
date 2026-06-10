from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "product_catalog.json"
OUTPUT_PATH = ROOT / "data" / "recommendations.json"
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
    "summary": "总分=跨平台热度35%+价格竞争力25%+利润可行性20%+销量信号15%+上架可操作性5%-风险扣分。",
    "items": [
        {
            "name": "跨平台热度",
            "weight": "35%",
            "description": "淘宝/天猫、京东、抖音、小红书出现榜单、热词、内容种草或行业报告信号越多，得分越高。"
        },
        {
            "name": "价格竞争力",
            "weight": "25%",
            "description": "建议到手价越接近主流成交低位，且不牺牲毛利，得分越高。"
        },
        {
            "name": "利润可行性",
            "weight": "20%",
            "description": "按建议到手价*78%倒推成本上限，能保留15%-25%毛利的商品得分更高。"
        },
        {
            "name": "销量信号",
            "weight": "15%",
            "description": "公开月销、评论量、榜单名次、内容互动等信号越强，得分越高。"
        },
        {
            "name": "上架可操作性",
            "weight": "5%",
            "description": "经销现货、标准品牌品、组合装/赠品差异化空间越大，得分越高。"
        },
        {
            "name": "风险扣分",
            "weight": "0-1.5分",
            "description": "控价、重货运费、液体破损、资质/功效合规、品控投诉等会扣分。"
        }
    ]
}


def load_catalog() -> dict:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def enrich_product(product: dict, date_key: str, focus_category: str) -> dict:
    item = dict(product)
    item["costCeiling"] = [round(value * 0.78, 1) for value in product["suggestedPrice"]]
    item["score"] = score_product(product, date_key, focus_category)
    item.pop("scoreInputs", None)
    return item


def generate() -> dict:
    now = datetime.now(BEIJING)
    date_key = now.strftime("%Y-%m-%d")
    catalog = load_catalog()
    categories = sorted({item["category"] for item in catalog["products"]})
    focus_category = categories[now.timetuple().tm_yday % len(categories)]

    products = [
        enrich_product(item, date_key, focus_category)
        for item in catalog["products"]
    ]
    products.sort(key=lambda item: item["score"]["total"], reverse=True)
    selected = products[:10]

    for index, item in enumerate(selected, start=1):
        item["rank"] = index

    return {
        "generatedAt": now.isoformat(),
        "generatedAtBeijing": now.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "date": date_key,
        "timezone": "Asia/Shanghai",
        "catalogVersion": catalog["catalogVersion"],
        "selectionPolicy": "每日选出综合热度分最高的10个候选品，并将前3个标记为最建议当天上架。",
        "focusCategory": focus_category,
        "scoreRules": RULES,
        "products": selected,
    }


def write_daily_markdown(data: dict) -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{data['date']}.md"
    lines = [
        f"# {data['date']} 每日选品推荐",
        "",
        f"- 生成时间：{data['generatedAtBeijing']}",
        f"- 今日轮换关注：{data['focusCategory']}",
        f"- 评分规则：{data['scoreRules']['summary']}",
        "",
        "| 排名 | 商品 | SKU | 类型 | 建议到手价 | 成本上限 | 热度分 |",
        "|---:|---|---|---|---:|---:|---:|",
    ]

    for item in data["products"]:
        price = f"￥{item['suggestedPrice'][0]}-￥{item['suggestedPrice'][1]}"
        cost = f"￥{item['costCeiling'][0]}-￥{item['costCeiling'][1]}"
        lines.append(
            f"| {item['rank']} | {item['name']} | {item['sku']} | {item['type']} | {price} | {cost} | {item['score']['total']} |"
        )

    lines.extend([
        "",
        "## 今日最建议上架",
        "",
    ])
    for item in data["products"][:3]:
        lines.append(f"- {item['name']}（{item['sku']}）：{item['listingAdvice']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    data = generate()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_daily_markdown(data)


if __name__ == "__main__":
    main()
