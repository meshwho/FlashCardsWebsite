from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.forms import formset_factory
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib.auth import get_user_model
from .models import Card, Deck, UserReviewSchedule
from .card_duplicates import normalize_card_text


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label="Email",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()

        if not email:
            raise forms.ValidationError("Email is required.")

        User = get_user_model()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")

        return email


class DeckForm(forms.ModelForm):
    class Meta:
        model = Deck
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Enter deck title",
                    "class": "deck-title-input",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_title(self):
        title = (self.cleaned_data["title"] or "").strip()

        if not self.user:
            return title

        queryset = Deck.objects.filter(owner=self.user, title=title)

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError("You already have a deck with this title.")

        return title


class CardForm(forms.ModelForm):
    class Meta:
        model = Card
        fields = ["question", "context", "answer", "has_article"]
        widgets = {
            "question": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Enter term / question",
                    "class": "card-input",
                }
            ),
            "context": forms.TextInput(
                attrs={
                    "placeholder": "Optional context, e.g. finance, river, noun, verb",
                    "class": "card-input",
                }
            ),
            "answer": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Enter definition / answer",
                    "class": "card-input",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        question = (cleaned_data.get("question") or "").strip()
        context = (cleaned_data.get("context") or "").strip()
        answer = (cleaned_data.get("answer") or "").strip()

        cleaned_data["question"] = question
        cleaned_data["context"] = context
        cleaned_data["answer"] = answer

        if not question and not answer and not context:
            return cleaned_data

        if question and not answer:
            self.add_error("answer", "Answer is required if question is filled.")

        if answer and not question:
            self.add_error("question", "Question is required if answer is filled.")

        return cleaned_data



    def clean(self):
        cleaned_data = super().clean()

        question = (cleaned_data.get("question") or "").strip()
        answer = (cleaned_data.get("answer") or "").strip()

        if not question and not answer:
            return cleaned_data

        if question and not answer:
            self.add_error("answer", "Answer is required if question is filled.")

        if answer and not question:
            self.add_error("question", "Question is required if answer is filled.")

        return cleaned_data


class AmbiguousCardContextForm(forms.Form):
    card_id = forms.UUIDField(widget=forms.HiddenInput)
    context = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "card-input",
                "placeholder": "Add context, e.g. finance, river, noun, verb",
            }
        ),
    )

class BaseCardInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        if any(self.errors):
            return

        active_items = []
        deleted_ids = set()

        for form in self.forms:
            cleaned_data = getattr(form, "cleaned_data", None) or {}

            if cleaned_data.get("DELETE"):
                if form.instance and form.instance.pk:
                    deleted_ids.add(form.instance.pk)
                continue

            question = cleaned_data.get("question")
            answer = cleaned_data.get("answer")

            if not question and not answer:
                continue

            question_norm = normalize_card_text(question)
            answer_norm = normalize_card_text(answer)

            if not question_norm or not answer_norm:
                continue

            active_items.append({
                "form": form,
                "card_id": form.instance.pk if form.instance and form.instance.pk else None,
                "question_norm": question_norm,
                "answer_norm": answer_norm,
            })

        self._validate_exact_duplicates_inside_formset(active_items)
        self._validate_exact_duplicates_against_database(active_items, deleted_ids)

    def _validate_exact_duplicates_inside_formset(self, active_items):
        seen = {}

        for item in active_items:
            key = (item["question_norm"], item["answer_norm"])

            if key in seen:
                item["form"].add_error(
                    None,
                    "This exact card already appears in this deck. "
                    "Duplicate cards with the same question and answer are not allowed.",
                )
                seen[key]["form"].add_error(
                    None,
                    "This exact card already appears in this deck. "
                    "Duplicate cards with the same question and answer are not allowed.",
                )
            else:
                seen[key] = item

    def _validate_exact_duplicates_against_database(self, active_items, deleted_ids):
        owner = getattr(self.instance, "owner", None)

        if owner is None:
            return

        current_form_ids = {
            item["card_id"]
            for item in active_items
            if item["card_id"] is not None
        }

        excluded_ids = current_form_ids | deleted_ids

        existing_cards = (
            Card.objects
            .filter(deck__owner=owner)
            .select_related("deck")
            .only("id", "question", "answer", "deck__title")
        )

        if excluded_ids:
            existing_cards = existing_cards.exclude(pk__in=excluded_ids)

        existing_items = []

        for card in existing_cards:
            existing_items.append({
                "card": card,
                "question_norm": normalize_card_text(card.question),
                "answer_norm": normalize_card_text(card.answer),
            })

        for item in active_items:
            for existing in existing_items:
                same_question = item["question_norm"] == existing["question_norm"]
                same_answer = item["answer_norm"] == existing["answer_norm"]

                if same_question and same_answer:
                    item["form"].add_error(
                        None,
                        (
                            "This exact card already exists in deck "
                            f'"{existing["card"].deck.title}". '
                            "Duplicate cards with the same question and answer are not allowed."
                        ),
                    )
                    break


CardInlineFormSet = inlineformset_factory(
    parent_model=Deck,
    model=Card,
    form=CardForm,
    formset=BaseCardInlineFormSet,
    fields=["question", "context", "answer", "has_article"],
    extra=1,
    can_delete=True,
)

class ReviewScheduleForm(forms.ModelForm):
    reviews_per_day = forms.IntegerField(
        min_value=1,
        max_value=10,
        label="Reviews per day",
        widget=forms.NumberInput(attrs={
            "class": "number-input",
            "inputmode": "numeric",
            "min": "1",
            "max": "10",
            "step": "1",
        }),
    )

    class Meta:
        model = UserReviewSchedule
        fields = ["timezone", "is_active"]

    def __init__(self, *args, **kwargs):
        slots_count = kwargs.pop("slots_count", 3)

        if args:
            data = args[0]
            args = args[1:]
        else:
            data = kwargs.pop("data", None)

        if data is not None:
            data = data.copy()

            raw_reviews_per_day = data.get("reviews_per_day", slots_count)

            try:
                reviews_per_day = int(raw_reviews_per_day)
            except (TypeError, ValueError):
                reviews_per_day = slots_count

            reviews_per_day = max(1, min(reviews_per_day, 10))
            data["reviews_per_day"] = str(reviews_per_day)

            if args:
                args = (data, *args)
            else:
                kwargs["data"] = data

        super().__init__(*args, **kwargs)

        self.fields["reviews_per_day"].initial = slots_count

        self.fields["timezone"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Europe/Kyiv",
        })

    def clean_timezone(self):
        timezone_name = self.cleaned_data.get("timezone")

        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise forms.ValidationError("Enter a valid IANA timezone name.")

        return timezone_name


class ReviewSlotForm(forms.Form):
    time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
        label="",
    )


ReviewSlotFormSet = formset_factory(
    ReviewSlotForm,
    extra=0,
    min_num=1,
    validate_min=True,
)

class SentencePracticeForm(forms.Form):
    def __init__(self, *args, sentence_count=1, **kwargs):
        super().__init__(*args, **kwargs)

        for i in range(sentence_count):
            self.fields[f"sentence_{i+1}"] = forms.CharField(
                label=f"Sentence {i+1}",
                widget=forms.Textarea(
                    attrs={
                        "rows": 2,
                        "placeholder": "Write a sentence with this word",
                    }
                ),
            )

class PracticeOptionsForm(forms.Form):
    require_sentences_after_mistake = forms.BooleanField(
        required=False,
        initial=False,
        label="Require sentence after mistake",
    )
