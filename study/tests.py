from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .active_fsrs_service import ActiveFSRSService
from .models import (
    ActiveUseAttempt,
    Card,
    CardActiveState,
    Deck,
    ReviewLog,
    UserActivePracticeSettings,
)
from .forms import ReviewScheduleForm
from .practice_session import get_practice_summary
from .sentence_logic import sentence_count_for_rating, should_require_sentences
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

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

    def test_sentence_practice_rejects_invalid_required_count_in_session(self):
        card = self._create_card(question="Wasser", answer="water")
        session = self.client.session
        session["pending_sentence_task"] = {
            "card_id": str(card.id),
            "source_mode": "typing_practice",
            "rating_value": 1,
            "required_count": "not-a-number",
            "return_url_name": "deck_practice_typing",
            "return_url_kwargs": {"deck_id": str(self.deck.id)},
        }
        session.save()

        response = self.client.get(reverse("sentence_practice"))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertNotIn("pending_sentence_task", self.client.session)

    def test_sentence_practice_rejects_unapproved_return_target(self):
        card = self._create_card(question="Wasser", answer="water")
        session = self.client.session
        session["pending_sentence_task"] = {
            "card_id": str(card.id),
            "source_mode": "typing_practice",
            "rating_value": 1,
            "required_count": 2,
            "return_url_name": "https://evil.example/",
            "return_url_kwargs": {},
        }
        session.save()

        response = self.client.get(reverse("sentence_practice"))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertNotIn("pending_sentence_task", self.client.session)

    def test_sentence_practice_rejects_missing_card_id(self):
        session = self.client.session
        session["pending_sentence_task"] = {
            "source_mode": "typing_practice",
            "rating_value": 1,
            "required_count": 2,
            "return_url_name": "deck_practice_typing",
            "return_url_kwargs": {"deck_id": str(self.deck.id)},
        }
        session.save()

        response = self.client.get(reverse("sentence_practice"))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertNotIn("pending_sentence_task", self.client.session)

    def test_sentence_practice_rejects_unexpected_return_kwargs(self):
        card = self._create_card(question="Wasser", answer="water")
        session = self.client.session
        session["pending_sentence_task"] = {
            "card_id": str(card.id),
            "source_mode": "typing_practice",
            "rating_value": 1,
            "required_count": 2,
            "return_url_name": "deck_practice_typing",
            "return_url_kwargs": {"deck_id": str(self.deck.id), "extra": "1"},
        }
        session.save()

        response = self.client.get(reverse("sentence_practice"))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertNotIn("pending_sentence_task", self.client.session)


class DashboardValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="scheduler", password="pass123456")
        self.client.force_login(self.user)

    def test_dashboard_ignores_non_numeric_reviews_per_day(self):
        response = self.client.post(
            reverse("dashboard"),
            {
                "timezone": "Europe/Berlin",
                "is_active": "on",
                "reviews_per_day": "abc",
                "slot_0_time": "09:00",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "1",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-time": "09:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard"))


class PracticeOptionsSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="practice-user", password="pass123456")
        self.client.force_login(self.user)
        self.deck = Deck.objects.create(owner=self.user, title="Practice deck")
        self.card = Card.objects.create(
            deck=self.deck,
            question="Wasser",
            answer="water",
            due=timezone.now(),
        )

    def test_setup_treats_string_false_as_false_for_checkbox(self):
        response = self.client.post(
            reverse("deck_practice_setup", kwargs={"deck_id": self.deck.id}),
            {
                "mode": "typing",
                "require_sentences_after_mistake": "false",
            },
        )

        self.assertEqual(response.status_code, 302)
        session = self.client.session["deck_practice_session"]
        self.assertFalse(session["require_sentences_after_mistake"])


class PracticeSessionSummaryTests(TestCase):
    def test_typing_summary_counts_only_explicit_boolean_results(self):
        request = SimpleNamespace(session={})
        request.session["deck_practice_session"] = {
            "mode": "typing",
            "summary": [
                {"rating_label": "Easy", "is_correct": True},
                {"rating_label": "Again", "is_correct": False},
                {"rating_label": "Good"},
            ],
        }

        summary = get_practice_summary(request)
        self.assertEqual(summary["correct_count"], 1)
        self.assertEqual(summary["wrong_count"], 1)


class ReviewScheduleFormTests(TestCase):
    def test_timezone_must_be_valid_iana_name(self):
        form = ReviewScheduleForm(
            data={
                "timezone": "Not/A_Timezone",
                "is_active": True,
                "reviews_per_day": 3,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

class DeckDeleteViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="deck-owner",
            password="pass123456",
        )
        self.other_user = User.objects.create_user(
            username="other-user",
            password="pass123456",
        )

        self.deck = Deck.objects.create(
            owner=self.user,
            title="Deck to delete",
        )
        self.card = Card.objects.create(
            deck=self.deck,
            question="Haus",
            answer="house",
            due=timezone.now(),
        )

        self.client.force_login(self.user)

    def test_user_can_delete_own_deck(self):
        response = self.client.post(
            reverse("deck_delete", kwargs={"deck_id": self.deck.id})
        )

        self.assertRedirects(response, reverse("deck_list"))
        self.assertFalse(Deck.objects.filter(id=self.deck.id).exists())
        self.assertFalse(Card.objects.filter(id=self.card.id).exists())

    def test_delete_requires_post(self):
        response = self.client.get(
            reverse("deck_delete", kwargs={"deck_id": self.deck.id})
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Deck.objects.filter(id=self.deck.id).exists())

    def test_user_cannot_delete_another_users_deck(self):
        other_deck = Deck.objects.create(
            owner=self.other_user,
            title="Other user's deck",
        )

        response = self.client.post(
            reverse("deck_delete", kwargs={"deck_id": other_deck.id})
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Deck.objects.filter(id=other_deck.id).exists())


class ActiveUseLayerModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="active_test_user",
            email="active_test_user@example.com",
            password="test-password-123",
        )
        self.deck = Deck.objects.create(
            owner=self.user,
            title="German test deck",
        )

    def test_card_active_state_is_created_for_new_card(self):
        card = Card.objects.create(
            deck=self.deck,
            question="die Entscheidung",
            answer="решение",
            has_article=True,
        )

        self.assertTrue(hasattr(card, "active_state"))
        self.assertEqual(card.active_state.stage, CardActiveState.STAGE_PASSIVE)

    def test_saving_card_again_does_not_create_duplicate_active_state(self):
        card = Card.objects.create(
            deck=self.deck,
            question="das Haus",
            answer="дом",
            has_article=True,
        )

        card.question = "das Haus"
        card.save()

        active_state_count = CardActiveState.objects.filter(card=card).count()

        self.assertEqual(active_state_count, 1)

    def test_user_active_practice_settings_are_created_for_new_user(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="settings_test_user",
            email="settings_test_user@example.com",
            password="test-password-123",
        )

        self.assertTrue(hasattr(user, "active_practice_settings"))
        self.assertEqual(user.active_practice_settings.current_level, "A2-B1")
        self.assertEqual(user.active_practice_settings.target_level, "C1")
        self.assertEqual(user.active_practice_settings.active_tasks_per_day, 5)

    def test_initialize_active_use_command_creates_missing_records(self):
        card = Card.objects.create(
            deck=self.deck,
            question="die Möglichkeit",
            answer="возможность",
            has_article=True,
        )

        # Simulate old data without active state.
        CardActiveState.objects.filter(card=card).delete()
        UserActivePracticeSettings.objects.filter(user=self.user).delete()

        self.assertFalse(CardActiveState.objects.filter(card=card).exists())
        self.assertFalse(
            UserActivePracticeSettings.objects.filter(user=self.user).exists()
        )

        call_command("initialize_active_use")

        self.assertTrue(CardActiveState.objects.filter(card=card).exists())
        self.assertTrue(
            UserActivePracticeSettings.objects.filter(user=self.user).exists()
        )

    def test_initialize_active_use_command_is_idempotent(self):
        card = Card.objects.create(
            deck=self.deck,
            question="die Erfahrung",
            answer="опыт",
            has_article=True,
        )

        call_command("initialize_active_use")
        call_command("initialize_active_use")

        self.assertEqual(CardActiveState.objects.filter(card=card).count(), 1)
        self.assertEqual(
            UserActivePracticeSettings.objects.filter(user=self.user).count(),
            1,
        )

    def test_initialize_active_use_marks_stable_review_cards_as_candidates(self):
        now = timezone.now()

        card = Card.objects.create(
            deck=self.deck,
            question="die Entscheidung",
            answer="решение",
            has_article=True,
        )

        card.state = Card.STATE_REVIEW
        card.save(update_fields=["state"])

        ReviewLog.objects.create(
            card=card,
            rating=3,  # Good
            due_before=now,
            due_after=now,
        )
        ReviewLog.objects.create(
            card=card,
            rating=4,  # Easy
            due_before=now,
            due_after=now,
        )

        # Simulate old card created before Active Use Layer existed.
        CardActiveState.objects.filter(card=card).delete()

        call_command("initialize_active_use")

        card.refresh_from_db()

        self.assertEqual(
            card.active_state.stage,
            CardActiveState.STAGE_CANDIDATE,
        )
        self.assertFalse(card.active_state.is_active_pipeline)

    def test_initialize_active_use_keeps_unstable_cards_passive(self):
        card = Card.objects.create(
            deck=self.deck,
            question="das Problem",
            answer="проблема",
            has_article=True,
        )

        card.state = Card.STATE_LEARNING
        card.save(update_fields=["state"])

        CardActiveState.objects.filter(card=card).delete()

        call_command("initialize_active_use")

        card.refresh_from_db()

        self.assertEqual(
            card.active_state.stage,
            CardActiveState.STAGE_PASSIVE,
        )
        self.assertFalse(card.active_state.is_active_pipeline)

class ActiveFSRSServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="active_fsrs_user",
            email="active_fsrs_user@example.com",
            password="test-password-123",
        )
        self.deck = Deck.objects.create(
            owner=self.user,
            title="Active FSRS test deck",
        )
        self.card = Card.objects.create(
            deck=self.deck,
            question="die Entscheidung",
            answer="решение",
            has_article=True,
        )

    def test_active_review_updates_only_active_state(self):
        original_due = self.card.due
        original_fsrs_state = self.card.fsrs_state
        original_stability = self.card.stability
        original_difficulty = self.card.difficulty
        original_state = self.card.state
        original_last_review = self.card.last_review

        service = ActiveFSRSService()

        outcome = service.review_active_card(
            card=self.card,
            user=self.user,
            rating_value=3,
            stage=CardActiveState.STAGE_RECALL,
            task_type="recall",
            generated_prompt="Test prompt",
            user_answer="die Entscheidung",
            chatgpt_response="Rating: Good\nActive use: yes",
            active_use=True,
            source=ActiveUseAttempt.SOURCE_PASTED_CHATGPT_RESPONSE,
        )

        self.card.refresh_from_db()
        self.card.active_state.refresh_from_db()

        self.assertEqual(self.card.due, original_due)
        self.assertEqual(self.card.fsrs_state, original_fsrs_state)
        self.assertEqual(self.card.stability, original_stability)
        self.assertEqual(self.card.difficulty, original_difficulty)
        self.assertEqual(self.card.state, original_state)
        self.assertEqual(self.card.last_review, original_last_review)

        self.assertIsNotNone(self.card.active_state.active_due)
        self.assertTrue(self.card.active_state.active_fsrs_state)
        self.assertGreaterEqual(self.card.active_state.total_active_attempts, 1)
        self.assertEqual(self.card.active_state.successful_active_attempts, 1)
        self.assertEqual(self.card.active_state.failed_active_attempts, 0)
        self.assertEqual(self.card.active_state.consecutive_active_failures, 0)

        self.assertEqual(outcome.active_attempt.rating, 3)
        self.assertTrue(outcome.active_attempt.active_use)
        self.assertTrue(outcome.active_attempt.is_success)

    def test_active_review_again_counts_as_failure(self):
        service = ActiveFSRSService()

        outcome = service.review_active_card(
            card=self.card,
            user=self.user,
            rating_value=1,
            stage=CardActiveState.STAGE_RECALL,
            task_type="recall",
            generated_prompt="Test prompt",
            user_answer="",
            chatgpt_response="Rating: Again\nActive use: no",
            active_use=False,
            error_summary="Could not recall the word.",
            source=ActiveUseAttempt.SOURCE_PASTED_CHATGPT_RESPONSE,
        )

        self.card.active_state.refresh_from_db()

        self.assertEqual(self.card.active_state.total_active_attempts, 1)
        self.assertEqual(self.card.active_state.successful_active_attempts, 0)
        self.assertEqual(self.card.active_state.failed_active_attempts, 1)
        self.assertEqual(self.card.active_state.consecutive_active_failures, 1)
        self.assertEqual(
            self.card.active_state.last_error_summary,
            "Could not recall the word.",
        )

        self.assertEqual(outcome.active_attempt.rating, 1)
        self.assertFalse(outcome.active_attempt.active_use)
        self.assertFalse(outcome.active_attempt.is_success)

    def test_invalid_active_rating_raises_error(self):
        service = ActiveFSRSService()

        with self.assertRaises(ValueError):
            service.review_active_card(
                card=self.card,
                user=self.user,
                rating_value=99,
            )

    def test_hard_rating_does_not_count_as_success(self):
        service = ActiveFSRSService()

        outcome = service.review_active_card(
            card=self.card,
            user=self.user,
            rating_value=2,
            stage=CardActiveState.STAGE_SENTENCE,
            task_type="sentence",
            active_use=True,
        )

        self.card.active_state.refresh_from_db()

        self.assertEqual(self.card.active_state.total_active_attempts, 1)
        self.assertEqual(self.card.active_state.successful_active_attempts, 0)
        self.assertEqual(self.card.active_state.failed_active_attempts, 1)
        self.assertEqual(self.card.active_state.consecutive_active_failures, 1)
        self.assertFalse(outcome.active_attempt.is_success)

    def test_good_without_active_use_does_not_count_as_success(self):
        service = ActiveFSRSService()

        outcome = service.review_active_card(
            card=self.card,
            user=self.user,
            rating_value=3,
            stage=CardActiveState.STAGE_SENTENCE,
            task_type="sentence",
            active_use=False,
        )

        self.card.active_state.refresh_from_db()

        self.assertEqual(self.card.active_state.total_active_attempts, 1)
        self.assertEqual(self.card.active_state.successful_active_attempts, 0)
        self.assertEqual(self.card.active_state.failed_active_attempts, 1)
        self.assertFalse(outcome.active_attempt.is_success)