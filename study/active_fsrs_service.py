from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler

from .models import ActiveUseAttempt, Card, CardActiveState


@dataclass(frozen=True)
class ActiveReviewOutcome:
    card: Card
    active_state: CardActiveState
    active_attempt: ActiveUseAttempt


class ActiveFSRSService:
    """
    Separate FSRS layer for active word usage.

    This service must never update the normal memory FSRS fields on Card:
    - card.due
    - card.fsrs_state
    - card.stability
    - card.difficulty
    - card.state
    - card.last_review

    It only updates CardActiveState fields.
    """

    def __init__(self, scheduler=None):
        self.scheduler = scheduler or Scheduler(
            desired_retention=0.90,
            learning_steps=(
                timedelta(hours=12),
                timedelta(days=1),
            ),
            relearning_steps=(
                timedelta(days=1),
            ),
            maximum_interval=90,
            enable_fuzzing=True,
        )

    def _build_fsrs_card(self, active_state: CardActiveState) -> FSRSCard:
        if active_state.active_fsrs_state:
            return FSRSCard.from_json(active_state.active_fsrs_state)

        return FSRSCard()

    def _apply_fsrs_card_to_active_state(
        self,
        active_state: CardActiveState,
        fsrs_card: FSRSCard,
    ) -> CardActiveState:
        active_state.active_fsrs_state = fsrs_card.to_json()
        active_state.active_due = fsrs_card.due
        active_state.active_stability = float(
            getattr(fsrs_card, "stability", 0.0) or 0.0
        )
        active_state.active_difficulty = float(
            getattr(fsrs_card, "difficulty", 0.0) or 0.0
        )
        active_state.last_active_review = getattr(fsrs_card, "last_review", None)

        return active_state

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
            raise ValueError(f"Unsupported active rating value: {rating_value}") from exc

    def _is_success(self, rating_value: int, active_use: bool) -> bool:
        return rating_value in {
            ActiveUseAttempt.RATING_GOOD,
            ActiveUseAttempt.RATING_EASY,
        } and active_use

    @transaction.atomic
    def review_active_card(
        self,
        *,
        card: Card,
        user,
        rating_value: int,
        stage: str | None = None,
        task_type: str = "",
        generated_prompt: str = "",
        user_answer: str = "",
        chatgpt_response: str = "",
        active_use: bool = False,
        error_summary: str = "",
        source: str = ActiveUseAttempt.SOURCE_MANUAL_RATING,
    ) -> ActiveReviewOutcome:
        """
        Review active usage of a card.

        This method:
        - creates or gets CardActiveState;
        - updates only Active-FSRS fields;
        - creates ActiveUseAttempt;
        - updates basic active counters;
        - does not change normal Card FSRS fields.
        """

        active_state, _created = CardActiveState.objects.get_or_create(
            card=card,
            defaults={
                "stage": CardActiveState.STAGE_PASSIVE,
            },
        )

        current_stage = stage or active_state.stage

        rating = self._to_rating(rating_value)
        fsrs_card = self._build_fsrs_card(active_state)

        updated_fsrs_card, _fsrs_review_log = self.scheduler.review_card(
            fsrs_card,
            rating,
        )

        self._apply_fsrs_card_to_active_state(active_state, updated_fsrs_card)

        is_success = self._is_success(
            rating_value=rating_value,
            active_use=active_use,
        )

        active_state.total_active_attempts += 1

        if is_success:
            active_state.successful_active_attempts += 1
            active_state.consecutive_active_failures = 0
        else:
            active_state.failed_active_attempts += 1
            active_state.consecutive_active_failures += 1

        if error_summary:
            active_state.last_error_summary = error_summary

        active_state.save()

        active_attempt = ActiveUseAttempt.objects.create(
            card=card,
            user=user,
            stage=current_stage,
            task_type=task_type,
            generated_prompt=generated_prompt,
            user_answer=user_answer,
            chatgpt_response=chatgpt_response,
            rating=rating_value,
            active_use=active_use,
            is_success=is_success,
            error_summary=error_summary,
            source=source,
            reviewed_at=timezone.now(),
        )

        return ActiveReviewOutcome(
            card=card,
            active_state=active_state,
            active_attempt=active_attempt,
        )