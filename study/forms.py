from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.forms import formset_factory
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib.auth import get_user_model
from .models import Card, Deck, UserReviewSchedule

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
        fields = ["question", "answer", "has_article"]
        widgets = {
            "question": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Enter term / question",
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
        answer = (cleaned_data.get("answer") or "").strip()

        if not question and not answer:
            return cleaned_data

        if question and not answer:
            self.add_error("answer", "Answer is required if question is filled.")

        if answer and not question:
            self.add_error("question", "Question is required if answer is filled.")

        return cleaned_data


class BaseCardInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()


CardInlineFormSet = inlineformset_factory(
    parent_model=Deck,
    model=Card,
    form=CardForm,
    formset=BaseCardInlineFormSet,
    fields=["question", "answer", "has_article"],
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
