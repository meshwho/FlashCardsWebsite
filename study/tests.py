from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Card, Deck
from .sentence_logic import sentence_count_for_rating, should_require_sentences


class SentenceLogicTests(TestCase):
    def test_sentence_count_for_rating(self):
        self.assertEqual(sentence_count_for_rating(4), 0)
        self.assertEqual(sentence_count_for_rating(3), 1)
        self.assertEqual(sentence_count_for_rating(2), 2)
        self.assertEqual(sentence_count_for_rating(1), 3)

    def test_should_require_sentences_uses_any_struggle_signal(self):
        self.assertTrue(
            should_require_sentences(
                had_wrong_attempt=True,
                had_hint=False,
                rating_value=3,
                feature_enabled=True,
            )
        )
        self.assertTrue(
            should_require_sentences(
                had_wrong_attempt=False,
                had_hint=True,
                rating_value=2,
                feature_enabled=True,
            )
        )
        self.assertTrue(
            should_require_sentences(
                had_wrong_attempt=False,
                had_hint=False,
                had_dont_know=True,
                rating_value=1,
                feature_enabled=True,
            )
        )

        self.assertFalse(
            should_require_sentences(
                had_wrong_attempt=False,
                had_hint=False,
                rating_value=4,
                feature_enabled=True,
            )
        )
        self.assertFalse(
            should_require_sentences(
                had_wrong_attempt=True,
                had_hint=True,
                rating_value=1,
                feature_enabled=False,
            )
        )


class SentenceFlowViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass123456")
        self.client.force_login(self.user)
        self.deck = Deck.objects.create(owner=self.user, title="Deck")

    def _create_card(self, *, question="Haus", answer="house", has_article=False):
        return Card.objects.create(
            deck=self.deck,
            question=question,
            answer=answer,
            has_article=has_article,
            due=timezone.now(),
        )

    @patch("study.views.get_next_due_card_for_user")
    @patch("study.views.FSRSService.review_card")
    def test_review_dont_know_creates_sentence_task(self, mock_review_card, mock_next_due_card):
        card = self._create_card()
        mock_next_due_card.return_value = card
        mock_review_card.return_value = SimpleNamespace(card=card)

        response = self.client.post(
            reverse("review_card"),
            {
                "action": "dont_know",
                "hints_used": "0",
                "wrong_attempts_count": "0",
                "user_answer": "",
            },
        )

        self.assertRedirects(response, reverse("sentence_practice"))
        pending = self.client.session.get("pending_sentence_task")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["source_mode"], "fsrs")
        self.assertEqual(pending["required_count"], 3)
        self.assertEqual(pending["card_id"], str(card.id))

    def test_typing_dont_know_with_toggle_on_creates_sentence_task(self):
        card = self._create_card(question="Wasser", answer="water")
        session = self.client.session
        session["deck_practice_session"] = {
            "deck_id": str(self.deck.id),
            "mode": "typing",
            "card_ids": [str(card.id)],
            "directions": ["forward"],
            "current_index": 0,
            "summary": [],
            "require_sentences_after_mistake": True,
        }
        session.save()

        response = self.client.post(
            reverse("deck_practice_typing", kwargs={"deck_id": self.deck.id}),
            {
                "action": "dont_know",
                "hints_used": "0",
                "wrong_attempts_count": "0",
                "user_answer": "",
            },
        )

        self.assertRedirects(response, reverse("sentence_practice"))
        updated_session = self.client.session["deck_practice_session"]
        self.assertEqual(updated_session["current_index"], 1)
        self.assertEqual(len(updated_session["summary"]), 1)
        self.assertEqual(updated_session["summary"][0]["rating_label"], "Again")

        pending = self.client.session.get("pending_sentence_task")
        self.assertEqual(pending["source_mode"], "typing_practice")
        self.assertEqual(pending["required_count"], 3)

    def test_typing_toggle_off_never_creates_sentence_task(self):
        card = self._create_card(question="Wasser", answer="water")
        session = self.client.session
        session["deck_practice_session"] = {
            "deck_id": str(self.deck.id),
            "mode": "typing",
            "card_ids": [str(card.id)],
            "directions": ["forward"],
            "current_index": 0,
            "summary": [],
            "require_sentences_after_mistake": False,
        }
        session.save()

        response = self.client.post(
            reverse("deck_practice_typing", kwargs={"deck_id": self.deck.id}),
            {
                "action": "check",
                "user_answer": "water",
                "hints_used": "1",
                "wrong_attempts_count": "1",
            },
        )

        self.assertRedirects(
            response,
            reverse("deck_practice_done", kwargs={"deck_id": self.deck.id}),
        )
        self.assertIsNone(self.client.session.get("pending_sentence_task"))

    def test_article_mode_toggle_on_wrong_then_correct_creates_sentence_task(self):
        card = self._create_card(question="die Katze", answer="cat", has_article=True)
        session = self.client.session
        session["deck_practice_session"] = {
            "deck_id": str(self.deck.id),
            "mode": "articles",
            "card_ids": [str(card.id)],
            "directions": ["forward"],
            "current_index": 0,
            "summary": [],
            "require_sentences_after_mistake": True,
        }
        session.save()

        wrong_response = self.client.post(
            reverse("deck_practice_articles", kwargs={"deck_id": self.deck.id}),
            {
                "wrong_attempts_count": "0",
                "chosen_article": "der",
            },
        )
        self.assertEqual(wrong_response.status_code, 200)

        response = self.client.post(
            reverse("deck_practice_articles", kwargs={"deck_id": self.deck.id}),
            {
                "wrong_attempts_count": "1",
                "chosen_article": "die",
            },
        )

        self.assertRedirects(response, reverse("sentence_practice"))
        updated_session = self.client.session["deck_practice_session"]
        self.assertEqual(updated_session["current_index"], 1)
        self.assertEqual(len(updated_session["summary"]), 1)
        self.assertEqual(updated_session["summary"][0]["mistakes_count"], 1)
        self.assertEqual(updated_session["summary"][0]["rating_label"], "Hard")

        pending = self.client.session.get("pending_sentence_task")
        self.assertEqual(pending["source_mode"], "article_practice")
        self.assertEqual(pending["required_count"], 2)
