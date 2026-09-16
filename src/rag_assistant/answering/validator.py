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

import re
from dataclasses import dataclass

from rag_assistant.answering.prompts import ABSTENTION_TEXT, SOURCE_LINE_PREFIX
from rag_assistant.domain.types import AnswerResult
from rag_assistant.retrieval.grounding import (
    GroundedContext,
    validate_source_claims,
)

# The prompt asks for the source on its own line, and the line-start check runs
# first so a compliant model is parsed exactly as before.  Local models often
# emit the marker inline instead ("12 hari per tahun. SUMBER: doc.md"); that is
# a formatting variance, not a grounding failure, so a fallback accepts the
# final inline marker.  Grounding is unchanged either way: every claimed source
# is still validated against the context, so a fake source can never pass.
_INLINE_SOURCE_RE = re.compile(
    re.escape(SOURCE_LINE_PREFIX), re.IGNORECASE
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
    """Return source names from every ``SUMBER:`` marker, in first-seen order.

    Line-start markers are preferred (the documented output contract).  When a
    model emits the marker inline on the same line as the answer body, the
    trailing marker is used as a fallback so a formatting slip does not discard
    an otherwise correctly grounded answer.
    """
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
    if claimed:
        return tuple(claimed)
    return _claimed_sources_inline(answer_text)


def strip_source_line(answer_text: str) -> str:
    """Return the answer body without any ``SUMBER:`` marker.

    A line that is entirely a marker is dropped; an inline marker is truncated
    so the citation does not remain glued to the answer body.
    """
    kept: list[str] = []
    for raw in answer_text.splitlines():
        if raw.strip().upper().startswith(SOURCE_LINE_PREFIX):
            continue
        kept.append(_INLINE_SOURCE_RE.split(raw)[0].rstrip())
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


def _claimed_sources_inline(text: str) -> tuple[str, ...]:
    """Return sources from a trailing inline ``SUMBER:`` marker, if any.

    Only the text after the *last* marker is considered, so an answer body that
    happens to mention the word earlier cannot be mistaken for a citation list.
    The result still passes through :func:`validate_source_claims`, so an
    out-of-context name is rejected exactly as a line-start claim would be.
    """
    matches = list(_INLINE_SOURCE_RE.finditer(text))
    if not matches:
        return ()
    remainder = text[matches[-1].end():]
    return _split_sources(remainder.splitlines()[0] if remainder else "")
