from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.utils import timezone


def snap_due_to_next_slot(due_dt, slot_times, tz_name="Europe/Zaporozhye"):
    """
    Round a due datetime up to the next allowed user review slot.
    If there are no slots, return the original due datetime.
    """
    if not slot_times:
        return due_dt

    tz = ZoneInfo(tz_name)

    reference_dt = max(due_dt, timezone.now())
    local_due = timezone.localtime(reference_dt, tz)

    current_date = local_due.date()

    # Search the current day and next days until a slot is found
    for day_offset in range(0, 30):
        target_date = current_date + timedelta(days=day_offset)

        for slot_time in slot_times:
            candidate_local = datetime.combine(target_date, slot_time)
            candidate_local = timezone.make_aware(candidate_local, tz)

            if candidate_local >= local_due:
                return candidate_local.astimezone(dt_timezone.utc)

    # Fallback: return original if something unexpected happens
    return due_dt