import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Deck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="decks",
    )
    title = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "title"],
                name="unique_deck_title_per_user",
            )
        ]

    def __str__(self):
        return self.title


class Card(models.Model):
    STATE_LEARNING = "Learning"
    STATE_REVIEW = "Review"
    STATE_RELEARNING = "Relearning"

    STATE_CHOICES = [
        (STATE_LEARNING, "Learning"),
        (STATE_REVIEW, "Review"),
        (STATE_RELEARNING, "Relearning"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    deck = models.ForeignKey(
        Deck,
        on_delete=models.CASCADE,
        related_name="cards",
    )
    question = models.TextField()
    answer = models.TextField()
    has_article = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Read model fields for querying and UI
    due = models.DateTimeField(default=timezone.now)
    stability = models.FloatField(default=0.0)
    difficulty = models.FloatField(default=0.0)
    state = models.CharField(
        max_length=32,
        choices=STATE_CHOICES,
        default=STATE_LEARNING,
    )
    last_review = models.DateTimeField(null=True, blank=True)

    # Source of truth for FSRS
    fsrs_state = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["due", "created_at"]

    def __str__(self):
        return self.question[:80]

    @property
    def owner(self):
        return self.deck.owner

    @property
    def is_due(self):
        return self.due <= timezone.now()

    def initialize_fsrs_defaults(self):
        from fsrs import Card as FSRSCard

        fsrs_card = FSRSCard()
        self.fsrs_state = fsrs_card.to_json()

        self.due = fsrs_card.due
        self.stability = float(getattr(fsrs_card, "stability", 0.0) or 0.0)
        self.difficulty = float(getattr(fsrs_card, "difficulty", 0.0) or 0.0)

        state_value = fsrs_card.state
        if hasattr(state_value, "name"):
            self.state = state_value.name
        else:
            text = str(state_value)
            if "." in text:
                text = text.split(".")[-1]
            self.state = text

        self.last_review = getattr(fsrs_card, "last_review", None)

    def save(self, *args, **kwargs):
        if self._state.adding and not self.fsrs_state:
            self.initialize_fsrs_defaults()
        super().save(*args, **kwargs)


class ReviewLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    RATING_CHOICES = [
        (1, "Again"),
        (2, "Hard"),
        (3, "Good"),
        (4, "Easy"),
    ]

    card = models.ForeignKey(
        Card,
        on_delete=models.CASCADE,
        related_name="review_logs",
    )
    reviewed_at = models.DateTimeField(auto_now_add=True)
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    due_before = models.DateTimeField()
    due_after = models.DateTimeField()

    class Meta:
        ordering = ["-reviewed_at"]

    def __str__(self):
        return f"Review(card={self.card_id}, rating={self.rating})"


class UserReviewSchedule(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_schedule",
    )
    timezone = models.CharField(max_length=64, default="Europe/Zaporozhye")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Review schedule for {self.user.username}"


class ReviewSlot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    schedule = models.ForeignKey(
        UserReviewSchedule,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    position = models.PositiveSmallIntegerField()
    time = models.TimeField()

    class Meta:
        ordering = ["position", "time"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "position"],
                name="unique_slot_position_per_schedule",
            )
        ]

    def __str__(self):
        return f"{self.schedule.user.username} - {self.time}"

class SentenceAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    card = models.ForeignKey(
        Card,
        on_delete=models.CASCADE,
        related_name="sentence_attempts",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sentence_attempts",
    )

    source_mode = models.CharField(
        max_length=32,
        choices=[
            ("fsrs", "FSRS"),
            ("typing_practice", "Typing Practice"),
            ("article_practice", "Article Practice"),
        ],
    )

    sentence = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"SentenceAttempt({self.user_id}, {self.card_id}, {self.source_mode})"