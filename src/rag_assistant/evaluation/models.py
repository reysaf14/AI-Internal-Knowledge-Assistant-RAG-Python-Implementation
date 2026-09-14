"""Data contracts for M5 evaluation evidence.

The model deliberately stores aggregate outcomes and technical metadata only.
It does not persist questions, answers, chat identities, or raw provider
payloads.  An approved evaluator may keep the answer key in memory while a
run is active, but the resulting evidence is safe to hand off.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvaluationCase:
    """One approved-rubric case supplied to the evaluator at runtime."""

    case_id: str
    question: str
    expected_supported: bool
    expected_sources: tuple[str, ...] = ()
    expected_answer_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if self.expected_supported and not self.expected_sources:
            raise ValueError("supported cases need at least one expected source")
        if self.expected_supported and not self.expected_answer_terms:
            raise ValueError("supported cases need answer terms")
        if not self.expected_supported and (
            self.expected_sources or self.expected_answer_terms
        ):
            raise ValueError("unsupported cases cannot carry answer or source claims")


@dataclass(frozen=True)
class EvaluationObservation:
    """Sanitized result for one case; raw message content is intentionally absent."""

    case_id: str
    expected_supported: bool
    observed_supported: bool
    observed_abstained: bool
    observed_sources: tuple[str, ...]
    send_outcome: str
    response_count: int
    received_at_epoch_ms: int | None
    sent_at_epoch_ms: int | None
    latency_ms: float | None
    content_pass: bool
    source_pass: bool
    abstention_pass: bool
    latency_pass: bool
    failure_categories: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EvaluationSummary:
    """Aggregate M5 evidence and the honest acceptance verdict."""

    total: int
    expected_supported: int
    expected_unsupported: int
    content_passed: int
    supported_content_passed: int
    source_passed: int
    abstention_passed: int
    latency_passed: int
    responses_sent: int
    duplicate_responses: int
    verification_level: str
    acceptance_verdict: str
    observations: tuple[EvaluationObservation, ...] = field(default_factory=tuple)

    @property
    def metric_targets_match(self) -> bool:
        """Whether the input shape and all per-case metrics match M5 targets."""
        return (
            self.total == 15
            and self.expected_supported == 12
            and self.expected_unsupported == 3
            and self.supported_content_passed >= self.expected_supported
            and self.source_passed == self.expected_supported
            and self.abstention_passed == self.expected_unsupported
            and self.latency_passed == self.total
            and self.responses_sent == self.total
            and self.duplicate_responses == 0
        )
