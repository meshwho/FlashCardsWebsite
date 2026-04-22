from dataclasses import dataclass

from django.db import transaction
from datetime import timedelta
from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler

from .models import Card, ReviewLog
from .selectors import get_user_review_slots
from .scheduling import snap_due_to_next_slot

FSRS_DESIRED_RETENTION = 0.96

@dataclass(frozen=True)
class ReviewOutcome:
    card: Card
    review_log: ReviewLog


class FSRSService:
    def __init__(self, scheduler=None):
        self.scheduler = scheduler or Scheduler(
            desired_retention=0.96,
            learning_steps=(
                timedelta(minutes=1),
                timedelta(minutes=10),
            ),
            relearning_steps=(
                timedelta(minutes=10),
            ),
            maximum_interval=365,
            enable_fuzzing=True,
        )

    def _fsrs_state_to_model_state(self, state_value):
        if hasattr(state_value, "name"):
            return state_value.name

        text = str(state_value)
        if "." in text:
            text = text.split(".")[-1]
        return text

    def _build_fsrs_card(self, card: Card) -> FSRSCard:
        if card.fsrs_state:
            return FSRSCard.from_json(card.fsrs_state)
        return FSRSCard()

    def _apply_fsrs_card_to_model(self, model_card: Card, fsrs_card: FSRSCard) -> Card:
        model_card.fsrs_state = fsrs_card.to_json()
        model_card.due = fsrs_card.due
        model_card.stability = float(getattr(fsrs_card, "stability", 0.0) or 0.0)
        model_card.difficulty = float(getattr(fsrs_card, "difficulty", 0.0) or 0.0)
        model_card.state = self._fsrs_state_to_model_state(fsrs_card.state)
        model_card.last_review = getattr(fsrs_card, "last_review", None)
        return model_card

    def _to_rating(self, rating_value: int) -> Rating:
        rating_map = {
            1: Rating.Again,
            2: Rating.Hard,
            3: Rating.Good,
            4: Rating.Easy,
        }

        try:
            return rating_map[rating_value]
        except KeyError as exc:
            raise ValueError(f"Unsupported rating value: {rating_value}") from exc

    @transaction.atomic
    def review_card(self, card: Card, rating_value: int) -> ReviewOutcome:
        rating = self._to_rating(rating_value)
        fsrs_card = self._build_fsrs_card(card)

        updated_fsrs_card, _fsrs_review_log = self.scheduler.review_card(fsrs_card, rating)

        slot_times = get_user_review_slots(card.owner)

        schedule = getattr(card.owner, "review_schedule", None)
        tz_name = schedule.timezone if schedule else "Europe/Zaporozhye"

        updated_fsrs_card.due = snap_due_to_next_slot(
            updated_fsrs_card.due,
            slot_times,
            tz_name=tz_name,
        )

        due_before = card.due

        self._apply_fsrs_card_to_model(card, updated_fsrs_card)
        card.save()

        review_log = ReviewLog.objects.create(
            card=card,
            rating=rating_value,
            due_before=due_before,
            due_after=card.due,
        )

        return ReviewOutcome(card=card, review_log=review_log)