"""Contract tests for the model-dependent retrieval knob (ADR-002).

``context_limit`` is the one retrieval parameter whose best value depends on the
answering model, so ADR-002 surfaces it as ``RAG_CONTEXT_LIMIT`` and keeps the
rest frozen.  These tests hold both halves of that decision in place:

* an unset variable must reproduce the approved ``context_limit=5`` baseline
  exactly, otherwise every approved M2/M5 measurement stops being reproducible;
* the support gate must stay unreachable from the environment, because a wrong
  ``min_coverage`` makes the system answer questions it should abstain on, and
  that failure is silent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_assistant.config import _OPTIONAL_DEFAULTS, load_config
from rag_assistant.retrieval.service import (
    DEFAULT_CONTEXT_LIMIT,
    RetrievalPolicy,
    build_retrieval_policy,
)

#: Retrieval parameters that decide whether a question may be answered at all.
#: None of these may ever be settable from the environment.
FROZEN_POLICY_FIELDS = (
    "candidate_limit",
    "min_matched_terms",
    "min_coverage",
    "min_single_term_length",
)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_CONTEXT_LIMIT", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DOCS_PATH", "docs")
    monkeypatch.setenv("INDEX_PATH", ".runtime/index.sqlite3")


def test_default_matches_the_approved_baseline():
    """The calibrated default is 5: the value every approved measurement used."""
    assert DEFAULT_CONTEXT_LIMIT == 5
    assert RetrievalPolicy().context_limit == 5


def test_unset_variable_reproduces_the_approved_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An unset knob must be indistinguishable from the pre-ADR-002 behaviour."""
    _base_env(monkeypatch)

    cfg = load_config(tmp_path)

    assert cfg.rag_context_limit == DEFAULT_CONTEXT_LIMIT
    assert build_retrieval_policy(cfg.rag_context_limit) == RetrievalPolicy()


def test_configured_value_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A configured breadth reaches the policy, so ganti model = ganti .env."""
    _base_env(monkeypatch)
    monkeypatch.setenv("RAG_CONTEXT_LIMIT", "2")

    cfg = load_config(tmp_path)

    assert cfg.rag_context_limit == 2
    assert build_retrieval_policy(cfg.rag_context_limit).context_limit == 2


def test_blank_value_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A blank line is not "unset": it is rejected by name, like other int keys.

    ``TELEGRAM_POLL_TIMEOUT_SECONDS`` and ``LLM_TIMEOUT_SECONDS`` already behave
    this way, so following them keeps one convention for integer keys instead of
    inventing a second.  Removing or commenting the line is how the default is
    selected.
    """
    _base_env(monkeypatch)
    monkeypatch.setenv("RAG_CONTEXT_LIMIT", "")

    with pytest.raises(SystemExit):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["0", "-1", "banyak", "2.5"])
def test_invalid_value_stops_before_any_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
):
    """A non-positive or non-integer breadth is a config error, not a default."""
    _base_env(monkeypatch)
    monkeypatch.setenv("RAG_CONTEXT_LIMIT", value)

    with pytest.raises(SystemExit):
        load_config(tmp_path)


def test_knob_cannot_move_the_support_gate():
    """The knob exposes exactly one field; the gate stays frozen in code.

    Exposing ``min_coverage`` (or the term thresholds) through the environment
    would let a typo change which questions are answerable, which invalidates
    the approved M2 baseline silently.  ADR-002 rules that out.
    """
    configured = build_retrieval_policy(2)

    defaults = RetrievalPolicy()
    for field in FROZEN_POLICY_FIELDS:
        assert getattr(configured, field) == getattr(defaults, field), field

    for field in FROZEN_POLICY_FIELDS:
        assert field.upper() not in _OPTIONAL_DEFAULTS
        assert f"RAG_{field.upper()}" not in _OPTIONAL_DEFAULTS


def test_no_other_retrieval_key_is_configurable():
    """Only RAG_CONTEXT_LIMIT exists among retrieval keys."""
    retrieval_keys = {k for k in _OPTIONAL_DEFAULTS if k.startswith("RAG_")}
    assert retrieval_keys == {"RAG_CONTEXT_LIMIT"}
