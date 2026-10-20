import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import free_search

PAGE = (
    "<html><head><script>var x = 1;</script></head><body>"
    "<h1>Сок J7 яблочный 0,97 л</h1><p>Штрихкод: 4601512005307</p>"
    "<p>Состав: яблочный сок, антиокислитель аскорбиновая кислота (Е300).</p>"
    "<p>Пищевая ценность на 100 мл: углеводы 10,5 г. Энергетическая ценность 45 ккал.</p>"
    "<p>Условия хранения: от 0 до 25 °С.</p></body></html>"
)


def product(barcode="4601512005307", brand="J7", name="Сок яблочный"):
    return SimpleNamespace(barcode=barcode, brand=brand, name=name)


class RuleExtractionTests(unittest.TestCase):
    def test_reads_label_fields_without_ai(self):
        found = free_search.rule_extract(free_search.page_text(PAGE))

        self.assertEqual(found["ingredients"], "яблочный сок, антиокислитель аскорбиновая кислота (Е300)")
        self.assertIn("45 ккал", found["nutrition"])
        self.assertEqual(found["additives"], "E300")

    def test_ingredients_label_variants(self):
        sour_cream = "В составе только нормализованные сливки. Состав: сливки нормализованные, закваска. Срок годности 14 суток"
        noodles = "Состав лапши: мука пшеничная в/с, масло пальмовое, соль. Условия хранения: сухо"
        juice = "Состав: яблочный сок, персиковое пюре. Нежный персик и ароматное яблоко дополняют друг друга"

        self.assertEqual(free_search.rule_extract(sour_cream)["ingredients"], "сливки нормализованные, закваска")
        self.assertEqual(free_search.rule_extract(noodles)["ingredients"], "мука пшеничная в/с, масло пальмовое, соль")
        self.assertEqual(free_search.rule_extract(juice)["ingredients"], "яблочный сок, персиковое пюре")

    def test_cut_off_ingredients_are_rejected(self):
        self.assertFalse(free_search.complete_ingredients("пшеничная мука в/с"))
        self.assertTrue(free_search.complete_ingredients("сливки, закваска"))

    def test_english_allergens_are_shown_in_russian(self):
        self.assertEqual(free_search.russian_allergens("milk"), "молоко")
        self.assertEqual(free_search.russian_allergens("en:milk, en:soybeans, sesame-seeds"), "молоко, соя, кунжут")
        self.assertEqual(free_search.russian_allergens("Milk, Peanuts; may contain hazelnuts"), "молоко, арахис; может содержать фундук")
        self.assertEqual(free_search.russian_allergens("По составу: молоко"), "По составу: молоко")

    def test_list_answer_from_model_is_joined(self):
        self.assertEqual(free_search.as_text(["сахар", "какао тертое"]), "сахар, какао тертое")

    def test_allergens_are_derived_from_ingredients(self):
        derived = free_search.allergens_from_ingredients("пшеничная мука, молоко сухое, соль. Может содержать следы арахиса")

        self.assertTrue(derived.startswith("молоко, глютен"))
        self.assertIn("Может содержать следы арахиса", derived)

    def test_page_must_name_the_product(self):
        def page(title, text=""):
            return {"title": title, "text": text}

        self.assertTrue(free_search.is_about_product(page("Магазин", "… 4601512005307 …"), "4601512005307", "J7", "Сок"))
        self.assertTrue(free_search.is_about_product(page("Сок J7 яблоко зелёное 0,97 л"), "", "J7", "сок джей севен смотка яблоко"))
        self.assertFalse(free_search.is_about_product(page("Сок Добрый яблочный"), "4601512005307", "J7", "Сок яблочный"))

    def test_another_product_type_of_the_same_brand_is_rejected(self):
        nectar = {"title": "Нектар Джей Севен персик-яблоко 0,97 л", "text": "Состав: яблочный сок, персиковое пюре"}

        self.assertFalse(free_search.is_about_product(nectar, "4601512005307", "J7", "сок джей севен смотка яблоко"))

    def test_barcode_in_related_goods_does_not_override_product_type(self):
        nectar = {"title": "Нектар Джей Севен персик-яблоко 0,9 л", "text": "Нектар J7. С этим товаром покупают: Сок J7 яблоко 4601512005307"}

        self.assertFalse(free_search.is_about_product(nectar, "4601512005307", "J7", "сок джей севен смотка яблоко"))

    def test_trace_warning_stays_and_shop_text_goes(self):
        value = free_search.clean_ingredients("Нормализованные сливки, закваска. Может содержать следы молока. Рекомендации О товаре")

        self.assertEqual(value, "Нормализованные сливки, закваска. Может содержать следы молока")

    def test_other_flavour_of_the_same_brand_is_rejected(self):
        related = {"title": "Сок J7 апельсин 0,97 л", "text": "Сок J7 апельсин. Похожие товары: Сок J7 яблоко"}

        self.assertFalse(free_search.is_about_product(related, "4601512005307", "J7", "Сок J7 яблочный"))

    def test_other_flavour_in_title_is_rejected_even_with_barcode(self):
        page = {"title": "Сок J7 (Джей севен) 970мл яблоко-персик с мякотью", "text": "… 4601512005307 …"}

        self.assertFalse(free_search.is_about_product(page, "4601512005307", "J7", "сок джей севен смотка яблоко"))
        self.assertTrue(free_search.is_about_product({"title": "Сок J7 яблоко-персик", "text": ""}, "", "J7", "Сок J7 яблоко-персик"))

    def test_brand_spelling_with_hyphen_matches(self):
        page = {"title": 'Сок J-7 "Яблоко зеленое", 0,97 л', "text": ""}

        self.assertTrue(free_search.is_about_product(page, "", "J7", "сок джей севен смотка яблоко"))

    def test_title_without_maker_brand_needs_every_word(self):
        name = "Драже M&M с арахисом и молочным шоколадом"
        full = {"title": "Драже M&Ms с арахисом и молочным шоколадом 45 г", "text": ""}
        partial = {"title": "Драже M&Ms с шоколадом", "text": ""}

        self.assertTrue(free_search.is_about_product(full, "4607065000790", "Mars", name))
        self.assertFalse(free_search.is_about_product(partial, "4607065000790", "Mars", name))

    def test_short_tavily_snippet_is_downloaded_in_full(self):
        payload = free_search.json.dumps({"results": [
            {"url": "https://a.example", "title": "A", "raw_content": "коротко"},
            {"url": "https://b.example", "title": "B", "raw_content": "Состав: " + "сахар, " * 100},
        ]})
        with patch.object(free_search, "_http", return_value=(200, payload)):
            results = free_search.search_tavily("q", "key")

        self.assertIsNone(results[0]["text"])
        self.assertTrue(results[1]["text"].startswith("Состав"))

    def test_search_query_uses_name_and_brand(self):
        self.assertEqual(free_search.search_query(product(name="Сок «яблочный»")), "J7 Сок яблочный состав")
        self.assertEqual(free_search.search_query(product(name="Сок J7 яблочный")), "Сок J7 яблочный состав")
        self.assertEqual(free_search.search_query(product(brand="", name="")), "4601512005307 состав")

    def test_only_the_first_listed_brand_is_used(self):
        with patch.object(free_search, "run_search", return_value=[]) as search:
            free_search.lookup(product(brand="J7, Мултон", name="Сок яблочный"), ["ingredients"])

        self.assertEqual(search.call_args_list[0].args[0], "J7 Сок яблочный состав")


class GroundingTests(unittest.TestCase):
    def test_value_must_come_from_page_text(self):
        source = "Состав: яблочный сок, аскорбиновая кислота. Энергетическая ценность 45 ккал."

        self.assertTrue(free_search.grounded("ingredients", "яблочный сок, аскорбиновая кислота", source))
        self.assertFalse(free_search.grounded("ingredients", "яблочный сок, сахар, лимонная кислота, ароматизатор", source))
        self.assertTrue(free_search.grounded("nutrition", "45 ккал", source))
        self.assertFalse(free_search.grounded("nutrition", "52 ккал", source))


class DuckDuckGoTests(unittest.TestCase):
    def setUp(self):
        free_search._ddg_blocked_until = 0.0
        self.addCleanup(setattr, free_search, "_ddg_blocked_until", 0.0)

    def test_bot_check_pauses_further_requests(self):
        with patch.object(free_search, "_http", return_value=(202, "<html>anomaly detected</html>")) as http:
            with self.assertRaises(free_search.SearchUnavailable):
                free_search.search_duckduckgo("4601512005307")
            with self.assertRaises(free_search.SearchUnavailable):
                free_search.search_duckduckgo("4601512005307")

        self.assertEqual(http.call_count, 1)

    def test_result_links_are_unwrapped(self):
        body = '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fshop.example%2Fjuice&amp;rut=1">Сок <b>J7</b></a>'
        with patch.object(free_search, "_http", return_value=(200, body)):
            links = free_search.search_duckduckgo("4601512005307")

        self.assertEqual(links, [{"url": "https://shop.example/juice", "title": "Сок J7", "text": None}])


class LookupTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"OPENROUTER_API_KEY": "key", "TAVILY_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        free_search._ddg_blocked_until = 0.0

    queries = None

    def network(self, model_answer):
        self.queries = []
        def fake_http(url, data=None, headers=None, timeout=10, limit=1_500_000):
            if "duckduckgo" in url:
                self.queries.append(free_search.unquote(data.decode()))
                return 200, '<a class="result__a" href="https://shop.example/juice">Сок J7 яблочный</a><a class="result__a" href="https://other.example/x">Сок Добрый яблочный</a>'
            if "openrouter" in url:
                return 200, free_search.json.dumps({"choices": [{"message": {"content": model_answer}}]})
            if url == "https://shop.example/juice":
                return 200, PAGE
            return 200, "<p>Сок Добрый яблочный. Состав: сок, сахар, вода.</p>"
        return patch.object(free_search, "_http", side_effect=fake_http)

    def test_model_values_are_kept_only_when_found_on_the_page(self):
        answer = '{"ingredients": "яблочный сок, антиокислитель аскорбиновая кислота (Е300)", "allergens": "орехи, соя"}'
        with self.network(answer):
            result = free_search.lookup(product(), ["ingredients", "allergens", "nutrition"])

        self.assertEqual(result["ingredients"], "яблочный сок, антиокислитель аскорбиновая кислота (Е300)")
        self.assertNotIn("allergens", result)
        self.assertIn("45 ккал", result["nutrition"])
        self.assertEqual([source["url"] for source in result["sources"]], ["https://shop.example/juice"])
        self.assertTrue(self.queries[0].startswith("q=J7+Сок+яблочный+состав"))

    def test_blocked_shop_page_is_read_through_tavily(self):
        result = {"url": "https://shop.example/juice", "title": "Сок J7 яблочный 0,97 л", "text": None, "snippet_hint": "Сок J7"}

        def fake_http(url, data=None, headers=None, timeout=10, limit=1_500_000):
            if url == "https://api.tavily.com/extract":
                return 200, free_search.json.dumps({"results": [{"url": result["url"], "raw_content": "Состав: яблочный сок, аскорбиновая кислота. Срок годности 1 год"}]})
            raise free_search.HTTPError(url, 403, "Forbidden", None, None)

        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-key", "OPENROUTER_API_KEY": ""}), \
             patch.object(free_search, "run_search", return_value=[result]), \
             patch.object(free_search, "_http", side_effect=fake_http):
            found = free_search.lookup(product(), ["ingredients"])

        self.assertEqual(found["ingredients"], "яблочный сок, аскорбиновая кислота")
        self.assertEqual([source["url"] for source in found["sources"]], ["https://shop.example/juice"])

    def test_name_results_survive_a_blocked_barcode_query(self):
        calls = []

        def search(query):
            calls.append(query)
            if len(calls) > 1:
                raise free_search.SearchUnavailable("капча")
            return [{"url": "https://shop.example/juice", "title": "Сок J7 яблочный", "text": free_search.page_text(PAGE).replace("4601512005307", "")}]

        with patch.object(free_search, "run_search", side_effect=search), patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            result = free_search.lookup(product(), ["ingredients"])

        self.assertEqual(calls, ["J7 Сок яблочный состав", "4601512005307 состав"])
        self.assertEqual(result["ingredients"], "яблочный сок, антиокислитель аскорбиновая кислота (Е300)")

    def test_rules_take_over_when_free_models_fail(self):
        with self.network("Я подумал и не нашёл JSON"):
            result = free_search.lookup(product(), ["ingredients"])

        self.assertEqual(result["ingredients"], "яблочный сок, антиокислитель аскорбиновая кислота (Е300)")


if __name__ == "__main__":
    unittest.main()
