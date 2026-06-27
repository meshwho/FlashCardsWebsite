from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from .article_logic import is_correct_article_choice, split_article_and_word
from .deck_metrics import enrich_deck_with_memory_score, enrich_decks_with_memory_scores
from .forms import (
    CardInlineFormSet,
    DeckForm,
    PracticeOptionsForm,
    ReviewScheduleForm,
    ReviewSlotFormSet,
    SentencePracticeForm,
    SignUpForm,
    AmbiguousCardContextForm
)
from .models import Card, Deck, PushSubscription, ReviewLog, ReviewSlot, SentenceAttempt
from .practice_logic import (
    MAX_HINTS as PRACTICE_MAX_HINTS,
    get_hint_text,
    get_prompt_and_expected,
    get_typing_result,
)
from .practice_session import (
    add_practice_summary_item,
    advance_practice_session,
    clear_practice_session,
    get_current_card_id,
    get_current_direction,
    get_practice_session,
    get_practice_summary,
    get_remaining_count,
    go_back_practice_session,
    should_require_sentences_in_practice,
    start_deck_practice_session,
)
from .review_logic import (
    MAX_HINTS as REVIEW_MAX_HINTS,
    build_hint_mask,
    get_rating_from_result,
    is_correct_answer,
)
from .review_session import (
    add_review_to_session,
    clear_review_session,
    complete_current_review_retry,
    enqueue_review_retry,
    get_current_review_retry,
    get_review_retry_count,
    get_review_session_summary,
    start_review_session,
)
from .schedule_services import reschedule_all_user_cards
from .selectors import (
    ensure_default_review_slots,
    get_due_cards_for_user,
    get_next_due_card_for_user,
    get_user_card_or_404,
    get_user_deck_cards,
    get_user_deck_or_404,
    get_user_decks,
    get_user_review_slots,
    get_weekly_due_schedule_for_user,
)
from .sentence_logic import sentence_count_for_rating, should_require_sentences
from .sentence_session import (
    clear_pending_sentence_task,
    get_pending_sentence_task,
    set_pending_sentence_task,
)
from .services import FSRSService
from audit.models import AuditLog
from audit.utils import log_action
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .models import UserReviewSchedule
from django.forms import formset_factory
from .card_duplicates import get_ambiguous_cards_for_user
import random
from .words_context import (
    DEFAULT_WORDS_CONTEXT_LEVEL,
    MAX_WORDS_IN_CONTEXT,
    MIN_WORDS_IN_CONTEXT,
    WORDS_CONTEXT_LEVELS,
    WORDS_CONTEXT_SESSION_KEY,
    build_options_for_item,
    build_words_context_prompt,
    choose_random_cards_for_context,
    extract_json_from_ai_response,
    is_correct_context_answer,
    serialize_card_for_context,
    validate_words_context_payload,
    choose_random_distractor_cards_for_context,
    serialize_distractor_options,
)
from django.urls import reverse
from .translation_test import (
    TRANSLATION_TEST_MAX_WORDS,
    TRANSLATION_TEST_MIN_WORDS,
    TRANSLATION_TEST_SESSION_KEY,
    build_translation_test_items,
    choose_random_cards_for_test,
    is_correct_translation_test_answer,
)
from .ai_prompts import build_sentence_check_prompt
from .ai_services import AIServiceError, check_sentences_with_gemini


def _get_posted_non_negative_int(request, key, default=0):
    raw_value = request.POST.get(key, default)

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default

    return max(value, 0)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)

            log_action(
                user=user,
                action=AuditLog.ACTION_CREATE,
                message="User account created",
                entity=user,
                details={
                    "username": user.username,
                    "email": getattr(user, "email", ""),
                },
                request=request,
            )

            return redirect("dashboard")
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})


@login_required
def dashboard_view(request):
    due_count = get_due_cards_for_user(request.user).count()
    weekly_schedule = get_weekly_due_schedule_for_user(request.user, days=7)

    schedule = ensure_default_review_slots(request.user)
    existing_slots = list(
        ReviewSlot.objects.filter(schedule=schedule).order_by("position", "time")
    )

    if request.method == "POST":
        schedule_post_data = request.POST.copy()

        # The dashboard does not let the user edit timezone directly.
        # Timezone is updated separately by /timezone/update/.
        # Therefore we preserve the current schedule timezone here,
        # otherwise ReviewScheduleForm becomes invalid because timezone is required.
        schedule_post_data["timezone"] = schedule.timezone

        schedule_form = ReviewScheduleForm(
            schedule_post_data,
            instance=schedule,
            slots_count=len(existing_slots) or 3,
        )

        reviews_per_day = _get_posted_non_negative_int(
            request,
            "reviews_per_day",
            len(existing_slots) or 3,
        )
        reviews_per_day = max(1, min(reviews_per_day, 10))
        posted_slot_data = []

        for i in range(reviews_per_day):
            posted_slot_data.append(
                {"time": request.POST.get(f"slot_{i}_time")}
            )

        slot_formset = ReviewSlotFormSet(data={
            "form-TOTAL_FORMS": str(reviews_per_day),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
            **{f"form-{i}-time": posted_slot_data[i]["time"] for i in range(reviews_per_day)},
        })

        if schedule_form.is_valid() and slot_formset.is_valid():
            with transaction.atomic():
                schedule = schedule_form.save()

                ReviewSlot.objects.filter(schedule=schedule).delete()

                cleaned_slots = []

                for form in slot_formset.forms:
                    slot_time = form.cleaned_data.get("time")

                    if not slot_time:
                        continue

                    cleaned_slots.append(
                        ReviewSlot(
                            schedule=schedule,
                            position=len(cleaned_slots) + 1,
                            time=slot_time,
                        )
                    )

                ReviewSlot.objects.bulk_create(cleaned_slots)

                updated_count = reschedule_all_user_cards(request.user)

            slot_values = [slot.time.strftime("%H:%M") for slot in cleaned_slots]

            log_action(
                user=request.user,
                action=AuditLog.ACTION_UPDATE,
                message="Review schedule updated",
                entity=schedule,
                details={
                    "timezone": schedule.timezone,
                    "is_active": schedule.is_active,
                    "slots": slot_values,
                    "updated_card_due_times": updated_count,
                },
                request=request,
            )

            messages.success(
                request,
                f"Schedule saved. Updated {updated_count} card due times."
            )
            return redirect("dashboard")
        else:
            messages.error(
                request,
                "Schedule was not saved. Please check the review times and try again."
            )
    else:
        slot_times = get_user_review_slots(request.user)

        schedule_form = ReviewScheduleForm(
            instance=schedule,
            slots_count=len(slot_times),
            initial={"reviews_per_day": len(slot_times)},
        )

        slot_formset = ReviewSlotFormSet(
            initial=[{"time": slot_time} for slot_time in slot_times]
        )

    return render(
        request,
        "study/dashboard.html",
        {
            "due_count": due_count,
            "weekly_schedule": weekly_schedule,
            "schedule_form": schedule_form,
            "slot_formset": slot_formset,
        },
    )


@login_required
def deck_list_view(request):
    decks = list(get_user_decks(request.user))
    decks = enrich_decks_with_memory_scores(decks)

    return render(
        request,
        "study/deck_list.html",
        {
            "decks": decks,
        },
    )


@login_required
def deck_create_view(request):
    if request.method == "POST":
        form = DeckForm(request.POST, user=request.user)
        if form.is_valid():
            deck = form.save(commit=False)
            deck.owner = request.user
            deck.save()

            log_action(
                user=request.user,
                action=AuditLog.ACTION_CREATE,
                message=f'Deck "{deck.title}" created',
                entity=deck,
                details={
                    "title": deck.title,
                    "owner_id": request.user.id,
                },
                request=request,
            )

            return redirect("deck_edit", deck_id=deck.id)
    else:
        form = DeckForm(user=request.user)

    return render(request, "study/deck_form.html", {"form": form})


@login_required
def deck_detail_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    deck = enrich_deck_with_memory_score(deck)

    return render(
        request,
        "study/deck_detail.html",
        {
            "deck": deck,
        },
    )


@login_required
def deck_edit_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)

    if request.method == "POST":
        deck_form = DeckForm(request.POST, instance=deck, user=request.user)
        card_formset = CardInlineFormSet(request.POST, instance=deck)

        if deck_form.is_valid() and card_formset.is_valid():
            old_title = deck.title
            old_card_count = deck.cards.count()

            deck_form.save()
            card_formset.save()

            deck.refresh_from_db()

            log_action(
                user=request.user,
                action=AuditLog.ACTION_UPDATE,
                message=f'Deck "{deck.title}" updated',
                entity=deck,
                details={
                    "old_title": old_title,
                    "new_title": deck.title,
                    "old_card_count": old_card_count,
                    "new_card_count": deck.cards.count(),
                },
                request=request,
            )

            return redirect("deck_detail", deck_id=deck.id)
    else:
        deck_form = DeckForm(instance=deck, user=request.user)
        card_formset = CardInlineFormSet(instance=deck)

    return render(
        request,
        "study/deck_edit.html",
        {
            "deck": deck,
            "deck_form": deck_form,
            "card_formset": card_formset,
            "empty_card_form": card_formset.empty_form,
        },
    )


@login_required
def study_today_view(request):
    due_count = get_due_cards_for_user(request.user).count()

    return render(
        request,
        "study/study_today.html",
        {
            "due_count": due_count,
        },
    )


@login_required
def start_review_session_view(request):
    start_review_session(request)
    return redirect("review_card")


@login_required
def review_card_view(request):
    is_retry = False
    retry_item = None

    if request.method == "POST":
        posted_card_id = request.POST.get("card_id")
        is_retry = request.POST.get("is_retry") == "1"

        if not posted_card_id:
            return redirect("review_card")

        if is_retry:
            retry_item = get_current_review_retry(request)

            if (
                not retry_item
                or retry_item.get("card_id") != posted_card_id
            ):
                return redirect("review_card")
        else:
            current_due_card = get_next_due_card_for_user(request.user)

            if (
                current_due_card is None
                or str(current_due_card.id) != posted_card_id
            ):
                return redirect("review_card")

        card = get_user_card_or_404(
            request.user,
            posted_card_id,
        )

    else:
        card = get_next_due_card_for_user(request.user)

        # Только когда обычные due-карточки закончились,
        # начинаем контрольные повторы.
        if card is None:
            retry_item = get_current_review_retry(request)

            if retry_item is None:
                return redirect("review_done")

            card = get_user_card_or_404(
                request.user,
                retry_item["card_id"],
            )
            is_retry = True

    remaining_count = (
        get_due_cards_for_user(request.user).count()
        + get_review_retry_count(request)
    )

    # Direction is random only when a new card is opened.
    # During POST actions such as Hint, Check, or Don't know,
    # we must preserve the same direction from the hidden input.
    if request.method == "POST":
        direction = request.POST.get("direction") or "forward"
    elif is_retry and retry_item:
        direction = retry_item.get("direction", "forward")
    else:
        direction = random.choice(["forward", "reverse"])

    if direction not in {"forward", "reverse"}:
        direction = "forward"

    if direction == "reverse":
        prompt_text = card.answer
        expected_answer = card.question
        direction_label = "Translation → German"
        expected_side = "question"
    else:
        prompt_text = card.question
        expected_answer = card.answer
        direction_label = "German → Translation"
        expected_side = "answer"

    # If the expected answer is the German side and the card has an article,
    # hints should be built without revealing the article itself.
    use_article_logic = card.has_article and expected_side == "question"

    hints_used = 0
    wrong_attempts_count = 0
    user_answer = ""
    hint_text = ""
    feedback = ""
    feedback_type = ""
    answer_revealed = False

    if request.method == "POST":
        action = request.POST.get("action")
        user_answer = request.POST.get("user_answer", "").strip()
        hints_used = _get_posted_non_negative_int(request, "hints_used", 0)
        wrong_attempts_count = _get_posted_non_negative_int(
            request,
            "wrong_attempts_count",
            0,
        )

        if is_retry:
            if action == "hint":
                hints_used = min(
                    hints_used + 1,
                    REVIEW_MAX_HINTS,
                )

                hint_text = build_hint_mask(
                    expected_answer,
                    hints_used,
                    has_article=use_article_logic,
                )

            elif action == "check":
                if is_correct_answer(
                    user_answer,
                    expected_answer,
                ):
                    complete_current_review_retry(request)
                    return redirect("review_card")

                wrong_attempts_count += 1
                feedback = "Not quite right. Try again or use a hint."
                feedback_type = "error"

                hint_text = build_hint_mask(
                    expected_answer,
                    hints_used,
                    has_article=use_article_logic,
                )

            elif action == "dont_know":
                complete_current_review_retry(request)
                return redirect("review_card")
        else:
            if action == "hint":
                hints_used = min(hints_used + 1, REVIEW_MAX_HINTS)
                hint_text = build_hint_mask(
                    expected_answer,
                    hints_used,
                    has_article=use_article_logic,
                )

            elif action == "check":
                if is_correct_answer(user_answer, expected_answer):
                    rating_value = get_rating_from_result(
                        hints_used,
                        knows_answer=True,
                    )

                    service = FSRSService()
                    outcome = service.review_card(card, rating_value)

                    if rating_value == 1:
                        enqueue_review_retry(
                            request,
                            outcome.card,
                            direction=direction,
                        )

                    if should_require_sentences(
                        had_wrong_attempt=bool(wrong_attempts_count > 0),
                        had_hint=bool(hints_used > 0),
                        rating_value=rating_value,
                        feature_enabled=True,
                    ):
                        required_count = sentence_count_for_rating(rating_value)

                        add_review_to_session(
                            request,
                            outcome.card,
                            rating_value,
                            user_answer=user_answer,
                            hints_used=hints_used,
                            direction=direction,
                            prompt_text=prompt_text,
                            expected_answer=expected_answer,
                        )

                        set_pending_sentence_task(
                            request,
                            card_id=outcome.card.id,
                            source_mode="fsrs",
                            rating_value=rating_value,
                            required_count=required_count,
                            return_url_name="review_card",
                            return_url_kwargs={},
                        )

                        return redirect("sentence_practice")

                    add_review_to_session(
                        request,
                        outcome.card,
                        rating_value,
                        user_answer=user_answer,
                        hints_used=hints_used,
                        direction=direction,
                        prompt_text=prompt_text,
                        expected_answer=expected_answer,
                    )

                    next_card = get_next_due_card_for_user(request.user)

                    if next_card is None:
                        return redirect("review_done")

                    return redirect("review_card")

                wrong_attempts_count += 1
                feedback = "Not quite right. Try again or use a hint."
                feedback_type = "error"
                hint_text = build_hint_mask(
                    expected_answer,
                    hints_used,
                    has_article=use_article_logic,
                )

            elif action == "dont_know":
                rating_value = get_rating_from_result(
                    hints_used,
                    knows_answer=False,
                )

                service = FSRSService()
                outcome = service.review_card(card, rating_value)

                if rating_value == 1:
                    enqueue_review_retry(
                        request,
                        outcome.card,
                        direction=direction,
                    )

                if should_require_sentences(
                    had_wrong_attempt=bool(wrong_attempts_count > 0),
                    had_hint=bool(hints_used > 0),
                    had_dont_know=True,
                    rating_value=rating_value,
                    feature_enabled=True,
                ):
                    required_count = sentence_count_for_rating(rating_value)

                    add_review_to_session(
                        request,
                        outcome.card,
                        rating_value,
                        user_answer=user_answer,
                        hints_used=hints_used,
                        direction=direction,
                        prompt_text=prompt_text,
                        expected_answer=expected_answer,
                    )

                    set_pending_sentence_task(
                        request,
                        card_id=outcome.card.id,
                        source_mode="fsrs",
                        rating_value=rating_value,
                        required_count=required_count,
                        return_url_name="review_card",
                        return_url_kwargs={},
                    )

                    return redirect("sentence_practice")

                add_review_to_session(
                    request,
                    outcome.card,
                    rating_value,
                    user_answer=user_answer,
                    hints_used=hints_used,
                    direction=direction,
                    prompt_text=prompt_text,
                    expected_answer=expected_answer,
                )

                answer_revealed = True
                feedback = f"Correct answer: {expected_answer}"
                feedback_type = "info"

                return redirect("review_card")

    else:
        hint_text = build_hint_mask(
            expected_answer,
            0,
            has_article=use_article_logic,
        )

    if hints_used > 0 and not hint_text:
        hint_text = build_hint_mask(
            expected_answer,
            hints_used,
            has_article=use_article_logic,
        )

    return render(
        request,
        "study/review_card.html",
        {
            "card": card,
            "is_retry": is_retry,
            "prompt_text": prompt_text,
            "expected_answer": expected_answer,
            "direction": direction,
            "direction_label": direction_label,
            "remaining_count": remaining_count,
            "hints_used": hints_used,
            "wrong_attempts_count": wrong_attempts_count,
            "max_hints": REVIEW_MAX_HINTS,
            "hint_text": hint_text,
            "user_answer": user_answer,
            "feedback": feedback,
            "feedback_type": feedback_type,
            "answer_revealed": answer_revealed,
            "can_speak_prompt": direction != "reverse",
            "speech_text": prompt_text if direction != "reverse" else "",
        },
    )


@login_required
def review_done_view(request):
    summary = get_review_session_summary(request)

    log_action(
        user=request.user,
        action=AuditLog.ACTION_REVIEW,
        message="Review session completed",
        details={
            "summary": summary,
        },
        request=request,
    )

    clear_review_session(request)

    return render(
        request,
        "study/review_done.html",
        {
            "summary": summary,
        },
    )

@login_required
def deck_practice_setup_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    cards = list(get_user_deck_cards(request.user, deck_id))
    practice_options_form = PracticeOptionsForm(request.POST or None)

    if not cards:
        return render(
            request,
            "study/deck_practice_setup.html",
            {
                "deck": deck,
                "has_cards": False,
            },
        )

    if request.method == "POST":
        mode = request.POST.get("mode")
        require_sentences_after_mistake = False
        if practice_options_form.is_valid():
            require_sentences_after_mistake = practice_options_form.cleaned_data[
                "require_sentences_after_mistake"
            ]

        if mode not in {"flip", "typing", "articles"}:
            mode = "flip"

        selected_cards = cards

        if mode == "articles":
            selected_cards = [card for card in cards if card.has_article]

            if not selected_cards:
                return render(
                    request,
                    "study/deck_practice_setup.html",
                    {
                        "deck": deck,
                        "has_cards": True,
                        "card_count": len(cards),
                        "has_article_cards": False,
                        "article_card_count": 0,
                        "practice_options_form": practice_options_form,
                    },
                )

        start_deck_practice_session(
            request,
            deck,
            mode,
            [card.id for card in selected_cards],
            require_sentences_after_mistake=require_sentences_after_mistake,
        )

        log_action(
            user=request.user,
            action=AuditLog.ACTION_PRACTICE,
            message=f'Practice session started for deck "{deck.title}"',
            entity=deck,
            details={
                "mode": mode,
                "selected_cards_count": len(selected_cards),
                "require_sentences_after_mistake": require_sentences_after_mistake,
            },
            request=request,
        )

        if mode == "flip":
            return redirect("deck_practice_flip", deck_id=deck.id)

        if mode == "typing":
            return redirect("deck_practice_typing", deck_id=deck.id)

        return redirect("deck_practice_articles", deck_id=deck.id)

    return render(
        request,
        "study/deck_practice_setup.html",
        {
            "deck": deck,
            "has_cards": True,
            "card_count": len(cards),
            "has_article_cards": any(card.has_article for card in cards),
            "article_card_count": sum(1 for card in cards if card.has_article),
            "practice_options_form": practice_options_form,
        },
    )


@login_required
def deck_practice_flip_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    session = get_practice_session(request)

    if not session or session.get("deck_id") != str(deck.id) or session.get("mode") != "flip":
        return redirect("deck_practice_setup", deck_id=deck.id)

    card_id = get_current_card_id(request)
    if card_id is None:
        return redirect("deck_practice_done", deck_id=deck.id)

    card = get_user_card_or_404(request.user, card_id)
    remaining_count = get_remaining_count(request)
    current_index = session.get("current_index", 0)
    can_go_back = current_index > 0

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "back":
            go_back_practice_session(request)
            return redirect("deck_practice_flip", deck_id=deck.id)

        if action == "next":
            add_practice_summary_item(
                request,
                {
                    "question": card.question,
                    "answer": card.answer,
                    "mode": "flip",
                },
            )
            advance_practice_session(request)

            if get_current_card_id(request) is None:
                return redirect("deck_practice_done", deck_id=deck.id)

            return redirect("deck_practice_flip", deck_id=deck.id)

    return render(
        request,
        "study/deck_practice_flip.html",
        {
            "deck": deck,
            "card": card,
            "remaining_count": remaining_count,
            "can_go_back": can_go_back,
        },
    )


@login_required
def deck_practice_typing_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    session = get_practice_session(request)

    if not session or session.get("deck_id") != str(deck.id) or session.get("mode") != "typing":
        return redirect("deck_practice_setup", deck_id=deck.id)

    card_id = get_current_card_id(request)
    if card_id is None:
        return redirect("deck_practice_done", deck_id=deck.id)

    card = get_user_card_or_404(request.user, card_id)
    direction = get_current_direction(request)
    qa = get_prompt_and_expected(card, direction)
    use_article_logic = card.has_article and qa["expected_side"] == "question"

    remaining_count = get_remaining_count(request)

    hints_used = 0
    wrong_attempts_count = 0
    user_answer = ""
    hint_text = ""
    feedback = ""

    if request.method == "POST":
        action = request.POST.get("action")
        user_answer = request.POST.get("user_answer", "").strip()
        hints_used = _get_posted_non_negative_int(request, "hints_used", 0)
        wrong_attempts_count = _get_posted_non_negative_int(request, "wrong_attempts_count", 0)

        if action == "hint":
            hints_used = min(hints_used + 1, PRACTICE_MAX_HINTS)
            hint_text = get_hint_text(
                qa["expected"],
                hints_used,
                has_article=use_article_logic,
            )

        elif action == "check":
            result = get_typing_result(
                qa["expected"],
                user_answer,
                hints_used,
                dont_know=False,
            )

            if result["is_correct"]:
                if should_require_sentences(
                        had_wrong_attempt=bool(wrong_attempts_count > 0),
                        had_hint=bool(hints_used > 0),
                        rating_value=result["rating_value"],
                        feature_enabled=should_require_sentences_in_practice(request),
                ):
                    required_count = sentence_count_for_rating(result["rating_value"])

                    set_pending_sentence_task(
                        request,
                        card_id=card.id,
                        source_mode="typing_practice",
                        rating_value=result["rating_value"],
                        required_count=required_count,
                        return_url_name="deck_practice_typing",
                        return_url_kwargs={"deck_id": deck.id},
                    )

                    add_practice_summary_item(
                        request,
                        {
                            "question": qa["prompt"],
                            "answer": qa["expected"],
                            "user_answer": user_answer,
                            "hints_used": hints_used,
                            "rating_label": result["rating_label"],
                            "direction_label": qa["direction_label"],
                            "is_correct": True,
                            "mode": "typing",
                        },
                    )
                    advance_practice_session(request)
                    return redirect("sentence_practice")

                add_practice_summary_item(
                    request,
                    {
                        "question": qa["prompt"],
                        "answer": qa["expected"],
                        "user_answer": user_answer,
                        "hints_used": hints_used,
                        "rating_label": result["rating_label"],
                        "direction_label": qa["direction_label"],
                        "is_correct": True,
                        "mode": "typing",
                    },
                )

                advance_practice_session(request)

                if get_current_card_id(request) is None:
                    return redirect("deck_practice_done", deck_id=deck.id)

                return redirect("deck_practice_typing", deck_id=deck.id)

            feedback = "Not quite right. Try again or use a hint."
            wrong_attempts_count += 1
            hint_text = get_hint_text(
                qa["expected"],
                hints_used,
                has_article=use_article_logic,
            )

        elif action == "dont_know":
            result = get_typing_result(
                qa["expected"],
                user_answer,
                hints_used,
                dont_know=True,
            )

            if should_require_sentences(
                    had_wrong_attempt=bool(wrong_attempts_count > 0),
                    had_hint=bool(hints_used > 0),
                    had_dont_know=True,
                    rating_value=result["rating_value"],
                    feature_enabled=should_require_sentences_in_practice(request),
            ):
                required_count = sentence_count_for_rating(result["rating_value"])

                set_pending_sentence_task(
                    request,
                    card_id=card.id,
                    source_mode="typing_practice",
                    rating_value=result["rating_value"],
                    required_count=required_count,
                    return_url_name="deck_practice_typing",
                    return_url_kwargs={"deck_id": deck.id},
                )

                add_practice_summary_item(
                    request,
                    {
                        "question": qa["prompt"],
                        "answer": qa["expected"],
                        "user_answer": user_answer,
                        "hints_used": hints_used,
                        "rating_label": result["rating_label"],
                        "direction_label": qa["direction_label"],
                        "is_correct": False,
                        "mode": "typing",
                    },
                )

                advance_practice_session(request)
                return redirect("sentence_practice")

            add_practice_summary_item(
                request,
                {
                    "question": qa["prompt"],
                    "answer": qa["expected"],
                    "user_answer": user_answer,
                    "hints_used": hints_used,
                    "rating_label": result["rating_label"],
                    "direction_label": qa["direction_label"],
                    "is_correct": False,
                    "mode": "typing",
                },
            )

            advance_practice_session(request)

            if get_current_card_id(request) is None:
                return redirect("deck_practice_done", deck_id=deck.id)

            return redirect("deck_practice_typing", deck_id=deck.id)

    if hints_used > 0 and not hint_text:
        hint_text = get_hint_text(
            qa["expected"],
            hints_used,
            has_article=use_article_logic,
        )

    return render(
        request,
        "study/deck_practice_typing.html",
        {
            "deck": deck,
            "card": card,
            "prompt_text": qa["prompt"],
            "direction_label": qa["direction_label"],
            "remaining_count": remaining_count,
            "hints_used": hints_used,
            "wrong_attempts_count": wrong_attempts_count,
            "max_hints": PRACTICE_MAX_HINTS,
            "hint_text": hint_text,
            "user_answer": user_answer,
            "feedback": feedback,
            "can_speak_prompt": direction != "reverse",
            "speech_text": qa["prompt"] if direction != "reverse" else "",
        },
    )

@login_required
def deck_practice_done_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    summary = get_practice_summary(request)
    practice_mode = summary.get("mode")

    log_action(
        user=request.user,
        action=AuditLog.ACTION_PRACTICE,
        message=f'Practice session finished for deck "{deck.title}"',
        entity=deck,
        details={
            "mode": practice_mode,
            "summary": summary,
        },
        request=request,
    )

    clear_practice_session(request)

    return render(
        request,
        "study/deck_practice_done.html",
        {
            "deck": deck,
            "summary": summary,
            "practice_mode": practice_mode,
        },
    )

@login_required
def profile_view(request):
    user = request.user

    total_decks = user.decks.count()
    total_cards = Card.objects.filter(deck__owner=user).count()
    due_now = get_due_cards_for_user(user).count()

    today = timezone.localdate()
    reviews_today = ReviewLog.objects.filter(
        card__deck__owner=user,
        reviewed_at__date=today,
    ).count()

    learning_count = Card.objects.filter(
        deck__owner=user,
        state="Learning",
    ).count()

    review_count = Card.objects.filter(
        deck__owner=user,
        state="Review",
    ).count()

    relearning_count = Card.objects.filter(
        deck__owner=user,
        state="Relearning",
    ).count()

    recent_reviews = ReviewLog.objects.filter(
        card__deck__owner=user,
    ).select_related("card", "card__deck").order_by("-reviewed_at")[:10]

    top_decks = list(
        Deck.objects.filter(owner=user)
        .annotate(card_count=Count("cards"))
        .order_by("-card_count", "title")[:5]
    )

    top_decks = enrich_decks_with_memory_scores(top_decks)

    schedule = getattr(user, "review_schedule", None)
    schedule_slots = []
    if schedule:
        schedule_slots = schedule.slots.all().order_by("position", "time")

    return render(
        request,
        "study/profile.html",
        {
            "total_decks": total_decks,
            "total_cards": total_cards,
            "due_now": due_now,
            "reviews_today": reviews_today,
            "learning_count": learning_count,
            "review_count": review_count,
            "relearning_count": relearning_count,
            "recent_reviews": recent_reviews,
            "top_decks": top_decks,
            "schedule": schedule,
            "schedule_slots": schedule_slots,
        },
    )

@login_required
def deck_practice_articles_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    session = get_practice_session(request)

    if not session or session.get("deck_id") != str(deck.id) or session.get("mode") != "articles":
        return redirect("deck_practice_setup", deck_id=deck.id)

    card_id = get_current_card_id(request)
    if card_id is None:
        return redirect("deck_practice_done", deck_id=deck.id)

    card = get_user_card_or_404(request.user, card_id)
    remaining_count = get_remaining_count(request)

    correct_article, word_without_article = split_article_and_word(card.question)

    wrong_attempts_count = 0
    feedback = ""

    if request.method == "POST":
        wrong_attempts_count = _get_posted_non_negative_int(request, "wrong_attempts_count", 0)
        chosen_article = request.POST.get("chosen_article", "").strip().lower()

        is_correct = is_correct_article_choice(card.question, chosen_article)

        if not is_correct:
            wrong_attempts_count += 1
            feedback = "Wrong article. Try again."

            return render(
                request,
                "study/deck_practice_articles.html",
                {
                    "deck": deck,
                    "card": card,
                    "word_without_article": word_without_article,
                    "remaining_count": remaining_count,
                    "wrong_attempts_count": wrong_attempts_count,
                    "feedback": feedback,
                },
            )

        if wrong_attempts_count == 0:
            rating_value = 4   # Easy
            rating_label = "Easy"
        elif wrong_attempts_count == 1:
            rating_value = 2   # Hard
            rating_label = "Hard"
        else:
            rating_value = 1   # Again
            rating_label = "Again"

        add_practice_summary_item(
            request,
            {
                "question": word_without_article,
                "answer": card.question,
                "chosen_article": chosen_article,
                "correct_article": correct_article,
                "is_correct": True,
                "mistakes_count": wrong_attempts_count,
                "is_perfect": wrong_attempts_count == 0,
                "rating_label": rating_label,
                "mode": "articles",
            },
        )

        if should_require_sentences(
                had_wrong_attempt=bool(wrong_attempts_count > 0),
                had_hint=False,
                rating_value=rating_value,
                feature_enabled=should_require_sentences_in_practice(request),
        ):
            required_count = sentence_count_for_rating(rating_value)

            set_pending_sentence_task(
                request,
                card_id=card.id,
                source_mode="article_practice",
                rating_value=rating_value,
                required_count=required_count,
                return_url_name="deck_practice_articles",
                return_url_kwargs={"deck_id": deck.id},
            )

            advance_practice_session(request)
            return redirect("sentence_practice")

        advance_practice_session(request)

        if get_current_card_id(request) is None:
            return redirect("deck_practice_done", deck_id=deck.id)

        return redirect("deck_practice_articles", deck_id=deck.id)

    return render(
        request,
        "study/deck_practice_articles.html",
        {
            "deck": deck,
            "card": card,
            "word_without_article": word_without_article,
            "remaining_count": remaining_count,
            "wrong_attempts_count": wrong_attempts_count,
            "feedback": feedback,
        },
    )


@login_required
def repeat_practice_view(request, deck_id, mode):
    deck = get_user_deck_or_404(request.user, deck_id)
    cards = list(get_user_deck_cards(request.user, deck_id))

    if mode not in {"flip", "typing", "articles"}:
        return redirect("deck_practice_setup", deck_id=deck.id)

    selected_cards = cards

    if mode == "articles":
        selected_cards = [card for card in cards if card.has_article]

    if not selected_cards:
        return redirect("deck_practice_setup", deck_id=deck.id)

    start_deck_practice_session(
        request,
        deck,
        mode,
        [card.id for card in selected_cards],
    )

    if mode == "flip":
        return redirect("deck_practice_flip", deck_id=deck.id)

    if mode == "typing":
        return redirect("deck_practice_typing", deck_id=deck.id)

    return redirect("deck_practice_articles", deck_id=deck.id)


@login_required
def sentence_practice_view(request):
    task = get_pending_sentence_task(request)

    if not task:
        return redirect("dashboard")

    allowed_source_modes = {"fsrs", "typing_practice", "article_practice"}
    allowed_return_urls = {
        "review_card",
        "deck_practice_typing",
        "deck_practice_articles",
    }

    try:
        required_count = int(task["required_count"])
    except (KeyError, TypeError, ValueError):
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    if required_count < 1 or required_count > 3:
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    source_mode = task.get("source_mode")
    if source_mode not in allowed_source_modes:
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    return_name = task.get("return_url_name")
    if return_name not in allowed_return_urls:
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    card_id = task.get("card_id")
    if not card_id:
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    return_kwargs = task.get("return_url_kwargs", {})
    if not isinstance(return_kwargs, dict):
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    if return_name == "review_card":
        allowed_kwargs = set()
    else:
        allowed_kwargs = {"deck_id"}

    if set(return_kwargs.keys()) != allowed_kwargs:
        clear_pending_sentence_task(request)
        return redirect("dashboard")

    card = get_user_card_or_404(request.user, card_id)

    if request.method == "POST":
        form = SentencePracticeForm(request.POST, sentence_count=required_count)

        if form.is_valid():
            for i in range(required_count):
                sentence_text = form.cleaned_data[f"sentence_{i+1}"].strip()

                SentenceAttempt.objects.create(
                    card=card,
                    user=request.user,
                    source_mode=source_mode,
                    sentence=sentence_text,
                )

            log_action(
                user=request.user,
                action=AuditLog.ACTION_PRACTICE,
                message="Sentence practice completed",
                entity=card,
                details={
                    "source_mode": source_mode,
                    "required_count": required_count,
                    "card_id": str(card.id),
                },
                request=request,
            )
            
            clear_pending_sentence_task(request)
            return redirect(return_name, **return_kwargs)
    else:
        form = SentencePracticeForm(sentence_count=required_count)

    return render(
        request,
        "study/sentence_practice.html",
        {
            "card": card,
            "required_count": required_count,
            "form": form,
            "source_mode": source_mode,
        },
    )

@login_required
@require_POST
def update_timezone_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON."},
            status=400,
        )

    timezone_name = (payload.get("timezone") or "").strip()

    if not timezone_name:
        return JsonResponse(
            {"ok": False, "error": "Timezone is required."},
            status=400,
        )

    # Some browsers/devices may still return older IANA aliases.
    timezone_aliases = {
        "Europe/Kiev": "Europe/Kyiv",
    }

    timezone_name = timezone_aliases.get(timezone_name, timezone_name)

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return JsonResponse(
            {
                "ok": False,
                "error": "Invalid timezone.",
                "timezone": timezone_name,
            },
            status=400,
        )

    schedule = ensure_default_review_slots(request.user)

    if schedule.timezone != timezone_name:
        schedule.timezone = timezone_name
        schedule.save(update_fields=["timezone"])

        updated_count = reschedule_all_user_cards(request.user)
    else:
        updated_count = 0

    return JsonResponse(
        {
            "ok": True,
            "timezone": schedule.timezone,
            "updated_card_due_times": updated_count,
        }
    )

@login_required
@require_POST
def deck_delete_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)

    deck_title = deck.title
    deck_id_str = str(deck.id)
    card_count = deck.cards.count()

    with transaction.atomic():
        log_action(
            user=request.user,
            action=AuditLog.ACTION_DELETE,
            message=f'Deck "{deck_title}" deleted',
            entity=deck,
            details={
                "deck_id": deck_id_str,
                "title": deck_title,
                "deleted_cards_count": card_count,
            },
            request=request,
        )

        deck.delete()

    messages.success(request, f'Deck "{deck_title}" was deleted.')
    return redirect("deck_list")


@login_required
def push_config_view(request):
    return JsonResponse({
        "publicKey": settings.WEB_PUSH_VAPID_PUBLIC_KEY,
    })


@login_required
@require_POST
def save_push_subscription_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return JsonResponse({"error": "Invalid push subscription."}, status=400)

    subscription, created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        },
    )

    return JsonResponse({
        "ok": True,
        "created": created,
        "subscription_id": subscription.id,
    })

@login_required
@require_POST
def delete_push_subscription_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    endpoint = (payload.get("endpoint") or "").strip()

    if not endpoint:
        return JsonResponse({"error": "Endpoint is required."}, status=400)

    deleted_count, _ = PushSubscription.objects.filter(
        user=request.user,
        endpoint=endpoint,
    ).delete()

    return JsonResponse({
        "ok": True,
        "deleted": deleted_count,
    })

@login_required
def ambiguous_cards_view(request):
    ambiguous_items = get_ambiguous_cards_for_user(request.user)

    ContextFormSet = formset_factory(
        AmbiguousCardContextForm,
        extra=0,
    )

    if request.method == "POST":
        formset = ContextFormSet(request.POST)

        cards_by_id = {
            str(item["card"].id): item["card"]
            for item in ambiguous_items
        }

        if formset.is_valid():
            updated_count = 0

            for form in formset:
                card_id = str(form.cleaned_data["card_id"])
                context = (form.cleaned_data.get("context") or "").strip()

                card = cards_by_id.get(card_id)

                if card is None:
                    continue

                if card.context != context:
                    card.context = context
                    card.save(update_fields=["context"])
                    updated_count += 1

            messages.success(
                request,
                f"Contexts saved. Updated {updated_count} card(s)."
            )
            return redirect("ambiguous_cards")
    else:
        initial = [
            {
                "card_id": item["card"].id,
                "context": item["card"].context,
            }
            for item in ambiguous_items
        ]

        formset = ContextFormSet(initial=initial)

    rows = []

    for item, form in zip(ambiguous_items, formset.forms):
        rows.append({
            "card": item["card"],
            "reasons": item["reasons"],
            "form": form,
        })

    return render(
        request,
        "study/ambiguous_cards.html",
        {
            "rows": rows,
            "formset": formset,
        },
    )


@login_required
def words_in_context_setup_view(request):
    available_cards_count = (
        Card.objects
        .filter(deck__owner=request.user)
        .exclude(question__exact="")
        .exclude(answer__exact="")
        .count()
    )

    selected_level = DEFAULT_WORDS_CONTEXT_LEVEL

    if request.method == "POST":
        raw_count = request.POST.get("word_count", MIN_WORDS_IN_CONTEXT)
        selected_level = request.POST.get("text_level") or DEFAULT_WORDS_CONTEXT_LEVEL

        if selected_level not in WORDS_CONTEXT_LEVELS:
            selected_level = DEFAULT_WORDS_CONTEXT_LEVEL

        try:
            word_count = int(raw_count)
        except (TypeError, ValueError):
            word_count = MIN_WORDS_IN_CONTEXT

        word_count = max(MIN_WORDS_IN_CONTEXT, min(word_count, MAX_WORDS_IN_CONTEXT))

        selected_cards = choose_random_cards_for_context(request.user, word_count)

        selected_card_ids = [card.id for card in selected_cards]

        distractor_cards = choose_random_distractor_cards_for_context(
            request.user,
            excluded_card_ids=selected_card_ids,
        )

        if len(selected_cards) < MIN_WORDS_IN_CONTEXT:
            messages.error(
                request,
                "You need at least 4 cards to start Words in context.",
            )
            return redirect("words_in_context_setup")

        if len(selected_cards) < word_count:
            messages.warning(
                request,
                f"Only {len(selected_cards)} suitable cards were found.",
            )

        request.session[WORDS_CONTEXT_SESSION_KEY] = {
            "selected_cards": [
                serialize_card_for_context(card)
                for card in selected_cards
            ],
            "distractor_cards": [
                serialize_card_for_context(card)
                for card in distractor_cards
            ],
            "selected_level": selected_level,
            "title": "",
            "level": selected_level,
            "full_text": "",
            "summary": "",
            "items": [],
            "current_index": 0,
            "results": [],
        }
        request.session.modified = True

        return redirect("words_in_context_prompt")

    return render(
        request,
        "study/words_in_context_setup.html",
        {
            "available_cards_count": available_cards_count,
            "min_words": MIN_WORDS_IN_CONTEXT,
            "max_words": MAX_WORDS_IN_CONTEXT,
            "default_words": min(8, max(MIN_WORDS_IN_CONTEXT, available_cards_count)),
            "levels": WORDS_CONTEXT_LEVELS,
            "selected_level": selected_level,
        },
    )

@login_required
def words_in_context_prompt_view(request):
    session_data = request.session.get(WORDS_CONTEXT_SESSION_KEY)

    if not session_data or not session_data.get("selected_cards"):
        return redirect("words_in_context_setup")

    selected_cards = session_data["selected_cards"]
    distractor_cards = session_data.get("distractor_cards", [])
    selected_level = session_data.get("selected_level") or DEFAULT_WORDS_CONTEXT_LEVEL

    ai_prompt = build_words_context_prompt(
        selected_cards,
        distractor_cards,
        selected_level,
    )

    ai_response = ""

    if request.method == "POST":
        ai_response = request.POST.get("ai_response", "")

        try:
            payload = extract_json_from_ai_response(ai_response)
            cleaned_payload = validate_words_context_payload(
                payload,
                selected_cards,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            session_data.update(cleaned_payload)
            session_data["current_index"] = 0
            session_data["results"] = []
            session_data["level"] = cleaned_payload.get("level") or selected_level

            request.session[WORDS_CONTEXT_SESSION_KEY] = session_data
            request.session.modified = True

            return redirect("words_in_context_practice")

    return render(
        request,
        "study/words_in_context_prompt.html",
        {
            "selected_cards": selected_cards,
            "distractor_cards": distractor_cards,
            "selected_level": selected_level,
            "ai_prompt": ai_prompt,
            "ai_response": ai_response,
        },
    )


@login_required
def words_in_context_practice_view(request):
    session_data = request.session.get(WORDS_CONTEXT_SESSION_KEY)

    if not session_data or not session_data.get("items"):
        return redirect("words_in_context_prompt")

    items = session_data["items"]
    current_index = session_data.get("current_index", 0)

    if current_index >= len(items):
        return redirect("words_in_context_done")

    current_item = items[current_index]
    options = build_options_for_item(items, current_index)

    session_data["items"] = items
    request.session[WORDS_CONTEXT_SESSION_KEY] = session_data
    request.session.modified = True

    attempted_options = current_item.get("attempted_options", [])

    option_rows = [
        {
            "text": option,
            "is_attempted": option in attempted_options,
        }
        for option in options
    ]

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        selected_answer = (request.POST.get("answer") or "").strip()
        correct_answer = current_item["correct_option"]

        is_answer_correct = is_correct_context_answer(
            selected_answer,
            correct_answer,
        )

        if is_answer_correct:
            had_wrong_attempt = bool(current_item.get("attempted_options", []))

            result = {
                "blank_text": current_item["blank_text"],
                "sentence": current_item.get("sentence", ""),
                "selected_answer": selected_answer,
                "correct_answer": correct_answer,
                "is_correct": not had_wrong_attempt,
                "was_solved": True,
                "had_wrong_attempt": had_wrong_attempt,
                "attempts_count": len(current_item.get("attempted_options", [])) + 1,
                "wrong_attempts": current_item.get("attempted_options", []),
            }

            session_data.setdefault("results", []).append(result)
            session_data["current_index"] = current_index + 1

            request.session[WORDS_CONTEXT_SESSION_KEY] = session_data
            request.session.modified = True

            if session_data["current_index"] >= len(items):
                redirect_url = reverse("words_in_context_done")
                next_label = "Finish"
            else:
                redirect_url = reverse("words_in_context_practice")
                next_label = "Next"

            full_sentence = current_item.get("sentence") or current_item["blank_text"].replace(
                "____",
                correct_answer,
            )

            if is_ajax:
                return JsonResponse({
                    "is_correct": True,
                    "redirect_url": redirect_url,
                    "next_label": next_label,
                    "full_sentence": full_sentence,
                    "correct_answer": correct_answer,
                    "had_wrong_attempt": had_wrong_attempt,
                    "counted_as_correct": not had_wrong_attempt,
                })

            return redirect(redirect_url)

        attempted_options = current_item.setdefault("attempted_options", [])

        if selected_answer and selected_answer not in attempted_options:
            attempted_options.append(selected_answer)

        items[current_index] = current_item
        session_data["items"] = items

        request.session[WORDS_CONTEXT_SESSION_KEY] = session_data
        request.session.modified = True

        if is_ajax:
            return JsonResponse({
                "is_correct": False,
                "selected_answer": selected_answer,
                "attempted_options": attempted_options,
                "feedback": "Not quite. Try another option.",
            })

        option_rows = [
            {
                "text": option,
                "is_attempted": option in attempted_options,
            }
            for option in options
        ]

        return render(
            request,
            "study/words_in_context_practice.html",
            {
                "title": session_data.get("title") or "Words in context",
                "level": session_data.get("level") or "A2-B1",
                "current_item": current_item,
                "options": options,
                "option_rows": option_rows,
                "attempted_options": attempted_options,
                "feedback": "Not quite. Try another option.",
                "current_number": current_index + 1,
                "total_count": len(items),
            },
        )

    return render(
        request,
        "study/words_in_context_practice.html",
        {
            "title": session_data.get("title") or "Words in context",
            "level": session_data.get("level") or "A2-B1",
            "current_item": current_item,
            "options": options,
            "option_rows": option_rows,
            "attempted_options": attempted_options,
            "feedback": "",
            "current_number": current_index + 1,
            "total_count": len(items),
        },
    )


@login_required
def words_in_context_done_view(request):
    session_data = request.session.get(WORDS_CONTEXT_SESSION_KEY)

    if not session_data:
        return redirect("words_in_context_setup")

    results = session_data.get("results", [])
    total_count = len(results)
    correct_count = sum(1 for item in results if item.get("is_correct"))
    wrong_count = total_count - correct_count

    return render(
        request,
        "study/words_in_context_done.html",
        {
            "title": session_data.get("title") or "Words in context",
            "level": session_data.get("level") or "A2-B1",
            "summary_text": session_data.get("summary") or "",
            "full_text": session_data.get("full_text") or "",
            "results": results,
            "total_count": total_count,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
        },
    )

@login_required
def translation_test_setup_view(request):
    available_cards_count = (
        Card.objects
        .filter(deck__owner=request.user)
        .exclude(question__exact="")
        .exclude(answer__exact="")
        .count()
    )

    if request.method == "POST":
        raw_count = request.POST.get("word_count", TRANSLATION_TEST_MIN_WORDS)

        try:
            word_count = int(raw_count)
        except (TypeError, ValueError):
            word_count = TRANSLATION_TEST_MIN_WORDS

        word_count = max(
            TRANSLATION_TEST_MIN_WORDS,
            min(word_count, TRANSLATION_TEST_MAX_WORDS),
        )

        selected_cards = choose_random_cards_for_test(request.user, word_count)

        if len(selected_cards) < TRANSLATION_TEST_MIN_WORDS:
            messages.error(
                request,
                "You need at least 4 cards to start the test.",
            )
            return redirect("translation_test_setup")

        if len(selected_cards) < word_count:
            messages.warning(
                request,
                f"Only {len(selected_cards)} suitable cards were found.",
            )

        try:
            items = build_translation_test_items(
                user=request.user,
                selected_cards=selected_cards,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("translation_test_setup")

        request.session[TRANSLATION_TEST_SESSION_KEY] = {
            "items": items,
            "current_index": 0,
            "results": [],
        }
        request.session.modified = True

        return redirect("translation_test_practice")

    return render(
        request,
        "study/translation_test_setup.html",
        {
            "available_cards_count": available_cards_count,
            "min_words": TRANSLATION_TEST_MIN_WORDS,
            "max_words": TRANSLATION_TEST_MAX_WORDS,
            "default_words": min(
                10,
                max(TRANSLATION_TEST_MIN_WORDS, available_cards_count),
            ),
        },
    )


@login_required
def translation_test_practice_view(request):
    session_data = request.session.get(TRANSLATION_TEST_SESSION_KEY)

    if not session_data or not session_data.get("items"):
        return redirect("translation_test_setup")

    items = session_data["items"]
    current_index = session_data.get("current_index", 0)

    if current_index >= len(items):
        return redirect("translation_test_done")

    current_item = items[current_index]

    attempted_options = current_item.get("attempted_options", [])

    option_rows = [
        {
            "text": option,
            "is_attempted": option in attempted_options,
        }
        for option in current_item["options"]
    ]

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        selected_answer = (request.POST.get("answer") or "").strip()
        correct_answer = current_item["correct_option"]

        is_answer_correct = is_correct_translation_test_answer(
            selected_answer,
            correct_answer,
        )

        if is_answer_correct:
            had_wrong_attempt = bool(current_item.get("attempted_options", []))

            result = {
                "prompt_text": current_item["prompt_text"],
                "correct_option": correct_answer,
                "selected_answer": selected_answer,
                "direction_label": current_item["direction_label"],
                "deck_title": current_item["deck_title"],
                "context": current_item.get("context", ""),
                # Important:
                # If the user made at least one wrong attempt,
                # the item is counted as incorrect even after the correct answer.
                "is_correct": not had_wrong_attempt,
                "was_solved": True,
                "had_wrong_attempt": had_wrong_attempt,
                "attempts_count": len(current_item.get("attempted_options", [])) + 1,
                "wrong_attempts": current_item.get("attempted_options", []),
            }

            session_data.setdefault("results", []).append(result)
            session_data["current_index"] = current_index + 1

            request.session[TRANSLATION_TEST_SESSION_KEY] = session_data
            request.session.modified = True

            if session_data["current_index"] >= len(items):
                redirect_url = reverse("translation_test_done")
                next_label = "Finish"
            else:
                redirect_url = reverse("translation_test_practice")
                next_label = "Next"

            if is_ajax:
                return JsonResponse({
                    "is_correct": True,
                    "redirect_url": redirect_url,
                    "next_label": next_label,
                    "correct_answer": correct_answer,
                    "had_wrong_attempt": had_wrong_attempt,
                    "counted_as_correct": not had_wrong_attempt,
                })

            return redirect(redirect_url)

        attempted_options = current_item.setdefault("attempted_options", [])

        if selected_answer and selected_answer not in attempted_options:
            attempted_options.append(selected_answer)

        items[current_index] = current_item
        session_data["items"] = items

        request.session[TRANSLATION_TEST_SESSION_KEY] = session_data
        request.session.modified = True

        if is_ajax:
            return JsonResponse({
                "is_correct": False,
                "selected_answer": selected_answer,
                "attempted_options": attempted_options,
                "feedback": "Not quite. Try another option.",
            })

        option_rows = [
            {
                "text": option,
                "is_attempted": option in attempted_options,
            }
            for option in current_item["options"]
        ]

        return render(
            request,
            "study/translation_test_practice.html",
            {
                "item": current_item,
                "option_rows": option_rows,
                "feedback": "Not quite. Try another option.",
                "current_number": current_index + 1,
                "total_count": len(items),
            },
        )

    return render(
        request,
        "study/translation_test_practice.html",
        {
            "item": current_item,
            "option_rows": option_rows,
            "feedback": "",
            "current_number": current_index + 1,
            "total_count": len(items),
        },
    )


@login_required
def translation_test_done_view(request):
    session_data = request.session.get(TRANSLATION_TEST_SESSION_KEY)

    if not session_data:
        return redirect("translation_test_setup")

    results = session_data.get("results", [])
    total_count = len(results)
    correct_count = sum(1 for item in results if item.get("is_correct"))
    wrong_count = total_count - correct_count

    request.session.pop(TRANSLATION_TEST_SESSION_KEY, None)
    request.session.modified = True

    return render(
        request,
        "study/translation_test_done.html",
        {
            "results": results,
            "total_count": total_count,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
        },
    )


@login_required
@require_POST
def ai_check_sentences_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "ok": False,
                "error": "Invalid JSON request.",
            },
            status=400,
        )

    card_id = payload.get("card_id")
    raw_sentences = payload.get("sentences", [])

    if not card_id:
        return JsonResponse(
            {
                "ok": False,
                "error": "card_id is required.",
            },
            status=400,
        )

    if not isinstance(raw_sentences, list):
        return JsonResponse(
            {
                "ok": False,
                "error": "sentences must be a list.",
            },
            status=400,
        )

    sentences = [
        str(sentence).strip()
        for sentence in raw_sentences
        if str(sentence).strip()
    ]

    if not sentences:
        return JsonResponse(
            {
                "ok": False,
                "error": "Write at least one sentence first.",
            },
            status=400,
        )

    card = get_user_card_or_404(request.user, card_id)

    prompt = build_sentence_check_prompt(
        word=card.question,
        translation=card.answer,
        context=card.context,
        sentences=sentences,
    )

    try:
        result = check_sentences_with_gemini(prompt)
    except AIServiceError as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status=502,
        )

    return JsonResponse(
        {
            "ok": True,
            "result": result.model_dump(),
        }
    )