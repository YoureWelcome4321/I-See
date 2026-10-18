import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

from backend import server


class ProductDetailsEnrichmentTests(unittest.TestCase):
    def setUp(self):
        server.ai_enrichment_cache.clear()
        server.ai_request_times.clear()
        self.request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    def lookup(self, missing):
        return server.ProductLookupData(
            name="Сок J7 яблочный",
            brand="J7",
            missing=missing,
            known_data={"quantity": "970 мл"},
        )

    def test_match_reason_does_not_count_as_nutrition(self):
        first_result = {
            "ingredients": "Яблочный сок, антиокислитель: аскорбиновая кислота.",
            "nutrition": None,
            "match_reason": "Источник указал пищевую ценность на 100 мл.",
            "confidence": "high",
        }
        second_result = {"nutrition": "На 100 мл: 45 ккал; белки 0 г; жиры 0 г; углеводы 11 г."}

        with patch.object(server, "request_openrouter_product_details", side_effect=[first_result, second_result]) as fetch:
            response = server.ai_product_details(self.lookup(["ingredients", "nutrition"]), self.request)

        self.assertEqual(response["fields"]["ingredients"], first_result["ingredients"])
        self.assertEqual(response["fields"]["nutrition"], second_result["nutrition"])
        self.assertEqual(response["missing"], [])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[1].args[1]["fields_to_find"], ["nutrition"])

    def test_status_text_is_not_accepted_as_nutrition(self):
        first_result = {"ingredients": "Яблочный сок.", "nutrition": "Пищевая ценность есть в источнике."}
        second_result = {"nutrition": "Не указано"}

        with patch.object(server, "request_openrouter_product_details", side_effect=[first_result, second_result]):
            response = server.ai_product_details(self.lookup(["ingredients", "nutrition"]), self.request)

        self.assertEqual(response["fields"], {"ingredients": "Яблочный сок."})
        self.assertEqual(response["missing"], ["nutrition"])

    def test_partial_result_survives_failed_targeted_retry(self):
        first_result = {"ingredients": "Яблочный сок."}

        with patch.object(
            server,
            "request_openrouter_product_details",
            side_effect=[first_result, server.HTTPException(503, "Временно недоступно")],
        ):
            response = server.ai_product_details(self.lookup(["ingredients", "nutrition"]), self.request)

        self.assertTrue(response["matched"])
        self.assertEqual(response["fields"], {"ingredients": "Яблочный сок."})
        self.assertEqual(response["missing"], ["nutrition"])

    def test_validation_filters_unknown_and_unrequested_values(self):
        result = {
            "ingredients": "Сок.",
            "nutrition": "На 100 мл: 42 ккал.",
            "unexpected": "Не должен попасть в ответ",
        }

        self.assertEqual(
            server.validated_enrichment_fields(result, ["ingredients"]),
            {"ingredients": "Сок."},
        )
        self.assertIsNone(server.valid_enrichment_value("nutrition", "Пищевая ценность есть в источнике."))
        self.assertEqual(server.valid_enrichment_value("nutrition", "Энергия: 42 ккал"), "Энергия: 42 ккал")


if __name__ == "__main__":
    unittest.main()
