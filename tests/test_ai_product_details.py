import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

from backend import server


class ProductDetailsEnrichmentTests(unittest.TestCase):
    def setUp(self):
        # Only OpenRouter is configured unless a test opts into Gemini explicitly.
        env = patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "GEMINI_API_KEY": "", "FREE_SEARCH": "0", "TAVILY_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        server.clear_ai_cache()
        server.ai_request_times.clear()
        server.provider_cooldown.clear()
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

    def test_prompt_token_limit_retries_with_one_web_result(self):
        first_result = {"ingredients": "Яблочный сок.", "allergens": "Не содержит."}

        with patch.object(
            server,
            "request_openrouter_product_details",
            side_effect=[server.HTTPException(402, "PROMPT_TOKEN_LIMIT"), first_result],
        ) as fetch:
            response = server.ai_product_details(self.lookup(["ingredients", "allergens"]), self.request)

        self.assertEqual(response["fields"], first_result)
        self.assertEqual(fetch.call_args_list[1].kwargs["web_results"], 1)

    def test_gemini_is_used_first_and_openrouter_fills_its_gaps(self):
        gemini_result = {"ingredients": "Яблочный сок.", "sources": [{"title": "Магазин", "url": "https://shop.example/juice"}]}
        openrouter_result = {"allergens": "Не содержит."}

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-key"}), \
             patch.object(server, "request_gemini_product_details", side_effect=[gemini_result, {"sources": []}]) as gemini, \
             patch.object(server, "request_openrouter_product_details", side_effect=[openrouter_result]) as openrouter:
            response = server.ai_product_details(self.lookup(["ingredients", "allergens"]), self.request)

        self.assertEqual(response["fields"], {"ingredients": "Яблочный сок.", "allergens": "Не содержит."})
        self.assertEqual(response["provider"], "Gemini + Google Search / OpenRouter + web search")
        self.assertEqual(gemini.call_count, 2)
        self.assertEqual(openrouter.call_args_list[0].args[1]["fields_to_find"], ["allergens"])

    def test_failed_gemini_falls_back_to_openrouter(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-key"}), \
             patch.object(server, "request_gemini_product_details", side_effect=server.HTTPException(503, "Лимит")), \
             patch.object(server, "request_openrouter_product_details", side_effect=[{"ingredients": "Сок."}]):
            response = server.ai_product_details(self.lookup(["ingredients"]), self.request)

        self.assertEqual(response["fields"], {"ingredients": "Сок."})

    def test_gemini_answer_without_search_sources_is_discarded(self):
        upstream = {"candidates": [{"content": {"parts": [{"text": '{"ingredients": "Выдуманный состав"}'}]}}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return server.json.dumps(upstream).encode()

        with patch.object(server, "urlopen", return_value=Response()):
            result = server.request_gemini_product_details("key", {"fields_to_find": ["ingredients"]})

        self.assertEqual(result, {"sources": []})

    def test_provider_without_quota_is_skipped_for_an_hour(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-key", "OPENROUTER_WEB_SEARCH": "0"}), \
             patch.object(server, "request_gemini_product_details", side_effect=server.HTTPException(503, "Лимит")) as gemini:
            server.ai_product_details(self.lookup(["ingredients"]), self.request)
            server.ai_product_details(self.lookup(["allergens"]), self.request)

        self.assertEqual(gemini.call_count, 1)

    def test_successful_result_is_cached_in_database(self):
        with patch.object(server, "request_openrouter_product_details", side_effect=[{"ingredients": "Сок."}]) as fetch:
            server.ai_product_details(self.lookup(["ingredients"]), self.request)
            cached = server.ai_product_details(self.lookup(["ingredients"]), self.request)

        self.assertEqual(cached["fields"], {"ingredients": "Сок."})
        self.assertEqual(fetch.call_count, 1)

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
