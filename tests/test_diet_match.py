import os
import unittest
from unittest.mock import patch

from backend import diet_match


class RuleMatchTests(unittest.TestCase):
    def test_milk_covers_dairy_words(self):
        for text in ("Кефир: нормализованное молоко", "Круассан: мука, сливочное масло", "Вафли: сгущённое молоко", "Творог зернистый"):
            self.assertEqual(diet_match.rule_matches(["молоко"], text), ["молоко"], text)

    def test_no_false_positives_inside_other_words(self):
        self.assertEqual(diet_match.rule_matches(["молоко"], "Перец молотый"), [])
        self.assertEqual(diet_match.rule_matches(["мёд"], "Медленно томлёное мясо"), [])
        self.assertEqual(diet_match.rule_matches(["лук"], "Лукошко ягод"), [])

    def test_typed_word_matches_its_forms(self):
        self.assertEqual(diet_match.rule_matches(["мёд"], "Блины с мёдом"), ["мёд"])
        self.assertEqual(diet_match.rule_matches(["орехи"], "Салат с орехами"), ["орехи"])
        self.assertEqual(diet_match.rule_matches(["рыба"], "Рыбный суп"), ["рыба"])


class CheckTests(unittest.TestCase):
    def test_without_ai_only_rules_answer(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            results, state = diet_match.check(["молоко"], [("a", "Кефир"), ("b", "Сок яблочный")], lambda key: None, lambda key, value: None)
        self.assertEqual(results, {"a": ["молоко"], "b": []})
        self.assertEqual(state, "off")

    def test_cached_ai_answer_adds_to_rules(self):
        cache = {diet_match._cache_key(["молоко"], "Соус бешамель"): {"matches": ["молоко"]}}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            results, state = diet_match.check(["молоко"], [("a", "Соус бешамель")], cache.get, cache.__setitem__)
        self.assertEqual(results, {"a": ["молоко"]})
        self.assertEqual(state, "done")


if __name__ == "__main__":
    unittest.main()
