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


class WordUsageExample(BaseModel):
    german: str = Field(
        description="A natural German example sentence using the word."
    )
    translation: str = Field(
        description="Russian translation of the German example sentence."
    )


class WordUsageResult(BaseModel):
    canonical_form: str = Field(
        description="Dictionary form of the German word or expression."
    )
    part_of_speech: str = Field(
        description="Part of speech, explained briefly in Russian."
    )
    meaning: str = Field(
        description="Meaning and important nuances, explained in Russian."
    )
    grammar_and_position: List[str] = Field(
        description="Grammar, government, and sentence-position rules in Russian."
    )
    common_collocations: List[str] = Field(
        description="Common German collocations with short Russian explanations."
    )
    fixed_expressions: List[str] = Field(
        description="Common fixed expressions with short Russian explanations."
    )
    examples: List[WordUsageExample] = Field(
        description="Natural German examples with Russian translations."
    )
    important_notes: List[str] = Field(
        description="Register, common mistakes, and easily confused words in Russian."
    )
