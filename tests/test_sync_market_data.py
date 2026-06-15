from __future__ import annotations

import importlib.util
import hashlib
import hmac
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_market_data.py"
SPEC = importlib.util.spec_from_file_location("sync_market_data", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def sample_product() -> dict:
    return {
        "id": "vinda-80x5",
        "brand": "维达",
        "name": "维达湿厕纸家庭装",
        "sku": "80片*5包",
        "sourceSkuId": "123",
        "sourceUrl": "https://item.jd.com/123.html",
        "catalogStatus": "active",
        "marketplaceIds": {"taobao": None, "jd": "123", "douyin": None},
        "marketSearch": {
            "keywords": "维达 湿厕纸 80片 5包",
            "requiredTokenGroups": [
                ["维达", "Vinda"],
                ["湿厕纸"],
                ["80片", "80抽"],
                ["5包", "5袋"],
            ],
        },
    }


class SyncMarketDataTest(unittest.TestCase):
    def test_exact_match_requires_every_brand_and_specification_group(self) -> None:
        product = sample_product()
        candidates = [
            {
                "platformItemId": "1",
                "title": "维达湿厕纸80片3包",
                "url": "https://item.taobao.com/item.htm?id=1",
                "estimatedPrice": 19.9,
            },
            {
                "platformItemId": "2",
                "title": "维达 Vinda 湿厕纸80抽5袋家庭装",
                "url": "https://item.taobao.com/item.htm?id=2",
                "estimatedPrice": 24.9,
            },
        ]
        match = MODULE.choose_exact(product, candidates)
        self.assertIsNotNone(match)
        self.assertEqual(match["platformItemId"], "2")
        self.assertEqual(match["matchEvidence"], ["维达", "湿厕纸", "80抽", "5袋"])

    def test_exact_match_rejects_missing_id_url_or_price(self) -> None:
        product = sample_product()
        base = {"title": "维达湿厕纸80片5包"}
        candidates = [
            {**base, "platformItemId": None, "url": "https://item.taobao.com/1", "estimatedPrice": 20},
            {**base, "platformItemId": "2", "url": "", "estimatedPrice": 20},
            {**base, "platformItemId": "3", "url": "https://item.taobao.com/3", "estimatedPrice": 0},
        ]
        self.assertIsNone(MODULE.choose_exact(product, candidates))

    def test_freshness_thresholds_are_24_and_72_hours(self) -> None:
        now = datetime(2026, 6, 15, 10, tzinfo=MODULE.BEIJING)
        self.assertEqual(MODULE.freshness((now - timedelta(hours=24)).isoformat(), now)[0], "fresh")
        self.assertEqual(MODULE.freshness((now - timedelta(hours=25)).isoformat(), now)[0], "aging")
        self.assertEqual(MODULE.freshness((now - timedelta(hours=73)).isoformat(), now)[0], "stale")

    def test_normalizers_keep_official_price_sales_and_review_fields_separate(self) -> None:
        taobao = MODULE.normalize_taobao(
            {
                "item_basic_info": {
                    "item_id": "10",
                    "title": "维达湿厕纸80片5包",
                    "volume": "321",
                    "ratesum": "4567",
                },
                "publish_info": {"click_url": "//uland.taobao.com/item/10"},
                "price_promotion_info": {
                    "zk_final_price": "29.90",
                    "final_promotion_price": "24.90",
                    "coupon_amount": "5",
                },
            }
        )
        self.assertEqual(taobao["estimatedPrice"], 24.9)
        self.assertEqual(taobao["sales30d"], 321)
        self.assertEqual(taobao["reviewCount"], 4567)
        self.assertTrue(taobao["url"].startswith("https://"))

        jd = MODULE.normalize_jd(
            {
                "skuId": 123,
                "skuName": "维达湿厕纸80片5包",
                "priceInfo": {"price": 29.9, "lowestPrice": 23.9},
                "couponInfo": {"couponList": [{"discount": 6}]},
                "inOrderCount30Days": 88,
                "comments": 990,
            }
        )
        self.assertEqual(jd["estimatedPrice"], 23.9)
        self.assertEqual(jd["couponAmount"], 6)
        self.assertEqual(jd["sales30d"], 88)
        self.assertEqual(jd["reviewCount"], 990)

    def test_douyin_uses_hmac_sha256_and_coupon_price(self) -> None:
        params = {
            "app_key": "app",
            "method": "buyin.kolMaterialsProductsSearch",
            "param_json": '{"keyword":"维达"}',
            "timestamp": "1",
            "v": "2",
            "access_token": "ignored",
            "sign_method": "hmac-sha256",
        }
        canonical = "".join(
            f"{key}{params[key]}"
            for key in sorted(params)
            if key not in {"sign", "access_token", "sign_method"}
        )
        expected = hmac.new(
            b"secret",
            f"secret{canonical}secret".encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(MODULE.sign_douyin(params, "secret"), expected)
        normalized = MODULE.normalize_douyin(
            {
                "product_id": "99",
                "product_name": "维达湿厕纸80片5包",
                "coupon_price": "24.9",
                "sales": "1234",
            }
        )
        self.assertEqual(normalized["estimatedPrice"], 24.9)
        self.assertIsNone(normalized["sales30d"])

    def test_provider_without_credentials_marks_every_sku_pending(self) -> None:
        product = sample_product()
        catalog = {"products": [product]}
        cache = {"providers": {}, "items": {}}
        with patch.dict(os.environ, {}, clear=True):
            MODULE.sync_provider("taobao", catalog, cache)
        row = cache["items"][product["id"]]["taobao"]
        self.assertEqual(cache["providers"]["taobao"]["status"], "not-configured")
        self.assertEqual(row["matchStatus"], "unverified")
        self.assertIsNone(row["estimatedPrice"])

    def test_rotated_douyin_token_is_only_written_to_configured_sink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory) / "rotated-token"
            with patch.dict(os.environ, {"DOUYIN_REFRESH_TOKEN_OUTPUT": str(sink)}, clear=True):
                MODULE.persist_rotated_douyin_token("new-secret")
            self.assertEqual(sink.read_text(encoding="utf-8"), "new-secret")

    def test_refresh_failure_preserves_last_exact_data_and_marks_age(self) -> None:
        product = sample_product()
        previous = {
            "platform": "jd",
            "platformItemId": "123",
            "title": "维达湿厕纸80片5包",
            "url": "https://item.jd.com/123.html",
            "estimatedPrice": 22.9,
            "matchStatus": "exact",
            "verifiedAt": (datetime.now(MODULE.BEIJING) - timedelta(hours=80)).isoformat(),
            "sourceApi": "jd.union.open.goods.query",
        }
        row = MODULE.preserve_failure("jd", product, previous, "error", "timeout")
        self.assertEqual(row["estimatedPrice"], 22.9)
        self.assertEqual(row["freshnessStatus"], "stale")
        self.assertEqual(row["status"], "error")

    def test_refresh_failure_invalidates_even_recent_cached_data(self) -> None:
        product = sample_product()
        previous = {
            "platform": "jd",
            "platformItemId": "123",
            "title": "维达湿厕纸80片5包",
            "url": "https://item.jd.com/123.html",
            "estimatedPrice": 22.9,
            "matchStatus": "exact",
            "verifiedAt": datetime.now(MODULE.BEIJING).isoformat(),
            "sourceApi": "jd.union.open.goods.query",
            "status": "verified",
        }
        row = MODULE.preserve_failure("jd", product, previous, "error", "timeout")
        self.assertEqual(row["freshnessStatus"], "stale")


if __name__ == "__main__":
    unittest.main()
