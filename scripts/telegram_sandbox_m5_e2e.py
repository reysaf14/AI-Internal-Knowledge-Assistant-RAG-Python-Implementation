"""Live Telegram sandbox E2E for the *full* approved 12+3 eval set (M5).

Closes the gap the 3-question smoke test leaves open.  ``telegram_sandbox_e2e.py``
proves the sandbox path works on three messages and emits delivery counters; it
does not score content, sources, or abstention per row, so it cannot produce the
evidence ``AC-027``..``AC-031`` require.  This script drives the same real
``PtbTelegramClient`` boundary and the same real ``TelegramPoller`` over all 15
approved rows and scores each one against the approved rubric.

Reused rather than reimplemented
--------------------------------
The boundary wrapper, the one-iteration-at-a-time collector, the model prewarm,
and the chat-id cache all come from ``telegram_sandbox_e2e`` by import.  That
machinery was debugged against live traffic and each piece of it encodes a
failure that was actually observed -- notably that a *second bot* can never be
the sender (Telegram does not deliver messages from one bot to another), so a
human must type the questions.  Duplicating it here would fork that knowledge.

Why a human types the questions
-------------------------------
Same reason as the smoke test: Telegram never delivers a bot's message to
another bot, so the only actor whose traffic the application bot can observe is
a person.  The script prints the 15 questions in order and measures what arrives.

Correctness of the match
------------------------
Updates are matched to questions in ascending ``update_id`` order, which is the
order they were printed and the order a human types them.  That assumption is
not left implicit: if a message's cited source matches a *different* row's
expected source, the run reports ``ORDER_WARN`` naming the rows, so a shuffled
typing order surfaces as a warning instead of as a silent misscore.

No secret is printed: only counts, coarse status, document filenames from the
grounded answer contract, and the approved synthetic questions themselves.

Run it directly (``python scripts/telegram_sandbox_m5_e2e.py``).  Python then
puts ``scripts/`` on ``sys.path[0]``, which is what makes the sibling imports
(``run_candidate_eval``, ``telegram_sandbox_e2e``) resolve without a path insert.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from candidate_rubric import (
    OutcomeRow,
    outcomes_meet_targets,
    summarize_outcomes,
)
from run_candidate_eval import _cases
from telegram_sandbox_e2e import (
    CHAT_ID_CACHE,
    DEFAULT_WAIT_SECONDS,
    POLL_TIMEOUT_SECONDS,
    TimingBoundary,
    _collect,
    _pending_count,
    _prewarm_model,
    _read_cached_chat_id,
    _sanitize,
    _say,
    _write_cached_chat_id,
)

from rag_assistant.answering.prompts import ABSTENTION_TEXT
from rag_assistant.answering.service import build_answer_service
from rag_assistant.answering.validator import (
    extract_claimed_sources,
    strip_source_line,
)
from rag_assistant.config import load_config, load_operator_env
from rag_assistant.evaluation.runner import source_credit_pass
from rag_assistant.retrieval.service import Retriever, build_retrieval_policy
from rag_assistant.storage.index_store import IndexStore
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.poller import TelegramPoller
from rag_assistant.telegram.ptb_client import PtbTelegramClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path("eval/QA_Dataset_12_3_candidate.csv")


def _score_observations(cases, boundary: TimingBoundary, expected: int) -> int:
    """Score each received answer against its row and print the evidence.

    Presentation, not collection, is the difference from the smoke test: the
    per-row verdict here is exactly the one ``LocalEvaluationRunner`` computes,
    including the shared :func:`source_credit_pass` predicate, so a sandbox run
    and a local run agree on what a correct answer is.
    """
    received_ids = sorted(boundary.received)
    if len(received_ids) != expected:
        _say(f"FAIL=updates_received({len(received_ids)}) != expected({expected})")

    # Maps each expected source to the rows that legitimately cite it, so a
    # citation that belongs to another row can be reported as an ordering fault.
    allowed_by_source: dict[str, list[str]] = {}
    for case in cases:
        for source in case.expected_sources:
            allowed_by_source.setdefault(source, []).append(case.case_id)

    rows: list[OutcomeRow] = []
    order_warnings = 0

    for index, uid in enumerate(received_ids):
        case = cases[index] if index < len(cases) else None
        bodies = boundary.messages.get(uid, [])
        body = bodies[0] if bodies else ""
        latency_ms = None
        if uid in boundary.sent:
            latency_ms = (boundary.sent[uid] - boundary.received[uid]) * 1000
        latency_pass = latency_ms is not None and latency_ms < 5000.0

        if case is None:
            _say(f"update={uid}|UNMAPPED (more updates than questions)")
            continue

        sources = extract_claimed_sources(body)
        abstained = body.strip() == ABSTENTION_TEXT
        observed_supported = bool(sources) and not abstained
        text_body = strip_source_line(body).casefold()

        if case.expected_supported:
            content_ok = observed_supported and all(
                term.casefold() in text_body for term in case.expected_answer_terms
            )
            source_ok = source_credit_pass(sources, case.expected_sources)
            abstention_ok = observed_supported
        else:
            content_ok = abstained and not sources
            source_ok = not sources
            abstention_ok = abstained and not sources

        # A citation that would have been correct for a *different* row means the
        # human typed out of order; saying so keeps a shuffled run from being read
        # as a set of model failures.
        if not source_ok and sources:
            belongs_to = sorted(
                {
                    other
                    for source in sources
                    for other in allowed_by_source.get(source, [])
                    if other != case.case_id
                }
            )
            if belongs_to:
                order_warnings += 1
                _say(
                    f"ORDER_WARN update={uid} mapped_to={case.case_id}"
                    f" but cited sources belong to {','.join(belongs_to)}"
                )

        rows.append(
            OutcomeRow(
                case_id=case.case_id,
                expected_supported=case.expected_supported,
                content_ok=content_ok,
                source_ok=source_ok,
                abstention_ok=abstention_ok,
                latency_ok=latency_pass,
                response_count=len(bodies),
            )
        )

        lat = f"{latency_ms:.0f}ms" if latency_ms is not None else "none"
        failures = [
            name
            for name, ok in (
                ("content", content_ok),
                ("source", source_ok),
                ("abstention", abstention_ok),
                ("latency", latency_pass),
            )
            if not ok
        ]
        _say(
            f"{case.case_id}|responses={len(bodies)}|supported={case.expected_supported}|"
            f"content={content_ok}|source={source_ok}|abstention={abstention_ok}|"
            f"latency={lat}|failures={','.join(failures) or 'none'}"
        )

    summary = summarize_outcomes(tuple(rows))
    _say(f"content={summary.content_passed}/{summary.total}")
    _say(
        f"supported_content={summary.supported_content_passed}"
        f"/{summary.expected_supported}"
    )
    _say(f"sources={summary.source_passed}/{summary.expected_supported}")
    _say(f"abstention={summary.abstention_passed}/{summary.expected_unsupported}")
    _say(f"latency_within_5s={summary.latency_passed}/{summary.total}")
    _say(f"sent={summary.responses_sent} duplicates={summary.duplicates}")
    if order_warnings:
        _say(f"order_warnings={order_warnings}")
    _say("verification_level=telegram-sandbox")

    complete = len(received_ids) == len(cases) and order_warnings == 0
    if complete and outcomes_meet_targets(summary):
        _say("acceptance_verdict=PASS")
    else:
        _say("acceptance_verdict=FAIL (see failures above)")
    return 0


def _main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="approved 12+3 candidate set (default: %(default)s)",
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        default=0,
        help="Target group id; defaults to the cached id, else live discovery",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help="How long to wait for the operator's questions (default: %(default)s)",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    load_operator_env(root)
    cfg = load_config(root)

    if not cfg.telegram_bot_token:
        _say("bot_a_token_present=False")
        _say("ACTION=set TELEGRAM_BOT_TOKEN in .env, then re-run")
        return 4

    dataset = (root / args.dataset).resolve()
    if not dataset.is_relative_to(root) or not dataset.is_file():
        _say(f"dataset_unusable={_sanitize(str(args.dataset))}")
        return 4
    cases = _cases(dataset, cfg.resolve_docs_path())
    expected = len(cases)
    if expected != 15:
        _say(f"dataset_shape_unexpected rows={expected} expected=15")
        return 4

    if IndexStore(cfg.resolve_index_path()).get_index_info() is None:
        _say("active_index=unavailable (run the rebuild entry point first)")
        return 4

    bot_a = PtbTelegramClient(
        token=cfg.telegram_bot_token,
        poll_timeout_seconds=cfg.telegram_poll_timeout,
        request_timeout_seconds=cfg.telegram_request_timeout,
    )

    _say("== phase1 getMe ==")
    try:
        bot_a.get_updates(offset=0, timeout_seconds=1)
        _say("bot_a_reachable=True")
    except Exception as exc:  # noqa: BLE001 - surface category only
        _say(f"bot_a_reachable=False category={type(exc).__name__}")
        return 1

    _say("== phase2 target chat ==")
    chat_id = args.chat_id or _read_cached_chat_id(root)
    if not chat_id:
        _say("chat_found=False")
        _say("ALT=pass the group id directly, or run telegram_sandbox_e2e.py once")
        _say(f"     to discover it (cache path: {CHAT_ID_CACHE})")
        return 4
    state_dir = root / ".runtime"
    state_dir.mkdir(exist_ok=True)
    state_store = StateStore(state_dir / "sandbox-e2e-state.sqlite3")
    _write_cached_chat_id(root, chat_id)
    _say(f"chat_found=True kind={'group' if chat_id < 0 else 'private'}")
    _say("drain=skipped (operator traffic must survive)")

    _say("== phase2b model warmup ==")
    _prewarm_model(cfg)

    seed = state_store.get_polling_offset()
    state_store.set_polling_offset(seed)
    _say(f"offset_seeded={seed}")

    _say("== phase3 live e2e (full 12+3) ==")
    _say(f"expected_updates={expected}")
    for index, case in enumerate(cases, start=1):
        _say(f"ask_{index}={case.question}")
    _say(f"ACTION=send those {expected} messages into the chat now, IN THIS ORDER")

    boundary = TimingBoundary(bot_a, expected_chat_id=chat_id)

    def build_poller() -> TelegramPoller:
        return TelegramPoller(
            boundary=boundary,
            state_store=state_store,
            retriever=Retriever(
                IndexStore(cfg.resolve_index_path()),
                policy=build_retrieval_policy(cfg.rag_context_limit),
            ),
            answer_service=build_answer_service(cfg),
            poll_timeout_seconds=POLL_TIMEOUT_SECONDS,
            max_question_chars=cfg.max_question_chars,
            max_iterations=1,
        )

    counters = _collect(
        build_poller,
        boundary,
        expected,
        args.wait_seconds,
        pending_probe=lambda: _pending_count(cfg.telegram_bot_token),
    )

    _say(f"end_of_run pending_at_telegram={_pending_count(cfg.telegram_bot_token)}")
    _say(f"updates={counters['updates']} delivered={counters['answers_delivered']}")
    _say(f"duplicates={counters['duplicates']} rejected={counters['rejected']}")
    _say(
        f"sends_failed={counters['sends_failed']}"
        f" sends_unknown={counters['sends_unknown']}"
    )
    _say(f"poll_failures={counters['poll_failures']}")
    _say(f"context_limit={cfg.rag_context_limit}")
    if boundary.off_target:
        _say(
            f"FAIL=answered_wrong_chat updates={boundary.off_target}; a private"
            " message reaches the same bot, so the group run is void"
        )
    if counters["updates"] != expected:
        _say(
            f"WARN=updates({counters['updates']}) != expected({expected}); the"
            " operator sent a different number of messages"
        )

    return _score_observations(cases, boundary, expected)


if __name__ == "__main__":
    raise SystemExit(_main())
