from django.contrib import admin
from .models import Card, Deck, ReviewLog


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "created_at")
    search_fields = ("title", "owner__username")


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deck",
        "short_question",
        "due",
        "state",
        "stability",
        "difficulty",
        "last_review",
    )
    list_filter = ("state", "deck")
    search_fields = ("question", "answer", "deck__title")

    def short_question(self, obj):
        return obj.question[:50]


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "card",
        "rating",
        "reviewed_at",
        "due_before",
        "due_after",
    )
    list_filter = ("rating", "reviewed_at")