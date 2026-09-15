"""M2 retrieval, support-gate, and source-grounding tests.

Fixtures are synthetic and cover the retrieval boundary only.  Model
generation, Telegram, and approved 12+3 evaluation remain later milestones.
"""
from pathlib import Path

from rag_assistant.config import AppConfig
from rag_assistant.domain.types import ChunkData, RetrievalResult, SupportLevel
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.retrieval import (
    Retriever,
    build_grounded_context,
    validate_source_claims,
)
from rag_assistant.retrieval.query import build_fts_match_query, normalize_query
from rag_assistant.storage.index_store import IndexStore


def _build_store(tmp_path: Path, synthetic_docs: Path) -> IndexStore:
    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    result = rebuild_corpus(cfg)
    assert result.success
    return IndexStore(cfg.resolve_index_path())


def test_supported_query_passes_gate_and_returns_metadata(
    tmp_path: Path, synthetic_docs: Path
):
    """AC-011/017 boundary: supported query returns grounded chunks."""
    result = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        "Apa saja metode pembayaran yang diterima?"
    )

    assert result.support_level == SupportLevel.SUFFICIENT
    assert result.chunks
    assert result.corpus_version
    assert result.chunks[0].source_file == "02_FAQ_Pembayaran.md"
    assert result.chunks[0].heading_path


def test_unsupported_query_is_fail_closed(tmp_path: Path, synthetic_docs: Path):
    """AC-012/022 boundary: no lexical support produces no context."""
    result = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        "Bagaimana kebijakan layanan laundry antar kota?"
    )

    assert result.support_level == SupportLevel.INSUFFICIENT
    assert result.chunks == []


def test_partial_term_overlap_does_not_count_as_support(
    tmp_path: Path, synthetic_docs: Path
):
    """AC-012/022: known terms plus an unknown term still abstain."""
    result = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        "metode pembayaran dompet digital"
    )

    assert result.support_level == SupportLevel.INSUFFICIENT
    assert result.chunks == []


def test_ranking_is_stable_and_specific_terms_are_preferred(
    tmp_path: Path, synthetic_docs: Path
):
    """M2 ranking: FTS relevance plus deterministic chunk-id tie-breaker."""
    store = _build_store(tmp_path, synthetic_docs)
    first = store.search("metode pembayaran", limit=5)
    second = store.search("metode pembayaran", limit=5)

    assert [chunk.chunk_id for chunk in first.chunks] == [
        chunk.chunk_id for chunk in second.chunks
    ]
    assert first.chunks[0].source_file == "02_FAQ_Pembayaran.md"


def test_query_operators_and_punctuation_are_not_executed(
    tmp_path: Path, synthetic_docs: Path
):
    """AC-013 boundary: hostile FTS syntax cannot alter search grammar."""
    result = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        '"metode" OR pembayaran; DROP TABLE corpus_chunks'
    )

    assert result.support_level == SupportLevel.INSUFFICIENT
    assert Retriever(_build_store(tmp_path / "second", synthetic_docs)).retrieve(
        "metode pembayaran"
    ).support_level == SupportLevel.SUFFICIENT


def test_empty_or_oversized_query_abstains(tmp_path: Path, synthetic_docs: Path):
    """AC-013/022 boundary: no usable search terms cannot reach context."""
    retriever = Retriever(_build_store(tmp_path, synthetic_docs))

    assert retriever.retrieve("   ?!* ").support_level == SupportLevel.INSUFFICIENT
    assert retriever.retrieve("x" * 2001).support_level == SupportLevel.INSUFFICIENT


def test_grounded_context_derives_sources_from_index_only(
    tmp_path: Path, synthetic_docs: Path
):
    """AC-017: source allowlist is generated from returned chunks."""
    retrieval = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        "metode pembayaran"
    )
    grounded = build_grounded_context(retrieval)

    assert grounded.valid
    assert grounded.context is not None
    assert grounded.context.sources == ("02_FAQ_Pembayaran.md",)

    valid = validate_source_claims(
        "02_FAQ_Pembayaran.md", grounded
    )
    assert valid.valid
    assert valid.accepted_sources == ("02_FAQ_Pembayaran.md",)


def test_source_outside_context_is_rejected(
    tmp_path: Path, synthetic_docs: Path
):
    """AC-018/023 boundary: an invented source invalidates the claim."""
    retrieval = Retriever(_build_store(tmp_path, synthetic_docs)).retrieve(
        "metode pembayaran"
    )
    grounded = build_grounded_context(retrieval)
    validation = validate_source_claims(
        ["02_FAQ_Pembayaran.md", "99_Kebijakan_Palsu.md"], grounded
    )

    assert not validation.valid
    assert validation.accepted_sources == ()
    assert validation.rejected_sources == ("99_Kebijakan_Palsu.md",)


def test_invalid_or_unsupported_context_cannot_allow_source_claims():
    """AC-013/023: source validation fails closed without supported context."""
    result = RetrievalResult(
        support_level=SupportLevel.INSUFFICIENT,
        corpus_version="synthetic-v1",
    )
    grounded = build_grounded_context(result)
    validation = validate_source_claims("02_FAQ_Pembayaran.md", grounded)

    assert not grounded.valid
    assert not validation.valid
    assert validation.accepted_sources == ()


def test_query_normalization_has_no_fts_operators():
    """The normalized query is deterministic and grammar-free."""
    normalized = normalize_query('"Metode" OR pembayaran -cuti')
    built = build_fts_match_query(normalized.terms)

    assert normalized.terms == ("metode", "pembayaran", "cuti")
    assert '"metode"' in built
    assert " OR " in built
    assert "-cuti" not in built


def test_mismatched_corpus_version_invalidates_context():
    """Context chunks must all belong to the active retrieval version."""
    result = RetrievalResult(
        chunks=[
            ChunkData(
                chunk_id="chunk-1",
                text="Metode pembayaran.",
                source_file="02_FAQ_Pembayaran.md",
                heading_path="FAQ > Pembayaran",
                corpus_version="old-version",
            )
        ],
        support_level=SupportLevel.SUFFICIENT,
        corpus_version="active-version",
    )

    grounded = build_grounded_context(result)

    assert not grounded.valid
    assert grounded.reason == "invalid_context_chunk"
