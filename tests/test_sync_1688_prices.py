from __future__ import annotations

import importlib.util
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
        self.assertEqual(len(products), 10)
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


if __name__ == "__main__":
    unittest.main()
