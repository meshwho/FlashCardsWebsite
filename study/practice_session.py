import random


SESSION_KEY = "deck_practice_session"


def start_deck_practice_session(
    request,
    deck,
    mode,
    card_ids,
    require_sentences_after_mistake=False,
):
    random.shuffle(card_ids)

    directions = []
    if mode == "typing":
        start_forward = random.choice([True, False])
        for idx, _ in enumerate(card_ids):
            is_forward = start_forward if idx % 2 == 0 else not start_forward
            directions.append("forward" if is_forward else "reverse")
    else:
        directions = ["forward"] * len(card_ids)

    request.session[SESSION_KEY] = {
        "deck_id": str(deck.id),
        "mode": mode,
        "card_ids": [str(card_id) for card_id in card_ids],
        "directions": directions,
        "current_index": 0,
        "summary": [],
        "require_sentences_after_mistake": require_sentences_after_mistake,
    }
    request.session.modified = True


def get_practice_session(request):
    return request.session.get(SESSION_KEY)


def clear_practice_session(request):
    if SESSION_KEY in request.session:
        del request.session[SESSION_KEY]
        request.session.modified = True


def get_current_card_id(request):
    session = get_practice_session(request)
    if not session:
        return None

    index = session.get("current_index", 0)
    card_ids = session.get("card_ids", [])

    if index >= len(card_ids):
        return None

    return card_ids[index]


def get_current_direction(request):
    session = get_practice_session(request)
    if not session:
        return "forward"

    index = session.get("current_index", 0)
    directions = session.get("directions", [])

    if index >= len(directions):
        return "forward"

    return directions[index]


def get_remaining_count(request):
    session = get_practice_session(request)
    if not session:
        return 0

    total = len(session.get("card_ids", []))
    index = session.get("current_index", 0)
    return max(total - index, 0)


def advance_practice_session(request):
    session = get_practice_session(request)
    if not session:
        return

    session["current_index"] = session.get("current_index", 0) + 1
    request.session[SESSION_KEY] = session
    request.session.modified = True


def go_back_practice_session(request):
    session = get_practice_session(request)
    if not session:
        return

    current_index = session.get("current_index", 0)
    session["current_index"] = max(current_index - 1, 0)

    summary = session.get("summary", [])
    if summary:
        summary.pop()

    session["summary"] = summary
    request.session[SESSION_KEY] = session
    request.session.modified = True


def add_practice_summary_item(request, item):
    session = get_practice_session(request)
    if not session:
        return

    session.setdefault("summary", []).append(item)
    request.session[SESSION_KEY] = session
    request.session.modified = True


def should_require_sentences_in_practice(request):
    session = get_practice_session(request)
    if not session:
        return False
    return bool(session.get("require_sentences_after_mistake", False))


def get_practice_summary(request):
    session = get_practice_session(request)
    if not session:
        return {
            "mode": None,
            "total": 0,
            "again_count": 0,
            "hard_count": 0,
            "good_count": 0,
            "easy_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "perfect_count": 0,
            "after_mistakes_count": 0,
            "total_mistakes": 0,
            "der_count": 0,
            "die_count": 0,
            "das_count": 0,
            "items": [],
        }

    items = session.get("summary", [])

    if session.get("mode") == "articles":
        return {
            "mode": session.get("mode"),
            "total": len(items),
            "perfect_count": sum(1 for item in items if item.get("mistakes_count", 0) == 0),
            "after_mistakes_count": sum(1 for item in items if item.get("mistakes_count", 0) > 0),
            "total_mistakes": sum(item.get("mistakes_count", 0) for item in items),
            "der_count": sum(1 for item in items if item.get("chosen_article") == "der"),
            "die_count": sum(1 for item in items if item.get("chosen_article") == "die"),
            "das_count": sum(1 for item in items if item.get("chosen_article") == "das"),
            "items": items,
        }

    return {
        "mode": session.get("mode"),
        "total": len(items),
        "again_count": sum(1 for item in items if item.get("rating_label") == "Again"),
        "hard_count": sum(1 for item in items if item.get("rating_label") == "Hard"),
        "good_count": sum(1 for item in items if item.get("rating_label") == "Good"),
        "easy_count": sum(1 for item in items if item.get("rating_label") == "Easy"),
        "correct_count": sum(1 for item in items if item.get("is_correct") is True),
        "wrong_count": sum(1 for item in items if item.get("is_correct") is False),
        "der_count": sum(1 for item in items if item.get("chosen_article") == "der"),
        "die_count": sum(1 for item in items if item.get("chosen_article") == "die"),
        "das_count": sum(1 for item in items if item.get("chosen_article") == "das"),
        "items": items,
    }
