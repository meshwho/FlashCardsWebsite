SESSION_KEY = "pending_sentence_task"


def set_pending_sentence_task(
    request,
    *,
    card_id,
    source_mode,
    rating_value,
    required_count,
    return_url_name,
    return_url_kwargs=None,
):
    request.session[SESSION_KEY] = {
        "card_id": str(card_id),
        "source_mode": source_mode,
        "rating_value": rating_value,
        "required_count": required_count,
        "return_url_name": return_url_name,
        "return_url_kwargs": return_url_kwargs or {},
    }
    request.session.modified = True


def get_pending_sentence_task(request):
    return request.session.get(SESSION_KEY)


def clear_pending_sentence_task(request):
    if SESSION_KEY in request.session:
        del request.session[SESSION_KEY]
        request.session.modified = True