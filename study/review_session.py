from collections import Counter


SESSION_KEY = "review_session_summary"


RATING_LABELS = {
    1: "Again",
    2: "Hard",
    3: "Good",
    4: "Easy",
}


def start_review_session(request):
    request.session[SESSION_KEY] = {
        "reviews": [],
        "retry_queue": [],
    }
    request.session.modified = True

def enqueue_review_retry(request, card, direction="forward"):
    session = request.session.get(
        SESSION_KEY,
        {
            "reviews": [],
            "retry_queue": [],
        },
    )

    retry_queue = session.setdefault("retry_queue", [])
    card_id = str(card.id)

    # Не добавляем одну карточку несколько раз.
    already_queued = any(
        item.get("card_id") == card_id
        for item in retry_queue
    )

    if not already_queued:
        retry_queue.append(
            {
                "card_id": card_id,
                "direction": direction,
            }
        )

    request.session[SESSION_KEY] = session
    request.session.modified = True


def get_current_review_retry(request):
    session = request.session.get(SESSION_KEY)

    if not session:
        return None

    retry_queue = session.get("retry_queue", [])

    if not retry_queue:
        return None

    return retry_queue[0]


def complete_current_review_retry(request):
    session = request.session.get(SESSION_KEY)

    if not session:
        return

    retry_queue = session.get("retry_queue", [])

    if retry_queue:
        retry_queue.pop(0)

    session["retry_queue"] = retry_queue
    request.session[SESSION_KEY] = session
    request.session.modified = True


def get_review_retry_count(request):
    session = request.session.get(SESSION_KEY)

    if not session:
        return 0

    return len(session.get("retry_queue", []))

def add_review_to_session(
    request,
    card,
    rating_value,
    user_answer="",
    hints_used=0,
    direction="forward",
    prompt_text="",
    expected_answer="",
):
    summary = request.session.get(SESSION_KEY, {"reviews": []})

    direction_label = (
        "German → Translation"
        if direction != "reverse"
        else "Translation → German"
    )

    summary["reviews"].append(
        {
            "card_id": str(card.id),
            "question": prompt_text or card.question,
            "expected_answer": expected_answer or card.answer,
            "direction": direction,
            "direction_label": direction_label,
            "user_answer": user_answer,
            "hints_used": hints_used,
            "rating_value": rating_value,
            "rating_label": RATING_LABELS.get(rating_value, str(rating_value)),
            "due_after": card.due.isoformat() if card.due else None,
        }
    )

    request.session[SESSION_KEY] = summary
    request.session.modified = True
def get_review_session_summary(request):
    summary = request.session.get(SESSION_KEY, {"reviews": []})
    reviews = summary.get("reviews", [])

    counter = Counter(item["rating_label"] for item in reviews)

    return {
        "reviews": reviews,
        "total_reviewed": len(reviews),
        "again_count": counter.get("Again", 0),
        "hard_count": counter.get("Hard", 0),
        "good_count": counter.get("Good", 0),
        "easy_count": counter.get("Easy", 0),
    }


def clear_review_session(request):
    if SESSION_KEY in request.session:
        del request.session[SESSION_KEY]
        request.session.modified = True