from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.forms import BaseInlineFormSet, inlineformset_factory
from .models import Card, Deck
from datetime import time
from django.forms import formset_factory
from .models import ReviewSlot, UserReviewSchedule

class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


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
    fields=["question", "answer"],
    extra=1,
    can_delete=True,
)

class ReviewScheduleForm(forms.ModelForm):
    reviews_per_day = forms.IntegerField(
        min_value=1,
        max_value=10,
        initial=3,
        label="Reviews per day",
    )

    class Meta:
        model = UserReviewSchedule
        fields = ["timezone", "is_active"]
        widgets = {
            "timezone": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        slots_count = kwargs.pop("slots_count", 3)
        super().__init__(*args, **kwargs)
        self.fields["reviews_per_day"].initial = slots_count


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