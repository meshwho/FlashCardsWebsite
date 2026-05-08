import json
import random
import re

from .card_duplicates import normalize_card_text
from .models import Card


WORDS_CONTEXT_SESSION_KEY = "words_context_session"
EXTRA_DISTRACTOR_OPTIONS_COUNT = 24

MIN_WORDS_IN_CONTEXT = 4
MAX_WORDS_IN_CONTEXT = 20

WORDS_CONTEXT_LEVELS = [
    "A1.1",
    "A1.2",
    "A2.1",
    "A2.2",
    "B1.1",
    "B1.2",
    "B2.1",
    "B2.2",
]

DEFAULT_WORDS_CONTEXT_LEVEL = "A2.2"


def normalize_option_text(value):
    return " ".join((value or "").strip().lower().split())


def choose_random_cards_for_context(user, count):
    cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .exclude(question__exact="")
        .exclude(answer__exact="")
    )

    random.shuffle(cards)

    selected = []
    seen = set()

    for card in cards:
        key = (
            normalize_card_text(card.question),
            normalize_card_text(card.answer),
        )

        if key in seen:
            continue

        seen.add(key)
        selected.append(card)

        if len(selected) >= count:
            break

    return selected


def serialize_card_for_context(card):
    return {
        "id": str(card.id),
        "word": card.question,
        "translation": card.answer,
        "context": card.context or "",
        "deck": card.deck.title,
    }


def build_words_context_prompt(selected_cards, distractor_cards, text_level):
    lines = []

    lines.append("Ты — преподаватель немецкого языка и автор интересных учебных текстов.")
    lines.append("")
    lines.append(f"Создай один связный, интересный и естественный немецкий текст уровня {text_level}.")
    lines.append("Текст должен быть маленькой историей, сценой из жизни или живой ситуацией, а не сухим набором предложений.")
    lines.append("")
    lines.append("У тебя есть два списка слов:")
    lines.append("1. MAIN WORDS — основные слова. Их обязательно нужно использовать в тексте.")
    lines.append("2. DISTRACTOR WORDS — дополнительные слова. Их можно использовать только как неправильные варианты ответа.")
    lines.append("")
    lines.append("Задача:")
    lines.append("- Используй все MAIN WORDS в немецком тексте.")
    lines.append("- Для каждого MAIN WORD сделай одно упражнение с пропуском.")
    lines.append("- Для каждого упражнения дай ровно 4 варианта ответа: 1 правильный и 3 неправильных.")
    lines.append("- Неправильные варианты выбирай из MAIN WORDS или DISTRACTOR WORDS.")
    lines.append("- Все варианты должны быть в грамматически подходящей форме для данного пропуска.")
    lines.append("- Если правильный ответ стоит в нужном падеже, числе или форме, остальные варианты тоже должны быть даны в форме, которая выглядит грамматически возможной.")
    lines.append("- Но по смыслу только ОДИН вариант должен быть 100% правильным.")
    lines.append("- Остальные 3 варианта должны быть неправильно подобраны по смыслу именно для этого контекста.")
    lines.append("- Не создавай упражнения, где больше одного варианта могут естественно подходить по смыслу.")
    lines.append("- Не создавай слишком общий контекст, если в него могут подойти несколько слов.")
    lines.append("- Делай предложение достаточно конкретным, чтобы правильный ответ был однозначен.")
    lines.append("- Если нужно, добавь больше контекстных деталей в предложение, чтобы исключить другие варианты.")
    lines.append("- Неправильные варианты могут быть грамматически возможны, но должны быть явно неверны по содержанию, ситуации или смыслу.")
    lines.append("- Вопрос должен проверять знание конкретного слова, а не давать несколько разумных ответов.")
    lines.append("- Если правильный ответ является существительным с артиклем, варианты тоже должны быть существительными с подходящим артиклем и в той же грамматической форме.")
    lines.append("- Если правильный ответ является глаголом, варианты тоже должны быть глаголами в подходящей форме.")
    lines.append("- Не смешивай в одном вопросе существительные, глаголы и прилагательные, если это выглядит неестественно.")
    lines.append("")
    lines.append("")
    lines.append("Очень важное правило однозначности:")
    lines.append("- В каждом вопросе должен быть только один однозначно правильный ответ.")
    lines.append("- Остальные варианты не должны подходить по смыслу.")
    lines.append("- Если предложение слишком общее и допускает несколько логичных ответов, перепиши предложение так, чтобы остался только один правильный вариант.")
    lines.append("- Не допускай дубликатов вариантов.")
    lines.append("- Не допускай почти одинаковых вариантов, если они оба могут считаться правильными.")
    lines.append("")
    lines.append("Пример хорошего задания:")
    lines.append("- 'Am Morgen hebt Lukas Geld ab, deshalb muss er zur ____ gehen.'")
    lines.append("- correct_option: 'der Bank'")
    lines.append("- Здесь 'der Bank' — единственный правильный вариант, потому что контекст 'hebt Geld ab' делает ответ однозначным.")
    lines.append("")
    lines.append("Пример плохого задания:")
    lines.append("- 'Zuerst muss er zu ____ gehen, um eine wichtige Sache zu erledigen.'")
    lines.append("- Это плохой вопрос, потому что туда могут подойти несколько слов: 'der Bank', 'dem Büro', 'der Universität' и другие.")
    lines.append("- Такие задания создавать нельзя.")
    lines.append("Правило для артиклей:")
    lines.append("- Если слово в списке дано с артиклем, например 'die Universität', 'das Haus', 'der Termin', вариант ответа должен быть с артиклем.")
    lines.append("- Если в предложении нужен другой падеж, измени артикль правильно.")
    lines.append("- Пример: исходное слово 'die Universität', но в предложении 'in der Universität', тогда correct_option должен быть 'der Universität'.")
    lines.append("- blank_text должен заменять всю группу, включая артикль.")
    lines.append("- Правильно: 'Ich lerne in ____.' → correct_option: 'der Universität'.")
    lines.append("- Неправильно: 'Ich lerne in der ____.' → correct_option: 'Universität'.")
    lines.append("")
    lines.append("Требования к тексту:")
    lines.append(f"- Уровень текста должен соответствовать {text_level}.")
    lines.append("- Текст должен быть интересным и понятным.")
    lines.append("- Не используй слишком сложную грамматику выше выбранного уровня.")
    lines.append("- Не выделяй слова жирным.")
    lines.append("- Не используй markdown.")
    lines.append("- В конце добавь короткий summary на русском языке: о чём был текст и какие слова потренированы.")
    lines.append("")
    lines.append("Верни ответ строго в JSON, без markdown, без ```json, без комментариев.")
    lines.append("")
    lines.append("Формат JSON:")
    lines.append("{")
    lines.append('  "title": "Название текста",')
    lines.append(f'  "level": "{text_level}",')
    lines.append('  "full_text": "Полный немецкий текст без пропусков.",')
    lines.append('  "summary": "Короткое summary на русском языке.",')
    lines.append('  "items": [')
    lines.append("    {")
    lines.append('      "card_id": "id основной карточки",')
    lines.append('      "word": "исходное немецкое слово из MAIN WORDS",')
    lines.append('      "translation": "перевод",')
    lines.append('      "context": "context или пустая строка",')
    lines.append('      "sentence": "полное предложение без пропуска",')
    lines.append('      "blank_text": "предложение или кусочек текста с ____ вместо ответа",')
    lines.append('      "correct_option": "правильный вариант в нужной форме",')
    lines.append('      "options": ["вариант 1", "вариант 2", "вариант 3", "вариант 4"]')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("")
    lines.append("Важно для options:")
    lines.append("- В options должно быть ровно 4 варианта.")
    lines.append("- Один и только один вариант должен быть правильным.")
    lines.append("- Один из вариантов должен точно совпадать с correct_option.")
    lines.append("- correct_option должен быть единственным вариантом, который подходит по смыслу.")
    lines.append("- Остальные 3 варианта должны быть неправильными по смыслу, даже если грамматически выглядят возможными.")
    lines.append("- Все 4 варианта должны быть в подходящей грамматической форме для этого места в предложении.")
    lines.append("- Варианты должны быть похожи по типу слова, чтобы упражнение выглядело естественно.")
    lines.append("- Не используй дубликаты в options.")
    lines.append("- Не используй варианты, которые могут считаться альтернативно правильными.")
    lines.append("- Перед тем как вернуть результат, проверь, что у каждого вопроса только один однозначно правильный ответ.")
    lines.append("")
    lines.append("MAIN WORDS:")

    for index, card in enumerate(selected_cards, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f'card_id: {card["id"]}')
        lines.append(f'word: {card["word"]}')
        lines.append(f'translation: {card["translation"]}')
        lines.append(f'context: {card["context"] or "—"}')
        lines.append(f'deck: {card["deck"]}')

    lines.append("")
    lines.append("DISTRACTOR WORDS:")

    for index, card in enumerate(distractor_cards, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f'word: {card["word"]}')
        lines.append(f'translation: {card["translation"]}')
        lines.append(f'context: {card["context"] or "—"}')
        lines.append(f'deck: {card["deck"]}')

    return "\n".join(lines)


def extract_json_from_ai_response(raw_text):
    text = (raw_text or "").strip()

    if not text:
        raise ValueError("AI response is empty.")

    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ValueError("Could not find JSON object in AI response.")

    json_text = text[first_brace:last_brace + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def validate_words_context_payload(payload, selected_cards):
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object.")

    title = (payload.get("title") or "").strip()
    level = (payload.get("level") or "").strip()
    full_text = (payload.get("full_text") or "").strip()
    summary = (payload.get("summary") or "").strip()
    items = payload.get("items")

    if not full_text:
        raise ValueError("JSON field full_text is required.")

    if not summary:
        raise ValueError("JSON field summary is required.")

    if not isinstance(items, list) or not items:
        raise ValueError("JSON field items must be a non-empty list.")

    selected_ids = {card["id"] for card in selected_cards}
    cleaned_items = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} must be an object.")

        card_id = str(item.get("card_id") or "").strip()
        word = (item.get("word") or "").strip()
        translation = (item.get("translation") or "").strip()
        context = (item.get("context") or "").strip()
        sentence = (item.get("sentence") or "").strip()
        blank_text = (item.get("blank_text") or "").strip()
        correct_option = (item.get("correct_option") or "").strip()
        options = item.get("options")

        if card_id not in selected_ids:
            raise ValueError(f"Item {index} has unknown card_id: {card_id}")

        if "____" not in blank_text:
            raise ValueError(f"Item {index} blank_text must contain ____.")

        if not correct_option:
            raise ValueError(f"Item {index} correct_option is required.")

        if not isinstance(options, list):
            raise ValueError(f"Item {index} options must be a list.")

        cleaned_options = []

        for option in options:
            option = (str(option) if option is not None else "").strip()

            if option:
                cleaned_options.append(option)

        if len(cleaned_options) != 4:
            raise ValueError(f"Item {index} options must contain exactly 4 options.")

        if not any(
            normalize_option_text(option) == normalize_option_text(correct_option)
            for option in cleaned_options
        ):
            raise ValueError(f"Item {index} options must include correct_option.")

        cleaned_items.append(
            {
                "card_id": card_id,
                "word": word,
                "translation": translation,
                "context": context,
                "sentence": sentence,
                "blank_text": blank_text,
                "correct_option": correct_option,
                "attempted_options": [],
                "options": cleaned_options,
            }
        )

    return {
        "title": title or "Words in context",
        "level": level or "",
        "full_text": full_text,
        "summary": summary,
        "items": cleaned_items,
    }


def build_options_for_item(items, current_index, extra_options=None):
    current_item = items[current_index]

    ai_options = current_item.get("options") or []

    if ai_options:
        return ai_options

    # Fallback на старую логику, если ИИ почему-то не вернул options.
    correct = (current_item["correct_option"] or "").strip()
    current_item["correct_option"] = correct

    extra_options = extra_options or []

    distractors = []
    seen = set()

    def add_distractor(option):
        option = (option or "").strip()

        if not option:
            return

        option_key = normalize_option_text(option)
        correct_key = normalize_option_text(correct)

        if not option_key:
            return

        if option_key == correct_key:
            return

        if option_key in seen:
            return

        seen.add(option_key)
        distractors.append(option)

    for item in items:
        add_distractor(item.get("correct_option", ""))

    for option in extra_options:
        add_distractor(option)

    random.shuffle(distractors)

    options = [correct] + distractors[:3]
    random.shuffle(options)

    current_item["options"] = options

    return options


def is_correct_context_answer(selected_answer, correct_answer):
    return normalize_option_text(selected_answer) == normalize_option_text(correct_answer)

def choose_random_distractor_cards_for_context(user, excluded_card_ids, count=EXTRA_DISTRACTOR_OPTIONS_COUNT):
    cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .exclude(id__in=excluded_card_ids)
        .exclude(question__exact="")
        .exclude(answer__exact="")
    )

    random.shuffle(cards)

    selected = []
    seen = set()

    for card in cards:
        key = normalize_card_text(card.question)

        if not key or key in seen:
            continue

        seen.add(key)
        selected.append(card)

        if len(selected) >= count:
            break

    return selected


def serialize_distractor_options(cards):
    options = []
    seen = set()

    for card in cards:
        option = (card.question or "").strip()
        key = normalize_option_text(option)

        if not option or not key or key in seen:
            continue

        seen.add(key)
        options.append(option)

    return options