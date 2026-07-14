import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .ai_prompts import build_word_usage_prompt
from .ai_schemas import WordUsageExample, WordUsageResult
from .ai_services import AIServiceError
from .models import Card, Deck


class WordUsagePromptTests(SimpleTestCase):
    def test_prompt_includes_card_data_and_usage_requirements(self):
        prompt = build_word_usage_prompt(
            word="sich erinnern",
            translation="помнить, вспоминать",
            context="an + Akkusativ",
        )

        self.assertIn("Слово: sich erinnern", prompt)
        self.assertIn("Перевод: помнить, вспоминать", prompt)
        self.assertIn("Context: an + Akkusativ", prompt)
        self.assertIn("где слово обычно стоит в предложении", prompt)
        self.assertIn("частые сочетания", prompt)
        self.assertIn("устойчивые выражения", prompt)


class AIWordUsageViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usage-user",
            password="pass123456",
        )
        self.other_user = User.objects.create_user(
            username="other-usage-user",
            password="pass123456",
        )
        self.deck = Deck.objects.create(owner=self.user, title="German")
        self.card = Card.objects.create(
            deck=self.deck,
            question="sich erinnern",
            answer="помнить, вспоминать",
            context="an + Akkusativ",
            due=timezone.now(),
        )
        self.client.force_login(self.user)

    def _result(self):
        return WordUsageResult(
            canonical_form="sich an etwas erinnern",
            part_of_speech="возвратный глагол",
            meaning="Вспоминать кого-либо или что-либо.",
            grammar_and_position=["Управление: sich an + Akkusativ erinnern."],
            common_collocations=["sich gut an etwas erinnern — хорошо помнить"],
            fixed_expressions=[],
            examples=[
                WordUsageExample(
                    german="Ich erinnere mich an den Urlaub.",
                    translation="Я вспоминаю отпуск.",
                )
            ],
            important_notes=["Не путать с jemanden an etwas erinnern."],
        )

    @patch("study.views.explain_word_usage_with_gemini")
    def test_returns_structured_usage_guide_for_owned_card(self, mock_explain):
        mock_explain.return_value = self._result()

        response = self.client.post(
            reverse("ai_word_usage"),
            data=json.dumps({"card_id": str(self.card.id)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["result"]["canonical_form"],
            "sich an etwas erinnern",
        )
        self.assertEqual(len(payload["result"]["examples"]), 1)

        prompt = mock_explain.call_args.args[0]
        self.assertIn("Слово: sich erinnern", prompt)
        self.assertIn("Перевод: помнить, вспоминать", prompt)
        self.assertIn("Context: an + Akkusativ", prompt)

    @patch("study.views.explain_word_usage_with_gemini")
    def test_rejects_another_users_card(self, mock_explain):
        other_deck = Deck.objects.create(owner=self.other_user, title="Private")
        other_card = Card.objects.create(
            deck=other_deck,
            question="gehen",
            answer="идти",
            due=timezone.now(),
        )

        response = self.client.post(
            reverse("ai_word_usage"),
            data=json.dumps({"card_id": str(other_card.id)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        mock_explain.assert_not_called()

    def test_requires_card_id(self):
        response = self.client.post(
            reverse("ai_word_usage"),
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "card_id is required.")

    def test_rejects_invalid_json(self):
        response = self.client.post(
            reverse("ai_word_usage"),
            data="not-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid JSON request.")

    def test_rejects_non_object_json(self):
        response = self.client.post(
            reverse("ai_word_usage"),
            data=json.dumps([str(self.card.id)]),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "JSON request must be an object.",
        )

    @patch("study.views.explain_word_usage_with_gemini")
    def test_returns_bad_gateway_when_ai_service_fails(self, mock_explain):
        mock_explain.side_effect = AIServiceError("AI features are disabled.")

        response = self.client.post(
            reverse("ai_word_usage"),
            data=json.dumps({"card_id": str(self.card.id)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "AI features are disabled.")

    def test_sentence_practice_page_contains_how_to_use_button(self):
        session = self.client.session
        session["pending_sentence_task"] = {
            "card_id": str(self.card.id),
            "source_mode": "fsrs",
            "required_count": 1,
            "return_url_name": "review_card",
            "return_url_kwargs": {},
        }
        session.save()

        response = self.client.get(reverse("sentence_practice"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "How to use")
        self.assertContains(response, reverse("ai_word_usage"))
