from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from .review_session import (
    add_review_to_session,
    clear_review_session,
    get_review_session_summary,
    start_review_session,
)
from .services import FSRSService
from django.contrib import messages
from django.db import transaction
from .forms import (
    CardInlineFormSet,
    DeckForm,
    ReviewScheduleForm,
    ReviewSlotFormSet,
    SignUpForm,
)
from .models import ReviewSlot
from .schedule_services import reschedule_all_user_cards
from .selectors import (
    ensure_default_review_slots,
    get_due_cards_for_user,
    get_next_due_card_for_user,
    get_or_create_user_review_schedule,
    get_user_deck_or_404,
    get_user_decks,
    get_user_review_slots,
    get_weekly_due_schedule_for_user,
)
from .review_logic import (
    MAX_HINTS,
    build_hint_mask,
    get_rating_from_result,
    is_correct_answer,
)
from collections import Counter

from .practice_logic import MAX_HINTS, get_hint_text, get_prompt_and_expected, get_typing_result
from .practice_session import (
    add_practice_summary_item,
    advance_practice_session,
    clear_practice_session,
    get_current_card_id,
    get_current_direction,
    get_practice_session,
    get_practice_summary,
    get_remaining_count,
    start_deck_practice_session,
)
from .selectors import get_user_card_or_404, get_user_deck_cards
from .practice_session import go_back_practice_session
from django.db.models import Count
from django.utils import timezone
from .models import Card, Deck, ReviewLog, ReviewSlot
from .article_logic import split_article_and_word, is_correct_article_choice
from .deck_metrics import enrich_deck_with_memory_score, enrich_decks_with_memory_scores

def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
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
        schedule_form = ReviewScheduleForm(
            request.POST,
            instance=schedule,
            slots_count=len(existing_slots) or 3,
        )

        reviews_per_day = int(request.POST.get("reviews_per_day", len(existing_slots) or 3))
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
                for idx, form in enumerate(slot_formset.forms, start=1):
                    slot_time = form.cleaned_data["time"]
                    cleaned_slots.append(
                        ReviewSlot(
                            schedule=schedule,
                            position=idx,
                            time=slot_time,
                        )
                    )

                ReviewSlot.objects.bulk_create(cleaned_slots)

                updated_count = reschedule_all_user_cards(request.user)

            messages.success(
                request,
                f"Schedule saved. Updated {updated_count} card due times."
            )
            return redirect("dashboard")
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
            deck_form.save()
            card_formset.save()
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
    card = get_next_due_card_for_user(request.user)

    if card is None:
        return redirect("review_done")

    remaining_count = get_due_cards_for_user(request.user).count()

    hints_used = 0
    user_answer = ""
    hint_text = ""
    feedback = ""
    feedback_type = ""
    answer_revealed = False

    if request.method == "POST":
        action = request.POST.get("action")
        user_answer = request.POST.get("user_answer", "").strip()
        hints_used = int(request.POST.get("hints_used", 0))

        if action == "hint":
            hints_used = min(hints_used + 1, MAX_HINTS)
            hint_text = build_hint_mask(card.answer, hints_used)

        elif action == "check":
            if is_correct_answer(user_answer, card.answer):
                rating_value = get_rating_from_result(hints_used, knows_answer=True)
                service = FSRSService()
                outcome = service.review_card(card, rating_value)

                add_review_to_session(
                    request,
                    outcome.card,
                    rating_value,
                    user_answer=user_answer,
                    hints_used=hints_used,
                )

                next_card = get_next_due_card_for_user(request.user)
                if next_card is None:
                    return redirect("review_done")
                return redirect("review_card")
            else:
                feedback = "Not quite right. Try again or use a hint."
                feedback_type = "error"
                hint_text = build_hint_mask(card.answer, hints_used)

        elif action == "dont_know":
            rating_value = get_rating_from_result(hints_used, knows_answer=False)
            service = FSRSService()
            outcome = service.review_card(card, rating_value)

            add_review_to_session(
                request,
                outcome.card,
                rating_value,
                user_answer=user_answer,
                hints_used=hints_used,
            )

            answer_revealed = True
            feedback = f"Correct answer: {card.answer}"
            feedback_type = "info"

            next_card = get_next_due_card_for_user(request.user)
            if next_card is None:
                return redirect("review_done")
            return redirect("review_card")

    else:
        hint_text = build_hint_mask(card.answer, 0)

    if hints_used > 0 and not hint_text:
        hint_text = build_hint_mask(card.answer, hints_used)

    return render(
        request,
        "study/review_card.html",
        {
            "card": card,
            "remaining_count": remaining_count,
            "hints_used": hints_used,
            "max_hints": MAX_HINTS,
            "hint_text": hint_text,
            "user_answer": user_answer,
            "feedback": feedback,
            "feedback_type": feedback_type,
            "answer_revealed": answer_revealed,
        },
    )


@login_required
def review_done_view(request):
    summary = get_review_session_summary(request)
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
                    },
                )

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

    return render(
        request,
        "study/deck_practice_setup.html",
        {
            "deck": deck,
            "has_cards": True,
            "card_count": len(cards),
            "has_article_cards": any(card.has_article for card in cards),
            "article_card_count": sum(1 for card in cards if card.has_article),
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
    user_answer = ""
    hint_text = ""
    feedback = ""

    if request.method == "POST":
        action = request.POST.get("action")
        user_answer = request.POST.get("user_answer", "").strip()
        hints_used = int(request.POST.get("hints_used", 0))

        if action == "hint":
            hints_used = min(hints_used + 1, MAX_HINTS)
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
                add_practice_summary_item(
                    request,
                    {
                        "question": qa["prompt"],
                        "answer": qa["expected"],
                        "user_answer": user_answer,
                        "hints_used": hints_used,
                        "rating_label": result["rating_label"],
                        "direction_label": qa["direction_label"],
                        "mode": "typing",
                    },
                )

                advance_practice_session(request)

                if get_current_card_id(request) is None:
                    return redirect("deck_practice_done", deck_id=deck.id)

                return redirect("deck_practice_typing", deck_id=deck.id)

            feedback = "Not quite right. Try again or use a hint."
            hint_text = get_hint_text(
                qa["expected"],
                hints_used,
                has_article=card.has_article if direction == "forward" else False,
            )

        elif action == "dont_know":
            result = get_typing_result(
                qa["expected"],
                user_answer,
                hints_used,
                dont_know=True,
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
            "max_hints": MAX_HINTS,
            "hint_text": hint_text,
            "user_answer": user_answer,
            "feedback": feedback,
        },
    )


@login_required
def deck_practice_done_view(request, deck_id):
    deck = get_user_deck_or_404(request.user, deck_id)
    summary = get_practice_summary(request)
    practice_mode = summary.get("mode")
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

    if request.method == "POST":
        chosen_article = request.POST.get("chosen_article", "").strip().lower()
        is_correct = is_correct_article_choice(card.question, chosen_article)

        add_practice_summary_item(
            request,
            {
                "question": word_without_article,
                "answer": card.question,
                "chosen_article": chosen_article,
                "correct_article": correct_article,
                "is_correct": is_correct,
                "mode": "articles",
            },
        )

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