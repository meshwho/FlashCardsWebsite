from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import CardInlineFormSet, DeckForm, SignUpForm
from .review_session import (
    add_review_to_session,
    clear_review_session,
    get_review_session_summary,
    start_review_session,
)
from .selectors import (
    get_due_cards_for_user,
    get_next_due_card_for_user,
    get_user_deck_or_404,
    get_user_decks,
    get_weekly_due_schedule_for_user,
)
from .services import FSRSService


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

    return render(
        request,
        "study/dashboard.html",
        {
            "due_count": due_count,
            "weekly_schedule": weekly_schedule,
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