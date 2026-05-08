from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from .models import ActiveUseAttempt, CardActiveState


@dataclass(frozen=True)
class StageProgressionResult:
    active_state: CardActiveState
    old_stage: str
    new_stage: str
    changed: bool
    reason: str


class ActiveStageService:
    """
    Handles active-use stage progression.

    This service does NOT update Active-FSRS scheduling logic directly,
    except when a stage changes and we intentionally bring the next task closer.

    Active-FSRS answers: WHEN to review active use.
    This service answers: WHAT stage the card is currently on.
    """

    STAGE_ORDER = [
        CardActiveState.STAGE_RECALL,
        CardActiveState.STAGE_PHRASE,
        CardActiveState.STAGE_CLOZE,
        CardActiveState.STAGE_SENTENCE,
        CardActiveState.STAGE_SITUATION,
        CardActiveState.STAGE_ARGUMENTATION,
        CardActiveState.STAGE_ACTIVE,
    ]

    STAGE_SUCCESS_FIELD = {
        CardActiveState.STAGE_RECALL: "recall_success_count",
        CardActiveState.STAGE_PHRASE: "phrase_success_count",
        CardActiveState.STAGE_CLOZE: "cloze_success_count",
        CardActiveState.STAGE_SENTENCE: "sentence_success_count",
        CardActiveState.STAGE_SITUATION: "situation_success_count",
        CardActiveState.STAGE_ARGUMENTATION: "argumentation_success_count",
    }

    SIMPLE_ADVANCEMENT_REQUIRED_SUCCESSES = {
        CardActiveState.STAGE_RECALL: 2,
        CardActiveState.STAGE_PHRASE: 2,
        CardActiveState.STAGE_CLOZE: 2,
    }

    DATE_BASED_ADVANCEMENT_RULES = {
        CardActiveState.STAGE_SENTENCE: {
            "required_successes": 3,
            "required_days": 2,
        },
        CardActiveState.STAGE_SITUATION: {
            "required_successes": 3,
            "required_days": 3,
        },
        CardActiveState.STAGE_ARGUMENTATION: {
            "required_successes": 3,
            "required_days": 3,
        },
    }

    def apply_after_attempt(
        self,
        *,
        active_state: CardActiveState,
        active_attempt: ActiveUseAttempt,
    ) -> StageProgressionResult:
        """
        Apply stage progression after a saved ActiveUseAttempt.

        Expected call order:
        1. ActiveFSRSService creates ActiveUseAttempt.
        2. ActiveFSRSService updates active counters.
        3. This service updates stage-specific counters and stage.
        """

        old_stage = active_state.stage

        if old_stage in {
            CardActiveState.STAGE_PASSIVE,
            CardActiveState.STAGE_CANDIDATE,
            CardActiveState.STAGE_PAUSED,
            CardActiveState.STAGE_ACTIVE,
        }:
            return StageProgressionResult(
                active_state=active_state,
                old_stage=old_stage,
                new_stage=old_stage,
                changed=False,
                reason="Stage is not eligible for normal progression.",
            )

        if active_attempt.is_success:
            self._increment_stage_success_counter(
                active_state=active_state,
                stage=old_stage,
            )

            if self._can_advance(active_state=active_state, stage=old_stage):
                new_stage = self._get_next_stage(old_stage)
                self._advance_to_stage(
                    active_state=active_state,
                    new_stage=new_stage,
                )

                return StageProgressionResult(
                    active_state=active_state,
                    old_stage=old_stage,
                    new_stage=new_stage,
                    changed=True,
                    reason="Success threshold reached.",
                )

            active_state.save()
            return StageProgressionResult(
                active_state=active_state,
                old_stage=old_stage,
                new_stage=old_stage,
                changed=False,
                reason="Successful attempt saved, threshold not reached yet.",
            )

        if self._has_two_consecutive_again_attempts(active_state):
            new_stage = self._get_previous_stage(old_stage)
            self._demote_to_stage(
                active_state=active_state,
                new_stage=new_stage,
            )

            return StageProgressionResult(
                active_state=active_state,
                old_stage=old_stage,
                new_stage=new_stage,
                changed=(new_stage != old_stage),
                reason="Two consecutive Again attempts.",
            )

        active_state.save()
        return StageProgressionResult(
            active_state=active_state,
            old_stage=old_stage,
            new_stage=old_stage,
            changed=False,
            reason="Failed attempt saved, no demotion yet.",
        )

    def activate_candidate(self, active_state: CardActiveState) -> StageProgressionResult:
        """
        Move a candidate card into the active pipeline.

        This will be used later by the queue manager.
        """
        old_stage = active_state.stage

        if active_state.stage != CardActiveState.STAGE_CANDIDATE:
            return StageProgressionResult(
                active_state=active_state,
                old_stage=old_stage,
                new_stage=old_stage,
                changed=False,
                reason="Only candidate cards can be activated by this method.",
            )

        active_state.stage = CardActiveState.STAGE_RECALL
        active_state.is_active_pipeline = True
        active_state.active_started_at = active_state.active_started_at or timezone.now()
        active_state.active_due = timezone.now()
        active_state.save(
            update_fields=[
                "stage",
                "is_active_pipeline",
                "active_started_at",
                "active_due",
            ]
        )

        return StageProgressionResult(
            active_state=active_state,
            old_stage=old_stage,
            new_stage=CardActiveState.STAGE_RECALL,
            changed=True,
            reason="Candidate moved into active pipeline.",
        )

    def pause_active_practice(
        self,
        active_state: CardActiveState,
        *,
        reason: str = "",
    ) -> StageProgressionResult:
        old_stage = active_state.stage

        active_state.stage = CardActiveState.STAGE_PAUSED
        active_state.is_active_pipeline = False

        if reason:
            active_state.last_error_summary = reason

        active_state.save(
            update_fields=[
                "stage",
                "is_active_pipeline",
                "last_error_summary",
            ]
        )

        return StageProgressionResult(
            active_state=active_state,
            old_stage=old_stage,
            new_stage=CardActiveState.STAGE_PAUSED,
            changed=True,
            reason=reason or "Active practice paused.",
        )

    def _increment_stage_success_counter(
        self,
        *,
        active_state: CardActiveState,
        stage: str,
    ) -> None:
        field_name = self.STAGE_SUCCESS_FIELD.get(stage)

        if not field_name:
            return

        current_value = getattr(active_state, field_name)
        setattr(active_state, field_name, current_value + 1)

    def _can_advance(
        self,
        *,
        active_state: CardActiveState,
        stage: str,
    ) -> bool:
        if stage in self.SIMPLE_ADVANCEMENT_REQUIRED_SUCCESSES:
            field_name = self.STAGE_SUCCESS_FIELD[stage]
            required_successes = self.SIMPLE_ADVANCEMENT_REQUIRED_SUCCESSES[stage]

            return getattr(active_state, field_name) >= required_successes

        if stage in self.DATE_BASED_ADVANCEMENT_RULES:
            rule = self.DATE_BASED_ADVANCEMENT_RULES[stage]

            success_count = self._get_success_attempt_count_for_stage(
                active_state=active_state,
                stage=stage,
            )
            success_days = self._get_success_attempt_day_count_for_stage(
                active_state=active_state,
                stage=stage,
            )

            return (
                success_count >= rule["required_successes"]
                and success_days >= rule["required_days"]
            )

        return False

    def _get_success_attempt_count_for_stage(
        self,
        *,
        active_state: CardActiveState,
        stage: str,
    ) -> int:
        return ActiveUseAttempt.objects.filter(
            card=active_state.card,
            stage=stage,
            is_success=True,
            reviewed_at__isnull=False,
        ).count()

    def _get_success_attempt_day_count_for_stage(
        self,
        *,
        active_state: CardActiveState,
        stage: str,
    ) -> int:
        attempts = ActiveUseAttempt.objects.filter(
            card=active_state.card,
            stage=stage,
            is_success=True,
            reviewed_at__isnull=False,
        ).only("reviewed_at")

        days = {
            timezone.localtime(attempt.reviewed_at).date()
            for attempt in attempts
            if attempt.reviewed_at is not None
        }

        return len(days)

    def _get_next_stage(self, stage: str) -> str:
        try:
            index = self.STAGE_ORDER.index(stage)
        except ValueError:
            return stage

        if index >= len(self.STAGE_ORDER) - 1:
            return stage

        return self.STAGE_ORDER[index + 1]

    def _get_previous_stage(self, stage: str) -> str:
        try:
            index = self.STAGE_ORDER.index(stage)
        except ValueError:
            return stage

        if index <= 0:
            return stage

        return self.STAGE_ORDER[index - 1]

    def _advance_to_stage(
        self,
        *,
        active_state: CardActiveState,
        new_stage: str,
    ) -> None:
        now = timezone.now()

        active_state.stage = new_stage
        active_state.consecutive_active_failures = 0

        # When entering a new stage, we do not want Active-FSRS to postpone it too far.
        # The next task should appear soon so the new stage starts quickly.
        if new_stage == CardActiveState.STAGE_ACTIVE:
            active_state.activated_at = active_state.activated_at or now
            active_state.active_due = now + timedelta(days=7)
        else:
            active_state.active_due = now + timedelta(days=1)

        active_state.save(
            update_fields=[
                "stage",
                "consecutive_active_failures",
                "activated_at",
                "active_due",
                "recall_success_count",
                "phrase_success_count",
                "cloze_success_count",
                "sentence_success_count",
                "situation_success_count",
                "argumentation_success_count",
            ]
        )

    def _demote_to_stage(
        self,
        *,
        active_state: CardActiveState,
        new_stage: str,
    ) -> None:
        now = timezone.now()

        active_state.stage = new_stage
        active_state.active_due = now + timedelta(days=1)

        active_state.save(
            update_fields=[
                "stage",
                "active_due",
                "consecutive_active_failures",
                "last_error_summary",
            ]
        )

    def _has_two_consecutive_again_attempts(
        self,
        active_state: CardActiveState,
    ) -> bool:
        recent_attempts = list(
            ActiveUseAttempt.objects.filter(card=active_state.card)
            .order_by("-created_at")[:2]
        )

        if len(recent_attempts) < 2:
            return False

        return all(
            attempt.rating == ActiveUseAttempt.RATING_AGAIN
            for attempt in recent_attempts
        )