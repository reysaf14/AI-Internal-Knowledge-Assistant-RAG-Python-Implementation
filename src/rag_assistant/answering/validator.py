"""Answer validator: enforces the grounding contract on model output.

Fail-closed rules.  A response is presented as a supported answer only when it
cites at least one source that exists in the *validated* retrieval context:

* empty output -> abstain
* no source line -> abstain
* any claimed source outside the context -> abstain (fake sources never pass)
* supported answer with an empty body -> abstain

Every abstention returns the canonical :data:`ABSTENTION_TEXT` with no sources,
so a rejected or failed answer can never be mistaken for a sourced policy answer.
"""
from __future__ import annotations

from dataclasses import dataclass

from rag_assistant.answering.prompts import ABSTENTION_TEXT, SOURCE_LINE_PREFIX
from rag_assistant.domain.types import AnswerResult
from rag_assistant.retrieval.grounding import (
    GroundedContext,
    validate_source_claims,
)

ABSTENTION_MARKERS = (
    "tidak menemukan",
    "tidak tahu",
    "tidak ada informasi",
    "tidak cukup",
    "tidak dapat menjawab",
    "tidak ditemukan",
    "belum ada informasi",
)


@dataclass(frozen=True)
class ValidatedAnswer:
    """Outcome of validating one model response against its context."""

    result: AnswerResult
    reason: str


def extract_claimed_sources(answer_text: str) -> tuple[str, ...]:
    """Return source names from every ``SUMBER:`` line, in first-seen order."""
    claimed: list[str] = []
    seen: set[str] = set()
    for raw_line in answer_text.splitlines():
        line = raw_line.strip()
        if line.upper().startswith(SOURCE_LINE_PREFIX):
            remainder = line[len(SOURCE_LINE_PREFIX):]
            for token in _split_sources(remainder):
                if token not in seen:
                    seen.add(token)
                    claimed.append(token)
    return tuple(claimed)


def strip_source_line(answer_text: str) -> str:
    """Return the answer body without any ``SUMBER:`` line."""
    kept = [
        raw
        for raw in answer_text.splitlines()
        if not raw.strip().upper().startswith(SOURCE_LINE_PREFIX)
    ]
    return "\n".join(kept).strip()


def validate_model_answer(
    answer_text: str, context: GroundedContext
) -> ValidatedAnswer:
    """Validate one model response and return a safe, sourced answer or abstention."""
    text = (answer_text or "").strip()
    if not text:
        return _abstain("empty_model_output")

    claims = extract_claimed_sources(text)
    if not claims:
        reason = "model_abstained" if _looks_like_abstention(text) else "no_source_claim"
        return _abstain(reason)

    validation = validate_source_claims(claims, context)
    if not validation.valid:
        return _abstain(validation.reason)

    body = strip_source_line(text)
    if not body:
        return _abstain("empty_answer_body")

    return ValidatedAnswer(
        result=AnswerResult(
            text=body,
            sources=list(validation.accepted_sources),
            supported=True,
            abstained=False,
        ),
        reason="grounded_answer",
    )


def _abstain(reason: str) -> ValidatedAnswer:
    return ValidatedAnswer(
        result=AnswerResult(
            text=ABSTENTION_TEXT,
            sources=[],
            supported=False,
            abstained=True,
        ),
        reason=reason,
    )


def _looks_like_abstention(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in ABSTENTION_MARKERS)


def _split_sources(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for part in value.replace(";", ",").split(","):
        cleaned = part.strip().strip("`*-\"'\u2022").strip()
        if cleaned:
            tokens.append(cleaned)
    return tuple(tokens)
