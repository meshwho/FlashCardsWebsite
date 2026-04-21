from django.urls import path

from .views import (
    dashboard_view,
    deck_create_view,
    deck_detail_view,
    deck_edit_view,
    deck_list_view,
    review_card_view,
    review_done_view,
    signup_view,
    start_review_session_view,
    study_today_view,
)

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("signup/", signup_view, name="signup"),
    path("decks/", deck_list_view, name="deck_list"),
    path("decks/create/", deck_create_view, name="deck_create"),
    path("decks/<uuid:deck_id>/", deck_detail_view, name="deck_detail"),
    path("decks/<uuid:deck_id>/edit/", deck_edit_view, name="deck_edit"),
    path("study/", study_today_view, name="study_today"),
    path("study/start/", start_review_session_view, name="study_start"),
    path("study/review/", review_card_view, name="review_card"),
    path("study/done/", review_done_view, name="review_done"),
]