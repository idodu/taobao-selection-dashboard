from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_1688_prices.py"
SPEC = importlib.util.spec_from_file_location("sync_1688_prices", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class Sync1688PricesTest(unittest.TestCase):
    def test_catalog_has_strict_search_config_for_all_products(self) -> None:
        catalog_path = SCRIPT.parents[1] / "data" / "product_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        products = catalog["products"]
        self.assertGreaterEqual(len(products), 40)
        errors = [error for product in products for error in MODULE.validate_search_config(product)]
        self.assertEqual(errors, [])

    def test_top_hmac_signature(self) -> None:
        params = {"foo": "1", "bar": "2", "sign_method": "hmac"}
        self.assertEqual(
            MODULE.sign_top_request(params, "secret"),
            "58A844A53F724EC6B74C21F5373CA70F",
        )

    def test_title_requires_every_token_group(self) -> None:
        groups = [["维达", "vinda"], ["湿厕纸"], ["80片", "80抽"], ["5包", "5袋"]]
        self.assertTrue(MODULE.title_matches("维达湿厕纸80片家庭装5包", groups)[0])
        self.assertFalse(MODULE.title_matches("维达湿厕纸80片家庭装3包", groups)[0])

    def test_price_range_uses_lowest_value(self) -> None:
        self.assertEqual(MODULE.parse_lowest_price("18.80-23.50"), 18.8)
        self.assertEqual(MODULE.parse_lowest_price(12), 12.0)
        self.assertIsNone(MODULE.parse_lowest_price("面议"))

    def test_elim_price_uses_lowest_available_price_type(self) -> None:
        offer = {
            "price": 22.9,
            "promotion_price": 18.8,
            "dropship_price": 21.5,
            "retail_price": None,
        }
        self.assertEqual(MODULE.lowest_elim_price(offer), (18.8, "promotion_price"))

    def test_elim_api_key_uses_x_api_key_header(self) -> None:
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return io.BytesIO(b'{"success": true}')

            def __exit__(self, exc_type, exc, traceback):
                return False

        original = MODULE.urlopen

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        MODULE.urlopen = fake_urlopen
        try:
            payload = MODULE.post_json(
                "https://openapi.elim.asia/v1/products/search",
                {"q": "test"},
                api_key="secret-key",
            )
        finally:
            MODULE.urlopen = original
        self.assertTrue(payload["success"])
        self.assertEqual(captured["headers"]["X-api-key"], "secret-key")
        self.assertNotIn("Authorization", captured["headers"])

    def test_search_response_offer_list(self) -> None:
        payload = {
            "alibaba_open_search_daixiao_offer_get_response": {
                "is_success": 1,
                "result": {
                    "offer_list": {
                        "isv_offer_model": [
                            {
                                "id": 123,
                                "subject": "维达湿厕纸80片5包",
                                "price": "18.80-23.50",
                                "detail_url": "https://detail.1688.com/offer/123.html",
                            }
                        ]
                    }
                },
            }
        }
        result = MODULE.unwrap_search_response(payload)
        offers = MODULE.as_offer_list(result)
        self.assertEqual(len(offers), 1)
        self.assertEqual(MODULE.offer_url(offers[0]), "https://detail.1688.com/offer/123.html")

    def test_exact_search_selects_lowest_matching_offer(self) -> None:
        product = {
            "id": "sku-1",
            "supply1688Search": {
                "keywords": "维达 湿厕纸 80片 5包",
                "requiredTokenGroups": [["维达"], ["湿厕纸"], ["80片"], ["5包"]],
            },
        }
        payload = {
            "alibaba_open_search_daixiao_offer_get_response": {
                "is_success": 1,
                "result": {
                    "offer_list": {
                        "isv_offer_model": [
                            {
                                "id": 1,
                                "subject": "维达湿厕纸80片3包",
                                "price": "9.9",
                            },
                            {
                                "id": 2,
                                "subject": "维达湿厕纸80片5包",
                                "price": "19.9",
                            },
                            {
                                "id": 3,
                                "subject": "维达湿厕纸80片5包家庭装",
                                "price": "18.8",
                            },
                        ]
                    }
                },
            }
        }
        original = MODULE.call_top_api
        MODULE.call_top_api = lambda *args, **kwargs: payload
        try:
            match, attempt = MODULE.search_exact_offer(product, "key", "secret")
        finally:
            MODULE.call_top_api = original
        self.assertEqual(match["lowestPrice"], 18.8)
        self.assertEqual(match["offerId"], "3")
        self.assertEqual(attempt["exactMatches"], 2)

    def test_elim_search_selects_exact_sku_and_price_field(self) -> None:
        product = {
            "id": "sku-1",
            "supply1688Search": {
                "keywords": "维达 湿厕纸 80片 5包",
                "requiredTokenGroups": [["维达"], ["湿厕纸"], ["80片"], ["5包"]],
            },
        }
        payload = {
            "success": True,
            "items": [
                {
                    "id": 1,
                    "title": "维达湿厕纸80片3包",
                    "price": 9.9,
                    "link": "https://detail.1688.com/offer/1.html",
                },
                {
                    "id": 2,
                    "title": "维达湿厕纸80片5包",
                    "price": 20.8,
                    "promotion_price": 18.8,
                    "dropship_price": 19.9,
                    "unit": "件",
                    "link": "https://detail.1688.com/offer/2.html",
                    "sales_volume": 100,
                    "seller_type": "merchant",
                },
            ],
        }
        original = MODULE.post_json
        MODULE.post_json = lambda *args, **kwargs: payload
        try:
            match, attempt = MODULE.search_exact_elim_offer(product, api_key="token")
        finally:
            MODULE.post_json = original
        self.assertEqual(match["lowestPrice"], 18.8)
        self.assertEqual(match["priceField"], "promotion_price")
        self.assertIsNone(match["moq"])
        self.assertEqual(attempt["exactMatches"], 1)

    def test_elim_rotation_prioritizes_never_checked_then_oldest(self) -> None:
        products = [{"id": f"sku-{index}"} for index in range(1, 6)]
        cache = {
            "items": {
                "sku-1": {"verifiedAt": "2026-06-10T10:00:00+08:00"},
                "sku-2": {"verifiedAt": "2026-06-09T10:00:00+08:00"},
            },
            "attempts": {
                "sku-3": {"attemptedAt": "2026-06-08T10:00:00+08:00"},
                "sku-4": {"attemptedAt": "2026-06-11T10:00:00+08:00"},
            },
        }
        selected = MODULE.select_elim_refresh_products(products, cache, limit=3)
        self.assertEqual([item["id"] for item in selected], ["sku-5", "sku-3", "sku-2"])

    def test_elim_rotation_prioritizes_daily_shortlist(self) -> None:
        products = [{"id": f"sku-{index}"} for index in range(1, 7)]
        selected = MODULE.select_elim_refresh_products(
            products,
            {},
            limit=3,
            preferred_ids=["sku-5", "sku-2"],
        )
        self.assertEqual([item["id"] for item in selected[:2]], ["sku-5", "sku-2"])

    def test_elim_rotation_full_refresh_returns_all_products(self) -> None:
        products = [{"id": f"sku-{index}"} for index in range(1, 11)]
        selected = MODULE.select_elim_refresh_products(products, {}, limit=5, full_refresh=True)
        self.assertEqual(len(selected), 10)

    def test_elim_two_daily_runs_cover_all_ten_products(self) -> None:
        products = [
            {
                "id": f"sku-{index}",
                "supply1688Search": {
                    "keywords": f"product {index}",
                    "requiredTokenGroups": [[f"product{index}"]],
                },
            }
            for index in range(1, 11)
        ]
        catalog = {"products": products}
        original = MODULE.search_exact_elim_offer

        def fake_search(product, **credentials):
            product_number = product["id"].split("-")[-1]
            return (
                {
                    "lowestPrice": float(product_number),
                    "moq": 1,
                    "unit": "件",
                    "matchStatus": "exact",
                    "matchedTitle": f"product{product_number}",
                    "offerId": product_number,
                    "offerUrl": f"https://detail.1688.com/offer/{product_number}.html",
                    "verifiedAt": MODULE.datetime.now(MODULE.BEIJING).isoformat(),
                    "source": "test",
                },
                {"status": "matched"},
            )

        MODULE.search_exact_elim_offer = fake_search
        try:
            first = MODULE.sync_elim(
                catalog,
                api_key="token",
                existing_cache={},
                daily_limit=5,
            )
            second = MODULE.sync_elim(
                catalog,
                api_key="token",
                existing_cache=first,
                daily_limit=5,
            )
        finally:
            MODULE.search_exact_elim_offer = original
        self.assertEqual(len(first["refreshedProductIds"]), 5)
        self.assertEqual(len(second["refreshedProductIds"]), 5)
        self.assertEqual(set(first["refreshedProductIds"]).intersection(second["refreshedProductIds"]), set())
        self.assertEqual(len(second["items"]), 10)


if __name__ == "__main__":
    unittest.main()
