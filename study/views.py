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
    decks = get_user_decks(request.user)
    return render(request, "study/deck_list.html", {"decks": decks})


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

    if request.method == "POST":
        rating_value = int(request.POST["rating"])
        service = FSRSService()
        outcome = service.review_card(card, rating_value)

        add_review_to_session(request, outcome.card, rating_value)

        next_card = get_next_due_card_for_user(request.user)
        if next_card is None:
            return redirect("review_done")

        return redirect("review_card")

    remaining_count = get_due_cards_for_user(request.user).count()

    return render(
        request,
        "study/review_card.html",
        {
            "card": card,
            "remaining_count": remaining_count,
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