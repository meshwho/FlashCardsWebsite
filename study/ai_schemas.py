from typing import List

from pydantic import BaseModel, Field


class SentenceProblem(BaseModel):
    sentence_number: int = Field(
        description="Number of the sentence starting from 1."
    )
    original_sentence: str = Field(
        description="Original sentence written by the user."
    )
    corrected_sentence: str = Field(
        description="Corrected German sentence."
    )
    what_was_wrong: List[str] = Field(
        description="Clear list of mistakes in Russian."
    )
    why_it_is_wrong: List[str] = Field(
        description="Explanation why these are mistakes in Russian."
    )
    how_to_avoid: List[str] = Field(
        description="Practical advice for avoiding similar mistakes in Russian."
    )
    is_acceptable_but_more_natural: bool = Field(
        default=False,
        description="True if the original sentence is acceptable but another version sounds more natural."
    )


class SentenceCheckResult(BaseModel):
    all_ok: bool = Field(
        description="True if all submitted sentences are correct."
    )
    short_message: str = Field(
        description="Short friendly summary in Russian."
    )
    problems: List[SentenceProblem] = Field(
        description="List of problems. Empty if all_ok is true."
    )