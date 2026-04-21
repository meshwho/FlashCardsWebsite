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
        "reviews": []
    }
    request.session.modified = True


def add_review_to_session(request, card, rating_value, user_answer="", hints_used=0):
    summary = request.session.get(SESSION_KEY, {"reviews": []})

    summary["reviews"].append(
        {
            "card_id": str(card.id),
            "question": card.question,
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